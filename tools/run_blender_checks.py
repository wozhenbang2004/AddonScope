"""Run archive validation and generated-fixture integration on an installed host."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from addon_scope import __version__
from addon_scope.probe import _prepare_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    host = parser.add_mutually_exclusive_group(required=True)
    host.add_argument("--blender", type=Path)
    host.add_argument("--blender-file", type=Path)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "ci")
    args = parser.parse_args()
    executable = args.blender or Path(args.blender_file.read_text(encoding="utf-8").strip())
    executable = executable.resolve()
    archive = (args.dist / f"addon-scope-{__version__}.zip").resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not executable.is_file() or not archive.is_file():
        parser.error("The Blender executable and built extension archive must exist.")
    with tempfile.TemporaryDirectory(prefix="addonscope-validation-") as directory:
        checked = subprocess.run([str(executable), "--background", "--factory-startup", "--offline-mode",
                                  "--command", "extension", "validate", str(archive)],
                                 env=_prepare_profile(Path(directory)), capture_output=True, text=True, timeout=60)
        (output / "archive-validation.log").write_text(checked.stdout + checked.stderr, encoding="utf-8")
        if checked.returncode:
            print(checked.stdout + checked.stderr)
            return checked.returncode
    for name, stem, extra in (
        ("blender_install_integration.py", "install", ["--archive", str(archive)]),
        ("blender_scan_integration.py", "scan", []),
        ("blender_probe_integration.py", "probe", []),
        ("blender_settings_integration.py", "settings", []),
    ):
        subprocess.run([sys.executable, str(ROOT / "tests" / name), "--blender", str(executable),
                        "--output", str(output / f"{stem}.json"), *extra], check=True, timeout=180)
    (output / "summary.json").write_text(json.dumps({
        "status": "passed", "addon_scope_version": __version__,
        "platform": platform.system(), "machine": platform.machine(),
        "checks": ["archive-validation", "install-enable-scan-uninstall", "side-effect-free-import-provenance",
                   "shared-wheel-reduction", "settings-snapshot"],
        "scope": "Generated trusted add-ons; background registration only. This is not GUI or community-case validation.",
    }, indent=2) + "\n", encoding="utf-8")
    print("Blender integration suite passed:", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
