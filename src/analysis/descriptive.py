"""Phase-1 descriptive analysis: conditioned effect by stoppage type + bootstrap CIs.

The pooled mean momentum_delta is ~0 by construction (two mirrored team rows per
stoppage). The analysis conditions on the team ON TOP pre-break
(momentum_pre_5min_mean > 0). Hypothesis: hydration breaks reduce the leader's
momentum advantage (negative delta).

Bootstrap CIs are clustered at match level (multiple stoppages per match are not
independent) by resampling matches.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from src.paths import STOPPAGES_PARQUET


def load_processed(path=STOPPAGES_PARQUET) -> pl.DataFrame:
    return pl.read_parquet(path)


def on_top_rows(df: pl.DataFrame) -> pl.DataFrame:
    return df.drop_nulls(["momentum_delta", "momentum_pre_5min_mean"]).filter(
        pl.col("momentum_pre_5min_mean") > 0
    )


def cluster_bootstrap_ci(
    df: pl.DataFrame,
    value_col: str = "momentum_delta",
    *,
    n_boot: int = 2000,
    seed: int = 7,
) -> tuple[float, float, float]:
    """Mean + 95% CI by resampling matches (cluster bootstrap). Returns (mean, lo, hi)."""
    if df.is_empty():
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    matches = df["match_id"].unique().to_list()
    by_match = {m: df.filter(pl.col("match_id") == m)[value_col].to_numpy() for m in matches}
    point = float(df[value_col].mean())
    means = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.choice(matches, size=len(matches), replace=True)
        vals = np.concatenate([by_match[m] for m in pick])
        means[b] = vals.mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return point, float(lo), float(hi)


def effect_by_type(df: pl.DataFrame, **boot_kw) -> list[dict]:
    """Per stoppage type: n, on-top mean delta, cluster-bootstrap 95% CI."""
    top = on_top_rows(df)
    out = []
    for stype in sorted(top["stoppage_type"].unique().to_list()):
        sub = top.filter(pl.col("stoppage_type") == stype)
        mean, lo, hi = cluster_bootstrap_ci(sub, **boot_kw)
        out.append({
            "stoppage_type": stype,
            "n": sub.height,
            "n_matches": sub["match_id"].n_unique(),
            "mean_delta": mean,
            "ci_lo": lo,
            "ci_hi": hi,
        })
    return out
