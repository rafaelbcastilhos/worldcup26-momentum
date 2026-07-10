"""Momentum windowing + expansion to the stoppage-level table.

One stoppage -> two rows (one per team perspective). The momentum series is
home-positive; for the away row we negate it so every row is signed from
that row's team's perspective.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from src.paths import WINDOW_MIN

# Final column order for the stoppages parquet.
COLUMNS = [
    "match_id", "match_date", "stage", "venue",
    "team", "opponent", "is_home",
    "stoppage_id", "stoppage_type", "var_outcome",
    "clock_minute", "real_duration_seconds",
    "score_team_pre", "score_opp_pre", "score_diff_pre",
    "red_cards_pre_team", "red_cards_pre_opp",
    "sub_made_during_break", "subs_count_during_break",
    "momentum_pre_5min_mean", "momentum_pre_5min_slope",
    "momentum_post_5min_mean", "momentum_post_5min_slope",
    "momentum_delta",
]


def window_stats(
    series: list[dict[str, float]], center: float, window: float = WINDOW_MIN
) -> dict[str, float | None]:
    """Mean and slope in the pre and post windows around `center`.

    Pre  = [center - window, center)
    Post = (center, center + window]
    Returns None for fewer than 2 points (slope undefined).
    """
    pre = [(p["minute"], p["value"]) for p in series if center - window <= p["minute"] < center]
    post = [(p["minute"], p["value"]) for p in series if center < p["minute"] <= center + window]
    pre_mean, pre_slope = _mean_slope(pre)
    post_mean, post_slope = _mean_slope(post)
    delta = None if (pre_mean is None or post_mean is None) else post_mean - pre_mean
    return {
        "pre_mean": pre_mean,
        "pre_slope": pre_slope,
        "post_mean": post_mean,
        "post_slope": post_slope,
        "delta": delta,
    }


def _mean_slope(pts: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    if len(pts) < 2:
        return None, None
    xs = np.array([p[0] for p in pts], dtype=float)
    ys = np.array([p[1] for p in pts], dtype=float)
    return float(ys.mean()), float(np.polyfit(xs, ys, 1)[0])


def expand_stoppage_rows(
    meta: dict[str, Any],
    stoppage: dict[str, Any],
    momentum_series: list[dict[str, float]],
) -> list[dict[str, Any]]:
    """Produce two team-perspective rows for one stoppage."""
    center = stoppage["clock_minute"]
    home_w = window_stats(momentum_series, center)
    away_w = {k: (None if v is None else -v) for k, v in home_w.items()}

    match_date = _date_from_ts(meta.get("start_timestamp"))
    venue = meta.get("venue_stadium") or meta.get("venue_city")

    rows = []
    for is_home, w in ((True, home_w), (False, away_w)):
        team = meta.get("home_team") if is_home else meta.get("away_team")
        opp = meta.get("away_team") if is_home else meta.get("home_team")
        score_team = stoppage["home_score_pre"] if is_home else stoppage["away_score_pre"]
        score_opp = stoppage["away_score_pre"] if is_home else stoppage["home_score_pre"]
        reds_team = stoppage["red_cards_home_pre"] if is_home else stoppage["red_cards_away_pre"]
        reds_opp = stoppage["red_cards_away_pre"] if is_home else stoppage["red_cards_home_pre"]
        subs_team = stoppage["subs_count_home"] if is_home else stoppage["subs_count_away"]
        rows.append({
            "match_id": meta.get("match_id"),
            "match_date": match_date,
            "stage": meta.get("stage"),
            "venue": venue,
            "team": team,
            "opponent": opp,
            "is_home": is_home,
            "stoppage_id": stoppage["stoppage_id"],
            "stoppage_type": stoppage["stoppage_type"],
            "var_outcome": stoppage.get("var_outcome"),
            "clock_minute": center,
            "real_duration_seconds": stoppage.get("real_duration_seconds"),
            "score_team_pre": score_team,
            "score_opp_pre": score_opp,
            "score_diff_pre": (score_team - score_opp) if score_team is not None else None,
            "red_cards_pre_team": reds_team,
            "red_cards_pre_opp": reds_opp,
            "sub_made_during_break": stoppage["sub_made_during_break"],
            "subs_count_during_break": subs_team,
            "momentum_pre_5min_mean": w["pre_mean"],
            "momentum_pre_5min_slope": w["pre_slope"],
            "momentum_post_5min_mean": w["post_mean"],
            "momentum_post_5min_slope": w["post_slope"],
            "momentum_delta": w["delta"],
        })
    return rows


def _date_from_ts(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
