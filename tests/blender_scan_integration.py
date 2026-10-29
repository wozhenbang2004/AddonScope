"""Verify native scan-time provenance never executes a stdlib lazy module."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from addon_scope.probe import _prepare_profile


def inside_blender(output):
    import bpy
    from addon_scope import blender_ui
    with tempfile.TemporaryDirectory(prefix='scope-scan-lazy-') as directory:
        root = Path(directory)
        marker, source = root / 'executed', root / 'lazy.py'
        source.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("executed")\n')
        spec = importlib.util.spec_from_file_location('scope_scan_lazy', source)
        spec.loader = importlib.util.LazyLoader(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules['scope_scan_lazy'] = module
        class ModuleProxy:
            def __getattribute__(self, name):
                marker.write_text('proxy ' + name)
                raise RuntimeError('Scan accessed module proxy')
        sys.modules['scope_scan_proxy'] = ModuleProxy()
        try:
            assert not marker.exists()
            _, loaded, _, _, _ = blender_ui._inputs()
            assert not marker.exists(), 'Scan-time provenance executed a stdlib lazy module'
            assert loaded['scope_scan_lazy'] == str(source)
        finally:
            sys.modules.pop('scope_scan_lazy', None)
            sys.modules.pop('scope_scan_proxy', None)
    output.write_text(json.dumps({'status':'passed','blender':bpy.app.version_string,
                                 'stdlib_lazy_module_not_executed':True,
                                 'module_proxy_not_accessed':True,
                                 'stored_import_path_captured':True},indent=2))
    print('LAZY_SCAN_PASSED',flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blender')
    parser.add_argument('--inside', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None)
    args.output=args.output.resolve();args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.inside:
        inside_blender(args.output)
        return
    with tempfile.TemporaryDirectory(prefix='scope-native-scan-') as directory:
        result=subprocess.run([args.blender,'--background','--factory-startup','--offline-mode',
                               '--disable-autoexec','--python-exit-code','79','--python',__file__,
                               '--','--inside','--output',str(args.output)],
                              env=_prepare_profile(Path(directory)),capture_output=True,text=True,timeout=40)
        if result.returncode or 'LAZY_SCAN_PASSED' not in result.stdout:
            raise RuntimeError(result.stdout+result.stderr)
        print('Native scan stdlib LazyLoader integration passed')

if __name__=='__main__':main()
