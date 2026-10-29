"""Reproduce a shared-wheel conflict using an actual Blender executable.

Run: python tests/blender_probe_integration.py --blender /path/to/blender
The fixture uses only generated source; no downloaded add-ons are executed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from addon_scope.models import Addon
from addon_scope.probe import ProbeSpec, minimize, run_probe


def create_wheel_fixture(root: Path) -> list[Addon]:
    """A and B each work alone, but require different versions of one module."""
    addons = []
    for ident, version, symbol in (
        ("scope_legacy", "1.0.0", "LegacyToken"),
        ("scope_modern", "2.0.0", "ModernToken"),
        ("scope_helper", "", ""),
    ):
        directory = root / ident
        directory.mkdir(parents=True)
        manifest = (
            'schema_version = "1.0.0"\n'
            f'id = "{ident}"\n'
            'version = "1.0.0"\n'
            f'name = "{ident.replace("_", " ").title()}"\n'
            'tagline = "Disposable shared dependency conflict fixture"\n'
            'maintainer = "AddonScope tests"\n'
            'type = "add-on"\n'
            'blender_version_min = "4.2.0"\n'
            'license = ["SPDX:GPL-3.0-or-later"]\n'
        )
        code = "def register():\n    pass\n\ndef unregister():\n    pass\n"
        if version:
            wheel_dir = directory / "wheels"
            wheel_dir.mkdir()
            filename = f"scope_tokens-{version}-py3-none-any.whl"
            distinfo = f"scope_tokens-{version}.dist-info"
            files = {
                "scope_tokens/__init__.py": f"class {symbol}:\n    pass\n__version__ = '{version}'\n",
                f"{distinfo}/METADATA": f"Metadata-Version: 2.1\nName: scope-tokens\nVersion: {version}\n",
                f"{distinfo}/WHEEL": "Wheel-Version: 1.0\nGenerator: AddonScope fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                f"{distinfo}/top_level.txt": "scope_tokens\n",
            }
            files[f"{distinfo}/RECORD"] = "".join(f"{name},,\n" for name in files) + f"{distinfo}/RECORD,,\n"
            with zipfile.ZipFile(wheel_dir / filename, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for name, content in files.items():
                    archive.writestr(name, content)
            manifest += f'wheels = ["./wheels/{filename}"]\n'
            code = f"from scope_tokens import {symbol}\n\n" + code
        (directory / "blender_manifest.toml").write_text(manifest, encoding="utf-8")
        (directory / "__init__.py").write_text(code, encoding="utf-8")
        addons.append(Addon(ident, ident, str(directory), module=f"bl_ext.blender_org.{ident}", kind="extension"))
    return addons


def fingerprint(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def verify_environment_writes(executable: str) -> dict:
    """An ordinary add-on can save common preferences only inside this profile."""
    keys = ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
            "TMPDIR", "TEMP", "TMP")
    with tempfile.TemporaryDirectory(prefix="addonscope-config-fixture-") as temporary:
        root = Path(temporary)
        original = root / "original"
        original.mkdir()
        environment = {}
        for key in keys:
            location = original / key.lower()
            location.mkdir()
            (location / "sentinel.txt").write_text("original configuration", encoding="utf-8")
            environment[key] = str(location)
        environment["BLENDER_SYSTEM_SCRIPTS"] = str(original / "system_scripts")
        (original / "system_scripts").mkdir()
        addon_dir = root / "config_writer"
        addon_dir.mkdir()
        (addon_dir / "__init__.py").write_text(
            "def register():\n"
            "    import os, tempfile\n"
            "    from pathlib import Path\n"
            "    profile = Path(os.environ['BLENDER_USER_RESOURCES'])\n"
            "    assert Path.home().is_relative_to(profile), 'Path.home escaped profile'\n"
            "    paths = [Path.home()]\n"
            f"    paths.extend(Path(os.environ[key]) for key in {keys!r})\n"
            "    paths.append(Path(tempfile.gettempdir()))\n"
            "    for location in paths:\n"
            "        assert location.is_relative_to(profile), str(location)\n"
            "        assert location.is_dir(), 'Expected directories to be pre-created'\n"
            "        (location / 'ordinary-addon-preferences.txt').write_text('probe value')\n"
            "    assert not any(key.startswith('BLENDER_SYSTEM_') for key in os.environ)\n"
            "def unregister():\n"
            "    pass\n", encoding="utf-8")
        before = fingerprint(original)
        addon = Addon("config_writer", "Configuration writer", str(addon_dir),
                      module="config_writer", kind="legacy")
        with patch.dict(os.environ, environment):
            parent_before = dict(os.environ)
            result = run_probe(ProbeSpec(executable, [addon], timeout=30, target_modules=["config_writer"]))
            assert dict(os.environ) == parent_before, "The launcher changed its parent's environment."
        assert result.status == "pass", result.to_dict()
        assert fingerprint(original) == before, "An original home/configuration path was modified."
        return {"status": "passed", "original_configuration_unchanged": True,
                "parent_environment_unchanged": True,
                "checked_variables": list(keys), "probe": result.to_dict()}


def verify_import_collection(executable: str) -> dict:
    """Reading import provenance must not execute lazy-module/proxy hooks."""
    with tempfile.TemporaryDirectory(prefix="addonscope-provenance-fixture-") as temporary:
        source = Path(temporary) / "scope_provenance"
        source.mkdir()
        (source / "deferred.py").write_text(
            "raise RuntimeError('Import-path collection executed a stdlib LazyLoader module')\n",
            encoding="utf-8")
        (source / "__init__.py").write_text('''import sys
import importlib.util
from pathlib import Path
from types import ModuleType
class ImportedProxy:
    def __getattribute__(self, name):
        raise RuntimeError("Import-path collection called an add-on proxy")
def lazy_attribute(name):
    raise RuntimeError("Import-path collection invoked a lazy module")
def register():
    sys.modules["scope_provenance.proxy"] = ImportedProxy()
    lazy = ModuleType("scope_provenance.lazy")
    lazy.__getattr__ = lazy_attribute
    sys.modules["scope_provenance.lazy"] = lazy
    spec = importlib.util.spec_from_file_location(
        "scope_provenance.deferred", Path(__file__).with_name("deferred.py"))
    spec.loader = importlib.util.LazyLoader(spec.loader)
    deferred = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = deferred
    spec.loader.exec_module(deferred)
def unregister():
    pass
''', encoding="utf-8")
        before = fingerprint(source)
        addon = Addon("scope_provenance", "Import provenance fixture", str(source),
                      module="scope_provenance", kind="legacy")
        result = run_probe(ProbeSpec(executable, [addon], target_modules=["scope_provenance"]))
        assert result.status == "pass", result.to_dict()
        assert set(result.loaded) == {"scope_provenance", "scope_provenance.deferred"}, result.loaded
        assert fingerprint(source) == before
        return {"status": "passed", "proxy_hooks_not_called": True, "stdlib_lazyloader_not_executed": True,
                "original_files_unchanged": True, "probe": result.to_dict()}


def verify_failure_identity(executable: str) -> dict:
    """A new error after the profile path must not replace the retained failure."""
    with tempfile.TemporaryDirectory(prefix="addonscope-signature-fixture-") as temporary:
        root = Path(temporary)
        addons = []
        for ident in ("scope_signature_b", "scope_signature_a"):
            source = root / ident
            source.mkdir()
            code = "def register(): pass\ndef unregister(): pass\n"
            if ident.endswith("_a"):
                code = '''import bpy, os
def register():
    reason = "intended dependency failure" if "scope_signature_b" in bpy.context.preferences.addons else "unrelated missing dependency"
    raise RuntimeError(os.environ["BLENDER_USER_RESOURCES"] + ": " + reason)
def unregister():
    pass
'''
            (source / "__init__.py").write_text(code, encoding="utf-8")
            addons.append(Addon(ident, ident, str(source), module=ident, kind="legacy"))
        before = fingerprint(root)
        spec = ProbeSpec(executable, addons, target_modules=["scope_signature_a", "scope_signature_b"])
        original = run_probe(spec)
        different = run_probe(spec, ["scope_signature_a"])
        assert original.status == different.status == "fail", (original.to_dict(), different.to_dict())
        assert "intended dependency failure" in original.failure_key, original.to_dict()
        assert "unrelated missing dependency" in different.failure_key, different.to_dict()
        assert original.failure_key != different.failure_key
        reduction = minimize(spec, max_runs=12)
        assert reduction.status == "confirmed", reduction.to_dict()
        assert reduction.selected == [addon.id for addon in addons], reduction.to_dict()
        assert reduction.trials[-1].failure_key == original.failure_key
        assert fingerprint(root) == before
        return {"status": "passed", "different_reasons_not_merged": True,
                "full_set": original.to_dict(), "different_failure": different.to_dict(),
                "reduction": reduction.to_dict(), "original_files_unchanged": True}


def verify(executable: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="addonscope-wheel-fixture-") as temporary:
        root = Path(temporary)
        addons = create_wheel_fixture(root)
        before = fingerprint(root)
        spec = ProbeSpec(executable, addons, timeout=30, target_modules=["scope_tokens"])
        baseline = run_probe(spec, [])
        assert baseline.status == "pass", baseline.to_dict()
        singles = [run_probe(spec, [addon.id]) for addon in addons]
        assert all(result.status == "pass" for result in singles), [result.to_dict() for result in singles]
        full = run_probe(spec)
        assert full.status == "fail", full.to_dict()
        assert "LegacyToken" in full.failure_key, full.to_dict()
        assert any("site-packages/scope_tokens" in path.replace("\\", "/") for path in full.loaded.values()), full.loaded
        reduction = minimize(spec, max_runs=24)
        assert reduction.status == "confirmed", reduction.to_dict()
        assert reduction.selected == ["scope_legacy", "scope_modern"], reduction.to_dict()
        assert reduction.trials[-1].failure_key == full.failure_key, reduction.to_dict()
        dependent_spec = ProbeSpec(executable, addons, timeout=30,
                                   dependencies={"scope_legacy": ["scope_helper"]},
                                   target_modules=["scope_tokens"])
        dependent = minimize(dependent_spec, max_runs=24)
        assert dependent.status == "confirmed", dependent.to_dict()
        assert dependent.selected == ["scope_legacy", "scope_modern", "scope_helper"], dependent.to_dict()
        assert all("scope_helper" in trial.selected for trial in dependent.trials
                   if "scope_legacy" in trial.selected), dependent.to_dict()
        assert fingerprint(root) == before, "The original add-on fixture changed during a probe."
        return {
            "blender": executable,
            "baseline": baseline.to_dict(),
            "single_addons": [result.to_dict() for result in singles],
            "full_set": full.to_dict(),
            "reduction": reduction.to_dict(),
            "dependency_closure": dependent.to_dict(),
            "original_files_unchanged": True,
            "fixture_files": len(before),
            "configuration_isolation": verify_environment_writes(executable),
            "import_collection": verify_import_collection(executable),
            "failure_identity": verify_failure_identity(executable),
            "scope": "Factory-profile background registration on generated pure-Python wheels only",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = verify(args.blender)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": "passed",
        "single_addons": [result["status"] for result in evidence["single_addons"]],
        "full_set": evidence["full_set"]["status"],
        "reduced_to": evidence["reduction"]["selected"],
        "runs": len(evidence["reduction"]["trials"]),
        "original_files_unchanged": evidence["original_files_unchanged"],
        "output": str(args.output) if args.output else None,
    }, indent=2))


if __name__ == "__main__":
    main()
