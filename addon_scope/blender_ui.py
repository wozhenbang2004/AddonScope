"""Blender integration; the diagnostic engine itself has no bpy dependency."""

import platform
import sys
import textwrap
from types import ModuleType
from threading import Event
from queue import SimpleQueue
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from . import __version__
from .scanner import scan

_pool = None
_future = None
_result = None
_error = ""
_job = ""
_last_probe = None
_last_spec = None
_pending_spec = None
_progress_queue = SimpleQueue()
_progress_info = {}
_progress_trials = []
_registered = False
_loaded_items = []
_history_items = []
_history_context = None
_live_snapshot = None
_history_diff = None
_difference_items = []
_history_notice = ""
_pending_budget = None


def _wrap(layout, value, width=52, icon=None):
    column = layout.column(align=True)
    column.scale_y = 0.85
    region = bpy.context.region
    if region and region.type == "UI":
        scale = bpy.context.preferences.system.ui_scale
        width = max(18, min(width, int((region.width - 40) / (7 * scale))))
    for n, line in enumerate(textwrap.wrap(str(value), width=width, break_long_words=True) or [""]):
        column.label(text=line, **({"icon": icon} if icon and n == 0 else {}))


def _inputs():
    roots = []
    repos = []
    for repo in bpy.context.preferences.extensions.repos:
        if repo.directory and Path(repo.directory).is_dir():
            roots.append(repo.directory)
            repos.append((Path(repo.directory).resolve(), repo.module))
    for path in bpy.utils.script_paths(subdir="addons"):
        if Path(path).is_dir():
            roots.append(path)
    for path in sys.path:
        p = Path(path)
        if p.name == "site-packages" and p.is_dir():
            roots.append(str(p))
    roots = list(dict.fromkeys(roots))
    loaded = {}
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType):
            path = vars(module).get("__file__")
            if isinstance(path, str):
                loaded[name] = path
    enabled = set(bpy.context.preferences.addons.keys())
    env = {
        "blender_version": bpy.app.version_string,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_full_version": platform.python_version(),
        "sys_platform": sys.platform,
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "implementation_name": sys.implementation.name,
        "platform_python_implementation": platform.python_implementation(),
    }
    return roots, loaded, enabled, env, repos


def _scan(roots, loaded, enabled, env, repos):
    result = scan(roots, loaded=loaded, enabled=enabled, environment=env)
    for addon in result.addons:
        for root, module in repos:
            try:
                relative = Path(addon.path).resolve().relative_to(root)
            except ValueError:
                continue
            if relative.parts:
                addon.module = f"bl_ext.{module}.{relative.parts[0]}"
                break
        addon.enabled = addon.module in enabled
    return result


def _probe_addons(source="ENABLED"):
    if _result is None or _history_context is not None:
        return []
    by_module = {a.module: a for a in _result.addons}
    # Blender preferences preserve registration order. Inventory sorting must
    # never silently become an experimental load-order change.
    ordered = [by_module[module] for module in bpy.context.preferences.addons.keys()
               if module in by_module and module != __package__]
    if source == "FINDING":
        index = bpy.context.window_manager.addon_scope_index
        if not 0 <= index < len(_result.findings):
            return []
        owners = _result.findings[index].owners
        ordered = [a for a in ordered if a.id in owners]
        present = {a.id for a in ordered}
        ordered.extend(a for a in _result.addons if a.id in owners and a.id not in present and a.module != __package__)
    return ordered


def _complete():
    global _future, _result, _error, _last_probe, _last_spec, _pending_spec
    global _history_context, _live_snapshot, _history_diff
    if not _registered or _future is None:
        return None
    while not _progress_queue.empty():
        event = _progress_queue.get()
        _progress_info.update({key: value for key, value in event.items() if key != "result"})
        if event.get("result"):
            _progress_trials.append(event["result"])
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    if not _future.done():
        return 0.2
    try:
        value = _future.result()
        if _job == "scan":
            _set_result(value)
            _last_probe = None
            _last_spec = None
            _history_context = None
            _live_snapshot = None
            _history_diff = None
        else:
            _last_probe = value.to_dict()
            _last_probe["options"] = {"timeout": _pending_spec.timeout}
            if _pending_budget is not None:
                _last_probe["options"]["max_runs"] = _pending_budget
            _last_spec = _pending_spec
            bpy.context.window_manager.addon_scope_trial_index = 1
    except Exception as exc:
        _error = f"{type(exc).__name__}: {exc}"
    finally:
        _future = None
        _pending_spec = None
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            area.tag_redraw()
    return None


def _submit(job, fn, *args):
    global _pool, _future, _error, _job, _progress_queue, _progress_info, _progress_trials, _pending_spec, _pending_budget
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="addon-scope")
    _error = ""
    _job = job
    _progress_queue = SimpleQueue()
    _progress_info = {}
    _progress_trials = []
    _pending_budget = args[1] if job == "reduce" else None
    if job in {"probe", "reduce"}:
        _pending_spec = args[0]
        _pending_spec.on_progress = _progress_queue.put
    _future = _pool.submit(fn, *args)
    bpy.app.timers.register(_complete, first_interval=0.2)


class SCOPE_PG_finding(bpy.types.PropertyGroup):
    severity: StringProperty()
    index: IntProperty()
    search_text: StringProperty()


class SCOPE_PG_record(bpy.types.PropertyGroup):
    index: IntProperty()
    search_text: StringProperty()


def _refresh_evidence(wm, context=None):
    wm.addon_scope_evidence.clear()
    index = wm.addon_scope_index
    if _result is not None and 0 <= index < len(_result.findings):
        for i, value in enumerate(_result.findings[index].evidence):
            item = wm.addon_scope_evidence.add()
            item.name = f"{i + 1}. {value}"
            item.search_text = value
            item.index = i
    wm.addon_scope_evidence_index = 0
    wm.addon_scope_evidence_query = ""


def _set_result(result):
    global _result, _loaded_items
    _result = result
    wm = bpy.context.window_manager
    wm.addon_scope_findings.clear()
    for i, finding in enumerate(result.findings):
        item = wm.addon_scope_findings.add()
        item.name = finding.title
        item.severity = finding.severity
        item.index = i
        item.search_text = " ".join([finding.title, finding.summary, finding.code, *finding.owners, *finding.evidence])
    for prop, values in (("addons", result.addons), ("packages", result.distributions)):
        collection = getattr(wm, f"addon_scope_{prop}")
        collection.clear()
        for i, value in enumerate(values):
            item = collection.add()
            item.name = f"{value.name} {value.version}".strip()
            item.index = i
            item.search_text = " ".join(str(part) for part in vars(value).values())
    _loaded_items = sorted(result.loaded.items())
    wm.addon_scope_imports.clear()
    for i, (name, path) in enumerate(_loaded_items):
        item = wm.addon_scope_imports.add()
        item.name = name
        item.search_text = f"{name} {path}"
        item.index = i
    for prop in ("index", "addon_index", "package_index", "import_index"):
        setattr(wm, f"addon_scope_{prop}", 0)
    _refresh_evidence(wm)


_QUERIES = {
    "addon_scope_findings": "addon_scope_findings_query",
    "addon_scope_evidence": "addon_scope_evidence_query",
    "addon_scope_addons": "addon_scope_addons_query",
    "addon_scope_packages": "addon_scope_packages_query",
    "addon_scope_imports": "addon_scope_imports_query",
    "addon_scope_history": "addon_scope_history_query",
    "addon_scope_changes": "addon_scope_changes_query",
}


def _filter_records(ui_list, data, propname):
    query = getattr(data, _QUERIES[propname]).strip().casefold()
    if not query:
        return [], []
    return [ui_list.bitflag_filter_item if query in item.search_text.casefold() else 0
            for item in getattr(data, propname)], []


class SCOPE_UL_findings(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name, icon={"error": "ERROR", "warning": "INFO"}.get(item.severity, "DOT"))

    def filter_items(self, context, data, propname):
        return _filter_records(self, data, propname)

    def draw_filter(self, context, layout):
        pass


class SCOPE_UL_records(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        layout.label(text=item.name)

    def filter_items(self, context, data, propname):
        return _filter_records(self, data, propname)

    def draw_filter(self, context, layout):
        pass


class SCOPE_OT_copy(bpy.types.Operator):
    bl_idname = "addon_scope.copy"
    bl_label = "Copy full value"
    bl_description = "Copy the complete value, including long paths, to the clipboard"
    value: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        context.window_manager.clipboard = self.value
        return {"FINISHED"}


class SCOPE_OT_inspect_imports(bpy.types.Operator):
    bl_idname = "addon_scope.inspect_imports"
    bl_label = "Inspect captured imports"
    prefix: StringProperty()

    def execute(self, context):
        wm = context.window_manager
        wm.addon_scope_imports_query = self.prefix
        wm.addon_scope_import_index = next((i for i, (name, _) in enumerate(_loaded_items)
                                           if name == self.prefix or name.startswith(self.prefix + ".")), 0)
        wm.addon_scope_view = "IMPORTS"
        return {"FINISHED"}


class SCOPE_OT_scan(bpy.types.Operator):
    bl_idname = "addon_scope.scan"
    bl_label = "Scan environment"
    bl_description = "Read installed metadata and current import paths without importing add-ons"

    @classmethod
    def poll(cls, context):
        return _future is None

    def execute(self, context):
        _submit("scan", _scan, *_inputs())
        return {"FINISHED"}


class SCOPE_OT_export(bpy.types.Operator):
    bl_idname = "addon_scope.export"
    bl_label = "Export report for sharing"
    bl_description = "Save an optional offline copy; full scan details are available in this panel"
    filename_ext = ".html"
    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.html", options={"HIDDEN"})
    redact_paths: BoolProperty(name="Redact local paths", default=True)

    @classmethod
    def poll(cls, context):
        return _result is not None and _future is None

    def invoke(self, context, event):
        self.filepath = "addon-scope-report.html"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        from .report import write_html
        try:
            target = Path(bpy.path.ensure_ext(self.filepath, ".html"))
            write_html(_result, target, self.redact_paths)
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Report saved: {target.name}")
        return {"FINISHED"}


class SCOPE_OT_probe(bpy.types.Operator):
    bl_idname = "addon_scope.probe"
    bl_label = "Test add-ons in a fresh process"
    bl_description = "Run registration code in a copied profile; does not reproduce scene or UI actions"
    acknowledge: BoolProperty(name="These add-ons are trusted to execute code", default=False)
    source: EnumProperty(name="Test scope", items=[("ENABLED", "Enabled add-ons", "Use current preference order"), ("FINDING", "Affected owners", "Test owners of the selected finding, including disabled add-ons")])
    profile_mode: EnumProperty(name="Settings", items=[
        ("factory", "Factory defaults", "Register with default add-on settings"),
        ("settings", "Current add-on settings", "Copy stored add-on preferences, including unsaved changes"),
    ])
    reduce: BoolProperty(default=False, options={"HIDDEN"})
    timeout: FloatProperty(name="Seconds per trial", default=30, min=1, max=600,
                          description="Maximum registration time for each fresh Blender process")
    max_runs: IntProperty(name="Maximum trials", default=16, min=3, max=100,
                          description="Includes empty baseline, full set and final failure confirmation")

    @classmethod
    def poll(cls, context):
        return _result is not None and _future is None and _history_context is None

    def invoke(self, context, event):
        self.acknowledge = False
        return context.window_manager.invoke_props_dialog(self, width=470)

    def draw(self, context):
        layout = self.layout
        if not self.reduce:
            layout.prop(self, "source")
            layout.prop(self, "profile_mode", expand=True)
            layout.prop(self, "timeout")
        else:
            layout.prop(self, "max_runs")
            if _last_spec:
                layout.label(text=f"Seconds per trial: {_last_spec.timeout:g} (same test conditions)")
        addons = _last_spec.addons if self.reduce and _last_spec else _probe_addons(self.source)
        layout.label(text=f"Run registration for {len(addons)} selected add-ons.")
        for addon in addons[:6]:
            layout.label(text=addon.name)
        if len(addons) > 6:
            layout.label(text=f"And {len(addons) - 6} more, in current preference order.")
        mode = _last_spec.profile_mode if self.reduce and _last_spec else self.profile_mode
        _wrap(layout, "A new Blender process uses disposable add-on copies. Original preferences are not changed.", 62)
        if mode == "settings":
            _wrap(layout, "Stored add-on settings are restored before registration. Global preferences, keymaps and scenes are not copied. Saved external paths still refer to their original locations.", 62)
        else:
            _wrap(layout, "Factory defaults: current add-on settings are not copied.", 62)
        _wrap(layout, "This is not a security sandbox. Scene actions, UI state and external services are outside this check.", 62)
        if self.source == "FINDING" and not self.reduce:
            _wrap(layout, "Enabled owners retain their preference order. Disabled owners follow in inventory order; that is an experimental condition.", 62)
        if self.reduce:
            _wrap(layout, f"Up to {self.max_runs} fresh processes will look for a smaller combination with the same failure. Undeclared dependencies may limit reduction.", 62)
        layout.prop(self, "acknowledge")

    def execute(self, context):
        if not self.acknowledge:
            self.report({"ERROR"}, "Confirm that the selected add-ons are trusted")
            return {"CANCELLED"}
        from .probe import ProbeSpec, minimize, run_probe
        if self.reduce:
            if _last_spec is None or not _last_probe or _last_probe.get("status") != "fail":
                self.report({"WARNING"}, "Run a failing probe before reducing its combination")
                return {"CANCELLED"}
            from dataclasses import replace
            spec = replace(_last_spec, cancel_event=Event())
            _submit("reduce", minimize, spec, self.max_runs)
            return {"FINISHED"}
        addons = _probe_addons(self.source)
        if not addons:
            self.report({"WARNING"}, "No add-ons were found in this test scope")
            return {"CANCELLED"}
        from .preferences import capture_settings
        try:
            settings = capture_settings(context.preferences, [addon.module for addon in addons]) if self.profile_mode == "settings" else {}
        except (ValueError, TypeError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        spec = ProbeSpec(bpy.app.binary_path, addons, timeout=self.timeout, cancel_event=Event(),
                         profile_mode=self.profile_mode, settings=settings)
        _submit("probe", run_probe, spec)
        return {"FINISHED"}


class SCOPE_OT_stop(bpy.types.Operator):
    bl_idname = "addon_scope.stop"
    bl_label = "Stop after current trial"
    bl_description = "Let the running process finish, then stop scheduling new trials"

    @classmethod
    def poll(cls, context):
        return _future is not None and _job in {"probe", "reduce"} and _pending_spec is not None

    def execute(self, context):
        _pending_spec.cancel_event.set()
        self.report({"INFO"}, "Stopping after the current trial")
        return {"FINISHED"}


def _operation_error(operator, error):
    global _error
    _error = f"{type(error).__name__}: {error}"
    operator.report({"ERROR"}, str(error))
    return {"CANCELLED"}


def _history_directory():
    config = bpy.utils.user_resource("CONFIG")
    if not config:
        raise ValueError("Blender's user configuration directory is unavailable.")
    return Path(config) / "addon_scope" / "history"


def _refresh_history(context):
    global _history_items
    from .sessions import list_sessions
    _history_items = list_sessions(_history_directory())
    wm = context.window_manager
    wm.addon_scope_history.clear()
    for index, record in enumerate(_history_items):
        item = wm.addon_scope_history.add()
        item.index = index
        item.name = record["label"] or record["created_at"]
        item.search_text = " ".join(str(value) for value in record.values())
    wm.addon_scope_history_index = 0


def _selected_history(context):
    wm = context.window_manager
    index = wm.addon_scope_history_index
    if not 0 <= index < len(_history_items):
        return None
    query = wm.addon_scope_history_query.strip().casefold()
    if query not in wm.addon_scope_history[index].search_text.casefold():
        return None
    return _history_items[index]


_VIEW_STATE_PROPERTIES = ("view", "inventory", "index", "show_evidence", "evidence_index",
                          "addon_index", "package_index", "import_index", "trial_index",
                          "findings_query", "evidence_query", "addons_query", "packages_query", "imports_query")


def _capture_view_state(wm):
    return {prop: getattr(wm, f"addon_scope_{prop}") for prop in _VIEW_STATE_PROPERTIES}


def _restore_view_state(wm, values):
    # Restore indices before queries: the finding index update rebuilds evidence.
    for prop in _VIEW_STATE_PROPERTIES:
        setattr(wm, f"addon_scope_{prop}", values[prop])


def _current_scan():
    return _live_snapshot[0] if _history_context is not None and _live_snapshot else _result


class SCOPE_OT_save_session(bpy.types.Operator):
    bl_idname = "addon_scope.save_session"
    bl_label = "Save diagnostic snapshot"
    bl_description = "Explicitly save this scan and test results in your local AddonScope history"
    label: StringProperty(name="Label", maxlen=120)

    @classmethod
    def poll(cls, context):
        return _result is not None and _future is None and _history_context is None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        self.layout.prop(self, "label")
        _wrap(self.layout, "Stores full local paths and captured test output on this computer. No add-on source or raw settings snapshot is saved.", 58)

    def execute(self, context):
        global _history_notice, _error
        from .sessions import save_session
        try:
            saved = save_session(_history_directory(), _result, _last_probe, self.label)
            _refresh_history(context)
        except (OSError, ValueError, TypeError) as exc:
            return _operation_error(self, exc)
        _error = ""
        _history_notice = f"Saved snapshot: {self.label or saved.name}"
        context.window_manager.addon_scope_show_history = True
        return {"FINISHED"}


class SCOPE_OT_refresh_history(bpy.types.Operator):
    bl_idname = "addon_scope.refresh_history"
    bl_label = "Refresh saved snapshots"

    @classmethod
    def poll(cls, context):
        return _future is None

    def execute(self, context):
        global _error, _history_notice
        try:
            _refresh_history(context)
        except (OSError, ValueError, TypeError) as exc:
            return _operation_error(self, exc)
        _error = ""
        _history_notice = f"{len(_history_items)} saved snapshot(s)"
        return {"FINISHED"}


class SCOPE_OT_open_session(bpy.types.Operator):
    bl_idname = "addon_scope.open_session"
    bl_label = "View saved snapshot"
    bl_description = "Inspect the saved record without enabling or testing its old add-ons"

    @classmethod
    def poll(cls, context):
        return _future is None and _selected_history(context) is not None

    def execute(self, context):
        global _history_context, _live_snapshot, _last_probe, _last_spec, _error
        from .sessions import load_session
        selected = _selected_history(context)
        try:
            result, probe = load_session(selected["path"])
        except (OSError, ValueError, TypeError) as exc:
            return _operation_error(self, exc)
        wm = context.window_manager
        if _history_context is None:
            _live_snapshot = (_result, _last_probe, _last_spec, _capture_view_state(wm))
        _set_result(result)
        _last_probe = probe
        _last_spec = None
        _history_context = selected
        for prop in ("findings_query", "addons_query", "packages_query", "imports_query"):
            setattr(wm, f"addon_scope_{prop}", "")
        _error = ""
        return {"FINISHED"}


class SCOPE_OT_return_current(bpy.types.Operator):
    bl_idname = "addon_scope.return_current"
    bl_label = "Return to current scan"

    @classmethod
    def poll(cls, context):
        return _future is None and _history_context is not None

    def execute(self, context):
        global _result, _last_probe, _last_spec, _history_context, _live_snapshot, _loaded_items
        result, probe, spec, view_state = _live_snapshot
        _history_context = None
        _live_snapshot = None
        if result is not None:
            _set_result(result)
            _restore_view_state(context.window_manager, view_state)
        else:
            _result = None
            _loaded_items = []
        _last_probe, _last_spec = probe, spec
        return {"FINISHED"}


def _difference_value(field, value):
    if field == "providers" and isinstance(value, list):
        return "\n\n".join(f"{item['name']} {item['version']} ({item['source']})\n{item['path']}"
                            for item in value) or "None recorded"
    if isinstance(value, list):
        return "\n".join(str(item) for item in value) or "None recorded"
    return str(value)


def _difference_records(difference):
    records = []
    for kind, groups in difference.items():
        for action in ("added", "removed", "changed"):
            for entry in groups[action]:
                record = entry.get("after", entry) if action == "changed" else entry
                name = record.get("name") or record.get("id", "Unknown")
                title = f"{kind.title()} · {action} · {name}"
                if action == "changed":
                    lines = [f"{field}\nBefore:\n{_difference_value(field, entry['before'].get(field))}\nAfter:\n{_difference_value(field, entry['after'].get(field))}"
                             for field in entry["fields"]]
                else:
                    lines = [f"{key}:\n{_difference_value(key, value)}" for key, value in record.items()]
                records.append({"title": title, "text": "\n\n".join(lines)})
    return records


class SCOPE_OT_compare_session(bpy.types.Operator):
    bl_idname = "addon_scope.compare_session"
    bl_label = "Compare with current scan"
    bl_description = "Show changes from the selected saved snapshot to the latest scan in this session"

    @classmethod
    def poll(cls, context):
        return _future is None and _selected_history(context) is not None and _current_scan() is not None

    def execute(self, context):
        global _history_diff, _difference_items, _error
        from .sessions import load_session, compare_scans
        selected = _selected_history(context)
        current = _current_scan()
        try:
            before, _ = load_session(selected["path"])
            difference = compare_scans(before, current)
        except (OSError, ValueError, TypeError) as exc:
            return _operation_error(self, exc)
        _history_diff = {"label": selected["label"] or selected["name"],
                         "before": before.created_at, "after": current.created_at}
        _difference_items = _difference_records(difference)
        wm = context.window_manager
        wm.addon_scope_changes.clear()
        for index, record in enumerate(_difference_items):
            item = wm.addon_scope_changes.add()
            item.name, item.search_text, item.index = record["title"], record["title"] + " " + record["text"], index
        wm.addon_scope_changes_index = 0
        wm.addon_scope_changes_query = ""
        _error = ""
        return {"FINISHED"}


class SCOPE_OT_support_bundle(bpy.types.Operator):
    bl_idname = "addon_scope.support_bundle"
    bl_label = "Export support bundle"
    bl_description = "Save a ZIP with this scan, offline report, test logs and a support summary"
    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.zip", options={"HIDDEN"})
    redact_paths: BoolProperty(name="Replace local path prefixes", default=True)

    @classmethod
    def poll(cls, context):
        return _result is not None and _future is None

    def invoke(self, context, event):
        self.filepath = "addon-scope-support.zip"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        self.layout.prop(self, "redact_paths")
        _wrap(self.layout, "Includes the displayed snapshot and captured logs. Review add-on output before sharing; path replacement is not a general privacy filter.", 58)

    def execute(self, context):
        global _history_notice, _error
        from .sessions import write_support_bundle
        try:
            target = write_support_bundle(_result, _last_probe, Path(bpy.path.ensure_ext(self.filepath, ".zip")), self.redact_paths)
        except (OSError, ValueError, TypeError) as exc:
            return _operation_error(self, exc)
        _error = ""
        _history_notice = f"Support bundle saved: {target.name}"
        self.report({"INFO"}, "Support bundle saved; review its logs before sharing")
        return {"FINISHED"}


class SCOPE_OT_export_trial(bpy.types.Operator):
    bl_idname = "addon_scope.export_trial"
    bl_label = "Export trial log"
    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _last_probe is not None and _future is None

    def invoke(self, context, event):
        self.filepath = "addon-scope-trials.json"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        import json
        from .models import ScanResult
        from .report import report_dict
        try:
            data = report_dict(ScanResult(roots=_result.roots, environment={"probe": _last_probe}))
            target = Path(bpy.path.ensure_ext(self.filepath, ".json"))
            target.write_text(json.dumps(data["environment"]["probe"], indent=2), encoding="utf-8")
        except (OSError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, "Trial log saved")
        return {"FINISHED"}


def _field(layout, label, value):
    row = layout.row(align=True)
    row.label(text=label)
    operator = row.operator("addon_scope.copy", text="", icon="COPYDOWN")
    operator.value = str(value)
    for line in str(value).splitlines() or [""]:
        _wrap(layout, line)


def _section(layout, ident, title, values, *, closed=True):
    header, body = layout.panel(ident, default_closed=closed)
    header.label(text=f"{title} ({len(values)})")
    if body is not None:
        if values:
            _field(body, "Full text", "\n".join(str(value) for value in values))
        else:
            body.label(text="None recorded")


def _record_list(layout, wm, kind, index_prop, *, rows=5):
    prop = f"addon_scope_{kind}"
    collection = getattr(wm, prop)
    query_prop = _QUERIES[prop]
    layout.prop(wm, query_prop, text="", icon="VIEWZOOM")
    query = getattr(wm, query_prop).strip().casefold()
    visible = [i for i, item in enumerate(collection) if query in item.search_text.casefold()]
    if query:
        layout.label(text=f"{len(visible)} of {len(collection)} matches")
    if not visible:
        _wrap(layout, "No matches. Clear the search to show all records." if collection else "No records in this scan.")
        return False
    list_type = "SCOPE_UL_findings" if kind == "findings" else "SCOPE_UL_records"
    rows = min(rows, max(2, len(visible)))
    layout.template_list(list_type, kind, wm, prop, wm, index_prop, rows=rows, maxrows=rows)
    if getattr(wm, index_prop) not in visible:
        _wrap(layout, "Select a matching item to see its details.")
        return False
    return True


def _draw_findings(layout, context):
    wm = context.window_manager
    if not _result.findings:
        _wrap(layout, "No metadata findings. Runtime, scene or native-library conflicts may still need a separate reproduction.", icon="CHECKMARK")
        return
    if not _record_list(layout, wm, "findings", "addon_scope_index", rows=4):
        return
    finding = _result.findings[wm.addon_scope_index]
    layout.separator()
    _wrap(layout, finding.title, icon="INFO")
    _wrap(layout, f"{finding.severity.title()} · {finding.code}")
    _wrap(layout, finding.summary)
    _wrap(layout, "Potential conflict" if finding.confidence == "potential" else "Observed evidence")
    from .comparison import package_comparison
    names = {addon.id: addon.name for addon in _result.addons}
    groups = package_comparison(_result, finding)
    if groups:
        layout.separator()
        layout.label(text="Dependency comparison", icon="PACKAGE")
        for group in groups:
            layout.label(text=group["package"])
            for provider in group["providers"]:
                row = layout.row()
                split = row.split(factor=0.65)
                owner = names.get(provider["owner"])
                if owner is None:
                    owner = "Shared environment" if provider["source"] == "installed" else provider["owner"]
                split.label(text=owner or "Shared environment")
                split.label(text=f"{provider['version']} ({provider['source']})")
            if group["loaded"]:
                prefixes = sorted({name.split(".", 1)[0] for name in group["loaded"]})
                for prefix in prefixes:
                    paths = {name: path for name, path in group["loaded"].items()
                             if name == prefix or name.startswith(prefix + ".")}
                    name = prefix if prefix in paths else next(iter(paths))
                    _field(layout, f"Loaded: {name}", paths[name])
                    op = layout.operator("addon_scope.inspect_imports", text=f"Inspect {len(paths)} captured import(s)")
                    op.prefix = prefix
            else:
                _wrap(layout, "Import path not captured. Scan after using the add-ons, or inspect a fresh-process test.")
        _wrap(layout, "Supplied versions are metadata candidates, not proof of the loaded version.")
    else:
        for owner in finding.owners:
            _wrap(layout, names.get(owner, owner))
    if finding.advice:
        layout.separator()
        layout.label(text="Suggested next step")
        _wrap(layout, finding.advice)
    if _probe_addons("FINDING"):
        operator = layout.operator("addon_scope.probe", text="Test affected owners", icon="PLAY")
        operator.source = "FINDING"
    layout.prop(wm, "addon_scope_show_evidence", text=f"Evidence ({len(finding.evidence)})", icon="TRIA_DOWN" if wm.addon_scope_show_evidence else "TRIA_RIGHT", emboss=False)
    if wm.addon_scope_show_evidence and finding.evidence:
        if _record_list(layout, wm, "evidence", "addon_scope_evidence_index", rows=3):
            index = wm.addon_scope_evidence_index
            _field(layout, f"Evidence {index + 1} of {len(finding.evidence)}", finding.evidence[index])


def _draw_inventory(layout, context):
    wm = context.window_manager
    layout.prop(wm, "addon_scope_inventory", expand=True)
    if wm.addon_scope_inventory == "ADDONS":
        if not _record_list(layout, wm, "addons", "addon_scope_addon_index"):
            return
        addon = _result.addons[wm.addon_scope_addon_index]
        layout.separator()
        _wrap(layout, addon.name, icon="PLUGIN")
        state = "Enabled" if addon.enabled is True else "Disabled" if addon.enabled is False else "Enable state unknown"
        _wrap(layout, f"{addon.version or 'Version unknown'} · {state}")
        _field(layout, "Add-on ID", addon.id)
        _field(layout, "Module", addon.module or "Not recorded")
        _field(layout, "Installation path", addon.path)
        layout.label(text=f"Kind: {addon.kind}")
        _section(layout, "scope_addon_wheels", "Declared wheels", addon.wheels)
        packages = [f"{package.name} {package.version} ({package.source})\n{package.path}"
                    for package in _result.distributions if package.owner == addon.id]
        _section(layout, "scope_addon_packages", "Supplied distributions", packages, closed=False)
    else:
        if not _record_list(layout, wm, "packages", "addon_scope_package_index"):
            return
        package = _result.distributions[wm.addon_scope_package_index]
        layout.separator()
        _wrap(layout, f"{package.name} {package.version}", icon="PACKAGE")
        names = {addon.id: addon.name for addon in _result.addons}
        _field(layout, "Owner", names.get(package.owner, package.owner) or "Shared environment")
        layout.label(text=f"Metadata source: {package.source}")
        _wrap(layout, "Installed metadata and bundled wheels are candidates; presence alone does not prove which copy is loaded.")
        _field(layout, "Package path", package.path)
        _section(layout, "scope_package_requires", "Requirements", package.requires, closed=False)
        _section(layout, "scope_package_modules", "Import names", package.modules)
        _section(layout, "scope_package_tags", "Wheel tags", package.tags)
        _section(layout, "scope_package_native", "Native files", package.native_files)


def _draw_imports(layout, context):
    _wrap(layout, "Module paths saved in this historical snapshot. They are not a live observation." if _history_context else
          "Actual module paths captured in this Blender process at scan time. Rescan after loading add-ons.")
    if not _record_list(layout, context.window_manager, "imports", "addon_scope_import_index", rows=6):
        return
    name, path = _loaded_items[context.window_manager.addon_scope_import_index]
    layout.separator()
    _field(layout, "Module", name)
    _field(layout, "Loaded from", path)


def _draw_test(layout, context):
    layout.separator()
    if _history_context is None:
        layout.operator("addon_scope.probe", text="Test enabled add-ons", icon="PLAY")
    if not _last_probe:
        return
    status = _last_probe["status"]
    labels = {"pass": "Registration passed", "fail": "Registration failed",
              "confirmed": "Failure reproduced in the retained subset", "unresolved": "Inconclusive test"}
    prefix = "Saved result" if _history_context else "Last test"
    _wrap(layout, f"{prefix}: {labels.get(status, status)}", icon="CHECKMARK" if status == "pass" else "INFO")
    _wrap(layout, _last_probe.get("reason", ""))
    trials = _last_probe.get("trials") or [_last_probe]
    probe_context = trials[-1].get("context", {})
    if probe_context:
        mode = {"settings": "Current add-on settings", "factory": "Factory defaults"}.get(
            probe_context.get("profile_mode"), "Not recorded")
        _wrap(layout, f"Settings: {mode}")
    options = _last_probe.get("options", {})
    if options.get("timeout"):
        _wrap(layout, f"Limit: {options['timeout']:g}s per trial" +
              (f" · {options['max_runs']} trials maximum" if options.get("max_runs") else ""))
    names = {addon.id: addon.name for addon in _result.addons}
    selected = _last_probe.get("selected", [])
    if selected:
        _wrap(layout, " + ".join(names.get(ident, ident) for ident in selected))
    if status == "fail" and _history_context is None:
        operator = layout.operator("addon_scope.probe", text="Reduce failing combination")
        operator.reduce = True
    header, body = layout.panel("scope_test_details", default_closed=True)
    header.label(text="Test details")
    if body is not None:
        trials = _last_probe.get("trials")
        trial = _last_probe
        if trials:
            wm = context.window_manager
            body.label(text=f"{len(trials)} recorded trials")
            body.prop(wm, "addon_scope_trial_index", text="Trial (starts at 1)")
            index = wm.addon_scope_trial_index - 1
            if not 0 <= index < len(trials):
                _wrap(body, f"Choose a trial from 1 to {len(trials)}.")
                return
            trial = trials[index]
        _wrap(body, f"{trial.get('status', status)} · {trial.get('duration', 0):.2f}s · exit {trial.get('returncode')}")
        _wrap(body, trial.get("reason", ""))
        if trial.get("context", {}).get("settings_sha256"):
            _field(body, "Settings snapshot identity", trial["context"]["settings_sha256"])
        _section(body, "scope_trial_selected", "Selected add-ons", trial.get("selected", []), closed=False)
        _section(body, "scope_trial_modules", "Registration modules", trial.get("modules", []))
        _section(body, "scope_trial_errors", "Errors", trial.get("errors", []), closed=False)
        if trial.get("failure_key"):
            _field(body, "Failure identity", trial["failure_key"])
        loaded = [f"{name}\n{path}" for name, path in trial.get("loaded", {}).items()]
        _section(body, "scope_trial_loaded", "Trial import paths", loaded)
        if trial.get("stdout"):
            _section(body, "scope_trial_stdout", "Process output", trial["stdout"].splitlines())
        body.operator("addon_scope.export_trial", text="Export trial log for sharing", icon="EXPORT")


def _draw_history(layout, context):
    wm = context.window_manager
    layout.prop(wm, "addon_scope_show_history", text="History and sharing", emboss=False,
                icon="TRIA_DOWN" if wm.addon_scope_show_history else "TRIA_RIGHT")
    if not wm.addon_scope_show_history:
        return
    row = layout.row(align=True)
    row.operator("addon_scope.save_session", text="Save snapshot", icon="FILE_TICK")
    row.operator("addon_scope.refresh_history", text="", icon="FILE_REFRESH")
    layout.operator("addon_scope.support_bundle", text="Export support bundle", icon="EXPORT")
    if _history_notice:
        _wrap(layout, _history_notice)
    _wrap(layout, "Snapshots stay on this computer. Save is explicit; a scan does not write history.")
    if not _history_items:
        _wrap(layout, "No saved snapshots listed. Save this scan or refresh history from a previous session.")
        return
    if _record_list(layout, wm, "history", "addon_scope_history_index", rows=3):
        selected = _selected_history(context)
        if selected:
            _wrap(layout, selected["label"] or selected["name"], icon="TIME")
            _wrap(layout, selected["created_at"])
            _wrap(layout, f"{selected['addon_count']} add-ons · {selected['finding_count']} findings · test {selected.get('probe_status') or 'not recorded'}")
            layout.operator("addon_scope.open_session", icon="VIEWZOOM")
            layout.operator("addon_scope.compare_session", icon="ARROW_LEFTRIGHT")
    if _history_diff:
        layout.separator()
        _wrap(layout, f"Changes from {_history_diff['label']} → current scan")
        _wrap(layout, f"Saved: {_history_diff['before']}\nCurrent: {_history_diff['after']}")
        if not _difference_items:
            _wrap(layout, "No add-on, package or captured import changes.", icon="CHECKMARK")
        elif _record_list(layout, wm, "changes", "addon_scope_changes_index", rows=3):
            record = _difference_items[wm.addon_scope_changes_index]
            _wrap(layout, record["title"])
            _field(layout, "Difference", record["text"])


def _draw_scope(layout):
    header, body = layout.panel("scope_scan_details", default_closed=True)
    header.label(text="Scan scope and limitations")
    if body is not None:
        _wrap(body, f"Captured: {_result.created_at}")
        _section(body, "scope_roots", "Inspected roots", _result.roots, closed=False)
        for key, value in _result.environment.items():
            _wrap(body, f"{key}: {value}")
        _wrap(body, "Static findings are leads, not reproduced failures. Copied-profile tests cover background registration; scene actions and native-library interactions can require a separate reproduction.")


class SCOPE_PT_main(bpy.types.Panel):
    bl_label = "AddonScope"
    bl_idname = "SCOPE_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "AddonScope"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Add-on environment diagnostics", icon="VIEWZOOM")
        row = layout.row(align=True)
        row.operator("addon_scope.scan", text="Scan environment", icon="FILE_REFRESH")
        row.operator("addon_scope.export", text="", icon="EXPORT")
        if _future is not None:
            layout.label(text="Reading metadata…" if _job == "scan" else "Testing copied profile…", icon="TIME")
            if _job != "scan":
                names = {addon.id: addon.name for addon in _result.addons} if _result else {}
                stage = _progress_info.get("stage", "preparing").replace("_", " ").title()
                _wrap(layout, f"{stage} · {len(_progress_trials)} completed")
                if _progress_info.get("trial"):
                    _wrap(layout, f"Trial {_progress_info['trial']} · limit {_progress_info['budget']}")
                selected = _progress_info.get("selected", [])
                _wrap(layout, " + ".join(names.get(ident, ident) for ident in selected) or "Empty-profile baseline")
                for trial in _progress_trials[-3:]:
                    _wrap(layout, f"{trial['status']} · {trial['duration']:.2f}s · {len(trial['selected'])} add-ons")
                layout.operator("addon_scope.stop", icon="CANCEL")
        if _error:
            box = layout.box()
            _wrap(box, _error, icon="ERROR")
        if _history_context is not None:
            box = layout.box()
            _wrap(box, "Viewing a saved snapshot", icon="TIME")
            _wrap(box, _history_context["label"] or _history_context["name"])
            _wrap(box, "Captured: " + _result.created_at)
            box.operator("addon_scope.return_current", text="Return to current scan" if _live_snapshot[0] else "Close saved snapshot", icon="LOOP_BACK")
        if _result is None:
            _wrap(layout, "Find shared packages, version collisions and actual import sources. Scanning does not enable or change add-ons.")
            _draw_history(layout, context)
            return
        wm = context.window_manager
        counts = {s: sum(f.severity == s for f in _result.findings) for s in ("error", "warning", "info")}
        layout.separator()
        layout.label(text=f"{len(_result.addons)} add-ons · {len(_result.distributions)} packages")
        layout.label(text=" · ".join(f"{counts[s]} {label}{'' if counts[s] == 1 else 's'}" for s, label in (("error", "error"), ("warning", "warning"), ("info", "note"))))
        layout.prop(wm, "addon_scope_view", expand=True)
        if wm.addon_scope_view == "FINDINGS":
            _draw_findings(layout, context)
        elif wm.addon_scope_view == "INVENTORY":
            _draw_inventory(layout, context)
        else:
            _draw_imports(layout, context)
        _draw_test(layout, context)
        layout.separator()
        _draw_scope(layout)
        _draw_history(layout, context)


_CLASSES = (SCOPE_PG_finding, SCOPE_PG_record, SCOPE_UL_findings, SCOPE_UL_records, SCOPE_OT_copy,
            SCOPE_OT_inspect_imports, SCOPE_OT_scan, SCOPE_OT_export, SCOPE_OT_probe, SCOPE_OT_stop,
            SCOPE_OT_save_session, SCOPE_OT_refresh_history, SCOPE_OT_open_session,
            SCOPE_OT_return_current, SCOPE_OT_compare_session, SCOPE_OT_support_bundle,
            SCOPE_OT_export_trial, SCOPE_PT_main)


_WM_PROPERTIES = ("findings", "index", "show_evidence", "view", "inventory", "trial_index",
                  "evidence", "addons", "packages", "imports", "evidence_index", "addon_index", "package_index", "import_index",
                  "findings_query", "evidence_query", "addons_query", "packages_query", "imports_query",
                  "history", "history_index", "history_query", "changes", "changes_index", "changes_query", "show_history")


def register():
    global _registered
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.addon_scope_findings = CollectionProperty(type=SCOPE_PG_finding)
    bpy.types.WindowManager.addon_scope_index = IntProperty(default=0, update=_refresh_evidence)
    bpy.types.WindowManager.addon_scope_show_evidence = BoolProperty(default=False)
    bpy.types.WindowManager.addon_scope_show_history = BoolProperty(default=False)
    bpy.types.WindowManager.addon_scope_view = EnumProperty(name="View", items=[
        ("FINDINGS", "Findings", "Issues, owners and full evidence"),
        ("INVENTORY", "Inventory", "Installed add-ons and package metadata"),
        ("IMPORTS", "Imports", "Module paths captured in this Blender process"),
    ])
    bpy.types.WindowManager.addon_scope_inventory = EnumProperty(name="Inventory", items=[
        ("ADDONS", "Add-ons", "All inspected add-ons"), ("PACKAGES", "Packages", "All Python distributions"),
    ])
    bpy.types.WindowManager.addon_scope_trial_index = IntProperty(name="Trial", default=1, min=1)
    for kind in ("evidence", "addons", "packages", "imports", "history", "changes"):
        setattr(bpy.types.WindowManager, f"addon_scope_{kind}", CollectionProperty(type=SCOPE_PG_record))
    for kind in ("evidence", "addon", "package", "import", "history", "changes"):
        setattr(bpy.types.WindowManager, f"addon_scope_{kind}_index", IntProperty(default=0, min=0))
    for prop in _QUERIES.values():
        setattr(bpy.types.WindowManager, prop, StringProperty(name="Search", options={"TEXTEDIT_UPDATE"}))
    _registered = True


def unregister():
    global _registered, _pool, _future, _result, _last_probe, _last_spec, _loaded_items, _pending_spec
    global _history_items, _history_context, _live_snapshot, _history_diff, _difference_items, _history_notice, _pending_budget
    _registered = False
    if _pending_spec is not None and _pending_spec.cancel_event is not None:
        _pending_spec.cancel_event.set()
    if bpy.app.timers.is_registered(_complete):
        bpy.app.timers.unregister(_complete)
    if _pool:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None
    _future = None
    _result = None
    _last_probe = None
    _last_spec = None
    _pending_spec = None
    _loaded_items = []
    _history_items = []
    _history_context = None
    _live_snapshot = None
    _history_diff = None
    _difference_items = []
    _history_notice = ""
    _pending_budget = None
    for prop in _WM_PROPERTIES:
        delattr(bpy.types.WindowManager, f"addon_scope_{prop}")
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
