"""One-command pipeline: scrape → parse → features → processed parquet → snapshot.

Idempotent: matches whose raw JSON already exists are NOT re-scraped; the parquet
is always rebuilt from disk. Designed to run daily from a residential machine
(scrape only). The Dash app never calls this — it reads the committed parquet.

Usage:
  uv run python -m src.pipeline --ids-file data/match_ids.json --date 2026-06-22
  uv run python -m src.pipeline --match-ids 12345678 87654321
  uv run python -m src.pipeline --no-scrape     # rebuild parquet from cached raw
  uv run python -m src.pipeline --discover-days 3 --date 2026-06-30
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import polars as pl

from src.features.momentum_features import COLUMNS, expand_stoppage_rows
from src.parse.stoppages import detect_stoppages
from src.paths import DATA, PROCESSED, RAW_SOFASCORE, STOPPAGES_PARQUET, ensure_dirs
from src.scrape import sofascore
from src.snapshot import write_snapshot

MATCH_IDS_FILE = DATA / "match_ids.json"


def assemble_rows(
    meta: dict[str, Any],
    momentum: list[dict[str, float]],
    incidents: list[dict[str, Any]],
    commentary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for s in detect_stoppages(meta, incidents, commentary):
        rows.extend(expand_stoppage_rows(meta, s, momentum))
    return rows


def rows_for_match(event_id: int | str) -> list[dict[str, Any]]:
    meta, momentum, incidents, commentary = sofascore.match_inputs(event_id)
    if not meta or not momentum:
        return []
    return assemble_rows(meta, momentum, incidents, commentary)


def scrape_match(event_id: int | str, *, client=None, force: bool = False) -> None:
    sofascore.fetch_match(event_id, client=client, force=force)


def discover_scraped_ids() -> list[str]:
    return sorted(p.stem for p in RAW_SOFASCORE.glob("*.json")) if RAW_SOFASCORE.exists() else []


def _guard_rowcount(prev: int, new: int, *, force: bool) -> None:
    if force or prev <= 0:
        return
    if new < max(1, prev // 2):
        raise RuntimeError(
            f"Refusing to overwrite stoppages.parquet: rows {prev} -> {new} (>50% drop). "
            "Investigate or re-run with --force."
        )
    if prev >= 60 and new > prev * 2.5:
        raise RuntimeError(
            f"Refusing to overwrite stoppages.parquet: rows {prev} -> {new} (>2.5x inflation). "
            "Investigate or re-run with --force."
        )


def build_table(match_ids: list[str]) -> pl.DataFrame:
    rows: list[dict[str, Any]] = []
    for mid in match_ids:
        rows.extend(rows_for_match(mid))
    if not rows:
        return pl.DataFrame(schema={c: pl.Utf8 for c in COLUMNS})
    return pl.DataFrame(rows).select(COLUMNS)


def _write_matches_json(match_ids: list[str]) -> None:
    rows = []
    for mid in match_ids:
        raw = sofascore.load_raw(mid)
        if not raw:
            continue
        m = sofascore.parse_match_meta(raw)
        rows.append({
            "id": str(mid),
            "home": m.get("home_team"),
            "away": m.get("away_team"),
            "home_score": m.get("home_score"),
            "away_score": m.get("away_score"),
            "ts": m.get("start_timestamp"),
            "stage": m.get("stage"),
        })
    rows.sort(key=lambda r: (r["ts"] or 0, r["id"]))
    (PROCESSED / "matches.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def _write_momentum_json(match_ids: list[str], df: pl.DataFrame) -> None:
    out = []
    for mid in match_ids:
        raw = sofascore.load_raw(mid)
        if not raw:
            continue
        series = [
            [round(p["minute"], 1), round(p["value"], 1)]
            for p in sofascore.parse_momentum(raw)
        ]
        if not series:
            continue
        m = sofascore.parse_match_meta(raw)
        stoppages = []
        if df is not None and not df.is_empty():
            sub = (
                df.filter(pl.col("match_id") == str(mid))
                .select(["clock_minute", "stoppage_type", "real_duration_seconds"])
                .unique()
                .sort(["clock_minute", "stoppage_type"])
            )
            stoppages = [
                [r["clock_minute"], r["stoppage_type"], r["real_duration_seconds"]]
                for r in sub.to_dicts()
            ]
        out.append({
            "id": str(mid),
            "home": m.get("home_team"),
            "away": m.get("away_team"),
            "hs": m.get("home_score"),
            "as": m.get("away_score"),
            "ts": m.get("start_timestamp"),
            "stage": m.get("stage"),
            "series": series,
            "stoppages": stoppages,
            "goals": sofascore.parse_goals(raw),
        })
    (PROCESSED / "momentum.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


def discover_finished_wc_ids(days: int | None = None, end_date: str | None = None) -> list[str]:
    """Discover all finished WC2026 matches from the SofaScore tournament endpoint.

    The `days` / `end_date` parameters are kept for CLI compatibility but are now
    ignored — the tournament endpoint returns ALL finished matches in one go,
    which is simpler and more reliable than querying by date.
    """
    client = sofascore.make_client()
    events = sofascore.list_wc_finished_events(client=client)
    found = {str(e["id"]) for e in events if e.get("id")}

    existing: set[str] = set()
    if MATCH_IDS_FILE.exists():
        existing = {str(x) for x in json.loads(MATCH_IDS_FILE.read_text(encoding="utf-8"))}

    if not found and existing:
        print(f"[discover] WARNING: 0 matches returned; keeping {len(existing)} (no overwrite)")
        return sorted(existing, key=lambda x: int(x) if x.isdigit() else 0)

    merged = sorted(existing | found, key=lambda x: int(x) if x.isdigit() else 0)
    tmp = MATCH_IDS_FILE.with_name(MATCH_IDS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(merged), encoding="utf-8")
    tmp.replace(MATCH_IDS_FILE)
    new_count = len(found - existing)
    print(f"[discover] {len(found)} finished WC matches ({new_count} new); tracking {len(merged)} total")
    return merged


def run(
    match_ids: list[str],
    *,
    do_scrape: bool,
    force: bool,
    date: str | None,
) -> pl.DataFrame:
    ensure_dirs()

    if do_scrape and match_ids:
        client = sofascore.make_client()
        try:
            for mid in match_ids:
                try:
                    scrape_match(mid, client=client, force=force)
                    print(f"[scrape] ok {mid}")
                except Exception as e:
                    print(f"[scrape] FAIL {mid}: {type(e).__name__}: {e}")
        finally:
            if hasattr(client, "close"):
                client.close()

    all_ids = sorted(set(discover_scraped_ids()) | set(map(str, match_ids)))
    df = build_table(all_ids)

    covered = set(df["match_id"].unique().to_list()) if not df.is_empty() else set()
    missing = [m for m in all_ids if m not in covered]
    if missing:
        shown = ", ".join(missing[:12]) + (" …" if len(missing) > 12 else "")
        print(f"[build] WARNING: {len(missing)}/{len(all_ids)} matches produced 0 rows ({shown})")

    if set(df.columns) != set(COLUMNS):
        raise RuntimeError(f"parquet schema drift: {sorted(set(COLUMNS) ^ set(df.columns))}")
    if STOPPAGES_PARQUET.exists():
        _guard_rowcount(pl.read_parquet(STOPPAGES_PARQUET).height, df.height, force=force)

    STOPPAGES_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(STOPPAGES_PARQUET)
    print(f"[build] {df.height} rows from {len(all_ids)} matches ({len(covered)} with data) -> {STOPPAGES_PARQUET}")

    if date:
        path = write_snapshot(df, date)
        print(f"[snapshot] {path}")

    _write_matches_json(all_ids)
    _write_momentum_json(all_ids, df)
    print(f"[meta] matches.json + momentum.json written ({len(all_ids)} matches)")

    return df


def _parse_ids(args: argparse.Namespace) -> list[str]:
    ids: list[str] = [str(i) for i in (args.match_ids or [])]
    if args.ids_file:
        data = json.loads(open(args.ids_file, encoding="utf-8").read())
        ids += [str(i) for i in data]
    return sorted(set(ids))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--match-ids", nargs="*", type=str, help="SofaScore event IDs to scrape/build")
    ap.add_argument("--ids-file", type=str, help="JSON file with a list of event IDs")
    ap.add_argument("--no-scrape", action="store_true", help="rebuild parquet from cached raw only")
    ap.add_argument("--force", action="store_true", help="re-fetch even if raw exists")
    ap.add_argument("--date", type=str, default=None, help="snapshot date YYYY-MM-DD")
    ap.add_argument(
        "--discover-days", type=int, default=None,
        help="auto-discover finished WC matches over the last N days",
    )
    args = ap.parse_args()

    ids = _parse_ids(args)
    if args.discover_days:
        ids = sorted(
            set(ids) | set(discover_finished_wc_ids(args.discover_days, args.date)),
            key=lambda x: int(x) if x.isdigit() else 0,
        )
    run(ids, do_scrape=not args.no_scrape, force=args.force, date=args.date)


if __name__ == "__main__":
    main()
