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


def test_recommend_ranks_by_variant(sqlite_db, mock_chroma, monkeypatch):
    """Chroma ranks by (PN, application_type): the specific variant it matched is the one
    whose specs are shown — not an arbitrary row for that PN.

    The fixture has 763A00-11300000/A twice (on/off @ some torque + modulating @ another).
    Chroma's metadata says it matched the on/off variant, so the on/off row's specs appear,
    and exactly once (the modulating row is a different candidate Chroma didn't return here).
    """
    empty_filters = RecommendationFilters()
    monkeypatch.setattr("app.tools.recommend._extract_filters", lambda req: empty_filters)

    result = recommend_actuators.invoke({"requirements": "any actuator"})
    assert result.count("763A00-11300000/A") == 1, f"variant listed more than once:\n{result}"
    assert "on/off" in result, f"the matched on/off variant should be shown:\n{result}"
    assert "Top 1 actuator" in result, f"one ranked variant expected:\n{result}"


def test_recommend_both_variants_keep_own_specs(sqlite_db, mock_chroma, monkeypatch):
    """When Chroma ranks both variants of a PN, each keeps ITS OWN torque — the bug was
    collapsing to one arbitrary variant's specs. Here Chroma returns on/off then modulating
    for the same PN; both must appear, each with the torque of its own row."""
    empty_filters = RecommendationFilters()
    monkeypatch.setattr("app.tools.recommend._extract_filters", lambda req: empty_filters)
    mock_chroma.query.return_value = {
        "metadatas": [[
            {"base_part_number": "763A00-11300000/A", "application_type": "on/off"},
            {"base_part_number": "763A00-11300000/A", "application_type": "modulating"},
        ]]
    }
    result = recommend_actuators.invoke({"requirements": "any actuator"})
    assert "on/off" in result and "modulating" in result, f"both variants expected:\n{result}"
    assert "Top 2 actuator" in result, f"two distinct variants expected:\n{result}"


def test_recommend_respects_application_type_filter(sqlite_db, mock_chroma, monkeypatch):
    """When on/off is requested, the modulating variant of the same PN must not leak in."""
    onoff = RecommendationFilters(application_type="on/off")
    monkeypatch.setattr("app.tools.recommend._extract_filters", lambda req: onoff)

    result = recommend_actuators.invoke({"requirements": "on/off actuator"})
    assert "on/off" in result
    # The modulating row (torque 13.6 Nm) for the same PN must not appear.
    assert "13.6" not in result, f"modulating variant leaked into on/off results:\n{result}"


def test_fuzzy_suggestions_are_unique(sqlite_db):
    """Fuzzy 'Did you mean' must not repeat a PN that has multiple variant rows.

    Regression: get_all_part_numbers lacked DISTINCT, so a duplicated PN could fill the
    limit=3 slots with the same suggestion.
    """
    result = get_actuator_by_part_number.invoke({"part_number": "763A00-11300000/B"})
    assert "Did you mean" in result
    assert result.count("763A00-11300000/A") == 1, f"duplicate suggestion:\n{result}"
