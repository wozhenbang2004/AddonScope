"""Fetch the pinned official Blender build used by integration workflows.

SHA256 values come from
https://download.blender.org/release/Blender4.5/blender-4.5.15.sha256.
Downloading/extracting a host does not establish that the tests passed on it.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen
from zipfile import ZipFile

VERSION = "4.5.15"
BUILDS = {
    "linux-x64": ("tar.xz", "0d2b8bb2efe97e6c8eb57de6b7322f8800e1984e3125b60decca5f6771e4773e"),
    "windows-x64": ("zip", "52dd02fd74877fa08e74b67d7854cf32468a232c02aaa19b6844c91285574f8d"),
    "macos-arm64": ("dmg", "bfbc0bda099d1ab7aef0992a584f872f58bed9bb491210ad45f9ca071aa2e688"),
    "macos-x64": ("dmg", "3801a97619292a012ede0e855ee705ae872a680474845297b777254f7f21ed78"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_dmg(archive: Path, destination: Path) -> Path:
    attached = subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-plist", str(archive)],
                              check=True, stdout=subprocess.PIPE)
    entities = plistlib.loads(attached.stdout)["system-entities"]
    mount = next((Path(item["mount-point"]) for item in entities if "mount-point" in item), None)
    if mount is None:
        raise ValueError("Blender disk image did not provide a mount point.")
    try:
        app = mount / "Blender.app"
        if not app.is_dir():
            raise ValueError("Official Blender disk image did not contain Blender.app.")
        shutil.copytree(app, destination / app.name, symlinks=True)
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], check=True)
    return destination / "Blender.app" / "Contents" / "MacOS" / "Blender"


def fetch(platform: str, directory: Path) -> Path:
    suffix, expected = BUILDS[platform]
    basename = f"blender-{VERSION}-{platform}"
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "extracted"
    if target.exists():
        raise ValueError("The extraction directory already exists; use a fresh download directory.")
    archive = directory / f"{basename}.{suffix}"
    if not archive.exists():
        url = f"https://download.blender.org/release/Blender4.5/{archive.name}"
        temporary = archive.with_suffix(archive.suffix + ".part")
        try:
            with urlopen(url, timeout=120) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, 1024 * 1024)
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    if _sha256(archive) != expected:
        raise ValueError("Blender archive failed the pinned official SHA256 check.")
    with tempfile.TemporaryDirectory(prefix="extract-", dir=directory) as temporary:
        staging = Path(temporary)
        if suffix == "tar.xz":
            with tarfile.open(archive) as package:
                package.extractall(staging, filter="data")
            executable = staging / basename / "blender"
        elif suffix == "zip":
            with ZipFile(archive) as package:
                for name in package.namelist():
                    path = PurePosixPath(name)
                    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
                        raise ValueError("Unsafe member in Blender ZIP.")
                package.extractall(staging)
            executable = staging / basename / "blender.exe"
        else:
            executable = _extract_dmg(archive, staging)
        if not executable.is_file():
            raise ValueError("Blender executable was not found in the verified archive.")
        relative = executable.relative_to(staging)
        # A new target avoids merging a downloaded application with an old tree.
        staging.rename(target)
    return target / relative


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=sorted(BUILDS), required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--executable-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        executable = fetch(args.platform, args.directory)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Blender setup failed: {error}\n")
    args.executable_file.parent.mkdir(parents=True, exist_ok=True)
    args.executable_file.write_text(executable.as_posix() + "\n", encoding="utf-8", newline="\n")
    print(f"Verified official Blender {VERSION}: {executable}")


if __name__ == "__main__":
    main()
