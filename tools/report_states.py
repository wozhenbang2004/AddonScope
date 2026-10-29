"""Generate synthetic states for optional browser verification."""

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from blender_probe_integration import create_wheel_fixture
from addon_scope.models import ScanResult, Finding, Addon, Distribution
from addon_scope.report import write_html
from addon_scope.scanner import scan


def main():
    output = ROOT / "artifacts" / "verification" / "ui"
    result = ScanResult(roots=["/home/tester/extensions"], environment={"fixture": "Synthetic interaction and adversarial text states"})
    result.addons = [Addon("a", "Example extension — 中文长标题", "/home/tester/extensions/a", version="1.0", module="bl_ext.test.a")]
    result.distributions = [Distribution("example", "1.0", "/home/tester/extensions/a/" + "long-path/" * 20, "a", "wheel")]
    result.findings = [
        Finding("ONE", "warning", "Multiple versions of example", "Potential conflict", owners=["a"], evidence=["/home/tester/extensions/a/<script>window.injected=true</script>"], advice="Inspect the actual import path.", confidence="potential"),
        Finding("TWO", "error", "Dependency requires example>=2", "All inventoried versions differ from the requirement.", owners=["a"], evidence=["Long path: /home/tester/extensions/a/" + "long-path/" * 20], confidence="potential"),
        Finding("THREE", "info", "A module was captured", "</script><script>window.injected=true</script>", evidence=["Literal HTML should remain text"]),
    ]
    write_html(result, output / "states.html")
    write_html(ScanResult(roots=[], environment={"fixture": "Empty synthetic scan"}), output / "empty.html")
    with tempfile.TemporaryDirectory(prefix="addonscope-report-fixture-") as directory:
        root = Path(directory) / "extensions" / "demo"
        root.mkdir(parents=True)
        create_wheel_fixture(root)
        result = scan([root], environment={"fixture": "Synthetic shared-wheel conflict demo"})
        write_html(result, output / "demo-report.html")


if __name__ == "__main__":
    main()
