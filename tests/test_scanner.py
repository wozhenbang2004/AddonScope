import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from addon_scope.scanner import MAX_METADATA_BYTES, scan
from fixtures import conflict_fixture, extension, installed, wheel


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def codes(self, result):
        return {finding.code for finding in result.findings}

    def test_conflict_records_owners_constraints_and_runtime_source(self):
        conflict_fixture(self.root)
        loaded = str(self.root / "mesh_tools" / "lib" / "bridge" / "__init__.py")
        result = scan([self.root], loaded={"bridge": loaded})
        self.assertEqual(len(result.addons), 2)
        self.assertEqual(len(result.distributions), 3)
        self.assertTrue({"PACKAGE_VERSION_COLLISION", "DEPENDENCY_VERSION_MISMATCH", "IMPORT_PROVENANCE"} <= self.codes(result))
        finding = next(f for f in result.findings if f.code == "DEPENDENCY_VERSION_MISMATCH")
        self.assertEqual(finding.severity, "warning")
        self.assertIn("mesh_tools", finding.owners)
        self.assertTrue(any("bridge>=2" in evidence for evidence in finding.evidence))
        provenance = next(f for f in result.findings if f.code == "IMPORT_PROVENANCE")
        self.assertIn(loaded, provenance.evidence)
        self.assertNotIn("bridge", sys.modules)

    def test_compatible_installation_has_no_conflict(self):
        addon = extension(self.root, "clean", wheels=["wheels/consumer-1.0-py3-none-any.whl", "wheels/bridge-2.0-py3-none-any.whl"])
        wheel(addon / "wheels", "consumer", requires=["bridge>=2,<3"])
        wheel(addon / "wheels", "bridge", "2.0")
        result = scan([self.root])
        self.assertEqual(result.findings, [])
        self.assertEqual(len(result.distributions), 2)

    def test_all_known_versions_incompatible_is_an_error_candidate(self):
        installed(self.root, "consumer", requires=["bridge>=3"], modules=["consumer"])
        installed(self.root, "bridge", "2.0", modules=["bridge"])
        result = scan([self.root])
        finding = next(f for f in result.findings if f.code == "DEPENDENCY_VERSION_MISMATCH")
        self.assertEqual(finding.severity, "error")
        self.assertEqual(finding.confidence, "potential")
        self.assertIn("inventoried", finding.summary)

    def test_markers_are_evaluated_in_requested_environment(self):
        installed(self.root, "consumer", requires=['absent>=2; sys_platform == "win32"', 'other>=2; extra == "optional"'])
        result = scan([self.root], environment={"sys_platform": "linux"})
        self.assertNotIn("DEPENDENCY_NOT_IN_INVENTORY", self.codes(result))
        result = scan([self.root], environment={"sys_platform": "win32"})
        self.assertIn("DEPENDENCY_NOT_IN_INVENTORY", self.codes(result))

    def test_invalid_requirement_does_not_abort_scan(self):
        installed(self.root, "consumer", requires=['bridge>=2; nonsense ???'])
        result = scan([self.root])
        self.assertIn("REQUIREMENT_INVALID", self.codes(result))
        self.assertEqual(len(result.distributions), 1)

    def test_invalid_distribution_metadata_is_reported(self):
        addon = extension(self.root, "broken", wheels=["wheels/bridge-1.0-py3-none-any.whl"])
        wheel(addon / "wheels", "bridge", metadata="Name: bridge\nVersion: who-knows\n")
        result = scan([self.root])
        self.assertIn("DISTRIBUTION_METADATA_INVALID", self.codes(result))
        self.assertEqual(result.distributions, [])

    def test_cross_platform_versions_do_not_create_false_collision(self):
        addon = extension(self.root, "multi", wheels=["wheels/bridge-1.0-cp311-cp311-win_amd64.whl", "wheels/bridge-2.0-cp311-cp311-manylinux_2_28_x86_64.whl"])
        wheel(addon / "wheels", "bridge", "1.0", tag="cp311-cp311-win_amd64")
        wheel(addon / "wheels", "bridge", "2.0", tag="cp311-cp311-manylinux_2_28_x86_64")
        result = scan([self.root], environment={"sys_platform": "linux", "python_version": "3.11", "platform_machine": "x86_64"})
        self.assertEqual([d.version for d in result.distributions], ["2.0"])
        self.assertIn("WHEEL_TARGET_SKIPPED", self.codes(result))
        all_targets = scan([self.root])
        self.assertEqual(len(all_targets.distributions), 2)

    def test_abi3_older_interpreter_is_kept(self):
        addon = extension(self.root, "abi", wheels=["wheels/bridge-1.0-cp38-abi3-manylinux_2_17_x86_64.whl"])
        wheel(addon / "wheels", "bridge", tag="cp38-abi3-manylinux_2_17_x86_64")
        result = scan([self.root], environment={"sys_platform": "linux", "python_version": "3.11"})
        self.assertEqual(len(result.distributions), 1)

    def test_pypy_provider_cannot_satisfy_a_cpython_dependency(self):
        first = extension(self.root, "one", wheels=[
            "wheels/consumer-1.0-py3-none-any.whl",
            "wheels/bridge-1.0-cp311-cp311-manylinux_2_28_x86_64.whl"])
        second = extension(self.root, "two", wheels=[
            "wheels/bridge-2.0-pp311-pypy311_pp73-manylinux_2_28_x86_64.whl"])
        wheel(first / "wheels", "consumer", requires=["bridge>=2"])
        wheel(first / "wheels", "bridge", "1.0", tag="cp311-cp311-manylinux_2_28_x86_64")
        wheel(second / "wheels", "bridge", "2.0", tag="pp311-pypy311_pp73-manylinux_2_28_x86_64")
        result = scan([self.root], environment={"sys_platform": "linux", "python_version": "3.11",
                      "platform_machine": "x86_64", "implementation_name": "cpython",
                      "platform_python_implementation": "CPython"})
        self.assertEqual([(d.name, d.version) for d in result.distributions], [("bridge", "1.0"), ("consumer", "1.0")])
        mismatch = next(f for f in result.findings if f.code == "DEPENDENCY_VERSION_MISMATCH")
        self.assertEqual(mismatch.severity, "error")
        self.assertNotIn("PACKAGE_VERSION_COLLISION", self.codes(result))

    def test_cpython_target_excludes_incompatible_abis(self):
        tags = ["cp311-pypy311_pp73-manylinux_2_28_x86_64", "cp311-cp310-manylinux_2_28_x86_64",
                "py3-cp311-manylinux_2_28_x86_64", "cp311-cp311-manylinux_2_28_x86_64"]
        addon = extension(self.root, "abis", wheels=[f"wheels/bridge-{i}.0-{tag}.whl" for i, tag in enumerate(tags, 1)])
        for i, tag in enumerate(tags, 1):
            wheel(addon / "wheels", "bridge", f"{i}.0", tag=tag)
        result = scan([self.root], environment={"python_version": "3.11", "implementation_name": "cpython"})
        self.assertEqual([d.version for d in result.distributions], ["4.0"])

    def test_unknown_implementation_retains_an_unexcluded_interpreter(self):
        addon = extension(self.root, "unknown", wheels=["wheels/bridge-1.0-pp311-pypy311_pp73-manylinux_2_28_x86_64.whl"])
        wheel(addon / "wheels", "bridge", tag="pp311-pypy311_pp73-manylinux_2_28_x86_64")
        result = scan([self.root], environment={"python_version": "3.11", "sys_platform": "linux"})
        self.assertEqual(len(result.distributions), 1)

    def test_pypy_target_excludes_cpython_but_keeps_generic_python(self):
        tags = ["cp311-abi3-manylinux_2_28_x86_64", "pp311-pypy311_pp73-manylinux_2_28_x86_64", "py310-none-any"]
        addon = extension(self.root, "pypy", wheels=[f"wheels/bridge-{i}.0-{tag}.whl" for i, tag in enumerate(tags, 1)])
        for i, tag in enumerate(tags, 1):
            wheel(addon / "wheels", "bridge", f"{i}.0", tag=tag)
        result = scan([self.root], environment={"python_version": "3.11", "implementation_name": "pypy"})
        self.assertEqual([d.version for d in result.distributions], ["2.0", "3.0"])

    def test_platform_implementation_name_is_a_supported_target_key(self):
        addon = extension(self.root, "cpython", wheels=["wheels/bridge-1.0-pp311-pypy311_pp73-manylinux_2_28_x86_64.whl"])
        wheel(addon / "wheels", "bridge", tag="pp311-pypy311_pp73-manylinux_2_28_x86_64")
        result = scan([self.root], environment={"python_version": "3.11", "platform_python_implementation": "CPython"})
        self.assertEqual(result.distributions, [])
        self.assertIn("WHEEL_TARGET_SKIPPED", self.codes(result))

    def test_filename_and_wheel_metadata_target_disagreement(self):
        addon = extension(self.root, "mixed", wheels=["wheels/bridge-1.0-py3-none-any.whl"])
        wheel(addon / "wheels", "bridge", wheel_tag="cp311-cp311-win_amd64")
        result = scan([self.root])
        self.assertIn("WHEEL_TAG_MISMATCH", self.codes(result))
        self.assertEqual(result.distributions[0].tags, ["py3-none-any"])

    def test_invalid_wheel_tag_does_not_abort_metadata_inventory(self):
        addon = extension(self.root, "mixed", wheels=["wheels/bridge-1.0-py3-none-any.whl"])
        wheel(addon / "wheels", "bridge", wheel_tag="nonsense")
        result = scan([self.root])
        self.assertIn("WHEEL_TAG_INVALID", self.codes(result))
        self.assertEqual(len(result.distributions), 1)

    def test_manifest_path_traversal_is_rejected(self):
        extension(self.root, "escape", wheels=["../../external.whl", "C:\\outside.whl"])
        result = scan([self.root])
        self.assertEqual(len([f for f in result.findings if f.code == "UNSAFE_WHEEL_PATH"]), 2)

    def test_manifest_symlink_loop_is_a_local_finding(self):
        addon = extension(self.root, "loop", wheels=["wheels/loop.whl"])
        (addon / "wheels").mkdir()
        (addon / "wheels" / "loop.whl").symlink_to("loop.whl")
        installed(self.root / "shared", "unrelated", modules=["unrelated"])
        result = scan([self.root])
        self.assertIn("WHEEL_PATH_UNREADABLE", self.codes(result))
        self.assertEqual([d.name for d in result.distributions], ["unrelated"])

    def test_manifest_symlink_loop_with_non_strict_resolve_preserving_the_path(self):
        addon = extension(self.root, "loop", wheels=["wheels/loop.whl"])
        (addon / "wheels").mkdir()
        loop = addon / "wheels" / "loop.whl"
        loop.symlink_to("loop.whl")
        installed(self.root / "shared", "unrelated", modules=["unrelated"])
        resolve = Path.resolve

        def resolve_preserving_loop(path, *args, **kwargs):
            # Python 3.13 leaves a loop unresolved when strict=False; the OS
            # still rejects stat() with ELOOP. Exercise that behavior on 3.12.
            strict = kwargs.get("strict", args[0] if args else False)
            if path == loop and not strict:
                return path.absolute()
            return resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve_preserving_loop):
            result = scan([self.root])
        self.assertIn("WHEEL_PATH_UNREADABLE", self.codes(result))
        self.assertNotIn("WHEEL_MISSING", self.codes(result))
        self.assertEqual([d.name for d in result.distributions], ["unrelated"])

    def test_missing_declared_wheel_stays_missing(self):
        extension(self.root, "missing", wheels=["wheels/not_here.whl"])
        result = scan([self.root])
        self.assertIn("WHEEL_MISSING", self.codes(result))
        self.assertNotIn("WHEEL_PATH_UNREADABLE", self.codes(result))

    def test_declared_wheel_symlink_outside_extension_is_not_opened(self):
        addon = extension(self.root, "linked", wheels=["wheels/linked.whl"])
        (addon / "wheels").mkdir()
        outside = wheel(self.root / "outside", "hidden")
        (addon / "wheels" / "linked.whl").symlink_to(outside)
        with patch("addon_scope.scanner.zipfile.ZipFile", side_effect=AssertionError("Outside wheel must not be opened")):
            result = scan([addon])
        self.assertIn("UNSAFE_WHEEL_PATH", self.codes(result))
        self.assertEqual(result.distributions, [])

    def test_archive_traversal_is_reported_without_extraction(self):
        addon = extension(self.root, "unsafe", wheels=["wheels/bridge-1.0-py3-none-any.whl"])
        wheel(addon / "wheels", "bridge", extra_members={"../../escaped.txt": "bad"})
        result = scan([self.root])
        self.assertIn("UNSAFE_WHEEL_MEMBER", self.codes(result))
        self.assertEqual(result.distributions, [])
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_corrupt_and_oversized_metadata_archives(self):
        addon = extension(self.root, "broken", wheels=["wheels/bridge-1.0-py3-none-any.whl", "wheels/other-1.0-py3-none-any.whl"])
        path = wheel(addon / "wheels", "bridge")
        path.write_bytes(b"not a zip")
        wheel(addon / "wheels", "other", metadata="x" * (MAX_METADATA_BYTES + 1))
        result = scan([self.root])
        self.assertEqual(len([f for f in result.findings if f.code == "WHEEL_UNREADABLE"]), 2)

    def test_installed_and_bundled_metadata_have_different_owners(self):
        addon = extension(self.root / "extensions" / "user_default", "tools")
        installed(addon / "lib", "bridge", "1.0", modules=["bridge"])
        installed(self.root / "site-packages", "bridge", "2.0", modules=["bridge"])
        result = scan([self.root])
        self.assertEqual(result.addons[0].module, "bl_ext.user_default.tools")
        self.assertEqual(result.addons[0].id, "bl_ext.user_default.tools")
        records = {d.source: d for d in result.distributions}
        self.assertEqual(records["bundled"].owner, result.addons[0].id)
        self.assertTrue(records["installed"].owner.startswith("shared:"))
        self.assertIn("PACKAGE_VERSION_COLLISION", self.codes(result))

    def test_record_can_expose_multiple_modules(self):
        installed(self.root, "different-name", record=["alpha/__init__.py", "beta.py", "different-name-1.0.dist-info/METADATA"])
        result = scan([self.root])
        self.assertEqual(result.distributions[0].modules, ["alpha", "beta"])

    def test_different_distributions_sharing_an_import_are_candidates(self):
        for identity, package in [("a", "first"), ("b", "second")]:
            addon = extension(self.root, identity)
            installed(addon / "lib", package, modules=["common"])
        result = scan([self.root])
        finding = next(f for f in result.findings if f.code == "MODULE_NAME_COLLISION")
        self.assertEqual(finding.confidence, "potential")

    def test_duplicate_native_names_are_not_claimed_as_proven_conflict(self):
        for identity in ["a", "b"]:
            addon = extension(self.root, identity)
            (addon / "helper.dll").write_bytes(b"fake")
        result = scan([self.root])
        finding = next(f for f in result.findings if f.code == "NATIVE_LIBRARY_OVERLAP")
        self.assertEqual(finding.confidence, "potential")
        self.assertIn("do not establish", finding.summary)

    def test_symlink_outside_root_is_not_read(self):
        outside = self.root / "outside"
        installed(outside, "hidden")
        inside = self.root / "inside"
        inside.mkdir()
        (inside / "linked").symlink_to(outside, target_is_directory=True)
        result = scan([inside])
        self.assertEqual(result.distributions, [])
        self.assertIn("SYMLINKS_SKIPPED", self.codes(result))

    def test_duplicate_ids_are_unique_across_repositories(self):
        extension(self.root / "one", "tools")
        extension(self.root / "two", "tools")
        result = scan([self.root])
        self.assertEqual(len({a.id for a in result.addons}), 2)

    def test_legacy_metadata_is_read_without_execution(self):
        addon = self.root / "addons" / "legacy"
        addon.mkdir(parents=True)
        (addon / "__init__.py").write_text("bl_info = {'name': 'Old Tools', 'version': (2, 1)}\nraise RuntimeError('do not run')\n")
        result = scan([self.root], enabled={"legacy"})
        self.assertEqual(result.addons[0].name, "Old Tools")
        self.assertEqual(result.addons[0].version, "2.1")
        self.assertTrue(result.addons[0].enabled)

    def test_single_file_legacy_addon_in_a_custom_directory(self):
        (self.root / "custom.py").write_text("bl_info = {'name': 'Single File'}\nraise RuntimeError('do not run')\n")
        result = scan([self.root])
        self.assertEqual(result.addons[0].name, "Single File")
        self.assertEqual(result.addons[0].module, "custom")

    def test_manifest_file_can_be_the_scan_input(self):
        addon = extension(self.root, "direct", wheels=["wheels/bridge-1.0-py3-none-any.whl"])
        wheel(addon / "wheels", "bridge")
        result = scan([addon / "blender_manifest.toml"])
        self.assertEqual(len(result.addons), 1)
        self.assertEqual(len(result.distributions), 1)

    def test_scan_is_read_only(self):
        conflict_fixture(self.root)
        before = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*") if p.is_file()}
        scan([self.root, self.root])
        after = {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_missing_root_is_a_result_not_an_exception(self):
        result = scan([self.root / "absent"])
        self.assertIn("ROOT_MISSING", self.codes(result))


if __name__ == "__main__":
    unittest.main()
