"""Actual native GUI checks for dependency comparison and settings probes."""
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
OUTPUT = ROOT / "artifacts" / "review" / "native-0.2.0"
OUTPUT.mkdir(parents=True, exist_ok=True)
fixture = Path(bpy.utils.user_resource("SCRIPTS")) / "scope_fixture"
fixture.mkdir(parents=True)
create_wheel_fixture(fixture)
(fixture / "scope_helper" / "__init__.py").write_text("""
import bpy, time
from bpy.props import BoolProperty
class FixtureSettings(bpy.types.AddonPreferences):
    bl_idname = __package__
    broken: BoolProperty(default=False)
def register():
    bpy.utils.register_class(FixtureSettings)
    time.sleep(.8)
    if bpy.context.preferences.addons[__package__].preferences.broken:
        raise RuntimeError('Generated settings-sensitive registration failure')
def unregister():
    bpy.utils.unregister_class(FixtureSettings)
""")
repo = bpy.context.preferences.extensions.repos.new(name="Generated 0.2 fixtures", module="scope_native", custom_directory=str(fixture), source="USER")
repo.use_custom_directory = True
repo.use_sync_on_startup = False
addon_scope.register()
for ident in ("scope_modern", "scope_helper"):
    assert addon_utils.enable("bl_ext.scope_native." + ident, default_set=True) is not None
bpy.context.preferences.addons["bl_ext.scope_native.scope_helper"].preferences.broken = True
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
checks = {"version": addon_scope.__version__, "blender": bpy.app.version_string,
          "fixture": "Generated wheels and a settings-sensitive add-on; screenshots are actual Blender renders"}

def redraw():
    for current in bpy.context.screen.areas:
        current.tag_redraw()

def shot(name, title, dialog=False):
    path = OUTPUT / (name + ".png")
    region = next(r for r in area.regions if r.type == "UI")
    height = wm.windows[0].height
    if dialog:
        rect = (503, 369, 260, 630)
    else:
        rect = (region.width - 28, region.height, region.x, height-region.y-region.height)
    width, h, x, y = rect
    subprocess.run(["import", "-window", "root", "-crop", f"{width}x{h}+{x}+{y}", str(path)], check=True, timeout=5)
    captures.append({"file": path.name, "title": title, "source": checks["fixture"]})
    print("CAPTURED", name, flush=True)

def ready():
    if ui._future is not None:
        return .2
    assert not ui._error, ui._error
    wm.addon_scope_index = next(i for i,f in enumerate(ui._result.findings) if f.code == "PACKAGE_VERSION_COLLISION")
    assert ui._result.loaded["scope_tokens"].endswith("scope_tokens/__init__.py")
    bpy.app.timers.register(tick, first_interval=.5)

drag_position = None
def drag_start():
    global drag_position
    region = next(r for r in area.regions if r.type == "UI")
    y = wm.windows[0].height - region.y - region.height//2
    drag_position = (region.x-190, y)
    motion(region.x, y)
    xtest.XTestFakeButtonEvent(display, 1, 1, 0)
    x11.XFlush(display)
def drag_move():
    motion(*drag_position)
def drag_end():
    xtest.XTestFakeButtonEvent(display, 1, 0, 0)
    x11.XFlush(display)

def imports():
    assert bpy.ops.addon_scope.inspect_imports(prefix="scope_tokens") == {"FINISHED"}
    assert ui._loaded_items[wm.addon_scope_import_index][0] == "scope_tokens"
    assert wm.addon_scope_view == "IMPORTS"
    checks["comparison_import_navigation"] = "passed"

def dialog():
    wm.addon_scope_view = "FINDINGS"
    motion(720, 700)
    with bpy.context.temp_override(area=area):
        assert bpy.ops.addon_scope.probe("INVOKE_DEFAULT", profile_mode="settings") == {"RUNNING_MODAL"}

def factory():
    assert bpy.ops.addon_scope.probe(source="ENABLED", acknowledge=True) == {"FINISHED"}

def wait_factory():
    if ui._future is not None:
        return .2
    assert not ui._error, ui._error
    assert ui._last_probe["status"] == "pass", ui._last_probe
    checks["factory"] = "pass"
    assert bpy.ops.addon_scope.probe(source="ENABLED", profile_mode="settings", acknowledge=True) == {"FINISHED"}

def wait_settings():
    if ui._future is not None:
        return .2
    assert not ui._error, ui._error
    assert ui._last_probe["status"] == "fail", ui._last_probe
    assert ui._last_probe["context"]["profile_mode"] == "settings"
    checks["settings"] = "fail"

def reduce():
    assert bpy.ops.addon_scope.probe(reduce=True, acknowledge=True) == {"FINISHED"}

def capture_progress():
    if ui._future is not None and len(ui._progress_trials) < 2:
        return .1
    assert len(ui._progress_trials) >= 2
    checks["live_completed_trials"] = len(ui._progress_trials)
    shot("N05-live-progress", "Live reduction: current combination, run budget and completed outcomes")

def wait_reduction():
    if ui._future is not None:
        return .2
    assert not ui._error, ui._error
    assert ui._last_probe["status"] == "confirmed", ui._last_probe
    checks["reduction"] = "confirmed"
    checks["trials"] = len(ui._last_probe["trials"])
    assert ui._last_probe["selected"] == [a.id for a in ui._result.addons if a.name == "Scope Helper"]
    assert bpy.context.preferences.addons["bl_ext.scope_native.scope_helper"].preferences.broken

def finish():
    (OUTPUT / "metadata.json").write_text(json.dumps(captures, indent=2))
    (OUTPUT / "checks.json").write_text(json.dumps(checks, indent=2))
    addon_scope.unregister()
    addon_scope.register()
    addon_scope.unregister()
    bpy.ops.wm.quit_blender()

steps = [
    (escape,.4),(escape,.4),(lambda:click(1175,260),.5),
    (drag_start,.2),(drag_move,.2),(drag_end,.5),
    (lambda:shot("N01-comparison","Supplied versions beside observed import path"),.2),
    (imports,.4),(lambda:shot("N02-import-navigation","Full import details reached directly from comparison"),.2),
    (dialog,.5),(lambda:shot("N03-settings-dialog","Factory defaults or a current add-on settings snapshot",True),.2),
    (escape,.4),(factory,.2),(wait_factory,.3),(wait_settings,.5),
    (lambda:shot("N04-settings-result","Settings-dependent failure; original settings stay unchanged"),.2),
    (reduce,.2),(capture_progress,.2),(wait_reduction,.4),
    (lambda:shot("N06-confirmed-subset","Confirmed settings-sensitive subset"),.2),
    (finish,.2),
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

bpy.app.timers.register(ready, first_interval=.3)
