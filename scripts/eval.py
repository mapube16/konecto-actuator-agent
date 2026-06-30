"""Evaluation CLI: runs retrieval + end-to-end accuracy, saves history, writes an HTML report.

Usage:
  python scripts/eval.py                      # full eval, write report, enforce 80% gate
  python scripts/eval.py --no-gate            # run without failing the build on low accuracy
  python scripts/eval.py --gate 0.9           # custom gate
  python scripts/eval.py --compare-prompts prompts/*.txt   # A/B prompt variants
  python scripts/eval.py --retrieval-only     # just index health + recall@k (fast, no LLM E2E)

The heavy lifting lives in app/eval/* (catalog, graders, retrieval, runner, history, report).
This file is the orchestration shell: build agent, call the harness, persist, report, gate.
"""

from __future__ import annotations

import argparse
import datetime
import glob
import sys
from pathlib import Path

# Make the package importable when run as `python scripts/eval.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from langgraph.checkpoint.sqlite import SqliteSaver

from app.agent import build_agent
from app.config import settings
from app.eval import history, report, retrieval, runner
from app.eval.cases import CASES
from app.prompts import SYSTEM_PROMPT


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _accuracy(cases: list[dict]) -> float:
    return sum(c["passed"] for c in cases) / len(cases) if cases else 0.0


def _print_table(cases: list[dict]) -> None:
    print(f"\n{'Case':<24}{'Category':<16}{'Grader':<8}{'Result':<7}Detail")
    print("-" * 90)
    for c in cases:
        mark = "PASS" if c["passed"] else "FAIL"
        print(f"{c['name']:<24}{c['category']:<16}{c['grader']:<8}{mark:<7}{c['detail']}")


def _build_run(cases: list[dict], retr: dict, gate: float, judge_model: str) -> dict:
    return {
        "timestamp": _now_iso(),
        "model": settings.model_name,
        "judge_model": judge_model,
        "accuracy": _accuracy(cases),
        "passed": sum(c["passed"] for c in cases),
        "total": len(cases),
        "gate": gate,
        "cases": cases,
        "retrieval": retr,
    }


def _trend(runs: list[dict]) -> list[dict]:
    """Compact per-run series for the trend chart."""
    out = []
    for r in runs:
        out.append({
            "ts": r["timestamp"][5:16],  # MM-DDTHH:MM
            "acc": r["accuracy"],
            "recall": r.get("retrieval", {}).get("recall_at_k", 0.0),
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Konecto actuator agent evaluation")
    ap.add_argument("--gate", type=float, default=0.8, help="minimum accuracy (default 0.8)")
    ap.add_argument("--no-gate", action="store_true", help="do not exit non-zero on low accuracy")
    ap.add_argument("--retrieval-only", action="store_true", help="run only retrieval metrics")
    ap.add_argument("--compare-prompts", nargs="+", metavar="GLOB",
                    help="prompt files (txt) to A/B against the default SYSTEM_PROMPT")
    args = ap.parse_args()

    import os
    judge_model = os.getenv("EVAL_JUDGE_MODEL", "openai/gpt-4o-mini")
    if not os.getenv("OPENROUTER_API_KEY"):
        print("[!] OPENROUTER_API_KEY not set — judge cases fall back to non-empty grading")

    # --- Retrieval eval (always; it's cheap and answers "is the index healthy?") ---
    print("Running retrieval eval (index health + recall@k)...")
    retr = retrieval.run_retrieval_eval()
    h = retr["index_health"]
    print(f"  index: {h['indexed_docs']}/{h['catalog_rows']} docs "
          f"({'healthy' if h['healthy'] else 'MISMATCH ' + str(h['delta'])})")
    print(f"  recall@{retr['k']}: {retr['recall_at_k']:.0%}")
    for p in retr["probes"]:
        flag = "[+]" if p["recall"] else "[-]"
        print(f"    {flag} {p['query'][:50]:<50} hits={len(p['hits'])}/{p['expected_count']}")

    if args.retrieval_only:
        sys.exit(0 if h["healthy"] else 1)

    # --- A/B prompt variants ---------------------------------------------------
    prompt_variants = {"default": SYSTEM_PROMPT}
    if args.compare_prompts:
        for pattern in args.compare_prompts:
            for path in glob.glob(pattern):
                name = Path(path).stem
                prompt_variants[name] = Path(path).read_text(encoding="utf-8")
        print(f"\nA/B comparing {len(prompt_variants)} prompt variant(s): {', '.join(prompt_variants)}")

    # --- End-to-end eval -------------------------------------------------------
    variant_runs = {}
    with SqliteSaver.from_conn_string(settings.memory_db_path) as memory:
        for vname, prompt in prompt_variants.items():
            print(f"\nRunning {len(CASES)} E2E cases [prompt: {vname}]...")
            agent = build_agent(memory, prompt=prompt)
            cases = runner.run_cases(agent, CASES)
            _print_table(cases)
            acc = _accuracy(cases)
            print(f"\n  [{vname}] accuracy: {sum(c['passed'] for c in cases)}/{len(cases)} = {acc:.0%}")
            variant_runs[vname] = cases

    # The default variant is the one we persist/report/gate on.
    cases = variant_runs["default"]
    run = _build_run(cases, retr, args.gate, judge_model)
    if len(prompt_variants) > 1:
        run["ab_variants"] = {v: _accuracy(c) for v, c in variant_runs.items()}

    # --- Persist + diff + report ----------------------------------------------
    prior = history.load_runs()
    previous = prior[-1] if prior else None
    history.save_run(run, run["timestamp"].replace(":", "-"))
    diff = history.diff_against_previous(run, previous)
    trend = _trend(history.load_runs())
    path = report.write_report(run, trend, diff)
    print(f"\nReport written: {path}")
    if diff["regressed"]:
        print(f"[!] REGRESSIONS vs previous run: {', '.join(diff['regressed'])}")
    if diff["improved"]:
        print(f"[+] Improved: {', '.join(diff['improved'])}")

    # --- Gate ------------------------------------------------------------------
    acc = run["accuracy"]
    if acc < args.gate and not args.no_gate:
        print(f"\nFAIL: accuracy {acc:.0%} below {args.gate:.0%} gate")
        sys.exit(1)
    print(f"\nPASS: accuracy {acc:.0%} meets {args.gate:.0%} gate")
    sys.exit(0)


if __name__ == "__main__":
    main()
