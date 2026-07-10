# WC Rafael — WC2026 Stoppage Momentum

Análise do momentum das seleções na Copa do Mundo 2026 durante pausas de hidratação e paradas do VAR.

**Fonte de dados:** SofaScore exclusivamente.

## Arquitetura

```mermaid
flowchart TD
    subgraph LOCAL["💻 Local — macOS (residencial)"]
        direction TB
        CRON["🕐 scripts/daily.sh\ncron / launchd"]

        subgraph PIPELINE["src/pipeline.py"]
            direction TB
            DISC["Descoberta\nlist_wc_finished_events()"]
            SCRAPE["Scrape\nfetch_match()"]
            PARSE["Detecção de paradas\ndetect_stoppages()"]
            FEAT["Janelamento\nexpand_stoppage_rows()"]
            GUARD["Guardrails\n±50% rowcount"]
        end

        DISC --> SCRAPE --> PARSE --> FEAT --> GUARD
        CRON --> PIPELINE
    end

    subgraph SOFA["🌐 SofaScore API"]
        EP1["/event/{id}\nmetadados"]
        EP2["/event/{id}/graph\nmomentum por minuto"]
        EP3["/event/{id}/incidents\ngols · cartões · VAR"]
        EP4["/unique-tournament/16/season/58210\ndescoberta de partidas"]
    end

    subgraph RAW["data/raw/sofascore/\n🔒 gitignored"]
        JSON["{match_id}.json\nevent + graph + incidents"]
    end

    subgraph PROCESSED["data/processed/  ✅ commitado"]
        PARQUET["stoppages.parquet\n2 linhas por parada"]
        MOMJSON["momentum.json\nséries + marcadores"]
        MATCHJSON["matches.json\nmetadados das partidas"]
    end

    subgraph SNAP["snapshots/{date}/"]
        SUMJSON["summary.json\nagregados diários"]
    end

    subgraph APP["src/app.py — Dash"]
        direction TB
        GRID["Grid de partidas\npor fase · mini SVG"]
        MODAL["Modal de partida\ncurva + tabela"]
        CHARTS["Gráficos de análise\nlollipop · scatter · histograma"]
    end

    SOFA -->|"curl-cffi\nChrome impersonation"| RAW
    RAW --> PIPELINE
    GUARD --> PARQUET
    PIPELINE --> MOMJSON
    PIPELINE --> MATCHJSON
    PIPELINE --> SUMJSON

    PARQUET --> APP
    MOMJSON --> APP
    MATCHJSON --> APP

    style LOCAL   fill:#F0EDE8,stroke:#C8C0AD,color:#1A1813
    style SOFA    fill:#EBF5FB,stroke:#1D9BF0,color:#1A1813
    style RAW     fill:#FFF3E0,stroke:#F5A623,color:#1A1813
    style PROCESSED fill:#E8F5E9,stroke:#16A34A,color:#1A1813
    style SNAP    fill:#F3E5F5,stroke:#9C27B0,color:#1A1813
    style APP     fill:#FCE4EC,stroke:#E5482E,color:#1A1813
    style PIPELINE fill:#FFFFFF,stroke:#C8C0AD,color:#1A1813
```

## Quickstart

```bash
uv sync --extra dev       # instala dependências + pytest
uv run pytest             # testes offline
uv run python -m src.pipeline --discover-days 3 --date $(date +%Y-%m-%d)
uv run python src/app.py  # app web em http://localhost:8050
```

## Estrutura

```
src/scrape/sofascore.py   — scraper SofaScore (discovery + fetch + parse)
src/parse/stoppages.py    — detecção de paradas (hidratação, VAR, lesão)
src/features/             — janelamento 5 min pré/pós momentum
src/analysis/             — estatísticas descritivas + IC bootstrap
src/viz/charts.py         — builders Plotly + mini-SVG dos cards
src/app.py                — aplicação Dash (gráficos interativos)
scripts/daily.sh          — runner diário (macOS, cron/launchd)
```

## Script diário (macOS)

```bash
# Execução manual
uv run python -m src.pipeline --discover-days 1 --date $(date +%Y-%m-%d)

# Cron (todo dia às 09:00)
0 9 * * * cd /caminho/para/wc-rafael && uv run python -m src.pipeline \
  --discover-days 1 --date $(date +%Y-%m-%d) >> logs/daily.log 2>&1
```
