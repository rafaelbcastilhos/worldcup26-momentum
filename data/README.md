# data/

**Policy**: derived-data only. Raw SofaScore payloads stay in `data/raw/sofascore/` (gitignored).
Only `data/processed/` (parquet + JSON) and `snapshots/` are committed.

| Path | Contents | Committed? |
|------|----------|------------|
| `raw/sofascore/*.json` | Raw SofaScore API responses per match | No (gitignored) |
| `processed/stoppages.parquet` | Analysis-ready stoppage table (2 rows/stoppage) | Yes |
| `processed/momentum.json` | Per-match momentum series + stoppage markers (for Dash app) | Yes |
| `processed/matches.json` | Match metadata (teams, score, stage) | Yes |
| `match_ids.json` | Tracked SofaScore event IDs | Yes |
