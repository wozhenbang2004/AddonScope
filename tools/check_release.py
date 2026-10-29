"""Check release identities, licenses, contents, reproducibility and source recovery."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import tomllib
from zipfile import ZipFile

from build import ROOT, ZIP_TIME, build, checked_version, extension_members, source_members

REQUIRED_LICENSES = (
    "LICENSE", "THIRD_PARTY.md", "_vendor/packaging/LICENSE",
    "_vendor/packaging/LICENSE.APACHE", "_vendor/packaging/LICENSE.BSD",
)


def check_archive(path: Path, expected: dict[str, Path]) -> None:
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError(f"Unexpected or missing release files: {path.name}")
        if archive.testzip() is not None:
            raise ValueError(f"Archive integrity check failed: {path.name}")
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in member.filename:
                raise ValueError(f"Unsafe archive member: {member.filename}")
            if member.date_time != ZIP_TIME or member.create_system != 3 or member.external_attr >> 16 != 0o100644:
                raise ValueError(f"Non-reproducible member metadata: {member.filename}")
            if archive.read(member) != expected[member.filename].read_bytes():
                raise ValueError(f"Release file differs from source: {member.filename}")


def check_release(output: Path, *, expect_tag: str | None = None, rebuild=False, restore_test=False) -> None:
    version = checked_version()
    if expect_tag is not None and expect_tag != "v" + version:
        raise ValueError(f"Release tag must be v{version}, received {expect_tag!r}.")
    extension = output / f"addon-scope-{version}.zip"
    source = output / f"addon-scope-{version}-source.zip"
    check_archive(extension, extension_members())
    check_archive(source, source_members(version))
    with ZipFile(extension) as archive:
        for name in REQUIRED_LICENSES:
            if not archive.read(name).strip():
                raise ValueError(f"Missing license text: {name}")
        manifest = tomllib.loads(archive.read("blender_manifest.toml").decode())
        if manifest["license"] != ["SPDX:GPL-3.0-or-later"] or manifest["version"] != version:
            raise ValueError("Extension license or version does not match its published contract.")
    checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in (extension, source))
    if (output / "SHA256SUMS").read_text(encoding="utf-8") != checksums:
        raise ValueError("SHA256SUMS does not match the release archives.")
    if rebuild:
        with tempfile.TemporaryDirectory(prefix="addonscope-rebuild-") as directory:
            rebuilt = build(Path(directory))
            for original, repeated in zip((extension, source, output / "SHA256SUMS"), rebuilt):
                if original.read_bytes() != repeated.read_bytes():
                    raise ValueError(f"Repeated build differs: {original.name}")
        print("Repeated build is byte-identical.")
    if restore_test:
        with tempfile.TemporaryDirectory(prefix="addonscope-source-check-") as directory:
            with ZipFile(source) as archive:
                archive.extractall(directory)  # Names and exact contents were validated above.
            restored = Path(directory) / f"addon-scope-{version}"
            for required in ("AGENTS.md", "docs/PROJECT.md", "tools/build.py", "tests"):
                if not (restored / required).exists():
                    raise ValueError(f"Source release is missing recovery material: {required}")
            subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
                           cwd=restored, check=True)
        print("Source archive restored and its tests passed.")
    print(f"Release {version}: version, contents, archive metadata, licenses and checksums passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--expect-tag")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--restore-test", action="store_true")
    args = parser.parse_args()
    try:
        check_release(args.output.resolve(), expect_tag=args.expect_tag,
                      rebuild=args.rebuild, restore_test=args.restore_test)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Release check failed: {error}\n")


if __name__ == "__main__":
    main()
