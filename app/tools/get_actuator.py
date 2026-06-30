"""LangChain Tool 1: get_actuator_by_part_number — exact SQLite lookup with rapidfuzz fuzzy-match fallback."""

import contextlib
import sqlite3

from langchain_core.tools import tool
from rapidfuzz import fuzz, process

from app.cache import actuator_cache
from app.config import settings
from app.db.sqlite import get_all_part_numbers, get_sqlite_conn


def _format_actuator(row: sqlite3.Row) -> str:
    def v(val):
        return val if val is not None else "N/A"

    return (
        f"Part Number: {v(row['base_part_number'])}\n"
        f"Enclosure: {v(row['enclosure_type'])} | Voltage: {v(row['voltage'])} | Phase: {v(row['phase'])}\n"
        f"Application: {v(row['application_type'])}\n"
        f"Torque: {v(row['torque_inlbs'])} in-lbs ({v(row['torque_nm'])} Nm)\n"
        f"Duty Cycle: {v(row['duty_cycle'])}% | Cycles/hr: {v(row['cycles_per_hour'])} | Starts/hr: {v(row['starts_per_hour'])}\n"
        f"Speed (60Hz/50Hz): {v(row['speed_60hz'])}s / {v(row['speed_50hz'])}s\n"
        f"FLA (60Hz/50Hz): {v(row['fla_60hz'])}A / {v(row['fla_50hz'])}A\n"
        f"LRA (60Hz/50Hz): {v(row['lra_60hz'])}A / {v(row['lra_50hz'])}A\n"
        f"Motor Power: {v(row['motor_power_watts'])}W | CSA Certified: {'Yes' if row['csa_certified'] else 'No'}"
    )


@tool(parse_docstring=True)
def get_actuator_by_part_number(part_number: str) -> str:
    """Get exact technical specifications for a Series 76 actuator by its Base Part Number.

    Args:
        part_number: The Base Part Number to look up (e.g., '763A00-11300000/A').
    """
    if part_number in actuator_cache:
        return actuator_cache[part_number]

    with contextlib.closing(get_sqlite_conn(settings.db_path)) as conn:
        row = conn.execute(
            "SELECT * FROM actuators WHERE base_part_number = ?", (part_number,)
        ).fetchone()

        if row is not None:
            result = _format_actuator(row)
            actuator_cache[part_number] = result
            return result

        all_pns = get_all_part_numbers(conn)

    matches = process.extract(part_number, all_pns, scorer=fuzz.ratio, limit=3, score_cutoff=70)
    if matches:
        suggestions = ", ".join(m[0] for m in matches)
        return f"No exact match for '{part_number}'. Did you mean: {suggestions}?"

    return f"Part number '{part_number}' not found in the Series 76 catalog."
