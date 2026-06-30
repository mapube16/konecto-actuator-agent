"""Run history: persist each eval run to disk and diff against the previous one.

This is what turns a pass/fail gate into regression detection. Each run writes
eval_runs/<timestamp>.json. Comparing the current run to the last one tells you
which cases improved or regressed when you changed SYSTEM_PROMPT or the data.
"""

from __future__ import annotations

import json
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parents[2] / "eval_runs"


def save_run(run: dict, timestamp: str) -> Path:
    """Persist a run under eval_runs/<timestamp>.json. Caller supplies the timestamp
    (scripts can't call datetime.now in some sandboxes; keep this pure)."""
    RUNS_DIR.mkdir(exist_ok=True)
    path = RUNS_DIR / f"{timestamp}.json"
    path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    return path


def load_runs() -> list[dict]:
    """All saved runs, oldest first (filenames sort chronologically by ISO timestamp)."""
    if not RUNS_DIR.exists():
        return []
    out = []
    for p in sorted(RUNS_DIR.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue  # skip a corrupt/half-written run rather than crash the report
    return out


def diff_against_previous(current: dict, previous: dict | None) -> dict:
    """Per-case delta between two runs. Returns improved/regressed/unchanged buckets."""
    if previous is None:
        return {"improved": [], "regressed": [], "unchanged": [], "new": [c["name"] for c in current["cases"]]}

    prev_by_name = {c["name"]: c["passed"] for c in previous["cases"]}
    improved, regressed, unchanged, new = [], [], [], []
    for c in current["cases"]:
        name, now = c["name"], c["passed"]
        if name not in prev_by_name:
            new.append(name)
        elif now and not prev_by_name[name]:
            improved.append(name)
        elif not now and prev_by_name[name]:
            regressed.append(name)
        else:
            unchanged.append(name)
    return {"improved": improved, "regressed": regressed, "unchanged": unchanged, "new": new}


if __name__ == "__main__":
    # Self-check: save/load round-trips and diff classifies correctly.
    prev = {"cases": [{"name": "a", "passed": True}, {"name": "b", "passed": False}]}
    curr = {"cases": [{"name": "a", "passed": False}, {"name": "b", "passed": True}, {"name": "c", "passed": True}]}
    d = diff_against_previous(curr, prev)
    assert d["regressed"] == ["a"], f"expected a regressed, got {d}"
    assert d["improved"] == ["b"], f"expected b improved, got {d}"
    assert d["new"] == ["c"], f"expected c new, got {d}"
    assert diff_against_previous(curr, None)["new"] == ["a", "b", "c"], "first run = all new"
    print("OK — history diff classifies improved/regressed/new correctly")
