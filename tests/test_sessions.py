import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from addon_scope.models import Addon, Distribution, Finding, ScanResult
from addon_scope.sessions import compare_scans, list_sessions, load_session, save_session, write_support_bundle


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def scan(self):
        root = str(self.root / "private-addons")
        return ScanResult(roots=[root],
                          addons=[Addon("a", "Example", root + "/a", version="1", module="example", enabled=True)],
                          distributions=[Distribution("shared", "1", root + "/a/shared.whl", "a", "wheel", modules=["shared"])],
                          findings=[Finding("TEST", "warning", "Review </script><b>literal</b>", "Inspect " + root + "/a", owners=["a"], packages=["shared"])],
                          loaded={"shared": root + "/a/shared/__init__.py"}, environment={"blender_version": "4.5.15"})

    def probe(self):
        return {"status": "confirmed", "selected": ["a"], "reason": "Retained failure repeated",
                "settings": {"token": "private-snapshot-value"}, "options": {"timeout": 42, "max_runs": 18},
                "trials": [{"status": "fail", "selected": ["a"], "reason": "Failed registration", "duration": 1.2,
                            "settings": {"token": "private-snapshot-value"},
                            "loaded": {"shared": str(self.root / "private-addons/a/shared/__init__.py")},
                            "failure_key": "[example, RuntimeError, fixture]",
                            "context": {"profile_mode": "settings", "settings_sha256": "a" * 64, "settings_modules": ["example"],
                                        "settings": {"token": "private-snapshot-value"}}}]}

    def test_roundtrip_preserves_scan_and_recorded_results_without_raw_settings(self):
        scan, probe = self.scan(), self.probe()
        before = copy.deepcopy(probe)
        path = save_session(self.root / "history", scan, probe, label="Before upgrade")
        restored, recorded = load_session(path)
        self.assertEqual(restored.to_dict(), scan.to_dict())
        self.assertEqual(recorded["status"], "confirmed")
        self.assertEqual(recorded["trials"][0]["context"]["settings_sha256"], "a" * 64)
        self.assertEqual(recorded["options"], {"timeout": 42, "max_runs": 18})
        self.assertNotIn("private-snapshot-value", path.read_text())
        self.assertEqual(probe, before)
        self.assertEqual(list_sessions(path.parent)[0], {
            "path": str(path), "name": path.name, "label": "Before upgrade",
            "created_at": json.loads(path.read_text())["saved_at"], "captured_at": scan.created_at,
            "addon_count": 1, "finding_count": 1, "probe_status": "confirmed"})

    def test_labels_never_become_paths_and_snapshots_are_unique(self):
        history = self.root / "history"
        first = save_session(history, self.scan(), label="../../outside.json")
        second = save_session(history, self.scan())
        self.assertEqual(first.parent, history)
        self.assertNotEqual(first, second)
        self.assertFalse((self.root / "outside.json").exists())
        self.assertEqual(len(list_sessions(history)), 2)
        self.assertEqual(list_sessions(self.root / "absent"), [])

    def test_invalid_unknown_or_partial_snapshots_are_rejected_and_ignored_in_list(self):
        path = save_session(self.root, self.scan())
        valid = json.loads(path.read_text())
        variants = []
        unknown = copy.deepcopy(valid); unknown["version"] = 99; variants.append(unknown)
        missing = copy.deepcopy(valid); del missing["scan"]["addons"][0]["id"]; variants.append(missing)
        wrong = copy.deepcopy(valid); wrong["scan"]["addons"][0]["enabled"] = "yes"; variants.append(wrong)
        duplicate = copy.deepcopy(valid); duplicate["scan"]["addons"] *= 2; variants.append(duplicate)
        newer = copy.deepcopy(valid); newer["scan"]["schema_version"] = True; variants.append(newer)
        invalid_time = copy.deepcopy(valid); invalid_time["saved_at"] = "yesterday"; variants.append(invalid_time)
        for value in variants:
            with self.subTest(value=value):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    load_session(path)
                self.assertEqual(list_sessions(self.root), [])
        path.write_text('{"format":')
        with self.assertRaises(ValueError):
            load_session(path)

    def test_symlink_file_is_not_read_or_overwritten(self):
        original = save_session(self.root / "history", self.scan())
        link = self.root / "linked.json"
        try:
            link.symlink_to(original)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links unavailable")
        before = original.read_bytes()
        with self.assertRaises(ValueError):
            load_session(link)
        with self.assertRaises(ValueError):
            write_support_bundle(self.scan(), None, link)
        self.assertEqual(original.read_bytes(), before)

    def test_corrupt_enum_types_do_not_block_other_saved_diagnostics(self):
        valid = save_session(self.root, self.scan(), self.probe())
        broken = save_session(self.root, self.scan(), self.probe())
        original = json.loads(broken.read_text())
        for location in ("status", "profile_mode", "duration", "timeout"):
            value = copy.deepcopy(original)
            if location == "status":
                value["probe"]["status"] = []
            elif location == "profile_mode":
                value["probe"]["trials"][0]["context"]["profile_mode"] = []
            elif location == "duration":
                value["probe"]["trials"][0]["duration"] = 10 ** 1000
            else:
                value["probe"]["options"]["timeout"] = 10 ** 1000
            broken.write_text(json.dumps(value))
            with self.subTest(location=location):
                with self.assertRaises(ValueError):
                    load_session(broken)
                self.assertEqual([item["path"] for item in list_sessions(self.root)], [str(valid)])

    def test_size_depth_and_nonfinite_data_are_rejected(self):
        path = save_session(self.root, self.scan())
        with patch("addon_scope.sessions.MAX_SESSION_BYTES", 32):
            with self.assertRaises(ValueError):
                load_session(path)
            with self.assertRaises(ValueError):
                save_session(self.root, self.scan())
        scan = self.scan(); scan.environment["number"] = float("nan")
        with self.assertRaises(ValueError):
            save_session(self.root, scan)
        deep = {}
        for _ in range(18):
            deep = {"nested": deep}
        scan.environment = deep
        with self.assertRaises(ValueError):
            save_session(self.root, scan)

    def test_failed_atomic_write_preserves_existing_file_and_removes_temporary(self):
        bundle = self.root / "support.zip"
        bundle.write_bytes(b"existing")
        with patch("addon_scope.sessions.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                write_support_bundle(self.scan(), self.probe(), bundle)
        self.assertEqual(bundle.read_bytes(), b"existing")
        self.assertFalse(list(self.root.glob(".addonscope-*")))

    def test_compare_added_removed_activation_version_and_import_path(self):
        before = self.scan()
        after = copy.deepcopy(before)
        after.addons[0].enabled = False
        after.addons[0].version = "2"
        after.addons.append(Addon("new", "New", "/new"))
        after.distributions[0].version = "2"
        after.distributions[0].path = "/changed/shared.whl"
        after.loaded = {"shared": "/changed/shared.py", "added": "/new.py"}
        before.loaded["removed"] = "/old.py"
        diff = compare_scans(before, after)
        self.assertEqual(diff["addons"]["added"][0]["id"], "new")
        self.assertEqual(diff["addons"]["changed"][0]["fields"], ["enabled", "version"])
        self.assertIn("paths", diff["packages"]["changed"][0]["fields"])
        self.assertIn("versions", diff["packages"]["changed"][0]["fields"])
        self.assertEqual(diff["imports"]["changed"][0]["after"]["path"], "/changed/shared.py")
        self.assertEqual(diff["imports"]["added"], [{"name": "added", "path": "/new.py"}])
        self.assertEqual(diff["imports"]["removed"], [{"name": "removed", "path": "/old.py"}])

    def test_package_grouping_preserves_multiple_versions_and_path_associations(self):
        before = self.scan()
        before.distributions.append(Distribution("shared", "2", "/second/shared.whl", "a", "wheel", modules=["shared"]))
        after = copy.deepcopy(before)
        after.distributions[0].version, after.distributions[1].version = "2", "1"
        changed = compare_scans(before, after)["packages"]["changed"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["before"]["versions"], ["1", "2"])
        self.assertIn("providers", changed[0]["fields"])
        identical = compare_scans(before, copy.deepcopy(before))
        self.assertTrue(all(not records for area in identical.values() for records in area.values()))

    def test_support_bundle_fixed_members_redaction_and_snapshot_omission(self):
        scan, probe = self.scan(), self.probe()
        scan.environment["diagnostics"] = {"settings": {"token": "QA_PRIVATE_SNAPSHOT"}}
        scan.environment["python_version"] = {"settings": {"token": "QA_NESTED_SNAPSHOT"}}
        before = scan.to_dict()
        path = write_support_bundle(scan, probe, self.root / "support.zip")
        with ZipFile(path) as archive:
            self.assertEqual(set(archive.namelist()), {"report.html", "scan.json", "trials.json", "summary.txt"})
            exported = json.loads(archive.read("scan.json"))
            self.assertTrue(exported["paths_redacted"])
            self.assertEqual(exported["roots"], ["$SCAN_1"])
            all_text = "\n".join(archive.read(name).decode() for name in archive.namelist())
            self.assertNotIn("private-snapshot-value", all_text)
            self.assertNotIn("QA_PRIVATE_SNAPSHOT", all_text)
            self.assertNotIn("QA_NESTED_SNAPSHOT", all_text)
            self.assertNotIn(str(self.root), all_text)
            self.assertNotIn("</script><b>literal</b>", archive.read("report.html").decode())
            self.assertIn("not a privacy guarantee", archive.read("summary.txt").decode())
            self.assertIn("same add-on settings locally", archive.read("summary.txt").decode())
            self.assertIn('"max_runs": 18', archive.read("summary.txt").decode())
            self.assertEqual(json.loads(archive.read("trials.json"))["options"], {"timeout": 42, "max_runs": 18})
        self.assertEqual(scan.to_dict(), before)

    def test_support_bundle_keeps_paths_only_when_explicitly_requested(self):
        path = write_support_bundle(self.scan(), None, self.root / "full-paths.zip", redact_paths=False)
        with ZipFile(path) as archive:
            self.assertIn(str(self.root), archive.read("scan.json").decode())
            self.assertIsNone(json.loads(archive.read("trials.json")))

    def test_invalid_probe_values_never_write_a_snapshot(self):
        for probe in ({"status": "maybe"}, {"status": "pass", "duration": float("inf")},
                      {"status": "confirmed", "trials": [{"status": "fail", "trials": []}]},
                      {"status": "pass", "context": {"settings_sha256": "a" * 64}},
                      {"status": "pass", "context": {"profile_mode": "settings"}},
                      {"status": "pass", "options": {"timeout": True}},
                      {"status": "pass", "duration": 10 ** 1000},
                      {"status": "pass", "options": {"timeout": 10 ** 1000}},
                      {"status": "pass", "options": {"max_runs": 101}}):
            with self.subTest(probe=probe), self.assertRaises(ValueError):
                save_session(self.root, self.scan(), probe)
        self.assertEqual(list(self.root.glob("*.json")), [])


if __name__ == "__main__":
    unittest.main()
