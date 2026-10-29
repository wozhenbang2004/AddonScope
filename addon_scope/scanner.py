"""Read-only inventory of add-on metadata and shared import candidates.

An installed file is evidence of presence, not evidence that Blender imports it.
The optional ``loaded`` snapshot supplies that second, separate observation.
"""

import ast
import csv
import io
import os
import re
import stat
import tomllib
import zipfile
from collections import defaultdict
from email.parser import Parser
from pathlib import Path, PurePosixPath

from .models import Addon, Distribution, Finding, ScanResult
from ._vendor.packaging.markers import default_environment
from ._vendor.packaging.requirements import InvalidRequirement, Requirement
from ._vendor.packaging.tags import parse_tag
from ._vendor.packaging.utils import canonicalize_name, parse_wheel_filename
from ._vendor.packaging.version import InvalidVersion, Version


MAX_METADATA_BYTES = 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100_000
MAX_TREE_ENTRIES = 150_000
MAX_TREE_DEPTH = 16
_NATIVE = re.compile(r"(?:\.dll|\.pyd|\.dylib|\.so(?:\.\d+)*)$", re.I)
_MODULE = re.compile(r"^[A-Za-z_]\w*$")
_IGNORED = {".git", "__pycache__", ".svn", "node_modules"}


def _within(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def _safe_member(name):
    p = PurePosixPath(name)
    return bool(name) and "\\" not in name and not p.is_absolute() and not any(
        part in {"..", ":"} or ":" in part for part in p.parts
    )


def _native(name):
    return bool(_NATIVE.search(name))


def _module_from_record(name):
    """Use wheel/RECORD paths, not a guess based on distribution naming."""
    p = PurePosixPath(name)
    if not p.parts:
        return None
    parts = p.parts
    if parts[0].endswith(".data"):
        if len(parts) < 3 or parts[1] not in {"purelib", "platlib"}:
            return None
        parts = parts[2:]
    first = parts[0]
    if first.endswith((".dist-info", ".egg-info")) or first.startswith("."):
        return None
    if len(parts) == 1:
        if first.endswith(".py"):
            first = first[:-3]
        elif _native(first):
            first = first.split(".", 1)[0]
        else:
            return None
    return first if _MODULE.fullmatch(first) else None


class _Scanner:
    def __init__(self, roots, loaded, enabled, environment):
        self.result = ScanResult(roots=[], loaded=dict(loaded or {}), environment=dict(environment or {}))
        self.enabled = enabled
        self.target = environment or {}
        self.files = set()
        self.addon_roots = {}
        self.seen_distributions = set()
        self.seen_wheels = set()
        self.roots = []
        for value in roots:
            try:
                path = Path(value).expanduser().resolve()
            except (OSError, RuntimeError) as exc:
                self.issue("ROOT_UNREADABLE", "warning", "Cannot inspect this path", str(exc), evidence=[str(value)])
                continue
            if path not in self.roots:
                self.roots.append(path)
        self.result.roots = [str(p) for p in self.roots]

    def issue(self, code, severity, title, summary, *, owners=None, evidence=None, advice="", confidence="observed", packages=None):
        self.result.findings.append(Finding(code, severity, title, summary, owners or [], evidence or [], advice, confidence, packages or []))

    def read(self, path, owner=None):
        try:
            if path.is_symlink() or not any(_within(path, root if root.is_dir() else root.parent) for root in self.roots):
                raise ValueError("Metadata points outside the inspected roots or is a symbolic link")
            with path.open("rb") as handle:
                raw = handle.read(MAX_METADATA_BYTES + 1)
            if len(raw) > MAX_METADATA_BYTES:
                raise ValueError(f"Metadata exceeds {MAX_METADATA_BYTES} bytes")
            return raw.decode("utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            self.issue("METADATA_UNREADABLE", "warning", "Metadata could not be read", str(exc),
                       owners=[owner] if owner else [], evidence=[str(path)])
            return None

    def walk(self):
        seen = set()
        total = 0
        skipped = 0
        for root in self.roots:
            if not root.exists():
                self.issue("ROOT_MISSING", "error", "Scan path does not exist", "Choose an existing add-on or package directory.", evidence=[str(root)])
                continue
            if root.is_file():
                self.files.add(root)
                if root.name == "blender_manifest.toml":
                    self._walk_tree(root.parent, seen)
                continue
            pending = [(root, 0)]
            while pending:
                directory, depth = pending.pop()
                if directory in seen:
                    continue
                seen.add(directory)
                try:
                    with os.scandir(directory) as entries:
                        children = sorted(entries, key=lambda e: e.name)
                except OSError as exc:
                    self.issue("DIRECTORY_UNREADABLE", "warning", "Directory could not be inspected", str(exc), evidence=[str(directory)])
                    continue
                for entry in children:
                    total += 1
                    if total > MAX_TREE_ENTRIES:
                        self.issue("SCAN_LIMIT", "warning", "Inventory is incomplete", f"Stopped after {MAX_TREE_ENTRIES:,} entries. Scan narrower directories.", evidence=[str(root)])
                        return
                    try:
                        if entry.is_symlink():
                            skipped += 1
                            continue
                        p = Path(entry.path)
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in _IGNORED:
                                continue
                            if depth >= MAX_TREE_DEPTH:
                                self.issue("SCAN_DEPTH_LIMIT", "warning", "A nested directory was skipped", f"Maximum scan depth is {MAX_TREE_DEPTH}.", evidence=[str(p)])
                            else:
                                pending.append((p, depth + 1))
                        elif entry.is_file(follow_symlinks=False):
                            self.files.add(p)
                    except OSError:
                        continue
        if skipped:
            self.issue("SYMLINKS_SKIPPED", "info", "Symbolic links were skipped", f"{skipped} symbolic link(s) were not followed. Scan a target directory explicitly to include it.")

    def _walk_tree(self, directory, seen):
        # A manifest file is accepted as a convenient input; its siblings are in scope.
        if directory not in self.roots:
            self.roots.append(directory)
            self.result.roots.append(str(directory))

    def add_addon(self, path, identity, name, version, kind, wheels=None):
        module = path.stem if path.is_file() else path.name
        if kind == "extension" and path.parent.parent.name == "extensions":
            module = f"bl_ext.{path.parent.name}.{path.name}"
            identity = module
        original = str(identity or module)
        used = {a.id for a in self.result.addons}
        identity = original
        suffix = 1
        while identity in used:
            suffix += 1
            identity = f"{original}@{path.parent.name}:{suffix}"
        addon = Addon(identity, str(name or identity), str(path), str(version or ""), module,
                      None if self.enabled is None else module in self.enabled or identity in self.enabled,
                      kind, list(wheels or []))
        self.result.addons.append(addon)
        self.addon_roots[path] = addon
        return addon

    def discover_addons(self):
        for manifest in sorted(p for p in self.files if p.name == "blender_manifest.toml"):
            text = self.read(manifest)
            if text is None:
                continue
            try:
                data = tomllib.loads(text)
                identity = data.get("id", manifest.parent.name)
                if not isinstance(identity, str) or not _MODULE.fullmatch(identity):
                    raise ValueError("Manifest id must be a Python identifier")
                wheels = data.get("wheels", [])
                if not isinstance(wheels, list) or not all(isinstance(w, str) for w in wheels):
                    raise ValueError("Manifest wheels must be a list of relative paths")
                if data.get("type", "add-on") != "add-on":
                    continue
                addon = self.add_addon(manifest.parent, identity, data.get("name"), data.get("version"), "extension", wheels)
                for wheel in wheels:
                    if not _safe_member(wheel):
                        self.issue("UNSAFE_WHEEL_PATH", "error", "Wheel path escapes the extension", "Manifest wheel paths must stay inside their extension directory.", owners=[addon.id], evidence=[wheel])
                        continue
                    declared_path = manifest.parent / wheel
                    try:
                        path = declared_path.resolve()
                    except (OSError, RuntimeError, ValueError) as exc:
                        self.issue("WHEEL_PATH_UNREADABLE", "warning", "A declared wheel path could not be resolved", str(exc), owners=[addon.id], evidence=[str(declared_path)])
                        continue
                    if not _within(path, manifest.parent):
                        self.issue("UNSAFE_WHEEL_PATH", "error", "Wheel path escapes the extension", "A symbolic-link or relative path points outside the extension.", owners=[addon.id], evidence=[wheel])
                        continue
                    try:
                        # Non-strict resolve() can retain a symlink loop on
                        # Python 3.13. is_file() hides that OS error as False;
                        # stat() keeps an unreadable path distinct from missing.
                        is_file = stat.S_ISREG(path.stat().st_mode)
                    except (FileNotFoundError, NotADirectoryError):
                        is_file = False
                    except OSError as exc:
                        self.issue("WHEEL_PATH_UNREADABLE", "warning", "A declared wheel path could not be inspected", str(exc), owners=[addon.id], evidence=[str(path)])
                        continue
                    if not is_file:
                        self.issue("WHEEL_MISSING", "error", "A declared wheel is missing", "Blender cannot install this dependency from the declared path.", owners=[addon.id], evidence=[str(path)])
                    elif path not in self.files:
                        self.issue("WHEEL_NOT_INSPECTED", "warning", "A declared wheel was not inventoried", "A scan limit or skipped symbolic link prevented inspection. Scan its directory explicitly.", owners=[addon.id], evidence=[str(path)])
                    else:
                        self.wheel(path, addon.id)
            except (tomllib.TOMLDecodeError, ValueError, TypeError) as exc:
                self.issue("MANIFEST_INVALID", "error", "Extension manifest could not be parsed", str(exc), evidence=[str(manifest)])
        for path in sorted(p for p in self.files if p.suffix == ".py"):
            if any(_within(path, parent) for parent in self.addon_roots):
                continue
            # Only package entry points or single-file add-ons can define bl_info.
            if path.name != "__init__.py" and path.parent.name != "addons" and path not in self.roots and path.parent not in self.roots:
                continue
            text = self.read(path)
            if text is None or "bl_info" not in text:
                continue
            try:
                tree = ast.parse(text)
                info = None
                for statement in tree.body:
                    if isinstance(statement, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "bl_info" for t in statement.targets):
                        info = ast.literal_eval(statement.value)
                        break
                if not isinstance(info, dict):
                    continue
                version = info.get("version", "")
                if isinstance(version, (tuple, list)):
                    version = ".".join(str(x) for x in version)
                directory = path.parent if path.name == "__init__.py" else path
                self.add_addon(directory, directory.stem if directory.is_file() else directory.name, info.get("name"), version, "legacy")
            except (SyntaxError, ValueError, TypeError, RecursionError):
                # Dynamic bl_info cannot be evaluated safely and is not a metadata error.
                continue

    def owner(self, path):
        matches = [(len(str(parent)), addon.id) for parent, addon in self.addon_roots.items() if _within(path, parent)]
        return max(matches)[1] if matches else f"shared:{path.parent.parent}"

    def metadata(self, text, path, owner, source, modules, native_files, tags):
        try:
            message = Parser().parsestr(text)
            name = message.get("Name")
            version = message.get("Version")
            if not name or not version or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
                raise ValueError("METADATA needs valid Name and Version headers")
            Version(version)
            record = Distribution(canonicalize_name(name), version, str(path), owner, source,
                                  message.get_all("Requires-Dist", []), sorted(set(modules)),
                                  sorted(set(native_files)), sorted(set(tags)))
            key = (record.path, owner)
            if key not in self.seen_distributions:
                self.seen_distributions.add(key)
                self.result.distributions.append(record)
        except (ValueError, InvalidVersion) as exc:
            self.issue("DISTRIBUTION_METADATA_INVALID", "warning", "Package metadata is incomplete or invalid", str(exc), owners=[owner], evidence=[str(path)])

    def wheel_relevant(self, tags):
        if not self.target or not tags:
            return True
        py = str(self.target.get("python_version", ""))
        sys_platform = str(self.target.get("sys_platform", ""))
        machine = str(self.target.get("platform_machine", "")).lower()
        implementation = str(self.target.get("implementation_name") or self.target.get("platform_python_implementation", "")).lower()
        expected_family = {"cpython": "cp", "pypy": "pp", "ironpython": "ip", "jython": "jy"}.get(implementation)
        try:
            python_version = tuple(int(part) for part in py.split(".")[:2]) if py else ()
        except ValueError:
            python_version = ()
        for tag in tags:
            platform = tag.platform
            if sys_platform and platform != "any":
                families = {"win32": ("win",), "linux": ("linux", "manylinux", "musllinux"), "darwin": ("macosx",)}
                if sys_platform in families and not platform.startswith(families[sys_platform]):
                    continue
            if machine and platform != "any" and "universal2" not in platform:
                if machine in {"x86_64", "amd64"} and any(x in platform for x in ("aarch64", "arm64", "win32")):
                    continue
                if machine in {"aarch64", "arm64"} and any(x in platform for x in ("x86_64", "amd64", "i686")):
                    continue
            match = re.fullmatch(r"([a-z]+)(\d+)", tag.interpreter)
            if not match:
                if expected_family:
                    continue
                return True
            family, digits = match.groups()
            tagged_version = (int(digits[0]), int(digits[1:])) if len(digits) > 1 else (int(digits),)
            if family != "py" and expected_family and family != expected_family:
                continue
            if family == "py":
                # Generic pure-Python wheels may target an earlier minor release.
                if tag.abi != "none":
                    continue
                if python_version and (tagged_version[0] != python_version[0] or tagged_version > python_version):
                    continue
            else:
                stable_abi = family == "cp" and tag.abi == "abi3"
                if python_version and tagged_version != python_version:
                    if not (stable_abi and tagged_version[0] == python_version[0] and tagged_version <= python_version):
                        continue
                if family == "cp" and tag.abi not in {"none", "abi3", f"cp{digits}"}:
                    continue
                if family == "pp" and tag.abi != "none" and not tag.abi.startswith(f"pypy{digits}_"):
                    continue
            return True
        return False

    def wheel(self, path, owner):
        if path in self.seen_wheels:
            return
        self.seen_wheels.add(path)
        tags = set()
        try:
            _, _, _, tags = parse_wheel_filename(path.name)
        except ValueError:
            self.issue("WHEEL_FILENAME_INVALID", "warning", "Wheel filename is not a valid target tag", "The metadata can be inspected, but Blender may reject this wheel.", owners=[owner], evidence=[str(path)])
        if not self.wheel_relevant(tags):
            self.issue("WHEEL_TARGET_SKIPPED", "info", "Wheel targets a different environment", "This wheel was excluded from dependency comparison for the supplied target.", owners=[owner], evidence=[str(path), ", ".join(sorted(str(t) for t in tags))])
            return
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) > MAX_ARCHIVE_MEMBERS:
                    raise ValueError(f"Wheel has more than {MAX_ARCHIVE_MEMBERS:,} members")
                unsafe = [m.filename for m in members if not _safe_member(m.filename)]
                if unsafe:
                    self.issue("UNSAFE_WHEEL_MEMBER", "error", "Wheel contains unsafe file paths", "The archive was not extracted or executed.", owners=[owner], evidence=[str(path), *unsafe[:8]])
                    return
                metadata = [m for m in members if len(PurePosixPath(m.filename).parts) == 2 and m.filename.endswith(".dist-info/METADATA")]
                if len(metadata) != 1:
                    raise ValueError("Expected exactly one top-level .dist-info/METADATA entry")
                def read_member(info):
                    if info.file_size > MAX_METADATA_BYTES:
                        raise ValueError("Wheel metadata exceeds the inspection limit")
                    with archive.open(info) as handle:
                        raw = handle.read(MAX_METADATA_BYTES + 1)
                    if len(raw) > MAX_METADATA_BYTES:
                        raise ValueError("Wheel metadata exceeds the inspection limit")
                    return raw.decode("utf-8")
                text = read_member(metadata[0])
                metadata_dir = metadata[0].filename.rsplit("/", 1)[0]
                wheel_info = next((m for m in members if m.filename == metadata_dir + "/WHEEL"), None)
                if wheel_info:
                    wheel_headers = Parser().parsestr(read_member(wheel_info))
                    declared_tags = set()
                    try:
                        for value in wheel_headers.get_all("Tag", []):
                            declared_tags.update(parse_tag(value))
                    except ValueError:
                        self.issue("WHEEL_TAG_INVALID", "warning", "Wheel has invalid compatibility metadata", "A Tag header could not be parsed.", owners=[owner], evidence=[str(path)])
                    if declared_tags and tags and declared_tags != tags:
                        self.issue("WHEEL_TAG_MISMATCH", "warning", "Wheel compatibility tags disagree", "The filename and WHEEL metadata declare different target tags. Filename tags were used for target filtering.", owners=[owner], evidence=[str(path), "Filename: " + ", ".join(sorted(str(t) for t in tags)), "WHEEL: " + ", ".join(sorted(str(t) for t in declared_tags))])
                    if not tags:
                        tags = declared_tags
                else:
                    self.issue("WHEEL_METADATA_INCOMPLETE", "warning", "Wheel compatibility metadata is missing", "The archive contains package METADATA but no WHEEL metadata. Blender may reject it.", owners=[owner], evidence=[str(path)])
                top = metadata_dir + "/top_level.txt"
                top_info = next((m for m in members if m.filename == top), None)
                modules = [line.strip() for line in read_member(top_info).splitlines() if _MODULE.fullmatch(line.strip())] if top_info else []
                if not modules:
                    modules = [value for m in members if not m.is_dir() for value in [_module_from_record(m.filename)] if value]
                self.metadata(text, path, owner, "wheel", modules,
                              [m.filename for m in members if _native(m.filename)], [str(t) for t in tags])
        except (OSError, zipfile.BadZipFile, ValueError, UnicodeError, RuntimeError, NotImplementedError) as exc:
            self.issue("WHEEL_UNREADABLE", "error", "Wheel could not be inspected", str(exc), owners=[owner], evidence=[str(path)])

    def installed(self):
        for path in sorted(p for p in self.files if p.name == "METADATA" and p.parent.name.endswith(".dist-info")):
            owner = self.owner(path)
            text = self.read(path, owner)
            if text is None:
                continue
            modules = []
            native_files = []
            top = path.parent / "top_level.txt"
            if top in self.files:
                top_text = self.read(top, owner)
                if top_text:
                    modules = [s.strip() for s in top_text.splitlines() if _MODULE.fullmatch(s.strip())]
            record = path.parent / "RECORD"
            if record in self.files:
                contents = self.read(record, owner)
                if contents:
                    record_modules = []
                    try:
                        for row in csv.reader(io.StringIO(contents)):
                            if not row or not _safe_member(row[0]):
                                continue
                            value = _module_from_record(row[0])
                            if value:
                                record_modules.append(value)
                            if _native(row[0]):
                                native_files.append(str(path.parent.parent / row[0]))
                    except csv.Error as exc:
                        self.issue("RECORD_INVALID", "warning", "Package file inventory could not be parsed", str(exc), owners=[owner], evidence=[str(record)])
                    if not modules:
                        modules = record_modules
            source = "bundled" if owner in {a.id for a in self.result.addons} else "installed"
            self.metadata(text, path.parent, owner, source, modules, native_files, [])

    def compare(self):
        packages = defaultdict(list)
        modules = defaultdict(list)
        native = defaultdict(list)
        for dist in self.result.distributions:
            packages[dist.name].append(dist)
            for module in dist.modules:
                modules[module].append(dist)
            for file in dist.native_files:
                native[PurePosixPath(file).name.lower()].append((dist.owner, f"{dist.path}: {file}"))
        for name, records in sorted(packages.items()):
            owners = sorted({d.owner for d in records})
            versions = sorted({d.version for d in records})
            if len(owners) > 1 and len(versions) > 1:
                self.issue("PACKAGE_VERSION_COLLISION", "warning", f"Multiple versions of {name}",
                           "Different owners supply different versions. Blender extensions can share a site-packages directory; presence alone does not prove which version wins.",
                           owners=owners, evidence=[f"{d.owner}: {d.name} {d.version} — {d.path}" for d in records],
                           advice="Compare Requires-Dist constraints and the runtime import path. Test the affected owners in a copied profile before changing installations.", confidence="potential", packages=[name])
        marker_env = default_environment()
        marker_env.update({key: str(value) for key, value in self.target.items() if key in marker_env})
        marker_env["extra"] = ""
        for dist in self.result.distributions:
            for raw in dist.requires:
                try:
                    requirement = Requirement(raw)
                    if requirement.marker and not requirement.marker.evaluate(marker_env):
                        continue
                except (InvalidRequirement, ValueError) as exc:
                    self.issue("REQUIREMENT_INVALID", "warning", f"Invalid dependency metadata in {dist.name}", str(exc), owners=[dist.owner], evidence=[raw, dist.path])
                    continue
                candidates = packages.get(canonicalize_name(requirement.name), [])
                if not candidates:
                    self.issue("DEPENDENCY_NOT_IN_INVENTORY", "info", f"{requirement.name} is outside this inventory", "A declared dependency was not found in the scanned metadata. Blender's own packages or unscanned directories may provide it.", owners=[dist.owner], evidence=[f"{dist.name} {dist.version} requires {raw}", dist.path], confidence="potential")
                    continue
                if requirement.url:
                    continue
                incompatible = [d for d in candidates if requirement.specifier and not requirement.specifier.contains(d.version, prereleases=None)]
                if incompatible:
                    all_bad = len(incompatible) == len(candidates)
                    self.issue("DEPENDENCY_VERSION_MISMATCH", "error" if all_bad else "warning", f"{dist.name} requires {requirement}",
                               "No inventoried provider satisfies this declared version constraint." if all_bad else "Some inventoried providers violate this declared version constraint; the selected import determines the outcome.",
                               owners=sorted({dist.owner, *(d.owner for d in incompatible)}),
                               evidence=[f"Requirement: {raw} ({dist.path})", *[f"Supplied: {d.name} {d.version} by {d.owner} — {d.path}" for d in candidates]],
                               advice="Check the runtime import source, then ask the affected add-on maintainers for compatible dependency versions. Do not replace Blender's packages blindly.", confidence="potential", packages=[canonicalize_name(requirement.name)])
        for name, records in sorted(modules.items()):
            owners = sorted({d.owner for d in records})
            if len(owners) > 1 and len({d.name for d in records}) > 1:
                self.issue("MODULE_NAME_COLLISION", "warning", f"Different packages provide {name}", "These distributions expose the same top-level Python import. Some namespace packages intentionally share a name; this is a candidate to investigate.", owners=owners, evidence=[f"{d.name} {d.version}: {d.path}" for d in records], confidence="potential", packages=sorted({d.name for d in records}))
            loaded = self.result.loaded.get(name)
            if not loaded:
                loaded = next((v for k, v in self.result.loaded.items() if k.startswith(name + ".")), None)
            if loaded:
                matched = []
                for d in records:
                    base = Path(d.path).parent if d.source != "wheel" else Path(next((a.path for a in self.result.addons if a.id == d.owner), str(Path(d.path).parent)))
                    if _within(loaded, base):
                        matched.append(d.owner)
                if len(owners) > 1:
                    self.issue("IMPORT_PROVENANCE", "info", f"{name} is loaded from this path", "This is the observed runtime import source. Other providers are present in the inventory; their presence is not proof that they are active.", owners=owners, evidence=[str(loaded), f"Matching inventoried owner(s): {', '.join(sorted(set(matched))) or 'none'}"], advice="Attach this path and the affected owners when reporting a dependency conflict.", packages=sorted({d.name for d in records}))
                elif not matched:
                    self.issue("EXTERNAL_IMPORT_SOURCE", "info", f"{name} was imported from another location", "The loaded module is outside the inventoried provider location. It may be Blender's bundled copy or a path inserted by another add-on.", owners=owners, evidence=[str(loaded), *[d.path for d in records]])
        for path in self.files:
            if _native(path.name):
                owner = self.owner(path)
                if owner in {a.id for a in self.result.addons}:
                    native[path.name.lower()].append((owner, str(path)))
        for name, items in sorted(native.items()):
            owners = sorted({owner for owner, _ in items})
            if len(owners) > 1:
                self.issue("NATIVE_LIBRARY_OVERLAP", "warning", f"Shared native library name: {name}", "Multiple owners contain this native filename. Symbol, ABI or loader conflicts require a runtime reproduction; matching filenames alone do not establish a conflict.", owners=owners, evidence=sorted({value for _, value in items}), advice="Use an isolated registration probe and retain the process log. Updating Python package metadata alone may not fix native symbol conflicts.", confidence="potential")

    def run(self):
        self.walk()
        self.discover_addons()
        self.installed()
        self.compare()
        self.result.addons.sort(key=lambda a: (a.name.casefold(), a.id))
        self.result.distributions.sort(key=lambda d: (d.name, d.owner, d.version, d.path))
        self.result.findings.sort(key=lambda f: ({"error": 0, "warning": 1, "info": 2}[f.severity], f.code, f.title))
        return self.result


def scan(roots, *, loaded=None, enabled=None, environment=None):
    """Inspect directories without importing or modifying their add-ons.

    ``environment`` accepts PEP 508 marker keys (notably python_version,
    sys_platform, platform_machine and implementation_name). When supplied, clearly
    incompatible wheel targets are omitted from comparison. Interpreter families
    are excluded only when the target implementation is known. Without a target,
    all wheels are retained.
    ``loaded`` maps module names to their observed ``__file__`` paths.
    """
    return _Scanner(roots, loaded, enabled, environment).run()
