"""Unit tests for momentum windowing (offline)."""

import pytest

from src.features.momentum_features import expand_stoppage_rows, window_stats


def _series(start: int, end: int, value: float = 10.0) -> list[dict]:
    return [{"minute": float(m), "value": value} for m in range(start, end + 1)]


def test_window_stats_basic():
    series = _series(15, 35)
    stats = window_stats(series, center=25.0, window=5.0)
    assert stats["pre_mean"] == pytest.approx(10.0)
    assert stats["post_mean"] == pytest.approx(10.0)
    assert stats["delta"] == pytest.approx(0.0)


def test_window_stats_delta():
    # Pre window: value=10, post window: value=5 → delta = -5
    pre = [{"minute": float(m), "value": 10.0} for m in range(20, 25)]
    post = [{"minute": float(m), "value": 5.0} for m in range(26, 31)]
    stats = window_stats(pre + post, center=25.0, window=5.0)
    assert stats["delta"] == pytest.approx(-5.0)


def test_window_stats_excludes_center():
    series = [{"minute": 25.0, "value": 999.0}]
    series += [{"minute": float(m), "value": 1.0} for m in range(20, 25)]
    series += [{"minute": float(m), "value": 1.0} for m in range(26, 31)]
    stats = window_stats(series, center=25.0, window=5.0)
    assert stats["pre_mean"] == pytest.approx(1.0)
    assert stats["post_mean"] == pytest.approx(1.0)


def test_window_stats_too_few_points():
    # Only 1 point in each window → None
    stats = window_stats([{"minute": 22.0, "value": 5.0}, {"minute": 28.0, "value": 5.0}],
                         center=25.0, window=5.0)
    assert stats["pre_mean"] is None
    assert stats["post_mean"] is None
    assert stats["delta"] is None


def test_expand_stoppage_rows_two_rows(match_inputs):
    meta, momentum, incidents, commentary = match_inputs
    from src.parse.stoppages import detect_stoppages
    stoppages = detect_stoppages(meta, incidents, commentary)
    assert stoppages, "need at least one stoppage"
    rows = expand_stoppage_rows(meta, stoppages[0], momentum)
    assert len(rows) == 2
    home_row = next(r for r in rows if r["is_home"])
    away_row = next(r for r in rows if not r["is_home"])
    assert home_row["team"] == meta["home_team"]
    assert away_row["team"] == meta["away_team"]


def test_expand_stoppage_rows_negation(match_inputs):
    meta, momentum, incidents, commentary = match_inputs
    from src.parse.stoppages import detect_stoppages
    stoppages = detect_stoppages(meta, incidents, commentary)
    rows = expand_stoppage_rows(meta, stoppages[0], momentum)
    home_row = next(r for r in rows if r["is_home"])
    away_row = next(r for r in rows if not r["is_home"])
    if home_row["momentum_delta"] is not None:
        assert home_row["momentum_delta"] == pytest.approx(-away_row["momentum_delta"])


def test_expand_stoppage_rows_columns(match_inputs):
    from src.features.momentum_features import COLUMNS
    from src.parse.stoppages import detect_stoppages
    meta, momentum, incidents, commentary = match_inputs
    stoppages = detect_stoppages(meta, incidents, commentary)
    rows = expand_stoppage_rows(meta, stoppages[0], momentum)
    for row in rows:
        for col in COLUMNS:
            assert col in row, f"column '{col}' missing from row"
