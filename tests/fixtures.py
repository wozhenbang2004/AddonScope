"""Small, generated installations for deterministic diagnostics."""

from pathlib import Path
from zipfile import ZipFile


def wheel(directory, name="sample", version="1.0", *, requires=(), modules=None,
          tag="py3-none-any", wheel_tag=None, native=(), extra_members=None, metadata=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{name.replace('-', '_')}-{version}-{tag}.whl"
    path = directory / filename
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    contents = metadata if metadata is not None else (
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n" +
        "".join(f"Requires-Dist: {requirement}\n" for requirement in requires) + "\n"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr(f"{dist_info}/METADATA", contents)
        archive.writestr(f"{dist_info}/WHEEL", f"Wheel-Version: 1.0\nTag: {wheel_tag or tag}\n")
        for module in modules or [name.replace("-", "_")]:
            archive.writestr(f"{module}/__init__.py", "")
        for member in native:
            archive.writestr(member, b"not a real binary")
        for member, content in (extra_members or {}).items():
            archive.writestr(member, content)
    return path


def extension(root, identity, *, wheels=(), name=None, version="1.0.0"):
    path = Path(root) / identity
    path.mkdir(parents=True, exist_ok=True)
    wheel_paths = ", ".join(repr(str(w)) for w in wheels)
    (path / "blender_manifest.toml").write_text(
        f'schema_version = "1.0.0"\nid = "{identity}"\nname = "{name or identity}"\n'
        f'version = "{version}"\ntype = "add-on"\nwheels = [{wheel_paths}]\n', encoding="utf-8")
    (path / "__init__.py").write_text(
        "# The scanner must never execute this file.\nraise RuntimeError('executed fixture')\n", encoding="utf-8")
    return path


def installed(root, name="sample", version="1.0", *, requires=(), modules=None, record=None):
    path = Path(root) / f"{name}-{version}.dist-info"
    path.mkdir(parents=True, exist_ok=True)
    (path / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n" +
        "".join(f"Requires-Dist: {r}\n" for r in requires), encoding="utf-8")
    if modules is not None:
        (path / "top_level.txt").write_text("\n".join(modules), encoding="utf-8")
    if record:
        (path / "RECORD").write_text("\n".join(f"{p},," for p in record), encoding="utf-8")
    return path


def conflict_fixture(root):
    """A consumer needs >=2; two add-ons carry different copies of bridge."""
    root = Path(root)
    first = extension(root, "mesh_tools", wheels=["wheels/consumer-1.0-py3-none-any.whl", "wheels/bridge-1.0-py3-none-any.whl"], name="Mesh Tools")
    wheel(first / "wheels", "consumer", requires=["bridge>=2"])
    wheel(first / "wheels", "bridge", "1.0")
    second = extension(root, "asset_bridge", wheels=["wheels/bridge-2.0-py3-none-any.whl"], name="Asset Bridge")
    wheel(second / "wheels", "bridge", "2.0")
    return root
