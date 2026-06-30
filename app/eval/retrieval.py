"""Retrieval-only evaluation: is the ChromaDB index healthy, independent of the LLM?

The agent's recommend tool does SQL hard-filter -> ChromaDB semantic re-rank. If an
end-to-end case fails, you can't tell whether retrieval brought the wrong actuator or
the LLM ignored a good one. This module measures retrieval alone:

- index_health: doc count vs catalog row count (did ingest drop anything?)
- recall@k: for a query whose ideal PN is known, is it in ChromaDB's top-k?

These are deterministic and need no LLM — they prove the index, not the prose.
"""

from __future__ import annotations

from app.config import settings
from app.db.chroma import get_chroma_collection
from app.eval import catalog


def index_health() -> dict:
    """Compare indexed doc count against catalog rows. 1:1 means no ingest loss."""
    from app.db.sqlite import get_sqlite_conn

    collection = get_chroma_collection(settings)
    indexed = collection.count()
    # catalog rows = one ChromaDB doc per (PN, application) — count rows, not distinct PNs
    with get_sqlite_conn(settings.db_path) as conn:
        rows = conn.execute("SELECT COUNT(*) AS c FROM actuators").fetchone()["c"]
    return {
        "indexed_docs": indexed,
        "catalog_rows": rows,
        "healthy": indexed == rows,
        "delta": indexed - rows,
    }


def recall_at_k(query: str, expected_pns: set[str], k: int = 5) -> dict:
    """Proportional recall@k: of the valid PNs that COULD appear in the top-k, how
    many did? Reported alongside precision@k so a large valid set can't inflate it.

    expected_pns is the catalog-derived valid set. The reachable ceiling is
    min(k, |valid|) — you can't surface 31 valid PNs in a top-5. recall@k is
    hits / reachable, so a query whose whole valid set fits in k is held to 100%,
    and a query with 31 valid PNs isn't trivially scored 100% for a single hit.
    precision@k (hits / k) shows how much of the top-k was on-target.
    """
    collection = get_chroma_collection(settings)
    n = min(k, collection.count())
    res = collection.query(query_texts=[query], n_results=n)
    got = [m["base_part_number"] for m in res["metadatas"][0]]
    hits = [pn for pn in got if pn in expected_pns]
    reachable = min(n, len(expected_pns)) or 1  # ceiling of valid PNs that fit in top-k
    return {
        "query": query,
        "k": n,
        "returned": got,
        "hits": hits,
        "recall": len(hits) / reachable,          # proportional, not binary
        "precision": len(hits) / n if n else 0.0,
        "hit_at_1": bool(hits) and got[0] in expected_pns,
        "expected_count": len(expected_pns),
        "reachable": reachable,
    }


# Retrieval probes: (query, kind, catalog filter that defines the valid set).
# kind segments the aggregate recall so it's interpretable:
#   fuzzy       — free-form semantic intent ("hazardous location"); embedding's core job
#   numeric     — a hard number ("<100 Nm"); embeddings are weak on exact numbers
#   categorical — a small closed-value set ("24V modulating"); narrowest valid set
RETRIEVAL_PROBES = [
    ("explosionproof actuator for hazardous location", "fuzzy", {"enclosure_type": "explosionproof"}),
    ("high torque actuator at least 500 Nm", "numeric", {"torque_nm_min": 500.0}),
    ("24V modulating actuator", "categorical", {"voltage": "24V", "application_type": "modulating"}),
    ("weatherproof 220V actuator", "categorical", {"enclosure_type": "weatherproof", "voltage": "220V"}),
    ("low torque on/off actuator under 100 Nm", "numeric", {"application_type": "on/off"}),
]


def run_retrieval_eval(k: int = 5) -> dict:
    """Run all retrieval probes + index health. Returns a structured result.

    recall_by_kind segments the aggregate so an 80% number can't hide which query
    type fails — the production interpretation depends entirely on the segment.
    """
    health = index_health()
    probes = []
    for query, kind, filt in RETRIEVAL_PROBES:
        expected = catalog.pns_matching(**filt)
        p = recall_at_k(query, expected, k=k)
        p["kind"] = kind
        probes.append(p)
    recall_avg = sum(p["recall"] for p in probes) / len(probes) if probes else 0.0
    precision_avg = sum(p["precision"] for p in probes) / len(probes) if probes else 0.0

    by_kind: dict[str, list[float]] = {}
    for p in probes:
        by_kind.setdefault(p["kind"], []).append(p["recall"])
    recall_by_kind = {k2: sum(v) / len(v) for k2, v in by_kind.items()}

    return {
        "index_health": health,
        "probes": probes,
        "recall_at_k": recall_avg,
        "precision_at_k": precision_avg,
        "recall_by_kind": recall_by_kind,
        "k": k,
    }


if __name__ == "__main__":
    # Self-check: index is healthy and retrieval returns structured results.
    result = run_retrieval_eval()
    h = result["index_health"]
    assert h["indexed_docs"] > 0, "index is empty — run scripts/ingest.py"
    assert h["healthy"], f"index/catalog mismatch: {h['delta']} delta"
    assert 0.0 <= result["recall_at_k"] <= 1.0, "recall must be a fraction"
    assert 0.0 <= result["precision_at_k"] <= 1.0, "precision must be a fraction"
    assert result["recall_by_kind"], "recall must be segmented by kind"
    for p in result["probes"]:
        assert p["recall"] <= 1.0 and p["precision"] <= 1.0, "per-probe metrics must be fractions"
    seg = " ".join(f"{k}={v:.0%}" for k, v in result["recall_by_kind"].items())
    print(
        f"OK — index {h['indexed_docs']} docs (healthy={h['healthy']}), "
        f"recall@{result['k']}={result['recall_at_k']:.0%} "
        f"precision@{result['k']}={result['precision_at_k']:.0%} [{seg}]"
    )
