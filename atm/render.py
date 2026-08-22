"""Render an inventory into a human-readable surface map.

This renders FACTS ONLY. It states what was found, with citations, and what the
collector could not see. It does not grade, score, or recommend — that is the
analysis layer's job, and it happens with the framework in context.
"""

from __future__ import annotations

from collections import defaultdict

EFFECT_LABEL = {
    "writes": "writes",
    "executes": "executes code",
    "read_only": "read-only",
    "no_io_detected": "no I/O detected",
}

KIND_LABEL = {
    "network_write": "outbound HTTP write",
    "messaging": "message / notification send",
    "db_write": "database write",
    "fs_write": "filesystem write",
    "exec": "code execution",
    "infra_write": "infrastructure mutation",
    "financial": "payment system",
    "vcs_write": "repository write",
}


def _cite(ev: dict) -> str:
    return f"`{ev['file']}:{ev['line']}`"


def _bullets(bucket: dict, limit: int = 3) -> list[str]:
    out = []
    for key, evs in sorted(bucket.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        cites = ", ".join(_cite(e) for e in evs[:limit])
        more = f" (+{len(evs) - limit} more)" if len(evs) > limit else ""
        out.append(f"- **{key}** — {cites}{more}")
    return out


def render_markdown(inv: dict) -> str:
    t = inv["target"]
    L: list[str] = []
    add = L.append

    add(f"# Agent surface map — `{t['root']}`")
    add("")
    add(
        f"Collected by ATM v{inv['atm_version']} (static pass, Python only). "
        "Facts with citations; no findings and no grading. Read the coverage limits at the "
        "end before drawing conclusions from an absence."
    )
    add("")
    add(
        f"**Scanned:** {t['python_files_parsed']} Python files "
        f"({t['python_lines']:,} lines) out of {t['files_seen']} files seen."
    )
    if t["unparsed_code_files"]:
        others = ", ".join(f"{n}× {e}" for e, n in sorted(t["unparsed_code_files"].items(), key=lambda kv: -kv[1]))
        add(f"**Not parsed:** {others}")
    add("")

    # --- frameworks
    add("## Frameworks in use")
    add("")
    if inv["frameworks"]:
        L.extend(_bullets(inv["frameworks"]))
    else:
        add("_No known agent framework was fingerprinted._")
    add("")

    # --- tool surface
    ts = inv["tool_summary"]
    add("## Tool surface")
    add("")
    if ts["count"] == 0:
        add(
            "_No tool declarations were recognised._ Either the agent exposes no tools, or it "
            "declares them in a form this collector does not yet fingerprint (see coverage limits)."
        )
        add("")
    else:
        parts = [f"{n} {EFFECT_LABEL.get(k, k)}" for k, n in sorted(ts["by_effect_class"].items(), key=lambda kv: -kv[1])]
        add(f"**{ts['count']} tools declared** — {', '.join(parts)}.")
        add("")

        by_class: dict[str, list[dict]] = defaultdict(list)
        for tool in inv["tools"]:
            by_class[tool["effect_class"]].append(tool)

        for cls in ("executes", "writes", "read_only", "no_io_detected"):
            group = by_class.get(cls)
            if not group:
                continue
            add(f"### {EFFECT_LABEL.get(cls, cls).capitalize()} ({len(group)})")
            add("")
            add("| Tool | Location | Detected effects | Declared by |")
            add("|---|---|---|---|")
            for tool in group:
                kinds = ", ".join(KIND_LABEL.get(e["kind"], e["kind"]) for e in tool["side_effects"]) or "—"
                add(
                    f"| `{tool['name']}` | `{tool['file']}:{tool['line']}` | {kinds} | {tool['declared_by']} |"
                )
            add("")

    if inv["side_effects_outside_tools"]:
        add("### Side-effecting code outside declared tools")
        add("")
        add(
            "Write, send, or execute operations found in source that is not inside a recognised "
            "tool declaration. These paths reach the outside world without passing a tool boundary."
        )
        add("")
        L.extend(_bullets(inv["side_effects_outside_tools"]))
        add("")

    # --- mediation
    add("## Mediation between proposal and execution")
    add("")
    if inv["mediation"]:
        add("Signals found:")
        add("")
        L.extend(_bullets(inv["mediation"]))
    else:
        add(
            "**No mediation signal was found in the scanned source** — no interrupt, approval gate, "
            "guardrail, lifecycle hook, policy engine, allow/deny rule set, or sandbox. "
            "This is an absence, not a proof: mediation can live in a gateway, proxy, or platform "
            "configuration outside this repository."
        )
    add("")

    # --- identity and credentials
    creds = inv["credentials"]
    add("## Identity and credentials")
    add("")
    add(f"**{creds['distinct_env_vars']} distinct environment variables** are read.")
    add("")
    if creds["env_reads"]:
        add("| Variable | Read at |")
        add("|---|---|")
        for name, evs in sorted(creds["env_reads"].items(), key=lambda kv: (-len(kv[1]), kv[0])):
            cites = ", ".join(_cite(e) for e in evs[:3])
            more = f" +{len(evs) - 3}" if len(evs) > 3 else ""
            add(f"| `{name}` | {cites}{more} |")
        add("")
    if creds["possible_hardcoded_secrets"]:
        add(
            f"**{len(creds['possible_hardcoded_secrets'])} line(s) match a hardcoded-credential shape.** "
            "Values are redacted here; confirm each by hand before treating it as a finding."
        )
        add("")
        for ev in creds["possible_hardcoded_secrets"][:10]:
            add(f"- {_cite(ev)} — `{ev['snippet']}`")
        add("")

    # --- state
    add("## State and persistence")
    add("")
    if inv["persistence"]:
        L.extend(_bullets(inv["persistence"]))
    else:
        add("_No checkpointer, store, vector database, or conversation memory was detected._")
    add("")

    # --- observability
    add("## Observability")
    add("")
    if inv["observability"]:
        L.extend(_bullets(inv["observability"]))
    else:
        add("_No tracing or structured logging was detected._")
    add("")

    # --- scale and coordination
    add("## Concurrency, retry, and coordination")
    add("")
    if inv["concurrency"]:
        L.extend(_bullets(inv["concurrency"]))
    else:
        add("_No fan-out, retry, rate-limit, idempotency, or circuit-breaker signal was detected._")
    add("")

    # --- data handling
    add("## Data handling")
    add("")
    if inv["data_handling"]:
        L.extend(_bullets(inv["data_handling"]))
    else:
        add(
            "_No redaction, classification, PII detection, secret-manager, encryption, or retention "
            "signal was detected._"
        )
    add("")

    # --- egress
    add("## Egress destinations")
    add("")
    if inv["egress_hosts"]:
        add("Hosts appearing as URL literals in source:")
        add("")
        L.extend(_bullets(inv["egress_hosts"], limit=2))
        add("")
        add(
            "_Literal URLs are the visible fraction of egress. Destinations built at runtime from "
            "configuration, environment, or model output do not appear here._"
        )
    else:
        add("_No literal URLs found. Any egress is configured at runtime and invisible to this pass._")
    add("")

    # --- coverage
    add("## Coverage limits")
    add("")
    add("What this pass could not see. Every conclusion drawn downstream inherits these limits.")
    add("")
    for note in inv["coverage_notes"]:
        add(f"- {note}")
    add("")
    if inv["parse_failures"]:
        add("### Files that failed to parse")
        add("")
        for pf in inv["parse_failures"][:15]:
            add(f"- `{pf['file']}` — {pf['reason']}")
        add("")

    add("---")
    add("")
    add(
        "_This is an inventory, not an assessment. It records what is present and what could not "
        "be seen. Turning it into findings requires the analysis pass, which separates what the "
        "code shows from what only the team can answer._"
    )
    add("")
    return "\n".join(L)
