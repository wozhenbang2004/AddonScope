"""Build reproducible Blender extension and source archives using the standard library."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import tempfile
import tomllib
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from addon_scope import __version__, bl_info

SOURCE_TREES = ("addon_scope", "tests", "tools", "docs", "examples", ".github")
SOURCE_FILES = (
    "AGENTS.md", "README.md", "README.zh-CN.md", "LICENSE", "THIRD_PARTY.md",
    "pyproject.toml", ".gitignore", ".gitattributes", "CONTRIBUTING.md",
    "SECURITY.md", "CHANGELOG.md", "CODE_OF_CONDUCT.md",
)
EXCLUDED_PARTS = {"__pycache__", ".git", "dist", ".venv", "venv", "node_modules", ".pytest_cache", ".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".pem", ".key"}
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def checked_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        project_version = tomllib.load(stream)["project"]["version"]
    with (ROOT / "addon_scope" / "blender_manifest.toml").open("rb") as stream:
        manifest_version = tomllib.load(stream)["version"]
    if project_version != __version__ or manifest_version != __version__:
        raise ValueError("Package, Python project and Blender manifest versions must agree.")
    if tuple(int(part) for part in __version__.split(".")) != tuple(bl_info["version"]):
        raise ValueError("bl_info version must match the package version.")
    return __version__


def eligible(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.name == ".env" or path.name.startswith(".env.") or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name in {"userpref.blend", "startup.blend"}:
        return False
    if path.is_symlink():
        raise ValueError(f"Release inputs cannot be symbolic links: {relative}")
    return path.is_file()


def extension_members() -> dict[str, Path]:
    members = {
        path.relative_to(ROOT / "addon_scope").as_posix(): path
        for path in sorted((ROOT / "addon_scope").rglob("*")) if eligible(path)
    }
    members["THIRD_PARTY.md"] = ROOT / "THIRD_PARTY.md"
    return members


def source_members(version: str) -> dict[str, Path]:
    members = {}
    prefix = f"addon-scope-{version}/"
    for tree in SOURCE_TREES:
        for path in sorted((ROOT / tree).rglob("*")):
            if eligible(path):
                members[prefix + path.relative_to(ROOT).as_posix()] = path
    for name in SOURCE_FILES:
        path = ROOT / name
        if path.exists() and eligible(path):
            members[prefix + name] = path
    return members


def _write_archive(target: Path, members: dict[str, Path]) -> None:
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name + ".", suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for name, path in sorted(members.items()):
                info = ZipInfo(name, date_time=ZIP_TIME)
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def build(output: Path) -> list[Path]:
    version = checked_version()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    extension = output / f"addon-scope-{version}.zip"
    source = output / f"addon-scope-{version}-source.zip"
    _write_archive(extension, extension_members())
    _write_archive(source, source_members(version))
    checksums = output / "SHA256SUMS"
    checksums.write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                                 for path in (extension, source)), encoding="utf-8", newline="\n")
    return [extension, source, checksums]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    for path in build(args.output):
        print(path)


if __name__ == "__main__":
    main()
