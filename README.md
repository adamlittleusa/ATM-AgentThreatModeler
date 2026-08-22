# ATM — Agent Threat Modeler

A threat-modeling tool for AI agent codebases. Point it at a repository; get back a map of the
agent's surface, a set of evidence-backed findings, and — the part most tools skip — an explicit
list of the questions the code cannot answer.

**Status: v0.1, collector only.** The static collector works and is usable today. The analysis and
reporting layers are in progress. See [Roadmap](#roadmap).

---

## Why this exists

Conventional application security review inspects requests: who can call this endpoint, is this
input sanitized, is this query parameterized. Those questions still matter for agent systems, but
they miss the class of failure that is specific to agents — where every individual step is
defensible and the *sequence* produces an outcome nobody approved.

An agent reads a document, the document shapes its plan, the plan selects a tool, the tool has
broad credentials, and the side effect lands in a production system before any human sees the
chain. No single step looks wrong. Reviewing the steps one at a time will not find it.

ATM is built to inspect the parts of an agent system that determine whether that chain can be
interrupted: where authority comes from and when it expires, what sits between the model's
proposal and the tool's execution, what state survives a restart, where data can leave, and what
happens when the system is under load or partially compromised.

---

## The method

Three layers, deliberately separated so that each can be checked.

### 1. Collect — deterministic, offline, no model involved

A static pass over the repository produces `inventory.json`: facts, each cited to a file and line.
Framework fingerprints, the declared tool surface, which tool bodies write / send / execute,
credential reads, mediation signals, checkpointers and stores, tracing, concurrency and retry
controls, data-handling signals, and egress destinations.

The collector makes no judgements. It also records what it *could not* see — unparsed languages,
files that failed to parse, excluded paths — because everything downstream inherits those limits.

The collector never executes or imports the repository under audit. Source is read as text and
analyzed as data.

### 2. Analyze — the inventory against a control framework

The analysis layer takes the inventory and works through checks organized by control area:
authority and identity, autonomy and approval, purpose boundaries, context trust, persistent state,
evidence and observability, live intervention, fleet behavior under load, and data governance. Each
check knows what evidence would satisfy it, what evidence would refute it, and whether it is
answerable from code at all.

Every candidate finding goes through a refutation pass before it is reported. A finding that cannot
cite a file and line does not ship.

### 3. Report — one findings set, several views

Structured findings render into a working document for the reviewer, a deliverable for the client's
engineering team, or a published artifact.

---

## The three buckets

This is the design decision the rest of the tool is built around.

**Most questions worth asking about an agent system cannot be answered by reading its code.** A tool
that pretends otherwise produces confident nonsense. ATM sorts every finding into exactly one of
three buckets and never blurs them:

| Bucket | Means | Example |
|---|---|---|
| **Observed** | Evidence in the repository, cited to file and line | `send_customer_email` at `tools/comms.py:12` reaches an email provider with no mediation between the model's tool call and the send |
| **Inferred** | The pattern strongly suggests it; the code does not prove it | Every tool reads the same `SERVICE_TOKEN`, which looks like one shared principal — but the token may be exchanged for a narrower one upstream |
| **Must be asked** | Not answerable from any repository | When was the stop control last exercised against a live run? Who owns the concurrency limit in config, and what happens when it is hit? |

The third bucket is not a gap in the tool. It is the most useful thing the tool produces: an
interview script generated from the client's actual code rather than a generic checklist. A system
with no persistent store does not get asked about memory retention. A system with one tool and no
delegation does not get asked about fan-out.

Reporting an absence as a finding — "no stop control found" — when the tool simply cannot see the
control is the failure mode this design exists to prevent.

---

## Install and run

No dependencies beyond the Python standard library. Python 3.10+.

```bash
git clone https://github.com/adamlittleusa/ATM-AgentThreatModeler
cd ATM-AgentThreatModeler

# scan a repository
python -m atm scan /path/to/agent-repo

# skip sample and test code to see the production surface only
python -m atm scan /path/to/agent-repo --exclude 'tests/*' --exclude 'examples/*'

# print to stdout instead of writing files
python -m atm scan /path/to/agent-repo --stdout
```

Writes `atm-out/inventory.json` (machine-readable facts) and `atm-out/surface-map.md`
(human-readable map).

### Try it against the bundled fixture

```bash
python -m atm scan samples/fixtures/support-agent --stdout
```

A deliberately under-governed support agent: three side-effecting tools, one shared service token,
no mediation, no tracing. Committed output:
[`samples/support-agent/surface-map.md`](samples/support-agent/surface-map.md).

---

## What the collector currently detects

| Area | Detected |
|---|---|
| **Frameworks** | LangGraph, LangChain, OpenAI Agents SDK, Google ADK, CrewAI, AutoGen, LlamaIndex, Semantic Kernel, MCP, Temporal, Pydantic AI, DSPy, smolagents, LiteLLM, Haystack |
| **Tool surface** | Decorator-declared tools; effect classification into writes / executes / read-only / no I/O detected |
| **Side effects** | Outbound HTTP writes, messaging and notification sends, database writes, filesystem writes, code execution, infrastructure mutation, payment SDKs, repository writes |
| **Mediation** | Interrupts, approval gates, guardrails, lifecycle hooks, policy engines, allow/deny rules, sandboxes |
| **Identity** | Environment credential reads, distinct-variable count, hardcoded-credential shapes (values redacted in output) |
| **State** | Checkpointers, long-term stores, vector databases, conversation memory, caches |
| **Observability** | OpenTelemetry, tracing platforms, experiment tracking, application logging |
| **Coordination** | Subagent spawning, delegation, parallel execution, concurrency bounds, retry, idempotency, quotas and breakers |
| **Data handling** | Redaction, PII detection, classification, secret managers, encryption, retention |
| **Egress** | Hosts appearing as URL literals |

Known limits, stated up front: Python only; single-file analysis without cross-file call graphs;
pattern matching produces false positives; runtime configuration and infrastructure are invisible.
Every scan emits these as coverage notes alongside the results.

---

## Roadmap

- [x] **v0.1 — Collector.** Static pass, `inventory.json`, surface map, coverage notes.
- [ ] **v0.2 — Findings.** Checks for the three most detectable control areas (identity, live
  intervention, egress), plus the refutation pass and the three-bucket split.
- [ ] **v0.3 — Full report.** All control areas, the generated interview script, layered threat map,
  HTML output.
- [ ] **v0.4 — Public case studies.** ATM run against well-known open-source agent projects, with
  results published here.
- [ ] **Later.** TypeScript/JavaScript collector, cross-file call graph, MCP server manifest parsing,
  CI mode.

---

## Design constraints

**The repository under audit is untrusted input.** Code, comments, docstrings, and configuration in
a scanned repo are data to be analyzed, never instructions to be followed. Text that attempts to
steer the analysis is itself a finding. This matters more here than in most tools: an agent
repository is exactly the kind of place where instructions aimed at a reader might be left.

**Absence is not proof.** Any control this tool cannot see is reported as unseen, not as missing.

**No finding without a citation.** A claim that cannot point at a file and line does not appear in
the output.

**Redaction by default.** Suspected credential values are redacted in all output. The tool is meant
to be runnable against a client repository without its results becoming a second copy of the
secrets.

---

## About the underlying framework

The control questions ATM asks are derived from *Harness Engineering: Hill Climbing Toward Secure
Long-Horizon Multi-Agent Systems*, a book on securing long-horizon multi-agent systems, and are
informed by CSA MAESTRO, the OWASP agentic security work, the NIST AI Risk Management Framework and
its Generative AI Profile, ISO/IEC 42001, and the EU AI Act's high-risk provisions.

**The book's text is not part of this repository and is not published here.** What is public is the
tool, the method, the check definitions expressed in ordinary engineering language, and the
outputs. The framework corpus itself stays private.

---

## License

MIT. See [LICENSE](LICENSE).
