"""Smoke tests for the collector. Run: python3 -m tests.test_collector"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atm.scan import scan  # noqa: E402
from atm.render import render_markdown  # noqa: E402
from atm.analyze import DEPLOYMENT_ASSUMING, analyze  # noqa: E402
from atm.checks import REGISTRY, catalogue  # noqa: E402
from atm.report import render_findings  # noqa: E402

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

    print("checks:")
    ids = [c.id for c in REGISTRY]
    check("check ids are unique", len(ids) == len(set(ids)))
    check("every check declares answerable in the vocabulary",
          all(c.answerable in ("code", "partial", "team") for c in REGISTRY))
    check("every check has a question ending in '?'",
          all(c.question.rstrip().endswith("?") for c in REGISTRY))
    check("team-answerable checks never claim code evidence",
          all(c.satisfied_by == [] for c in REGISTRY if c.answerable == "team"))

    print("analysis:")
    fa = analyze(inv)
    check("produces candidates", fa["summary"]["candidates"] > 0)
    check("no detector crashed", not any("failed to run" in f["title"] for f in fa["findings"]))
    check("buckets are exhaustive",
          fa["summary"]["observed"] + fa["summary"]["inferred"] + fa["summary"]["team_questions"]
          == fa["summary"]["candidates"])
    check("every bucket value is legal",
          all(f["bucket"] in ("observed", "inferred", "team") for f in fa["findings"]))
    check("every asserted finding cites evidence",
          all(f["evidence"] for f in fa["findings"] if f["bucket"] in ("observed", "inferred")))
    check("observed and inferred findings carry a refutation",
          all(f["refuted_by"] for f in fa["findings"] if f["bucket"] in ("observed", "inferred")))
    check("evidence is deduplicated",
          all(len({(e["file"], e["line"]) for e in f["evidence"]}) == len(f["evidence"])
              for f in fa["findings"]))
    check("status marks candidates as unrefuted", fa["status"] == "candidates_unrefuted")

    ids_found = {f["check_id"] for f in fa["findings"]}
    check("flags unmediated consequential tools",
          "autonomy/consequential-without-approval" in ids_found)
    check("flags the planted analysis-time injection",
          "meta/analysis-time-injection" in ids_found)
    check("flags effects outside the tool boundary",
          "steering/effects-outside-tool-boundary" in ids_found)
    check("asks about blast radius rather than asserting it",
          any(f["check_id"] == "autonomy/blast-radius" and f["bucket"] == "team"
              for f in fa["findings"]))

    print("report:")
    rpt = render_findings(fa, inv)
    check("report names the unrefuted status", "candidates_unrefuted" in rpt)
    check("report separates the three buckets",
          all(h in rpt for h in ("## Observed", "## Inferred", "## Questions for the team")))
    check("report states that no score is produced", "No score is produced" in rpt)
    check("report contains no numeric grade",
          not re.search(r"\b(?:risk|security|threat)\s+score\b|\b\d{1,3}\s*/\s*(?:10|100)\b", rpt, re.I))
    check("report carries coverage forward", "## Coverage" in rpt)
    check("report has no placeholder leader in the system summary", "x because" not in rpt)
    check("report states the detected shape in prose",
          "Reads as an application" in rpt)

    print("target shape:")
    check("fixture reads as an application", inv["target"]["shape"] == "application")
    check("shape decision carries its reasons", bool(inv["target"]["shape_evidence"]))

    print("dual shape:")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        dual_root = Path(td)
        (dual_root / "pyproject.toml").write_text(
            "[build-system]\nrequires = ['setuptools']\n", encoding="utf-8")
        (dual_root / "main.py").write_text("print('serve')\n", encoding="utf-8")
        (dual_root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
        (dual_root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        dual = scan(dual_root)
        check("packaged repo with deployment artifacts reads as an application",
              dual["target"]["shape"] == "application")
        check("deployment evidence is cited",
              any("docker-compose" in w or "Dockerfile" in w
                  for w in dual["target"]["shape_evidence"]))
    with tempfile.TemporaryDirectory() as td:
        pure_root = Path(td)
        (pure_root / "pyproject.toml").write_text(
            "[build-system]\nrequires = ['setuptools']\n", encoding="utf-8")
        src = pure_root / "src" / "mylib"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("", encoding="utf-8")
        (pure_root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
        pure = scan(pure_root)
        check("a lone dev Dockerfile does not make a library an application",
              pure["target"]["shape"] == "library")

    lib = dict(inv)
    lib["target"] = dict(inv["target"], shape="library")
    fa_lib = analyze(lib)
    check("a library asserts nothing about deployment",
          all(f["bucket"] == "team" for f in fa_lib["findings"]
              if f["check_id"] in DEPLOYMENT_ASSUMING))
    check("library findings say whose question it is",
          all(f["detail"].startswith("This target is a library")
              for f in fa_lib["findings"] if f["check_id"] in DEPLOYMENT_ASSUMING))

    print("catalogue:")
    cat = catalogue()
    check("catalogue covers every registered check", len(cat) == len(REGISTRY))

    print()
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
