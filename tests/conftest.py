"""Shared fixtures for offline unit tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic_match"


@pytest.fixture
def raw_match() -> dict:
    event = json.loads((FIXTURES / "event.json").read_text(encoding="utf-8"))
    incidents = json.loads((FIXTURES / "incidents.json").read_text(encoding="utf-8"))
    return {**event, "incidents": incidents}


@pytest.fixture
def match_inputs(raw_match):
    from src.scrape.sofascore import (
        nominal_hydration_lines,
        parse_incidents,
        parse_match_meta,
        parse_momentum,
    )

    meta = parse_match_meta(raw_match)
    momentum = parse_momentum(raw_match)
    incidents = parse_incidents(raw_match)

    hydration_lines = [
        {"minute": float(inc["minute"]), "text": inc["raw_type"], "type": "hydration"}
        for inc in incidents if inc["kind"] == "hydration" and inc["minute"] is not None
    ]
    var_lines = [
        {"minute": float(inc["minute"]), "text": "VAR decision", "type": "var"}
        for inc in incidents if inc["kind"] == "var" and inc["minute"] is not None
    ]
    injury_lines = [
        {"minute": float(inc["minute"]), "text": "injury stoppage", "type": "injury"}
        for inc in incidents if inc["kind"] == "injury" and inc["minute"] is not None
    ]
    if not hydration_lines:
        hydration_lines = nominal_hydration_lines(momentum)

    commentary = hydration_lines + var_lines + injury_lines
    return meta, momentum, incidents, commentary
