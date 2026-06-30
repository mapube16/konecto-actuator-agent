"""SQLite connection manager: read-only connection for tools, read-write connection for SqliteSaver checkpointer."""

import sqlite3


def get_sqlite_conn(db_path: str) -> sqlite3.Connection:
    """Open a read-only SQLite connection with busy_timeout=5000.

    Caller is responsible for closing (use as context manager in tools).
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_all_part_numbers(conn: sqlite3.Connection) -> list[str]:
    """Return all base_part_number values from actuators table.

    Used by rapidfuzz fallback in Tool 1.
    """
    # DISTINCT: a PN has one row per application_type variant; the fuzzy fallback
    # must suggest unique part numbers, not the same PN twice.
    cursor = conn.execute("SELECT DISTINCT base_part_number FROM actuators")
    return [row[0] for row in cursor.fetchall()]
