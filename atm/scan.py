"""Repo walk and inventory assembly.

The collector is deterministic and offline. It never executes the repository under
audit, never imports it, and never follows instructions found inside it. Files are
read as bytes and analysed as text.
"""

from __future__ import annotations

import json
from collections import defaultdict
from fnmatch import fnmatch
from dataclasses import asdict
from pathlib import Path

from . import detect
from .detect import Evidence, analyze_manifest, analyze_python

ATM_VERSION = "0.1.0"

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".next",
    "site-packages", ".tox", ".idea", ".vscode", "target", "vendor", ".terraform",
}

MANIFESTS = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml", "setup.py",
    "setup.cfg", "Pipfile", "environment.yml", "package.json", "poetry.lock",
    "uv.lock", "pdm.lock",
}

# Extensions we can only count, not parse. Their presence is a coverage note.
UNPARSED_CODE_EXT = {".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".rb", ".cs", ".php"}

MAX_FILE_BYTES = 2_000_000


def _merge_ev(dst: dict[str, list[dict]], src: dict[str, list[Evidence]], cap: int = 25) -> None:
    for key, items in src.items():
        bucket = dst.setdefault(key, [])
        for ev in items:
            if len(bucket) < cap:
                bucket.append(ev.to_dict())


def _detect_shape(root: Path, tools: list[dict], manifests: list[str]) -> tuple[str, list[str]]:
    """Application, library, or unknown.

    This matters because most checks assume a deployed system. A library is designed to
    be the infrastructure that sits outside the tool boundary, holds no credentials of
    its own, and has no deployment to govern. Reporting those as gaps is a category
    error, so the shape is detected, stated, and carried into the report.
    """
    why: list[str] = []
    lib, app = 0, 0

    for m in manifests:
        try:
            text = (root / m).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "[build-system]" in text:
            lib += 2
            why.append(f"`{m}` declares a build system, so this is packaged for distribution")
        if "[project.scripts]" in text or "console_scripts" in text:
            app += 1
            why.append(f"`{m}` declares a console entry point")

    if (root / "src").is_dir() and any((root / "src").glob("*/__init__.py")):
        lib += 2
        why.append("`src/` layout with an importable package")

    # An application usually has a runnable entry point that is not a CLI shim.
    for name in ("main.py", "app.py", "server.py", "worker.py", "run.py", "bot.py"):
        if (root / name).is_file():
            app += 2
            why.append(f"`{name}` at the repository root")
            break

    if tools:
        sample_like = sum(
            1 for t in tools
            if any(seg in t["file"] for seg in ("test", "example", "fixture", "demo", "sample"))
        )
        if sample_like / len(tools) > 0.6:
            lib += 1
            why.append(
                f"{sample_like} of {len(tools)} tool declarations sit in test or example paths, "
                "which is the shape of a library demonstrating itself"
            )
        elif sample_like == 0:
            app += 1
            why.append("tool declarations sit in production paths")

    if lib >= app + 2:
        return "library", why
    if app >= lib + 2:
        return "application", why
    return "unknown", why


def scan(root: Path, include_hidden: bool = False, exclude: list[str] | None = None) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"{root} is not a directory")
    exclude = exclude or []
    excluded_files = 0

    frameworks: dict[str, list[dict]] = {}
    tools: list[dict] = []
    env_reads: dict[str, list[dict]] = {}
    secret_literals: list[dict] = []
    mediation: dict[str, list[dict]] = {}
    persistence: dict[str, list[dict]] = {}
    observability: dict[str, list[dict]] = {}
    concurrency: dict[str, list[dict]] = {}
    data_handling: dict[str, list[dict]] = {}
    hosts: dict[str, list[dict]] = {}
    loose_side_effects: dict[str, list[dict]] = {}
    suspicious: list[dict] = []

    py_files = 0
    py_lines = 0
    total_files = 0
    unparsed_lang_counts: dict[str, int] = defaultdict(int)
    parse_failures: list[dict] = []
    manifests_seen: list[str] = []
    oversized: list[str] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        parts = set(path.relative_to(root).parts)
        if parts & SKIP_DIRS:
            continue
        if not include_hidden and any(p.startswith(".") and p not in {".", ".."} for p in path.relative_to(root).parts[:-1]):
            continue

        rel = path.relative_to(root).as_posix()
        if any(fnmatch(rel, pat) or rel.startswith(pat.rstrip("/") + "/") for pat in exclude):
            excluded_files += 1
            continue
        total_files += 1

        if path.suffix in UNPARSED_CODE_EXT:
            unparsed_lang_counts[path.suffix] += 1

        is_py = path.suffix == ".py"
        is_manifest = path.name in MANIFESTS
        if not (is_py or is_manifest):
            continue

        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                oversized.append(rel)
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            parse_failures.append({"file": rel, "reason": f"unreadable: {exc}"})
            continue

        if is_manifest:
            manifests_seen.append(rel)
            _merge_ev(frameworks, analyze_manifest(rel, text))
            if not is_py:
                continue

        facts = analyze_python(path, rel, text)
        py_files += 1
        py_lines += facts.lines
        if not facts.parsed:
            parse_failures.append({"file": rel, "reason": facts.parse_error or "parse error"})

        _merge_ev(frameworks, facts.frameworks)
        tools.extend(facts.tools)
        _merge_ev(mediation, facts.mediation)
        _merge_ev(persistence, facts.persistence)
        _merge_ev(observability, facts.observability)
        _merge_ev(concurrency, facts.concurrency)
        _merge_ev(data_handling, facts.data_handling)
        _merge_ev(hosts, facts.urls, cap=10)
        _merge_ev(loose_side_effects, facts.side_effects_outside_tools)
        for name, evs in facts.env_reads.items():
            bucket = env_reads.setdefault(name, [])
            for ev in evs:
                if len(bucket) < 10:
                    bucket.append(ev.to_dict())
        for ev in facts.secret_literals:
            if len(secret_literals) < 40:
                secret_literals.append(ev.to_dict())
        for ev in facts.suspicious_instructions:
            if len(suspicious) < 60:
                suspicious.append(ev.to_dict())

    # ---- effect summary
    effect_counts: dict[str, int] = defaultdict(int)
    for t in tools:
        effect_counts[t["effect_class"]] += 1
    effect_kinds: dict[str, int] = defaultdict(int)
    for t in tools:
        for e in t["side_effects"]:
            effect_kinds[e["kind"]] += 1

    # ---- coverage notes: what the collector could NOT see
    notes: list[str] = []
    if py_files == 0:
        notes.append(
            "No Python files were parsed. This collector only reads Python; any agent "
            "logic in another language is invisible to it and must be reviewed by hand."
        )
    for ext, count in sorted(unparsed_lang_counts.items(), key=lambda kv: -kv[1]):
        if count >= 5:
            notes.append(
                f"{count} {ext} files were counted but not parsed. If agent logic lives there, "
                "this inventory is incomplete."
            )
    if parse_failures:
        notes.append(
            f"{len(parse_failures)} file(s) failed to parse; their contents are absent from this inventory."
        )
    if oversized:
        notes.append(f"{len(oversized)} file(s) exceeded the size cap and were skipped.")
    if not manifests_seen:
        notes.append(
            "No dependency manifest was found, so framework detection rests on imports alone."
        )
    if tools and not mediation:
        notes.append(
            "No mediation signal (interrupt, approval, guardrail, hook, policy engine, sandbox) "
            "was found anywhere in the scanned source. Absence here is weak evidence: mediation "
            "may live in infrastructure this collector cannot see."
        )
    notes.append(
        "Effect classification is pattern-based. A tool marked no_io_detected may still cause "
        "side effects through a helper this collector did not follow across files."
    )
    notes.append(
        "Runtime configuration, deployment topology, IAM policy, and operational practice are "
        "outside the reach of any static pass and must be established by interview."
    )
    if suspicious:
        notes.append(
            f"{len(suspicious)} line(s) contain text shaped like an instruction to a machine reader. "
            "Prompt templates and test fixtures match this too; each needs classification by eye. "
            "Nothing in the scanned repository was followed as instruction."
        )
    if exclude:
        notes.append(
            f"{excluded_files} file(s) matched an --exclude pattern ({', '.join(exclude)}) and were "
            "not scanned. Anything they contain is absent from this inventory."
        )
    elif tools:
        test_like = sum(1 for t in tools if any(
            seg in t["file"] for seg in ("test", "tests/", "example", "examples/", "fixture", "demo/")))
        if test_like and test_like / len(tools) > 0.3:
            notes.append(
                f"{test_like} of {len(tools)} tool declarations sit in test, example, or fixture "
                "paths. Re-run with --exclude to separate production surface from sample code."
            )

    shape, shape_why = _detect_shape(root, tools, manifests_seen)
    if shape == "library":
        notes.insert(0,
            "This target looks like a LIBRARY or framework rather than a deployed agent. Checks "
            "that assume a running system — credentials, mediation, admission, egress policy — are "
            "reported as unresolved rather than as gaps, because a library legitimately has none "
            "of those. Point ATM at an application that consumes this library to get a real answer."
        )
    elif shape == "unknown":
        notes.insert(0,
            "Whether this target is a deployed application or a library could not be determined. "
            "That distinction changes which checks are meaningful; settle it before acting on "
            "anything below."
        )

    return {
        "atm_version": ATM_VERSION,
        "target": {
            "root": root.name,
            "shape": shape,
            "shape_evidence": shape_why,
            "excluded_patterns": exclude,
            "excluded_files": excluded_files,
            "files_seen": total_files,
            "python_files_parsed": py_files,
            "python_lines": py_lines,
            "manifests": manifests_seen,
            "unparsed_code_files": dict(unparsed_lang_counts),
        },
        "frameworks": frameworks,
        "tools": sorted(tools, key=lambda t: (t["file"], t["line"])),
        "tool_summary": {
            "count": len(tools),
            "by_effect_class": dict(effect_counts),
            "by_effect_kind": dict(effect_kinds),
        },
        "credentials": {
            "env_reads": env_reads,
            "distinct_env_vars": len(env_reads),
            "possible_hardcoded_secrets": secret_literals,
        },
        "mediation": mediation,
        "persistence": persistence,
        "observability": observability,
        "concurrency": concurrency,
        "data_handling": data_handling,
        "egress_hosts": hosts,
        "side_effects_outside_tools": loose_side_effects,
        "suspicious_instructions": suspicious,
        "parse_failures": parse_failures,
        "coverage_notes": notes,
    }


def write_inventory(inventory: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inventory, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return out
