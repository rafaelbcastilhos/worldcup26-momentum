"""Canonical filesystem paths and project-wide constants."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"

SNAPSHOTS = ROOT / "snapshots"
SITE = ROOT / "site"
FIXTURES = ROOT / "tests" / "fixtures"

RAW_SOFASCORE = RAW / "sofascore"

STOPPAGES_PARQUET = PROCESSED / "stoppages.parquet"

# Nominal hydration break minutes (FIFA mandates at ~22' and ~67' in hot conditions).
# Used as seeds when SofaScore has no explicit hydration incident.
HYDRATION_NOMINAL_MINUTES = (22, 67)

# Pre/post momentum window (minutes) around a stoppage.
WINDOW_MIN = 5

STOPPAGE_TYPES = (
    "hydration",
    "var",
    "injury_huddle",
    "injury_no_huddle",
)


def ensure_dirs() -> None:
    for d in (RAW_SOFASCORE, PROCESSED, SNAPSHOTS, SITE):
        d.mkdir(parents=True, exist_ok=True)
