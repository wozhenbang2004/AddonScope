"""Run inside Blender to check native registration, scan, export and order."""

import json
from pathlib import Path
import sys
import time
import subprocess
import ctypes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bpy
import addon_utils
import addon_scope
from addon_scope import blender_ui

OUTPUT = ROOT / "artifacts" / "verification" / "ui"
OUTPUT.mkdir(parents=True, exist_ok=True)
addon_scope.register()
sys.modules["scope_non_module_fixture"] = object()

repo = bpy.context.preferences.extensions.repos.new(
    name="Synthetic conflict demo", module="scope_demo",
    custom_directory=str(ROOT / "artifacts" / "demo" / "extensions" / "demo"), source="USER",
)
repo.use_custom_directory = True
repo.use_sync_on_startup = False

# Regression: inventory order must not become registration order.
script_root = Path(bpy.utils.user_resource("SCRIPTS")) / "addons"
for module, name, body in (
    ("z_provider", "Z Provider", "bpy.app.driver_namespace['scope_order_ready'] = True"),
    ("a_consumer", "A Consumer", "assert bpy.app.driver_namespace.get('scope_order_ready'), 'provider has not registered yet'"),
):
    path = script_root / module
    path.mkdir(parents=True, exist_ok=True)
    path.joinpath("__init__.py").write_text(
        "import bpy\nbl_info = " + repr({"name": name, "blender": (4, 5, 0), "category": "Development"})
        + "\ndef register():\n    " + body + "\ndef unregister():\n    pass\n", encoding="utf-8")
bpy.utils.refresh_script_paths()
for module in ("z_provider", "a_consumer"):
    assert addon_utils.enable(module, default_set=True) is not None

for area in bpy.context.screen.areas if bpy.context.screen else []:
    if area.type == "VIEW_3D":
        area.spaces.active.show_region_ui = True

assert bpy.ops.addon_scope.scan() == {"FINISHED"}
started = time.monotonic()


def finish():
    if blender_ui._future is not None:
        if time.monotonic() - started > 20:
            raise RuntimeError("Native scan did not complete")
        return 0.2
    assert not blender_ui._error, blender_ui._error
    result = blender_ui._result
    assert any(f.code == "PACKAGE_VERSION_COLLISION" for f in result.findings)
    modules = [a.module for a in blender_ui._probe_addons() if a.module in {"z_provider", "a_consumer"}]
    assert modules == ["z_provider", "a_consumer"], modules
    export = OUTPUT / "native-report.html"
    assert bpy.ops.addon_scope.export(filepath=str(export)) == {"FINISHED"}
    assert export.is_file()
    assert bpy.context.window_manager.addon_scope_findings
    index = next(i for i, f in enumerate(result.findings) if f.code == "PACKAGE_VERSION_COLLISION")
    bpy.context.window_manager.addon_scope_index = index
    (OUTPUT / "native-checks.json").write_text(json.dumps({
        "blender": bpy.app.version_string, "scan": "passed", "export": "passed",
        "registration_order": modules, "findings": len(result.findings),
        "addons": len(result.addons), "packages": len(result.distributions),
        "fixture": "Generated shared-wheel conflict, not a user installation",
    }, indent=2), encoding="utf-8")
    assert bpy.ops.addon_scope.probe(source="FINDING", acknowledge=True) == {"FINISHED"}
    bpy.app.timers.register(check_probe, first_interval=0.3)
    return None


def check_probe():
    if blender_ui._future is not None:
        return 0.2
    assert blender_ui._last_probe["status"] == "fail", blender_ui._last_probe
    assert bpy.ops.addon_scope.probe(reduce=True, acknowledge=True) == {"FINISHED"}
    bpy.app.timers.register(check_reduction, first_interval=0.3)
    return None


def check_reduction():
    if blender_ui._future is not None:
        return 0.2
    assert blender_ui._last_probe["status"] == "confirmed", blender_ui._last_probe
    assert len(blender_ui._last_probe["selected"]) == 2
    assert bpy.ops.addon_scope.export_trial(filepath=str(OUTPUT / "native-trials.json")) == {"FINISHED"}
    path = OUTPUT / "native-checks.json"
    data = json.loads(path.read_text())
    data["probe"] = "fail"
    data["reduction"] = "confirmed"
    data["trials"] = len(blender_ui._last_probe["trials"])
    path.write_text(json.dumps(data, indent=2))
    bpy.app.timers.register(capture, first_interval=1)
    return None


def click(x, y):
    x11 = ctypes.CDLL("libX11.so.6")
    xtest = ctypes.CDLL("libXtst.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    display = x11.XOpenDisplay(None)
    if not display:
        raise RuntimeError("Test display is unavailable")
    xtest.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
    xtest.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xtest.XTestFakeMotionEvent(display, -1, x, y, 0)
    xtest.XTestFakeButtonEvent(display, 1, 1, 0)
    xtest.XTestFakeButtonEvent(display, 1, 0, 0)
    x11.XFlush(display)
    x11.XCloseDisplay(display)


capture_step = 0


def capture():
    global capture_step
    if capture_step < 3:
        click(*[(720, 706), (300, 300), (1175, 260)][capture_step])
        capture_step += 1
        return 1.0
    subprocess.run(["import", "-window", "root", str(OUTPUT / "blender-display.png")], check=True, timeout=5)
    addon_scope.unregister()
    addon_scope.register()
    addon_scope.unregister()
    bpy.ops.wm.quit_blender()
    return None


bpy.app.timers.register(finish, first_interval=0.3)
