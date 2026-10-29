"""Command-line diagnostics for support and reproducible bug reports."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .report import write_html, write_json
from .scanner import scan


def _parser():
    parser = argparse.ArgumentParser(prog="addon-scope", description="Inspect Blender add-on dependency coexistence")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("scan", help="Read manifests and package metadata; never import add-ons")
    inspect.add_argument("roots", nargs="+", type=Path, help="Add-on, repository or site-packages directories")
    inspect.add_argument("--html", type=Path, help="Write a self-contained report")
    inspect.add_argument("--json", type=Path, help="Write structured diagnostics")
    inspect.add_argument("--include-paths", action="store_true", help="Keep absolute paths in exported reports")
    inspect.add_argument("--fail-on", choices=("error", "warning"), help="Return exit code 1 for findings at this severity")
    probe = sub.add_parser("probe", help="Execute selected trusted add-ons in a disposable Blender process")
    probe.add_argument("roots", nargs="+", type=Path)
    probe.add_argument("--blender", required=True, help="Path to the Blender executable")
    probe.add_argument("--addon", action="append", required=True, help="Add-on ID to test; repeat to preserve enable order")
    probe.add_argument("--trust-addons", action="store_true", help="Acknowledge that selected add-ons execute code, without an OS sandbox")
    probe.add_argument("--depends", action="append", default=[], metavar="ADDON=DEPENDENCY", help="Required add-on IDs; repeat for multiple dependencies")
    probe.add_argument("--timeout", type=float, default=30.0, help="Seconds per process (default: 30)")
    probe.add_argument("--minimize", action="store_true", help="Try smaller dependency-preserving failing combinations")
    probe.add_argument("--max-runs", type=int, default=24)
    probe.add_argument("--output", type=Path, required=True, help="Write detailed probe trials as JSON")
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if any(not p.is_dir() for p in args.roots):
            parser.error("Every root must be an existing directory")
        result = scan(args.roots)
        if args.command == "scan":
            print(f"AddonScope {__version__} · {len(result.addons)} add-ons · {len(result.distributions)} distributions")
            for finding in result.findings:
                print(f"{finding.severity.upper():7} {finding.code}: {finding.title}")
                print(f"        {finding.summary}")
            if not result.findings:
                print("No metadata findings. Runtime and scene-level conflicts remain outside this check.")
            if args.html:
                write_html(result, args.html, not args.include_paths)
                print(f"HTML: {args.html}")
            if args.json:
                write_json(result, args.json, not args.include_paths)
                print(f"JSON: {args.json}")
            if args.fail_on:
                blocked = {"error"} if args.fail_on == "error" else {"error", "warning"}
                return int(any(f.severity in blocked for f in result.findings))
            return 0
        if not args.trust_addons:
            parser.error("probe requires --trust-addons: registration executes add-on code")
        if not 0 < args.timeout <= 600:
            parser.error("--timeout must be greater than 0 and no more than 600 seconds")
        if not 3 <= args.max_runs <= 100:
            parser.error("--max-runs must be between 3 and 100")
        by_id = {addon.id: addon for addon in result.addons}
        missing = set(args.addon) - by_id.keys()
        if missing:
            parser.error("Unknown add-on IDs: " + ", ".join(sorted(missing)))
        dependencies = {}
        for value in args.depends:
            parts = value.split("=", 1)
            if len(parts) != 2 or not all(parts) or any(p not in by_id for p in parts):
                parser.error("--depends must be ADDON=DEPENDENCY using known add-on IDs")
            dependencies.setdefault(parts[0], []).append(parts[1])
        selected = list(dict.fromkeys(args.addon))
        # Dependency closure is executed by the probe, but every possible provider
        # must be in its inventory. Requested order precedes extra dependencies.
        inventory = [by_id[id_] for id_ in selected] + [a for a in result.addons if a.id not in selected]
        from .probe import ProbeSpec, minimize, run_probe
        spec = ProbeSpec(args.blender, inventory, args.timeout, dependencies)
        if args.minimize:
            needed = set(selected)
            pending = list(selected)
            while pending:
                for dep in dependencies.get(pending.pop(), []):
                    if dep not in needed:
                        needed.add(dep)
                        pending.append(dep)
            spec.addons = [a for a in inventory if a.id in needed]
            outcome = minimize(spec, max_runs=args.max_runs)
        else:
            outcome = run_probe(spec, selected)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(outcome.to_dict(), indent=2), encoding="utf-8")
        print(f"{outcome.status}: {outcome.reason}")
        print(f"Trials: {args.output}")
        return {"pass": 0, "fail": 1, "confirmed": 1}.get(outcome.status, 2)
    except (OSError, ValueError) as exc:
        print(f"addon-scope: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
