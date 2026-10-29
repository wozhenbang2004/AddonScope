import unittest

from addon_scope.models import Addon, Distribution, Finding, ScanResult
from addon_scope.comparison import package_comparison
from addon_scope.report import report_dict


class ComparisonTests(unittest.TestCase):
    def sample(self):
        return ScanResult(roots=["/private"], distributions=[
            Distribution("shared", "1", "/private/a/shared-1.whl", "a", "wheel", modules=["shared"]),
            Distribution("shared", "2", "/private/b/shared-2.whl", "b", "wheel", modules=["shared"]),
            Distribution("unrelated", "3", "/private/a/other.whl", "a", "wheel", modules=["other"]),
        ], findings=[Finding("PACKAGE_VERSION_COLLISION", "warning", "Title can change", "Summary",
                             owners=["a", "b"], packages=["shared"])])

    def test_compare_exact_package_and_loaded_submodule_without_claiming_winner(self):
        result = self.sample()
        result.loaded = {"shared.api": "/private/site-packages/shared/api.py", "other": "/private/other.py"}
        group = package_comparison(result, result.findings[0])[0]
        self.assertEqual([p["version"] for p in group["providers"]], ["1", "2"])
        self.assertEqual(group["loaded"], {"shared.api": result.loaded["shared.api"]})
        self.assertNotIn("loaded_version", group)

    def test_missing_import_is_explicit_and_exports_redact_comparison_paths(self):
        result = self.sample()
        group = package_comparison(result, result.findings[0])[0]
        self.assertEqual(group["loaded"], {})
        data = report_dict(result)
        self.assertEqual(data["findings"][0]["comparison"][0]["providers"][0]["path"], "$SCAN_1/a/shared-1.whl")
        self.assertEqual(result.distributions[0].path, "/private/a/shared-1.whl")
