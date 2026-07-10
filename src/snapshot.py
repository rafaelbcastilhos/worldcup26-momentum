"""Dated snapshot writer — headline aggregates per daily run."""

from __future__ import annotations

import json
from typing import Any

import polars as pl

from src.paths import SNAPSHOTS


def summarize(df: pl.DataFrame) -> dict[str, Any]:
    if df.is_empty():
        return {"n_matches": 0, "n_stoppage_rows": 0, "by_type": {}}

    valid = df.drop_nulls(["momentum_delta", "momentum_pre_5min_mean"])
    on_top = valid.filter(pl.col("momentum_pre_5min_mean") > 0)
    by_type = (
        valid.group_by("stoppage_type")
        .agg(pl.len().alias("n_rows"))
        .join(
            on_top.group_by("stoppage_type").agg(
                pl.len().alias("n_on_top"),
                pl.col("momentum_delta").mean().alias("on_top_mean_delta"),
                pl.col("momentum_delta").std().alias("on_top_std_delta"),
            ),
            on="stoppage_type",
            how="left",
        )
        .sort("stoppage_type")
    )

    def _r(v):
        return round(v, 4) if v is not None else None

    return {
        "n_matches": df["match_id"].n_unique(),
        "n_stoppage_rows": df.height,
        "n_stoppages": df["stoppage_id"].n_unique(),
        "by_type": {
            r["stoppage_type"]: {
                "n_rows": r["n_rows"],
                "n_on_top": r["n_on_top"],
                "on_top_mean_delta": _r(r["on_top_mean_delta"]),
                "on_top_std_delta": _r(r["on_top_std_delta"]),
            }
            for r in by_type.to_dicts()
        },
    }


def write_snapshot(df: pl.DataFrame, date_str: str) -> str:
    out_dir = SNAPSHOTS / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(df)
    summary["date"] = date_str
    path = out_dir / "summary.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return str(path)


def load_all_snapshots() -> list[dict[str, Any]]:
    out = []
    if not SNAPSHOTS.exists():
        return out
    for d in sorted(SNAPSHOTS.iterdir()):
        f = d / "summary.json"
        if f.is_file():
            out.append(json.loads(f.read_text(encoding="utf-8")))
    return out
