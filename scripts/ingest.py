"""Idempotent data ingestion script: validates actuators.json against Pydantic schema, populates SQLite and ChromaDB."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Resolve paths relative to this file's location
SCRIPTS_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPTS_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
JSON_PATH = DATA_DIR / "actuators.json"
DB_PATH = DATA_DIR / "actuators.db"
CHROMA_PATH = DATA_DIR / "chroma"

# Add project root to sys.path so app.db.schema is importable
sys.path.insert(0, str(PROJECT_ROOT))
from app.db.schema import Actuator  # noqa: E402


CREATE_TABLE_SQL = """
CREATE TABLE actuators (
    base_part_number   TEXT NOT NULL,
    enclosure_type     TEXT NOT NULL,
    voltage            TEXT NOT NULL,
    phase              TEXT NOT NULL,
    application_type   TEXT NOT NULL,
    torque_inlbs       REAL NOT NULL,
    torque_nm          REAL NOT NULL,
    duty_cycle         REAL NOT NULL,
    cycles_per_hour    REAL NOT NULL,
    starts_per_hour    REAL NOT NULL,
    motor_power_watts  REAL NOT NULL,
    csa_certified      INTEGER NOT NULL,
    speed_60hz         REAL,
    speed_50hz         REAL,
    fla_60hz           REAL,
    fla_50hz           REAL,
    lra_60hz           REAL,
    lra_50hz           REAL
)
"""

INSERT_SQL = """
INSERT INTO actuators (
    base_part_number, enclosure_type, voltage, phase, application_type,
    torque_inlbs, torque_nm, duty_cycle, cycles_per_hour, starts_per_hour,
    motor_power_watts, csa_certified,
    speed_60hz, speed_50hz, fla_60hz, fla_50hz, lra_60hz, lra_50hz
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _actuator_to_tuple(a: Actuator) -> tuple:
    return (
        a.base_part_number, a.enclosure_type, a.voltage, a.phase, a.application_type,
        a.torque_inlbs, a.torque_nm, a.duty_cycle, a.cycles_per_hour, a.starts_per_hour,
        a.motor_power_watts, int(a.csa_certified),
        a.speed_60hz, a.speed_50hz, a.fla_60hz, a.fla_50hz, a.lra_60hz, a.lra_50hz,
    )


def _descriptive_text(a: Actuator) -> str:
    # Lead with and repeat the categorical fields (voltage/enclosure/application).
    # text-embedding-3-small under-weights short tokens like "24V" vs "220V" when
    # they're buried mid-sentence; fronting + restating them lifts categorical recall.
    text = (
        f"{a.voltage} {a.application_type} {a.enclosure_type} actuator. "
        f"Voltage: {a.voltage}. Application type: {a.application_type}. Enclosure: {a.enclosure_type}. "
        f"Actuator {a.base_part_number}: {a.enclosure_type} enclosure, "
        f"{a.voltage} {a.phase} phase, {a.application_type} application, "
        f"output torque {a.torque_inlbs} in-lbs ({a.torque_nm} Nm), "
        f"duty cycle {a.duty_cycle}%, motor power {a.motor_power_watts}W, "
        f"CSA certified: {a.csa_certified}"
    )
    extras = []
    if a.speed_60hz is not None:
        extras.append(f"60Hz speed: {a.speed_60hz} RPM")
    if a.fla_60hz is not None:
        extras.append(f"FLA: {a.fla_60hz}A")
    if a.lra_60hz is not None:
        extras.append(f"LRA: {a.lra_60hz}A")
    if extras:
        text += ", " + ", ".join(extras)
    return text


def main() -> None:
    # 1. LOAD
    with open(JSON_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    # 2. VALIDATE
    actuators: list[Actuator] = []
    errors = []
    for i, record in enumerate(raw):
        try:
            actuators.append(Actuator.model_validate(record))
        except Exception as exc:
            errors.append(f"Record {i}: {exc}")
    if errors:
        for e in errors:
            print(f"Validation error — {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Validated {len(actuators)} records")

    # 3. SQLITE SETUP (idempotent via DROP + recreate)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("DROP TABLE IF EXISTS actuators")
    conn.execute(CREATE_TABLE_SQL)
    conn.execute("CREATE INDEX idx_actuators_torque ON actuators(torque_nm)")
    conn.execute("CREATE INDEX idx_actuators_enclosure ON actuators(enclosure_type)")
    conn.execute("CREATE INDEX idx_actuators_voltage ON actuators(voltage)")
    conn.executemany(INSERT_SQL, [_actuator_to_tuple(a) for a in actuators])
    conn.commit()
    conn.close()
    print(f"Inserted {len(actuators)} rows into SQLite ({DB_PATH})")

    # 4. CHROMADB SETUP (idempotent via delete + get_or_create)
    import chromadb
    from chromadb import Settings
    from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    CHROMA_PATH.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(CHROMA_PATH),
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        client.delete_collection("actuators")
    except Exception:
        pass  # ponytail: collection may not exist on first run
    collection = client.get_or_create_collection(
        "actuators",
        embedding_function=OpenAIEmbeddingFunction(
            api_key=api_key,
            model_name="text-embedding-3-small",
        ),
    )
    documents = [_descriptive_text(a) for a in actuators]
    ids = [f"{a.base_part_number}::{a.application_type}" for a in actuators]
    metadatas = [
        {
            "base_part_number": a.base_part_number,
            "enclosure_type": a.enclosure_type,
            "voltage": a.voltage,
            "torque_nm": a.torque_nm,
        }
        for a in actuators
    ]
    collection.add(documents=documents, ids=ids, metadatas=metadatas)
    print(f"Embedded {len(actuators)} documents into ChromaDB ({CHROMA_PATH})")

    # 5. SUMMARY
    print(f"Ingested {len(actuators)} actuators into SQLite and ChromaDB")


if __name__ == "__main__":
    main()
