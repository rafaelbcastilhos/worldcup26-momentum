# PROJECT_BRIEF.md

## Project goal

Quantify how in-match stoppages affect game momentum at the 2026 FIFA World Cup, using FIFA's new mandatory hydration breaks as the primary natural experiment and other stoppage types (VAR) as comparison conditions to isolate the mechanism.

Output: a reproducible dataset, an analysis notebook, a short writeup with charts suitable for a LinkedIn/portfolio post.

## Research questions

**Primary.** Do FIFA's mandated 3-minute hydration breaks (~22' and ~67') shift in-match momentum, and if so, in whose favor?

## Hypotheses

1. Hydration breaks shift momentum away from the team that was on top pre-break (the "momentum killer" claim from coaches and pundits).
2. The effect is larger for hydration breaks than for VAR reviews of similar duration — implying the coaching window matters more than the pause.

## Data sources

### Live momentum series (primary outcome)
- **SofaScore** match pages expose a per-minute momentum series. Scrape via their internal API used by the web app.

## Momentum operationalization

**Primary metric.** Signed momentum series from SofaScore (positive = home team, negative = away), reframed to team-perspective per row. Aggregate to 5-minute pre/post windows around each stoppage.

## Confounders and pitfalls to handle explicitly

- **Regression to the mean** is the single biggest threat. A team that just had a hot 5 minutes is, on average, regressing whether or not a break happens.
- **Selection on injuries** — they correlate with intensity and score state, and sometimes are tactically feigned.
- **VAR reviews** typically follow potential goals or red cards — score state often changes during them. Either drop VARs that result in a goal/card or analyze them split by outcome.
- **Score state asymmetry** — losing teams behave differently. Always condition on `score_diff_pre`.
- **Substitutions at the break** are a real co-treatment. Report results both pooled and split by sub/no-sub.
- **Multiple stoppages per match** are not independent. Cluster standard errors at the match level.
- **Stoppage time accounting** — the clock runs during hydration breaks, so the "67'" stoppage is real-time-shifted from the nominal mark. Use actual commentary timestamps, not clock minutes.

## Tech stack

- **Python 3.12**, `uv` for env management.
- **Data**: `polars` (preferred) or `pandas`, `httpx` for scraping, `selectolax` or `parsel` for HTML where needed. Persist raw responses; never re-scrape during analysis.
- **Stats**: `statsmodels` for fixed-effects regression, `linearmodels` if we need proper panel methods, `scipy` for bootstrap.
