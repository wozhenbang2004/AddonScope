"""Actual native GUI checks for dependency comparison and settings probes."""
import ctypes
import json
from pathlib import Path
import zipfile
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
from blender_probe_integration import create_wheel_fixture, fingerprint
OUTPUT = ROOT / "artifacts" / "review" / "native-release"
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
          "fixture": "Generated shared-wheel and settings-sensitive add-ons; actual Blender UI"}
initial = current = None
current_import_index = None
original_files = fingerprint(fixture)
initial_history = set(ui._history_directory().glob("*.json")) if ui._history_directory().is_dir() else set()
assert not initial_history, "Run this GUI check in a disposable Blender profile"

def redraw():
    for current_area in bpy.context.screen.areas:
        current_area.tag_redraw()

def shot(name, title, dialog=False):
    path = OUTPUT / (name + ".png")
    region = next(r for r in area.regions if r.type == "UI")
    height = wm.windows[0].height
    if dialog:
        # Keep raw popup captures for root to crop precisely after viewing them.
        rect = (1440, 1400, 0, 0)
    else:
        rect = (region.width - 28, region.height, region.x, height-region.y-region.height)
    width, h, x, y = rect
    subprocess.run(["import", "-window", "root", "-crop", f"{width}x{h}+{x}+{y}", str(path)], check=True, timeout=5)
    captures.append({"file": path.name, "title": title, "source": checks["fixture"], "requires_crop": dialog})
    print("CAPTURED", name, flush=True)

def ready():
    global initial
    if ui._future is not None:
        return .2
    assert not ui._error, ui._error
    initial = ui._result
    assert not ui._history_directory().exists(), "Scanning must not create history"
    assert fingerprint(fixture) == original_files, "A scan changed inspected add-on files"
    wm.addon_scope_index = next(i for i,f in enumerate(ui._result.findings) if f.code == "PACKAGE_VERSION_COLLISION")
    bpy.app.timers.register(tick, first_interval=.5)

drag_position = None
def drag_start():
    global drag_position
    region = next(r for r in area.regions if r.type == "UI")
    y = wm.windows[0].height - region.y - region.height//2
    drag_position = (region.x-190, y)
    motion(region.x,y)
    xtest.XTestFakeButtonEvent(display,1,1,0)
    x11.XFlush(display)
def drag_move(): motion(*drag_position)
def drag_end():
    xtest.XTestFakeButtonEvent(display,1,0,0)
    x11.XFlush(display)

def initial_dialog():
    motion(720,700)
    with bpy.context.temp_override(area=area):
        assert bpy.ops.addon_scope.probe("INVOKE_DEFAULT", profile_mode="settings", timeout=12) == {"RUNNING_MODAL"}

def start_probe():
    assert bpy.ops.addon_scope.probe(source="ENABLED", profile_mode="settings", timeout=12, acknowledge=True) == {"FINISHED"}

def wait_probe():
    if ui._future is not None: return .2
    assert not ui._error,ui._error
    assert ui._last_probe["status"] == "fail",ui._last_probe
    assert ui._last_probe["options"] == {"timeout":12.0}
    checks["configured_probe_timeout"] = ui._last_spec.timeout

def reduction_dialog():
    motion(720,700)
    with bpy.context.temp_override(area=area):
        assert bpy.ops.addon_scope.probe("INVOKE_DEFAULT", reduce=True,max_runs=8) == {"RUNNING_MODAL"}

def start_reduction():
    assert bpy.ops.addon_scope.probe(reduce=True,max_runs=8,acknowledge=True) == {"FINISHED"}

def wait_reduction():
    if ui._future is not None:return .2
    assert not ui._error,ui._error
    assert ui._last_probe["status"] == "confirmed",ui._last_probe
    assert ui._last_probe["options"] == {"timeout":12.0,"max_runs":8}
    assert fingerprint(fixture) == original_files, "Probes changed the original add-on installation"
    assert bpy.context.preferences.addons["bl_ext.scope_native.scope_helper"].preferences.broken is True
    checks["original_installation_and_settings_unchanged"] = True
    checks["retained_failure"] = "confirmed"
    checks["maximum_trials"] = 8

def save_and_update_fixture():
    assert bpy.ops.addon_scope.save_session(label="Before generated helper update") == {"FINISHED"}
    assert len(ui._history_items) == 1
    saved = Path(ui._history_items[0]["path"])
    assert saved.is_file()
    from addon_scope.sessions import load_session
    record,probe = load_session(saved)
    assert record.created_at == initial.created_at
    assert probe["status"] == "confirmed"
    assert probe["options"] == {"timeout":12.0,"max_runs":8}
    manifest=fixture/"scope_helper"/"blender_manifest.toml"
    manifest.write_text(manifest.read_text().replace('version = "1.0.0"','version = "1.1.0"'))
    assert bpy.ops.addon_scope.scan() == {"FINISHED"}

def wait_updated_scan():
    global current, current_import_index
    if ui._future is not None:return .2
    assert not ui._error,ui._error
    current=ui._result
    assert any(a.name == "Scope Helper" and a.version == "1.1.0" for a in current.addons)
    assert ui._last_probe is None
    assert bpy.ops.addon_scope.inspect_imports(prefix="bl_ext.scope_native.scope_helper") == {"FINISHED"}
    current_import_index = wm.addon_scope_import_index
    wm.addon_scope_show_history=True
    assert bpy.ops.addon_scope.compare_session() == {"FINISHED"}
    assert any("version" in r["text"] and "1.0.0" in r["text"] and "1.1.0" in r["text"] for r in ui._difference_items)
    checks["history_comparison"]="actual generated add-on manifest 1.0.0 -> 1.1.0"

def scroll_down():
    motion(1000,1100)
    for _ in range(24):
        xtest.XTestFakeButtonEvent(display,5,1,0)
        xtest.XTestFakeButtonEvent(display,5,0,0)
    x11.XFlush(display)

def scroll_up():
    motion(1000,500)
    for _ in range(32):
        xtest.XTestFakeButtonEvent(display,4,1,0)
        xtest.XTestFakeButtonEvent(display,4,0,0)
    x11.XFlush(display)

def open_history():
    assert bpy.ops.addon_scope.open_session() == {"FINISHED"}
    assert ui._result.created_at == initial.created_at
    assert ui._history_context is not None
    assert not ui.SCOPE_OT_probe.poll(bpy.context)
    assert not ui.SCOPE_OT_save_session.poll(bpy.context)
    assert ui._current_scan() is current
    assert bpy.ops.addon_scope.inspect_imports(prefix="scope_tokens") == {"FINISHED"}
    checks["historical_probe_disabled"] = True

def export_bundle():
    target=OUTPUT/"generated-support.zip"
    assert bpy.ops.addon_scope.support_bundle(filepath=str(target)) == {"FINISHED"}
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == {"report.html","scan.json","trials.json","summary.txt"}
        scan=json.loads(archive.read("scan.json")); probe=json.loads(archive.read("trials.json"))
        assert scan["created_at"] == initial.created_at
        assert scan["paths_redacted"] is True
        assert probe["status"] == "confirmed"
        assert probe["options"] == {"timeout":12.0,"max_runs":8}
        assert "settings" not in probe
    checks["support_bundle"]="four evidence files, matching archived scan/probe, default path replacement"

def return_live():
    assert bpy.ops.addon_scope.return_current() == {"FINISHED"}
    assert ui._result is current
    assert ui._last_probe is None
    assert wm.addon_scope_view == "IMPORTS"
    assert wm.addon_scope_imports_query == "bl_ext.scope_native.scope_helper"
    assert wm.addon_scope_import_index == current_import_index
    assert ui.SCOPE_OT_probe.poll(bpy.context)
    checks["live_view_restored"] = True

def restart_and_open_before_scan():
    addon_scope.unregister()
    for prop in ui._WM_PROPERTIES:
        assert not hasattr(bpy.types.WindowManager,"addon_scope_"+prop)
    addon_scope.register()
    assert ui._result is None
    assert bpy.ops.addon_scope.refresh_history() == {"FINISHED"}
    assert len(ui._history_items) == 1
    assert bpy.ops.addon_scope.open_session() == {"FINISHED"}
    assert ui._current_scan() is None
    assert not ui.SCOPE_OT_compare_session.poll(bpy.context)
    assert bpy.ops.addon_scope.return_current() == {"FINISHED"}
    assert ui._result is None
    checks["history_after_restart_and_before_scan"] = True

def finish():
    (OUTPUT/"metadata.json").write_text(json.dumps(captures,indent=2))
    (OUTPUT/"checks.json").write_text(json.dumps(checks,indent=2))
    addon_scope.unregister()
    bpy.ops.wm.quit_blender()

steps=[
 (escape,.4),(escape,.4),(lambda:click(1175,260),.5),(drag_start,.2),(drag_move,.2),(drag_end,.5),
 (lambda:shot("N01-native-comparison","Native dependency versions and actual loaded source"),.2),
 (initial_dialog,.5),(lambda:shot("N02-trial-limits","Configure initial trial settings and timeout",True),.2),(escape,.4),
 (start_probe,.2),(wait_probe,.4),(reduction_dialog,.5),
 (lambda:shot("N03-reduction-limits","Configure reduction run budget while retaining original timeout",True),.2),(escape,.4),
 (start_reduction,.2),(wait_reduction,.4),
 (lambda:shot("N04-failure-confirmed","A retained failure is explicitly labelled reproduced, not compatible"),.2),
 (save_and_update_fixture,.2),(wait_updated_scan,.5),(scroll_down,.6),
 (lambda:shot("N05-history-comparison","Saved snapshot versus the current scan, with complete before/after changes"),.2),
 (open_history,.3),(scroll_up,.5),
 (lambda:shot("N06-saved-snapshot","Saved record identity, capture time and historical import provenance"),.2),
 (export_bundle,.3),(scroll_down,.5),
 (lambda:shot("N07-support-bundle","Support bundle export from the displayed saved diagnostic record"),.2),
 (return_live,.2),(restart_and_open_before_scan,.3),(finish,.2),
]
step=0

def tick():
    global step
    try:
        callback,delay=steps[step]
        repeat=callback()
        if repeat is not None:return repeat
        step+=1
        redraw()
        return delay
    except Exception:
        traceback.print_exc();sys.stdout.flush();bpy.ops.wm.quit_blender()

bpy.app.timers.register(ready,first_interval=.3)
