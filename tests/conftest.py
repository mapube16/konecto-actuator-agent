"""Pytest fixtures: in-memory SQLite with test actuators, mock ChromaDB collection, and FastAPI TestClient."""

import os
import sqlite3
from unittest.mock import AsyncMock, MagicMock

# Must be set before any app import triggers pydantic Settings instantiation
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

import app.db.chroma as chroma_module  # noqa: E402


COLUMNS = [
    "base_part_number", "enclosure_type", "voltage", "phase", "application_type",
    "torque_inlbs", "torque_nm", "duty_cycle", "cycles_per_hour", "starts_per_hour",
    "speed_60hz", "speed_50hz", "fla_60hz", "fla_50hz", "lra_60hz", "lra_50hz",
    "motor_power_watts", "csa_certified",
]

TEST_ROWS = [
    ("763A00-11300000/A", "NEMA4", "115/1/60", "single", "quarter-turn",
     130, 14.7, 25, 60, 150, 12, 14, 1.2, 1.0, 6.0, 5.0, 85, 1),
    ("763B00-21300000/A", "explosion-proof", "230/1/60", "single", "throttling",
     265, 29.9, 100, 30, 100, 15, 18, 2.1, 1.8, 10.0, 8.5, 150, 0),
]


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    """Create a temp SQLite file with test actuator rows, monkeypatch settings.db_path."""
    db_file = tmp_path / "test_actuators.db"
    db_path = str(db_file)

    # Write rows with a normal (rw) connection first
    conn = sqlite3.connect(db_path)
    cols = ", ".join(COLUMNS)
    placeholders = ", ".join("?" * len(COLUMNS))
    conn.execute(f"CREATE TABLE actuators ({cols})")
    conn.executemany(f"INSERT INTO actuators ({cols}) VALUES ({placeholders})", TEST_ROWS)
    conn.commit()
    conn.close()

    # Point the tools at the test DB via settings
    from app import config as config_module
    monkeypatch.setattr(config_module.settings, "db_path", db_path)

    return db_path


@pytest.fixture
def mock_chroma():
    """Stub _chroma_collection so recommend_actuators skips OpenAI embedding calls."""
    stub = MagicMock()
    stub.query.return_value = {
        "metadatas": [[{"base_part_number": "763A00-11300000/A"}]]
    }
    chroma_module._chroma_collection = stub
    yield stub
    # Teardown: reset singleton so other tests don't inherit the stub
    chroma_module._chroma_collection = None


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient with a stub agent (no real LLM calls).

    Patches build_agent and the AsyncSqliteSaver checkpointer so the app lifespan
    succeeds without touching OpenAI, ChromaDB, or a real SQLite checkpointer.
    """
    stub_agent = MagicMock()
    stub_agent.ainvoke = AsyncMock(
        return_value={"messages": [AIMessage(content="Stub answer from test agent")]}
    )

    # main.py opens `async with AsyncSqliteSaver.from_conn_string(...)` in its
    # lifespan — stub from_conn_string to return an async-context-manager yielding a mock.
    saver_cm = MagicMock()
    saver_cm.__aenter__ = AsyncMock(return_value=MagicMock())
    saver_cm.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("app.main.build_agent", lambda memory: stub_agent)
    monkeypatch.setattr(
        "app.main.AsyncSqliteSaver.from_conn_string", lambda path: saver_cm
    )

    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
