"""Build static HTML report from committed processed data → site/index.html.

Generates a fully-interactive static page with:
- Stage-filtered match grid (Todos / Fase de grupos / Eliminatórias)
- Click-to-expand match modal with momentum chart + stoppage table
- Distribution tabs (Hidratação / VAR)
- All interactivity via vanilla JS + Plotly.js (no server needed)
"""

from __future__ import annotations

import base64
import json
import math
from collections import defaultdict
from datetime import datetime, timezone

import polars as pl

from src.analysis.descriptive import effect_by_type, load_processed
from src.paths import DOCS, PROCESSED, STOPPAGES_PARQUET
from src.viz.charts import (
    ACTIVE_TYPES,
    STOPPAGE_COLORS,
    STOPPAGE_LABELS,
    distribution_chart,
    effect_bar_chart,
    mini_momentum_svg,
    scatter_delta_by_minute,
)

_ACCENT = "#E5482E"
_INK = "#1A1813"
_BG = "#F0EDE8"
_CARD = "#FFFFFF"
_HOME = "#1D9BF0"
_AWAY = "#F5A623"
_FONT = "'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"

# ── stage helpers (mirrors app.py) ────────────────────────────────────────────

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


def _stage_type(stage: str | None) -> str:
    if stage is not None and stage.strip().isdigit():
        return "group"
    if _is_group_stage(stage):
        return "group"
    if _is_knockout(stage):
        return "knockout"
    return "other"


def _stage_sort_key(stage: str | None) -> tuple:
    if not stage:
        return (99, 0)
    s = stage.lower().strip()
    if s.isdigit():
        return (6, -int(s))
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


# ── helpers ───────────────────────────────────────────────────────────────────

def _fig_div(fig) -> str:
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


def _safe(v: object) -> object:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


# ── match grid HTML ───────────────────────────────────────────────────────────

def _legend_bar() -> str:
    chip_style = "display:flex;align-items:center;gap:6px"
    label_style = "font-size:11px;font-weight:600;color:#666;letter-spacing:.06em"
    return (
        '<div style="display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin-bottom:18px">'
        f'<div style="{chip_style}">'
        f'<div style="width:22px;height:12px;border-radius:3px;background:rgba(29,155,240,0.15)"></div>'
        f'<span style="{label_style}">CASA NA FRENTE</span>'
        f'</div>'
        f'<div style="{chip_style}">'
        f'<div style="width:22px;height:12px;border-radius:3px;background:rgba(245,166,35,0.15)"></div>'
        f'<span style="{label_style}">VISITANTE NA FRENTE</span>'
        f'</div>'
        f'<div style="{chip_style}">'
        f'<div style="width:18px;height:0;border-top:2px dashed {_HOME};flex-shrink:0;margin-top:1px"></div>'
        f'<span style="{label_style}">HIDRATAÇÃO</span>'
        f'</div>'
        f'<div style="{chip_style}">'
        f'<div style="width:18px;height:0;border-top:2px dashed {_AWAY};flex-shrink:0;margin-top:1px"></div>'
        f'<span style="{label_style}">VAR</span>'
        f'</div>'
        '</div>'
    )


def _filter_buttons() -> str:
    base = (
        "padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;"
        "font-weight:500;border:1px solid #D1CBC0;background:transparent;color:#6B7280;"
        "font-family:" + _FONT
    )
    active = (
        "padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;"
        "font-weight:500;border:1px solid #1A1813;background:#1A1813;color:white;"
        "font-family:" + _FONT
    )
    return (
        '<div style="display:flex;gap:8px;margin-bottom:24px">'
        f'<button id="filter-all" onclick="setFilter(\'all\')" style="{active}">Todos</button>'
        f'<button id="filter-groups" onclick="setFilter(\'groups\')" style="{base}">Fase de grupos</button>'
        f'<button id="filter-knockouts" onclick="setFilter(\'knockouts\')" style="{base}">Eliminatórias</button>'
        '</div>'
    )


def _match_sections(momentum_data: list[dict]) -> str:
    if not momentum_data:
        return "<p style='color:#9CA3AF;font-size:14px'>Nenhuma partida disponível ainda.</p>"

    sorted_matches = sorted(momentum_data, key=lambda m: m.get("ts") or 0)
    match_nums = {m["id"]: f"M{i + 1:02d}" for i, m in enumerate(sorted_matches)}

    groups: dict[str, list[dict]] = defaultdict(list)
    for m in sorted_matches:
        groups[m.get("stage") or "Outro"].append(m)

    sorted_stages = sorted(groups.keys(), key=_stage_sort_key)
    sections = []

    for stage in sorted_stages:
        matches_in_stage = groups[stage]
        stype = _stage_type(stage)
        label = _stage_label_pt(stage)
        count = len(matches_in_stage)

        cards = []
        for m in matches_in_stage:
            mid = str(m["id"])
            home = m.get("home") or "?"
            away = m.get("away") or "?"
            hs, aws = m.get("hs"), m.get("as")
            score = f"{hs}–{aws}" if hs is not None else ""
            date_str = _fmt_date(m.get("ts"))
            num = match_nums[m["id"]]

            svg = mini_momentum_svg(
                m.get("series") or [], m.get("stoppages") or [],
                width=270, height=68,
            )
            score_row = (
                f'<div style="font-size:11px;font-weight:700;color:#888;'
                f'text-align:right;margin-top:4px">{score}</div>'
                if score else ""
            )

            cards.append(
                f'<div class="match-card" data-id="{mid}" onclick="openModal(\'{mid}\')">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
                f'<span style="font-size:11px;color:#999;font-weight:500;letter-spacing:.04em">'
                f'{num}  ·  {date_str}</span>'
                f'<span style="font-size:14px;color:#bbb">↗</span>'
                f'</div>'
                f'<div style="margin-bottom:10px">'
                f'<div style="display:flex;align-items:center;gap:7px;margin-bottom:3px">'
                f'<div style="width:9px;height:9px;border-radius:50%;background:{_HOME};flex-shrink:0;opacity:.85"></div>'
                f'<span style="font-size:13px;font-weight:700;color:{_INK}">{home}</span>'
                f'</div>'
                f'<div style="display:flex;align-items:center;gap:7px">'
                f'<div style="width:9px;height:9px;border-radius:50%;background:{_AWAY};flex-shrink:0;opacity:.80"></div>'
                f'<span style="font-size:13px;font-weight:500;color:#777">{away}</span>'
                f'</div>'
                f'</div>'
                f'<img src="{_svg_uri(svg)}" alt="" '
                f'style="width:100%;max-width:270px;height:68px;object-fit:contain;display:block">'
                f'{score_row}'
                f'</div>'
            )

        sections.append(
            f'<div class="stage-section" data-stage-type="{stype}" style="margin-bottom:32px">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;'
            f'margin-bottom:14px;border-bottom:1.5px solid #DDD8D0;padding-bottom:10px">'
            f'<span style="font-size:13px;font-weight:800;color:{_INK};letter-spacing:.12em">{label}</span>'
            f'<span style="font-size:12px;color:#aaa;font-weight:500">{count} –</span>'
            f'</div>'
            f'<div class="match-grid">' + "".join(cards) + '</div>'
            f'</div>'
        )

    return "\n".join(sections)


# ── JavaScript ────────────────────────────────────────────────────────────────

def _build_js(momentum_data_json: str, stoppages_json: str) -> str:
    data_vars = (
        "const _MD = " + momentum_data_json + ";\n"
        "const _MS = " + stoppages_json + ";\n"
        "const _MM = {};\n"
        "_MD.forEach(m => { _MM[String(m.id)] = m; });\n"
    )

    # NOTE: this is a plain string (not f-string), so { } are JS literals
    functions = """
const _SC = {hydration:'#1D9BF0',var:'#F5A623',injury_huddle:'#E5482E',injury_no_huddle:'#FF8C6B'};
const _SL = {hydration:'Pausa de Hidratão',var:'VAR',injury_huddle:'Lesão (c/ subst.)',injury_no_huddle:'Lesão (s/ subst.)'};

const _SPT = {
  'group a':'GRUPO A','group b':'GRUPO B','group c':'GRUPO C','group d':'GRUPO D',
  'group e':'GRUPO E','group f':'GRUPO F','group g':'GRUPO G','group h':'GRUPO H',
  'group i':'GRUPO I','group j':'GRUPO J','group k':'GRUPO K','group l':'GRUPO L',
  'round of 32':'RODADA DE 32','round of 16':'OITAVAS DE FINAL',
  'quarter-finals':'QUARTAS DE FINAIS','semi-finals':'SEMI FINAIS',
  'final':'FINAL','third place play-off':'DISPUTA DO 3º LUGAR','third place':'DISPUTA DO 3º LUGAR'
};

function _stagePt(s) {
  if (!s) return '';
  const lc = s.toLowerCase().trim();
  if (/^[0-9]+$/.test(lc)) return lc + 'ª RODADA';
  return _SPT[lc] || s.toUpperCase();
}

// ── filter ────────────────────────────────────────────────────────────────────

function setFilter(type) {
  const base   = 'padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;font-weight:500;border:1px solid #D1CBC0;background:transparent;color:#6B7280';
  const active = 'padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;font-weight:500;border:1px solid #1A1813;background:#1A1813;color:white';

  document.querySelectorAll('.stage-section').forEach(s => {
    const st = s.dataset.stageType;
    s.style.display = (type === 'all' ||
                       (type === 'groups'    && st === 'group') ||
                       (type === 'knockouts' && st === 'knockout')) ? '' : 'none';
  });

  [['filter-all','all'],['filter-groups','groups'],['filter-knockouts','knockouts']].forEach(([id, val]) => {
    const btn = document.getElementById(id);
    if (btn) btn.setAttribute('style', (val === type ? active : base));
  });
}

// ── distribution tabs ─────────────────────────────────────────────────────────

function showDist(type) {
  const base   = 'padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;font-weight:500;border:1px solid #D1CBC0;background:transparent;color:#6B7280';
  const active = 'padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;font-weight:500;border:1px solid #1A1813;background:#1A1813;color:white';
  ['hydration','var'].forEach(t => {
    const panel = document.getElementById('dist-' + t);
    const btn   = document.getElementById('dtab-' + t);
    if (panel) panel.style.display = t === type ? '' : 'none';
    if (btn)   btn.setAttribute('style', t === type ? active : base);
  });
  // Plotly charts initialised inside display:none get 0 width — force a resize
  window.dispatchEvent(new Event('resize'));
}

// ── momentum chart builder ────────────────────────────────────────────────────

function _buildFig(m) {
  const series    = m.series    || [];
  const stoppages = m.stoppages || [];
  const goals     = m.goals     || [];
  if (!series.length) return null;

  const minutes = series.map(p => p[0]);
  const values  = series.map(p => p[1]);
  const posV    = values.map(v => Math.max(v, 0));
  const negV    = values.map(v => Math.min(v, 0));
  const maxAbs  = Math.max(...values.map(v => Math.abs(v)), 0.1);

  const data = [
    {type:'scatter',x:minutes,y:posV,fill:'tozeroy',mode:'none',
     fillcolor:'rgba(29,155,240,0.15)',hoverinfo:'skip',showlegend:false},
    {type:'scatter',x:minutes,y:negV,fill:'tozeroy',mode:'none',
     fillcolor:'rgba(245,166,35,0.15)',hoverinfo:'skip',showlegend:false},
    {type:'scatter',x:minutes,y:values,mode:'lines',showlegend:false,
     line:{color:'rgba(26,24,19,0.55)',width:1.8},
     hovertemplate:'min %{x}: %{y:.1f}<extra></extra>'},
  ];

  const shapes = [
    {type:'line',x0:45,x1:45,y0:0,y1:1,yref:'paper',
     line:{color:'rgba(26,24,19,0.10)',width:1}},
  ];

  const annotations = [
    {x:2,y:maxAbs*0.82,text:'<b>'+m.home+'</b>',showarrow:false,
     font:{size:11,color:'#1D9BF0'},xanchor:'left'},
    {x:2,y:-maxAbs*0.82,text:'<b>'+m.away+'</b>',showarrow:false,
     font:{size:11,color:'#F5A623'},xanchor:'left'},
  ];

  const seen = new Set();
  for (const s of stoppages) {
    if (s.length < 2) continue;
    const minute = s[0], stype = s[1];
    const color = _SC[stype] || '#aaa';
    const label = _SL[stype] || stype;
    shapes.push({type:'line',x0:minute,x1:minute,y0:0,y1:1,yref:'paper',
                 line:{color,width:2.5,dash:'dot'}});
    if (!seen.has(stype)) {
      annotations.push({x:minute,y:1.02,xref:'x',yref:'paper',text:label,
                        showarrow:false,font:{size:10,color},xanchor:'left',yanchor:'bottom'});
      seen.add(stype);
    }
  }

  for (const g of goals) {
    const icon = g.k === 'pen' ? '🟡' : g.k === 'og' ? '🔴' : '⚽';
    annotations.push({x:g.m,y:0,text:icon,showarrow:false,
                      font:{size:13},yshift:g.h ? 14 : -18});
  }

  const hs  = m.hs  != null ? m.hs  : 0;
  const aws = m['as'] != null ? m['as'] : 0;

  return {
    data,
    layout: {
      font:{family:"'Plus Jakarta Sans', sans-serif",size:13,color:'#1A1813'},
      plot_bgcolor:'#FFFFFF',paper_bgcolor:'#FFFFFF',
      margin:{l:50,r:30,t:56,b:44},
      hovermode:'x unified',height:380,showlegend:false,
      shapes,annotations,
      title:{text:'<b>'+m.home+'  '+hs+' – '+aws+'  '+m.away+'</b>',
             x:0.5,xanchor:'center',font:{size:15}},
      xaxis:{gridcolor:'rgba(26,24,19,0.06)',tickfont:{size:11},
             linecolor:'rgba(26,24,19,0.06)',zerolinecolor:'rgba(26,24,19,0.20)',
             title:{text:'Minuto'}},
      yaxis:{gridcolor:'rgba(26,24,19,0.06)',tickfont:{size:11},
             linecolor:'rgba(26,24,19,0.06)',zeroline:true,zerolinewidth:2,
             zerolinecolor:'rgba(26,24,19,0.20)',title:{text:'Momentum'}},
    }
  };
}

// ── modal rendering ───────────────────────────────────────────────────────────

function _deltaHtml(v) {
  if (v == null) return '<span style="color:#ccc">—</span>';
  const color = v < 0 ? '#E5482E' : '#16A34A';
  return '<span style="color:'+color+';font-weight:700;font-size:14px">'+(v>=0?'+':'')+v.toFixed(2)+'</span>';
}

function _badge(stype) {
  const c = _SC[stype] || '#999', l = _SL[stype] || stype;
  return '<span style="background:'+c+';color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;white-space:nowrap">'+l+'</span>';
}

function openModal(matchId) {
  const m = _MM[matchId];
  if (!m) return;

  const hs  = m.hs  != null ? m.hs  : '';
  const aws = m['as'] != null ? m['as'] : '';
  const scoreStr = (hs !== '' && aws !== '') ? hs + '–' + aws : 'vs';

  document.getElementById('modal-header').innerHTML =
    '<div style="margin-bottom:20px;padding-right:32px">' +
    '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#bbb;margin-bottom:4px">'+_stagePt(m.stage||'')+'</div>'+
    '<div style="display:flex;align-items:baseline;gap:10px">'+
    '<span style="font-size:20px;font-weight:800;color:#1D9BF0">'+m.home+'</span>'+
    '<span style="font-size:18px;font-weight:600;color:#888">'+scoreStr+'</span>'+
    '<span style="font-size:20px;font-weight:600;color:#F5A623">'+m.away+'</span>'+
    '</div></div>';

  const fig = _buildFig(m);
  if (fig) Plotly.newPlot('modal-chart', fig.data, fig.layout, {displayModeBar:false,responsive:true});

  const rows = (_MS[matchId] || []);
  const TH = 'padding:10px 14px;text-align:left;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#aaa;border-bottom:2px solid #F0EDE8';
  let tbl;
  if (rows.length) {
    const trs = rows.map(r =>
      '<tr style="border-bottom:1px solid #F4F2EE">'+
      '<td style="padding:8px 14px;font-weight:700;color:#555;width:64px">'+Math.round(r.clock_minute)+"'</td>"+
      '<td style="padding:8px 14px">'+_badge(r.stoppage_type)+'</td>'+
      '<td style="padding:8px 14px">'+_deltaHtml(r.momentum_delta)+'</td>'+
      '<td style="padding:8px 14px;color:#999;font-size:13px">'+r.score_team_pre+'–'+r.score_opp_pre+'</td>'+
      '</tr>'
    ).join('');
    tbl = '<table style="width:100%;border-collapse:collapse;font-size:13px">'+
          '<thead><tr>'+
          ['Minuto','Tipo','Δ Momentum','Placar (pré)'].map(h=>'<th style="'+TH+'">'+h+'</th>').join('')+
          '</tr></thead><tbody>'+trs+'</tbody></table>';
  } else {
    tbl = '<p style="color:#bbb;font-size:13px;padding:8px 0">Nenhuma parada de hidratação ou VAR registrada.</p>';
  }
  document.getElementById('modal-table').innerHTML =
    '<div style="border-top:1px solid #F0EDE8;margin:20px 0 14px"></div>'+
    '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#bbb;margin-bottom:10px">PARADAS DETECTADAS</div>'+
    tbl;

  document.getElementById('modal-overlay').style.display = 'block';
  document.body.style.overflow = 'hidden';
}

function closeModal() {
  document.getElementById('modal-overlay').style.display = 'none';
  document.body.style.overflow = '';
  Plotly.purge('modal-chart');
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
"""
    return data_vars + functions


# ── full page ─────────────────────────────────────────────────────────────────

def _page(
    n_matches: int,
    n_stoppages: int,
    effects_div: str,
    scatter_div: str,
    dist_hyd_div: str,
    dist_var_div: str,
    match_sections_html: str,
    legend_html: str,
    filter_html: str,
    js_code: str,
    updated: str,
) -> str:
    btn_base = (
        "padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;"
        f"font-weight:500;border:1px solid #D1CBC0;background:transparent;color:#6B7280"
    )
    btn_active = (
        "padding:6px 16px;border-radius:4px;cursor:pointer;font-size:13px;"
        f"font-weight:500;border:1px solid {_INK};background:{_INK};color:white"
    )
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>As pausas para hidratação realmente quebram o ritmo?, Copa do Mundo 2026</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: {_BG}; font-family: {_FONT}; color: {_INK}; min-height: 100vh; }}
    .container {{ max-width: 1120px; margin: 0 auto; padding: 48px 24px 64px; }}
    .chart-card {{ background: {_CARD}; border-radius: 12px; padding: 20px 22px;
                   box-shadow: 0 1px 3px rgba(0,0,0,.06), 0 4px 16px rgba(0,0,0,.04); }}
    .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
    .section-label {{ font-size: 13px; font-weight: 500; color: #9CA3AF; margin-bottom: 12px; }}
    .match-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }}
    .match-card {{
      background: {_CARD}; border-radius: 10px; padding: 14px;
      box-shadow: 0 1px 3px rgba(0,0,0,.07), 0 2px 8px rgba(0,0,0,.05);
      border: 2px solid transparent; cursor: pointer;
      transition: box-shadow .15s, border-color .15s;
    }}
    .match-card:hover {{ box-shadow: 0 2px 8px rgba(0,0,0,.12), 0 4px 16px rgba(0,0,0,.08); border-color: {_ACCENT}; }}
    footer {{ border-top: 1px solid #E5E0D8; margin-top: 48px; padding-top: 20px; font-size: 12px; color: #B0A898; }}
    @media (max-width: 900px) {{ .match-grid {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 600px) {{ .two-col {{ grid-template-columns: 1fr; }} .match-grid {{ grid-template-columns: 1fr; }} .container {{ padding: 32px 16px 48px; }} }}
  </style>
</head>
<body>
<div class="container">

  <!-- intro -->
  <div style="margin-bottom:48px">
    <h1 style="font-size:24px;font-weight:700;margin-bottom:6px;line-height:1.25">As pausas para hidratação realmente quebram o ritmo?</h1>
    <p style="font-size:13px;color:#9CA3AF;margin-bottom:28px;font-weight:400">Copa do Mundo 2026 · atualizado em {updated}</p>
    <p style="font-size:15px;line-height:1.75;color:#4B5563;margin-bottom:14px">
      Em <strong style="color:{_INK}">{n_matches} partidas analisadas</strong>, detectamos
      <strong style="color:{_INK}">{n_stoppages} pausas de jogo</strong>, hidratação obrigatória e revisões de VAR.
      A pergunta é simples: quando uma equipe está no controle, a interrupção quebra o ritmo de quem domina?
    </p>
    <div style="border-left:3px solid #E5E7EB;padding-left:18px">
      <p style="font-size:13.5px;line-height:1.7;color:#6B7280">
        O SofaScore atribui um índice de momentum minuto a minuto, oscilando entre −100 e +100.
        Para cada parada, medimos a média dos 5 minutos antes e dos 5 depois, excluindo o minuto exato.
        O <strong>Δ Momentum</strong> é a diferença pós menos pré, sempre da perspectiva do time que estava na frente.
        Um Δ negativo significa que a parada interrompeu quem dominava.
      </p>
    </div>
  </div>

  <!-- main charts -->
  <div class="two-col">
    <div class="chart-card">{effects_div}</div>
    <div class="chart-card">{scatter_div}</div>
  </div>

  <!-- distribution with tabs -->
  <div style="margin-bottom:28px">
    <div class="section-label">Distribuição por tipo de parada</div>
    <div class="chart-card">
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <button id="dtab-hydration" onclick="showDist('hydration')" style="{btn_active}">Pausa de Hidratação</button>
        <button id="dtab-var"       onclick="showDist('var')"       style="{btn_base}">VAR</button>
      </div>
      <div id="dist-hydration">{dist_hyd_div}</div>
      <div id="dist-var" style="display:none">{dist_var_div}</div>
    </div>
  </div>

  <!-- match grid -->
  <div class="section-label">Partidas</div>
  {legend_html}
  {filter_html}
  {match_sections_html}

  <footer>
    Fonte: SofaScore, janelas de 5 min pré e pós parada, IC 95% via bootstrap clusterizado por partida
  </footer>
</div>

<!-- modal overlay -->
<div id="modal-overlay" style="display:none">
  <div id="modal-backdrop" onclick="closeModal()"
       style="position:fixed;inset:0;background:rgba(26,24,19,0.55);
              backdrop-filter:blur(3px);z-index:1000"></div>
  <div style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
              z-index:1001;width:min(900px,94vw);max-height:88vh;overflow-y:auto;
              background:{_CARD};border-radius:16px;padding:28px 28px 24px;
              box-shadow:0 24px 64px rgba(0,0,0,.32);font-family:{_FONT}">
    <button onclick="closeModal()"
            style="position:absolute;top:16px;right:20px;background:none;border:none;
                   cursor:pointer;font-size:26px;line-height:1;color:#bbb;padding:0">&#215;</button>
    <div id="modal-header"></div>
    <div id="modal-chart"></div>
    <div id="modal-table"></div>
  </div>
</div>

<script>
{js_code}
</script>
</body>
</html>"""


# ── empty page ────────────────────────────────────────────────────────────────

_EMPTY_HTML = (
    "<!doctype html><html lang='pt-BR'><meta charset='utf-8'>"
    "<title>Copa do Mundo 2026, Momentum</title>"
    "<body style='font-family:sans-serif;max-width:640px;margin:60px auto;color:#1A1813'>"
    "<h1 style='font-size:22px;margin-bottom:16px'>Copa do Mundo 2026, Momentum em Paradas</h1>"
    "<p style='color:#6B7280'>Nenhum dado disponível ainda. Volte após a próxima partida.</p>"
)


# ── build ─────────────────────────────────────────────────────────────────────

def build() -> str:
    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / "index.html"
    updated = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    if not STOPPAGES_PARQUET.exists():
        out.write_text(_EMPTY_HTML, encoding="utf-8")
        return str(out)

    df = load_processed()
    if df.is_empty():
        out.write_text(_EMPTY_HTML, encoding="utf-8")
        return str(out)

    momentum_path = PROCESSED / "momentum.json"
    momentum_data: list[dict] = (
        json.loads(momentum_path.read_text(encoding="utf-8"))
        if momentum_path.exists() else []
    )

    # Stoppages per match for modal table (is_home=True, active types only)
    match_stoppages: dict[str, list] = defaultdict(list)
    for row in df.to_dicts():
        if row.get("is_home") and row.get("stoppage_type") in ACTIVE_TYPES:
            mid = str(row.get("match_id", ""))
            match_stoppages[mid].append({
                "clock_minute":   _safe(row.get("clock_minute")),
                "stoppage_type":  row.get("stoppage_type"),
                "momentum_delta": _safe(row.get("momentum_delta")),
                "score_team_pre": _safe(row.get("score_team_pre", 0)),
                "score_opp_pre":  _safe(row.get("score_opp_pre", 0)),
            })
    for mid in match_stoppages:
        match_stoppages[mid].sort(key=lambda r: r.get("clock_minute") or 0)

    js_code = _build_js(
        momentum_data_json=json.dumps(momentum_data),
        stoppages_json=json.dumps(dict(match_stoppages)),
    )

    effects = effect_by_type(df)
    n_matches = int(df["match_id"].n_unique())
    n_stoppages = int(df["stoppage_id"].n_unique())

    # Shared x_range and bin_size so hydration and VAR bars are identical in width
    _sub_all = (
        df.drop_nulls(["momentum_delta", "momentum_pre_5min_mean"])
          .filter(pl.col("momentum_pre_5min_mean") > 0)
          .filter(pl.col("stoppage_type").is_in(list(ACTIVE_TYPES)))
    )
    _dist_x_range: tuple[float, float] | None = None
    _dist_bin_size: float | None = None
    if not _sub_all.is_empty():
        _vals = _sub_all["momentum_delta"].to_list()
        _dist_x_range = (min(_vals), max(_vals))
        _dist_bin_size = (max(_vals) - min(_vals)) / 22

    page = _page(
        n_matches=n_matches,
        n_stoppages=n_stoppages,
        effects_div=_fig_div(effect_bar_chart(effects)),
        scatter_div=_fig_div(scatter_delta_by_minute(df)),
        dist_hyd_div=_fig_div(distribution_chart(df, "hydration",
                                                  x_range=_dist_x_range, bin_size=_dist_bin_size)),
        dist_var_div=_fig_div(distribution_chart(df, "var",
                                                  x_range=_dist_x_range, bin_size=_dist_bin_size)),
        match_sections_html=_match_sections(momentum_data),
        legend_html=_legend_bar(),
        filter_html=_filter_buttons(),
        js_code=js_code,
        updated=updated,
    )
    out.write_text(page, encoding="utf-8")
    return str(out)


if __name__ == "__main__":
    print("[docs]", build())
