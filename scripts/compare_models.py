"""Compare chat models (gpt-5-mini / gpt-5.1 / gpt-5.2) on the same eval set.

Runs the E2E case suite N times per model against the REAL LLM, records accuracy per run,
and renders the narrative:
  - docs/model_run_<model>.png   one progression chart per model (accuracy across its runs)
  - docs/model_comparison.png    grouped bars: mean accuracy + retrieval recall per model
  - docs/MODEL_COMPARISON.md     table + takeaways
  - docs/model_comparison.json   raw results (committed as evidence)

Retrieval recall depends only on the embedding model (unchanged across chat models), so it's
measured once and shown as a constant reference.

Usage:
    python scripts/compare_models.py                 # default: 3 runs each, all three models
    python scripts/compare_models.py --runs 1         # cheaper smoke
    python scripts/compare_models.py --models gpt-5-mini gpt-5.1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402

from app.config import settings  # noqa: E402
from app.eval import retrieval, runner  # noqa: E402
from app.eval.cases import CASES  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
DOCS = _ROOT / "docs"
# Lives in docs/, not eval_runs/: this is a model-comparison artifact, not a progression
# run. Keeping it out of eval_runs/ keeps that dir's *.json glob (history/plot_progress)
# to uniform run records — a differently-shaped file there would KeyError the diff.
RUNS_OUT = DOCS / "model_comparison.json"

DEFAULT_MODELS = ["gpt-5-mini", "gpt-5.1", "gpt-5.2"]


def _accuracy(cases: list[dict]) -> float:
    return sum(c["passed"] for c in cases) / len(cases) if cases else 0.0


def _run_model(model: str, n_runs: int) -> list[float]:
    """Run the E2E suite n_runs times for one chat model; return accuracy per run."""
    # settings is a singleton; override the chat model in-process for this batch.
    settings.model_name = model
    from app.agent import build_agent  # imported here so it picks up the current settings

    accs = []
    with SqliteSaver.from_conn_string(settings.memory_db_path) as memory:
        for i in range(1, n_runs + 1):
            agent = build_agent(memory)
            cases = runner.run_cases(agent, CASES)
            acc = _accuracy(cases)
            accs.append(acc)
            passed = sum(c["passed"] for c in cases)
            print(f"  [{model}] run {i}/{n_runs}: {passed}/{len(cases)} = {acc:.0%}")
    return accs


def _plot_per_model(model: str, accs: list[float], recall: float) -> Path:
    x = list(range(1, len(accs) + 1))
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(x, [a * 100 for a in accs], marker="o", linewidth=2, color="#2563eb", label="E2E accuracy")
    ax.axhline(recall * 100, color="#16a34a", linestyle="--", linewidth=1.2, label=f"Retrieval recall@5 ({recall:.0%})")
    ax.axhline(80, color="#dc2626", linestyle=":", linewidth=1, label="80% gate")
    for xi, a in zip(x, accs):
        ax.annotate(f"{a*100:.0f}%", (xi, a * 100), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)
    ax.set_title(f"Eval runs — {model}")
    ax.set_xlabel("Run")
    ax.set_ylabel("Score (%)")
    ax.set_ylim(0, 105)
    ax.set_xticks(x)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    out = DOCS / f"model_run_{model.replace('.', '-')}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def _plot_comparison(results: dict, recall: float) -> Path:
    models = list(results)
    means = [sum(results[m]) / len(results[m]) * 100 for m in models]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    xpos = range(len(models))
    bars = ax.bar([p - 0.2 for p in xpos], means, width=0.4, color="#2563eb", label="Mean E2E accuracy")
    ax.bar([p + 0.2 for p in xpos], [recall * 100] * len(models), width=0.4, color="#16a34a", label="Retrieval recall@5")
    ax.axhline(80, color="#dc2626", linestyle=":", linewidth=1, label="80% gate")
    for b, m in zip(bars, means):
        ax.annotate(f"{m:.0f}%", (b.get_x() + b.get_width() / 2, m), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=9, fontweight="bold")
    ax.set_title("Model comparison — Konecto Actuator Agent")
    ax.set_ylabel("Score (%)")
    ax.set_ylim(0, 105)
    ax.set_xticks(list(xpos))
    ax.set_xticklabels(models)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    out = DOCS / "model_comparison.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def _write_doc(results: dict, recall: float, per_model_pngs: dict) -> Path:
    lines = [
        "# Model comparison",
        "",
        "Each chat model ran the **same** end-to-end eval suite against the **real** LLM "
        f"({len(next(iter(results.values())))} runs per model). Retrieval recall@5 is "
        f"`{recall:.0%}` for all models (it depends on the embedding model, which is unchanged).",
        "",
        "| Model | Runs | Mean accuracy | Min | Max |",
        "|-------|------|---------------|-----|-----|",
    ]
    for m, accs in results.items():
        mean = sum(accs) / len(accs)
        lines.append(f"| `{m}` | {len(accs)} | **{mean:.0%}** | {min(accs):.0%} | {max(accs):.0%} |")
    best = max(results, key=lambda m: sum(results[m]) / len(results[m]))
    lines += [
        "",
        f"**Winner: `{best}`** (highest mean accuracy). `gpt-5-mini` is kept as the dev/test "
        "default (budget-friendly, per the assessment), and the comparison justifies the "
        "production choice with data rather than intuition.",
        "",
        "## Per-model progression",
        "",
    ]
    for m, png in per_model_pngs.items():
        lines.append(f"### `{m}`")
        lines.append(f"![{m}]({png.name})")
        lines.append("")
    lines += ["## Side by side", "", "![comparison](model_comparison.png)", ""]
    out = DOCS / "MODEL_COMPARISON.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3, help="runs per model (default 3)")
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = ap.parse_args()

    DOCS.mkdir(exist_ok=True)
    print(f"Measuring retrieval recall@5 (once; embedding-model dependent)...")
    retr = retrieval.run_retrieval_eval(k=5)
    recall = retr["recall_at_k"]
    print(f"  recall@5 = {recall:.0%}")

    results: dict[str, list[float]] = {}
    for model in args.models:
        print(f"\n=== {model} ({args.runs} run(s)) ===")
        results[model] = _run_model(model, args.runs)

    RUNS_OUT.parent.mkdir(exist_ok=True)
    RUNS_OUT.write_text(json.dumps({"recall_at_k": recall, "accuracy_by_model": results}, indent=2), encoding="utf-8")
    print(f"\nRaw results: {RUNS_OUT}")

    per_model_pngs = {m: _plot_per_model(m, accs, recall) for m, accs in results.items()}
    comp = _plot_comparison(results, recall)
    doc = _write_doc(results, recall, per_model_pngs)
    print(f"Charts: {', '.join(p.name for p in per_model_pngs.values())}, {comp.name}")
    print(f"Doc: {doc}")


if __name__ == "__main__":
    main()
