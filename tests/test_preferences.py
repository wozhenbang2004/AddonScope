import json
from types import SimpleNamespace
import unittest

from addon_scope.preferences import capture_settings, settings_identity


class PreferenceTests(unittest.TestCase):
    def test_capture_stored_fields_only_and_leave_original_unchanged(self):
        values = {"path": "/user/data", "count": 4, "nested": {"enabled": True}, "vector": [1.0, 2.0]}
        preferences = SimpleNamespace(addons={"a": SimpleNamespace(preferences=values),
                                             "b": SimpleNamespace(preferences=None)})
        copied = capture_settings(preferences, ["a", "b", "disabled"])
        self.assertEqual(copied, {"a": values})
        copied["a"]["vector"][0] = 9
        self.assertEqual(values["vector"], [1.0, 2.0])

    def test_snapshot_identity_is_order_independent_and_value_sensitive(self):
        first = {"a": {"enabled": True, "count": 4}}
        second = {"a": {"count": 4, "enabled": True}}
        self.assertEqual(settings_identity(first), settings_identity(second))
        second["a"]["count"] = 5
        self.assertNotEqual(settings_identity(first), settings_identity(second))

    def test_unsupported_pointer_nonfinite_depth_and_large_settings_fail(self):
        for value in (object(), float("nan"), {"text": "x" * (2 * 1024 * 1024)}):
            with self.subTest(value=type(value).__name__), self.assertRaises(ValueError):
                settings_identity({"a": {"value": value}})
        deep = {}
        for _ in range(18):
            deep = {"value": deep}
        with self.assertRaises(ValueError):
            settings_identity(deep)

    def test_identity_has_no_raw_settings(self):
        digest = settings_identity({"a": {"token": "private-value"}})
        self.assertEqual(len(digest), 64)
        self.assertNotIn("private-value", digest)
