import ast
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from addon_scope.scanner import scan

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reproduce_case", ROOT / "tools" / "reproduce_case.py")
case = importlib.util.module_from_spec(spec)
spec.loader.exec_module(case)


class CaseTests(unittest.TestCase):
    def test_upstream_sources_are_pinned_and_only_new_version_exports_sentinel(self):
        manifest = case.verify_sources()
        self.assertEqual([item["version"] for item in manifest["sources"]], ["4.12.2", "4.14.0"])
        for version, expected in (("4.12.2", False), ("4.14.0", True)):
            tree = ast.parse((case.CASE / "vendor" / version / "typing_extensions.py").read_text())
            declarations = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
            self.assertEqual("Sentinel" in declarations, expected)

    def test_case_scan_records_real_dependency_metadata_without_importing_addons(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            addons = case.create_case(root)
            before = case.fingerprint(root)
            result = scan([root])
            self.assertEqual(case.fingerprint(root), before)
        packages = [dist for dist in result.distributions if dist.name == "typing-extensions"]
        self.assertEqual({dist.version for dist in packages}, {"4.12.2", "4.14.0"})
        finding = next(finding for finding in result.findings if finding.code == "PACKAGE_VERSION_COLLISION")
        self.assertEqual(set(finding.owners), {addon.id for addon in result.addons})
        self.assertEqual(finding.confidence, "potential")


if __name__ == "__main__":
    unittest.main()
