"""Plot the accuracy progression across eval runs into docs/accuracy_progression.png.

Reads the run history written by scripts/eval.py (eval_runs/*.json) and renders a line
chart of end-to-end accuracy + retrieval recall per run. This is the visual record of
how the agent's accuracy was improved over the iteration (see docs/ITERATION.md).

Usage:
    python scripts/plot_progress.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: write a file, never open a window
import matplotlib.pyplot as plt

_PKG_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = _PKG_ROOT / "eval_runs"
OUT_PATH = _PKG_ROOT / "docs" / "accuracy_progression.png"


def _load_runs() -> list[dict]:
    if not RUNS_DIR.exists():
        return []
    runs = []
    for p in sorted(RUNS_DIR.glob("*.json")):
        try:
            runs.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return runs


def main() -> None:
    runs = _load_runs()
    if not runs:
        sys.exit("No eval runs found in eval_runs/ — run `python scripts/eval.py` first.")

    x = list(range(1, len(runs) + 1))
    acc = [r["accuracy"] * 100 for r in runs]
    recall = [r.get("retrieval", {}).get("recall_at_k", 0) * 100 for r in runs]

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(x, acc, marker="o", linewidth=2, color="#2563eb", label="E2E accuracy")
    ax.plot(x, recall, marker="s", linewidth=1.5, color="#16a34a", linestyle="--", label="Retrieval recall@5")

    # 80% gate line
    ax.axhline(80, color="#dc2626", linestyle=":", linewidth=1, label="80% gate")

    # Annotate each accuracy point with its value
    for xi, yi in zip(x, acc):
        ax.annotate(f"{yi:.0f}%", (xi, yi), textcoords="offset points", xytext=(0, 8),
                    ha="center", fontsize=8, color="#1e3a8a")

    ax.set_xlabel("Eval run (chronological)")
    ax.set_ylabel("Score (%)")
    ax.set_title("Konecto Actuator Agent — accuracy improvement across eval runs")
    ax.set_ylim(0, 105)
    ax.set_xticks(x)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()

    OUT_PATH.parent.mkdir(exist_ok=True)
    fig.savefig(OUT_PATH, dpi=120)
    print(f"Wrote {OUT_PATH} ({len(runs)} runs, accuracy {acc[0]:.0f}% -> {acc[-1]:.0f}%)")


if __name__ == "__main__":
    main()
