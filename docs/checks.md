# Check catalogue

21 checks.

`answerable` records how much of a question a repository can settle: **code** — it can be answered outright; **partial** — the code raises it and only the team can close it; **team** — no repository can answer it, so it becomes a question.

## Autonomy and approval

### `autonomy/blast-radius`

**For each consequential tool, what is the worst outcome of one wrong call, and who absorbs it?**

- answerable: `team`
- applies when: any tool writes, sends, or executes

### `autonomy/consequential-without-approval`

**Can the agent take a consequential action without a human or policy decision?**

- answerable: `partial`
- applies when: any tool writes, sends, or executes
- satisfied by: an approval gate, interrupt, or policy decision on the path to the consequential tool
- refuted by: an approval or policy check exists in a wrapper, gateway, or registration path the collector did not parse; the tool is only reachable from an already-approved workflow; the effect classification is wrong on inspection

## Context trust

### `context/untrusted-content-reaches-model`

**Can content the agent fetched become an instruction it follows?**

- answerable: `partial`
- applies when: retrieval, web fetch, or file ingestion feeds the model
- satisfied by: provenance carried with retrieved content; a structural separation between instruction and data
- refuted by: all retrieved content originates inside a trust boundary the team controls

## Data governance

### `data/egress-without-classification`

**Is anything checking what class of data leaves, and where it may go?**

- answerable: `partial`
- applies when: tools send outward or literal external hosts appear
- satisfied by: a classification step or destination policy consulted before an outbound call
- refuted by: egress policy is enforced at a gateway outside this repository

### `data/non-network-egress`

**Which non-network paths can carry data out of its authorised audience?**

- answerable: `team`
- applies when: any tool writes files, commits, or posts messages

### `data/residency-and-retention`

**Where may this data live, and for how long?**

- answerable: `team`
- applies when: a model provider is called and any state is stored

## Evidence and observability

### `evidence/logging-without-redaction`

**Could the trace or log pipeline itself become the leak?**

- answerable: `partial`
- applies when: logging or tracing exists without redaction
- satisfied by: redaction applied before emission, not after ingestion
- refuted by: redaction is applied by the collector or platform downstream

### `evidence/no-tracing`

**After an incident, could anyone reconstruct what the agent did and why?**

- answerable: `partial`
- applies when: consequential tools exist
- satisfied by: tracing, structured decision logs, or an eval harness recording runs
- refuted by: tracing is injected by the platform or a sidecar outside this repository

## Fleet behavior under load

### `fleet/admission-and-fairness`

**What has to be true before a run is allowed to start, and can one caller starve another?**

- answerable: `team`
- applies when: the agent runs as a service, worker, or fleet

### `fleet/fanout-without-bounds`

**What bounds how much work one run can create?**

- answerable: `partial`
- applies when: the agent spawns subagents or runs work in parallel
- satisfied by: a concurrency bound, semaphore, budget, or quota on spawned work
- refuted by: fan-out is bounded by the platform's own scheduler outside this code

## Identity and delegation

### `identity/credential-lifetime`

**How long does each credential stay valid, and what revokes it mid-run?**

- answerable: `team`
- applies when: any credential is read

### `identity/hardcoded-credential`

**Are credentials present as literals in source?**

- answerable: `code`
- applies when: a credential-shaped literal is found
- satisfied by: credentials resolved from environment, a vault, or a workload identity
- refuted by: the literal is a placeholder, fixture, or public identifier; the value is already rotated and dead

### `identity/shared-principal`

**Does each tool act under a distinct, scoped principal?**

- answerable: `partial`
- applies when: credentials are read and more than one tool exists
- satisfied by: a distinct credential per tool or per operation class; token exchange before a privileged call
- refuted by: the shared token is exchanged upstream for a narrower one; all tools genuinely address one system under one scope; scoping happens at the gateway rather than in the credential

## Purpose boundaries

### `intent/purpose-not-represented`

**Does anything at runtime know what this run was authorised to accomplish?**

- answerable: `partial`
- applies when: consequential tools exist
- satisfied by: a task or purpose value the runtime can evaluate a call against
- refuted by: purpose is enforced by a per-task credential or a separate agent per purpose

## Analysis integrity

### `meta/analysis-time-injection`

**Does the repository contain text aimed at whatever reads it?**

- answerable: `code`
- applies when: always
- satisfied by: no instruction-shaped text addressed to an automated reader
- refuted by: the text is a legitimate prompt template, test fixture, or documented example of an attack

## Persistent state

### `state/persistence-without-expiry`

**Does anything the agent writes expire, and can it be deleted on request?**

- answerable: `partial`
- applies when: a checkpointer, store, or vector database exists
- satisfied by: a TTL, retention policy, or purge path on stored state
- refuted by: retention is enforced by the storage layer's own policy outside this code

### `state/vector-store-tenancy`

**What separates one tenant's or user's vectors from another's?**

- answerable: `team`
- applies when: a vector database is in use

## Live intervention

### `steering/effects-outside-tool-boundary`

**Does anything reach the outside world without crossing a tool boundary?**

- answerable: `code`
- applies when: write, send, or execute operations exist outside declared tools
- satisfied by: all external effects flow through declared, mediatable tools
- refuted by: the code is setup, migration, or test scaffolding not reachable at agent runtime

### `steering/irreversible-without-idempotency`

**If a consequential call is retried after an uncertain failure, can it happen twice?**

- answerable: `partial`
- applies when: consequential tools exist alongside retry logic
- satisfied by: an idempotency key recorded before the side effect; a ledger consulted before re-execution
- refuted by: the downstream API deduplicates natively; retries are disabled for these tools

### `steering/no-mediation-layer`

**Is there anything between the model's proposal and the tool's execution?**

- answerable: `partial`
- applies when: any tool exists
- satisfied by: an interrupt, guardrail, lifecycle hook, policy engine, allow/deny rules, or a sandbox
- refuted by: mediation lives in a gateway, proxy, or platform configuration outside this repository; the framework mediates by default in a way the collector did not fingerprint

### `steering/no-stop-control`

**Once a run is moving and looks wrong, what stops it?**

- answerable: `team`
- applies when: any consequential tool exists

