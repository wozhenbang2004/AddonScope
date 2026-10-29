"""Run an incident-derived Sentinel/import-cache reproduction in real Blender.

This is not the original Speckle connector or an assertion about its current
compatibility. The dependency sources are unchanged, pinned upstream copies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from addon_scope.models import Addon
from addon_scope.probe import ProbeSpec, minimize, run_probe
from addon_scope.report import report_dict, write_html, write_json
from addon_scope.scanner import scan

CASE = ROOT / "examples" / "cases" / "sentinel"


def verify_sources(case=CASE):
    manifest = json.loads((case / "sources.json").read_text(encoding="utf-8"))
    for item in manifest["sources"]:
        source = case / "vendor" / item["version"] / "typing_extensions.py"
        raw = source.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError(f"Dependency source checksum does not match: {item['version']}")
        license_path = source.parent / item["license_file"]
        if not license_path.is_file():
            raise ValueError(f"Dependency license is missing: {item['version']}")
        if hashlib.sha256(license_path.read_bytes()).hexdigest() != item["license_sha256"]:
            raise ValueError(f"Dependency license checksum does not match: {item['version']}")
    return manifest


def create_case(directory: Path) -> list[Addon]:
    """Create two minimal legacy add-ons using the pinned real dependency code."""
    manifest = verify_sources()
    addons = []
    for ident, version, feature, name in (
        ("scope_sentinel_old", "4.12.2", "Literal", "Older typing_extensions provider"),
        ("scope_sentinel_consumer", "4.14.0", "Sentinel", "Sentinel consumer"),
    ):
        location = directory / ident
        vendor = location / "vendor"
        vendor.mkdir(parents=True)
        source = CASE / "vendor" / version
        shutil.copyfile(source / "typing_extensions.py", vendor / "typing_extensions.py")
        metadata = vendor / f"typing_extensions-{version}.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: typing_extensions\nVersion: {version}\n", encoding="utf-8")
        (metadata / "top_level.txt").write_text("typing_extensions\n", encoding="utf-8")
        shutil.copyfile(source / "LICENSE", metadata / "LICENSE")
        (location / "__init__.py").write_text(
            f"bl_info = {{'name': {name!r}, 'version': (1, 0, 0), 'blender': (4, 5, 0), 'category': 'Development'}}\n"
            "def register():\n"
            "    import sys\n"
            "    from pathlib import Path\n"
            "    sys.path.insert(0, str(Path(__file__).parent / 'vendor'))\n"
            f"    from typing_extensions import {feature}\n"
            "def unregister():\n"
            "    pass\n", encoding="utf-8")
        addons.append(Addon(ident, name, str(location), version="1.0.0", module=ident, kind="legacy"))
    return addons


def fingerprint(directory):
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


def reproduce(executable, output):
    sources = verify_sources()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="addonscope-sentinel-case-") as temporary:
        directory = Path(temporary)
        addons = create_case(directory)
        before = fingerprint(directory)
        spec = ProbeSpec(str(Path(executable).resolve()), addons, timeout=30,
                         target_modules=["typing_extensions"])
        baseline = run_probe(spec, [])
        singles = [run_probe(spec, [addon.id]) for addon in addons]
        combined = run_probe(spec)
        reversed_order = run_probe(ProbeSpec(spec.executable, list(reversed(addons)),
                                            timeout=30, target_modules=["typing_extensions"]))
        reduction = minimize(spec, max_runs=8)
        if baseline.status != "pass" or any(trial.status != "pass" for trial in singles):
            raise RuntimeError("The baseline or single-addon checks did not pass; inspect the test environment.")
        if combined.status != "fail" or "Sentinel" not in combined.failure_key:
            raise RuntimeError("The expected missing-Sentinel failure was not reproduced.")
        if reversed_order.status != "pass":
            raise RuntimeError("The reverse-order check did not pass.")
        if reduction.status != "confirmed" or reduction.selected != [addon.id for addon in addons]:
            raise RuntimeError("The original ordered pair was not reconfirmed.")
        if fingerprint(directory) != before:
            raise RuntimeError("A probe changed the original case files.")
        result = scan([directory], loaded=combined.loaded)
        if not any(f.code == "PACKAGE_VERSION_COLLISION" for f in result.findings):
            raise RuntimeError("Static scan did not record the dependency version candidates.")
        write_html(result, output / "scan.html")
        write_json(result, output / "scan.json")
        evidence = {
            "case": "sentinel-import-cache", "kind": sources["kind"],
            "original_connector_executed": False,
            "incident_url": sources["incident_url"], "dependency_sources": sources["sources"],
            "blender": subprocess.check_output([spec.executable, "--version"], text=True).splitlines()[0],
            "baseline": baseline.to_dict(), "single_addons": [trial.to_dict() for trial in singles],
            "old_first": combined.to_dict(), "new_first": reversed_order.to_dict(),
            "reduction": reduction.to_dict(), "original_files_unchanged": True,
        }
        result.environment = {"case": evidence}
        evidence = report_dict(result)["environment"]["case"]
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "passed", "kind": sources["kind"],
                      "single_addons": [trial.status for trial in singles],
                      "old_first": combined.status, "new_first": reversed_order.status,
                      "reduction": reduction.status, "trials": len(reduction.trials),
                      "original_files_unchanged": True, "output": str(output)}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "cases" / "sentinel")
    args = parser.parse_args()
    reproduce(args.blender, args.output)


if __name__ == "__main__":
    main()
