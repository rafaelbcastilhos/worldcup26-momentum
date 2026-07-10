"""Unit tests for stoppage detection (offline, uses synthetic fixture)."""

from src.parse.stoppages import (
    _cluster,
    _cluster_hydration,
    _red_cards_before,
    _score_at,
    _subs_in_window,
    detect_stoppages,
)


def test_cluster_basic():
    assert _cluster([1.0, 2.0, 5.0, 6.0], 2.0) == [[1.0, 2.0], [5.0, 6.0]]


def test_cluster_single():
    assert _cluster([22.0], 3.0) == [[22.0]]


def test_cluster_hydration_filters_nominal(match_inputs):
    _, _, _, commentary = match_inputs
    minutes = _cluster_hydration(commentary)
    # Synthetic match has hydration at 22 and 67 — both near nominal
    assert len(minutes) == 2
    assert any(abs(m - 22) <= 3 for m in minutes)
    assert any(abs(m - 67) <= 3 for m in minutes)


def test_detect_stoppages_types(match_inputs):
    meta, momentum, incidents, commentary = match_inputs
    stoppages = detect_stoppages(meta, incidents, commentary)
    types = {s["stoppage_type"] for s in stoppages}
    assert "hydration" in types
    assert "var" in types


def test_detect_stoppages_order(match_inputs):
    meta, momentum, incidents, commentary = match_inputs
    stoppages = detect_stoppages(meta, incidents, commentary)
    minutes = [s["clock_minute"] for s in stoppages]
    assert minutes == sorted(minutes)


def test_detect_stoppages_ids_unique(match_inputs):
    meta, momentum, incidents, commentary = match_inputs
    stoppages = detect_stoppages(meta, incidents, commentary)
    ids = [s["stoppage_id"] for s in stoppages]
    assert len(ids) == len(set(ids))


def test_score_at():
    incidents = [
        {"kind": "goal", "is_home": True, "minute": 10.0, "home_score": 1, "away_score": 0},
        {"kind": "goal", "is_home": False, "minute": 30.0, "home_score": 1, "away_score": 1},
    ]
    assert _score_at(incidents, 5.0) == (0, 0)
    assert _score_at(incidents, 15.0) == (1, 0)
    assert _score_at(incidents, 35.0) == (1, 1)


def test_red_cards_before():
    incidents = [
        {"kind": "card", "is_home": True, "minute": 50.0, "detail": "red"},
        {"kind": "card", "is_home": False, "minute": 70.0, "detail": "yellowred"},
    ]
    reds = _red_cards_before(incidents, 60.0)
    assert reds["home"] == 1
    assert reds["away"] == 0
    reds2 = _red_cards_before(incidents, 80.0)
    assert reds2["away"] == 1


def test_subs_in_window():
    incidents = [
        {"kind": "substitution", "is_home": True, "minute": 67.0},
    ]
    subs = _subs_in_window(incidents, 66.5)
    assert subs["home"] == 1
    subs2 = _subs_in_window(incidents, 60.0)
    assert subs2["home"] == 0
