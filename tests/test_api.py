"""FastAPI endpoint tests using TestClient: POST /api/conversation, GET /health, GET /cache/stats."""

import pytest


def test_conversation_happy_path(client):
    """POST /api/conversation with valid query returns 200 with answer and session_id."""
    resp = client.post(
        "/api/conversation",
        json={"query": "What is the torque for 763A00-11300000/A?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "session_id" in data
    assert isinstance(data["answer"], str)
    assert len(data["answer"]) > 0
    assert isinstance(data["session_id"], str)


def test_conversation_provided_session_id_echoed(client):
    """session_id provided in request is echoed back in response."""
    resp = client.post(
        "/api/conversation",
        json={"query": "hello", "session_id": "test-session-123"},
    )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "test-session-123"


def test_health_endpoint(client):
    """GET /health returns 200 with status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_cache_stats_endpoint(client):
    """GET /cache/stats returns 200 with actuator_cache key."""
    resp = client.get("/cache/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "actuator_cache" in data
    assert "size" in data["actuator_cache"]
