"""Render candidate findings into a reviewer's working document."""

from __future__ import annotations

from collections import defaultdict

from .checks import AREAS

BUCKET_TITLE = {
    "observed": "Observed",
    "inferred": "Inferred",
    "team": "Questions for the team",
}

BUCKET_NOTE = {
    "observed": "Evidence is in the repository. Each cites a file and line — open them before you use them.",
    "inferred": "The pattern points this way; the code does not settle it. Each carries what would refute it.",
    "team": "Not answerable from any repository. This is the interview script, anchored to what their code shows.",
}

CONSEQUENCE_MARK = {"high": "●●●", "medium": "●●", "low": "●"}


def _cite(ev: dict) -> str:
    return f"`{ev['file']}:{ev['line']}`"


def render_findings(fa: dict, inventory: dict | None = None) -> str:
    L: list[str] = []
    add = L.append
    s = fa["summary"]
    t = fa.get("target", {})

    add(f"# Agent threat model — `{t.get('root', 'target')}`")
    add("")
    add(
        f"Candidate findings from ATM v{fa.get('atm_version')}. "
        f"{s['checks_run']} checks run; {s['candidates']} raised — "
        f"**{s['observed']} observed, {s['inferred']} inferred, {s['team_questions']} for the team.**"
    )
    add("")
    add(f"> **Status: {fa['status']}.** {fa['next_step']}")
    add("")
    shape = fa.get("target_shape", "unknown")
    if shape == "library":
        add(
            "> **This target reads as a library, not a deployed agent.** Checks that assume a "
            "running system have been rerouted into questions for whoever embeds it — a library "
            "legitimately holds no credentials, mediates nothing, and has no deployment to govern. "
            "Point ATM at a consuming application for a real answer."
        )
        add("")
    elif shape == "unknown":
        add(
            "> **Whether this is a deployed application or a library could not be determined.** "
            "That distinction changes which findings below are meaningful. Settle it first."
        )
        add("")

    # --- what the system looks like
    if inventory:
        add("## What this system is")
        add("")
        fw = ", ".join(inventory.get("frameworks", {})) or "no framework fingerprinted"
        ts = inventory.get("tool_summary", {})
        by = ts.get("by_effect_class", {})
        shape: list[str] = []
        if inventory.get("persistence", {}).get("checkpointer"):
            shape.append("checkpoints, so runs survive a pause")
        conc = inventory.get("concurrency", {})
        if conc.get("subagent_spawn") or conc.get("delegation"):
            shape.append("delegates work to other agents")
        if conc.get("parallel_execution"):
            shape.append("runs work in parallel")
        if inventory.get("observability"):
            shape.append("emits traces or logs")
        else:
            shape.append("has no tracing detected")
        add(
            f"Built on {fw}. {ts.get('count', 0)} declared tools "
            f"({', '.join(f'{v} {k.replace(chr(95), chr(32))}' for k, v in sorted(by.items(), key=lambda kv: -kv[1]))}). "
            f"It {'; '.join(shape)}."
        )
        ev = inventory.get("target", {}).get("shape_evidence") or []
        if ev:
            add("")
            add(f"x because: "
                + "; ".join(ev) + ".")
        add("")
        add(
            "_This paragraph is assembled from detected facts. Replace it with a real description "
            "of the system's job and blast radius before this goes in front of anyone._"
        )
        add("")

    # --- findings by bucket
    for bucket in ("observed", "inferred", "team"):
        items = fa["by_bucket"].get(bucket, [])
        add(f"## {BUCKET_TITLE[bucket]} ({len(items)})")
        add("")
        add(f"_{BUCKET_NOTE[bucket]}_")
        add("")
        if not items:
            add("_Nothing raised._")
            add("")
            continue

        if bucket == "team":
            grouped: dict[str, list[dict]] = defaultdict(list)
            for it in items:
                grouped[it["area"]].append(it)
            hints = fa.get("owner_hints", {})
            for area, group in sorted(grouped.items()):
                add(f"### {AREAS.get(area, area)} — usually answered by {hints.get(area, 'the team')}")
                add("")
                for it in group:
                    add(f"**{it['title']}**")
                    add("")
                    add(it["detail"])
                    add("")
                    if it.get("evidence"):
                        add(f"Raised by: {', '.join(_cite(e) for e in it['evidence'][:4])}")
                        add("")
                    if it.get("resolves_to"):
                        add(f"→ _Closes when:_ {it['resolves_to']}")
                        add("")
        else:
            for it in items:
                mark = CONSEQUENCE_MARK.get(it["consequence"], "")
                add(f"### {mark} {it['title']}")
                add("")
                add(f"`{it['check_id']}` · {AREAS.get(it['area'], it['area'])} · consequence: {it['consequence']}")
                add("")
                add(it["detail"])
                add("")
                if it.get("evidence"):
                    add("**Evidence**")
                    add("")
                    for e in it["evidence"][:8]:
                        add(f"- {_cite(e)} — `{e['snippet']}`")
                    add("")
                if it.get("refuted_by"):
                    add("**Would be wrong if**")
                    add("")
                    for r in it["refuted_by"]:
                        add(f"- {r}")
                    add("")
                if it.get("resolves_to"):
                    add(f"→ _Closes when:_ {it['resolves_to']}")
                    add("")

    # --- coverage
    add("## Coverage")
    add("")
    add("Every finding above inherits these limits.")
    add("")
    for n in fa.get("coverage_notes", []):
        add(f"- {n}")
    add("")
    add(
        "- Checks are matched against a static inventory. A control implemented in a way the "
        "collector does not fingerprint reads here as absent — which is why absences are phrased "
        "as unseen, and why the refutation pass exists."
    )
    add("")
    add("---")
    add("")
    add(
        "_No score is produced, deliberately. A number invites a target, and a system tuned to a "
        "threat-model score has learned to satisfy the scanner rather than the threat._"
    )
    add("")
    return "\n".join(L)


def render_catalogue(checks: list[dict]) -> str:
    L = ["# Check catalogue", "", f"{len(checks)} checks.", ""]
    L.append(
        "`answerable` records how much of a question a repository can settle: **code** — it can be "
        "answered outright; **partial** — the code raises it and only the team can close it; "
        "**team** — no repository can answer it, so it becomes a question."
    )
    L.append("")
    grouped: dict[str, list[dict]] = defaultdict(list)
    for c in checks:
        grouped[c["area"]].append(c)
    for area, group in sorted(grouped.items()):
        L.append(f"## {AREAS.get(area, area)}")
        L.append("")
        for c in sorted(group, key=lambda x: x["id"]):
            L.append(f"### `{c['id']}`")
            L.append("")
            L.append(f"**{c['question']}**")
            L.append("")
            L.append(f"- answerable: `{c['answerable']}`")
            L.append(f"- applies when: {c['applies_when']}")
            if c["satisfied_by"]:
                L.append(f"- satisfied by: {'; '.join(c['satisfied_by'])}")
            if c["refuted_by"]:
                L.append(f"- refuted by: {'; '.join(c['refuted_by'])}")
            L.append("")
    return "\n".join(L)
