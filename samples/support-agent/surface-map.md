# Agent surface map — `support-agent`

Collected by ATM v0.1.0 (static pass, Python only). Facts with citations; no findings and no grading. Read the coverage limits at the end before drawing conclusions from an absence.

**Scanned:** 5 Python files (106 lines) out of 6 files seen.

## Frameworks in use

- **LangChain** — `requirements.txt:2`, `tools/comms.py:4`, `tools/crm.py:6`
- **LangGraph** — `graph/build.py:4`, `graph/build.py:5`, `requirements.txt:1`
- **OpenAI API** — `graph/build.py:6`, `requirements.txt:3`

## Tool surface

**5 tools declared** — 3 writes, 1 no I/O detected, 1 read-only.

### Writes (3)

| Tool | Location | Detected effects | Declared by |
|---|---|---|---|
| `send_customer_email` | `tools/comms.py:12` | message / notification send | LangChain @tool |
| `update_customer_note` | `tools/crm.py:22` | outbound HTTP write | LangChain @tool |
| `issue_refund` | `tools/crm.py:31` | database write | LangChain @tool |

### Read-only (1)

| Tool | Location | Detected effects | Declared by |
|---|---|---|---|
| `lookup_customer` | `tools/crm.py:14` | — | LangChain @tool |

### No i/o detected (1)

| Tool | Location | Detected effects | Declared by |
|---|---|---|---|
| `summarize_thread` | `tools/comms.py:22` | — | LangChain @tool |

### Side-effecting code outside declared tools

Write, send, or execute operations found in source that is not inside a recognised tool declaration. These paths reach the outside world without passing a tool boundary.

- **messaging** — `worker.py:10`, `worker.py:19`
- **fs_write** — `worker.py:20`
- **network_write** — `worker.py:19`

## Mediation between proposal and execution

**No mediation signal was found in the scanned source** — no interrupt, approval gate, guardrail, lifecycle hook, policy engine, allow/deny rule set, or sandbox. This is an absence, not a proof: mediation can live in a gateway, proxy, or platform configuration outside this repository.

## Identity and credentials

**6 distinct environment variables** are read.

| Variable | Read at |
|---|---|
| `COMPLETION_WEBHOOK` | `worker.py:10` |
| `DATABASE_URL` | `tools/crm.py:9` |
| `OPENAI_API_KEY` | `graph/build.py:12` |
| `OPENAI_MODEL` | `graph/build.py:11` |
| `SENDGRID_API_KEY` | `tools/comms.py:8` |
| `SERVICE_TOKEN` | `tools/crm.py:8` |

## State and persistence

- **checkpointer** — `graph/build.py:4`, `graph/build.py:19`, `graph/build.py:21`

## Observability

_No tracing or structured logging was detected._

## Concurrency, retry, and coordination

- **subagent_spawn** — `graph/build.py:5`, `graph/build.py:21`

## Data handling

_No redaction, classification, PII detection, secret-manager, encryption, or retention signal was detected._

## Egress destinations

Hosts appearing as URL literals in source:

- **crm.internal.acme.example** — `tools/crm.py:10`
- **queue.acme.example** — `worker.py:9`

_Literal URLs are the visible fraction of egress. Destinations built at runtime from configuration, environment, or model output do not appear here._

## Coverage limits

What this pass could not see. Every conclusion drawn downstream inherits these limits.

- No mediation signal (interrupt, approval, guardrail, hook, policy engine, sandbox) was found anywhere in the scanned source. Absence here is weak evidence: mediation may live in infrastructure this collector cannot see.
- Effect classification is pattern-based. A tool marked no_io_detected may still cause side effects through a helper this collector did not follow across files.
- Runtime configuration, deployment topology, IAM policy, and operational practice are outside the reach of any static pass and must be established by interview.

---

_This is an inventory, not an assessment. It records what is present and what could not be seen. Turning it into findings requires the analysis pass, which separates what the code shows from what only the team can answer._
