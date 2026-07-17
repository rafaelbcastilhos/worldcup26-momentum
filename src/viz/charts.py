"""Plotly chart builders + SVG mini-chart generator for the Dash app.

Paleta canônica — todos os gráficos compartilham estas constantes:

  Casa (azul)      #1D9BF0  ↔  Pausa de Hidratação  (mesmo hue)
  Visitante (âmbar) #F5A623 ↔  VAR                  (mesmo hue)
  Destaque negativo #E5482E  (Δ ruins para o líder)
  Destaque positivo #16A34A

As áreas preenchidas usam versões transparentes dessas cores. As linhas de
grade e zero são sutis, sempre a partir de _INK com baixa opacidade.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import polars as pl

# ── paleta canônica ──────────────────────────────────────────────────────────

# Cores primárias dos dois times/tipos de parada
COLOR_HOME = "#1D9BF0"        # azul   — casa + hidratação
COLOR_AWAY = "#F5A623"        # âmbar  — visitante + VAR
COLOR_NEG  = "#E5482E"        # vermelho — Δ negativo para o líder
COLOR_POS  = "#16A34A"        # verde  — Δ positivo para o líder
COLOR_INK  = "#1A1813"        # quase-preto — textos e linhas estruturais

# Áreas preenchidas dos gráficos de momentum
FILL_HOME  = "rgba(29,155,240,0.15)"   # #1D9BF0 a 15%
FILL_AWAY  = "rgba(245,166,35,0.15)"   # #F5A623 a 15%

# Linhas de estrutura
ZERO_LINE  = "rgba(26,24,19,0.20)"     # zero / referência
GRID_LINE  = "rgba(26,24,19,0.06)"     # grade dos eixos
HALF_LINE  = "rgba(26,24,19,0.10)"     # linha do intervalo
MOM_LINE   = "rgba(26,24,19,0.55)"     # curva de momentum

# Mesmas cores para os marcadores de paradas nos mini-SVGs
STOPPAGE_COLORS = {
    "hydration":       COLOR_HOME,
    "var":             COLOR_AWAY,
    "injury_huddle":   COLOR_NEG,
    "injury_no_huddle": "#FF8C6B",
}

STOPPAGE_LABELS = {
    "hydration":       "Pausa de Hidratação",
    "var":             "VAR",
    "injury_huddle":   "Lesão (com substituição)",
    "injury_no_huddle":"Lesão (sem substituição)",
}

# Paleta exportada para a app (legenda, badges, etc.)
PALETTE = {
    "home":       COLOR_HOME,
    "away":       COLOR_AWAY,
    "negative":   COLOR_NEG,
    "positive":   COLOR_POS,
    "fill_home":  FILL_HOME,
    "fill_away":  FILL_AWAY,
    "zero_line":  ZERO_LINE,
    "grid":       GRID_LINE,
    "ink":        COLOR_INK,
}

ACTIVE_TYPES = ("hydration", "var")

_FONT = "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


# ── layout base ──────────────────────────────────────────────────────────────

def _base_layout(**overrides) -> dict:
    base = {
        "font":         {"family": _FONT, "size": 13, "color": COLOR_INK},
        "plot_bgcolor": "#FFFFFF",
        "paper_bgcolor":"#FFFFFF",
        "margin":       {"l": 60, "r": 40, "t": 60, "b": 50},
        "hovermode":    "x unified",
    }
    base.update(overrides)
    return base


def _xaxis(**kw) -> dict:
    return {"gridcolor": GRID_LINE, "tickfont": {"size": 11}, "linecolor": GRID_LINE,
            "zerolinecolor": ZERO_LINE, **kw}


def _yaxis(**kw) -> dict:
    return {"gridcolor": GRID_LINE, "tickfont": {"size": 11}, "linecolor": GRID_LINE,
            "zeroline": True, "zerolinewidth": 2, "zerolinecolor": ZERO_LINE, **kw}


# ── momentum_chart ───────────────────────────────────────────────────────────

def momentum_chart(
    series: list[list[float]],
    stoppages: list[list],
    goals: list[dict[str, Any]],
    home: str,
    away: str,
    home_score: int | None,
    away_score: int | None,
) -> go.Figure:
    """Curva de momentum da partida com marcadores de paradas e gols."""
    if not series:
        return go.Figure(layout=_base_layout(height=360))

    minutes = [p[0] for p in series]
    values  = [p[1] for p in series]
    pos_v   = [max(v, 0) for v in values]
    neg_v   = [min(v, 0) for v in values]

    fig = go.Figure()

    # Áreas preenchidas — mesmas cores da paleta
    fig.add_trace(go.Scatter(
        x=minutes, y=pos_v, fill="tozeroy", mode="none",
        fillcolor=FILL_HOME, name=home, showlegend=False, hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=minutes, y=neg_v, fill="tozeroy", mode="none",
        fillcolor=FILL_AWAY, name=away, showlegend=False, hoverinfo="skip",
    ))
    # Curva de momentum
    fig.add_trace(go.Scatter(
        x=minutes, y=values, mode="lines",
        line={"color": MOM_LINE, "width": 1.8},
        name="Momentum",
        hovertemplate="min %{x}: %{y:.1f}<extra></extra>",
    ))

    # Marcadores de paradas
    seen: set[str] = set()
    for s in stoppages:
        if len(s) < 2:
            continue
        minute, stype = s[0], s[1]
        color = STOPPAGE_COLORS.get(stype, "#aaa")
        label = STOPPAGE_LABELS.get(stype, stype)
        fig.add_vline(
            x=minute, line_dash="dot", line_color=color, line_width=2.5,
            annotation_text=label if stype not in seen else "",
            annotation_position="top right",
            annotation_font_size=10, annotation_font_color=color,
        )
        seen.add(stype)

    # Gols
    for g in goals:
        m, is_home = g["m"], g["h"]
        kind = g.get("k", "")
        icon = "⚽" if kind not in ("pen", "og") else ("🟡" if kind == "pen" else "🔴")
        fig.add_annotation(
            x=m, y=0, text=icon, showarrow=False,
            font={"size": 13}, yshift=14 if is_home else -18,
            hovertext=f"{g.get('who','')} {g.get('sc','')}".strip(),
        )

    # Linha do intervalo
    fig.add_vline(x=45, line_dash="solid", line_color=HALF_LINE, line_width=1)

    # Rótulos dos times
    max_y = max(abs(v) for v in values) if values else 10
    fig.add_annotation(x=2, y= max_y * 0.82, text=f"<b>{home}</b>",
                       showarrow=False, font={"size": 11, "color": COLOR_HOME}, xanchor="left")
    fig.add_annotation(x=2, y=-max_y * 0.82, text=f"<b>{away}</b>",
                       showarrow=False, font={"size": 11, "color": COLOR_AWAY}, xanchor="left")

    hs  = home_score if home_score is not None else 0
    aws = away_score if away_score is not None else 0

    fig.update_layout(**_base_layout(
        title={"text": f"<b>{home}  {hs} – {aws}  {away}</b>",
               "x": 0.5, "xanchor": "center", "font": {"size": 15}},
        xaxis=_xaxis(title="Minuto"),
        yaxis=_yaxis(title="Momentum"),
        showlegend=False,
        height=360,
        margin={"l": 50, "r": 30, "t": 56, "b": 44},
    ))
    return fig


# ── effect_bar_chart (lollipop) ───────────────────────────────────────────────

def effect_bar_chart(effects: list[dict]) -> go.Figure:
    """Lollipop: variação média de Δ Momentum por tipo de parada (time líder)."""
    active = sorted(
        [e for e in effects if e["stoppage_type"] in ACTIVE_TYPES],
        key=lambda e: e["mean_delta"],
    )
    if not active:
        return go.Figure(layout=_base_layout(height=280))

    n = len(active)
    fig = go.Figure()

    for i, e in enumerate(active):
        stype = e["stoppage_type"]
        mean, ci_lo, ci_hi = e["mean_delta"], e["ci_lo"], e["ci_hi"]
        ns, nm = e["n"], e["n_matches"]
        color = STOPPAGE_COLORS[stype]
        label = STOPPAGE_LABELS[stype]

        # Stem 0 → mean
        fig.add_trace(go.Scatter(
            x=[0, mean], y=[i, i], mode="lines",
            line={"color": color, "width": 4},
            showlegend=False, hoverinfo="skip",
        ))
        # CI bar
        fig.add_trace(go.Scatter(
            x=[ci_lo, ci_hi], y=[i, i], mode="lines",
            line={"color": f"rgba(26,24,19,.35)", "width": 2},
            showlegend=False, hoverinfo="skip",
        ))
        for xv in (ci_lo, ci_hi):
            fig.add_trace(go.Scatter(
                x=[xv, xv], y=[i - .18, i + .18], mode="lines",
                line={"color": "rgba(26,24,19,.35)", "width": 2},
                showlegend=False, hoverinfo="skip",
            ))
        # Círculo
        fig.add_trace(go.Scatter(
            x=[mean], y=[i], mode="markers", name=label,
            marker={"color": color, "size": 18, "line": {"width": 2.5, "color": "white"}},
            showlegend=False,
            hovertemplate=(
                f"<b>{label}</b><br>"
                f"Δ médio: <b>{mean:.2f}</b><br>"
                f"IC 95%: [{ci_lo:.2f}, {ci_hi:.2f}]<br>"
                f"Observações: {ns} em {nm} partidas<extra></extra>"
            ),
        ))
        fig.add_annotation(x=mean, y=i + .38, text=f"<b>{mean:.1f}</b>",
                           showarrow=False, font={"size": 14, "color": color, "family": _FONT},
                           xanchor="center", yanchor="bottom")
        fig.add_annotation(x=mean, y=i - .38, text=f"n = {ns}",
                           showarrow=False, font={"size": 10, "color": "#999", "family": _FONT},
                           xanchor="center", yanchor="top")

    fig.add_vline(x=0, line_color=ZERO_LINE, line_width=2)

    fig.update_layout(**_base_layout(
        title={"text": "Variação média de Δ Momentum",
               "subtitle": {"text": "Time líder pré-parada · 5 min depois vs 5 min antes · IC 95%"},
               "x": 0.5, "xanchor": "center", "font": {"size": 15}},
        xaxis=_xaxis(title="Δ Momentum", zeroline=False),
        yaxis={"tickvals": list(range(n)),
               "ticktext": [STOPPAGE_LABELS[e["stoppage_type"]] for e in active],
               "tickfont": {"size": 13}, "gridcolor": "rgba(0,0,0,0)",
               "range": [-.8, n - .2]},
        showlegend=False, height=280,
        margin={"l": 200, "r": 50, "t": 64, "b": 52},
        hovermode="closest",
    ))
    return fig


# ── pre_post_scatter (substitui scatter_delta_by_minute) ─────────────────────

def scatter_delta_by_minute(df: pl.DataFrame) -> go.Figure:
    """Scatter pré vs pós momentum — cada ponto é uma parada do time líder.

    Eixo x: momentum médio nos 5 min *antes* da parada.
    Eixo y: momentum médio nos 5 min *depois* da parada.
    Linha diagonal (y = x): sem mudança — pontos abaixo = líder perdeu ritmo.
    """
    if df is None or df.is_empty():
        return go.Figure(layout=_base_layout(height=280))

    needed = ["momentum_delta", "momentum_pre_5min_mean", "clock_minute"]
    base = (
        df.drop_nulls(needed)
          .filter(pl.col("momentum_pre_5min_mean") > 0)
          .filter(pl.col("stoppage_type").is_in(list(ACTIVE_TYPES)))
          .with_columns(
              (pl.col("momentum_pre_5min_mean") + pl.col("momentum_delta"))
              .alias("momentum_post")
          )
    )
    if base.is_empty():
        return go.Figure(layout=_base_layout(height=280))

    # Reference diagonal (y = x): range from min pre to max pre
    all_pre  = base["momentum_pre_5min_mean"].to_list()
    all_post = base["momentum_post"].to_list()
    axis_min = min(min(all_pre), min(all_post)) - 5
    axis_max = max(max(all_pre), max(all_post)) + 5

    fig = go.Figure()

    # Diagonal reference line y = x
    fig.add_shape(
        type="line",
        x0=axis_min, y0=axis_min, x1=axis_max, y1=axis_max,
        line={"color": ZERO_LINE, "width": 1.5, "dash": "dot"},
        layer="below",
    )
    fig.add_annotation(
        x=axis_max, y=axis_max,
        text="<i>sem mudança</i>",
        showarrow=False,
        font={"size": 10, "color": "rgba(26,24,19,0.35)", "family": _FONT},
        xanchor="right", yanchor="bottom",
    )

    for stype in ACTIVE_TYPES:
        sub  = base.filter(pl.col("stoppage_type") == stype)
        if sub.is_empty():
            continue
        color = STOPPAGE_COLORS[stype]
        label = STOPPAGE_LABELS[stype]
        rows  = sub.to_dicts()

        fig.add_trace(go.Scatter(
            x=[r["momentum_pre_5min_mean"] for r in rows],
            y=[r["momentum_post"]          for r in rows],
            mode="markers",
            marker={
                "color": color, "size": 8, "opacity": 0.65,
                "line": {"width": 1, "color": "white"},
            },
            name=label,
            customdata=[
                (f"{r.get('team','?')} vs {r.get('opponent','?')}",
                 r["momentum_delta"],
                 int(r.get("clock_minute", 0)))
                for r in rows
            ],
            hovertemplate=(
                f"<b>{label}</b><br>"
                "Pré: <b>%{x:.1f}</b>  →  Pós: <b>%{y:.1f}</b><br>"
                "Δ: <b>%{customdata[1]:.1f}</b>  ·  min %{customdata[2]}'<br>"
                "%{customdata[0]}<extra></extra>"
            ),
        ))

    fig.update_layout(**_base_layout(
        title={
            "text": "Momentum antes vs. depois da parada<br>"
                    "<sup style='color:#888;font-size:11px'>"
                    "Cada ponto = 1 parada do time líder · abaixo da diagonal = perdeu ritmo"
                    "</sup>",
            "x": 0.5, "xanchor": "center", "font": {"size": 15},
        },
        xaxis=_xaxis(title="Momentum pré (5 min antes)", range=[axis_min, axis_max]),
        yaxis=_yaxis(title="Momentum pós (5 min depois)", range=[axis_min, axis_max], zeroline=False),
        legend={
            "orientation": "h",
            "yanchor": "top", "y": -0.32,
            "xanchor": "center", "x": 0.5,
            "font": {"size": 12},
            "itemsizing": "constant",
        },
        height=320,
        margin={"l": 60, "r": 40, "t": 84, "b": 120},
        hovermode="closest",
    ))
    return fig


# ── distribution_chart ────────────────────────────────────────────────────────

def distribution_chart(df: pl.DataFrame, stoppage_type: str) -> go.Figure:
    """Histograma de Δ Momentum para um tipo de parada (time líder)."""
    sub = (
        df.drop_nulls(["momentum_delta", "momentum_pre_5min_mean"])
          .filter(pl.col("momentum_pre_5min_mean") > 0)
          .filter(pl.col("stoppage_type") == stoppage_type)
    )
    if sub.is_empty():
        return go.Figure(layout=_base_layout(height=260))

    values    = sub["momentum_delta"].to_list()
    color     = STOPPAGE_COLORS.get(stoppage_type, "#aaa")
    label     = STOPPAGE_LABELS.get(stoppage_type, stoppage_type)
    mean_val  = sum(values) / len(values)

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=values, nbinsx=22,
        marker={"color": color, "opacity": 0.75,
                "line": {"width": 0.5, "color": "white"}},
        name=label,
        hovertemplate="Δ: %{x:.1f}<br>Contagem: %{y}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color=ZERO_LINE, line_width=2)
    fig.add_shape(
        type="line", x0=mean_val, x1=mean_val, y0=0, y1=1,
        xref="x", yref="paper",
        line={"dash": "dash", "color": color, "width": 2},
    )
    fig.add_annotation(
        x=mean_val, y=1.0, xref="x", yref="paper",
        text=f"média: {mean_val:.1f}",
        showarrow=False,
        font={"size": 11, "color": color},
        xanchor="left", yanchor="bottom",
        yshift=4,
    )

    fig.update_layout(**_base_layout(
        title={"text": f"Distribuição de Δ Momentum — <b>{label}</b><br>"
                       f"<sup>Apenas o time líder pré-parada · n={len(values)}</sup>",
               "x": 0.5, "xanchor": "center", "font": {"size": 13}},
        xaxis=_xaxis(title="Δ Momentum"),
        yaxis=_yaxis(title="Contagem"),
        showlegend=False, height=260,
        margin={"l": 60, "r": 40, "t": 72, "b": 48},
    ))
    return fig


# ── trend_chart (compatibilidade) ────────────────────────────────────────────

def trend_chart(snapshots: list[dict]) -> go.Figure:
    return go.Figure(layout=_base_layout(height=280))


# ── mini_momentum_svg ─────────────────────────────────────────────────────────

_SVG_COLORS = {
    "home_fill": "rgba(29,155,240,0.45)",    # COLOR_HOME a 45%
    "away_fill": "rgba(245,166,35,0.40)",    # COLOR_AWAY a 40%
    "line":      "rgba(26,24,19,0.50)",      # MOM_LINE
    "zero":      "rgba(26,24,19,0.18)",      # ZERO_LINE
    "hydration": COLOR_HOME,
    "var":       COLOR_AWAY,
    "injury_huddle":   COLOR_NEG,
    "injury_no_huddle": "#FF8C6B",
}


def mini_momentum_svg(
    series: list[list[float]],
    stoppages: list[list],
    *,
    width: int = 280,
    height: int = 70,
) -> str:
    """SVG puro inline para o mini-gráfico de momentum em cada card de partida."""
    if not series:
        return (
            f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg">'
            f'<line x1="0" y1="{height // 2}" x2="{width}" y2="{height // 2}" '
            f'stroke="{_SVG_COLORS["zero"]}" stroke-width="1"/></svg>'
        )

    minutes  = [p[0] for p in series]
    values   = [p[1] for p in series]
    min_m, max_m = min(minutes), max(minutes)
    max_abs  = max(max(abs(v) for v in values), 0.1)
    span_m   = max_m - min_m or 1
    px_pad, py_pad = 2, 3
    W = width  - 2 * px_pad
    H = height - 2 * py_pad

    def nx(m: float) -> float:
        return px_pad + (m - min_m) / span_m * W

    def ny(v: float) -> float:
        return py_pad + H / 2 - (v / max_abs) * (H / 2 * 0.90)

    zero_y = ny(0)

    # Área positiva (casa)
    pos_top = [(nx(m), min(ny(v), zero_y)) for m, v in zip(minutes, values)]
    pos_poly = [(pos_top[0][0], zero_y)] + pos_top + [(pos_top[-1][0], zero_y)]

    # Área negativa (visitante)
    neg_bot = [(nx(m), max(ny(v), zero_y)) for m, v in zip(minutes, values)]
    neg_poly = [(neg_bot[0][0], zero_y)] + neg_bot + [(neg_bot[-1][0], zero_y)]

    def pts(poly: list[tuple[float, float]]) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in poly)

    parts: list[str] = []

    parts.append(f'<polygon points="{pts(pos_poly)}" fill="{_SVG_COLORS["home_fill"]}" stroke="none"/>')
    parts.append(f'<polygon points="{pts(neg_poly)}" fill="{_SVG_COLORS["away_fill"]}" stroke="none"/>')

    line_pts = " ".join(f"{nx(m):.1f},{ny(v):.1f}" for m, v in zip(minutes, values))
    parts.append(
        f'<polyline points="{line_pts}" fill="none" '
        f'stroke="{_SVG_COLORS["line"]}" stroke-width="0.9"/>'
    )
    parts.append(
        f'<line x1="{px_pad}" y1="{zero_y:.1f}" x2="{width - px_pad}" y2="{zero_y:.1f}" '
        f'stroke="{_SVG_COLORS["zero"]}" stroke-width="1"/>'
    )

    for s in stoppages:
        if len(s) < 2:
            continue
        minute, stype = float(s[0]), str(s[1])
        if not (min_m <= minute <= max_m):
            continue
        x     = nx(minute)
        color = _SVG_COLORS.get(stype, "#aaa")
        parts.append(
            f'<line x1="{x:.1f}" y1="{py_pad}" x2="{x:.1f}" y2="{height - py_pad}" '
            f'stroke="{color}" stroke-width="1.5" stroke-dasharray="3,2.5"/>'
        )

    inner = "\n  ".join(parts)
    return (
        f'<svg width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;overflow:visible">'
        f'\n  {inner}\n</svg>'
    )
