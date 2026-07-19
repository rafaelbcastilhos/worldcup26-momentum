"""Dash web app — WC2026 Análise de Momentum em Paradas de Jogo."""

from __future__ import annotations

import base64
import json
from collections import defaultdict
from datetime import datetime, timezone

import polars as pl
from dash import ALL, Dash, Input, Output, State, callback, dcc, html, no_update
from dash import ctx as dash_ctx
from plotly import graph_objects as go

from src.analysis.descriptive import effect_by_type, load_processed
from src.paths import PROCESSED, STOPPAGES_PARQUET
from src.snapshot import load_all_snapshots
from src.viz.charts import (
    ACTIVE_TYPES,
    PALETTE,
    STOPPAGE_COLORS,
    STOPPAGE_LABELS,
    distribution_chart,
    effect_bar_chart,
    mini_momentum_svg,
    momentum_chart,
    scatter_delta_by_minute,
)

# ── paleta ────────────────────────────────────────────────────────────────────
_ACCENT = "#E5482E"
_INK = "#1A1813"
_BG = "#F0EDE8"
_CARD_BG = "#FFFFFF"
_DARK = "#1A1813"
_FONT = "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"

# ── stage helpers ─────────────────────────────────────────────────────────────

_STAGE_PT = {
    "group a": "GRUPO A", "group b": "GRUPO B", "group c": "GRUPO C",
    "group d": "GRUPO D", "group e": "GRUPO E", "group f": "GRUPO F",
    "group g": "GRUPO G", "group h": "GRUPO H", "group i": "GRUPO I",
    "group j": "GRUPO J", "group k": "GRUPO K", "group l": "GRUPO L",
    "round of 32": "RODADA DE 32", "round of 16": "OITAVAS DE FINAL",
    "quarter-finals": "QUARTAS DE FINAIS", "quarterfinals": "QUARTAS DE FINAIS",
    "semi-finals": "SEMI FINAIS", "semifinals": "SEMI FINAIS",
    "final": "FINAL", "third place play-off": "DISPUTA DO 3º LUGAR",
    "third place": "DISPUTA DO 3º LUGAR",
}

_KNOCKOUT_KEYWORDS = ("round of", "quarter", "semi", "final", "third", "play-off", "playoff")


def _stage_label_pt(stage: str | None) -> str:
    if not stage:
        return "SEM FASE"
    s = stage.lower().strip()
    if s.isdigit():
        return f"{s}ª RODADA"
    return _STAGE_PT.get(s, stage.upper())


def _is_group_stage(stage: str | None) -> bool:
    return stage is not None and "group" in stage.lower()


def _is_knockout(stage: str | None) -> bool:
    if not stage:
        return False
    s = stage.lower()
    return any(k in s for k in _KNOCKOUT_KEYWORDS)


def _stage_sort_key(stage: str | None) -> tuple:
    if not stage:
        return (99, 0)
    s = stage.lower().strip()
    # Rodadas numeradas (fase de grupos): ordem decrescente (3ª antes de 2ª antes de 1ª)
    if s.isdigit():
        return (6, -int(s))
    # Fases eliminatórias: do mais recente para o mais antigo
    if s == "final":
        return (0, 0)
    if "third" in s or "play-off" in s or "play_off" in s:
        return (1, 0)
    if "semi" in s:
        return (2, 0)
    if "quarter" in s:
        return (3, 0)
    if "16" in s:
        return (4, 0)
    if "32" in s:
        return (5, 0)
    if "group" in s:
        return (7, s.replace("group", "").strip())
    return (8, s)


# ── data loading ──────────────────────────────────────────────────────────────

def _load_df() -> pl.DataFrame | None:
    return load_processed() if STOPPAGES_PARQUET.exists() else None


def _load_momentum() -> list[dict]:
    p = PROCESSED / "momentum.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def _svg_img(svg_str: str, width: int, height: int) -> html.Img:
    """Embed an SVG string as a base64 data-URI <img> (Dash 4 compatible)."""
    b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
    return html.Img(
        src=f"data:image/svg+xml;base64,{b64}",
        width=width, height=height,
        style={"display": "block"},
    )


def _fmt_date(ts: int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")


# ── UI building blocks ────────────────────────────────────────────────────────

def _card(children, style_extra: dict | None = None) -> html.Div:
    s = {
        "background": _CARD_BG, "borderRadius": "12px", "padding": "20px 22px",
        "boxShadow": "0 1px 3px rgba(0,0,0,.07), 0 4px 16px rgba(0,0,0,.04)",
    }
    if style_extra:
        s.update(style_extra)
    return html.Div(children, style=s)


def _section_label(text: str) -> html.Div:
    return html.Div(text, style={
        "fontSize": "13px", "fontWeight": "500",
        "color": "#9CA3AF", "marginBottom": "12px",
    })


def _intro_block(n_matches: int, n_stoppages: int) -> html.Div:
    """Cabeçalho editorial — substitui os stat cards e o explainer estruturado."""
    p = {"margin": "0 0 14px", "lineHeight": "1.75", "color": "#4B5563", "fontSize": "15px"}
    s = {"fontWeight": "600", "color": _INK}
    note_p = {"margin": "0 0 10px", "lineHeight": "1.7", "color": "#6B7280", "fontSize": "13.5px"}
    return html.Div(
        style={"marginBottom": "48px"},
        children=[
            html.H1(
                "As pausas para hidratação realmente quebram o ritmo?",
                style={"fontSize": "24px", "fontWeight": "700", "color": _INK,
                       "margin": "0 0 6px", "lineHeight": "1.25"},
            ),
            html.P(
                "Copa do Mundo 2026",
                style={"fontSize": "13px", "color": "#9CA3AF", "margin": "0 0 28px", "fontWeight": "400"},
            ),
            html.P([
                f"Em {n_matches} partidas analisadas, detectamos ",
                html.Strong(f"{n_stoppages} pausas de jogo", style=s),
                ", hidratação obrigatória e revisões de VAR. A pergunta é simples: "
                "quando uma equipe está no controle, a interrupção quebra o ritmo de quem domina?",
            ], style=p),
            html.Div(
                style={
                    "borderLeft": "3px solid #E5E7EB",
                    "paddingLeft": "18px", "marginTop": "4px",
                },
                children=[
                    html.P([
                        "O SofaScore atribui um índice de momentum minuto a minuto, oscilando entre −100 e +100. "
                        "Para cada parada, medimos a média dos 5 minutos antes e dos 5 depois, excluindo o minuto exato. "
                        "O ", html.Strong("Δ Momentum", style={**s, "fontSize": "13.5px"}),
                        " é a diferença pós menos pré, sempre da perspectiva do time que estava na frente. "
                        "Um Δ negativo significa que a parada interrompeu quem dominava.",
                    ], style={**note_p, "marginBottom": "0"}),
                ],
            ),
        ],
    )


def _stoppage_badge(stype: str) -> html.Span:
    return html.Span(STOPPAGE_LABELS.get(stype, stype), style={
        "background": STOPPAGE_COLORS.get(stype, "#999"), "color": "white",
        "borderRadius": "4px", "padding": "2px 8px",
        "fontSize": "11px", "fontWeight": "700", "whiteSpace": "nowrap",
    })


# ── match grid components ─────────────────────────────────────────────────────

def _legend_bar() -> html.Div:
    def _area_chip(color: str, label: str) -> html.Div:
        return html.Div(style={"display": "flex", "alignItems": "center", "gap": "6px"}, children=[
            html.Div(style={
                "width": "22px", "height": "12px", "borderRadius": "3px",
                "background": color, "flexShrink": "0",
            }),
            html.Span(label, style={"fontSize": "11px", "fontWeight": "600",
                                     "color": "#666", "letterSpacing": ".06em"}),
        ])

    def _line_chip(color: str, label: str) -> html.Div:
        return html.Div(style={"display": "flex", "alignItems": "center", "gap": "6px"}, children=[
            html.Div(style={
                "width": "18px", "height": "0", "borderTop": f"2px dashed {color}",
                "flexShrink": "0", "marginTop": "1px",
            }),
            html.Span(label, style={"fontSize": "11px", "fontWeight": "600",
                                     "color": "#666", "letterSpacing": ".06em"}),
        ])

    return html.Div(
        style={
            "display": "flex", "alignItems": "center", "gap": "18px",
            "flexWrap": "wrap", "marginBottom": "18px",
        },
        children=[
            _area_chip(PALETTE["fill_home"], "Casa na frente"),
            _area_chip(PALETTE["fill_away"], "Visitante na frente"),
            _line_chip(PALETTE["home"], "Hidratação"),
            _line_chip(PALETTE["away"], "VAR"),
        ],
    )


def _filter_buttons() -> html.Div:
    btn_base = {
        "padding": "6px 16px", "borderRadius": "4px", "cursor": "pointer",
        "fontSize": "13px", "fontWeight": "500",
        "border": "1px solid #D1CBC0", "background": "transparent",
        "color": "#6B7280",
    }
    btn_active = {**btn_base, "background": _INK, "color": "white", "border": f"1px solid {_INK}"}

    return html.Div(
        style={"display": "flex", "gap": "8px", "marginBottom": "24px"},
        children=[
            html.Button("Todos", id="filter-all", n_clicks=0, style=btn_active),
            html.Button("Fase de grupos", id="filter-groups", n_clicks=0, style=btn_base),
            html.Button("Eliminatórias", id="filter-knockouts", n_clicks=0, style=btn_base),
        ],
    )


def _mini_card(match_num: str, match: dict, is_selected: bool) -> html.Div:
    ts = match.get("ts")
    date_str = _fmt_date(ts)
    home = match.get("home") or "?"
    away = match.get("away") or "?"
    hs = match.get("hs") if match.get("hs") is not None else ""
    aws = match.get("as") if match.get("as") is not None else ""
    score = f"{hs}–{aws}" if hs != "" else ""

    svg_str = mini_momentum_svg(
        match.get("series") or [],
        match.get("stoppages") or [],
        width=270, height=68,
    )

    border = f"2px solid {_ACCENT}" if is_selected else "2px solid transparent"

    return html.Div(
        style={
            "background": _CARD_BG, "borderRadius": "10px", "padding": "14px",
            "boxShadow": "0 1px 3px rgba(0,0,0,.07), 0 2px 8px rgba(0,0,0,.05)",
            "border": border, "cursor": "pointer",
            "transition": "box-shadow .15s, border .15s",
        },
        children=[
            # Header row
            html.Div(
                style={"display": "flex", "justifyContent": "space-between",
                       "alignItems": "center", "marginBottom": "10px"},
                children=[
                    html.Span(
                        f"{match_num}  ·  {date_str}",
                        style={"fontSize": "11px", "color": "#999", "fontWeight": "500", "letterSpacing": ".04em"},
                    ),
                    html.Button(
                        "↗",
                        id={"type": "match-card-btn", "index": match["id"]},
                        n_clicks=0,
                        style={
                            "background": "none", "border": "none", "cursor": "pointer",
                            "fontSize": "14px", "color": "#bbb", "padding": "0",
                            "lineHeight": "1",
                        },
                    ),
                ],
            ),
            # Teams
            html.Div([
                html.Div(style={"display": "flex", "alignItems": "center", "gap": "7px", "marginBottom": "3px"}, children=[
                    html.Div(style={"width": "9px", "height": "9px", "borderRadius": "50%",
                                    "background": PALETTE["home"], "flexShrink": "0", "opacity": ".85"}),
                    html.Span(home, style={"fontSize": "13px", "fontWeight": "700", "color": _INK}),
                ]),
                html.Div(style={"display": "flex", "alignItems": "center", "gap": "7px"}, children=[
                    html.Div(style={"width": "9px", "height": "9px", "borderRadius": "50%",
                                    "background": PALETTE["away"], "flexShrink": "0", "opacity": ".80"}),
                    html.Span(away, style={"fontSize": "13px", "fontWeight": "500", "color": "#777"}),
                ]),
            ], style={"marginBottom": "10px"}),
            # Mini SVG chart
            _svg_img(svg_str, width=270, height=68),
            # Score badge (if match finished)
            html.Div(score, style={
                "fontSize": "11px", "fontWeight": "700", "color": "#888",
                "textAlign": "right", "marginTop": "4px",
            }) if score else None,
        ],
    )


def _stage_section(label_pt: str, cards: list, count: int) -> html.Div:
    return html.Div(
        style={"marginBottom": "32px"},
        children=[
            # Stage header
            html.Div(
                style={
                    "display": "flex", "justifyContent": "space-between",
                    "alignItems": "center", "marginBottom": "14px",
                    "borderBottom": "1.5px solid #DDD8D0", "paddingBottom": "10px",
                },
                children=[
                    html.Span(label_pt, style={
                        "fontSize": "13px", "fontWeight": "800",
                        "color": _INK, "letterSpacing": ".12em",
                    }),
                    html.Span(f"{count}  –", style={
                        "fontSize": "12px", "color": "#aaa", "fontWeight": "500",
                    }),
                ],
            ),
            # Cards grid
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(3, 1fr)",
                    "gap": "14px",
                },
                children=cards,
            ),
        ],
    )


def _build_match_sections(
    momentum_data: list[dict],
    filter_val: str,
    selected_id: str | None,
) -> list:
    if not momentum_data:
        return [html.Div("Nenhuma partida disponível.", style={"color": "#aaa", "fontSize": "13px"})]

    # Sort by timestamp → assign match numbers
    sorted_matches = sorted(momentum_data, key=lambda m: m.get("ts") or 0)
    match_nums = {m["id"]: f"M{i + 1:02d}" for i, m in enumerate(sorted_matches)}

    # Group by stage
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in sorted_matches:
        groups[m.get("stage") or "Outro"].append(m)

    # Sort stages
    sorted_stages = sorted(groups.keys(), key=_stage_sort_key)

    # Apply filter
    def _keep(stage: str) -> bool:
        if filter_val == "groups":
            return _is_group_stage(stage)
        if filter_val == "knockouts":
            return _is_knockout(stage)
        return True

    sections = []
    for stage in sorted_stages:
        if not _keep(stage):
            continue
        matches_in_stage = groups[stage]
        cards = [
            _mini_card(match_nums[m["id"]], m, str(m["id"]) == str(selected_id or ""))
            for m in matches_in_stage
        ]
        sections.append(_stage_section(_stage_label_pt(stage), cards, len(matches_in_stage)))

    return sections or [html.Div("Nenhuma partida nesta fase.", style={"color": "#aaa", "fontSize": "13px"})]


# ── app ───────────────────────────────────────────────────────────────────────

app = Dash(
    __name__,
    title="WC2026 · Momentum em Paradas",
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    suppress_callback_exceptions=True,
    external_stylesheets=[
        "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap"
    ],
)


def build_layout() -> html.Div:
    df = _load_df()
    momentum_data = _load_momentum()

    n_matches = df["match_id"].n_unique() if df is not None else 0
    n_stoppages = df["stoppage_id"].n_unique() if df is not None else 0
    n_rows = df.height if df is not None else 0

    effects_fig = effect_bar_chart(
        effect_by_type(df) if df is not None and not df.is_empty() else []
    )
    scatter_fig = scatter_delta_by_minute(df) if df is not None else go.Figure()

    type_options = [{"label": STOPPAGE_LABELS[t], "value": t} for t in ACTIVE_TYPES]

    return html.Div(
        style={
            "background": _BG, "minHeight": "100vh",
            "fontFamily": _FONT,
        },
        children=[
            html.Div(
                style={"maxWidth": "1120px", "margin": "0 auto", "padding": "48px 24px 24px"},
                children=[

                    # ── intro editorial ───────────────────────────────────
                    _intro_block(n_matches, n_stoppages),

                    # ── main charts ───────────────────────────────────────
                    html.Div(
                        style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                               "gap": "16px", "marginBottom": "20px"},
                        children=[
                            _card([dcc.Graph(figure=effects_fig, config={"displayModeBar": False})]),
                            _card([dcc.Graph(figure=scatter_fig, config={"displayModeBar": False})]),
                        ],
                    ),

                    # ── distribution ──────────────────────────────────────
                    html.Div(style={"marginBottom": "28px"}, children=[
                        _section_label("Distribuição por tipo de parada"),
                        _card([
                            dcc.Dropdown(
                                id="dist-type-selector",
                                options=type_options, value="hydration",
                                clearable=False,
                                style={"width": "280px", "marginBottom": "12px"},
                            ),
                            dcc.Graph(id="distribution-chart", config={"displayModeBar": False}),
                        ]),
                    ]),

                    # ── match grid ────────────────────────────────────────
                    html.Div(style={"marginBottom": "8px"}, children=[
                        _section_label("Partidas"),
                    ]),
                    _legend_bar(),
                    _filter_buttons(),
                    html.Div(id="match-grid-container",
                             children=_build_match_sections(momentum_data, "all", None)),

                    # ── stores ────────────────────────────────────────────
                    dcc.Store(id="momentum-data-store", data=momentum_data),
                    dcc.Store(id="stoppages-store",
                              data=df.to_dicts() if df is not None else []),
                    dcc.Store(id="filter-state", data="all"),
                    dcc.Store(id="selected-match-id", data=None),

                    # Footer
                    html.Div(
                        style={"borderTop": "1px solid #E5E0D8", "marginTop": "32px",
                               "padding": "24px 0", "color": "#B0A898", "fontSize": "12px"},
                        children=[
                            "Fonte: SofaScore, janelas de 5 min pré e pós parada, "
                            "IC 95% via bootstrap clusterizado por partida"
                        ],
                    ),
                ],
            ),
            # ── modal overlay (fora do container central) ─────────────
            html.Div(
                id="match-modal-overlay",
                style={"display": "none"},
                children=[
                    # Backdrop clicável para fechar
                    html.Div(
                        id="modal-backdrop",
                        n_clicks=0,
                        style={
                            "position": "fixed", "inset": "0",
                            "background": "rgba(26,24,19,0.55)",
                            "backdropFilter": "blur(3px)",
                            "zIndex": "1000",
                        },
                    ),
                    # Card central
                    html.Div(
                        style={
                            "position": "fixed",
                            "top": "50%", "left": "50%",
                            "transform": "translate(-50%, -50%)",
                            "zIndex": "1001",
                            "width": "min(900px, 94vw)",
                            "maxHeight": "88vh",
                            "overflowY": "auto",
                            "background": _CARD_BG,
                            "borderRadius": "16px",
                            "padding": "28px 28px 24px",
                            "boxShadow": "0 24px 64px rgba(0,0,0,.32)",
                            "fontFamily": _FONT,
                        },
                        children=[
                            # Botão fechar
                            html.Button(
                                "×",
                                id="modal-close-btn",
                                n_clicks=0,
                                style={
                                    "position": "absolute", "top": "16px", "right": "20px",
                                    "background": "none", "border": "none", "cursor": "pointer",
                                    "fontSize": "26px", "lineHeight": "1", "color": "#bbb",
                                    "fontFamily": _FONT, "padding": "0",
                                },
                            ),
                            html.Div(id="modal-content"),
                        ],
                    ),
                ],
            ),
        ],
    )


app.layout = build_layout


# ── callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("filter-state", "data"),
    Output("filter-all", "style"),
    Output("filter-groups", "style"),
    Output("filter-knockouts", "style"),
    Input("filter-all", "n_clicks"),
    Input("filter-groups", "n_clicks"),
    Input("filter-knockouts", "n_clicks"),
    prevent_initial_call=True,
)
def update_filter(n_all, n_groups, n_ko):
    btn_base = {
        "padding": "8px 20px", "borderRadius": "6px", "cursor": "pointer",
        "fontSize": "12px", "fontWeight": "700", "letterSpacing": ".08em",
        "border": "1.5px solid #D0CBC3", "background": "transparent",
        "color": "#555",
    }
    btn_active = {**btn_base, "background": _INK, "color": "white", "border": f"1.5px solid {_INK}"}
    btn_map = {"filter-all": "all", "filter-groups": "groups", "filter-knockouts": "knockouts"}
    val = btn_map.get(dash_ctx.triggered_id, "all")
    styles = {
        "all": (btn_active, btn_base, btn_base),
        "groups": (btn_base, btn_active, btn_base),
        "knockouts": (btn_base, btn_base, btn_active),
    }
    return (val,) + styles[val]


@callback(
    Output("match-grid-container", "children"),
    Input("filter-state", "data"),
    State("momentum-data-store", "data"),
    prevent_initial_call=True,
)
def update_match_grid(filter_val, momentum_data):
    return _build_match_sections(momentum_data or [], filter_val or "all", None)


@callback(
    Output("selected-match-id", "data"),
    Input({"type": "match-card-btn", "index": ALL}, "n_clicks"),
    Input("modal-close-btn", "n_clicks"),
    Input("modal-backdrop", "n_clicks"),
    prevent_initial_call=True,
)
def handle_match_selection(card_clicks, close_clicks, backdrop_clicks):
    tid = dash_ctx.triggered_id
    if not tid:
        return no_update

    # Ignore spurious fires where no real click occurred (n_clicks == 0).
    # This happens when pattern-matching buttons are dynamically added to the DOM —
    # Dash fires the callback with value=0, which is not a real user interaction.
    real_click = any(t.get("value", 0) > 0 for t in dash_ctx.triggered)
    if not real_click:
        return no_update

    if tid in ("modal-close-btn", "modal-backdrop"):
        return None
    return str(tid["index"])


_OVERLAY_HIDDEN = {"display": "none"}
_OVERLAY_SHOWN = {"display": "block"}


@callback(
    Output("match-modal-overlay", "style"),
    Output("modal-content", "children"),
    Input("selected-match-id", "data"),
    State("momentum-data-store", "data"),
    State("stoppages-store", "data"),
    prevent_initial_call=True,
)
def update_modal(match_id, momentum_data, stoppages_data):
    if not match_id or not momentum_data:
        return _OVERLAY_HIDDEN, html.Div()

    match = next((m for m in momentum_data if str(m["id"]) == str(match_id)), None)
    if not match:
        return _OVERLAY_HIDDEN, html.Div()

    home = match.get("home", "Casa")
    away = match.get("away", "Visitante")
    hs = match.get("hs")
    aws = match.get("as")
    stage = _stage_label_pt(match.get("stage") or "")
    date_str = _fmt_date(match.get("ts"))

    fig = momentum_chart(
        series=match.get("series", []),
        stoppages=match.get("stoppages", []),
        goals=match.get("goals", []),
        home=home, away=away,
        home_score=hs, away_score=aws,
    )
    # Wider modal chart
    fig.update_layout(height=380, margin={"l": 50, "r": 30, "t": 56, "b": 44})

    # Stoppage table
    rows = sorted(
        [r for r in (stoppages_data or [])
         if str(r.get("match_id", "")) == str(match_id)
         and r.get("is_home")
         and r.get("stoppage_type") in ACTIVE_TYPES],
        key=lambda r: r.get("clock_minute", 0),
    )

    def _delta_cell(delta):
        if delta is None:
            return html.Td("—", style={"padding": "8px 14px", "color": "#ccc"})
        color = _ACCENT if delta < 0 else "#16A34A"
        return html.Td(f"{delta:+.2f}", style={
            "padding": "8px 14px", "fontWeight": "700", "color": color, "fontSize": "14px",
        })

    table_rows = [
        html.Tr(
            style={"borderBottom": "1px solid #F4F2EE"},
            children=[
                html.Td(f"{r.get('clock_minute', '?'):.0f}'",
                        style={"padding": "8px 14px", "fontWeight": "700", "color": "#555", "width": "64px"}),
                html.Td(_stoppage_badge(r.get("stoppage_type", "")), style={"padding": "8px 14px"}),
                _delta_cell(r.get("momentum_delta")),
                html.Td(f"{r.get('score_team_pre', 0)}–{r.get('score_opp_pre', 0)}",
                        style={"padding": "8px 14px", "color": "#999", "fontSize": "13px"}),
            ],
        )
        for r in rows
    ]

    table_section = (
        html.Table(
            style={"width": "100%", "borderCollapse": "collapse", "fontSize": "13px"},
            children=[
                html.Thead(html.Tr([
                    html.Th(col, style={
                        "padding": "10px 14px", "textAlign": "left",
                        "fontSize": "10px", "textTransform": "uppercase",
                        "letterSpacing": ".08em", "color": "#aaa",
                        "borderBottom": "2px solid #F0EDE8",
                    }) for col in ["Minuto", "Tipo", "Δ Momentum", "Placar (pré)"]
                ])),
                html.Tbody(table_rows),
            ],
        ) if table_rows
        else html.Div("Nenhuma parada de hidratação ou VAR registrada.",
                      style={"color": "#bbb", "fontSize": "13px", "padding": "8px 0"})
    )

    content = html.Div([
        # Modal header
        html.Div(
            style={"marginBottom": "20px", "paddingRight": "32px"},
            children=[
                html.Div(stage, style={
                    "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
                    "letterSpacing": ".12em", "color": "#bbb", "marginBottom": "4px",
                }),
                html.Div(
                    style={"display": "flex", "alignItems": "baseline", "gap": "10px"},
                    children=[
                        html.Span(f"{home}", style={"fontSize": "20px", "fontWeight": "800", "color": PALETTE["home"]}),
                        html.Span(f"{hs}–{aws}" if hs is not None else "vs",
                                  style={"fontSize": "18px", "fontWeight": "600", "color": "#888"}),
                        html.Span(f"{away}", style={"fontSize": "20px", "fontWeight": "600", "color": PALETTE["away"]}),
                        html.Span(f"· {date_str}", style={"fontSize": "13px", "color": "#bbb", "marginLeft": "4px"}),
                    ],
                ),
            ],
        ),
        # Momentum chart
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        # Separator
        html.Div(style={"borderTop": "1px solid #F0EDE8", "margin": "20px 0 14px"}),
        # Stoppage table header
        html.Div("PARADAS DETECTADAS", style={
            "fontSize": "10px", "fontWeight": "700", "textTransform": "uppercase",
            "letterSpacing": ".12em", "color": "#bbb", "marginBottom": "10px",
        }),
        table_section,
    ])

    return _OVERLAY_SHOWN, content


@callback(
    Output("distribution-chart", "figure"),
    Input("dist-type-selector", "value"),
    State("stoppages-store", "data"),
)
def update_distribution(stoppage_type, stoppages_data):
    if not stoppage_type or not stoppages_data:
        return go.Figure()
    full_df = pl.DataFrame(stoppages_data)
    sub_all = (
        full_df.drop_nulls(["momentum_delta", "momentum_pre_5min_mean"])
               .filter(pl.col("momentum_pre_5min_mean") > 0)
               .filter(pl.col("stoppage_type").is_in(list(ACTIVE_TYPES)))
    )
    x_range, bin_size = None, None
    if not sub_all.is_empty():
        vals = sub_all["momentum_delta"].to_list()
        xmin, xmax = min(vals), max(vals)
        x_range = (xmin, xmax)
        bin_size = (xmax - xmin) / 22
    return distribution_chart(full_df, stoppage_type, x_range=x_range, bin_size=bin_size)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8050)
