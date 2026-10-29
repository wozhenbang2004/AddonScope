"""Launch a local X server and Blender for native interface verification."""

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from addon_scope.probe import _environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", required=True)
    parser.add_argument("--xvfb", default="Xvfb")
    parser.add_argument("--script", type=Path, default=ROOT / "tests" / "blender_integration.py")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--height", type=int, default=1000)
    parser.add_argument("--log", type=Path, default=ROOT / "artifacts" / "verification" / "ui" / "blender-ui.log")
    args = parser.parse_args()
    env = dict(os.environ)
    server = subprocess.Popen([args.xvfb, ":94", "-screen", "0", f"1440x{args.height}x24",
                               "-nolisten", "unix", "-nolisten", "local", "-listen", "tcp", "-ac"],
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", 6094), timeout=0.2):
                    break
            except OSError:
                if server.poll() is not None:
                    raise RuntimeError(server.stderr.read().decode())
                time.sleep(0.1)
        else:
            raise RuntimeError("X server did not become ready")
        with tempfile.TemporaryDirectory(prefix="addonscope-ui-") as directory:
            env = _environment(Path(directory))
            env.update(DISPLAY="127.0.0.1:94", LIBGL_ALWAYS_SOFTWARE="1")
            log = args.log
            log.parent.mkdir(parents=True, exist_ok=True)
            try:
                with log.open("wb") as stream:
                    completed = subprocess.run([
                        args.blender, "--factory-startup", "--offline-mode", "--window-geometry", "0", "0", "1440", str(args.height),
                        "--python-exit-code", "70", "--python", str(args.script.resolve()),
                    ], env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=args.timeout)
            except subprocess.TimeoutExpired:
                print(log.read_text(errors="replace")[-6000:])
                return 2
            print(f"Blender exited {completed.returncode}; log: {log}")
            if completed.returncode or "Traceback (most recent call last)" in log.read_text(errors="replace"):
                print(log.read_text(errors="replace")[-4000:])
                return completed.returncode or 1
            return completed.returncode
    finally:
        server.terminate()
        server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
