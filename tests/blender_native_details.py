"""Exercise full diagnostic inspection in the real Blender GUI.

Run with tools/verify_ui.py --script tests/blender_native_details.py --height 1400.
The collision is generated test data. The 25-entry evidence stress state is
explicitly synthetic; all screenshots are captures of the actual native panel.
"""

import ctypes
import json
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import bpy
import addon_utils
import addon_scope
from addon_scope import blender_ui as ui
from blender_probe_integration import create_wheel_fixture

OUTPUT = ROOT / "artifacts" / "review" / "native-0.1.1"
OUTPUT.mkdir(parents=True, exist_ok=True)
fixture = Path(bpy.utils.user_resource("SCRIPTS")) / "scope_fixture"
fixture.mkdir(parents=True)
create_wheel_fixture(fixture)
repo = bpy.context.preferences.extensions.repos.new(
    name="Generated native diagnostics test", module="scope_native", custom_directory=str(fixture), source="USER")
repo.use_custom_directory = True
repo.use_sync_on_startup = False
addon_scope.register()
assert addon_utils.enable("bl_ext.scope_native.scope_helper", default_set=True) is not None
bpy.context.preferences.view.show_splash = False
bpy.context.preferences.system.use_region_overlap = False
assert bpy.ops.addon_scope.scan() == {"FINISHED"}

x11 = ctypes.CDLL("libX11.so.6")
xtest = ctypes.CDLL("libXtst.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
display = x11.XOpenDisplay(None)
assert display
for name in ("XTestFakeMotionEvent", "XTestFakeButtonEvent", "XTestFakeKeyEvent"):
    getattr(xtest, name).argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
xtest.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
x11.XKeysymToKeycode.restype = ctypes.c_uint
x11.XFlush.argtypes = [ctypes.c_void_p]


def motion(x, y):
    xtest.XTestFakeMotionEvent(display, -1, x, y, 0)
    x11.XFlush(display)


def click(x, y):
    motion(x, y)
    xtest.XTestFakeButtonEvent(display, 1, 1, 0)
    xtest.XTestFakeButtonEvent(display, 1, 0, 0)
    x11.XFlush(display)


def escape():
    key = x11.XKeysymToKeycode(display, 0xff1b)
    xtest.XTestFakeKeyEvent(display, key, 1, 0)
    xtest.XTestFakeKeyEvent(display, key, 0, 0)
    x11.XFlush(display)


def scroll_details():
    motion(1000, 1100)
    for _ in range(18):
        xtest.XTestFakeButtonEvent(display, 5, 1, 0)
        xtest.XTestFakeButtonEvent(display, 5, 0, 0)
    x11.XFlush(display)


wm = bpy.context.window_manager
area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
area.spaces.active.show_region_ui = True
captures = []
result = None
finding_index = None
original_evidence = None


def redraw():
    for current in bpy.context.screen.areas:
        current.tag_redraw()


def shot(name, title, source="Real Blender scan of generated test add-ons"):
    path = OUTPUT / f"{name}.png"
    subprocess.run(["import", "-window", "root", str(path)], check=True, timeout=5)
    region = next(region for region in area.regions if region.type == "UI")
    # Exclude the stock category tab strip and every other Blender editor.
    height = wm.windows[0].height
    rect = [region.x, height - region.y - region.height,
            region.x + region.width - 28, height - region.y]
    captures.append({"file": path.name, "title": title, "source": source, "crop": rect})
    print("CAPTURED", name, rect, flush=True)


def ready():
    global result, finding_index, original_evidence
    if ui._future is not None:
        return .2
    assert not ui._error, ui._error
    result = ui._result
    finding_index = next(i for i, finding in enumerate(result.findings) if finding.code == "PACKAGE_VERSION_COLLISION")
    wm.addon_scope_index = finding_index
    original_evidence = list(result.findings[finding_index].evidence)
    assert len(wm.addon_scope_addons) == len(result.addons)
    assert len(wm.addon_scope_packages) == len(result.distributions)
    assert len(wm.addon_scope_imports) == len(result.loaded)
    assert "bl_ext.scope_native.scope_helper" in result.loaded
    bpy.app.timers.register(tick, first_interval=.5)
    return None


drag_position = None


def drag_start():
    global drag_position
    region = next(region for region in area.regions if region.type == "UI")
    y = wm.windows[0].height - region.y - region.height // 2
    drag_position = (region.x - 150, y)
    motion(region.x, y)
    xtest.XTestFakeButtonEvent(display, 1, 1, 0)
    x11.XFlush(display)


def drag_move():
    motion(*drag_position)


def drag_end():
    xtest.XTestFakeButtonEvent(display, 1, 0, 0)
    x11.XFlush(display)


def stress():
    finding = result.findings[finding_index]
    finding.evidence = [f"Generated evidence {n:02d}: /test/addons/owner_{n:02d}/wheels/package_{n:02d}-1.0.0-py3-none-any.whl"
                        for n in range(1, 26)]
    ui._refresh_evidence(wm)
    assert len(wm.addon_scope_evidence) == 25
    wm.addon_scope_show_evidence = True
    wm.addon_scope_evidence_query = "evidence 25"
    wm.addon_scope_evidence_index = 24
    assert bpy.ops.addon_scope.copy(value=finding.evidence[24]) == {"FINISHED"}
    assert wm.clipboard == finding.evidence[24]
    redraw()


def addons():
    result.findings[finding_index].evidence = original_evidence
    ui._refresh_evidence(wm)
    wm.addon_scope_view = "INVENTORY"
    wm.addon_scope_addons_query = "scope_legacy"
    wm.addon_scope_addon_index = next(i for i, addon in enumerate(result.addons) if addon.name == "Scope Legacy")
    redraw()


def packages():
    wm.addon_scope_inventory = "PACKAGES"
    wm.addon_scope_packages_query = "scope-tokens"
    wm.addon_scope_package_index = next(i for i, package in enumerate(result.distributions) if package.name == "scope-tokens")
    redraw()


def imports():
    wm.addon_scope_view = "IMPORTS"
    wm.addon_scope_imports_query = "scope_helper"
    wm.addon_scope_import_index = next(i for i, item in enumerate(ui._loaded_items) if item[0] == "bl_ext.scope_native.scope_helper")
    redraw()


def no_matches():
    wm.addon_scope_imports_query = "no-module-matches-this-query"
    flags, _ = ui._filter_records(type("ListFlags", (), {"bitflag_filter_item": 1})(), wm, "addon_scope_imports")
    assert flags and not any(flags)
    redraw()


def recover():
    wm.addon_scope_imports_query = ""
    flags, order = ui._filter_records(type("ListFlags", (), {"bitflag_filter_item": 1})(), wm, "addon_scope_imports")
    assert flags == order == []
    wm.addon_scope_view = "FINDINGS"
    wm.addon_scope_show_evidence = False
    assert bpy.ops.addon_scope.probe(source="FINDING", acknowledge=True) == {"FINISHED"}
    redraw()


def wait_probe():
    if ui._future is not None:
        return .2
    assert ui._last_probe["status"] == "fail", ui._last_probe
    assert bpy.ops.addon_scope.probe(reduce=True, acknowledge=True) == {"FINISHED"}
    return None


def wait_reduction():
    if ui._future is not None:
        return .2
    assert ui._last_probe["status"] == "confirmed", ui._last_probe
    trials = ui._last_probe["trials"]
    assert len(trials) > 1
    wm.addon_scope_trial_index = len(trials)
    return None


def finish():
    (OUTPUT / "metadata.json").write_text(json.dumps(captures, indent=2))
    (OUTPUT / "checks.json").write_text(json.dumps({
        "blender": bpy.app.version_string, "version": addon_scope.__version__,
        "addons": len(result.addons), "packages": len(result.distributions), "imports": len(result.loaded),
        "evidence_count": 25, "last_evidence_copy": "passed", "search_recovery": "passed",
        "probe": "fail", "reduction": "confirmed", "trials": len(ui._last_probe["trials"]),
        "fixture": "Generated wheels, plus explicitly synthetic 25-entry evidence stress state",
    }, indent=2))
    addon_scope.unregister()
    for prop in ui._WM_PROPERTIES:
        assert not hasattr(bpy.types.WindowManager, f"addon_scope_{prop}")
    addon_scope.register()
    addon_scope.unregister()
    bpy.ops.wm.quit_blender()


steps = [
    (escape, .4), (escape, .4), (lambda: click(1175, 260), .5),
    (drag_start, .2), (drag_move, .2), (drag_end, .5),
    (lambda: shot("N01-findings", "Findings and next steps"), .2),
    (stress, .5), (lambda: shot("N02-full-evidence", "Evidence 25 of 25, no export required", "Explicit synthetic 25-entry evidence stress state"), .2),
    (addons, .5), (lambda: shot("N03-addons", "Searchable add-on inventory and full details"), .2),
    (packages, .5), (lambda: shot("N04-packages", "Package owners, paths and complete metadata"), .2),
    (lambda: click(775, 714), .4), (lambda: shot("N08-package-imports", "Expanded package import names"), .2),
    (imports, .5), (lambda: shot("N05-imports", "Actual import path captured in this Blender process"), .2),
    (lambda: click(775, 598), .4), (lambda: shot("N09-scan-scope", "Inspected roots and interpreter environment"), .2),
    (lambda: click(775, 598), .2),
    (no_matches, .5), (lambda: shot("N06-no-matches", "Search with no matches"), .2),
    (recover, .2), (wait_probe, .2), (wait_reduction, .5),
    (lambda: shot("N07-test-result", "Actual confirmed reduction result"), .2),
    (lambda: click(775, 804), .4), (lambda: shot("N10-trial-details", "Individual confirmed reduction trial, errors and import paths"), .2),
    (scroll_details, .5), (lambda: shot("N11-trial-details-lower", "Scrolled trial error, failure identity and captured output entries"), .2),
    (finish, .2),
]
step = 0


def tick():
    global step
    try:
        callback, delay = steps[step]
        repeat = callback()
        if repeat is not None:
            return repeat
        step += 1
        redraw()
        return delay
    except Exception:
        traceback.print_exc()
        sys.stdout.flush()
        bpy.ops.wm.quit_blender()
        return None


bpy.app.timers.register(ready, first_interval=.3)
