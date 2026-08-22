"""Command line entry point: `python -m atm scan <path>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .render import render_markdown
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

    return 1
