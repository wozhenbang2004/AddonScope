"""Run registration experiments in disposable Blender profiles.

Profiles isolate configuration, not operating-system permissions. Only probe
add-ons that you would trust to run in Blender itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
from threading import Event
import time
from typing import Callable

from .models import Addon
from .preferences import settings_identity


@dataclass
class ProbeSpec:
    executable: str
    addons: list[Addon]
    timeout: float = 30.0
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    target_modules: list[str] = field(default_factory=list)
    cancel_event: Event | None = None
    profile_mode: str = "factory"
    settings: dict = field(default_factory=dict, repr=False)
    on_progress: Callable[[dict], None] | None = field(default=None, repr=False)


@dataclass
class ProbeResult:
    status: str
    reason: str
    returncode: int | None = None
    duration: float = 0.0
    modules: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    loaded: dict[str, str] = field(default_factory=dict)
    stdout: str = ""
    failure_key: str = ""
    selected: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReductionResult:
    status: str
    selected: list[str]
    trials: list[ProbeResult]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class InvalidProbe(ValueError):
    pass


def _cancelled(spec: ProbeSpec) -> bool:
    return spec.cancel_event is not None and spec.cancel_event.is_set()


def _selection(spec: ProbeSpec, selected: list[str] | None) -> list[Addon]:
    by_id = {addon.id: addon for addon in spec.addons}
    if len(by_id) != len(spec.addons):
        raise InvalidProbe("Add-on ids must be unique within a probe.")
    requested = list(by_id) if selected is None else selected
    required = set(requested)
    pending = list(requested)
    while pending:
        ident = pending.pop()
        if ident not in by_id:
            raise InvalidProbe(f"Unknown add-on or required dependency: {ident}")
        for dependency in spec.dependencies.get(ident, []):
            if dependency not in required:
                required.add(dependency)
                pending.append(dependency)
    # Preserve the original registration order. Dependency closure keeps required
    # add-ons in the experiment; it does not invent a load-order repair.
    return [addon for addon in spec.addons if addon.id in required]


def _copy_addon(source: Path, target: Path, budget: list[int]) -> None:
    if source.is_symlink():
        raise InvalidProbe(f"Refusing to follow a symbolic link while copying: {source}")
    if source.is_file():
        budget[0] += source.stat().st_size
        budget[1] += 1
        if budget[0] > 2 * 1024**3 or budget[1] > 50_000:
            raise InvalidProbe("Copied add-ons exceed the 2 GiB / 50,000-file probe limit.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    elif source.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir()):
            if child.name in {"__pycache__", ".git"}:
                continue
            _copy_addon(child, target / child.name, budget)
    else:
        raise InvalidProbe(f"Add-on source is not a regular file or directory: {source}")


def _prepare(root: Path, addons: list[Addon]) -> tuple[list[str], list[dict]]:
    modules: list[str] = []
    repositories: dict[str, dict] = {}
    budget = [0, 0]
    destinations: set[Path] = set()
    for addon in addons:
        source = Path(addon.path).expanduser()
        module = addon.module or source.stem
        if addon.kind == "extension":
            parts = module.split(".")
            if len(parts) == 3 and parts[0] == "bl_ext":
                repo, ident = parts[1:]
            else:
                repo, ident = "addonscope_probe", source.name
            if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) for value in (repo, ident)):
                raise InvalidProbe(f"Invalid extension module identifier: {module}")
            module = f"bl_ext.{repo}.{ident}"
            repo_dir = root / "extensions" / repo
            destination = repo_dir / ident
            repositories[repo] = {"module": repo, "directory": str(repo_dir)}
        else:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", module):
                raise InvalidProbe(f"Invalid legacy add-on module identifier: {module}")
            filename = module + ".py" if source.is_file() else module
            destination = root / "scripts" / "addons" / filename
        if destination in destinations:
            raise InvalidProbe(f"Multiple add-ons map to the same module: {module}")
        destinations.add(destination)
        _copy_addon(source, destination, budget)
        modules.append(module)
    return modules, list(repositories.values())


def _environment(root: Path) -> dict[str, str]:
    home = root / "home"
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("BLENDER_USER_", "BLENDER_SYSTEM_"))
        and key.upper() not in {"PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE"}
    }
    environment.update({
        "BLENDER_USER_RESOURCES": str(root),
        "BLENDER_USER_CONFIG": str(root / "config"),
        "BLENDER_USER_SCRIPTS": str(root / "scripts"),
        "BLENDER_USER_EXTENSIONS": str(root / "extensions"),
        "BLENDER_USER_DATAFILES": str(root / "datafiles"),
        "PYTHONNOUSERSITE": "1",
        "HOME": str(home),
        "USERPROFILE": str(home),
        "HOMEDRIVE": home.drive,
        "HOMEPATH": str(home)[len(home.drive):],
        "APPDATA": str(home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_RUNTIME_DIR": str(root / "runtime"),
        "TMPDIR": str(root / "tmp"),
        "TEMP": str(root / "tmp"),
        "TMP": str(root / "tmp"),
    })
    return environment


def _prepare_profile(root: Path) -> dict[str, str]:
    environment = _environment(root)
    directories = (
        "BLENDER_USER_CONFIG", "BLENDER_USER_SCRIPTS", "BLENDER_USER_EXTENSIONS",
        "BLENDER_USER_DATAFILES", "HOME", "APPDATA", "LOCALAPPDATA",
        "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
        "XDG_RUNTIME_DIR", "TMPDIR",
    )
    for key in directories:
        Path(environment[key]).mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "addons").mkdir()
    Path(environment["XDG_RUNTIME_DIR"]).chmod(0o700)
    return environment


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        content = stream.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise InvalidProbe("Probe result exceeds the 2 MiB limit.")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise InvalidProbe("Probe did not return an object.")
    return result


def _terminate(process: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    process.wait()


def run_probe(spec: ProbeSpec, selected: list[str] | None = None) -> ProbeResult:
    """Run a fresh copied profile and retain its settings identity, never its values."""
    try:
        if spec.profile_mode not in {"factory", "settings"}:
            raise InvalidProbe("Unknown probe profile mode.")
        if spec.profile_mode == "factory" and spec.settings:
            raise InvalidProbe("A factory profile cannot contain add-on settings.")
        context = {"profile_mode": spec.profile_mode}
        if spec.profile_mode == "settings":
            context.update(settings_sha256=settings_identity(spec.settings),
                           settings_modules=sorted(spec.settings))
    except ValueError as error:
        return ProbeResult("unresolved", str(error))
    if spec.on_progress:
        spec.on_progress({"stage": "copying", "selected": selected if selected is not None else [a.id for a in spec.addons]})
    result = _run_probe(spec, selected)
    result.context = context
    if spec.on_progress:
        spec.on_progress({"stage": "completed", "result": result.to_dict()})
    return result


def _run_probe(spec: ProbeSpec, selected: list[str] | None = None) -> ProbeResult:
    """Copy selected add-ons, register them in Blender, and collect import paths.

    This tests background registration with factory defaults or stored add-on
    settings, not viewport actions or a particular .blend file. The launcher copies sources;
    add-on code still runs with the current user's operating-system permissions.
    """
    started = time.monotonic()
    modules: list[str] = []
    identifiers: list[str] = []
    try:
        if isinstance(spec.timeout, bool) or not isinstance(spec.timeout, (int, float)) or not math.isfinite(spec.timeout) or spec.timeout <= 0:
            raise InvalidProbe("Probe timeout must be a positive finite number.")
        addons = _selection(spec, selected)
        identifiers = [addon.id for addon in addons]
        if _cancelled(spec):
            return ProbeResult("unresolved", "Probe stopped before copying add-ons.",
                               duration=time.monotonic() - started, selected=identifiers)
        executable = shutil.which(spec.executable)
        if executable is None:
            raise InvalidProbe(f"Blender executable was not found: {spec.executable}")
        executable = str(Path(executable).resolve())
        with tempfile.TemporaryDirectory(prefix="addonscope-probe-") as directory:
            root = Path(directory)
            environment = _prepare_profile(root)
            modules, repositories = _prepare(root, addons)
            script = root / "probe_script.py"
            shutil.copyfile(Path(__file__).with_name("probe_script.py"), script)
            result_path, phase_path = root / "result.json", root / "phase.json"
            job = {
                "modules": modules,
                "repositories": repositories,
                "targets": spec.target_modules,
                "result": str(result_path),
                "phase": str(phase_path),
                "settings": {module: spec.settings[module] for module in modules
                             if module in spec.settings} if spec.profile_mode == "settings" else {},
            }
            job_path = root / "job.json"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            command = [
                executable, "--background", "--factory-startup", "--offline-mode",
                "--disable-autoexec", "--python-exit-code", "79",
                "--python", str(script), "--", str(job_path),
            ]
            log_path = root / "stdout.log"
            timed_out = False
            if _cancelled(spec):
                return ProbeResult("unresolved", "Probe stopped before launching Blender.",
                                   duration=time.monotonic() - started, modules=modules, selected=identifiers)
            with log_path.open("wb") as output:
                if spec.on_progress:
                    spec.on_progress({"stage": "registering", "selected": identifiers})
                process = subprocess.Popen(
                    command, stdout=output, stderr=subprocess.STDOUT,
                    cwd=root, env=environment, start_new_session=os.name == "posix",
                )
                try:
                    returncode = process.wait(timeout=spec.timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    _terminate(process)
                    returncode = process.returncode
            with log_path.open("rb") as output:
                output.seek(max(0, log_path.stat().st_size - 32_768))
                stdout = output.read().decode("utf-8", errors="replace")
            common = dict(returncode=returncode, duration=time.monotonic() - started,
                          modules=modules, stdout=stdout, selected=identifiers)
            if timed_out:
                return ProbeResult("unresolved", f"Blender exceeded the {spec.timeout:g}s timeout.", **common)
            if result_path.is_file():
                data = _read_json(result_path)
                status = data.get("status")
                if status not in {"pass", "fail", "unresolved"}:
                    raise InvalidProbe("Blender returned an unknown probe status.")
                if returncode != 0 and status == "pass":
                    return ProbeResult("unresolved", "Blender exited abnormally after registration completed.", **common)
                return ProbeResult(status, str(data.get("reason", "")),
                                   errors=data.get("errors", []), loaded=data.get("loaded", {}),
                                   failure_key=str(data.get("failure_key", "")), **common)
            phase = _read_json(phase_path) if phase_path.is_file() else {}
            failed_module = phase.get("module")
            if returncode and phase.get("stage") == "registering" and failed_module in modules:
                return ProbeResult("fail", f"Blender exited while registering {failed_module}.",
                                   failure_key=json.dumps([failed_module, "ProcessExit", returncode]), **common)
            return ProbeResult("unresolved", "Blender did not produce a registration result; inspect its output.", **common)
    except (OSError, ValueError, shutil.Error) as error:
        return ProbeResult("unresolved", str(error), duration=time.monotonic() - started,
                           modules=modules, selected=identifiers)


def minimize(spec: ProbeSpec, max_runs: int = 24) -> ReductionResult:
    """Find a smaller dependency-valid subset with the same failure signature.

    Results are bounded observations, never a global minimality guarantee.
    A final repeated run must confirm the retained failure.
    """
    trials: list[ProbeResult] = []
    try:
        full = [addon.id for addon in _selection(spec, None)]
    except InvalidProbe as error:
        return ReductionResult("unresolved", [], trials, str(error))
    current = full

    def stopped(reason="Stopped; final confirmation was not completed.") -> ReductionResult:
        return ReductionResult("unresolved", current, trials, reason)

    if _cancelled(spec):
        return stopped()
    if isinstance(max_runs, bool) or not isinstance(max_runs, int) or max_runs < 3:
        return ReductionResult("unresolved", full, trials, "The run budget must be an integer of at least three for baseline, full set and confirmation.")

    def run(selection: list[str], stage="candidate") -> ProbeResult:
        if spec.on_progress:
            spec.on_progress({"stage": stage, "trial": len(trials) + 1,
                              "budget": max_runs, "selected": selection})
        result = run_probe(spec, selection)
        trials.append(result)
        return result

    baseline = run([], "baseline")
    if _cancelled(spec):
        return stopped()
    if baseline.status != "pass":
        return ReductionResult("unresolved", full, trials, "The empty profile did not pass; fix the probe environment first.")
    initial = run(full, "full_set")
    if _cancelled(spec):
        return stopped()
    if initial.status != "fail" or not initial.failure_key:
        return ReductionResult("unresolved", full, trials, "The full set did not produce an identifiable registration failure.")
    expected = initial.failure_key
    granularity = 2
    unresolved = 0
    exhausted = False
    while len(current) > 1:
        width = math.ceil(len(current) / granularity)
        partitions = [current[index:index + width] for index in range(0, len(current), width)]
        candidates = partitions + [[ident for ident in current if ident not in part] for part in partitions]
        seen: set[tuple[str, ...]] = set()
        reduced = False
        for candidate in candidates:
            if _cancelled(spec):
                return stopped()
            closed = [addon.id for addon in _selection(spec, candidate)]
            key = tuple(closed)
            if not closed or len(closed) >= len(current) or key in seen:
                continue
            seen.add(key)
            if len(trials) >= max_runs - 1:
                exhausted = True
                break
            result = run(closed)
            if _cancelled(spec):
                return stopped()
            if result.status == "unresolved":
                unresolved += 1
            if result.status == "fail" and result.failure_key == expected:
                current = closed
                granularity = max(2, granularity - 1)
                reduced = True
                break
        if exhausted:
            break
        if reduced:
            continue
        if granularity >= len(current):
            break
        granularity = min(len(current), granularity * 2)
    if _cancelled(spec):
        return stopped()
    confirmation = run(current, "confirmation")
    if _cancelled(spec):
        return stopped("Stopped during final confirmation; no confirmed result is reported.")
    if confirmation.status != "fail" or confirmation.failure_key != expected:
        return ReductionResult("unresolved", current, trials, "The retained failure did not repeat; results may be stateful or intermittent.")
    notes = ["Confirmed this subset in a fresh profile; no global minimality claim."]
    if exhausted:
        notes.append("The run budget was reached.")
    if unresolved:
        notes.append(f"{unresolved} trials were unresolved and were not classified as working.")
    return ReductionResult("confirmed", current, trials, " ".join(notes))
