"""Generate an explicitly synthetic, reproducible shared-wheel conflict demo."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from blender_probe_integration import create_wheel_fixture
from addon_scope.report import write_html, write_json
from addon_scope.scanner import scan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="A new directory for generated fixtures and reports")
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("Choose an empty output directory; existing files will not be overwritten")
    repository = args.output / "extensions" / "demo"
    repository.mkdir(parents=True)
    create_wheel_fixture(repository)
    result = scan([repository], environment={"fixture": "Synthetic shared-wheel conflict demo"})
    write_html(result, args.output / "report.html")
    write_json(result, args.output / "report.json")
    print(f"Synthetic fixture: {repository}")
    print(f"Report: {args.output / 'report.html'}")


if __name__ == "__main__":
    main()
