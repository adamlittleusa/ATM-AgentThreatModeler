"""Command line entry point: `python -m atm scan <path>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyze import analyze, write_findings
from .checks import catalogue
from .render import render_markdown
from .report import render_catalogue, render_findings
from .scan import ATM_VERSION, scan, write_inventory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atm",
        description="Agent Threat Modeler — collect the agent surface of a repository.",
    )
    parser.add_argument("--version", action="version", version=f"atm {ATM_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_cmd = sub.add_parser("scan", help="collect an inventory from a repository")
    scan_cmd.add_argument("path", type=Path, help="path to the repository under audit")
    scan_cmd.add_argument(
        "-o", "--out", type=Path, default=Path("atm-out"),
        help="output directory (default: atm-out)",
    )
    scan_cmd.add_argument(
        "--json-only", action="store_true", help="write inventory.json and skip the markdown map",
    )
    scan_cmd.add_argument(
        "--stdout", action="store_true", help="print the markdown map to stdout instead of writing files",
    )
    scan_cmd.add_argument(
        "--include-hidden", action="store_true", help="descend into dot-directories",
    )
    scan_cmd.add_argument(
        "--exclude", action="append", default=[], metavar="GLOB",
        help="skip paths matching this glob (repeatable), e.g. --exclude 'tests/*' --exclude 'examples/*'",
    )

    an = sub.add_parser("analyze", help="run the checks over an inventory and emit candidate findings")
    an.add_argument("path", type=Path, help="repository path, or an existing inventory.json")
    an.add_argument("-o", "--out", type=Path, default=Path("atm-out"), help="output directory")
    an.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                    help="skip paths matching this glob (repeatable); ignored when reading an inventory.json")
    an.add_argument("--stdout", action="store_true", help="print the report instead of writing files")

    ck = sub.add_parser("checks", help="print the check catalogue")
    ck.add_argument("--json", action="store_true", help="emit JSON instead of markdown")

    args = parser.parse_args(argv)

    if args.command == "scan":
        try:
            inventory = scan(args.path, include_hidden=args.include_hidden, exclude=args.exclude)
        except (NotADirectoryError, FileNotFoundError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        if args.stdout:
            print(render_markdown(inventory))
            return 0

        out_dir: Path = args.out
        inv_path = write_inventory(inventory, out_dir / "inventory.json")
        written = [inv_path]
        if not args.json_only:
            map_path = out_dir / "surface-map.md"
            map_path.write_text(render_markdown(inventory), encoding="utf-8")
            written.append(map_path)

        ts = inventory["tool_summary"]
        print(f"atm {ATM_VERSION}: scanned {inventory['target']['python_files_parsed']} Python files")
        print(f"  frameworks: {', '.join(inventory['frameworks']) or 'none detected'}")
        print(f"  tools: {ts['count']}  ({ts['by_effect_class']})")
        print(f"  mediation signals: {len(inventory['mediation'])}")
        print(f"  coverage notes: {len(inventory['coverage_notes'])}")
        for p in written:
            print(f"  wrote {p}")
        return 0

    if args.command == "analyze":
        try:
            if args.path.is_file():
                inventory = json.loads(args.path.read_text(encoding="utf-8"))
            else:
                inventory = scan(args.path, exclude=args.exclude)
        except (NotADirectoryError, FileNotFoundError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            print(f"error: {args.path} is not valid JSON ({exc})", file=sys.stderr)
            return 2

        findings = analyze(inventory)
        report = render_findings(findings, inventory)

        if args.stdout:
            print(report)
            return 0

        out_dir: Path = args.out
        write_inventory(inventory, out_dir / "inventory.json")
        (out_dir / "surface-map.md").write_text(render_markdown(inventory), encoding="utf-8")
        write_findings(findings, out_dir / "findings.json")
        (out_dir / "threat-model.md").write_text(report, encoding="utf-8")

        s_ = findings["summary"]
        print(f"atm {ATM_VERSION}: {s_['checks_run']} checks -> {s_['candidates']} candidates")
        print(f"  observed  {s_['observed']}")
        print(f"  inferred  {s_['inferred']}")
        print(f"  questions {s_['team_questions']}")
        print(f"  areas     {', '.join(a['area'] for a in s_['areas_raised'])}")
        for name in ("inventory.json", "surface-map.md", "findings.json", "threat-model.md"):
            print(f"  wrote {out_dir / name}")
        print("\n  These are unrefuted candidates. Run /atm-scan to verify citations and refute.")
        return 0

    if args.command == "checks":
        cat = catalogue()
        if args.json:
            print(json.dumps(cat, indent=2))
        else:
            print(render_catalogue(cat))
        return 0

    return 1
