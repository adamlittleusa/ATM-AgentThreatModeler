"""The check catalogue.

A check is a question the framework asks about an agent system, plus enough
metadata to keep the answer honest:

  answerable   how much of the question the code can settle
                 "code"    -> a repository can answer it outright
                 "partial" -> the code raises it; only the team can close it
                 "team"    -> no repository can answer it; it is a question

  detect       given an inventory, return zero or more candidate findings.
               A detector may only assert what the inventory shows, and must
               attach the evidence it relied on.

  refuted_by   what would make a candidate wrong. Carried into the report so
               the refutation pass has something concrete to attack.

Checks live in Python rather than a data file so that predicate and prose stay
together and stay testable. `python -m atm checks` renders the catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

AREAS = {
    "autonomy": "Autonomy and approval",
    "identity": "Identity and delegation",
    "intent": "Purpose boundaries",
    "context": "Context trust",
    "state": "Persistent state",
    "evidence": "Evidence and observability",
    "steering": "Live intervention",
    "fleet": "Fleet behavior under load",
    "data": "Data governance",
    "meta": "Analysis integrity",
}

# Effect kinds whose consequences are hard to withdraw once they land.
EGRESS_WORDS = {
    "fs_write": "files on disk",
    "vcs_write": "repository commits",
    "messaging": "messages to people or channels",
}

CONSEQUENTIAL_EFFECTS = {
    "messaging": "reaches a person or an external system",
    "financial": "moves money",
    "infra_write": "mutates infrastructure",
    "vcs_write": "writes to a repository",
    "db_write": "commits durable state",
    "exec": "executes code",
    "network_write": "writes to an external service",
}


@dataclass
class Candidate:
    """One candidate finding, before refutation."""
    check_id: str
    area: str
    bucket: str                      # observed | inferred | team
    consequence: str                 # high | medium | low
    title: str
    detail: str
    evidence: list[dict] = field(default_factory=list)
    refuted_by: list[str] = field(default_factory=list)
    resolves_to: str = ""            # what would close this out
    subjects: list[str] = field(default_factory=list)   # tool/credential names in play

    def to_dict(self) -> dict:
        seen, deduped = set(), []
        for e in self.evidence:
            key = (e.get("file"), e.get("line"))
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        return {
            "check_id": self.check_id,
            "area": self.area,
            "area_label": AREAS.get(self.area, self.area),
            "bucket": self.bucket,
            "consequence": self.consequence,
            "title": self.title,
            "detail": self.detail,
            "evidence": deduped,
            "refuted_by": self.refuted_by,
            "resolves_to": self.resolves_to,
            "subjects": self.subjects,
        }


@dataclass
class Check:
    id: str
    area: str
    question: str
    answerable: str                  # code | partial | team
    detect: Callable[[dict], list[Candidate]]
    satisfied_by: list[str] = field(default_factory=list)
    refuted_by: list[str] = field(default_factory=list)
    applies_when: str = "always"     # human-readable routing note

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "area": self.area,
            "area_label": AREAS.get(self.area, self.area),
            "question": self.question,
            "answerable": self.answerable,
            "applies_when": self.applies_when,
            "satisfied_by": self.satisfied_by,
            "refuted_by": self.refuted_by,
        }


REGISTRY: list[Check] = []


def check(**kwargs):
    """Register a check. The decorated function is its detector."""
    def wrap(fn):
        REGISTRY.append(Check(detect=fn, **kwargs))
        return fn
    return wrap


# --------------------------------------------------------------------------
# Inventory helpers
# --------------------------------------------------------------------------

def _tools(inv: dict, classes: tuple[str, ...] = ()) -> list[dict]:
    tools = inv.get("tools", [])
    if not classes:
        return tools
    return [t for t in tools if t["effect_class"] in classes]


def _consequential(inv: dict) -> list[dict]:
    out = []
    for t in _tools(inv, ("writes", "executes")):
        if any(e["kind"] in CONSEQUENTIAL_EFFECTS for e in t["side_effects"]):
            out.append(t)
    return out


def _has(inv: dict, section: str, *keys: str) -> bool:
    bucket = inv.get(section) or {}
    return any(k in bucket for k in keys) if keys else bool(bucket)


def _ev(inv: dict, section: str, *keys: str, limit: int = 4) -> list[dict]:
    bucket = inv.get(section) or {}
    out: list[dict] = []
    for k in (keys or tuple(bucket)):
        for e in bucket.get(k, []):
            if len(out) < limit:
                out.append(e)
    return out


def _tool_ev(tools: list[dict], limit: int = 6) -> list[dict]:
    return [t["evidence"] for t in tools[:limit]]


def _names(tools: list[dict]) -> list[str]:
    return [t["name"] for t in tools]


def _effect_words(tool: dict) -> str:
    kinds = [e["kind"] for e in tool["side_effects"]]
    words = [CONSEQUENTIAL_EFFECTS.get(k, k.replace("_", " ")) for k in kinds]
    return ", ".join(dict.fromkeys(words)) or "no detected I/O"


# --------------------------------------------------------------------------
# AUTONOMY
# --------------------------------------------------------------------------

@check(
    id="autonomy/consequential-without-approval",
    area="autonomy",
    question="Can the agent take a consequential action without a human or policy decision?",
    answerable="partial",
    applies_when="any tool writes, sends, or executes",
    satisfied_by=["an approval gate, interrupt, or policy decision on the path to the consequential tool"],
    refuted_by=[
        "an approval or policy check exists in a wrapper, gateway, or registration path the collector did not parse",
        "the tool is only reachable from an already-approved workflow",
        "the effect classification is wrong on inspection",
    ],
)
def _autonomy_no_approval(inv: dict) -> list[Candidate]:
    tools = _consequential(inv)
    if not tools:
        return []
    gated = _has(inv, "mediation", "approval_gate", "interrupt", "human_in_the_loop", "policy_engine")
    if gated:
        return []
    return [Candidate(
        check_id="autonomy/consequential-without-approval",
        area="autonomy",
        bucket="observed",
        consequence="high",
        title=f"{len(tools)} consequential tool(s) with no approval or policy gate visible",
        detail=(
            "These tools reach outside the process, and no approval gate, interrupt, "
            "human-review hook, or policy engine was found anywhere in the scanned source. "
            "Each is reachable directly from a model decision: "
            + "; ".join(f"`{t['name']}` ({_effect_words(t)})" for t in tools[:6])
            + ("" if len(tools) <= 6 else f"; and {len(tools) - 6} more")
        ),
        evidence=_tool_ev(tools),
        refuted_by=[
            "an approval or policy check exists in a wrapper the collector did not follow",
            "the tools are registered through a mediating adapter elsewhere",
        ],
        resolves_to="Show where the decision to execute is made, and by what.",
        subjects=_names(tools),
    )]


@check(
    id="autonomy/blast-radius",
    area="autonomy",
    question="For each consequential tool, what is the worst outcome of one wrong call, and who absorbs it?",
    answerable="team",
    applies_when="any tool writes, sends, or executes",
)
def _autonomy_blast_radius(inv: dict) -> list[Candidate]:
    tools = _consequential(inv)
    if not tools:
        return []
    listed = ", ".join(f"`{t['name']}`" for t in tools[:8])
    return [Candidate(
        check_id="autonomy/blast-radius",
        area="autonomy",
        bucket="team",
        consequence="high",
        title="Blast radius of each consequential tool is not visible in code",
        detail=(
            f"The code shows what these tools do, not what it costs when one fires wrongly: {listed}. "
            "For each: what is the worst single wrong call, is it reversible, who notices, and how long "
            "until they do?"
        ),
        evidence=_tool_ev(tools, limit=4),
        resolves_to="A per-tool answer for worst case, reversibility, and detection time.",
        subjects=_names(tools),
    )]


# --------------------------------------------------------------------------
# IDENTITY
# --------------------------------------------------------------------------

@check(
    id="identity/shared-principal",
    area="identity",
    question="Does each tool act under a distinct, scoped principal?",
    answerable="partial",
    applies_when="credentials are read and more than one tool exists",
    satisfied_by=["a distinct credential per tool or per operation class", "token exchange before a privileged call"],
    refuted_by=[
        "the shared token is exchanged upstream for a narrower one",
        "all tools genuinely address one system under one scope",
        "scoping happens at the gateway rather than in the credential",
    ],
)
def _identity_shared(inv: dict) -> list[Candidate]:
    creds = inv.get("credentials", {})
    env = creds.get("env_reads", {}) or {}
    tools = _tools(inv, ("writes", "executes", "read_only"))
    if len(tools) < 2 or not env:
        return []
    # a credential read from more than one file, used by a repo with several tools
    shared = {
        name: evs for name, evs in env.items()
        if len({e["file"] for e in evs}) > 1
        and any(w in name.upper() for w in ("TOKEN", "KEY", "SECRET", "CREDENTIAL", "PASSWORD"))
    }
    # or: far fewer credentials than tools reaching distinct systems
    tool_files = {t["file"] for t in tools}
    cred_like = [n for n in env if any(w in n.upper() for w in ("TOKEN", "KEY", "SECRET", "CREDENTIAL", "PASSWORD"))]
    thin = len(cred_like) and len(tools) >= 3 and len(cred_like) <= max(1, len(tool_files) // 2)
    if not shared and not thin:
        return []
    names = sorted(shared) or cred_like[:3]
    evidence = []
    for n in names[:3]:
        evidence.extend(env.get(n, [])[:2])
    return [Candidate(
        check_id="identity/shared-principal",
        area="identity",
        bucket="inferred",
        consequence="high",
        title=f"{len(tools)} tools appear to act under {len(cred_like)} credential(s)",
        detail=(
            "Credentials read here look like one principal serving several tools: "
            + ", ".join(f"`{n}`" for n in names[:4])
            + ". When every tool presents the same identity, least privilege cannot be enforced at "
              "the far end — the read-only caller and the writing caller are indistinguishable to "
              "every downstream system, and a revocation is all-or-nothing."
        ),
        evidence=evidence,
        refuted_by=[
            "the token is exchanged for a narrower one before use",
            "the tools address one system with one legitimate scope",
            "scoping is enforced at a gateway rather than in the credential",
        ],
        resolves_to="Show what the downstream system sees as the caller for two tools with different risk.",
        subjects=names,
    )]


@check(
    id="identity/hardcoded-credential",
    area="identity",
    question="Are credentials present as literals in source?",
    answerable="code",
    applies_when="a credential-shaped literal is found",
    satisfied_by=["credentials resolved from environment, a vault, or a workload identity"],
    refuted_by=["the literal is a placeholder, fixture, or public identifier", "the value is already rotated and dead"],
)
def _identity_hardcoded(inv: dict) -> list[Candidate]:
    lits = (inv.get("credentials", {}) or {}).get("possible_hardcoded_secrets", []) or []
    if not lits:
        return []
    return [Candidate(
        check_id="identity/hardcoded-credential",
        area="identity",
        bucket="observed",
        consequence="high",
        title=f"{len(lits)} line(s) match a hardcoded-credential shape",
        detail=(
            "Values are redacted in this report. Confirm each by hand: a literal that is real is "
            "both a live secret and a credential with no expiry, which makes every downstream "
            "revocation story untrue."
        ),
        evidence=lits[:8],
        refuted_by=["the literal is a placeholder or fixture", "the value is a public identifier"],
        resolves_to="Confirm or dismiss each line, and rotate anything real.",
    )]


@check(
    id="identity/credential-lifetime",
    area="identity",
    question="How long does each credential stay valid, and what revokes it mid-run?",
    answerable="team",
    applies_when="any credential is read",
)
def _identity_lifetime(inv: dict) -> list[Candidate]:
    env = (inv.get("credentials", {}) or {}).get("env_reads", {}) or {}
    if not env:
        return []
    long_running = _has(inv, "persistence", "checkpointer", "long_term_store")
    extra = (
        " This system checkpoints, so a run can resume after a pause — which makes credential "
        "lifetime a live question rather than a theoretical one."
        if long_running else ""
    )
    return [Candidate(
        check_id="identity/credential-lifetime",
        area="identity",
        bucket="team",
        consequence="medium",
        title="Credential lifetime and revocation are not visible in code",
        detail=(
            "The code shows credentials being read from the environment; it cannot show how long "
            "they are valid, whether anything rotates them, or what happens to a run holding one "
            "when it is revoked." + extra
        ),
        evidence=[e for evs in list(env.values())[:4] for e in evs[:1]],
        resolves_to="Expiry, rotation mechanism, and mid-run revocation behaviour for each credential.",
        subjects=sorted(env)[:8],
    )]


# --------------------------------------------------------------------------
# STEERING (live intervention)
# --------------------------------------------------------------------------

@check(
    id="steering/no-mediation-layer",
    area="steering",
    question="Is there anything between the model's proposal and the tool's execution?",
    answerable="partial",
    applies_when="any tool exists",
    satisfied_by=["an interrupt, guardrail, lifecycle hook, policy engine, allow/deny rules, or a sandbox"],
    refuted_by=[
        "mediation lives in a gateway, proxy, or platform configuration outside this repository",
        "the framework mediates by default in a way the collector did not fingerprint",
    ],
)
def _steering_no_mediation(inv: dict) -> list[Candidate]:
    tools = _tools(inv)
    if not tools or _has(inv, "mediation"):
        return []
    return [Candidate(
        check_id="steering/no-mediation-layer",
        area="steering",
        bucket="inferred",
        consequence="high",
        title="No mediation layer found between model output and tool execution",
        detail=(
            f"{len(tools)} tools are declared and no interrupt, guardrail, lifecycle hook, policy "
            "engine, allow/deny rule set, or sandbox was found in the scanned source. If that "
            "holds, the model's decision to call a tool IS the decision to execute it, and there "
            "is no point at which a proposal can be delayed, edited, denied, or replaced. "
            "This is an absence in one repository, not a proof — mediation is often deployed "
            "outside the code."
        ),
        evidence=_tool_ev(tools, limit=4),
        refuted_by=[
            "a gateway or proxy mediates tool calls outside this repository",
            "the framework enforces a policy the collector did not fingerprint",
        ],
        resolves_to="Point at the component that decides whether a proposed call executes.",
    )]


@check(
    id="steering/effects-outside-tool-boundary",
    area="steering",
    question="Does anything reach the outside world without crossing a tool boundary?",
    answerable="code",
    applies_when="write, send, or execute operations exist outside declared tools",
    satisfied_by=["all external effects flow through declared, mediatable tools"],
    refuted_by=["the code is setup, migration, or test scaffolding not reachable at agent runtime"],
)
def _steering_loose_effects(inv: dict) -> list[Candidate]:
    loose = inv.get("side_effects_outside_tools") or {}
    if not loose:
        return []
    kinds = ", ".join(sorted(loose))
    evidence = _ev(inv, "side_effects_outside_tools", limit=6)
    return [Candidate(
        check_id="steering/effects-outside-tool-boundary",
        area="steering",
        bucket="observed",
        consequence="medium",
        title=f"External effects outside any tool declaration ({kinds})",
        detail=(
            "These write, send, or execute operations sit in source that is not inside a declared "
            "tool. Whatever mediation is applied at the tool boundary does not apply to them. "
            "Worth separating the ones that run at agent runtime from setup and migration code."
        ),
        evidence=evidence,
        refuted_by=["the code is setup or migration scaffolding not reachable at agent runtime"],
        resolves_to="Classify each as runtime or scaffolding; route the runtime ones through a tool.",
    )]


@check(
    id="steering/no-stop-control",
    area="steering",
    question="Once a run is moving and looks wrong, what stops it?",
    answerable="team",
    applies_when="any consequential tool exists",
)
def _steering_stop(inv: dict) -> list[Candidate]:
    tools = _consequential(inv)
    if not tools:
        return []
    seen = _has(inv, "mediation", "interrupt") or _has(inv, "concurrency", "quota_or_breaker")
    detail = (
        "Some interrupt or breaker signal is present, but the code cannot show whether it is "
        "reachable during an incident, who is authorised to use it, or whether it has ever been "
        "exercised."
        if seen else
        "No interrupt or circuit-breaker signal was found. The code cannot prove the absence of a "
        "stop control — it is often operational — but nothing here shows one."
    )
    return [Candidate(
        check_id="steering/no-stop-control",
        area="steering",
        bucket="team",
        consequence="high",
        title="Stop control: existence, reach, and last exercise are not visible in code",
        detail=detail + (
            " Ask three things separately, because teams routinely have one and claim all three: "
            "can you pause a run mid-flight, can you revoke its credentials, and can you stop the "
            "whole class of agent at once? Then ask when each was last tried against a live run."
        ),
        evidence=_ev(inv, "mediation", "interrupt") + _ev(inv, "concurrency", "quota_or_breaker"),
        resolves_to="A named control per scope, and a date for the last time it was exercised.",
    )]


@check(
    id="steering/irreversible-without-idempotency",
    area="steering",
    question="If a consequential call is retried after an uncertain failure, can it happen twice?",
    answerable="partial",
    applies_when="consequential tools exist alongside retry logic",
    satisfied_by=["an idempotency key recorded before the side effect", "a ledger consulted before re-execution"],
    refuted_by=["the downstream API deduplicates natively", "retries are disabled for these tools"],
)
def _steering_idempotency(inv: dict) -> list[Candidate]:
    tools = _consequential(inv)
    if not tools:
        return []
    has_retry = _has(inv, "concurrency", "retry")
    has_idem = _has(inv, "concurrency", "idempotency")
    if has_idem or not tools:
        return []
    consequence = "high" if has_retry else "medium"
    lead = (
        "Retry logic is present and no idempotency key or ledger was found."
        if has_retry else
        "No idempotency key or ledger was found."
    )
    return [Candidate(
        check_id="steering/irreversible-without-idempotency",
        area="steering",
        bucket="inferred",
        consequence=consequence,
        title="Consequential tools with no visible idempotency control",
        detail=(
            lead + " A crash, timeout, or resume between the call and its confirmation leaves the "
            "system unable to tell whether the effect landed. For a model-driven caller this is "
            "worse than for ordinary code: after a restart the agent may re-derive the task and "
            "issue a call that is semantically the same but not byte-identical, so exact-match "
            "deduplication downstream will not catch it. Tools at risk: "
            + ", ".join(f"`{t['name']}`" for t in tools[:6])
        ),
        evidence=_tool_ev(tools) + _ev(inv, "concurrency", "retry", limit=2),
        refuted_by=["the downstream API deduplicates natively", "retries are disabled for these tools"],
        resolves_to="Show what prevents a second execution after an uncertain first attempt.",
        subjects=_names(tools),
    )]


# --------------------------------------------------------------------------
# STATE
# --------------------------------------------------------------------------

@check(
    id="state/persistence-without-expiry",
    area="state",
    question="Does anything the agent writes expire, and can it be deleted on request?",
    answerable="partial",
    applies_when="a checkpointer, store, or vector database exists",
    satisfied_by=["a TTL, retention policy, or purge path on stored state"],
    refuted_by=["retention is enforced by the storage layer's own policy outside this code"],
)
def _state_expiry(inv: dict) -> list[Candidate]:
    if not _has(inv, "persistence"):
        return []
    if _has(inv, "data_handling", "retention"):
        return []
    kinds = ", ".join(sorted(inv.get("persistence", {})))
    return [Candidate(
        check_id="state/persistence-without-expiry",
        area="state",
        bucket="inferred",
        consequence="medium",
        title=f"Durable state ({kinds}) with no retention or expiry signal",
        detail=(
            "State written here survives the run that created it and can influence later runs. "
            "No TTL, retention rule, or purge path was found. Two consequences worth separating: "
            "state that is wrong or poisoned persists until something removes it, and a deletion "
            "request cannot be satisfied by deleting the source row if the agent already copied it "
            "into a checkpoint or a summary."
        ),
        evidence=_ev(inv, "persistence", limit=5),
        refuted_by=["retention is enforced by the storage layer outside this code"],
        resolves_to="A retention rule per store, and a path from a deletion request to the derived copies.",
    )]


@check(
    id="state/vector-store-tenancy",
    area="state",
    question="What separates one tenant's or user's vectors from another's?",
    answerable="team",
    applies_when="a vector database is in use",
)
def _state_tenancy(inv: dict) -> list[Candidate]:
    if not _has(inv, "persistence", "vector_store"):
        return []
    return [Candidate(
        check_id="state/vector-store-tenancy",
        area="state",
        bucket="team",
        consequence="high",
        title="Vector store isolation is not visible in code",
        detail=(
            "A vector database is in use. Retrieval that crosses a tenant or user boundary is a "
            "quiet failure — it returns plausible, relevant, unauthorised content, and nothing "
            "errors. Ask what enforces the boundary: separate collections, a metadata filter "
            "applied at query time, or nothing."
        ),
        evidence=_ev(inv, "persistence", "vector_store", limit=4),
        resolves_to="The enforcement mechanism, and what happens if the filter is omitted.",
    )]


# --------------------------------------------------------------------------
# EVIDENCE
# --------------------------------------------------------------------------

@check(
    id="evidence/no-tracing",
    area="evidence",
    question="After an incident, could anyone reconstruct what the agent did and why?",
    answerable="partial",
    applies_when="consequential tools exist",
    satisfied_by=["tracing, structured decision logs, or an eval harness recording runs"],
    refuted_by=["tracing is injected by the platform or a sidecar outside this repository"],
)
def _evidence_none(inv: dict) -> list[Candidate]:
    tools = _consequential(inv)
    if not tools or _has(inv, "observability"):
        return []
    return [Candidate(
        check_id="evidence/no-tracing",
        area="evidence",
        bucket="inferred",
        consequence="high",
        title="No tracing or structured logging alongside consequential tools",
        detail=(
            "Tools here send, write, or execute, and no tracing platform, OpenTelemetry wiring, or "
            "structured logging was found. If that holds, an incident review has the external "
            "side effects and nothing linking them to the decision that produced them."
        ),
        evidence=_tool_ev(tools, limit=4),
        refuted_by=["tracing is injected by the platform or a sidecar outside this repository"],
        resolves_to="Show what a reviewer would read to reconstruct one completed run.",
    )]


@check(
    id="evidence/logging-without-redaction",
    area="evidence",
    question="Could the trace or log pipeline itself become the leak?",
    answerable="partial",
    applies_when="logging or tracing exists without redaction",
    satisfied_by=["redaction applied before emission, not after ingestion"],
    refuted_by=["redaction is applied by the collector or platform downstream"],
)
def _evidence_redaction(inv: dict) -> list[Candidate]:
    if not _has(inv, "observability"):
        return []
    if _has(inv, "data_handling", "redaction", "pii_detection"):
        return []
    return [Candidate(
        check_id="evidence/logging-without-redaction",
        area="evidence",
        bucket="inferred",
        consequence="medium",
        title="Traces and logs are produced with no redaction signal",
        detail=(
            "Observability is wired up and no redaction, masking, or PII-detection step was found. "
            "Agent traces are unusually rich — prompts, retrieved content, tool arguments, tool "
            "results — so the pipeline built to explain the system can become a second copy of "
            "whatever the system touched, usually with broader access than the source."
        ),
        evidence=_ev(inv, "observability", limit=5),
        refuted_by=["redaction is applied by the collector or platform downstream"],
        resolves_to="Read one real trace end to end and note what you would not want in a ticket.",
    )]


# --------------------------------------------------------------------------
# DATA GOVERNANCE
# --------------------------------------------------------------------------

@check(
    id="data/egress-without-classification",
    area="data",
    question="Is anything checking what class of data leaves, and where it may go?",
    answerable="partial",
    applies_when="tools send outward or literal external hosts appear",
    satisfied_by=["a classification step or destination policy consulted before an outbound call"],
    refuted_by=["egress policy is enforced at a gateway outside this repository"],
)
def _data_egress(inv: dict) -> list[Candidate]:
    senders = [t for t in _tools(inv, ("writes", "executes"))
               if any(e["kind"] in ("messaging", "network_write") for e in t["side_effects"])]
    hosts = inv.get("egress_hosts") or {}
    if not senders and not hosts:
        return []
    if _has(inv, "data_handling", "classification"):
        return []
    parts = []
    if senders:
        parts.append(", ".join(f"`{t['name']}`" for t in senders[:5]))
    detail = (
        "No data-classification signal was found anywhere in the scanned source, and these paths "
        "carry data outward"
        + (f": {parts[0]}." if parts else ".")
        + " Without a class attached to the content, an outbound call cannot be evaluated against "
          "a destination policy — every send is treated the same whether it carries a public FAQ "
          "or a customer record."
    )
    if hosts:
        detail += (
            f" {len(hosts)} external host(s) appear as literals; destinations built at runtime "
            "would not appear here at all."
        )
    return [Candidate(
        check_id="data/egress-without-classification",
        area="data",
        bucket="inferred",
        consequence="high",
        title="Outbound paths with no data-classification signal",
        evidence=_tool_ev(senders, limit=4) + _ev(inv, "egress_hosts", limit=3),
        detail=detail,
        refuted_by=["egress policy is enforced at a gateway outside this repository"],
        resolves_to="Show what decides that a given payload may go to a given destination.",
        subjects=_names(senders),
    )]


@check(
    id="data/non-network-egress",
    area="data",
    question="Which non-network paths can carry data out of its authorised audience?",
    answerable="team",
    applies_when="any tool writes files, commits, or posts messages",
)
def _data_non_network(inv: dict) -> list[Candidate]:
    kinds = {e["kind"] for t in _tools(inv) for e in t["side_effects"]}
    kinds |= set(inv.get("side_effects_outside_tools") or {})
    relevant = kinds & {"fs_write", "vcs_write", "messaging"}
    if not relevant:
        return []
    return [Candidate(
        check_id="data/non-network-egress",
        area="data",
        bucket="team",
        consequence="medium",
        title="Non-network egress paths need naming",
        detail=(
            "Egress is not only outbound HTTP. This system writes through "
            + ", ".join(sorted(EGRESS_WORDS.get(k, k) for k in relevant))
            + ". A file export, a commit message, a ticket comment, a rendered link, a log line, and "
              "a handoff to another agent are all ways data reaches an audience it was not scoped "
              "for. Ask which of these the team already counts as egress — usually the answer is "
              "the network one only."
        ),
        evidence=_ev(inv, "side_effects_outside_tools", limit=4),
        resolves_to="An enumerated list of egress channels this system actually has.",
    )]


@check(
    id="data/residency-and-retention",
    area="data",
    question="Where may this data live, and for how long?",
    answerable="team",
    applies_when="a model provider is called and any state is stored",
)
def _data_residency(inv: dict) -> list[Candidate]:
    calls_model = bool(inv.get("frameworks"))
    if not calls_model:
        return []
    stores = _has(inv, "persistence")
    return [Candidate(
        check_id="data/residency-and-retention",
        area="data",
        bucket="team",
        consequence="medium",
        title="Provider retention and data residency are not visible in code",
        detail=(
            "The code shows which model providers are called; it cannot show what those providers "
            "retain, in which region, or under what agreement. "
            + ("It also stores state locally, which adds a second retention question with a "
               "different owner. " if stores else "")
            + "Worth asking as one question: for the most sensitive thing this agent handles, "
              "name every place a copy currently exists."
        ),
        evidence=_ev(inv, "frameworks", limit=3),
        resolves_to="Provider terms per data class, and a list of every store holding a copy.",
    )]


# --------------------------------------------------------------------------
# CONTEXT
# --------------------------------------------------------------------------

@check(
    id="context/untrusted-content-reaches-model",
    area="context",
    question="Can content the agent fetched become an instruction it follows?",
    answerable="partial",
    applies_when="retrieval, web fetch, or file ingestion feeds the model",
    satisfied_by=["provenance carried with retrieved content", "a structural separation between instruction and data"],
    refuted_by=["all retrieved content originates inside a trust boundary the team controls"],
)
def _context_untrusted(inv: dict) -> list[Candidate]:
    retrieval = _has(inv, "persistence", "vector_store")
    readers = _tools(inv, ("read_only",))
    # A URL literal is NOT evidence that fetched content reaches the model. Infrastructure
    # endpoints -- object storage, sidecars, package mirrors -- are literals too. Requiring a
    # retrieval store or a read tool keeps this check on content that actually enters context.
    if not (retrieval or readers):
        return []
    sources = []
    if retrieval:
        sources.append("a vector store")
    if readers:
        sources.append(f"{len(readers)} read tool(s)")
    evidence = _tool_ev(readers, limit=3) + _ev(inv, "persistence", "vector_store", limit=2)
    if not evidence:
        return []
    return [Candidate(
        check_id="context/untrusted-content-reaches-model",
        area="context",
        bucket="inferred",
        consequence="high",
        title="Fetched content reaches the model with no visible provenance or trust marking",
        detail=(
            "Content arrives from " + " and ".join(sources) + ", and nothing in the scanned source "
            "marks where a piece of context came from or distinguishes it from operator "
            "instruction at the point the model reads it. The failure is not that retrieval is "
            "wrong — it is that retrieved text and instructions occupy the same channel, so a "
            "document can propose actions and be read as though the operator had."
        ),
        evidence=evidence,
        refuted_by=[
            "all retrieved content originates inside a trust boundary the team controls",
            "provenance is attached downstream of the retrieval call",
        ],
        resolves_to="Show how the model tells a retrieved document from an operator instruction.",
        subjects=_names(readers),
    )]


# --------------------------------------------------------------------------
# FLEET
# --------------------------------------------------------------------------

@check(
    id="fleet/fanout-without-bounds",
    area="fleet",
    question="What bounds how much work one run can create?",
    answerable="partial",
    applies_when="the agent spawns subagents or runs work in parallel",
    satisfied_by=["a concurrency bound, semaphore, budget, or quota on spawned work"],
    refuted_by=["fan-out is bounded by the platform's own scheduler outside this code"],
)
def _fleet_fanout(inv: dict) -> list[Candidate]:
    spawns = _has(inv, "concurrency", "subagent_spawn", "delegation", "parallel_execution")
    if not spawns or _has(inv, "concurrency", "concurrency_bound", "quota_or_breaker"):
        return []
    return [Candidate(
        check_id="fleet/fanout-without-bounds",
        area="fleet",
        bucket="inferred",
        consequence="medium",
        title="Fan-out or delegation with no visible concurrency bound",
        detail=(
            "This system spawns or parallelises work and no semaphore, concurrency cap, budget, or "
            "quota was found. Two distinct risks share this gap: a planner that keeps creating work "
            "while a downstream tool is already saturated, and a single run that consumes capacity "
            "other work needs."
        ),
        evidence=_ev(inv, "concurrency", "subagent_spawn", "delegation", "parallel_execution", limit=5),
        refuted_by=["fan-out is bounded by the platform's scheduler outside this code"],
        resolves_to="The number that caps concurrent work, and who owns it.",
    )]


@check(
    id="fleet/admission-and-fairness",
    area="fleet",
    question="What has to be true before a run is allowed to start, and can one caller starve another?",
    answerable="team",
    applies_when="the agent runs as a service, worker, or fleet",
)
def _fleet_admission(inv: dict) -> list[Candidate]:
    fleet_shape = (
        _has(inv, "concurrency", "subagent_spawn", "parallel_execution", "delegation")
        or _has(inv, "persistence", "checkpointer")
    )
    if not fleet_shape:
        return []
    return [Candidate(
        check_id="fleet/admission-and-fairness",
        area="fleet",
        bucket="team",
        consequence="medium",
        title="Admission and fairness are not visible in code",
        detail=(
            "This runs as a service rather than a one-shot script. Ask what must be true before a "
            "run is admitted — quota, clean worker, tool headroom, a way to produce evidence — and "
            "ask what happens when one caller's workload spikes. A queue with no admission policy "
            "accepts everything and fails later, and the failure surfaces somewhere other than "
            "where it was caused."
        ),
        evidence=_ev(inv, "concurrency", limit=3),
        resolves_to="The admission conditions, and whether isolation between callers exists.",
    )]


# --------------------------------------------------------------------------
# INTENT
# --------------------------------------------------------------------------

@check(
    id="intent/purpose-not-represented",
    area="intent",
    question="Does anything at runtime know what this run was authorised to accomplish?",
    answerable="partial",
    applies_when="consequential tools exist",
    satisfied_by=["a task or purpose value the runtime can evaluate a call against"],
    refuted_by=["purpose is enforced by a per-task credential or a separate agent per purpose"],
)
def _intent_purpose(inv: dict) -> list[Candidate]:
    tools = _consequential(inv)
    if len(tools) < 2:
        return []
    if _has(inv, "mediation", "policy_engine", "allow_deny_rules"):
        return []
    return [Candidate(
        check_id="intent/purpose-not-represented",
        area="intent",
        bucket="inferred",
        consequence="medium",
        title="Tool authorisation appears to be per-tool, not per-purpose",
        detail=(
            "Nothing found here represents what a given run was authorised to accomplish in a form "
            "the runtime could check a call against. A tool allowlist answers whether a call is "
            "permitted; it does not answer whether this call still serves the task the run was "
            "started for. The same "
            + f"`{tools[0]['name']}` "
            + "call can be correct for the ticket it was scoped to and a scope breach for an "
              "unrelated record that happened to be reachable."
        ),
        evidence=_tool_ev(tools, limit=4),
        refuted_by=["purpose is enforced by a per-task credential or a separate agent per purpose"],
        resolves_to="Show where the run's authorised purpose is recorded and what reads it.",
        subjects=_names(tools),
    )]


# --------------------------------------------------------------------------
# META — analysis integrity
# --------------------------------------------------------------------------

@check(
    id="meta/analysis-time-injection",
    area="meta",
    question="Does the repository contain text aimed at whatever reads it?",
    answerable="code",
    applies_when="always",
    satisfied_by=["no instruction-shaped text addressed to an automated reader"],
    refuted_by=["the text is a legitimate prompt template, test fixture, or documented example of an attack"],
)
def _meta_injection(inv: dict) -> list[Candidate]:
    hits = inv.get("suspicious_instructions") or []
    if not hits:
        return []
    return [Candidate(
        check_id="meta/analysis-time-injection",
        area="meta",
        bucket="observed",
        consequence="high",
        title=f"{len(hits)} line(s) contain instruction-shaped text addressed to a reader",
        detail=(
            "Text in this repository appears to address whatever tool or model reads it. Some of "
            "this will be legitimate — prompt templates, fixtures, documented attack examples — "
            "and each hit needs eyes. Anything that is not legitimate is a finding in its own "
            "right, and it means this analysis ran over content that was trying to steer it."
        ),
        evidence=hits[:10],
        refuted_by=["the text is a prompt template, test fixture, or a documented attack example"],
        resolves_to="Classify each line as template, fixture, or planted instruction.",
    )]


def run_all(inv: dict) -> list[Candidate]:
    """Evaluate every registered check against an inventory."""
    out: list[Candidate] = []
    for chk in REGISTRY:
        try:
            out.extend(chk.detect(inv) or [])
        except Exception as exc:  # a broken check must not silence the rest
            out.append(Candidate(
                check_id=chk.id, area=chk.area, bucket="team", consequence="low",
                title=f"Check {chk.id} failed to run",
                detail=f"The detector raised {type(exc).__name__}: {exc}. Treat this area as unchecked.",
            ))
    return out


def catalogue() -> list[dict]:
    return [c.to_dict() for c in REGISTRY]
