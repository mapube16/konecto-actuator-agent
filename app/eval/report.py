"""Render a self-contained HTML report (Chart.js from CDN, no build step, no server).

One file you open in a browser: overall accuracy, accuracy by category, retrieval
health, the historical trend across runs, and a per-case table flagging regressions.
"""

from __future__ import annotations

import json
from pathlib import Path

REPORT_PATH = Path(__file__).resolve().parents[2] / "eval_report.html"

_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Konecto Eval Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
 body{{font-family:system-ui,sans-serif;margin:2rem;background:#0f1117;color:#e6e6e6}}
 h1,h2{{font-weight:600}} h1{{margin-bottom:.2rem}}
 .sub{{color:#8b94a7;margin-top:0}}
 .grid{{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin:1.5rem 0}}
 .card{{background:#1a1d27;border:1px solid #2a2f3d;border-radius:10px;padding:1.2rem}}
 .big{{font-size:2.4rem;font-weight:700}} .ok{{color:#4ade80}} .bad{{color:#f87171}} .warn{{color:#fbbf24}}
 table{{width:100%;border-collapse:collapse;margin-top:.5rem;font-size:.9rem}}
 th,td{{text-align:left;padding:.45rem .6rem;border-bottom:1px solid #2a2f3d}}
 th{{color:#8b94a7;font-weight:500}}
 .pill{{padding:.1rem .5rem;border-radius:6px;font-size:.78rem;font-weight:600}}
 .pass{{background:#13371f;color:#4ade80}} .fail{{background:#3a1414;color:#f87171}}
 .tag-regressed{{background:#3a1414;color:#f87171}} .tag-improved{{background:#13371f;color:#4ade80}}
 .tag-new{{background:#1e293b;color:#93c5fd}}
 code{{color:#93c5fd}}
</style></head><body>
<h1>Konecto Actuator Agent — Evaluation Report</h1>
<p class="sub">Run <code>{timestamp}</code> · model <code>{model}</code> · judge <code>{judge_model}</code></p>

<div class="grid">
 <div class="card"><div>End-to-End Accuracy</div>
   <div class="big {acc_class}">{accuracy:.0%}</div>
   <div class="sub">{passed}/{total} cases · gate {gate:.0%} · {gate_verdict}</div></div>
 <div class="card"><div>Retrieval recall@{k} / precision@{k}</div>
   <div class="big {recall_class}">{recall:.0%} <span style="font-size:1.2rem;color:#8b94a7">/ {precision:.0%}</span></div>
   <div class="sub">index {indexed}/{catalog_rows} docs · {index_verdict}</div>
   <div class="sub" style="margin-top:.6rem">{recall_segments}</div></div>
</div>

<div class="grid">
 <div class="card"><h2>Accuracy by Category</h2><canvas id="catChart"></canvas></div>
 <div class="card"><h2>Accuracy Trend</h2><canvas id="trendChart"></canvas></div>
</div>

<div class="card"><h2>Run-over-Run Changes</h2>
 <p>{diff_summary}</p></div>

<div class="card" style="margin-top:1.5rem"><h2>Per-Case Results</h2>
 <table><thead><tr><th>Case</th><th>Category</th><th>Grader</th><th>Result</th><th>Detail</th><th>Δ</th></tr></thead>
 <tbody>{rows}</tbody></table></div>

<script>
const catData = {cat_json};
new Chart(document.getElementById('catChart'), {{
  type:'bar',
  data:{{labels:Object.keys(catData),datasets:[{{label:'accuracy',
    data:Object.values(catData).map(v=>Math.round(v*100)),
    backgroundColor:Object.values(catData).map(v=>v>=0.8?'#4ade80':v>=0.5?'#fbbf24':'#f87171')}}]}},
  options:{{scales:{{y:{{beginAtZero:true,max:100,ticks:{{color:'#8b94a7'}}}},x:{{ticks:{{color:'#8b94a7'}}}}}},
    plugins:{{legend:{{display:false}}}}}}
}});
const trend = {trend_json};
new Chart(document.getElementById('trendChart'), {{
  type:'line',
  data:{{labels:trend.map(t=>t.ts),datasets:[
    {{label:'E2E accuracy',data:trend.map(t=>Math.round(t.acc*100)),borderColor:'#4ade80',tension:.2}},
    {{label:'retrieval recall',data:trend.map(t=>Math.round(t.recall*100)),borderColor:'#93c5fd',tension:.2}}
  ]}},
  options:{{scales:{{y:{{beginAtZero:true,max:100,ticks:{{color:'#8b94a7'}}}},x:{{ticks:{{color:'#8b94a7'}}}}}},
    plugins:{{legend:{{labels:{{color:'#e6e6e6'}}}}}}}}
}});
</script>
</body></html>"""


def _category_accuracy(cases: list[dict]) -> dict[str, float]:
    by_cat: dict[str, list[bool]] = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).append(c["passed"])
    return {cat: sum(v) / len(v) for cat, v in by_cat.items()}


def _rows_html(cases: list[dict], diff: dict) -> str:
    tag_of = {}
    for name in diff.get("regressed", []):
        tag_of[name] = '<span class="pill tag-regressed">regressed</span>'
    for name in diff.get("improved", []):
        tag_of[name] = '<span class="pill tag-improved">improved</span>'
    for name in diff.get("new", []):
        tag_of[name] = '<span class="pill tag-new">new</span>'
    out = []
    for c in cases:
        verdict = '<span class="pill pass">PASS</span>' if c["passed"] else '<span class="pill fail">FAIL</span>'
        out.append(
            f"<tr><td><code>{c['name']}</code></td><td>{c['category']}</td>"
            f"<td>{c['grader']}</td><td>{verdict}</td><td>{c['detail']}</td>"
            f"<td>{tag_of.get(c['name'], '')}</td></tr>"
        )
    return "\n".join(out)


def render(run: dict, trend: list[dict], diff: dict) -> str:
    cases = run["cases"]
    cat_acc = _category_accuracy(cases)
    retr = run["retrieval"]
    health = retr["index_health"]
    seg = retr.get("recall_by_kind", {})
    seg_html = " &nbsp; ".join(
        f'<span class="{("ok" if v >= 0.8 else "warn" if v >= 0.5 else "bad")}">{k}: {v:.0%}</span>'
        for k, v in seg.items()
    ) or "—"
    diff_parts = []
    if diff.get("regressed"):
        diff_parts.append(f'<span class="bad">⚠ {len(diff["regressed"])} regressed: {", ".join(diff["regressed"])}</span>')
    if diff.get("improved"):
        diff_parts.append(f'<span class="ok">↑ {len(diff["improved"])} improved: {", ".join(diff["improved"])}</span>')
    if diff.get("new"):
        diff_parts.append(f'{len(diff["new"])} new case(s)')
    if not diff_parts:
        diff_parts.append("No change vs previous run.")

    return _TEMPLATE.format(
        timestamp=run["timestamp"],
        model=run.get("model", "?"),
        judge_model=run.get("judge_model", "?"),
        accuracy=run["accuracy"],
        acc_class="ok" if run["accuracy"] >= run["gate"] else "bad",
        passed=run["passed"],
        total=run["total"],
        gate=run["gate"],
        gate_verdict="PASS" if run["accuracy"] >= run["gate"] else "BELOW GATE",
        recall=retr["recall_at_k"],
        precision=retr.get("precision_at_k", 0.0),
        recall_class="ok" if retr["recall_at_k"] >= 0.8 else "warn",
        k=retr["k"],
        indexed=health["indexed_docs"],
        catalog_rows=health["catalog_rows"],
        index_verdict="healthy" if health["healthy"] else f"MISMATCH ({health['delta']:+d})",
        recall_segments=seg_html,
        diff_summary=" &nbsp;·&nbsp; ".join(diff_parts),
        rows=_rows_html(cases, diff),
        cat_json=json.dumps(cat_acc),
        trend_json=json.dumps(trend),
    )


def write_report(run: dict, trend: list[dict], diff: dict) -> Path:
    REPORT_PATH.write_text(render(run, trend, diff), encoding="utf-8")
    return REPORT_PATH


if __name__ == "__main__":
    # Self-check: render produces valid HTML containing the key numbers.
    fake = {
        "timestamp": "2026-06-30T00:00:00Z", "model": "gpt-5-mini", "judge_model": "openai/gpt-4o-mini",
        "accuracy": 0.9, "passed": 9, "total": 10, "gate": 0.8,
        "retrieval": {"recall_at_k": 0.88, "precision_at_k": 0.88, "k": 5, "recall_by_kind": {"fuzzy": 1.0, "numeric": 0.7, "categorical": 1.0}, "index_health": {"indexed_docs": 111, "catalog_rows": 111, "healthy": True, "delta": 0}},
        "cases": [{"name": "t1", "category": "exact", "grader": "exact", "passed": True, "detail": "ok"}],
    }
    html = render(fake, [{"ts": "r1", "acc": 0.9, "recall": 0.8}], {"regressed": [], "improved": [], "new": ["t1"]})
    assert "<html" in html and "90%" in html, "report must render accuracy"
    assert "Chart" in html, "report must embed Chart.js"
    print("OK — report renders valid HTML with metrics")
