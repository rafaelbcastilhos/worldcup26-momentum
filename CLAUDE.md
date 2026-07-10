# CLAUDE.md — agent guidance

This is a **research project, not production code.** Prioritize clarity and reproducibility over abstraction.

## Data source
**SofaScore only.** Do not add other scrapers. All momentum, incidents, and match metadata come from
`api.sofascore.com`. FotMob, ESPN, BBC, StatsBomb, and Open-Meteo are explicitly excluded.

## Hard rules
- Persist raw scraped JSON to `data/raw/sofascore/` before any parsing. Never re-scrape during analysis.
- Every result must be deterministically reproducible from `data/processed/stoppages.parquet`.
- Prefer **polars** over pandas for all data manipulation.
- Tests are required for stoppage-detection and momentum-windowing logic. Commit fixtures to `tests/fixtures/`.
- The Dash app (`src/app.py`) reads only from `data/processed/` — it never triggers scraping.

## Architecture
- **Local** (macOS, cron/launchd): `scripts/daily.sh` — scrape → parse → parquet → snapshot → commit → push.
- **App** (`src/app.py`): reads committed parquet + JSON → interactive Dash web app. Never scrapes.

## Run
```
uv sync                                   # install deps
uv sync --extra dev                       # + pytest
uv run python -m src.pipeline --help
uv run pytest
uv run python src/app.py                  # interactive web app at http://localhost:8050
```

## Layout
- `src/scrape/sofascore.py` — SofaScore API (network only; persist raw)
- `src/parse/stoppages.py`  — stoppage detection (hydration, VAR, injury)
- `src/features/`           — 5-min pre/post momentum windowing
- `src/analysis/`           — descriptive stats + CIs
- `src/viz/charts.py`       — Plotly chart builders
- `src/app.py`              — Dash web application
