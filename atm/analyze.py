"""Run the check catalogue over an inventory and produce candidate findings.

This pass is deterministic. It produces CANDIDATES, not conclusions: every item
carries what would refute it, and the refutation itself needs a reader who can
open the files. The `/atm-scan` command drives that second pass.

Running this alone is still useful — it is the shortest path from a repository
to a defensible agenda.
"""

from __future__ import annotations

import json
from pathlib import Path

from .checks import AREAS, Candidate, catalogue, run_all

CONSEQUENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
BUCKET_ORDER = {"observed": 0, "inferred": 1, "team": 2}

# Who is usually able to close out a question in each area. A hint for grouping
# the interview script, not an assignment.
OWNER_HINT = {
    "autonomy": "product owner + engineering lead",
    "identity": "platform / infrastructure",
    "intent": "product owner",
    "context": "engineering lead",
    "state": "engineering lead + data owner",
    "evidence": "platform / observability",
    "steering": "on-call + engineering lead",
    "fleet": "platform / infrastructure",
    "data": "data owner + legal or compliance",
    "meta": "whoever reviews this repository",
}


def _sort_key(c: Candidate) -> tuple:
    return (
        CONSEQUENCE_ORDER.get(c.consequence, 9),
        BUCKET_ORDER.get(c.bucket, 9),
        c.area,
        c.check_id,
    )


def analyze(inventory: dict) -> dict:
    candidates = sorted(run_all(inventory), key=_sort_key)

    by_bucket: dict[str, list[dict]] = {"observed": [], "inferred": [], "team": []}
    for c in candidates:
        by_bucket.setdefault(c.bucket, []).append(c.to_dict())

    areas_hit = sorted({c.area for c in candidates})
    ran = catalogue()

    return {
        "atm_version": inventory.get("atm_version"),
        "target": inventory.get("target", {}),
        "summary": {
            "candidates": len(candidates),
            "observed": len(by_bucket["observed"]),
            "inferred": len(by_bucket["inferred"]),
            "team_questions": len(by_bucket["team"]),
            "areas_raised": [{"area": a, "label": AREAS.get(a, a)} for a in areas_hit],
            "checks_run": len(ran),
        },
        "findings": [c.to_dict() for c in candidates],
        "by_bucket": by_bucket,
        "owner_hints": OWNER_HINT,
        "checks_run": ran,
        "coverage_notes": inventory.get("coverage_notes", []),
        "status": "candidates_unrefuted",
        "next_step": (
            "These are candidates from a deterministic pass. Run the /atm-scan command to read the "
            "cited files, refute what the code disproves, and add the system context that makes "
            "each finding legible."
        ),
    }


def write_findings(findings: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(findings, indent=2) + "\n", encoding="utf-8")
    return out
