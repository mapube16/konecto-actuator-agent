"""Derive golden answers from the live catalog so eval truth auto-updates with the data.

The verifiable graders (exact-PN, spec-lookup, NL-filter) need a source of truth.
Reading it from SQLite at runtime means a re-ingest of new data never silently
invalidates the eval — the expected answer is recomputed, not hardcoded.
"""

from __future__ import annotations

import sqlite3

from app.config import settings
from app.db.sqlite import get_sqlite_conn


def _rows() -> list[sqlite3.Row]:
    with get_sqlite_conn(settings.db_path) as conn:
        return conn.execute("SELECT * FROM actuators").fetchall()


def all_part_numbers() -> set[str]:
    return {r["base_part_number"] for r in _rows()}


def spec_for(part_number: str) -> dict | None:
    """Return the first row's specs for a PN, or None if absent."""
    for r in _rows():
        if r["base_part_number"] == part_number:
            return dict(r)
    return None


def pns_matching(
    *,
    torque_nm_min: float | None = None,
    voltage: str | None = None,
    enclosure_type: str | None = None,
    application_type: str | None = None,
) -> set[str]:
    """Compute the set of PNs that satisfy hard filters — the ground truth a
    correct recommendation must draw from. Mirrors recommend_actuators' SQL filter.
    """
    return {r["base_part_number"] for r in rows_matching(
        torque_nm_min=torque_nm_min, voltage=voltage,
        enclosure_type=enclosure_type, application_type=application_type,
    )}


def rows_matching(
    *,
    torque_nm_min: float | None = None,
    voltage: str | None = None,
    enclosure_type: str | None = None,
    application_type: str | None = None,
) -> list[dict]:
    """Full rows (PN, torque, application_type, ...) that satisfy the hard filters — the
    variant-level ground truth. A grader can check not just that a PN is valid, but that
    the specific torque shown belongs to a real row that passes the filter.
    """
    out = []
    for r in _rows():
        if torque_nm_min is not None and r["torque_nm"] < torque_nm_min:
            continue
        if voltage is not None and r["voltage"] != voltage:
            continue
        if enclosure_type is not None and r["enclosure_type"] != enclosure_type:
            continue
        if application_type is not None and r["application_type"] not in (
            application_type,
            "on/off and modulating",
        ):
            continue
        out.append(dict(r))
    return out


if __name__ == "__main__":
    # Self-check: catalog accessors return sane shapes against the real DB.
    pns = all_part_numbers()
    assert len(pns) > 0, "catalog has no part numbers"
    sample = next(iter(pns))
    assert spec_for(sample) is not None, "spec_for failed on a known PN"
    assert spec_for("DEFINITELY-NOT-A-PN") is None, "spec_for should return None for unknown PN"
    high_torque = pns_matching(torque_nm_min=500.0)
    assert high_torque <= pns, "filtered set must be a subset of all PNs"
    print(f"OK — {len(pns)} PNs, {len(high_torque)} match torque>=500Nm")
