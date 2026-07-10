"""Stoppage detection — adapted for SofaScore-only inputs.

Consumes normalized inputs (match meta + SofaScore incidents + commentary-style
lines derived from incidents) and emits one stoppage record per detected event.
`src/features/momentum_features.py` expands each into two team-perspective rows.

Detection sources:
  hydration      -> SofaScore drinkingBreak/coolingBreak incidents, or nominal 22'/67'
  var            -> SofaScore varDecision incidents; commentary lines as supplement
  injury_huddle  -> SofaScore injury incidents where a sub was made nearby
  injury_no_huddle -> SofaScore injury incidents with no nearby sub

Unit-tested offline against fixtures (CLAUDE.md requirement).
"""

from __future__ import annotations

from typing import Any

from src.paths import HYDRATION_NOMINAL_MINUTES

# Substitution window relative to stoppage minute: sub counts as "during the break"
# if it falls within [minute - 1, minute + 2].
SUB_WINDOW = (-1.0, 2.0)

# Two hydration signals within this many minutes → same break.
HYDRATION_CLUSTER_GAP = 3.0


def detect_stoppages(
    meta: dict[str, Any],
    incidents: list[dict[str, Any]],
    commentary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return match-level stoppage records (team-agnostic).

    Each record has enough context for the features step: clock minute, type,
    pre-stoppage score/card state, and sub-at-break info.
    """
    match_id = meta.get("match_id")
    stoppages: list[dict[str, Any]] = []

    # --- hydration: cluster nearby hydration commentary lines ----------------
    for minute in _cluster_hydration(commentary):
        stoppages.append(_base_record(match_id, "hydration", minute, incidents))

    # --- VAR: incidents (varDecision) + commentary supplement ----------------
    var_minutes = [
        float(i["minute"]) for i in incidents
        if i["kind"] == "var" and i["minute"] is not None
    ]
    for minute in var_minutes:
        rec = _base_record(match_id, "var", minute, incidents)
        rec["var_outcome"] = next(
            (i.get("detail") for i in incidents if i["kind"] == "var" and i["minute"] == minute),
            None,
        )
        stoppages.append(rec)
    # Commentary-derived VARs: deduplicated vs incidents list.
    for minute in _cluster_commentary_type(commentary, "var"):
        if any(abs(minute - vm) <= 2 for vm in var_minutes):
            continue
        stoppages.append(_base_record(match_id, "var", minute, incidents))

    # --- injuries: from commentary, classify huddle vs no_huddle -------------
    for minute in _cluster_commentary_type(commentary, "injury"):
        sub_during = _subs_in_window(incidents, minute)
        is_huddle = (sub_during["home"] + sub_during["away"]) > 0
        stype = "injury_huddle" if is_huddle else "injury_no_huddle"
        stoppages.append(_base_record(match_id, stype, minute, incidents))

    stoppages.sort(key=lambda s: s["clock_minute"])
    for idx, s in enumerate(stoppages):
        s["stoppage_id"] = f"{match_id}-{idx:02d}"
    return stoppages


# --- detection helpers ------------------------------------------------------

def _cluster_hydration(commentary: list[dict[str, Any]]) -> list[float]:
    """Representative minute per hydration break, filtered to nominal zones."""
    hyd = [c for c in commentary if c.get("type") == "hydration" and c.get("minute") is not None]
    out = []
    for cl in _cluster(sorted(c["minute"] for c in hyd), HYDRATION_CLUSTER_GAP):
        m = sum(cl) / len(cl)
        if any(abs(m - nom) <= 12 for nom in HYDRATION_NOMINAL_MINUTES):
            out.append(round(m, 1))
    return out


def _cluster_commentary_type(commentary: list[dict[str, Any]], label: str) -> list[float]:
    minutes = sorted(
        c["minute"] for c in commentary if c.get("type") == label and c.get("minute") is not None
    )
    return [round(sum(cl) / len(cl), 1) for cl in _cluster(minutes, 2.0)]


def _cluster(minutes: list[float], gap: float) -> list[list[float]]:
    clusters: list[list[float]] = []
    for m in minutes:
        if clusters and m - clusters[-1][-1] <= gap:
            clusters[-1].append(m)
        else:
            clusters.append([m])
    return clusters


def _base_record(
    match_id: Any,
    stype: str,
    minute: float,
    incidents: list[dict[str, Any]],
    *,
    duration: float | None = None,
) -> dict[str, Any]:
    home_score, away_score = _score_at(incidents, minute)
    reds = _red_cards_before(incidents, minute)
    subs = _subs_in_window(incidents, minute)
    return {
        "match_id": match_id,
        "stoppage_type": stype,
        "clock_minute": float(minute),
        "real_duration_seconds": duration,
        "home_score_pre": home_score,
        "away_score_pre": away_score,
        "red_cards_home_pre": reds["home"],
        "red_cards_away_pre": reds["away"],
        "sub_made_during_break": (subs["home"] + subs["away"]) > 0,
        "subs_count_home": subs["home"],
        "subs_count_away": subs["away"],
        "var_outcome": None,
    }


def _score_at(incidents: list[dict[str, Any]], minute: float) -> tuple[int, int]:
    home, away = 0, 0
    for i in incidents:
        if i["kind"] == "goal" and i["minute"] is not None and i["minute"] <= minute:
            if i.get("home_score") is not None and i.get("away_score") is not None:
                home, away = int(i["home_score"]), int(i["away_score"])
            else:
                if i.get("is_home"):
                    home += 1
                else:
                    away += 1
    return home, away


def _red_cards_before(incidents: list[dict[str, Any]], minute: float) -> dict[str, int]:
    reds = {"home": 0, "away": 0}
    for i in incidents:
        if i["kind"] == "card" and i["minute"] is not None and i["minute"] <= minute:
            if (i.get("detail") or "").lower() in {"red", "yellowred"}:
                reds["home" if i.get("is_home") else "away"] += 1
    return reds


def _subs_in_window(incidents: list[dict[str, Any]], minute: float) -> dict[str, int]:
    lo, hi = minute + SUB_WINDOW[0], minute + SUB_WINDOW[1]
    subs = {"home": 0, "away": 0}
    for i in incidents:
        if i["kind"] == "substitution" and i["minute"] is not None and lo <= i["minute"] <= hi:
            subs["home" if i.get("is_home") else "away"] += 1
    return subs
