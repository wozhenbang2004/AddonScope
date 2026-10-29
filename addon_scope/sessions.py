"""Explicit local diagnostic history and portable support bundles.

Saved files contain data only. Loading a snapshot never imports an inspected
add-on, changes activation, restores preferences or executes captured commands.
"""

from __future__ import annotations

from dataclasses import asdict, fields, replace
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import uuid
from zipfile import ZIP_DEFLATED, ZipFile

from . import __version__
from .models import Addon, Distribution, Finding, ScanResult
from .report import report_dict, write_html

MAX_SESSION_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 50_000
SESSION_FORMAT = "addon-scope-session"
SESSION_VERSION = 1
_ENVIRONMENT_FIELDS = {
    "blender_version", "python_version", "python_full_version", "sys_platform",
    "platform_system", "platform_machine", "implementation_name",
    "platform_python_implementation", "implementation_version", "os_name",
    "platform_release", "platform_version", "extra",
}


def _finite_number(value):
    if type(value) not in {int, float}:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _json_value(value, depth=0):
    if depth > 16:
        raise ValueError("Snapshot data is nested too deeply.")
    if value is None or type(value) in {bool, int}:
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, str):
        if len(value) > 1024 * 1024:
            raise ValueError("A snapshot string exceeds the 1 MiB limit.")
        return
    if isinstance(value, list):
        if len(value) > MAX_RECORDS:
            raise ValueError("A snapshot collection exceeds the record limit.")
        for item in value:
            _json_value(item, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        if len(value) > MAX_RECORDS:
            raise ValueError("A snapshot mapping exceeds the record limit.")
        for key, item in value.items():
            _json_value(key, depth + 1)
            _json_value(item, depth + 1)
        return
    raise ValueError("Snapshot data must contain finite JSON values only.")


def _string_list(value, name):
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} must be a list of strings.")
    return value


def _record(cls, value):
    if not isinstance(value, dict):
        raise ValueError(f"A {cls.__name__} record must be an object.")
    allowed = {field.name for field in fields(cls)}
    if value.keys() - allowed:
        raise ValueError(f"Unknown fields in a {cls.__name__} record.")
    try:
        result = cls(**value)
    except TypeError as exc:
        raise ValueError(f"Incomplete {cls.__name__} record.") from exc
    for key, item in asdict(result).items():
        if key == "enabled":
            if item is not None and type(item) is not bool:
                raise ValueError("Add-on activation must be true, false or unknown.")
        elif key in {"wheels", "requires", "modules", "native_files", "tags", "owners", "evidence", "packages"}:
            _string_list(item, key)
        elif not isinstance(item, str):
            raise ValueError(f"{cls.__name__}.{key} must be a string.")
    if cls is Finding and result.severity not in {"error", "warning", "info"}:
        raise ValueError("Unknown finding severity.")
    return result


def _scan(value):
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("Unsupported diagnostic snapshot schema.")
    allowed = {field.name for field in fields(ScanResult)}
    if value.keys() - allowed:
        raise ValueError("Unknown fields in the diagnostic snapshot.")
    roots = _string_list(value.get("roots"), "roots")
    created_at = value.get("created_at")
    if not isinstance(created_at, str):
        raise ValueError("The diagnostic snapshot needs a captured timestamp.")
    try:
        datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise ValueError("The diagnostic captured timestamp is invalid.") from exc
    loaded = value.get("loaded", {})
    environment = value.get("environment", {})
    if not isinstance(loaded, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in loaded.items()):
        raise ValueError("Captured imports must map module names to paths.")
    if not isinstance(environment, dict):
        raise ValueError("Snapshot environment must be an object.")
    collections = {}
    for key, cls in (("addons", Addon), ("distributions", Distribution), ("findings", Finding)):
        values = value.get(key, [])
        if not isinstance(values, list):
            raise ValueError(f"Snapshot {key} must be a list.")
        collections[key] = [_record(cls, item) for item in values]
    ids = [addon.id for addon in collections["addons"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Add-on IDs must be unique in a saved snapshot.")
    return ScanResult(roots=list(roots), loaded=dict(loaded), environment=environment,
                      created_at=created_at, **collections)


def _probe(value):
    """Keep recorded outcomes, not a ProbeSpec or its raw settings dictionary."""
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("status"), str) or value["status"] not in {"pass", "fail", "unresolved", "confirmed"}:
        raise ValueError("Invalid recorded probe result.")
    result = {"status": value["status"]}
    for key in ("reason", "stdout", "failure_key"):
        if key in value:
            if not isinstance(value[key], str):
                raise ValueError(f"Probe {key} must be a string.")
            result[key] = value[key]
    for key in ("selected", "modules", "errors"):
        if key in value:
            result[key] = list(_string_list(value[key], key))
    if "returncode" in value:
        if value["returncode"] is not None and type(value["returncode"]) is not int:
            raise ValueError("Probe exit code must be an integer or unknown.")
        result["returncode"] = value["returncode"]
    if "duration" in value:
        duration = value["duration"]
        if not _finite_number(duration) or duration < 0:
            raise ValueError("Probe duration must be a finite non-negative number.")
        result["duration"] = duration
    if "loaded" in value:
        loaded = value["loaded"]
        if not isinstance(loaded, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in loaded.items()):
            raise ValueError("Probe imports must map module names to paths.")
        result["loaded"] = dict(loaded)
    if "context" in value:
        context = value["context"]
        if not isinstance(context, dict):
            raise ValueError("Probe context must be an object.")
        if context and (not isinstance(context.get("profile_mode"), str) or context["profile_mode"] not in {"factory", "settings"}):
            raise ValueError("Recorded probe context needs a known profile mode.")
        result["context"] = {}
        for key in ("profile_mode", "settings_sha256"):
            if key in context:
                if not isinstance(context[key], str):
                    raise ValueError(f"Probe context {key} must be a string.")
                result["context"][key] = context[key]
        if "settings_modules" in context:
            result["context"]["settings_modules"] = list(_string_list(context["settings_modules"], "settings_modules"))
        if context.get("profile_mode") == "settings":
            if not re.fullmatch(r"[0-9a-f]{64}", context.get("settings_sha256", "")) or "settings_modules" not in context:
                raise ValueError("Recorded settings context needs a valid snapshot identity and module list.")
        elif context.get("profile_mode") == "factory" and ("settings_sha256" in context or "settings_modules" in context):
            raise ValueError("Factory-mode results cannot claim a copied settings snapshot.")
    if "options" in value:
        options = value["options"]
        if not isinstance(options, dict):
            raise ValueError("Recorded probe options must be an object.")
        result["options"] = {}
        if "timeout" in options:
            timeout = options["timeout"]
            if not _finite_number(timeout) or not 0 < timeout <= 600:
                raise ValueError("Recorded trial timeout must be greater than 0 and at most 600 seconds.")
            result["options"]["timeout"] = timeout
        if "max_runs" in options:
            max_runs = options["max_runs"]
            if type(max_runs) is not int or not 3 <= max_runs <= 100:
                raise ValueError("Recorded trial limit must be an integer from 3 to 100.")
            result["options"]["max_runs"] = max_runs
    if "trials" in value:
        trials = value["trials"]
        if not isinstance(trials, list) or len(trials) > 100:
            raise ValueError("Recorded probe trials must be a list of at most 100 results.")
        if any(not isinstance(trial, dict) or "trials" in trial for trial in trials):
            raise ValueError("Recorded trials cannot contain nested reductions.")
        result["trials"] = [_probe(trial) for trial in trials]
    _json_value(result)
    return result


def _encoded(value):
    _json_value(value)
    raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > MAX_SESSION_BYTES:
        raise ValueError("Diagnostic snapshot exceeds the 32 MiB size limit.")
    return raw


def _atomic_write(path, raw):
    if path.is_symlink():
        raise ValueError("Refusing to replace a symbolic link.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".addonscope-", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_session(directory, result: ScanResult, probe: dict | None = None, label: str = "") -> Path:
    """Save one explicitly requested snapshot without copying add-on settings/files."""
    if not isinstance(label, str) or len(label) > 160:
        raise ValueError("A session label must be at most 160 characters.")
    scan_data = result.to_dict()
    _json_value(scan_data)
    _scan(scan_data)
    now = datetime.now(timezone.utc)
    value = {"format": SESSION_FORMAT, "version": SESSION_VERSION, "label": label.strip(),
             "saved_at": now.isoformat(), "scan": scan_data, "probe": _probe(probe)}
    path = Path(directory) / f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:8]}.json"
    _atomic_write(path, _encoded(value))
    return path


def _read_session(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("A saved diagnostic must be a regular file, not a symbolic link.")
    if path.stat().st_size > MAX_SESSION_BYTES:
        raise ValueError("Saved diagnostic exceeds the 32 MiB size limit.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_SESSION_BYTES + 1)
    if len(raw) > MAX_SESSION_BYTES:
        raise ValueError("Saved diagnostic exceeds the 32 MiB size limit.")
    try:
        value = json.loads(raw)
    except (ValueError, RecursionError) as exc:
        raise ValueError("Saved diagnostic is not valid JSON.") from exc
    _json_value(value)
    if not isinstance(value, dict) or value.get("format") != SESSION_FORMAT or type(value.get("version")) is not int or value["version"] != SESSION_VERSION:
        raise ValueError("Unsupported saved diagnostic format or version.")
    if not isinstance(value.get("label"), str) or len(value["label"]) > 160 or not isinstance(value.get("saved_at"), str):
        raise ValueError("Invalid saved diagnostic metadata.")
    try:
        datetime.fromisoformat(value["saved_at"])
    except ValueError as exc:
        raise ValueError("Invalid saved diagnostic timestamp.") from exc
    scan = _scan(value.get("scan"))
    return value, scan, _probe(value.get("probe"))


def load_session(path) -> tuple[ScanResult, dict | None]:
    """Load data for inspection only; never apply a saved environment."""
    _, scan, probe = _read_session(path)
    return scan, probe


def list_sessions(directory) -> list[dict]:
    """List valid regular snapshots newest first; incomplete/unrelated files are ignored."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    result = []
    for path in directory.glob("*.json"):
        try:
            value, scan, probe = _read_session(path)
        except (OSError, ValueError):
            continue
        result.append({"path": str(path), "name": path.name, "label": value["label"],
                       "created_at": value["saved_at"], "captured_at": scan.created_at,
                       "addon_count": len(scan.addons), "finding_count": len(scan.findings),
                       "probe_status": probe.get("status", "") if probe else ""})
    return sorted(result, key=lambda item: (item["created_at"], item["name"]), reverse=True)


def _changes(before, after):
    added = [after[key] for key in sorted(after.keys() - before.keys())]
    removed = [before[key] for key in sorted(before.keys() - after.keys())]
    changed = []
    for key in sorted(before.keys() & after.keys()):
        fields_changed = sorted(field for field in before[key].keys() | after[key].keys()
                                if before[key].get(field) != after[key].get(field))
        if fields_changed:
            changed.append({"id": key, "before": before[key], "after": after[key], "fields": fields_changed})
    return {"added": added, "removed": removed, "changed": changed}


def _packages(scan):
    result = {}
    for package in scan.distributions:
        ident = json.dumps([package.owner, package.name, package.source], ensure_ascii=False, separators=(",", ":"))
        item = result.setdefault(ident, {"id": ident, "name": package.name, "owner": package.owner,
                                        "source": package.source, "versions": [], "paths": [],
                                        "requirements": [], "modules": [], "native_files": [], "tags": [],
                                        "providers": []})
        provider = asdict(package)
        for key in ("requires", "modules", "native_files", "tags"):
            provider[key] = sorted(set(provider[key]))
        item["providers"].append(provider)
        for key, values in (("versions", [package.version]), ("paths", [package.path]),
                            ("requirements", package.requires), ("modules", package.modules),
                            ("native_files", package.native_files), ("tags", package.tags)):
            item[key] = sorted(set(item[key]) | set(values))
    for item in result.values():
        # Preserve version-to-path associations as well as the compact sets.
        providers = {json.dumps(provider, sort_keys=True, ensure_ascii=False) for provider in item["providers"]}
        item["providers"] = [json.loads(provider) for provider in sorted(providers)]
    return result


def compare_scans(before: ScanResult, after: ScanResult) -> dict:
    """Compare observed metadata; a changed path/version is not proof of causation."""
    return {
        "addons": _changes({item.id: asdict(item) for item in before.addons},
                           {item.id: asdict(item) for item in after.addons}),
        "packages": _changes(_packages(before), _packages(after)),
        "imports": _changes({name: {"name": name, "path": path} for name, path in before.loaded.items()},
                            {name: {"name": name, "path": path} for name, path in after.loaded.items()}),
    }


def _summary(scan_data, probe):
    lines = [f"AddonScope {__version__} support bundle", "", f"Captured: {scan_data['created_at']}",
             f"Add-ons: {len(scan_data['addons'])}; distributions: {len(scan_data['distributions'])}; findings: {len(scan_data['findings'])}",
             "Paths redacted: " + str(scan_data["paths_redacted"]),
             "", "This bundle contains diagnostic evidence, not an executable environment.",
             "It does not contain add-on source, original settings snapshots or external files.",
             "Path replacement is not a privacy guarantee: inspect errors/output before sharing.",
             "Metadata changes alone do not establish a reproduced conflict."]
    for key in ("blender_version", "python_full_version", "platform_system", "platform_machine"):
        if key in scan_data["environment"]:
            lines.append(f"{key}: {scan_data['environment'][key]}")
    lines.extend(["", "Findings:"])
    lines.extend(f"- {item['severity']}: {item['title']} ({item['code']})" for item in scan_data["findings"])
    if probe:
        lines.extend(["", "Recorded test:", f"Status: {probe['status']}", f"Reason: {probe.get('reason', '')}",
                      "Selected add-on IDs: " + ", ".join(probe.get("selected", []))])
        if probe.get("options"):
            lines.append("Run limits: " + json.dumps(probe["options"], ensure_ascii=False, sort_keys=True))
        trials = probe.get("trials") or [probe]
        for index, trial in enumerate(trials, 1):
            lines.append(f"Trial {index}: {trial['status']}; {trial.get('duration', 0):g}s; selected={json.dumps(trial.get('selected', []), ensure_ascii=False)}")
            context = trial.get("context", {})
            if context:
                lines.append("  Conditions: " + json.dumps(context, ensure_ascii=False, sort_keys=True))
            if trial.get("failure_key"):
                lines.append("  Failure identity: " + trial["failure_key"])
        context = trials[-1].get("context", {})
        if context.get("profile_mode") == "settings":
            lines.append("Reproduce with the same add-on settings locally; their values are intentionally omitted.")
        else:
            lines.extend(["", "Local CLI template (replace ROOT/BLENDER and use installed add-on IDs):",
                          "python -m addon_scope probe ROOT --blender BLENDER --addon ADDON_ID --trust-addons --output trials.json"])
    return "\n".join(lines) + "\n"


def write_support_bundle(result: ScanResult, probe: dict | None, path, redact_paths: bool = True) -> Path:
    """Write fixed-name evidence files; never package sources or raw preference snapshots."""
    scan_data = result.to_dict()
    _json_value(scan_data)
    _scan(scan_data)
    recorded = _probe(probe)
    # Environment is intentionally extensible for local history. Sharing it
    # wholesale could accidentally package nested preference snapshots supplied
    # by a caller. Only known scalar platform metadata belongs in a support ZIP.
    shared_environment = {key: value for key, value in result.environment.items()
                          if key in _ENVIRONMENT_FIELDS and type(value) in {str, bool, int, float}}
    shared_result = replace(result, environment=shared_environment)
    exported_scan = report_dict(shared_result, redact_paths)
    exported_probe = report_dict(ScanResult(roots=result.roots, environment={"probe": recorded}), redact_paths)["environment"]["probe"]
    target = Path(path)
    if target.is_symlink():
        raise ValueError("Refusing to replace a symbolic link.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="addonscope-support-") as directory:
        temporary = Path(directory)
        html = write_html(shared_result, temporary / "report.html", redact_paths)
        archive_path = temporary / "support.zip"
        with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
            archive.write(html, "report.html")
            archive.writestr("scan.json", _encoded(exported_scan))
            archive.writestr("trials.json", _encoded(exported_probe))
            archive.writestr("summary.txt", _summary(exported_scan, exported_probe))
        _atomic_write(target, archive_path.read_bytes())
    return target
