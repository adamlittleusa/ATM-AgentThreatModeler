# Method

How ATM turns a repository into a threat model. This document describes the process and the check
taxonomy. It does not reproduce the source framework's text.

---

## The problem with scanning an agent

A static analyzer is good at questions of the form *does this line do a dangerous thing*. Agent
systems fail differently. The dangerous property is usually not in a line; it is in a **path** —
a sequence of individually reasonable steps whose composition nobody authorized.

Three properties make agent code resist ordinary review:

**The control flow is chosen at runtime.** In ordinary software the developer writes the sequence
and the system executes it. In an agent system the model picks the next step after reading context
that arrives at runtime. You cannot read the source and know the path.

**Authority is often ambient.** A tool that holds a long-lived credential is authorized for
everything that credential can reach, for as long as the process lives, regardless of what task it
was started for.

**Most of the real controls are not in the repository.** Whether a stop control works, whether an
approval queue is staffed, whether a quota has an owner, whether a rollback has ever been rehearsed
— none of this is in the code, and all of it determines whether the system is governable.

ATM is built around the third property rather than in spite of it.

---

## Layer 1 — Collect

Deterministic, offline, no model. Produces `inventory.json`.

The collector's contract:

- **Facts only.** Every record carries a file, a line, and the verbatim source snippet. No
  severities, no grades, no recommendations.
- **Never executes the target.** Source is read as text. The repository is not imported, its
  dependencies are not installed, its tests are not run.
- **Records its own blindness.** Unparsed languages, parse failures, excluded paths, and known
  pattern-matching limits are emitted as `coverage_notes` in the same document as the results.

What it extracts is chosen to answer one question per control area — not to be exhaustive, but to
be *sufficient to know which questions apply*:

| Extracted | Answers |
|---|---|
| Framework fingerprints | What execution model is this, and what primitives does it already have available? |
| Tool declarations and effect class | What can this agent actually do to the world? |
| Side-effecting code outside tools | What reaches the world without crossing a tool boundary? |
| Credential reads | How many distinct principals are there — and is it one? |
| Mediation signals | Is there anything between the model's proposal and the tool's execution? |
| Checkpointers, stores, vector DBs | What survives a restart, and can it influence a later run? |
| Tracing and logging | Could anyone reconstruct what happened after the fact? |
| Concurrency, retry, idempotency, quotas | What happens when this runs many times at once, or twice by accident? |
| Redaction, classification, retention | Is data handled by class, or by habit? |
| Egress hosts | Where can data go? |

---

## Layer 2 — Analyze

The inventory is checked against control areas. The areas are the framework's; the check logic is
expressed here in ordinary engineering terms.

### The nine control areas

**Autonomy and approval.** Which actions can this agent take without a human, and is that boundary
drawn by consequence or by convenience? An approval that arrives after the effect has landed is a
notification. Look for where the gate sits relative to the last point at which the action could
still be withdrawn.

**Identity and delegation.** Under whose authority does each tool call happen? A single shared token
across every tool means least privilege cannot be enforced at all — the ticket reader and the
refund issuer are the same principal to every downstream system. Look at the distinct-credential
count against the tool count, and at whether authority narrows when work is delegated.

**Purpose boundaries.** The same tool call can be correct or wrong depending on what the agent was
asked to accomplish. A tool allowlist answers "may this be called"; it does not answer "does this
call still serve the authorized task". Look for whether purpose is represented anywhere the runtime
can evaluate it.

**Context trust.** Content that arrives from retrieval, the web, files, or another agent is data.
The failure is when it becomes instruction. Look at whether retrieved content is distinguishable
from operator instruction at the point the model reads it, and whether the system tracks where a
piece of context came from.

**Persistent state.** Anything that survives a session can influence a later one. Checkpointers,
stores, vector databases, and "lessons learned" files are all durable writes, and durable writes
are how a one-time compromise becomes a standing one. Look at what can write, what can read, and
whether anything expires.

**Evidence and observability.** After an incident, can the team reconstruct what happened, why, and
under which policy? Two failure directions: no record at all, and a record so complete it becomes a
second copy of the sensitive data. Look for tracing, and look at what the traces would contain.

**Live intervention.** Once a run is moving and looks wrong, what can be done? Pause, deny, redirect,
degrade, stop, roll back. Each is a different capability and teams routinely have one and claim all
five. Look for interrupts, breakers, and stop controls — and note that their absence in code is
weak evidence, because they often live in infrastructure.

**Fleet behavior under load.** What happens at a hundred concurrent runs that does not happen at
one? Admission, quotas, isolation between tenants, back-pressure reaching the planner, retries that
do not double-charge. Look at fan-out, concurrency bounds, retry logic, and idempotency.

**Data governance.** What class of data does this touch, where can it go, and can that be shown
afterwards? Egress is not just the network — a commit message, a rendered image URL, a log line, and
a handoff to another agent are all ways data leaves its authorized audience.

### Check anatomy

Each check declares four things, which is what keeps the output honest:

```python
@check(
    id="identity/shared-principal",
    area="identity",
    question="Does each tool act under a distinct, scoped principal?",
    answerable="partial",          # code | partial | team
    applies_when="credentials are read and more than one tool exists",
    satisfied_by=["a distinct credential per tool or per operation class",
                  "token exchange before a privileged call"],
    refuted_by=["the shared token is exchanged upstream for a narrower one",
                "all tools genuinely address one system under one scope",
                "scoping happens at the gateway rather than in the credential"],
)
def _identity_shared(inventory) -> list[Candidate]:
    ...  # may only assert what the inventory shows, and must attach its evidence
```

`answerable` is what routes a check into one of the three buckets:

- **code** — a repository can settle the question outright. Produces an *observed* finding.
- **partial** — the code raises it; only the team can close it. Produces an *inferred* finding.
- **team** — no repository can answer it. Produces a *question*, never a finding.

A check marked `team` is forbidden from declaring `satisfied_by`, because there is no code
evidence that could satisfy it. That constraint is enforced by the test suite rather than by
convention.

`refuted_by` travels into the report with the finding. The refutation pass needs something
concrete to attack, and a reader deserves to know what would make the claim wrong before they
carry it into a meeting.

Checks live in Python rather than a data file so that predicate and prose stay together and stay
testable. The catalogue renders to markdown with `python -m atm checks`; the current one is at
[`checks.md`](checks.md).

### Refutation

Every candidate finding is attacked before it is reported. The default is to keep it; it is dropped
only on cited evidence that the control exists, the path is unreachable, or the classification was
wrong on inspection. Findings are not dropped because the code is pre-existing, because the system
is small, or because the team probably already knows.

Then every citation is re-opened and verified verbatim. A finding whose evidence does not hold up is
re-investigated, not shipped with a hedge.

---

## Layer 3 — Report

One structured findings set; several renderings.

The default rendering is a **reviewer's working document** — prep for a conversation with the team
rather than a document handed over cold. It leads with what the system is, so the findings are
legible to someone who has not read the repo; orders findings by consequence rather than by control
area; and ends with the coverage limits stated plainly enough that a reader knows which conclusions
would change if a limit were lifted.

It deliberately does **not** produce a score. A number invites a target, and a system optimized for
a threat-model score is a system that has learned to satisfy the scanner.

---

## Untrusted input

The repository under audit is untrusted. Its code, comments, docstrings, documentation, and test
fixtures are analysed as data and never followed as instruction. Text that attempts to steer the
analysis is reported as a finding in its own right, with its location.

This is not a theoretical concern for this tool in particular. An agent repository is precisely the
kind of place where text addressed to a machine reader might be left, and a threat modeler that can
be talked out of its findings is worse than no threat modeler.
