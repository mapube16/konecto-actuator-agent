"""Unit tests for get_actuator_by_part_number and recommend_actuators tools (exact match, fuzzy match, filters)."""

from unittest.mock import MagicMock

import pytest

from app.tools.get_actuator import get_actuator_by_part_number
from app.tools.recommend import RecommendationFilters, recommend_actuators


# ---------------------------------------------------------------------------
# get_actuator_by_part_number
# ---------------------------------------------------------------------------

def test_get_actuator_exact_match(sqlite_db):
    """Exact PN in test DB returns formatted specs containing the PN."""
    result = get_actuator_by_part_number.invoke({"part_number": "763A00-11300000/A"})
    assert "763A00-11300000/A" in result
    assert "NEMA4" in result


def test_get_actuator_fuzzy_did_you_mean(sqlite_db):
    """Near-miss PN with score >= 70 returns 'Did you mean' suggestion."""
    # '763A00-11300000/B' is close enough (differs only at last char) to trigger fuzzy
    result = get_actuator_by_part_number.invoke({"part_number": "763A00-11300000/B"})
    assert "Did you mean" in result
    assert "763A00-11300000/A" in result


def test_get_actuator_not_found(sqlite_db):
    """Completely unknown PN returns 'not found' message."""
    result = get_actuator_by_part_number.invoke({"part_number": "XXXXXX-99999999/Z"})
    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# recommend_actuators
# ---------------------------------------------------------------------------

def test_recommend_no_match(sqlite_db, mock_chroma, monkeypatch):
    """Filters that match no rows return 'No actuators match' string."""
    # Impossible torque (a free float field) → no SQL rows. voltage is now a closed
    # Literal, so an out-of-range value would be a schema violation, not a no-match.
    impossible_filters = RecommendationFilters(torque_nm_min=999999.0)
    monkeypatch.setattr("app.tools.recommend._extract_filters", lambda req: impossible_filters)

    result = recommend_actuators.invoke({"requirements": "something impossible"})
    assert "No actuators match" in result


def test_recommend_with_results(sqlite_db, mock_chroma, monkeypatch):
    """Filters matching rows + mock Chroma returns 'Top N actuator recommendations'."""
    # Empty filters → all rows qualify
    empty_filters = RecommendationFilters()
    monkeypatch.setattr("app.tools.recommend._extract_filters", lambda req: empty_filters)

    result = recommend_actuators.invoke({"requirements": "any actuator"})
    assert "Top" in result
    assert "763A00-11300000/A" in result
