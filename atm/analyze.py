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


# Checks whose premise is a deployed, operated system. On a library these are not gaps.
DEPLOYMENT_ASSUMING = {
    "identity/shared-principal", "identity/credential-lifetime",
    "steering/no-mediation-layer", "steering/no-stop-control",
    "steering/effects-outside-tool-boundary",
    "autonomy/consequential-without-approval", "autonomy/blast-radius",
    "evidence/no-tracing", "evidence/logging-without-redaction",
    "fleet/admission-and-fairness", "fleet/fanout-without-bounds",
    "data/egress-without-classification", "data/residency-and-retention",
    "data/non-network-egress", "intent/purpose-not-represented",
    "state/persistence-without-expiry",
}

LIBRARY_PREFIX = (
    "This target is a library, so this is not a gap in it — it is a question its CONSUMERS "
    "must answer, and a property to check in whatever application embeds it. "
)


def analyze(inventory: dict) -> dict:
    shape = inventory.get("target", {}).get("shape", "unknown")
    candidates = run_all(inventory)

    if shape == "library":
        for c in candidates:
            if c.check_id in DEPLOYMENT_ASSUMING:
                c.detail = LIBRARY_PREFIX + c.detail
                if c.bucket in ("observed", "inferred"):
                    c.bucket = "team"
                c.consequence = "low" if c.consequence == "medium" else c.consequence

    candidates = sorted(candidates, key=_sort_key)

    by_bucket: dict[str, list[dict]] = {"observed": [], "inferred": [], "team": []}
    for c in candidates:
        by_bucket.setdefault(c.bucket, []).append(c.to_dict())

    areas_hit = sorted({c.area for c in candidates})
    ran = catalogue()

    return {
        "atm_version": inventory.get("atm_version"),
        "target": inventory.get("target", {}),
        "target_shape": shape,
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
