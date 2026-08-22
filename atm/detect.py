"""Detectors: turn source files into cited facts.

Every detector returns Evidence records carrying file, line, and a verbatim snippet.
No detector makes a judgement. Judgement happens in the analysis layer, which cites
these records. If a detector cannot see something, it says so in coverage notes
rather than guessing.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------

@dataclass
class Evidence:
    file: str
    line: int
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


def _snippet(source_lines: list[str], line: int, max_len: int = 160) -> str:
    if 1 <= line <= len(source_lines):
        text = source_lines[line - 1].strip()
        return text[:max_len]
    return ""


# --------------------------------------------------------------------------
# Framework fingerprints
# --------------------------------------------------------------------------
# Module prefix -> framework label. Longest prefix wins.
FRAMEWORK_MODULES = {
    "langgraph": "LangGraph",
    "langchain": "LangChain",
    "langchain_core": "LangChain",
    "langchain_community": "LangChain",
    "langsmith": "LangSmith",
    "agents": "OpenAI Agents SDK",
    "openai": "OpenAI API",
    "anthropic": "Anthropic API",
    "google.adk": "Google ADK",
    "google.generativeai": "Google GenAI",
    "vertexai": "Google Vertex AI",
    "crewai": "CrewAI",
    "autogen": "AutoGen",
    "autogen_agentchat": "AutoGen",
    "llama_index": "LlamaIndex",
    "semantic_kernel": "Semantic Kernel",
    "mcp": "MCP",
    "fastmcp": "MCP",
    "temporalio": "Temporal",
    "celery": "Celery",
    "prefect": "Prefect",
    "dspy": "DSPy",
    "smolagents": "smolagents",
    "pydantic_ai": "Pydantic AI",
    "litellm": "LiteLLM",
    "haystack": "Haystack",
}

# --------------------------------------------------------------------------
# Tool declaration signatures
# --------------------------------------------------------------------------
TOOL_DECORATORS = {
    "tool": "LangChain @tool",
    "function_tool": "OpenAI Agents @function_tool",
    "agent_tool": "agent tool decorator",
    "mcp.tool": "MCP @mcp.tool",
    "server.tool": "MCP @server.tool",
    "app.tool": "MCP @app.tool",
    "register_tool": "register_tool",
    "tool_plugin": "tool_plugin",
    "kernel_function": "Semantic Kernel @kernel_function",
    "openai_function": "openai_function",
    "ai_function": "ai_function",
}

# --------------------------------------------------------------------------
# Side-effect signatures. Each entry: (regex, effect_kind, description)
# Ordered most-specific first; a tool can carry several.
# --------------------------------------------------------------------------
SIDE_EFFECT_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # network writes
    (re.compile(r"\b(requests|httpx|session|client)\s*\.\s*(post|put|patch|delete)\s*\("), "network_write", "outbound HTTP write"),
    (re.compile(r"\baiohttp\b.*\.(post|put|patch|delete)\s*\("), "network_write", "async HTTP write"),
    (re.compile(r"\burllib\.request\.urlopen\s*\("), "network_write", "urlopen"),
    # messaging / notification
    (re.compile(r"\b(smtplib|sendgrid|mailgun|postmark|mandrill|ses_client|send_email|send_mail|SendGridAPIClient)\b", re.I), "messaging", "email send"),
    (re.compile(r"\b(twilio|send_sms|sns_client|pusher|onesignal)\b", re.I), "messaging", "SMS/notification send"),
    (re.compile(r"\b(slack_sdk|chat_postMessage|discord|webhook)\b", re.I), "messaging", "chat/webhook post"),
    (re.compile(r"\b(client|mailer|sender|messenger|sg|ses|sns|smtp)\s*\.\s*send(_\w+)?\s*\(", re.I), "messaging", "client send call"),
    # database writes
    (re.compile(r"\.execute\s*\(\s*[\"'`].{0,40}\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE)\b", re.I), "db_write", "SQL write statement"),
    (re.compile(r"\.(commit|flush)\s*\(\s*\)"), "db_write", "transaction commit"),
    (re.compile(r"\.(save|insert_one|insert_many|update_one|update_many|delete_one|delete_many|put_item|delete_item)\s*\("), "db_write", "ORM/NoSQL write"),
    (re.compile(r"\bsession\s*\.\s*add\s*\("), "db_write", "session.add"),
    # filesystem writes
    (re.compile(r"\bopen\s*\([^)]*[\"'](w|a|wb|ab|w\+|a\+)[\"']"), "fs_write", "file opened for write"),
    (re.compile(r"\.write_(text|bytes)\s*\("), "fs_write", "Path write"),
    (re.compile(r"\b(shutil\.(copy|move|rmtree)|os\.(remove|unlink|rename|makedirs|rmdir))\s*\("), "fs_write", "filesystem mutation"),
    # code execution
    (re.compile(r"\bsubprocess\.(run|call|Popen|check_output|check_call)\s*\("), "exec", "subprocess execution"),
    (re.compile(r"\bos\.(system|popen|execv?p?)\s*\("), "exec", "shell execution"),
    (re.compile(r"(?<![\w.])(eval|exec)\s*\("), "exec", "dynamic code execution"),
    # cloud / infra mutation
    (re.compile(r"\bboto3\b|\.create_\w+\s*\(|\.terminate_\w+\s*\("), "infra_write", "cloud SDK mutation"),
    (re.compile(r"\b(kubernetes|docker)\b.*\.(create|delete|patch|replace)"), "infra_write", "orchestrator mutation"),
    # payment / money
    (re.compile(r"\b(stripe|braintree|paypal|plaid)\b"), "financial", "payment SDK"),
    # version control / deploy
    (re.compile(r"\bgit\s+(push|commit|merge)\b|\.create_pull\w*\(|\.merge\s*\("), "vcs_write", "repository write"),
]

# read-only signals, used only to distinguish "we saw activity but no writes"
READ_PATTERNS = [
    re.compile(r"\b(requests|httpx|session|client)\s*\.\s*get\s*\("),
    re.compile(r"\.execute\s*\(\s*[\"'`].{0,40}\bSELECT\b", re.I),
    re.compile(r"\.(find|find_one|query|scan|get_item|select)\s*\("),
    re.compile(r"\bopen\s*\([^)]*[\"'](r|rb)[\"']"),
]

# --------------------------------------------------------------------------
# Mediation: anything sitting between the model's proposal and the tool call
# --------------------------------------------------------------------------
MEDIATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\binterrupt\s*\(|\bNodeInterrupt\b|\bHumanInterrupt\b"), "interrupt"),
    (re.compile(r"\bhuman_in_the_loop\b|\bHumanInTheLoop\b|\bhitl\b", re.I), "human_in_the_loop"),
    (re.compile(r"\b(require_approval|needs_approval|await_approval|request_approval|approval_required)\b"), "approval_gate"),
    (re.compile(r"\b(input_guardrail|output_guardrail|guardrail|Guardrail)\b"), "guardrail"),
    (re.compile(r"\b(before_tool_callback|after_tool_callback|pre_tool|post_tool|PreToolUse|PostToolUse|on_tool_start|on_tool_end)\b"), "lifecycle_hook"),
    (re.compile(r"\b(opa|open_policy_agent|cedar|casbin|oso|permit\.io|authz)\b", re.I), "policy_engine"),
    (re.compile(r"\b(allowlist|allow_list|denylist|deny_list|blocklist|permission_rule)\b"), "allow_deny_rules"),
    (re.compile(r"\b(sandbox|Sandbox|firejail|gvisor|seccomp|nsjail)\b"), "sandbox"),
]

# --------------------------------------------------------------------------
# Persistence and state
# --------------------------------------------------------------------------
PERSISTENCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(MemorySaver|SqliteSaver|PostgresSaver|AsyncSqliteSaver|AsyncPostgresSaver|BaseCheckpointSaver|checkpointer)\b"), "checkpointer"),
    (re.compile(r"\b(InMemoryStore|BaseStore|PostgresStore)\b"), "long_term_store"),
    (re.compile(r"\b(chromadb|pinecone|weaviate|qdrant|pgvector|faiss|milvus|lancedb|Chroma|FAISS)\b"), "vector_store"),
    (re.compile(r"\b(ConversationBufferMemory|ConversationSummaryMemory|ChatMessageHistory|memory\s*=)\b"), "conversation_memory"),
    (re.compile(r"\bredis\b|\bRedis\(", re.I), "cache_or_state"),
]

# --------------------------------------------------------------------------
# Observability
# --------------------------------------------------------------------------
OBSERVABILITY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bopentelemetry\b|\botel\b", re.I), "opentelemetry"),
    (re.compile(r"\blangsmith\b|LANGCHAIN_TRACING|LANGSMITH_", re.I), "langsmith"),
    (re.compile(r"\b(logfire|braintrust|traceloop|arize|phoenix|helicone|langfuse|weave)\b", re.I), "tracing_platform"),
    (re.compile(r"\bwandb\b|\bmlflow\b", re.I), "experiment_tracking"),
    (re.compile(r"\blogging\.(getLogger|basicConfig)\b|\bstructlog\b|\bloguru\b"), "application_logging"),
]

# --------------------------------------------------------------------------
# Concurrency and fan-out
# --------------------------------------------------------------------------
CONCURRENCY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?<![\w.])Send\s*\(|\.spawn\s*\(|\bcreate_\w*agent\b\s*\([^)]*agents\s*="), "subagent_spawn"),
    (re.compile(r"\bcreate_react_agent\b|\bAgent\s*\(|\bworkflow\.compile\s*\("), "agent_construction"),
    (re.compile(r"\bsub_?agents?\b|\bhandoff\b|\bdelegate_to\b", re.I), "delegation"),
    (re.compile(r"\b(asyncio\.gather|ThreadPoolExecutor|ProcessPoolExecutor|as_completed)\b"), "parallel_execution"),
    (re.compile(r"\b(Semaphore|max_concurrency|max_workers|rate_limit|RateLimiter|ratelimit|Throttle)\b", re.I), "concurrency_bound"),
    (re.compile(r"\b(retry|tenacity|backoff|max_retries)\b", re.I), "retry"),
    (re.compile(r"\b(idempotenc|Idempotency-Key|idempotent_key)\w*", re.I), "idempotency"),
    (re.compile(r"\b(quota|bulkhead|circuit_breaker|CircuitBreaker)\b", re.I), "quota_or_breaker"),
]

# --------------------------------------------------------------------------
# Data-handling signals
# --------------------------------------------------------------------------
DATA_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(redact|anonymi[sz]e|mask_pii|scrub|sanitiz)\w*", re.I), "redaction"),
    (re.compile(r"\b(presidio|scrubadub|detect_pii|PIIMiddleware|dlp)\b", re.I), "pii_detection"),
    (re.compile(r"\b(classification|data_class|sensitivity_label|clearance)\b", re.I), "classification"),
    (re.compile(r"\b(vault|secretsmanager|SecretManager|keyvault|sops|1password)\b", re.I), "secret_manager"),
    (re.compile(r"\b(encrypt|decrypt|Fernet|AES|kms)\b"), "encryption"),
    (re.compile(r"\b(retention|ttl|expires_at|purge|tombstone)\b", re.I), "retention"),
]

# Hardcoded-secret shapes. Deliberately conservative — this is a signal, not a scanner.
SECRET_LITERAL = re.compile(
    r"""(?ix)
    (?:api[_-]?key|secret|token|password|passwd|credential|private[_-]?key)
    \s*[:=]\s*
    ["'][A-Za-z0-9_\-/+=]{16,}["']
    """
)

ENV_READ = re.compile(r"""os\.(?:environ\.get|getenv)\s*\(\s*["']([A-Z0-9_]+)["']|os\.environ\s*\[\s*["']([A-Z0-9_]+)["']\s*\]""")

URL_LITERAL = re.compile(r"""["'](https?://[^"'\s]+)["']""")

# Text that addresses whatever machine reads the repository. Deliberately narrow:
# this is a prompt for human eyes, not a classifier. Legitimate prompt templates
# will match, which is why every hit is reported for classification rather than
# treated as malicious.
INSTRUCTION_SHAPED = re.compile(
    r"""(?ix)
    (?:
      # override of a prior directive
        (?:ignore|disregard|forget)\s+(?:all\s+|any\s+)?
        (?:previous|prior|above|earlier|the\s+foregoing)\s+
        (?:instructions?|rules?|findings?|directions?|guidance)
      # suppression aimed at a reviewer or scanner
      | (?:do\s+not|don't|never)\s+(?:\w+\s+){0,2}
        (?:report|flag|raise|surface|include)\s+(?:\w+\s+){0,3}
        (?:finding|issue|vulnerabilit|weakness|credential|secret|risk)
      # a claim of prior clearance addressed at whatever reads it
      | (?:this|the\s+following)\s+(?:file|module|function|code|repo\w*|section)\s+
        (?:is|has\s+been|was)\s+
        (?:already\s+)?(?:vetted|pre-?approved|security[- ]reviewed|audited\s+and\s+cleared)
      # instruction to skip
      | (?:skip|exclude|omit|bypass)\s+(?:this|the\s+following)\s+
        (?:file|module|check|scan|audit|review|section|finding)
      # instruction to grade
      | (?:mark|treat|consider|report)\s+(?:this|it|the\s+\w+)\s+as\s+
        (?:safe|passing|compliant|secure|clean|no[- ]risk)
      # smuggled role framing
      | </?\s*(?:system|instructions?|im_start)\s*>
      | ^\s*(?:system|developer)\s*:\s*(?:you\s+(?:are|must|should)|ignore|disregard)
      # direct address to an automated reader
      | (?:AI|LLM|model|agent|assistant|automated)\s+
        (?:reviewer|auditor|scanner|reader|analy[sz]er)s?\s*[:,]
    )
    """
)


# --------------------------------------------------------------------------
# Per-file analysis
# --------------------------------------------------------------------------

@dataclass
class FileFacts:
    path: str
    lines: int
    parsed: bool = True
    parse_error: str | None = None
    frameworks: dict[str, list[Evidence]] = field(default_factory=dict)
    tools: list[dict] = field(default_factory=list)
    env_reads: dict[str, list[Evidence]] = field(default_factory=dict)
    secret_literals: list[Evidence] = field(default_factory=list)
    mediation: dict[str, list[Evidence]] = field(default_factory=dict)
    persistence: dict[str, list[Evidence]] = field(default_factory=dict)
    observability: dict[str, list[Evidence]] = field(default_factory=dict)
    concurrency: dict[str, list[Evidence]] = field(default_factory=dict)
    data_handling: dict[str, list[Evidence]] = field(default_factory=dict)
    urls: dict[str, list[Evidence]] = field(default_factory=dict)
    side_effects_outside_tools: dict[str, list[Evidence]] = field(default_factory=dict)
    suspicious_instructions: list[Evidence] = field(default_factory=list)


def _add(bucket: dict[str, list[Evidence]], key: str, ev: Evidence, cap: int = 12) -> None:
    lst = bucket.setdefault(key, [])
    if len(lst) < cap:
        lst.append(ev)


def _decorator_name(node: ast.expr) -> str:
    """Render a decorator expression back to a dotted name."""
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        base = _decorator_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _match_tool_decorator(dotted: str) -> str | None:
    if dotted in TOOL_DECORATORS:
        return TOOL_DECORATORS[dotted]
    tail = dotted.rsplit(".", 1)[-1]
    if tail in TOOL_DECORATORS:
        return TOOL_DECORATORS[tail]
    return None


def _classify_effects(body_text: str) -> tuple[list[dict], bool]:
    """Return (effects, saw_read_activity)."""
    effects: list[dict] = []
    seen: set[str] = set()
    for pattern, kind, desc in SIDE_EFFECT_PATTERNS:
        m = pattern.search(body_text)
        if m and kind not in seen:
            seen.add(kind)
            effects.append({"kind": kind, "description": desc, "matched": m.group(0)[:80]})
    saw_read = any(p.search(body_text) for p in READ_PATTERNS)
    return effects, saw_read


def analyze_python(path: Path, rel: str, text: str) -> FileFacts:
    src_lines = text.splitlines()
    facts = FileFacts(path=rel, lines=len(src_lines))

    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        facts.parsed = False
        facts.parse_error = f"{exc.msg} (line {exc.lineno})"
        tree = None

    # --- imports -> frameworks
    if tree is not None:
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for mod in mods:
                label = None
                best = ""
                for prefix, name in FRAMEWORK_MODULES.items():
                    if (mod == prefix or mod.startswith(prefix + ".")) and len(prefix) > len(best):
                        best, label = prefix, name
                if label:
                    _add(facts.frameworks, label, Evidence(rel, node.lineno, _snippet(src_lines, node.lineno)))

    # --- tools
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [_decorator_name(d) for d in node.decorator_list]
            matched = None
            for dotted in decorators:
                matched = _match_tool_decorator(dotted)
                if matched:
                    break
            if not matched:
                continue
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            body_text = "\n".join(src_lines[node.lineno - 1 : end])
            effects, saw_read = _classify_effects(body_text)
            if effects:
                effect_class = "writes"
                if any(e["kind"] == "exec" for e in effects):
                    effect_class = "executes"
            elif saw_read:
                effect_class = "read_only"
            else:
                effect_class = "no_io_detected"
            facts.tools.append({
                "name": node.name,
                "declared_by": matched,
                "file": rel,
                "line": node.lineno,
                "end_line": end,
                "docstring": (ast.get_docstring(node) or "").strip().split("\n")[0][:200],
                "effect_class": effect_class,
                "side_effects": effects,
                "evidence": Evidence(rel, node.lineno, _snippet(src_lines, node.lineno)).to_dict(),
            })

    # --- line-oriented scans
    tool_ranges = [(t["line"], t["end_line"]) for t in facts.tools]

    def inside_tool(lineno: int) -> bool:
        return any(a <= lineno <= b for a, b in tool_ranges)

    for i, line in enumerate(src_lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        ev = Evidence(rel, i, stripped[:160])

        # Instruction-shaped text is scanned everywhere, comments included --
        # a planted instruction is most likely to be left in a comment.
        if INSTRUCTION_SHAPED.search(line) and len(facts.suspicious_instructions) < 25:
            facts.suspicious_instructions.append(ev)

        if stripped.startswith("#"):
            continue

        m = ENV_READ.search(line)
        if m:
            name = m.group(1) or m.group(2)
            if name:
                facts.env_reads.setdefault(name, [])
                if len(facts.env_reads[name]) < 8:
                    facts.env_reads[name].append(ev)

        if SECRET_LITERAL.search(line):
            if len(facts.secret_literals) < 20:
                # redact the value: keep the assignment shape, drop the literal
                redacted = re.sub(r"""["'][A-Za-z0-9_\-/+=]{16,}["']""", '"<REDACTED>"', stripped)
                facts.secret_literals.append(Evidence(rel, i, redacted[:160]))

        for pattern, key in MEDIATION_PATTERNS:
            if pattern.search(line):
                _add(facts.mediation, key, ev)
        for pattern, key in PERSISTENCE_PATTERNS:
            if pattern.search(line):
                _add(facts.persistence, key, ev)
        for pattern, key in OBSERVABILITY_PATTERNS:
            if pattern.search(line):
                _add(facts.observability, key, ev)
        for pattern, key in CONCURRENCY_PATTERNS:
            if pattern.search(line):
                _add(facts.concurrency, key, ev)
        for pattern, key in DATA_PATTERNS:
            if pattern.search(line):
                _add(facts.data_handling, key, ev)

        for um in URL_LITERAL.finditer(line):
            url = um.group(1)
            host = re.sub(r"^https?://", "", url).split("/")[0].split("?")[0]
            if host:
                _add(facts.urls, host, ev, cap=6)

        is_import = stripped.startswith("import ") or stripped.startswith("from ")
        if not inside_tool(i) and not is_import:
            for pattern, kind, _desc in SIDE_EFFECT_PATTERNS:
                if pattern.search(line):
                    _add(facts.side_effects_outside_tools, kind, ev, cap=8)

    return facts


def analyze_manifest(rel: str, text: str) -> dict[str, list[Evidence]]:
    """Framework fingerprints from dependency manifests."""
    found: dict[str, list[Evidence]] = {}
    for i, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        if not low.strip() or low.strip().startswith("#"):
            continue
        for prefix, label in FRAMEWORK_MODULES.items():
            token = prefix.split(".")[0].replace("_", "-")
            if re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", low):
                _add(found, label, Evidence(rel, i, line.strip()[:160]), cap=4)
    return found
