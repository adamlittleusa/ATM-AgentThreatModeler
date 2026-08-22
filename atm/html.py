"""Render candidate findings as a self-contained HTML page.

One file, no external requests, works in light and dark. Intended for sharing a
result with someone who will not run the tool, and for publishing a case study.
"""

from __future__ import annotations

import html as _html
from collections import defaultdict

from .checks import AREAS

BUCKET_META = {
    "observed": ("Observed", "Evidence is in the repository, cited to file and line."),
    "inferred": ("Inferred", "The pattern points this way; the code does not settle it."),
    "team": ("Questions for the team", "Not answerable from any repository."),
}

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
    'family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&'
    'family=IBM+Plex+Mono:wght@400;500&'
    'family=IBM+Plex+Sans:wght@400;500;600&display=swap">'
)

# Ground: cool paper rather than cream. Accent (indigo) is structural chrome only --
# links, citations, rules -- and is deliberately a different hue family from the three
# bucket colours, so severity never competes with navigation.
CSS = """
:root{
  --ground:#f6f7f8; --raised:#ffffff; --ink:#14171b; --muted:#5c636b;
  --rule:#dde1e5; --rule-soft:#e9edf0; --accent:#2f4d8a; --wash:#eef1f4;
  --observed:#9a3b30; --inferred:#8a6516; --team:#25655c;
  --serif:"Newsreader",ui-serif,Georgia,"Times New Roman",serif;
  --sans:"IBM Plex Sans",ui-sans-serif,-apple-system,"Segoe UI",system-ui,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#101317; --raised:#171b20; --ink:#e6e9ec; --muted:#98a1aa;
    --rule:#272d34; --rule-soft:#1e232a; --accent:#8fa9dd; --wash:#1a1f25;
    --observed:#e08d80; --inferred:#d9b563; --team:#79b8ac;
  }
}
:root[data-theme="dark"]{
  --ground:#101317; --raised:#171b20; --ink:#e6e9ec; --muted:#98a1aa;
  --rule:#272d34; --rule-soft:#1e232a; --accent:#8fa9dd; --wash:#1a1f25;
  --observed:#e08d80; --inferred:#d9b563; --team:#79b8ac;
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--sans); font-size:16.5px; line-height:1.65;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
:focus-visible{outline:2px solid var(--accent); outline-offset:3px; border-radius:2px}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}

.sheet{max-width:52rem;margin:0 auto;padding:4rem 1.5rem 7rem}
@media (max-width:36rem){.sheet{padding:2.5rem 1.15rem 4rem}}

/* masthead ------------------------------------------------------------- */
.mast{border-bottom:2px solid var(--ink);padding-bottom:1.5rem}
.eyebrow{
  font-family:var(--mono); font-size:.7rem; font-weight:500;
  letter-spacing:.14em; text-transform:uppercase; color:var(--muted);
  margin:0 0 .9rem;
}
h1{
  font-family:var(--serif); font-weight:500; font-size:clamp(2rem,5vw,2.9rem);
  line-height:1.08; letter-spacing:-.015em; margin:0; text-wrap:balance;
}
h1 .subject{display:block;font-family:var(--mono);font-size:.42em;font-weight:500;
  letter-spacing:-.005em;color:var(--accent);margin-top:.65rem;line-height:1.3}

.tallies{display:flex;flex-wrap:wrap;gap:2.25rem;margin:1.75rem 0 0;
  padding:1.25rem 0 0;border-top:1px solid var(--rule-soft)}
.tally b{display:block;font-family:var(--mono);font-size:2rem;font-weight:400;
  line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.tally span{display:block;font-family:var(--mono);font-size:.68rem;font-weight:500;
  letter-spacing:.12em;text-transform:uppercase;color:var(--muted);margin-top:.5rem}
.tally.observed b{color:var(--observed)}
.tally.inferred b{color:var(--inferred)}
.tally.team b{color:var(--team)}

.standfirst{
  font-family:var(--serif); font-size:1.08rem; line-height:1.6; color:var(--ink);
  background:var(--wash); border-left:2px solid var(--accent);
  padding:1.1rem 1.3rem; margin:2.5rem 0 0; max-width:62ch;
}
.standfirst strong{font-weight:600}

/* sections ------------------------------------------------------------- */
section{margin-top:4rem}
h2{
  font-family:var(--serif); font-weight:600; font-size:1.6rem; line-height:1.2;
  letter-spacing:-.012em; margin:0; padding-bottom:.55rem;
  border-bottom:1px solid var(--rule); display:flex; align-items:baseline;
  justify-content:space-between; gap:1rem;
}
h2 .count{font-family:var(--mono);font-size:.85rem;font-weight:400;color:var(--muted);
  font-variant-numeric:tabular-nums}
.lede{color:var(--muted);font-size:.95rem;margin:.85rem 0 0;max-width:62ch}
.empty{color:var(--muted);font-style:italic;margin:1.5rem 0 0}

/* one finding ---------------------------------------------------------- */
.entry{padding:2rem 0;border-bottom:1px solid var(--rule-soft)}
.entry:last-child{border-bottom:0}
.tag{display:flex;align-items:center;gap:.5rem;font-family:var(--mono);
  font-size:.68rem;font-weight:500;letter-spacing:.12em;text-transform:uppercase;
  margin:0 0 .7rem}
.dot{width:.45rem;height:.45rem;border-radius:50%;flex:none}
.observed .dot{background:var(--observed)} .observed .tag{color:var(--observed)}
.inferred .dot{background:var(--inferred)} .inferred .tag{color:var(--inferred)}
.team .dot{background:var(--team)} .team .tag{color:var(--team)}
.tag .sep{color:var(--rule)}
.tag .weight{color:var(--muted)}

h3{font-family:var(--serif);font-weight:600;font-size:1.22rem;line-height:1.3;
  letter-spacing:-.008em;margin:0 0 .7rem;text-wrap:balance;max-width:60ch}
.entry p{margin:0;max-width:64ch}
.slug{font-family:var(--mono);font-size:.74rem;color:var(--muted);
  margin:.9rem 0 0;word-break:break-all}

.label{font-family:var(--mono);font-size:.68rem;font-weight:500;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);margin:1.6rem 0 .6rem}

.evidence{list-style:none;margin:0;padding:0;border-left:1px solid var(--rule);
  overflow-x:auto}
.evidence li{padding:.45rem 0 .45rem 1rem}
.loc{display:block;font-family:var(--mono);font-size:.73rem;color:var(--accent);
  letter-spacing:-.01em}
.src{display:block;font-family:var(--mono);font-size:.79rem;line-height:1.5;
  color:var(--ink);white-space:pre;margin-top:.15rem}

.refute{margin:0;padding-left:1.1rem;max-width:62ch}
.refute li{color:var(--muted);font-size:.95rem;margin:.3rem 0}
.refute li::marker{color:var(--rule)}

.closes{margin:1.4rem 0 0;padding-top:.85rem;border-top:1px dotted var(--rule);
  font-size:.95rem;color:var(--muted);max-width:64ch}
.closes b{font-family:var(--mono);font-size:.68rem;font-weight:500;letter-spacing:.12em;
  text-transform:uppercase;color:var(--ink);display:block;margin-bottom:.2rem}

.owner{font-family:var(--sans);font-size:1rem;font-weight:600;margin:2.5rem 0 -.5rem;
  padding-bottom:.4rem;border-bottom:1px dotted var(--rule)}
.owner em{font-style:normal;font-weight:400;color:var(--muted);font-size:.9rem}

.notes{margin:1.5rem 0 0;padding-left:1.1rem;max-width:64ch}
.notes li{color:var(--muted);font-size:.95rem;margin:.5rem 0}
.notes li::marker{color:var(--rule)}

.colophon{margin-top:5rem;padding-top:1.5rem;border-top:2px solid var(--ink);
  font-family:var(--serif);font-size:.98rem;color:var(--muted);max-width:62ch}
code{font-family:var(--mono);font-size:.86em;background:var(--wash);
  padding:.1em .3em;border-radius:2px}
"""


def _e(t) -> str:
    return _html.escape(str(t), quote=False)


def render_html(fa: dict, inventory: dict | None = None) -> str:
    s = fa["summary"]
    target = _e(fa.get("target", {}).get("root", "target"))
    P: list[str] = []
    add = P.append

    add(f"<title>Agent threat model — {target}</title>")
    add(FONTS)
    add(f"<style>{CSS}</style>")
    add('<div class="sheet">')

    # --- masthead
    add("<header class=\"mast\">")
    add(f'<p class="eyebrow">ATM v{_e(fa.get("atm_version"))} · '
        f'{s["checks_run"]} checks · {len(s["areas_raised"])} control areas</p>')
    add(f'<h1>Agent threat model<span class="subject">{target}</span></h1>')
    add('<div class="tallies">')
    for key, cls, label in (
        ("observed", "observed", "observed"),
        ("inferred", "inferred", "inferred"),
        ("team_questions", "team", "for the team"),
    ):
        add(f'<div class="tally {cls}"><b>{s[key]}</b><span>{label}</span></div>')
    add("</div>")
    add("</header>")

    add(f'<p class="standfirst"><strong>These are candidates, not conclusions.</strong> '
        f'{_e(fa["next_step"])}</p>')

    tshape = fa.get("target_shape", "unknown")
    if tshape == "library":
        add('<p class="standfirst"><strong>This target reads as a library, not a deployed '
            'agent.</strong> Checks that assume a running system have been rerouted into questions '
            'for whoever embeds it — a library legitimately holds no credentials, mediates nothing, '
            'and has no deployment to govern. Point ATM at a consuming application for a real '
            'answer.</p>')
    elif tshape == "unknown":
        add('<p class="standfirst"><strong>Whether this is a deployed application or a library '
            'could not be determined.</strong> That distinction changes which findings below are '
            'meaningful. Settle it first.</p>')

    if inventory:
        fw = ", ".join(inventory.get("frameworks", {})) or "no framework fingerprinted"
        ts = inventory.get("tool_summary", {})
        by = ts.get("by_effect_class", {})
        parts = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(by.items(), key=lambda kv: -kv[1]))
        add("<section>")
        add('<h2>Surface</h2>')
        add(f'<p class="lede">Built on {_e(fw)}. {ts.get("count", 0)} declared tools'
            + (f" — {_e(parts)}." if parts else ".")
            + f' {inventory.get("target", {}).get("python_files_parsed", 0)} Python files parsed.</p>')
        add("</section>")

    # --- findings
    for bucket in ("observed", "inferred", "team"):
        items = fa["by_bucket"].get(bucket, [])
        title, note = BUCKET_META[bucket]
        add("<section>")
        add(f'<h2>{title}<span class="count">{len(items)}</span></h2>')
        add(f'<p class="lede">{note}</p>')
        if not items:
            add('<p class="empty">Nothing raised.</p></section>')
            continue

        if bucket == "team":
            grouped: dict[str, list[dict]] = defaultdict(list)
            for it in items:
                grouped[it["area"]].append(it)
            hints = fa.get("owner_hints", {})
            for area, group in sorted(grouped.items()):
                add(f'<p class="owner">{_e(AREAS.get(area, area))} '
                    f'<em>— usually answered by {_e(hints.get(area, "the team"))}</em></p>')
                for it in group:
                    add(_finding(it, bucket))
        else:
            for it in items:
                add(_finding(it, bucket))
        add("</section>")

    # --- coverage
    add("<section>")
    add('<h2>Coverage</h2>')
    add('<p class="lede">Every finding above inherits these limits.</p>')
    add('<ul class="notes">')
    for n in fa.get("coverage_notes", []):
        add(f"<li>{_e(n)}</li>")
    add("<li>Checks are matched against a static inventory. A control implemented in a way the "
        "collector does not fingerprint reads here as absent — which is why absences are phrased "
        "as unseen, and why the refutation pass exists.</li>")
    add("</ul>")
    add("</section>")

    add('<p class="colophon">No score is produced, deliberately. A number invites a target, and a '
        'system tuned to a threat-model score has learned to satisfy the scanner rather than the '
        'threat.</p>')
    add("</div>")
    return "\n".join(P)


def _finding(it: dict, bucket: str) -> str:
    P: list[str] = []
    add = P.append
    label = {"observed": "Observed", "inferred": "Inferred", "team": "Question"}[bucket]
    add(f'<article class="entry {bucket}">')
    add('<p class="tag"><span class="dot"></span>'
        f'{label}<span class="sep">/</span>{_e(it.get("area_label", it["area"]))}'
        f'<span class="sep">/</span><span class="weight">'
        f'{_e(it.get("consequence", ""))} consequence</span></p>')
    add(f'<h3>{_e(it["title"])}</h3>')
    add(f'<p>{_e(it["detail"])}</p>')

    if it.get("evidence"):
        add('<p class="label">Evidence</p><ul class="evidence">')
        for e in it["evidence"][:8]:
            add(f'<li><span class="loc">{_e(e["file"])}:{e["line"]}</span>'
                f'<span class="src">{_e(e["snippet"])}</span></li>')
        add("</ul>")

    if it.get("refuted_by"):
        add('<p class="label">Would be wrong if</p><ul class="refute">')
        for r in it["refuted_by"]:
            add(f"<li>{_e(r)}</li>")
        add("</ul>")

    if it.get("resolves_to"):
        add(f'<p class="closes"><b>Closes when</b>{_e(it["resolves_to"])}</p>')
    add(f'<p class="slug">{_e(it["check_id"])}</p>')
    add("</article>")
    return "\n".join(P)
