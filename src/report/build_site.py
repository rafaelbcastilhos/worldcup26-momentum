"""Build static HTML report from committed processed data → site/index.html.

Run locally:  uv run python -m src.report.build_site
In CI:        same command, then GitHub Actions deploys site/ to Pages.

Reads only from data/processed/ — never scrapes.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from src.analysis.descriptive import effect_by_type, load_processed
from src.paths import PROCESSED, SITE, STOPPAGES_PARQUET
from src.viz.charts import (
    distribution_chart,
    effect_bar_chart,
    mini_momentum_svg,
    scatter_delta_by_minute,
)

_ACCENT = "#E5482E"
_INK = "#1A1813"
_BG = "#F0EDE8"
_CARD = "#FFFFFF"
_FONT = "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


# ── helpers ───────────────────────────────────────────────────────────────────

def _fig_div(fig) -> str:
    """Plotly figure → embeddable <div>. Plotly.js is loaded once in <head>."""
    return fig.to_html(
        include_plotlyjs=False,
        full_html=False,
        config={"displayModeBar": False},
    )


def _svg_uri(svg_str: str) -> str:
    b64 = base64.b64encode(svg_str.encode()).decode()
    return f"data:image/svg+xml;base64,{b64}"


def _fmt_date(ts: int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%d/%m/%Y")


def _stage_label(stage: str | None) -> str:
    if not stage:
        return ""
    s = stage.lower().strip()
    if s.isdigit():
        return f"{s}ª RODADA"
    _map = {
        "round of 32": "Rodada de 32", "round of 16": "Oitavas de final",
        "quarter-finals": "Quartas de final", "semi-finals": "Semifinais",
        "final": "Final", "third place play-off": "3º lugar",
        "third place": "3º lugar",
    }
    if "group" in s:
        return f"Grupo {s.replace('group', '').strip().upper()}"
    return _map.get(s, stage)


# ── match cards ───────────────────────────────────────────────────────────────

def _match_cards(momentum_data: list[dict]) -> str:
    if not momentum_data:
        return "<p style='color:#9CA3AF;font-size:14px'>Nenhuma partida disponível ainda.</p>"

    sorted_matches = sorted(momentum_data, key=lambda m: m.get("ts") or 0)
    cards: list[str] = []

    for i, m in enumerate(sorted_matches):
        home = m.get("home") or "?"
        away = m.get("away") or "?"
        hs, aws = m.get("hs"), m.get("as")
        score = f"{hs}–{aws}" if hs is not None else ""
        date_str = _fmt_date(m.get("ts"))
        stage = _stage_label(m.get("stage"))
        num = f"M{i + 1:02d}"
        meta = " · ".join(filter(None, [stage, date_str]))

        svg = mini_momentum_svg(m.get("series") or [], m.get("stoppages") or [],
                                width=280, height=68)

        score_row = (
            f'<div style="font-size:11px;font-weight:600;color:#9CA3AF;'
            f'text-align:right;margin-top:6px">{score}</div>'
            if score else ""
        )
        cards.append(f"""
        <div style="background:{_CARD};border-radius:10px;padding:14px;
                    box-shadow:0 1px 3px rgba(0,0,0,.06),0 2px 8px rgba(0,0,0,.04);
                    border:1px solid #EDE8DF">
          <div style="font-size:11px;color:#9CA3AF;margin-bottom:10px;font-weight:400">
            {num}{f"  ·  {meta}" if meta else ""}
          </div>
          <div style="margin-bottom:10px">
            <div style="font-size:13px;font-weight:700;color:{_INK};
                        margin-bottom:3px;line-height:1.2">{home}</div>
            <div style="font-size:13px;font-weight:400;color:#777;
                        line-height:1.2">{away}</div>
          </div>
          <img src="{_svg_uri(svg)}" alt=""
               style="width:100%;height:68px;object-fit:contain;display:block">
          {score_row}
        </div>""")

    return (
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,'
        'minmax(240px,1fr));gap:14px">'
        + "".join(cards)
        + "</div>"
    )


# ── HTML page ─────────────────────────────────────────────────────────────────

def _page(
    n_matches: int,
    n_stoppages: int,
    effects_div: str,
    scatter_div: str,
    dist_hyd_div: str,
    dist_var_div: str,
    cards_html: str,
    updated: str,
) -> str:
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pausas de jogo e momentum — Copa do Mundo 2026</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap"
        rel="stylesheet">
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: {_BG};
      font-family: {_FONT};
      color: {_INK};
      min-height: 100vh;
    }}
    .container {{
      max-width: 1120px;
      margin: 0 auto;
      padding: 48px 24px 64px;
    }}
    .chart-card {{
      background: {_CARD};
      border-radius: 12px;
      padding: 20px 22px;
      box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.04);
    }}
    .two-col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 20px;
    }}
    .section-label {{
      font-size: 13px;
      font-weight: 500;
      color: #9CA3AF;
      margin-bottom: 12px;
    }}
    hr.divider {{
      border: none;
      border-top: 1px solid #E5E0D8;
      margin: 48px 0 36px;
    }}
    footer {{
      border-top: 1px solid #E5E0D8;
      margin-top: 48px;
      padding-top: 20px;
      font-size: 12px;
      color: #B0A898;
    }}
    @media (max-width: 700px) {{
      .two-col {{ grid-template-columns: 1fr; }}
      .container {{ padding: 32px 16px 48px; }}
    }}
  </style>
</head>
<body>
<div class="container">

  <!-- intro -->
  <div style="margin-bottom:48px">
    <h1 style="font-size:24px;font-weight:700;margin-bottom:6px;line-height:1.25">
      Pausas de jogo e momentum
    </h1>
    <p style="font-size:13px;color:#9CA3AF;margin-bottom:28px;font-weight:400">
      Copa do Mundo 2026 · atualizado em {updated}
    </p>
    <p style="font-size:15px;line-height:1.75;color:#4B5563;margin-bottom:14px">
      Em <strong style="color:{_INK}">{n_matches} partidas analisadas</strong>, detectamos
      <strong style="color:{_INK}">{n_stoppages} pausas de jogo</strong> — hidratação obrigatória
      e revisões de VAR. A pergunta é simples: quando uma equipe está no controle, a interrupção
      quebra o ritmo de quem domina?
    </p>
    <div style="border-left:3px solid #E5E7EB;padding-left:18px">
      <p style="font-size:13.5px;line-height:1.7;color:#6B7280">
        O SofaScore atribui um índice de momentum minuto a minuto, oscilando entre −100 e +100.
        Para cada parada, medimos a média dos 5 minutos antes e dos 5 depois — excluindo o minuto exato.
        O <strong>Δ Momentum</strong> é a diferença pós menos pré, sempre da perspectiva do time que
        estava na frente. Um Δ negativo significa que a parada interrompeu quem dominava.
      </p>
    </div>
  </div>

  <!-- main charts -->
  <div class="two-col">
    <div class="chart-card">{effects_div}</div>
    <div class="chart-card">{scatter_div}</div>
  </div>

  <!-- distribution -->
  <div style="margin-bottom:28px">
    <div class="section-label">Distribuição por tipo de parada</div>
    <div class="two-col" style="margin-bottom:0">
      <div class="chart-card">{dist_hyd_div}</div>
      <div class="chart-card">{dist_var_div}</div>
    </div>
  </div>

  <hr class="divider">

  <!-- match grid -->
  <div class="section-label">Partidas</div>
  {cards_html}

  <footer>
    Fonte: SofaScore — janelas de 5 min pré e pós parada —
    IC 95% via bootstrap clusterizado por partida
  </footer>

</div>
</body>
</html>"""


# ── build ─────────────────────────────────────────────────────────────────────

_EMPTY_HTML = (
    "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
    "<title>Copa do Mundo 2026 — Momentum</title>"
    "<body style='font-family:sans-serif;max-width:640px;margin:60px auto;color:#1A1813'>"
    "<h1 style='font-size:22px;margin-bottom:16px'>Copa do Mundo 2026 — Momentum em Paradas</h1>"
    "<p style='color:#6B7280'>Nenhum dado disponível ainda. Volte após a próxima partida.</p>"
)


def build() -> str:
    """Generate site/index.html. Returns the path written."""
    SITE.mkdir(parents=True, exist_ok=True)
    out = SITE / "index.html"
    updated = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    if not STOPPAGES_PARQUET.exists():
        out.write_text(_EMPTY_HTML, encoding="utf-8")
        return str(out)

    df = load_processed()
    if df.is_empty():
        out.write_text(_EMPTY_HTML, encoding="utf-8")
        return str(out)

    effects = effect_by_type(df)
    n_matches = int(df["match_id"].n_unique())
    n_stoppages = int(df["stoppage_id"].n_unique())

    momentum_path = PROCESSED / "momentum.json"
    momentum_data: list[dict] = (
        json.loads(momentum_path.read_text(encoding="utf-8"))
        if momentum_path.exists() else []
    )

    page = _page(
        n_matches=n_matches,
        n_stoppages=n_stoppages,
        effects_div=_fig_div(effect_bar_chart(effects)),
        scatter_div=_fig_div(scatter_delta_by_minute(df)),
        dist_hyd_div=_fig_div(distribution_chart(df, "hydration")),
        dist_var_div=_fig_div(distribution_chart(df, "var")),
        cards_html=_match_cards(momentum_data),
        updated=updated,
    )
    out.write_text(page, encoding="utf-8")
    return str(out)


if __name__ == "__main__":
    print("[site]", build())
