"""SofaScore scraper — sole data source.

Fetches per-match momentum graph, incidents, and match metadata from
api.sofascore.com. Uses curl-cffi with Chrome impersonation to avoid
Cloudflare blocks. No auth header required (public API).

Endpoints:
  Event details:  GET /api/v1/event/{event_id}
  Momentum graph: GET /api/v1/event/{event_id}/graph
  Incidents:      GET /api/v1/event/{event_id}/incidents
  Scheduled:      GET /api/v1/sport/football/scheduled-events/{YYYY-MM-DD}

Runtime: residential IP recommended; SofaScore may block datacenter IPs.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.paths import HYDRATION_NOMINAL_MINUTES, RAW_SOFASCORE, WINDOW_MIN

BASE = "https://api.sofascore.com"

# SofaScore IDs for FIFA World Cup 2026.
# uniqueTournament 16 = FIFA World Cup (all editions).
# Season 58210 = 2026 edition.
# Verified via: GET /api/v1/unique-tournament/16/seasons
WC2026_TOURNAMENT_ID = 16
WC2026_SEASON_ID = 58210

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Full Chrome header set — SofaScore rejects requests that look non-browser.
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
}


def make_client(*, warmup: bool = True):
    """curl-cffi session with Chrome impersonation + optional homepage warm-up.

    The warm-up visit to sofascore.com establishes Cloudflare session cookies
    (cf_clearance) that the API endpoints require. Without it, /api/v1/ calls
    return 403 on the first request after a cold start.
    """
    from curl_cffi import requests as creq

    sess = creq.Session(impersonate="chrome131")
    sess.headers.update(_HEADERS)

    if warmup:
        try:
            sess.get("https://www.sofascore.com/", timeout=20)
            time.sleep(0.8)  # brief pause so Cloudflare sees a human pace
        except Exception:
            pass  # warm-up is best-effort; proceed anyway

    return sess


def _get(client, path: str, *, retries: int = 4) -> dict[str, Any]:
    last = None
    for attempt in range(retries):
        r = client.get(BASE + path, timeout=30)
        if r.status_code == 200:
            try:
                return r.json()
            except Exception as e:
                ct = r.headers.get("content-type", "?")
                raise RuntimeError(f"SofaScore 200 non-JSON ({ct}): {path}") from e
        # 403 = Cloudflare challenge or temporary bot-detection block — retryable.
        # 404 = resource doesn't exist — not retryable (caller handles).
        # 429 = rate limit — retryable.
        # Other 4xx = permanent error.
        if r.status_code == 404:
            raise RuntimeError(f"SofaScore GET 404: {path}")
        if 400 <= r.status_code < 500 and r.status_code not in (403, 429):
            raise RuntimeError(f"SofaScore GET {r.status_code}: {path}")
        last = str(r.status_code)
        # Exponential back-off: 3s, 8s, 18s (gives Cloudflare time to clear)
        wait = 3.0 * (2 ** attempt)
        ra = r.headers.get("Retry-After")
        if ra:
            try:
                wait = max(wait, float(ra))
            except ValueError:
                pass
        print(f"[sofascore] {r.status_code} on {path} — retrying in {wait:.0f}s (attempt {attempt + 1}/{retries})")
        time.sleep(wait)
    raise RuntimeError(f"SofaScore GET failed after {retries} attempts: {path} (last status {last})")


# --- fetch / persist --------------------------------------------------------

def _get_or_empty(client, path: str, empty_key: str) -> dict[str, Any]:
    """GET with graceful fallback: returns {empty_key: []} on 404 instead of raising."""
    try:
        return _get(client, path)
    except RuntimeError as e:
        if "404" in str(e):
            return {empty_key: []}
        raise


def fetch_match(event_id: int | str, *, client=None, force: bool = False) -> dict[str, Any]:
    """Fetch + persist all SofaScore data for one match. Idempotent.

    The /graph endpoint returns 404 for some matches (e.g. matches where SofaScore
    hasn't published a momentum series). Those are stored with an empty graphPoints
    list and will produce 0 rows in the pipeline (momentum required for windowing).
    """
    RAW_SOFASCORE.mkdir(parents=True, exist_ok=True)
    path = RAW_SOFASCORE / f"{event_id}.json"
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))

    cl = client or make_client()
    eid = str(event_id)

    event = _get(cl, f"/api/v1/event/{eid}")
    graph = _get_or_empty(cl, f"/api/v1/event/{eid}/graph", "graphPoints")
    incidents = _get_or_empty(cl, f"/api/v1/event/{eid}/incidents", "incidents")

    data = {"event": event.get("event", {}), "graph": graph, "incidents": incidents}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def load_raw(event_id: int | str) -> dict[str, Any]:
    path = RAW_SOFASCORE / f"{event_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# --- discovery --------------------------------------------------------------

def list_wc_finished_events(*, client=None) -> list[dict[str, Any]]:
    """All finished WC2026 matches from the SofaScore tournament-season endpoint.

    Uses /api/v1/unique-tournament/16/season/58210/events/last/{page} which
    paginates backwards (most recent first). More reliable than the
    scheduled-events-by-date endpoint, which returns empty arrays for scrapers.
    """
    cl = client or make_client()
    out = []
    for page in range(20):  # safety cap: 20 pages × 30 events = 600 max
        path = (f"/api/v1/unique-tournament/{WC2026_TOURNAMENT_ID}"
                f"/season/{WC2026_SEASON_ID}/events/last/{page}")
        try:
            data = _get(cl, path)
        except RuntimeError as e:
            if "404" in str(e):
                break  # no more pages
            raise
        events = data.get("events") or []
        for event in events:
            status = (event.get("status") or {}).get("type", "")
            if status not in ("finished", "ended"):
                continue
            out.append({
                "id": event.get("id"),
                "home": (event.get("homeTeam") or {}).get("name"),
                "away": (event.get("awayTeam") or {}).get("name"),
                "status": status,
                "startTimestamp": event.get("startTimestamp"),
            })
        if not data.get("hasNextPage", False):
            break
    return out


# --- parsers ----------------------------------------------------------------

def parse_momentum(raw: dict[str, Any]) -> list[dict[str, float]]:
    """Per-minute momentum series, home-positive.

    SofaScore graphPoints: [{minute, value, period}, ...].
    Value > 0 means home team dominant; < 0 means away dominant.
    """
    out = []
    for p in (raw.get("graph") or {}).get("graphPoints") or []:
        m, v = p.get("minute"), p.get("value")
        if m is not None and v is not None:
            out.append({"minute": float(m), "value": float(v)})
    out.sort(key=lambda p: p["minute"])
    return out


def parse_match_meta(raw: dict[str, Any]) -> dict[str, Any]:
    e = raw.get("event") or {}
    venue = e.get("venue") or {}
    city = (venue.get("city") or {}).get("name")
    hs = (e.get("homeScore") or {}).get("current")
    aws = (e.get("awayScore") or {}).get("current")
    season = e.get("season") or {}
    round_info = e.get("roundInfo") or {}
    stage = round_info.get("name") or round_info.get("round")
    return {
        "match_id": str(e.get("id", "")),
        "start_timestamp": e.get("startTimestamp"),
        "home_team": (e.get("homeTeam") or {}).get("name"),
        "away_team": (e.get("awayTeam") or {}).get("name"),
        "home_team_id": (e.get("homeTeam") or {}).get("id"),
        "away_team_id": (e.get("awayTeam") or {}).get("id"),
        "tournament": (e.get("tournament") or {}).get("name"),
        "season": season.get("name"),
        "stage": str(stage) if stage else None,
        "venue_stadium": venue.get("name"),
        "venue_city": city,
        "home_score": int(hs) if hs is not None else None,
        "away_score": int(aws) if aws is not None else None,
    }


def parse_incidents(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize SofaScore incidents to the pipeline-internal shape.

    SofaScore incident types mapped:
      goal / penalty → "goal"
      card (yellow/red/yellowRed) → "card"
      substitution → "substitution"
      varDecision → "var"
      drinkingBreak / coolingBreak → "hydration"
      injury → "injury"
    """
    _kind_map = {
        "goal": "goal",
        "penalty": "goal",
        "card": "card",
        "substitution": "substitution",
        "varDecision": "var",
        "drinkingBreak": "hydration",
        "coolingBreak": "hydration",
        "injury": "injury",
    }
    out: list[dict[str, Any]] = []
    for inc in (raw.get("incidents") or {}).get("incidents") or []:
        itype = inc.get("incidentType", "")
        kind = _kind_map.get(itype)
        if not kind:
            continue

        minute = inc.get("time") or inc.get("minute")
        is_home = inc.get("isHome")

        detail = None
        if kind == "card":
            detail = (inc.get("cardType") or "").lower() or None
        elif kind == "var":
            detail = (inc.get("incidentClass") or "").lower() or None
        elif kind == "goal":
            detail = (inc.get("incidentClass") or "").lower() or None

        out.append({
            "kind": kind,
            "raw_type": itype,
            "minute": float(minute) if minute is not None else None,
            "added": inc.get("addedTime"),
            "is_home": is_home,
            "detail": detail,
            "home_score": inc.get("homeScore"),
            "away_score": inc.get("awayScore"),
            "length": None,
        })

    out.sort(key=lambda r: (r["minute"] if r["minute"] is not None else 1e9, r.get("added") or 0))
    return out


def nominal_hydration_lines(momentum: list[dict[str, float]]) -> list[dict[str, Any]]:
    """Synthetic hydration markers at nominal WC2026 minutes (22' and 67').

    Used only when SofaScore has no explicit hydration incident. Emits
    pre-normalized commentary-style lines so detect_stoppages picks them up.
    """
    if not momentum:
        return []
    max_min = max(p["minute"] for p in momentum)
    lines = []
    for mark in HYDRATION_NOMINAL_MINUTES:
        if max_min >= mark + WINDOW_MIN:
            lines.append({
                "minute": float(mark),
                "text": "mandatory hydration break (nominal)",
                "type": "hydration",
            })
    return lines


def match_inputs(event_id: int | str) -> tuple[dict, list, list, list]:
    """(meta, momentum, incidents, commentary) for one match from persisted raw.

    `commentary` here is the SofaScore-derived hydration incident list (or
    nominal lines if none found) — passed to detect_stoppages in place of
    traditional commentary.
    """
    raw = load_raw(event_id)
    if not raw:
        return {}, [], [], []

    meta = parse_match_meta(raw)
    momentum = parse_momentum(raw)
    incidents = parse_incidents(raw)

    # Build commentary-style lines from structured incidents.
    # Hydration: explicit drinkingBreak/coolingBreak incidents if present.
    hydration_lines = [
        {"minute": float(inc["minute"]), "text": inc["raw_type"], "type": "hydration"}
        for inc in incidents if inc["kind"] == "hydration" and inc["minute"] is not None
    ]
    # VAR: from incidents (already reflected in incidents list; also feed commentary
    # so detect_stoppages commentary fallback path is populated).
    var_lines = [
        {"minute": float(inc["minute"]), "text": "VAR decision", "type": "var"}
        for inc in incidents if inc["kind"] == "var" and inc["minute"] is not None
    ]
    # Injury: from structured injury incidents if SofaScore provides them.
    injury_lines = [
        {"minute": float(inc["minute"]), "text": "injury stoppage", "type": "injury"}
        for inc in incidents if inc["kind"] == "injury" and inc["minute"] is not None
    ]

    # Fall back to nominal minutes when no explicit hydration found.
    if not hydration_lines:
        hydration_lines = nominal_hydration_lines(momentum)

    commentary = hydration_lines + var_lines + injury_lines
    return meta, momentum, incidents, commentary


def parse_goals(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Compact goal timeline for the momentum chart markers."""
    out = []
    for inc in (raw.get("incidents") or {}).get("incidents") or []:
        if inc.get("incidentType") not in ("goal", "penalty"):
            continue
        minute = inc.get("time") or inc.get("minute")
        if minute is None:
            continue
        kind = "pen" if inc.get("incidentType") == "penalty" else ""
        if (inc.get("incidentClass") or "").lower() == "owngoal":
            kind = "og"
        out.append({
            "m": int(minute),
            "h": 1 if inc.get("isHome") else 0,
            "who": (inc.get("player") or {}).get("name") or "",
            "sc": f"{inc.get('homeScore', '')}-{inc.get('awayScore', '')}",
            "k": kind,
        })
    out.sort(key=lambda r: r["m"])
    return out


# --- diagnostic -------------------------------------------------------------

def _diagnostic(event_id: str) -> int:
    from src.parse.stoppages import detect_stoppages

    print(f"[diag] SofaScore event {event_id} …")
    try:
        raw = fetch_match(event_id, force=True)
    except Exception as e:
        print(f"[diag] FAIL: {type(e).__name__}: {e}")
        return 1

    meta, momentum, incidents, commentary = match_inputs(event_id)
    stoppages = detect_stoppages(meta, incidents, commentary)
    print(f"[diag] OK  {meta.get('home_team')} {meta.get('home_score')}–"
          f"{meta.get('away_score')} {meta.get('away_team')}  ({meta.get('stage')})")
    print(f"[diag] momentum points: {len(momentum)} | incidents: {len(incidents)}")
    print(f"[diag] stoppages: {len(stoppages)} -> {sorted({s['stoppage_type'] for s in stoppages})}")
    return 0 if momentum else 1


def _list_wc(client=None) -> int:
    """List all finished WC2026 matches from the tournament endpoint."""
    cl = client or make_client()
    events = list_wc_finished_events(client=cl)
    from datetime import datetime, timezone
    print(f"\nWC2026 finished matches (tournament {WC2026_TOURNAMENT_ID}, season {WC2026_SEASON_ID}): {len(events)}\n")
    print(f"{'id':>12}  {'date':<12}  {'home':<25}  {'away'}")
    print("-" * 70)
    for e in sorted(events, key=lambda x: x.get("startTimestamp") or 0):
        ts = e.get("startTimestamp", 0)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else "?"
        print(f"{e['id']:>12}  {dt:<12}  {(e['home'] or '?'):<25}  {e['away'] or '?'}")
    return 0


if __name__ == "__main__":
    import sys

    if "--list-wc" in sys.argv:
        raise SystemExit(_list_wc())
    if len(sys.argv) < 2:
        print("usage: python -m src.scrape.sofascore <event_id>")
        print("       python -m src.scrape.sofascore --list-wc")
        raise SystemExit(2)
    raise SystemExit(_diagnostic(sys.argv[1]))
