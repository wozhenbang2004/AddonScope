"""Install and remove the built ZIP through Blender's actual extension operators."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from addon_scope.probe import _prepare_profile
from addon_scope import __version__

WORKER = '''import bpy, hashlib, importlib, json, sys
from pathlib import Path
arguments = sys.argv[sys.argv.index('--') + 1:]
root, archive, output = map(Path, arguments[:3])
expected_version = arguments[3]
target = root / 'extensions' / 'scope_install'
target.mkdir(parents=True, exist_ok=True)
repo = bpy.context.preferences.extensions.repos.new(name='Scope Install', module='scope_install', custom_directory=str(target), source='USER')
repo.use_custom_directory = True
repo.use_sync_on_startup = False
assert bpy.ops.extensions.package_install_files(filepath=str(archive), repo=repo.module, enable_on_install=True) == {'FINISHED'}
module = 'bl_ext.' + repo.module + '.addon_scope'
assert module in bpy.context.preferences.addons, list(bpy.context.preferences.addons.keys())
addon = importlib.import_module(module)
assert addon.__version__ == expected_version, (addon.__version__, expected_version)
ui = importlib.import_module(module + '.blender_ui')
result = ui._scan(*ui._inputs())
ui._set_result(result)
assert any(a.module == module for a in result.addons), [(a.id,a.module) for a in result.addons]
assert len(bpy.context.window_manager.addon_scope_addons) == len(result.addons)
assert len(bpy.context.window_manager.addon_scope_imports) == len(result.loaded)
assert hasattr(bpy.types, 'SCOPE_PT_main')
index = next(i for i,r in enumerate(bpy.context.preferences.extensions.repos) if r.module == repo.module)
assert bpy.ops.extensions.package_uninstall(repo_index=index, pkg_id='addon_scope') == {'FINISHED'}
assert not (target / 'addon_scope').exists()
assert not hasattr(bpy.types, 'SCOPE_PT_main')
output.write_text(json.dumps({'blender':bpy.app.version_string,'install':'passed','enable':'passed','scan':'passed','uninstall':'passed','archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--archive", type=Path, default=ROOT / "dist" / f"addon-scope-{__version__}.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "verification" / "install.json")
    args = parser.parse_args()
    archive, output = args.archive.resolve(), args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="addonscope-install-") as directory:
        root = Path(directory)
        environment = _prepare_profile(root)
        script = root / "install.py"
        script.write_text(WORKER, encoding="utf-8")
        result = subprocess.run([args.blender, "--background", "--factory-startup", "--offline-mode",
                                 "--python-exit-code", "70", "--python", str(script), "--", str(root), str(archive), str(output), __version__],
                                env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=40)
        output.with_suffix(".log").write_bytes(result.stdout)
        if result.returncode:
            print(result.stdout.decode(errors="replace")[-5000:])
        else:
            print(output.read_text())
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
