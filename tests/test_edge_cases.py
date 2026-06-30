"""Edge case tests: empty query, query too long, invalid session_id, out-of-domain query."""

import pytest


def test_empty_query_returns_422(client):
    """Empty query string violates min_length=1 — Pydantic should return 422."""
    resp = client.post("/api/conversation", json={"query": ""})
    assert resp.status_code == 422


def test_query_too_long_returns_422(client):
    """Query longer than 2000 chars violates max_length=2000 — Pydantic should return 422."""
    resp = client.post("/api/conversation", json={"query": "x" * 2001})
    assert resp.status_code == 422


def test_invalid_session_id_returns_422(client):
    """session_id with illegal chars (spaces, exclamation) violates the regex pattern — 422."""
    resp = client.post(
        "/api/conversation",
        json={"query": "hello", "session_id": "bad id!"},
    )
    assert resp.status_code == 422


def test_out_of_domain_query_returns_200(client):
    """An out-of-domain question routed through the stub agent still returns 200 with an answer."""
    resp = client.post(
        "/api/conversation",
        json={"query": "What is the capital of France?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert len(data["answer"]) > 0
