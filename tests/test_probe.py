import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from addon_scope.models import Addon
from addon_scope.probe import ProbeResult, ProbeSpec, _environment, minimize, run_probe
from addon_scope.probe_script import _failure_key, _module_file


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "example"
        self.source.mkdir()
        (self.source / "__init__.py").write_text("def register(): pass\ndef unregister(): pass\n")
        self.addon = Addon("example", "Example", str(self.source), module="example", kind="legacy")

    def spec(self, **kwargs):
        return ProbeSpec(sys.executable, [self.addon], **kwargs)

    def fake_process(self, payload=None, *, returncode=0, phase=None, inspect=None):
        class FakeProcess:
            pid = 12345678

            def __init__(inner, command, **kwargs):
                inner.returncode = returncode
                job_path = Path(command[-1])
                job = json.loads(job_path.read_text())
                if inspect:
                    inspect(command, kwargs, job)
                if payload:
                    Path(job["result"]).write_text(json.dumps(payload))
                if phase:
                    Path(job["phase"]).write_text(json.dumps(phase))
                kwargs["stdout"].write(b"Blender diagnostic output\n")

            def wait(inner, timeout=None):
                return inner.returncode

        return FakeProcess

    def test_copies_source_and_uses_disposable_paths(self):
        original = (self.source / "__init__.py").read_bytes()

        def inspect(command, kwargs, job):
            self.assertIn("--factory-startup", command)
            self.assertIn("--offline-mode", command)
            self.assertIn("--disable-autoexec", command)
            self.assertNotIn("shell", kwargs)
            profile = Path(kwargs["cwd"])
            copy = profile / "scripts/addons/example/__init__.py"
            self.assertEqual(copy.read_bytes(), original)
            copy.write_text("changed only the copy")
            self.assertNotEqual(profile, self.root)
            self.assertEqual(kwargs["env"]["BLENDER_USER_CONFIG"], str(profile / "config"))
            for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
                        "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
                        "TMPDIR", "TEMP", "TMP"):
                location = Path(kwargs["env"][key])
                self.assertTrue(location.is_dir(), key)
                self.assertTrue(location.is_relative_to(profile), key)
            self.assertEqual(job["modules"], ["example"])

        process = self.fake_process({"status": "pass", "reason": "registered", "loaded": {"abc": "/copied/abc.py"}}, inspect=inspect)
        with patch("addon_scope.probe.subprocess.Popen", process):
            result = run_probe(self.spec())
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.loaded, {"abc": "/copied/abc.py"})
        self.assertEqual((self.source / "__init__.py").read_bytes(), original)
        self.assertIn("Blender diagnostic output", result.stdout)

    def test_extension_keeps_repo_identity(self):
        self.addon.kind = "extension"
        self.addon.module = "bl_ext.blender_org.example"

        def inspect(command, kwargs, job):
            self.assertEqual(job["modules"], ["bl_ext.blender_org.example"])
            repository = job["repositories"][0]
            self.assertEqual(repository["module"], "blender_org")
            self.assertTrue((Path(repository["directory"]) / "example/__init__.py").is_file())

        with patch("addon_scope.probe.subprocess.Popen", self.fake_process({"status": "pass"}, inspect=inspect)):
            self.assertEqual(run_probe(self.spec()).status, "pass")

    def test_settings_reach_only_selected_worker_and_are_not_exported(self):
        settings = {"example": {"token": "private-value"}, "not_selected": {"count": 3}}

        def inspect(command, kwargs, job):
            self.assertEqual(job["settings"], {"example": settings["example"]})
            self.assertIn("--factory-startup", command)

        with patch("addon_scope.probe.subprocess.Popen", self.fake_process({"status": "pass"}, inspect=inspect)):
            result = run_probe(self.spec(profile_mode="settings", settings=settings))
        self.assertEqual(result.status, "pass")
        self.assertEqual(result.context["profile_mode"], "settings")
        self.assertEqual(len(result.context["settings_sha256"]), 64)
        self.assertNotIn("private-value", json.dumps(result.to_dict()))

    def test_factory_mode_rejects_settings_and_invalid_mode_never_launches(self):
        for spec in (self.spec(settings={"example": {}}), self.spec(profile_mode="unknown")):
            with patch("addon_scope.probe.subprocess.Popen") as launch:
                self.assertEqual(run_probe(spec).status, "unresolved")
                launch.assert_not_called()

    def test_progress_stages_include_real_completed_result(self):
        events = []
        with patch("addon_scope.probe.subprocess.Popen", self.fake_process({"status": "pass"})):
            result = run_probe(self.spec(on_progress=events.append))
        self.assertEqual([event["stage"] for event in events], ["copying", "registering", "completed"])
        self.assertEqual(events[-1]["result"], result.to_dict())

    def test_unknown_dependency_is_unresolved_without_launch(self):
        with patch("addon_scope.probe.subprocess.Popen") as launch:
            result = run_probe(self.spec(dependencies={"example": ["missing"]}))
        self.assertEqual(result.status, "unresolved")
        launch.assert_not_called()

    def test_invalid_timeout_is_unresolved_without_launch(self):
        for value in (None, "30", True, float("nan"), float("inf"), 0, -1):
            with self.subTest(timeout=value), patch("addon_scope.probe.subprocess.Popen") as launch:
                result = run_probe(self.spec(timeout=value))
            self.assertEqual(result.status, "unresolved")
            self.assertIn("timeout", result.reason)
            launch.assert_not_called()

    def test_cancelled_probe_never_copies_or_launches(self):
        event = Event()
        event.set()
        with patch("addon_scope.probe._prepare") as copy, patch("addon_scope.probe.subprocess.Popen") as launch:
            result = run_probe(self.spec(cancel_event=event))
        self.assertEqual(result.status, "unresolved")
        self.assertIn("stopped", result.reason)
        copy.assert_not_called()
        launch.assert_not_called()

    def test_cancel_during_copy_prevents_process_launch(self):
        from addon_scope.probe import _prepare
        event = Event()

        def copy_then_stop(root, addons):
            copied = _prepare(root, addons)
            event.set()
            return copied

        with patch("addon_scope.probe._prepare", side_effect=copy_then_stop), patch("addon_scope.probe.subprocess.Popen") as launch:
            result = run_probe(self.spec(cancel_event=event))
        self.assertEqual(result.status, "unresolved")
        self.assertIn("before launching", result.reason)
        launch.assert_not_called()

    def test_symlink_is_not_followed(self):
        try:
            (self.source / "external").symlink_to(self.root)
        except (OSError, NotImplementedError):
            self.skipTest("No symlinks on this platform")
        result = run_probe(self.spec())
        self.assertEqual(result.status, "unresolved")
        self.assertIn("symbolic link", result.reason)

    def test_startup_error_is_not_a_conflict(self):
        with patch("addon_scope.probe.subprocess.Popen", self.fake_process(returncode=1)):
            result = run_probe(self.spec())
        self.assertEqual(result.status, "unresolved")

    def test_crash_during_registration_is_distinct(self):
        with patch("addon_scope.probe.subprocess.Popen", self.fake_process(returncode=-11, phase={"stage": "registering", "module": "example"})):
            result = run_probe(self.spec())
        self.assertEqual(result.status, "fail")
        self.assertEqual(json.loads(result.failure_key), ["example", "ProcessExit", -11])

    def test_same_exit_signal_from_another_module_has_a_different_key(self):
        other_source = self.root / "other"
        other_source.mkdir()
        (other_source / "__init__.py").write_text("def register(): pass\ndef unregister(): pass\n")
        other = Addon("other", "Other", str(other_source), module="other", kind="legacy")
        results = []
        for addon in (self.addon, other):
            with patch("addon_scope.probe.subprocess.Popen", self.fake_process(
                    returncode=-11, phase={"stage": "registering", "module": addon.module})):
                results.append(run_probe(ProbeSpec(sys.executable, [addon])))
        self.assertTrue(all(result.status == "fail" for result in results))
        self.assertNotEqual(results[0].failure_key, results[1].failure_key)

    def test_crash_without_a_known_registration_module_is_unresolved(self):
        with patch("addon_scope.probe.subprocess.Popen", self.fake_process(
                returncode=-11, phase={"stage": "registering", "module": "not_selected"})):
            self.assertEqual(run_probe(self.spec()).status, "unresolved")

    def test_exit_after_registration_is_not_attributed_to_last_addon(self):
        for phase in ({"stage": "collecting_imports", "module": "example"},
                      {"stage": "complete", "module": "example"}):
            with self.subTest(phase=phase), patch("addon_scope.probe.subprocess.Popen", self.fake_process(
                    returncode=-11, phase=phase)):
                result = run_probe(self.spec())
            self.assertEqual(result.status, "unresolved")
            self.assertEqual(result.failure_key, "")

    def test_abnormal_exit_after_success_is_unresolved(self):
        with patch("addon_scope.probe.subprocess.Popen", self.fake_process(
                {"status": "pass", "reason": "registered"}, returncode=12)):
            result = run_probe(self.spec())
        self.assertEqual(result.status, "unresolved")
        self.assertIn("after registration", result.reason)

    def test_relative_executable_is_resolved_before_changing_cwd(self):
        def inspect(command, kwargs, job):
            self.assertTrue(Path(command[0]).is_absolute())
            self.assertEqual(command[0], str(Path("relative/blender").resolve()))
        with patch("addon_scope.probe.shutil.which", return_value="relative/blender"), patch(
                "addon_scope.probe.subprocess.Popen", self.fake_process({"status": "pass"}, inspect=inspect)):
            self.assertEqual(run_probe(self.spec()).status, "pass")

    def test_failure_key_binds_module_and_exception_but_normalizes_profile(self):
        first = _failure_key("example", RuntimeError("/tmp/addonscope-probe-first/module.py failed"), "/tmp/addonscope-probe-first")
        repeat = _failure_key("example", RuntimeError("/tmp/addonscope-probe-second/module.py failed"), "/tmp/addonscope-probe-second")
        self.assertEqual(first, repeat)
        self.assertNotEqual(first, _failure_key("other", RuntimeError("/tmp/addonscope-probe-first/module.py failed"), "/tmp/addonscope-probe-first"))
        self.assertNotEqual(first, _failure_key("example", ValueError("/tmp/addonscope-probe-first/module.py failed"), "/tmp/addonscope-probe-first"))

    def test_failure_identity_preserves_reason_after_profile_path(self):
        first = _failure_key("a", RuntimeError("/tmp/addonscope-probe-FIRST: intended dependency failure"), "/tmp/addonscope-probe-FIRST")
        unrelated = _failure_key("a", RuntimeError("/tmp/addonscope-probe-SECOND: unrelated missing dependency"), "/tmp/addonscope-probe-SECOND")
        self.assertNotEqual(first, unrelated)
        self.assertIn("intended dependency failure", json.loads(first)[2])
        self.assertIn("unrelated missing dependency", json.loads(unrelated)[2])
        other_directory = _failure_key("a", RuntimeError("/tmp/addonscope-probe-UNRELATED: missing file"), "/tmp/addonscope-probe-FIRST")
        self.assertIn("addonscope-probe-UNRELATED", json.loads(other_directory)[2])

    def test_provenance_type_checks_do_not_call_proxy_class_hooks(self):
        class Proxy:
            def __getattribute__(self, name):
                raise AssertionError("Provenance read a proxy attribute: " + name)
        self.assertIsNone(_module_file(Proxy()))

    def test_import_provenance_does_not_execute_stdlib_lazyloader(self):
        source = self.root / "deferred.py"
        marker = self.root / "executed.txt"
        source.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n")
        name = "scope_probe_lazy_regression"
        spec = importlib.util.spec_from_file_location(name, source)
        spec.loader = importlib.util.LazyLoader(spec.loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(module)
        self.assertEqual(_module_file(module), str(source))
        self.assertFalse(marker.exists(), "Provenance collection executed deferred module code")
        self.assertIs(type(module), importlib.util._LazyModule)

    def test_setup_error_payload_is_unresolved(self):
        with patch("addon_scope.probe.subprocess.Popen", self.fake_process({"status": "unresolved", "reason": "bad repository"})):
            self.assertEqual(run_probe(self.spec()).status, "unresolved")

    def test_timeout_is_never_a_confirmed_failure(self):
        process = self.fake_process()
        original_wait = process.wait
        waits = []

        def wait(instance, timeout=None):
            waits.append(timeout)
            if timeout is not None:
                raise subprocess.TimeoutExpired("blender", timeout)
            return original_wait(instance)

        process.wait = wait
        termination = (patch("addon_scope.probe.os.killpg") if os.name == "posix"
                       else patch.object(process, "kill", create=True))
        with patch("addon_scope.probe.subprocess.Popen", process), termination as kill:
            result = run_probe(self.spec(timeout=0.01))
        self.assertEqual(result.status, "unresolved")
        kill.assert_called_once()
        self.assertEqual(waits, [0.01, None], "The timed-out process must be stopped and reaped")

    def test_environment_drops_user_python_and_blender_paths(self):
        with patch.dict(os.environ, {"PYTHONPATH": "/original", "PYTHONHOME": "/original", "BLENDER_USER_CONFIG": "/original",
                                     "BLENDER_SYSTEM_SCRIPTS": "/original-system", "BLENDER_SYSTEM_PYTHON": "/original-python"}):
            before = dict(os.environ)
            env = _environment(Path("/copy"))
            self.assertEqual(dict(os.environ), before)
        self.assertNotIn("PYTHONPATH", env)
        self.assertNotIn("PYTHONHOME", env)
        self.assertNotIn("BLENDER_SYSTEM_SCRIPTS", env)
        self.assertNotIn("BLENDER_SYSTEM_PYTHON", env)
        self.assertEqual(env["BLENDER_USER_CONFIG"], str(Path("/copy/config")))

    def test_normal_configuration_and_temp_paths_belong_to_child_profile(self):
        keys = ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
                "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
                "TMPDIR", "TEMP", "TMP")
        with patch.dict(os.environ, {key: "/original-user" for key in keys}):
            before = dict(os.environ)
            profile = self.root / "copy"
            child = _environment(profile)
            for key in keys:
                self.assertTrue(Path(child[key]).is_relative_to(profile), key)
            self.assertEqual(dict(os.environ), before)


class ReductionTests(unittest.TestCase):
    def spec(self, *, dependencies=None):
        return ProbeSpec("blender", [Addon(name, name, "/" + name, module=name, kind="legacy")
                                     for name in ["a", "b", "c", "d"]],
                         dependencies=dependencies or {})

    def oracle(self, spec, selected):
        from addon_scope.probe import _selection
        ids = [addon.id for addon in _selection(spec, selected)]
        broken = {"a", "c"}.issubset(ids)
        return ProbeResult("fail" if broken else "pass", "fixture", selected=ids,
                           failure_key="ImportError: target" if broken else "")

    def test_reduces_pair_and_repeats_final_trial(self):
        with patch("addon_scope.probe.run_probe", side_effect=self.oracle):
            result = minimize(self.spec())
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.selected, ["a", "c"])
        self.assertEqual(result.trials[0].selected, [])
        self.assertEqual(result.trials[1].selected, ["a", "b", "c", "d"])
        self.assertEqual(result.trials[-1].selected, result.selected)

    def test_dependency_closure_and_original_order(self):
        spec = self.spec(dependencies={"c": ["b"], "b": ["d"]})
        with patch("addon_scope.probe.run_probe", side_effect=self.oracle):
            result = minimize(spec)
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.selected, ["a", "b", "c", "d"])
        for trial in result.trials:
            if "c" in trial.selected:
                self.assertIn("b", trial.selected)
                self.assertIn("d", trial.selected)
            self.assertEqual(trial.selected, [x for x in ["a", "b", "c", "d"] if x in trial.selected])

    def test_unresolved_candidates_do_not_become_working(self):
        def oracle(spec, selected):
            if selected and len(selected) < 4:
                return ProbeResult("unresolved", "timeout", selected=selected)
            return self.oracle(spec, selected)
        with patch("addon_scope.probe.run_probe", side_effect=oracle):
            result = minimize(self.spec())
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.selected, ["a", "b", "c", "d"])
        self.assertIn("unresolved", result.reason)

    def test_unrelated_error_does_not_count_as_same_failure(self):
        def oracle(spec, selected):
            result = self.oracle(spec, selected)
            if selected and result.status == "pass":
                result.status = "fail"
                result.failure_key = "RuntimeError: unrelated"
            return result
        with patch("addon_scope.probe.run_probe", side_effect=oracle):
            result = minimize(self.spec())
        self.assertEqual(result.selected, ["a", "c"])

    def test_same_exception_message_in_another_addon_cannot_replace_target(self):
        def oracle(spec, selected):
            if {"a", "c"}.issubset(selected):
                module = "a"
            elif "c" in selected:
                module = "c"
            else:
                return ProbeResult("pass", "fixture", selected=selected)
            return ProbeResult("fail", "fixture", selected=selected,
                               failure_key=_failure_key(module, RuntimeError("shared error message")))

        with patch("addon_scope.probe.run_probe", side_effect=oracle):
            result = minimize(self.spec())
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.selected, ["a", "c"])
        self.assertEqual(json.loads(result.trials[-1].failure_key)[0], "a")

    def test_flaky_confirmation_is_unresolved(self):
        count = 0
        def oracle(spec, selected):
            nonlocal count
            count += 1
            if count > 2:
                return ProbeResult("pass", "intermittent", selected=selected)
            return self.oracle(spec, selected)
        with patch("addon_scope.probe.run_probe", side_effect=oracle):
            result = minimize(self.spec())
        self.assertEqual(result.status, "unresolved")

    def test_run_budget_includes_final_confirmation(self):
        with patch("addon_scope.probe.run_probe", side_effect=self.oracle):
            result = minimize(self.spec(), max_runs=3)
        self.assertEqual(len(result.trials), 3)
        self.assertEqual(result.selected, ["a", "b", "c", "d"])
        self.assertIn("budget", result.reason)

    def test_broken_empty_profile_stops(self):
        with patch("addon_scope.probe.run_probe", return_value=ProbeResult("fail", "startup")) as run:
            result = minimize(self.spec())
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(run.call_count, 1)

    def test_invalid_run_budget_does_not_start_trials(self):
        for value in (None, "4", True, 3.5, 0, 2):
            with self.subTest(budget=value), patch("addon_scope.probe.run_probe") as run:
                result = minimize(self.spec(), max_runs=value)
            self.assertEqual(result.status, "unresolved")
            self.assertEqual(result.trials, [])
            run.assert_not_called()

    def test_stop_after_current_trial_keeps_trace_and_runs_no_more(self):
        event = Event()
        spec = self.spec()
        spec.cancel_event = event
        calls = []

        def oracle(spec, selected):
            calls.append(selected)
            result = self.oracle(spec, selected)
            if len(calls) == 3:
                event.set()
            return result

        with patch("addon_scope.probe.run_probe", side_effect=oracle):
            result = minimize(spec)
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(result.trials), 3)
        self.assertIn("final confirmation was not completed", result.reason)

    def test_stop_during_final_confirmation_never_reports_confirmed(self):
        event = Event()
        spec = self.spec()
        spec.cancel_event = event
        calls = []

        def oracle(spec, selected):
            calls.append(selected)
            result = self.oracle(spec, selected)
            if len(calls) == 3:
                event.set()
            return result

        with patch("addon_scope.probe.run_probe", side_effect=oracle):
            result = minimize(spec, max_runs=3)
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(len(result.trials), 3)
        self.assertIn("during final confirmation", result.reason)

    def test_preexisting_stop_does_not_run_baseline(self):
        spec = self.spec()
        spec.cancel_event = Event()
        spec.cancel_event.set()
        with patch("addon_scope.probe.run_probe") as run:
            result = minimize(spec)
        self.assertEqual(result.status, "unresolved")
        self.assertEqual(result.trials, [])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
