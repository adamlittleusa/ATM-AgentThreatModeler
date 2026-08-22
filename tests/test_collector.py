"""Smoke tests for the collector. Run: python3 -m tests.test_collector"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atm.scan import scan  # noqa: E402
from atm.render import render_markdown  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "samples" / "fixtures" / "support-agent"

failures = []


def check(label, cond):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        failures.append(label)


def main() -> int:
    inv = scan(FIXTURE)
    print("collector:")
    check("parses the fixture", inv["target"]["python_files_parsed"] == 5)
    check("fingerprints LangGraph", "LangGraph" in inv["frameworks"])
    check("finds five tools", inv["tool_summary"]["count"] == 5)

    names = {t["name"]: t for t in inv["tools"]}
    check("email tool classified as writing", names["send_customer_email"]["effect_class"] == "writes")
    check("refund tool classified as writing", names["issue_refund"]["effect_class"] == "writes")
    check("lookup tool classified read-only", names["lookup_customer"]["effect_class"] == "read_only")

    check("every tool cites a file and line",
          all(t["file"] and t["line"] > 0 for t in inv["tools"]))
    check("no mediation detected in fixture", inv["mediation"] == {})
    check("credentials found", inv["credentials"]["distinct_env_vars"] >= 5)
    check("checkpointer detected", "checkpointer" in inv["persistence"])
    check("no observability detected", inv["observability"] == {})
    check("coverage notes emitted", len(inv["coverage_notes"]) >= 2)
    check("side effects found outside tools", bool(inv["side_effects_outside_tools"]))

    print("exclusion:")
    excluded = scan(FIXTURE, exclude=["tools/*"])
    check("--exclude drops matching paths", excluded["tool_summary"]["count"] == 0)
    check("exclusion recorded as a coverage note",
          any("--exclude" in n for n in excluded["coverage_notes"]))

    print("render:")
    md = render_markdown(inv)
    check("renders a surface map", md.startswith("# Agent surface map"))
    check("map cites the email tool", "tools/comms.py:12" in md)
    check("map states the mediation absence is not proof", "not a proof" in md)
    check("map has a coverage section", "## Coverage limits" in md)

    print()
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
