"""Verify settings-sensitive registration using a real disposable Blender host."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from addon_scope.probe import _prepare_profile


def inside_blender(output):
    import bpy
    import addon_utils
    from addon_scope.preferences import capture_settings
    from addon_scope.models import Addon
    from addon_scope.probe import ProbeSpec, run_probe, minimize
    from blender_probe_integration import fingerprint

    source = Path(bpy.utils.user_resource("SCRIPTS")) / "addons" / "settings_sensitive"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text('''
import bpy
from bpy.props import StringProperty, BoolProperty, FloatVectorProperty, IntProperty, PointerProperty, CollectionProperty
bl_info = {"name": "Settings-sensitive fixture", "blender": (4, 5, 0), "category": "Development"}
class NestedSettings(bpy.types.PropertyGroup):
    label: StringProperty(default="")
    count: IntProperty(default=0)
class FixturePreferences(bpy.types.AddonPreferences):
    bl_idname = __name__
    token: StringProperty(default="default")
    broken: BoolProperty(default=False)
    vector: FloatVectorProperty(size=3, default=(0, 0, 0))
    count: IntProperty(default=0)
    nested: PointerProperty(type=NestedSettings)
    rows: CollectionProperty(type=NestedSettings)
    expected_rows: IntProperty(default=2)
def register():
    bpy.utils.register_class(NestedSettings)
    bpy.utils.register_class(FixturePreferences)
    prefs = bpy.context.preferences.addons[__name__].preferences
    if prefs.broken:
        assert prefs.token == "private-fixture-value", "String setting was not restored"
        assert tuple(prefs.vector) == (1, 2, 3), "Vector setting was not restored"
        assert prefs.count == 7, "Integer setting was not restored"
        assert prefs.nested.label == "nested value", "Nested group was not restored"
        assert prefs.nested.count == 9, "Nested integer was not restored"
        assert len(prefs.rows) == prefs.expected_rows, "Collection length was not restored"
        for i, row in enumerate(prefs.rows):
            assert row.label == "row " + str(i) and row.count == i + 10, "Collection values were not restored"
        raise RuntimeError("Settings-sensitive registration failure")
def unregister():
    bpy.utils.unregister_class(FixturePreferences)
    bpy.utils.unregister_class(NestedSettings)
''')
    bpy.utils.refresh_script_paths()
    assert addon_utils.enable("settings_sensitive", default_set=True) is not None
    prefs = bpy.context.preferences.addons["settings_sensitive"].preferences
    prefs.broken = True
    prefs.token = "private-fixture-value"
    prefs.vector = (1, 2, 3)
    prefs.count = 7
    prefs.nested.label = "nested value"
    prefs.nested.count = 9
    for i in range(2):
        row = prefs.rows.add()
        row.label = "row " + str(i)
        row.count = i + 10
    settings = capture_settings(bpy.context.preferences, ["settings_sensitive"])
    before = fingerprint(source)
    addon = Addon("settings_sensitive", "Settings-sensitive fixture", str(source),
                  module="settings_sensitive", kind="legacy")
    factory = run_probe(ProbeSpec(bpy.app.binary_path, [addon]))
    assert factory.status == "pass", factory.to_dict()
    events = []
    spec = ProbeSpec(bpy.app.binary_path, [addon], profile_mode="settings", settings=settings,
                     on_progress=events.append, target_modules=["settings_sensitive"])
    copied = run_probe(spec)
    assert copied.status == "fail", copied.to_dict()
    assert "Settings-sensitive registration failure" in copied.failure_key, copied.to_dict()
    reduction = minimize(spec, max_runs=8)
    assert reduction.status == "confirmed", reduction.to_dict()
    assert all(trial.context["settings_sha256"] == copied.context["settings_sha256"] for trial in reduction.trials)
    assert fingerprint(source) == before
    assert capture_settings(bpy.context.preferences, ["settings_sensitive"]) == settings
    prefs.rows.clear()
    prefs.expected_rows = 0
    empty_settings = capture_settings(bpy.context.preferences, ["settings_sensitive"])
    empty_collection = run_probe(ProbeSpec(bpy.app.binary_path, [addon], profile_mode="settings",
                                          settings=empty_settings, target_modules=["settings_sensitive"]))
    assert empty_collection.status == "fail", empty_collection.to_dict()
    assert empty_collection.failure_key == copied.failure_key, empty_collection.to_dict()
    assert capture_settings(bpy.context.preferences, ["settings_sensitive"]) == empty_settings
    assert not Path(bpy.utils.user_resource("CONFIG"), "userpref.blend").exists()
    assert "private-fixture-value" not in json.dumps(reduction.to_dict())
    evidence = {"version": bpy.app.version_string, "factory": factory.to_dict(),
                "settings": copied.to_dict(), "reduction": reduction.to_dict(),
                "empty_collection": empty_collection.to_dict(),
                "setting_types": ["string", "bool", "float_vector", "integer", "nested_group", "collection", "empty_collection"],
                "source_unchanged": True, "original_settings_unchanged": True,
                "no_original_userpref_written": True,
                "progress_stages": sorted({event["stage"] for event in events})}
    output.write_text(json.dumps(evidence, indent=2))
    print("SETTINGS_INTEGRATION_PASSED", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender")
    parser.add_argument("--inside", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None)
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.inside:
        sys.path.insert(0, str(ROOT / "tests"))
        inside_blender(args.output)
        return
    with tempfile.TemporaryDirectory(prefix="addonscope-settings-host-") as directory:
        completed = subprocess.run([args.blender, "--background", "--factory-startup", "--offline-mode",
                                    "--disable-autoexec", "--python-exit-code", "79", "--python", __file__,
                                    "--", "--inside", "--output", str(args.output)],
                                   env=_prepare_profile(Path(directory)), capture_output=True, text=True, timeout=90)
        if completed.returncode or "SETTINGS_INTEGRATION_PASSED" not in completed.stdout:
            raise RuntimeError(completed.stdout + completed.stderr)
        print("Real Blender settings-sensitive reproduction and reduction passed:", args.output)


if __name__ == "__main__":
    main()
