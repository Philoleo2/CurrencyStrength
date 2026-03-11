"""
Currency Strength Dashboard
==============================
Dashboard interattiva Streamlit per visualizzare la forza delle valute,
il momentum, la classificazione trend/mean-revert e gli alert.

Avvio:
    streamlit run app.py
"""

import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

_ROME = ZoneInfo("Europe/Rome")

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from config import (
    CURRENCIES, DEFAULT_TIMEFRAME, REFRESH_SECONDS,
    THRESHOLD_STRONG_BULL, THRESHOLD_EXTREME_BULL,
    THRESHOLD_STRONG_BEAR, THRESHOLD_EXTREME_BEAR,
    COMPOSITE_WEIGHT_H1, COMPOSITE_WEIGHT_H4, COMPOSITE_WEIGHT_D1,
    ALERTS_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ALERT_GRADES,
    ALERT_STATE_FILE,
    NEWS_MIN_IMPACT,
    GRADE_HYSTERESIS_POINTS, SIGNAL_MIN_RESIDENCE_HOURS,
    SIGNAL_GRACE_REFRESHES, SIGNAL_CONFIRMATION_REFRESHES,
)
from data_fetcher import fetch_all_pairs, fetch_all_futures
from cot_data import load_cot_data, compute_cot_scores, get_cot_timeseries
from strength_engine import (
    full_analysis, compute_rolling_strength, blend_multi_timeframe,
    compute_atr_context, compute_trade_setups, compute_currency_correlation,
    compute_velocity_scores, smooth_composite_scores,
)
from alerts import send_test_alert, load_signal_history
from economic_calendar import (
    get_current_sessions, fetch_calendar, get_news_impact_for_pairs,
    filter_setups_by_news, get_upcoming_events, get_recent_events,
    is_forex_market_open,
)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURAZIONE PAGINA
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="Strength Dashboard",
    page_icon="💱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-REFRESH allineato alla chiusura candela oraria (xx:00)
# ═══════════════════════════════════════════════════════════════════════════════
def _ms_to_next_hour() -> int:
    """Millisecondi mancanti alla prossima ora piena + 10 s di margine."""
    now = dt.datetime.now(dt.timezone.utc)
    next_hour = (now + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    delta_ms = int((next_hour - now).total_seconds() * 1000) + 10_000  # +10 s margine
    return max(delta_ms, 60_000)  # minimo 60 s di sicurezza

st_autorefresh(interval=_ms_to_next_hour(), limit=0, key="currency_hourly_refresh")

# ── Forza refresh dati a cambio ora (allineamento candela) ──────────
# Chiave condivisa tra tutte le pagine: il clear avviene UNA sola volta
# al cambio d'ora, non quando si naviga tra pagine.
_current_hour_key = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H")
if st.session_state.get("_last_hour_global") != _current_hour_key:
    st.session_state["_last_hour_global"] = _current_hour_key
    st.cache_data.clear()          # svuota cache → forza fetch nuovi dati

# CSS personalizzato
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1f77b4;
        text-align: center;
        padding: 0.5rem 0;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
        padding: 1rem;
        color: white;
        text-align: center;
    }
    .alert-box {
        background-color: #fff3cd;
        border: 1px solid #ffc107;
        border-radius: 5px;
        padding: 0.8rem;
        margin: 0.5rem 0;
    }
    .trend-follow {
        background-color: #d4edda;
        border-left: 4px solid #28a745;
        padding: 0.5rem 1rem;
        margin: 0.3rem 0;
        border-radius: 3px;
    }
    .mean-revert {
        background-color: #d1ecf1;
        border-left: 4px solid #17a2b8;
        padding: 0.5rem 1rem;
        margin: 0.3rem 0;
        border-radius: 3px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.5rem;
    }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.image("https://img.icons8.com/color/96/currency-exchange.png", width=64)
    st.title("⚙️ Impostazioni")

    timeframe = st.selectbox(
        "Timeframe",
        options=["Composito", "H1", "H4", "D1"],
        index=0 if DEFAULT_TIMEFRAME == "Composito" else (
            3 if DEFAULT_TIMEFRAME == "D1" else (2 if DEFAULT_TIMEFRAME == "H4" else 1)),
        help="Composito = blend H1+H4+D1 (reattività + stabilità + trend di fondo), H1 = ogni ora, H4 = ogni 4 ore, D1 = giornaliero",
    )

    _next_h = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    st.info(f"🔄 Prossimo refresh: {_next_h.astimezone(_ROME).strftime('%H:%M')} (ora candela)")

    if timeframe == "Composito":
        st.divider()
        st.subheader("⚖️ Pesi Blend")
        st.write(f"H1 (reattività): **{COMPOSITE_WEIGHT_H1:.0%}**")
        st.write(f"H4 (stabilità): **{COMPOSITE_WEIGHT_H4:.0%}**")
        st.write(f"D1 (trend di fondo): **{COMPOSITE_WEIGHT_D1:.0%}**")

    st.divider()
    st.subheader("📊 Soglie di Attenzione")
    st.write(f"🟢 Forte Bullish: **≥ {THRESHOLD_STRONG_BULL}**")
    st.write(f"🟢🟢 Estremo Bull: **≥ {THRESHOLD_EXTREME_BULL}**")
    st.write(f"🔴 Forte Bearish: **≤ {THRESHOLD_STRONG_BEAR}**")
    st.write(f"🔴🔴 Estremo Bear: **≤ {THRESHOLD_EXTREME_BEAR}**")

    st.divider()
    st.subheader("📅 Frequenza Dati")
    if timeframe == "Composito":
        st.markdown("""
        | Dato | Frequenza |
        |------|-----------|
        | Prezzo H1 | Ogni ora |
        | Prezzo H4 | Ogni 4 ore |
        | Prezzo D1 | Giornaliero |
        | Volume | Ogni barra |
        | COT | Settimanale (venerdì) |
        """)
    else:
        st.markdown("""
        | Dato | Frequenza |
        |------|-----------|
        | Prezzo | Ogni barra ({tf}) |
        | Volume | Ogni barra ({tf}) |
        | COT | Settimanale (venerdì) |
        """.format(tf=timeframe))

    st.divider()
    st.subheader("📱 Alert Telegram")
    if ALERTS_ENABLED and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        st.success("✅ Alert attivi")
        st.caption(f"Gradi monitorati: {', '.join(ALERT_GRADES)}")
        if st.button("🔔 Invia Test", key="tg_test", use_container_width=True):
            if send_test_alert():
                st.toast("✅ Test inviato!", icon="📱")
            else:
                st.toast("❌ Errore invio", icon="⚠️")
    else:
        st.warning("Alert disabilitati")
        st.caption(
            "Per attivare: apri **config.py** e imposta\n"
            "`ALERTS_ENABLED = True`\n"
            "+ il token del bot e il tuo chat\\_id Telegram."
        )

    st.divider()
    st.caption(f"Ultimo aggiornamento: {dt.datetime.now(_ROME).strftime('%Y-%m-%d %H:%M')}")

    # Sessione attiva nella sidebar
    st.divider()
    st.subheader("🕐 Sessione Attiva")
    _sb_session = get_current_sessions()
    st.markdown(f"**{_sb_session['session_label']}**")
    st.caption(f"{_sb_session['utc_now'].strftime('%H:%M')} UTC")

    if st.button("🔄 Aggiorna Dati Ora", use_container_width=True):
        st.cache_data.clear()  # svuota cache di TUTTE le pagine (sincronizzazione)
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING (con cache Streamlit)
# ═══════════════════════════════════════════════════════════════════════════════

# Quando il mercato è chiuso (weekend), usa una TTL molto lunga per evitare
# fetch inutili — i dati non cambiano fino alla riapertura.
_market_open_for_ttl = is_forex_market_open()["is_open"]
_cache_ttl = REFRESH_SECONDS.get(DEFAULT_TIMEFRAME, 3600) if _market_open_for_ttl else 86400

@st.cache_data(ttl=_cache_ttl, show_spinner=False)
def load_all_data(tf: str):
    """Carica tutti i dati necessari."""
    with st.spinner("📥 Scaricamento dati di prezzo..."):
        if tf == "Composito":
            all_pairs_h1 = fetch_all_pairs("H1")
            all_pairs_h4 = fetch_all_pairs("H4")
            all_pairs_d1 = fetch_all_pairs("D1")
            all_pairs = all_pairs_h4  # usato come riferimento principale
        else:
            all_pairs = fetch_all_pairs(tf)
            all_pairs_h1 = None
            all_pairs_h4 = None
            all_pairs_d1 = None

    with st.spinner("📥 Scaricamento volumi futures CME..."):
        if tf == "Composito":
            futures_h1 = fetch_all_futures("H1")
            futures_h4 = fetch_all_futures("H4")
            futures_d1 = fetch_all_futures("D1")
            futures = futures_h4
        else:
            futures = fetch_all_futures(tf)
            futures_h1 = None
            futures_h4 = None
            futures_d1 = None

    with st.spinner("📥 Scaricamento dati COT (CFTC)..."):
        cot_raw = load_cot_data()
        cot_scores = compute_cot_scores(cot_raw)
        cot_ts = get_cot_timeseries(cot_raw)

    return {
        "all_pairs": all_pairs,
        "futures": futures,
        "cot_raw": cot_raw,
        "cot_scores": cot_scores,
        "cot_ts": cot_ts,
        "all_pairs_h1": all_pairs_h1,
        "all_pairs_h4": all_pairs_h4,
        "all_pairs_d1": all_pairs_d1,
        "futures_h1": futures_h1,
        "futures_h4": futures_h4,
        "futures_d1": futures_d1,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CARICAMENTO
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="main-header">💱 Currency Strength Indicator</div>',
            unsafe_allow_html=True)

if timeframe == "Composito":
    st.markdown(
        f"<p style='text-align:center; color:gray;'>Timeframe: <b>Composito (H1 {COMPOSITE_WEIGHT_H1:.0%} + H4 {COMPOSITE_WEIGHT_H4:.0%} + D1 {COMPOSITE_WEIGHT_D1:.0%})</b> | "
        f"Dati aggiornati: {dt.datetime.now(_ROME).strftime('%H:%M:%S')}</p>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"<p style='text-align:center; color:gray;'>Timeframe: <b>{timeframe}</b> | "
        f"Dati aggiornati: {dt.datetime.now(_ROME).strftime('%H:%M:%S')}</p>",
        unsafe_allow_html=True,
    )

# ── Rilevamento weekend / mercato chiuso ────────────────────────────────────
_market_status = is_forex_market_open()
if not _market_status["is_open"]:
    st.warning(
        f"⚠️ **{_market_status['reason']}**\n\n"
        f"I dati visualizzati sono gli ultimi disponibili dalla cache. "
        f"Riapertura: **{_market_status['next_open']}**"
    )

try:
    data = load_all_data(timeframe)
    all_pairs = data["all_pairs"]
    futures = data["futures"]
    cot_raw = data["cot_raw"]
    cot_scores = data["cot_scores"]
    cot_ts = data["cot_ts"]
except Exception as e:
    st.error(f"Errore nel caricamento dati: {e}")
    st.stop()

if not all_pairs:
    st.warning("Nessun dato di prezzo disponibile. Verifica la connessione internet.")
    st.stop()

# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI
# ═══════════════════════════════════════════════════════════════════════════════

if timeframe == "Composito":
    analysis_h1 = full_analysis(data["all_pairs_h1"], data["futures_h1"], cot_scores)
    analysis_h4 = full_analysis(data["all_pairs_h4"], data["futures_h4"], cot_scores)
    analysis_d1 = full_analysis(data["all_pairs_d1"], data["futures_d1"], cot_scores)
    analysis = blend_multi_timeframe(analysis_h1, analysis_h4, analysis_d1)
    is_composite = True
else:
    analysis = full_analysis(all_pairs, futures, cot_scores)
    is_composite = False

composite = analysis["composite"]
momentum = analysis["momentum"]
classification = analysis["classification"]
rolling = analysis["rolling_strength"]
atr_context = analysis.get("atr_context", {})
velocity = analysis.get("velocity", {})
candle9 = analysis.get("candle9", {})

# ── Smoothing composito (anti-flickering) ────────────────────────────
# Recupera prev_composite dal file condiviso con lo scheduler (stessa base)
import json as _json_smooth
_pc_disk_path = os.path.join("cache", "prev_composite.json")
_prev_composite = None
try:
    if os.path.exists(_pc_disk_path):
        with open(_pc_disk_path, "r") as _pcf:
            _prev_composite = _json_smooth.load(_pcf)
except Exception:
    pass
if _prev_composite is None:
    _prev_composite = st.session_state.get("_prev_composite", None)
composite = smooth_composite_scores(composite, _prev_composite)
st.session_state["_prev_composite"] = composite  # salva anche in session per fallback
analysis["composite"] = composite  # aggiorna anche l'analysis dict

# ═══════════════════════════════════════════════════════════════════════════════
# SESSIONE & CALENDARIO ECONOMICO
# ═══════════════════════════════════════════════════════════════════════════════

session_info = get_current_sessions()

# Fetch calendario (con cache interna ogni 4h)
try:
    calendar_events = fetch_calendar()
except Exception:
    calendar_events = []

news_impact = get_news_impact_for_pairs(calendar_events) if calendar_events else {}
upcoming_events = get_upcoming_events(calendar_events, hours_ahead=12) if calendar_events else []
recent_events = get_recent_events(calendar_events, hours_back=4) if calendar_events else []

# Indicatore sessione in cima alla pagina
_session_cols = st.columns([3, 2])
with _session_cols[0]:
    st.markdown(
        f"<div style='background:#1a1a2e; color:white; padding:8px 16px; "
        f"border-radius:8px; display:inline-block; font-size:0.9rem;'>"
        f"🕐 <b>{session_info['session_label']}</b> — "
        f"{session_info['utc_now'].strftime('%H:%M')} UTC</div>",
        unsafe_allow_html=True,
    )
with _session_cols[1]:
    # Warning notizie imminenti
    _suppress_ccys = [c for c, v in news_impact.items() if v["status"] == "SUPPRESS"]
    _warn_ccys = [c for c, v in news_impact.items() if v["status"] == "WARNING"]
    if _suppress_ccys:
        st.warning(f"🔴 News macro recente su: **{', '.join(_suppress_ccys)}** — segnali soppressi")
    elif _warn_ccys:
        st.info(f"⚠️ News in arrivo su: **{', '.join(_warn_ccys)}**")


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER GRAFICI
# ═══════════════════════════════════════════════════════════════════════════════

def strength_color(score: float) -> str:
    if score >= THRESHOLD_EXTREME_BULL:
        return "#00c853"
    elif score >= THRESHOLD_STRONG_BULL:
        return "#66bb6a"
    elif score <= THRESHOLD_EXTREME_BEAR:
        return "#ff1744"
    elif score <= THRESHOLD_STRONG_BEAR:
        return "#ef5350"
    else:
        return "#78909c"


def classification_emoji(cls: str) -> str:
    return {"TREND_FOLLOWING": "📈", "MEAN_REVERTING": "🔄", "MIXED": "⚖️"}.get(cls, "")


def _signal_label(score: float) -> str:
    """Restituisce etichetta di segnale stile Smart Quant."""
    if score >= 80:
        return "STRONG BUY"
    elif score >= 65:
        return "BUY"
    elif score >= 55:
        return "SLIGHT BUY"
    elif score >= 45:
        return "NEUTRAL"
    elif score >= 35:
        return "SLIGHT SELL"
    elif score >= 20:
        return "SELL"
    else:
        return "STRONG SELL"


def _signal_color(score: float) -> str:
    """Colore principale del gauge in base allo score."""
    if score >= 80:
        return "#00c853"
    elif score >= 65:
        return "#4caf50"
    elif score >= 55:
        return "#8bc34a"
    elif score >= 45:
        return "#78909c"
    elif score >= 35:
        return "#ff9800"
    elif score >= 20:
        return "#f44336"
    else:
        return "#b71c1c"


def _label_color(label: str) -> str:
    """Colore testo del label."""
    mapping = {
        "STRONG BUY": "#00c853",
        "BUY": "#4caf50",
        "SLIGHT BUY": "#8bc34a",
        "NEUTRAL": "#78909c",
        "SLIGHT SELL": "#ff9800",
        "SELL": "#f44336",
        "STRONG SELL": "#b71c1c",
    }
    return mapping.get(label, "#78909c")


def make_gauge_chart(score: float, currency: str) -> go.Figure:
    """
    Crea un mini grafico a ciambella (gauge) stile Smart Quant.
    Cerchio colorato con score al centro e barra dei segmenti colorati sotto.
    """
    label = _signal_label(score)
    main_color = _signal_color(score)

    # Arco di score (filled) + remainder (grigio scuro)
    fig = go.Figure()

    # Segmenti colorati della scala 0-100 (come la barra nel widget)
    segment_colors = [
        "#b71c1c",  # 0-10   STRONG SELL
        "#f44336",  # 10-20  SELL
        "#ff9800",  # 20-30  SELL
        "#ffc107",  # 30-40  SLIGHT SELL
        "#ffeb3b",  # 40-50  NEUTRAL
        "#c6ff00",  # 50-60  SLIGHT BUY
        "#8bc34a",  # 60-70  BUY
        "#4caf50",  # 70-80  BUY
        "#00c853",  # 80-90  STRONG BUY
        "#00e676",  # 90-100 STRONG BUY
    ]

    # Donut gauge principale
    fig.add_trace(go.Pie(
        values=[score, 100 - score],
        hole=0.75,
        marker=dict(
            colors=[main_color, "#2a2a3d"],
            line=dict(color="#1e1e2f", width=2),
        ),
        textinfo="none",
        hoverinfo="none",
        rotation=90,
        sort=False,
        direction="clockwise",
    ))

    # Score al centro
    fig.add_annotation(
        text=f"<b>{score:.0f}</b>",
        x=0.5, y=0.55,
        xref="paper", yref="paper",
        showarrow=False,
        font=dict(size=36, color="white", family="Arial Black"),
    )

    # Label sotto lo score
    fig.add_annotation(
        text=f"<b>{label}</b>",
        x=0.5, y=0.92,
        xref="paper", yref="paper",
        showarrow=False,
        font=dict(size=13, color=_label_color(label), family="Arial"),
    )

    # Sottotitolo "/ 100"
    fig.add_annotation(
        text="100",
        x=0.5, y=0.40,
        xref="paper", yref="paper",
        showarrow=False,
        font=dict(size=12, color="#888"),
    )

    # Barra segmenti colorati sotto il gauge (posizionata come shapes)
    n_seg = len(segment_colors)
    seg_w = 0.8 / n_seg
    x_start = 0.1
    # Determina quale segmento è "attivo" in base allo score
    active_seg = min(int(score / 10), n_seg - 1)

    for idx, clr in enumerate(segment_colors):
        opacity = 1.0 if idx == active_seg else 0.3
        fig.add_shape(
            type="rect",
            x0=x_start + idx * seg_w,
            x1=x_start + (idx + 1) * seg_w - 0.005,
            y0=0.02, y1=0.08,
            xref="paper", yref="paper",
            fillcolor=clr,
            opacity=opacity,
            line=dict(width=0),
        )
        # Numero nel segmento
        fig.add_annotation(
            text=f"{(idx + 1) * 10}",
            x=x_start + idx * seg_w + seg_w / 2,
            y=0.05,
            xref="paper", yref="paper",
            showarrow=False,
            font=dict(size=7, color="white" if idx == active_seg else "#aaa"),
        )

    # Barra colorata top
    fig.add_shape(
        type="rect",
        x0=0, x1=1, y0=0.97, y1=1.0,
        xref="paper", yref="paper",
        fillcolor=main_color,
        line=dict(width=0),
    )

    fig.update_layout(
        showlegend=False,
        height=240,
        margin=dict(l=5, r=5, t=10, b=10),
        paper_bgcolor="#1e1e2f",
        plot_bgcolor="#1e1e2f",
    )

    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 1: BARRA DI FORZA COMPOSITA
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("🏆 Classifica Forza Valutaria (Score Composito 0-100)")

# Ordina per score
sorted_ccys = sorted(composite.keys(), key=lambda c: composite[c]["composite"],
                     reverse=True)

# Bar chart orizzontale
fig_bar = go.Figure()
scores_list = [composite[c]["composite"] for c in sorted_ccys]
colors = [strength_color(s) for s in scores_list]

fig_bar.add_trace(go.Bar(
    y=sorted_ccys,
    x=scores_list,
    orientation="h",
    marker_color=colors,
    text=[f"{s:.0f}" for s in scores_list],
    textposition="inside",
    textfont=dict(size=16, color="white"),
))

# Soglie verticali
for thresh, name, color in [
    (THRESHOLD_EXTREME_BULL, "Estremo Bull", "green"),
    (THRESHOLD_STRONG_BULL, "Forte Bull", "lightgreen"),
    (THRESHOLD_STRONG_BEAR, "Forte Bear", "salmon"),
    (THRESHOLD_EXTREME_BEAR, "Estremo Bear", "red"),
    (50, "Neutro", "gray"),
]:
    fig_bar.add_vline(x=thresh, line_dash="dash", line_color=color,
                      annotation_text=name, annotation_position="top")

fig_bar.update_layout(
    height=400,
    xaxis=dict(range=[0, 100], title="Score"),
    yaxis=dict(autorange="reversed"),
    margin=dict(l=60, r=20, t=30, b=40),
    plot_bgcolor="#fafafa",
)
st.plotly_chart(fig_bar, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 2: GAUGE CHARTS (stile Smart Quant)
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📊 Gauge di Forza per Valuta")

# Mostriamo 4 valute per riga
row1_ccys = sorted_ccys[:4]
row2_ccys = sorted_ccys[4:]

for row_ccys in [row1_ccys, row2_ccys]:
    cols = st.columns(len(row_ccys))
    for i, ccy in enumerate(row_ccys):
        info = composite[ccy]
        score = info["composite"]
        mom = momentum.get(ccy, {})
        delta_val = mom.get("delta", 0)

        with cols[i]:
            st.markdown(
                f"<h4 style='text-align:center; margin-bottom:0;'>{ccy}</h4>",
                unsafe_allow_html=True,
            )
            fig_gauge = make_gauge_chart(score, ccy)
            st.plotly_chart(fig_gauge, use_container_width=True, key=f"gauge_{ccy}")

            # Dettaglio sotto il gauge
            delta_str = f"{delta_val:+.1f}" if delta_val != 0 else "0"
            delta_color = "#4caf50" if delta_val > 0 else ("#f44336" if delta_val < 0 else "#888")
            st.markdown(
                f"<p style='text-align:center; margin:0; font-size:0.85rem;'>"
                f"Momentum: <span style='color:{delta_color};font-weight:bold;'>"
                f"{delta_str}</span></p>",
                unsafe_allow_html=True,
            )
            # Candle-9 signal
            c9 = candle9.get(ccy, {})
            c9_signal = c9.get("candle9_signal", "➖ NEUTRO")
            c9_ratio = c9.get("candle9_ratio", 0)
            c9_color = "#4caf50" if c9_ratio > 0 else "#f44336" if c9_ratio < 0 else "#888"
            st.markdown(
                f"<p style='text-align:center; margin:0; font-size:0.80rem;'>"
                f"Candle 9: <span style='color:{c9_color};font-weight:bold;'>"
                f"{c9_signal}</span> "
                f"<span style='color:{c9_color};font-size:0.75rem;'>({c9_ratio:+.2f}%)</span></p>",
                unsafe_allow_html=True,
            )
            if is_composite:
                _d1_decay = info.get('d1_decay_pct', 0)
                _decay_tag = f" | ⏬D1 −{_d1_decay}%" if _d1_decay > 0 else ""
                st.caption(
                    f"H1: {info.get('h1_score', '—')} | H4: {info.get('h4_score', '—')} | D1: {info.get('d1_score', '—')}{_decay_tag}"
                )
                concordance = info.get("concordance", "")
                if concordance:
                    st.caption(concordance)
            else:
                st.caption(
                    f"PA: {info['price_score']:.0f} | "
                    f"Vol: {info['volume_score']:.0f} | "
                    f"COT: {info['cot_score']:.0f}"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 2B: CONFRONTO H1 vs H4 vs D1 (solo in modalità Composito)
# ═══════════════════════════════════════════════════════════════════════════════

if is_composite:
    st.divider()
    st.subheader("⚖️ Confronto H1 vs H4 vs D1 per Valuta")
    st.caption(
        f"H1 (reattività, peso {COMPOSITE_WEIGHT_H1:.0%}) vs "
        f"H4 (stabilità, peso {COMPOSITE_WEIGHT_H4:.0%}) vs "
        f"D1 (trend di fondo, peso {COMPOSITE_WEIGHT_D1:.0%}) — "
        "il blend produce lo Score Composito finale. "
        "Se H1 e H4 divergono, il peso D1 viene ridotto (⏬Decay) per accelerare le transizioni."
    )

    # Tabella comparativa
    compare_rows = []
    for ccy in sorted_ccys:
        info = composite[ccy]
        h1_s = info.get("h1_score", 50)
        h4_s = info.get("h4_score", 50)
        d1_s = info.get("d1_score", 50)
        decay = info.get("d1_decay_pct", 0)
        compare_rows.append({
            "Valuta": ccy,
            "Score H1": h1_s,
            "Score H4": h4_s,
            "Score D1": d1_s,
            "⏬D1 Decay": f"−{decay}%" if decay > 0 else "—",
            "Score Composito": info["composite"],
            "Concordanza": info.get("concordance", "—"),
        })

    compare_df = pd.DataFrame(compare_rows)
    st.dataframe(
        compare_df,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Score H1": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.0f",
            ),
            "Score H4": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.0f",
            ),
            "Score D1": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.0f",
            ),
            "Score Composito": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.0f",
            ),
        },
    )

    # Grafico confronto H1 vs H4 vs D1
    fig_compare = go.Figure()
    ccys_compare = [r["Valuta"] for r in compare_rows]
    h1_scores = [r["Score H1"] for r in compare_rows]
    h4_scores = [r["Score H4"] for r in compare_rows]
    d1_scores = [r["Score D1"] for r in compare_rows]
    comp_scores = [r["Score Composito"] for r in compare_rows]

    fig_compare.add_trace(go.Bar(
        name="H1 (reattività)",
        x=ccys_compare, y=h1_scores,
        marker_color="#ff9800", opacity=0.7,
    ))
    fig_compare.add_trace(go.Bar(
        name="H4 (stabilità)",
        x=ccys_compare, y=h4_scores,
        marker_color="#2196f3", opacity=0.7,
    ))
    fig_compare.add_trace(go.Bar(
        name="D1 (trend di fondo)",
        x=ccys_compare, y=d1_scores,
        marker_color="#9c27b0", opacity=0.7,
    ))
    fig_compare.add_trace(go.Scatter(
        name="Composito",
        x=ccys_compare, y=comp_scores,
        mode="markers+lines",
        marker=dict(size=12, color="#e91e63", symbol="diamond"),
        line=dict(color="#e91e63", width=3),
    ))

    fig_compare.add_hline(y=50, line_dash="dash", line_color="gray",
                          annotation_text="Neutro")
    fig_compare.update_layout(
        height=400,
        yaxis=dict(range=[0, 100], title="Score"),
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
        margin=dict(l=40, r=20, t=40, b=40),
        plot_bgcolor="#fafafa",
    )
    st.plotly_chart(fig_compare, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 3: MOMENTUM – CHI GUADAGNA / PERDE FORZA
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
col_gain, col_lose = st.columns(2)

with col_gain:
    st.subheader("🚀 Guadagnano Forza Rapidamente")
    gainers = sorted(momentum.items(), key=lambda x: x[1]["delta"], reverse=True)
    gainers_df = pd.DataFrame([
        {
            "Valuta": ccy,
            "Δ Forza": f"{m['delta']:+.2f}",
            "Accelerazione": f"{m['acceleration']:+.2f}",
            "Stato": m["rank_label"],
        }
        for ccy, m in gainers[:4]
        if m["delta"] > 0
    ])
    if not gainers_df.empty:
        st.dataframe(gainers_df, hide_index=True, use_container_width=True)
    else:
        st.info("Nessuna valuta in forte accelerazione rialzista")

with col_lose:
    st.subheader("📉 Perdono Forza Rapidamente")
    losers = sorted(momentum.items(), key=lambda x: x[1]["delta"])
    losers_df = pd.DataFrame([
        {
            "Valuta": ccy,
            "Δ Forza": f"{m['delta']:+.2f}",
            "Accelerazione": f"{m['acceleration']:+.2f}",
            "Stato": m["rank_label"],
        }
        for ccy, m in losers[:4]
        if m["delta"] < 0
    ])
    if not losers_df.empty:
        st.dataframe(losers_df, hide_index=True, use_container_width=True)
    else:
        st.info("Nessuna valuta in forte decelerazione")


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 3B: CANDLE-9 PRICE ACTION (close attuale vs 9 candele fa)
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("🕯️ Candle-9 Price Action")
st.caption(
    "Confronta il prezzo di chiusura attuale con quello di 9 candele fa per ogni valuta. "
    "Se il close è superiore → segnale di **forza** (🟢); se inferiore → segnale di **debolezza** (🔴)."
)

c9_sorted = sorted(
    candle9.items(),
    key=lambda x: x[1].get("candle9_ratio", 0),
    reverse=True,
)

c9_bull = [(ccy, c9) for ccy, c9 in c9_sorted if c9.get("candle9_ratio", 0) > 0.05]
c9_bear = [(ccy, c9) for ccy, c9 in c9_sorted if c9.get("candle9_ratio", 0) < -0.05]
c9_neutral = [(ccy, c9) for ccy, c9 in c9_sorted
              if -0.05 <= c9.get("candle9_ratio", 0) <= 0.05]

c9_col1, c9_col2, c9_col3 = st.columns(3)

with c9_col1:
    st.markdown("#### 🟢 Forza (Close > Candle 9)")
    if c9_bull:
        c9_bull_df = pd.DataFrame([
            {
                "Valuta": ccy,
                "Δ vs C9": f"{c9['candle9_ratio']:+.3f}%",
                "Segnale": c9["candle9_signal"],
            }
            for ccy, c9 in c9_bull
        ])
        st.dataframe(c9_bull_df, hide_index=True, use_container_width=True)
    else:
        st.info("Nessuna valuta con segnale bullish")

with c9_col2:
    st.markdown("#### 🔴 Debolezza (Close < Candle 9)")
    if c9_bear:
        c9_bear_df = pd.DataFrame([
            {
                "Valuta": ccy,
                "Δ vs C9": f"{c9['candle9_ratio']:+.3f}%",
                "Segnale": c9["candle9_signal"],
            }
            for ccy, c9 in c9_bear
        ])
        st.dataframe(c9_bear_df, hide_index=True, use_container_width=True)
    else:
        st.info("Nessuna valuta con segnale bearish")

with c9_col3:
    st.markdown("#### ➖ Neutro")
    if c9_neutral:
        c9_neutral_df = pd.DataFrame([
            {
                "Valuta": ccy,
                "Δ vs C9": f"{c9['candle9_ratio']:+.3f}%",
                "Segnale": c9["candle9_signal"],
            }
            for ccy, c9 in c9_neutral
        ])
        st.dataframe(c9_neutral_df, hide_index=True, use_container_width=True)
    else:
        st.info("—")

# Barchart Candle-9
fig_c9 = go.Figure()
c9_ccys = [ccy for ccy, _ in c9_sorted]
c9_vals = [c9.get("candle9_ratio", 0) for _, c9 in c9_sorted]
c9_colors = ["#4caf50" if v > 0.05 else "#f44336" if v < -0.05 else "#78909c"
             for v in c9_vals]

fig_c9.add_trace(go.Bar(
    x=c9_ccys,
    y=c9_vals,
    marker_color=c9_colors,
    text=[f"{v:+.3f}%" for v in c9_vals],
    textposition="outside",
    textfont=dict(size=12),
))
fig_c9.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
fig_c9.update_layout(
    height=300,
    yaxis_title="Δ % vs Candle 9",
    xaxis_title="Valuta",
    margin=dict(l=40, r=20, t=20, b=40),
    plot_bgcolor="#fafafa",
)
st.plotly_chart(fig_c9, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 4: TREND FOLLOWING vs MEAN REVERTING
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("📈 Classificazione: Trend Following vs Mean Reverting")

col_tf, col_mr = st.columns(2)

with col_tf:
    st.markdown("#### 📈 Favorevoli al Trend Following")
    st.caption("ADX alto, Hurst > 0.5, alta Efficiency Ratio → mercato direzionale")
    tf_list = [
        (ccy, c) for ccy, c in classification.items()
        if c["classification"] == "TREND_FOLLOWING"
    ]
    tf_list.sort(key=lambda x: x[1]["trend_score"], reverse=True)

    if tf_list:
        for ccy, c in tf_list:
            score_comp = composite[ccy]["composite"]
            direction = "LONG" if score_comp >= 50 else "SHORT"
            st.markdown(
                f'<div class="trend-follow">'
                f'<b>{ccy}</b> — Trend Score: {c["trend_score"]:.0f}/100 '
                f'(ADX: {c["adx_avg"]:.0f}, Hurst: {c["hurst"]:.2f}, '
                f'ER: {c["eff_ratio"]:.2f}) — Direzione: <b>{direction}</b>'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("Nessuna valuta attualmente in regime trending chiaro")

with col_mr:
    st.markdown("#### 🔄 Favorevoli al Mean Reverting")
    st.caption("ADX basso, Hurst < 0.5, bassa Efficiency Ratio → mercato laterale")
    mr_list = [
        (ccy, c) for ccy, c in classification.items()
        if c["classification"] == "MEAN_REVERTING"
    ]
    mr_list.sort(key=lambda x: x[1]["trend_score"])

    if mr_list:
        for ccy, c in mr_list:
            st.markdown(
                f'<div class="mean-revert">'
                f'<b>{ccy}</b> — Trend Score: {c["trend_score"]:.0f}/100 '
                f'(ADX: {c["adx_avg"]:.0f}, Hurst: {c["hurst"]:.2f}, '
                f'ER: {c["eff_ratio"]:.2f})'
                f'</div>',
                unsafe_allow_html=True,
            )
    else:
        st.info("Nessuna valuta in regime mean-reverting chiaro")


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 5: ALERT & SOGLIE
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("🚨 Alert e Soglie di Attenzione")

alerts = []
for ccy in sorted_ccys:
    info = composite[ccy]
    if info.get("alert"):
        alerts.append({"Valuta": ccy, "Score": info["composite"],
                       "Alert": info["alert"]})

if alerts:
    for a in alerts:
        st.markdown(
            f'<div class="alert-box">'
            f'<b>{a["Valuta"]}</b> (Score: {a["Score"]:.0f}) — {a["Alert"]}'
            f'</div>',
            unsafe_allow_html=True,
        )
else:
    st.success("✅ Nessun alert attivo — tutte le valute entro soglie normali")


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 5B: VOLATILITÀ (ATR)
# ═══════════════════════════════════════════════════════════════════════════════

if atr_context:
    st.divider()
    st.subheader("🌊 Volatilità & Velocità per Valuta")
    st.caption("ATR = volatilità del mercato. Velocity = quanto rapidamente "
               "la valuta ha raggiunto il livello attuale di forza/debolezza.")

    vol_emoji = {"LOW": "🟢", "NORMAL": "🔵", "HIGH": "🟠", "EXTREME": "🔴"}
    vol_rows = []
    for ccy in sorted_ccys:
        ac = atr_context.get(ccy, {})
        vc = velocity.get(ccy, {})
        regime = ac.get("volatility_regime", "NORMAL")
        vel_label = vc.get("velocity_label", "N/A")
        vel_norm = vc.get("velocity_norm", 50)
        bars = vc.get("bars_to_move", 0)
        vol_rows.append({
            "Valuta": ccy,
            "ATR %": round(ac.get("atr_pct", 0), 4),
            "Percentile ATR": round(ac.get("atr_percentile", 50), 1),
            "Regime": f"{vol_emoji.get(regime, '')} {regime}",
            "Velocity": vel_norm,
            "Velocità": vel_label,
            "Barre": bars,
        })

    st.dataframe(
        pd.DataFrame(vol_rows),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Percentile ATR": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.0f",
            ),
            "Velocity": st.column_config.ProgressColumn(
                min_value=0, max_value=100, format="%.0f",
            ),
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 6: FORZA VALUTARIA — LINEE STORICHE (stile MetaTrader)
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("📉 Forza Valutaria — Linee Storiche")
st.caption(
    "Ogni valuta è rappresentata da una linea oscillante (0–100). "
    "Attiva/disattiva ciascuna valuta cliccando sul tab corrispondente. "
    "Le zone colorate indicano **ipercomprato** (≥ {ob}) e **ipervenduto** (≤ {os}).".format(
        ob=THRESHOLD_EXTREME_BULL, os=THRESHOLD_EXTREME_BEAR,
    )
)

if not rolling.empty:
    # ── I dati sono già score compositi 0-100 (PA + Volume + COT) ───────
    # Smoothing leggero con EMA per curve più pulite nel grafico
    _smoothed = rolling.ewm(span=6, min_periods=3).mean()
    rolling_score = _smoothed.clip(0, 100).dropna(how="all")

    # Resample a 4H se troppi punti (per pulizia visiva)
    if len(rolling_score) > 250:
        rolling_score = rolling_score.resample("4h").mean().dropna(how="all")

    # ── Colori BOLD stile MetaTrader (alta separazione visiva) ──────────
    ccy_colors = {
        "EUR": "#3399FF",   # blu intenso
        "GBP": "#00CC00",   # verde acceso
        "AUD": "#FF9900",   # arancione
        "NZD": "#00CCCC",   # ciano
        "CAD": "#996633",   # marrone
        "CHF": "#CC66FF",   # viola
        "JPY": "#FF3333",   # rosso
        "USD": "#FFFFFF",   # bianco (risalta su sfondo scuro)
    }

    # ── CSS per tab / strip ─────────────────────────────────────────────
    st.markdown("""
    <style>
    .ccy-tab-row {display:flex; gap:0; margin-bottom:0.2rem;}
    .ccy-tab {
        flex:1; text-align:center; padding:7px 4px 5px;
        cursor:pointer; font-weight:700; font-size:0.82rem;
        border-bottom:3px solid transparent;
        transition: opacity 0.15s;
    }
    .ccy-tab.active {opacity:1;}
    .ccy-tab.inactive {opacity:0.35;}
    .ccy-current-strip {
        display: flex; gap: 4px; flex-wrap: wrap;
        margin-top: 0.5rem;
    }
    .ccy-current-card {
        text-align: center;
        padding: 8px 6px;
        border-radius: 0 0 6px 6px;
        flex: 1;
        min-width: 80px;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Tab di selezione ────────────────────────────────────────────────
    # Tutte le valute attive al primo caricamento; la scelta persiste in session_state
    if "strength_inited" not in st.session_state:
        for ccy in CURRENCIES:
            st.session_state[f"strength_toggle_{ccy}"] = True
        st.session_state["strength_inited"] = True
    tab_cols = st.columns(len(CURRENCIES))
    active_ccys = []
    for idx, ccy in enumerate(CURRENCIES):
        with tab_cols[idx]:
            col_color = ccy_colors.get(ccy, "#888")
            last_score = 50.0
            if ccy in rolling_score.columns:
                _s = rolling_score[ccy].dropna()
                if not _s.empty:
                    last_score = _s.iloc[-1]
            # Barra colorata sopra il checkbox
            st.markdown(
                f"<div style='height:5px;background:{col_color};border-radius:3px 3px 0 0;margin-bottom:2px;'></div>",
                unsafe_allow_html=True,
            )
            is_on = st.checkbox(
                f"{ccy}",
                key=f"strength_toggle_{ccy}",
            )
            # Score corrente sotto il checkbox
            _score_color = col_color if is_on else "#555"
            st.markdown(
                f"<div style='text-align:center;margin-top:-8px;font-size:1.1rem;"
                f"font-weight:800;color:{_score_color};'>{last_score:.0f}</div>",
                unsafe_allow_html=True,
            )
            if is_on:
                active_ccys.append(ccy)

    # ── Grafico principale ──────────────────────────────────────────────
    if active_ccys and not rolling_score.empty:
        fig_strength = go.Figure()

        for ccy in active_ccys:
            if ccy not in rolling_score.columns:
                continue
            y_data = rolling_score[ccy].dropna()
            if y_data.empty:
                continue
            fig_strength.add_trace(go.Scatter(
                x=y_data.index,
                y=y_data,
                name=ccy,
                line=dict(
                    color=ccy_colors.get(ccy, "gray"),
                    width=2.8,
                    shape="spline",       # curva interpolata
                    smoothing=1.0,
                ),
                mode="lines",
                hovertemplate=f"<b>{ccy}</b>: %{{y:.1f}}<extra></extra>",
            ))
            # Etichetta a destra dell'ultima barra
            fig_strength.add_annotation(
                x=y_data.index[-1],
                y=y_data.iloc[-1],
                text=f"<b>{ccy}</b>",
                showarrow=False,
                xanchor="left",
                xshift=10,
                font=dict(
                    color=ccy_colors.get(ccy, "gray"),
                    size=13,
                    family="Arial Black",
                ),
            )

        # ── Zone ipercomprato / ipervenduto ─────────────────────────────
        fig_strength.add_hrect(
            y0=THRESHOLD_EXTREME_BULL, y1=100,
            fillcolor="rgba(0,200,83,0.08)", line_width=0,
        )
        fig_strength.add_hline(
            y=THRESHOLD_EXTREME_BULL, line_dash="dash",
            line_color="rgba(0,200,83,0.55)", line_width=1.2,
            annotation_text="Ipercomprato",
            annotation_position="top left",
            annotation=dict(font=dict(size=10, color="rgba(0,200,83,0.8)")),
        )
        fig_strength.add_hline(
            y=THRESHOLD_STRONG_BULL, line_dash="dot",
            line_color="rgba(102,187,106,0.25)", line_width=0.8,
        )

        # Linea neutra 50
        fig_strength.add_hline(
            y=50, line_dash="dash",
            line_color="rgba(180,180,200,0.35)", line_width=1,
            annotation_text="0.00",
            annotation_position="left",
            annotation=dict(font=dict(size=9, color="rgba(180,180,200,0.6)")),
        )

        fig_strength.add_hline(
            y=THRESHOLD_STRONG_BEAR, line_dash="dot",
            line_color="rgba(239,83,80,0.25)", line_width=0.8,
        )
        fig_strength.add_hline(
            y=THRESHOLD_EXTREME_BEAR, line_dash="dash",
            line_color="rgba(255,23,68,0.55)", line_width=1.2,
            annotation_text="Ipervenduto",
            annotation_position="bottom left",
            annotation=dict(font=dict(size=10, color="rgba(255,23,68,0.8)")),
        )
        fig_strength.add_hrect(
            y0=0, y1=THRESHOLD_EXTREME_BEAR,
            fillcolor="rgba(255,23,68,0.08)", line_width=0,
        )

        # ── Controllo range asse Y (come range-slider orizzontale) ──────
        y_range = st.slider(
            "🔍 Range asse verticale (Forza)",
            min_value=-10, max_value=110,
            value=(0, 100),
            step=5,
            key="strength_y_range",
            help="Trascina le maniglie per ingrandire o rimpicciolire la scala verticale",
        )

        # ── Layout scuro stile MetaTrader ───────────────────────────────
        fig_strength.update_layout(
            height=600,
            dragmode="pan",
            yaxis=dict(
                range=[y_range[0], y_range[1]],
                fixedrange=False,
                title="",
                gridcolor="rgba(60,60,100,0.20)",
                showgrid=True,
                zeroline=False,
                tickfont=dict(size=10),
                side="right",
                dtick=max(5, (y_range[1] - y_range[0]) // 10),
            ),
            xaxis=dict(
                title="",
                gridcolor="rgba(60,60,100,0.12)",
                showgrid=True,
                tickfont=dict(size=10),
                rangeslider=dict(
                    visible=True,
                    thickness=0.08,
                    bgcolor="#111125",
                    bordercolor="#333",
                    borderwidth=1,
                ),
                spikecolor="rgba(255,255,255,0.7)",
                spikethickness=1,
                spikemode="across",
                spikedash="dot",
            ),
            yaxis_spikecolor="rgba(255,255,255,0.7)",
            yaxis_spikethickness=1,
            yaxis_spikemode="across",
            yaxis_spikedash="dot",
            spikedistance=-1,
            legend=dict(
                orientation="h",
                yanchor="bottom", y=1.02,
                xanchor="center", x=0.5,
                font=dict(size=12, color="#ddd"),
                bgcolor="rgba(0,0,0,0)",
            ),
            margin=dict(l=10, r=90, t=30, b=10),
            plot_bgcolor="#0d0d1f",
            paper_bgcolor="#0d0d1f",
            font=dict(color="#aab0d0"),
            hovermode="x unified",
            hoverlabel=dict(bgcolor="#1a1a30", font_size=12, font_color="#eee"),
        )

        st.plotly_chart(
            fig_strength,
            use_container_width=True,
            config={
                "scrollZoom": True,
                "displayModeBar": True,
                "modeBarButtonsToAdd": ["pan2d", "zoomIn2d", "zoomOut2d", "resetScale2d"],
                "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                "displaylogo": False,
            },
        )

        # ── Strip riepilogativa sotto il grafico ────────────────────────
        strip_html = '<div class="ccy-current-strip">'
        for ccy in active_ccys:
            if ccy not in rolling_score.columns:
                continue
            s = rolling_score[ccy].dropna()
            if s.empty:
                continue
            val = s.iloc[-1]
            col = ccy_colors.get(ccy, "#888")
            if val >= THRESHOLD_EXTREME_BULL:
                zone, zclr = "IPERCOMPRATO", "#00e676"
            elif val >= THRESHOLD_STRONG_BULL:
                zone, zclr = "FORTE", "#66bb6a"
            elif val <= THRESHOLD_EXTREME_BEAR:
                zone, zclr = "IPERVENDUTO", "#ff1744"
            elif val <= THRESHOLD_STRONG_BEAR:
                zone, zclr = "DEBOLE", "#ef5350"
            else:
                zone, zclr = "NEUTRO", "#78909c"
            strip_html += (
                f'<div class="ccy-current-card" '
                f'style="border-top:3px solid {col};background:#111125;">'
                f'<span style="color:{col};font-weight:700;font-size:0.95rem;">{ccy}</span><br>'
                f'<span style="font-size:1.4rem;font-weight:800;color:white;">{val:.0f}</span><br>'
                f'<span style="font-size:0.75rem;color:{zclr};font-weight:600;">{zone}</span>'
                f'</div>'
            )
        strip_html += '</div>'
        st.markdown(strip_html, unsafe_allow_html=True)

    else:
        st.info("Seleziona almeno una valuta per visualizzare il grafico.")
else:
    st.info("Dati storici insufficienti per il grafico rolling")


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 6B: RADAR CHART PER VALUTA
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("🕸️ Profilo Radar per Valuta")
st.caption("5 dimensioni: Price Action, Volume, COT, Momentum (normalizzato), "
           "Trend Score — più ampia l'area, più forte il segnale complessivo.")

# Radar: 2 righe da 4
radar_row1 = sorted_ccys[:4]
radar_row2 = sorted_ccys[4:]

color_map = {
    "USD": "#1f77b4", "EUR": "#ff7f0e", "GBP": "#2ca02c",
    "JPY": "#d62728", "CHF": "#9467bd", "AUD": "#8c564b",
    "NZD": "#e377c2", "CAD": "#7f7f7f",
}

def _hex_to_rgba(hex_color: str, alpha: float = 0.2) -> str:
    """Convert hex color to rgba string for Plotly compatibility."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

for row_ccys in [radar_row1, radar_row2]:
    cols_radar = st.columns(len(row_ccys))
    for i, ccy in enumerate(row_ccys):
        info = composite[ccy]
        cls = classification.get(ccy, {})
        mom = momentum.get(ccy, {})

        # Normalizza momentum delta a 0-100 scale (centrato su 50)
        raw_mom = mom.get("delta", 0)
        mom_norm = 50 + np.clip(raw_mom * 5, -50, 50)

        categories = ["Price Action", "Volume", "COT", "Momentum", "Trend Score"]
        values = [
            info["price_score"],
            info["volume_score"],
            info["cot_score"],
            mom_norm,
            cls.get("trend_score", 50),
        ]
        # Chiudi il radar
        values_closed = values + [values[0]]
        cats_closed = categories + [categories[0]]

        ccy_color = color_map.get(ccy, "#888888")
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=cats_closed,
            fill="toself",
            fillcolor=_hex_to_rgba(ccy_color, 0.2),
            line=dict(color=ccy_color, width=2),
            name=ccy,
        ))
        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 100], showticklabels=False),
                bgcolor="#fafafa",
            ),
            showlegend=False,
            height=250,
            margin=dict(l=30, r=30, t=30, b=30),
            title=dict(text=f"<b>{ccy}</b>", x=0.5, font=dict(size=14)),
        )

        with cols_radar[i]:
            st.plotly_chart(fig_radar, use_container_width=True, key=f"radar_{ccy}")


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 7: POSIZIONAMENTO COT
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("📋 Posizionamento COT (Commitments of Traders)")

cot_data_display = []
for ccy in sorted_ccys:
    cs = cot_scores.get(ccy, {})
    cot_data_display.append({
        "Valuta": ccy,
        "Score COT": cs.get("score", 50),
        "Percentile Net Spec.": cs.get("net_spec_percentile", 50),
        "Var. Settimanale": cs.get("weekly_change", 0),
        "Bias": cs.get("bias", "NEUTRAL"),
        "Estremo": cs.get("extreme") or "—",
    })

cot_df_display = pd.DataFrame(cot_data_display)
st.dataframe(cot_df_display, hide_index=True, use_container_width=True)

# Grafico COT storico
if not cot_ts.empty:
    st.markdown("##### Storico Net Speculative Positioning")
    fig_cot = go.Figure()
    for ccy in CURRENCIES:
        if ccy in cot_ts.columns:
            fig_cot.add_trace(go.Scatter(
                x=cot_ts.index, y=cot_ts[ccy],
                name=ccy,
                line=dict(width=2),
            ))
    fig_cot.update_layout(
        height=350,
        yaxis_title="Net Speculative Position (contratti)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=30, b=40),
        plot_bgcolor="#fafafa",
        hovermode="x unified",
    )
    fig_cot.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig_cot, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 8: TABELLA RIEPILOGATIVA COMPLETA
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("📋 Riepilogo Completo")

summary_rows = []
for ccy in sorted_ccys:
    info = composite[ccy]
    mom = momentum.get(ccy, {})
    cls = classification.get(ccy, {})
    cs = cot_scores.get(ccy, {})

    row = {
        "Valuta": ccy,
        "Score Composito": info["composite"],
        "Etichetta": info["label"],
    }

    if is_composite:
        row["Score H1"] = info.get("h1_score", "—")
        row["Score H4"] = info.get("h4_score", "—")
        row["Score D1"] = info.get("d1_score", "—")
        _decay = info.get("d1_decay_pct", 0)
        row["⏬D1 Decay"] = f"−{_decay}%" if _decay > 0 else "—"
        row["Concordanza"] = info.get("concordance", "—")

    row.update({
        "Price Action": info["price_score"],
        "Volume": info["volume_score"],
        "COT": info["cot_score"],
        "Δ Momentum": mom.get("delta", 0),
        "Candle 9": candle9.get(ccy, {}).get("candle9_signal", "➖ NEUTRO"),
        "Δ C9 %": candle9.get(ccy, {}).get("candle9_ratio", 0),
        "Regime": f'{classification_emoji(cls.get("classification", ""))} '
                  f'{cls.get("classification", "N/A")}',
        "Trend Score": cls.get("trend_score", 50),
        "ADX": cls.get("adx_avg", 0),
        "Hurst": cls.get("hurst", 0.5),
        "COT Bias": cs.get("bias", "NEUTRAL"),
    })

    summary_rows.append(row)

summary_df = pd.DataFrame(summary_rows)

col_config = {
    "Score Composito": st.column_config.ProgressColumn(
        min_value=0, max_value=100, format="%.0f",
    ),
    "Trend Score": st.column_config.ProgressColumn(
        min_value=0, max_value=100, format="%.0f",
    ),
}
if is_composite:
    col_config["Score H1"] = st.column_config.ProgressColumn(
        min_value=0, max_value=100, format="%.0f",
    )
    col_config["Score H4"] = st.column_config.ProgressColumn(
        min_value=0, max_value=100, format="%.0f",
    )

st.dataframe(
    summary_df,
    hide_index=True,
    use_container_width=True,
    column_config=col_config,
)


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 9: TRADE SETUP SCORE + HEATMAP
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("🎯 Trade Setup Score")
st.caption("Classifica delle coppie per qualità del setup: combina differenziale, "
           "momentum, regime, volatilità e COT in un punteggio 0-100.")

# ── Carica setup dallo stato alert (UNICA SORGENTE = stessa del Telegram) ──
_use_scheduler_setups = False
trade_setups = []
suppressed_setups = []
_alert_state_data = {}   # caricato una volta, riusato per Stato colonna

try:
    if os.path.exists(ALERT_STATE_FILE):
        with open(ALERT_STATE_FILE, "r", encoding="utf-8") as _asf:
            _alert_state_data = json.load(_asf)
        _as_updated = _alert_state_data.get("updated", "")
        if _as_updated:
            _as_dt = dt.datetime.fromisoformat(_as_updated)
            _as_age_h = (dt.datetime.now(_ROME) - _as_dt).total_seconds() / 3600
            if _as_age_h < 2.0 and _alert_state_data.get("all_setups"):
                trade_setups = _alert_state_data["all_setups"]
                suppressed_setups = _alert_state_data.get("suppressed_setups", [])
                _use_scheduler_setups = True
except Exception:
    pass

if not _use_scheduler_setups:
    # Fallback: calcola localmente (può divergere dal Telegram)
    trade_setups = compute_trade_setups(
        composite, momentum, classification, atr_context, cot_scores,
        velocity_scores=velocity,
        trend_structure=analysis.get("trend_structure"),
        strength_persistence=analysis.get("strength_persistence"),
        session_info=session_info,
        candle9=candle9,
    )
    suppressed_setups = []
    if trade_setups and news_impact:
        trade_setups, suppressed_setups = filter_setups_by_news(trade_setups, news_impact)

if _use_scheduler_setups:
    st.caption("📡 Dati sincronizzati con lo scheduler Telegram")
else:
    st.caption("⚠️ Dati calcolati localmente — lo scheduler non ha ancora eseguito")

if trade_setups:
    # ── Mostra variazioni A/A+ (info stabilizzazione da alert_state) ──
    _prev = set(_alert_state_data.get("pairs", []))
    _pair_details = _alert_state_data.get("pair_details", {})
    _pending_pairs = _alert_state_data.get("pending_pairs", {})

    if _use_scheduler_setups:
        # Quando sincronizzato: _current_top = set stabilizzato (= stessa del Telegram)
        _current_top = _prev.copy()
    else:
        # Fallback locale: calcola dal grade grezzo
        _current_top = {
            f"{s['pair']} {s['direction']}"
            for s in trade_setups
            if s["grade"] in ALERT_GRADES
        }
    # Escludi i pending da "NUOVO": sono segnali non ancora confermati
    _entered = _current_top - _prev - set(_pending_pairs.keys())
    _exited  = _prev - _current_top

    # Mostra segnali stabilizzati (in grace/hysteresis/residenza)
    _grace_signals = {
        k for k, v in _pair_details.items()
        if v.get("grace_counter", 0) > 0 and k in _prev
    }

    if _entered or _exited or _grace_signals or _pending_pairs:
        alert_col1, alert_col2, alert_col3, alert_col4 = st.columns(4)
        with alert_col1:
            if _entered:
                for p in sorted(_entered):
                    st.success(f"🟢 NUOVO: **{p}**")
        with alert_col2:
            if _exited:
                for p in sorted(_exited):
                    st.warning(f"🔴 RIMOSSO: **{p}**")
        with alert_col3:
            if _grace_signals:
                for p in sorted(_grace_signals):
                    gc = _pair_details[p].get("grace_counter", 0)
                    st.info(f"⏳ IN OSSERVAZIONE: **{p}** ({gc}h)")
        with alert_col4:
            if _pending_pairs:
                for p, info in sorted(_pending_pairs.items()):
                    cnt = info.get("consecutive_count", 0)
                    st.info(f"🔎 PENDING: **{p}** ({cnt}/{SIGNAL_CONFIRMATION_REFRESHES})")

    # Mostra setup soppressi per macro news
    if suppressed_setups:
        suppressed_aa = [s for s in suppressed_setups if s.get("grade") in ["A+", "A"]]
        if suppressed_aa:
            with st.expander(f"🚫 {len(suppressed_aa)} setup A/A+ soppressi per notizie macro", expanded=False):
                for s in suppressed_aa:
                    st.markdown(
                        f"**{s['pair']}** {s['direction']} — Grado {s['grade']} "
                        f"(Score {s['quality_score']:.0f})\n\n"
                        f"↳ _{s.get('suppressed_reason', 'Evento macro recente')}_"
                    )

    # Filtro per grado
    grade_filter = st.multiselect(
        "Filtra per Grado:", ["A+", "A", "B", "C", "D"],
        default=["A+", "A", "B"],
        key="grade_filter",
    )
    # Quando sincronizzato, inserisci active_setups (stabilizzati) nella lista
    if _use_scheduler_setups and ("A+" in grade_filter or "A" in grade_filter):
        _active_setups = _alert_state_data.get("active_setups", [])
        # Filtra active_setups per grado selezionato
        _active_filtered = [s for s in _active_setups
                            if s.get("grade", "D") in grade_filter]
        _active_map = {f"{s['pair']} {s['direction']}": s for s in _active_filtered}
        # Base: setup grezzi filtrati + active_setups stabilizzati (filtrati)
        _non_aa = [s for s in trade_setups
                   if s["grade"] in grade_filter
                   and f"{s['pair']} {s['direction']}" not in _active_map]
        filtered_setups = _active_filtered + _non_aa
    else:
        filtered_setups = [s for s in trade_setups if s["grade"] in grade_filter]

    # Sort by grade (A+ → A → B → C → D), then by quality_score descending
    _grade_order = {"A+": 0, "A": 1, "B": 2, "C": 3, "D": 4}
    filtered_setups.sort(
        key=lambda s: (_grade_order.get(s.get("grade", "D"), 4),
                       -s.get("quality_score", 0)))

    if filtered_setups:
        grade_emoji = {"A+": "🟢", "A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}

        # Costruisci mappa stato stabilizzazione per allineare tabella al Telegram
        _confirmed_set = _prev  # segnali già confermati nello stato
        _pending_set = set(_pending_pairs.keys())
        _hysteresis_set = set()  # segnali in isteresi: in _prev ma non più A/A+, score ≥ 55
        _grace_set = set()       # segnali in grace period
        _residence_set = set()   # segnali in residenza minima
        _grade_exit_threshold = 60 - GRADE_HYSTERESIS_POINTS

        for pk in _prev:
            if pk in _current_top:
                continue  # ancora A/A+
            # Cerca lo score corrente di questo setup
            _pk_setup = next((s for s in trade_setups
                              if f"{s['pair']} {s['direction']}" == pk), None)
            _pk_score = _pk_setup["quality_score"] if _pk_setup else 0
            _pk_detail = _pair_details.get(pk, {})
            if _pk_score >= _grade_exit_threshold:
                _hysteresis_set.add(pk)
            elif _pk_detail.get("entered_at"):
                import datetime as _dt_mod
                try:
                    _entered_at = _dt_mod.datetime.fromisoformat(_pk_detail["entered_at"])
                    _hours_in = (dt.datetime.now(_ROME) - _entered_at).total_seconds() / 3600
                    if _hours_in < SIGNAL_MIN_RESIDENCE_HOURS:
                        _residence_set.add(pk)
                    elif _pk_detail.get("grace_counter", 0) < SIGNAL_GRACE_REFRESHES:
                        _grace_set.add(pk)
                except (ValueError, TypeError):
                    pass

        setup_rows = []
        for s in filtered_setups[:15]:
            pk = f"{s['pair']} {s['direction']}"

            # Determina stato per questo setup
            if s["grade"] in ALERT_GRADES:
                if pk in _confirmed_set:
                    stato = "✅ Confermato"
                elif pk in _pending_set:
                    cnt = _pending_pairs.get(pk, {}).get("consecutive_count", 0)
                    stato = f"🔎 Pending ({cnt}/{SIGNAL_CONFIRMATION_REFRESHES})"
                elif pk in _hysteresis_set:
                    stato = "🔒 Isteresi"
                elif pk in _residence_set:
                    stato = "🕐 Residenza"
                elif pk in _grace_set:
                    gc = _pair_details.get(pk, {}).get("grace_counter", 0)
                    stato = f"⏳ Grace ({gc}/{SIGNAL_GRACE_REFRESHES})"
                else:
                    stato = "🆕 Nuovo"
            else:
                stato = ""  # gradi B/C/D non hanno stato di stabilizzazione

            row = {
                "Grado": f"{grade_emoji.get(s['grade'], '')} {s['grade']}",
                "Coppia": s["pair"],
                "Direzione": "⬆ LONG" if s["direction"] == "LONG" else "⬇ SHORT",
                "Score": s["quality_score"],
                "Δ Forza": s["differential"],
                "Stato": stato,
            }
            # Aggiungi flag news se presente
            if s.get("news_warning"):
                row["⚠️"] = "📰"
            else:
                row["⚠️"] = ""
            row["Motivi"] = " | ".join(
                [r for r in s.get("reasons", [])[:3] if not r.startswith("⚠️ ") or "Volatilità" in r]
            )
            setup_rows.append(row)
        st.dataframe(
            pd.DataFrame(setup_rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Score": st.column_config.ProgressColumn(
                    "Score", min_value=0, max_value=100, format="%d"
                ),
            },
        )

        # Dettaglio news warning per setup flaggati
        setups_with_news = [s for s in filtered_setups[:15] if s.get("news_warning")]
        if setups_with_news:
            with st.expander("📰 Dettaglio avvisi macro sui setup attivi", expanded=False):
                for s in setups_with_news:
                    st.markdown(f"**{s['pair']}**: {s['news_warning']}")
    else:
        st.info("Nessun setup corrisponde ai filtri selezionati.")
else:
    st.warning("Impossibile calcolare i trade setup.")

# ── Storico Segnali ──────────────────────────────────────────────────
st.markdown("---")
st.markdown("##### 📜 Storico Segnali A/A+")
st.caption("Log permanente di tutti i segnali entrati e usciti dalla classifica A/A+. "
           "Conserva gli ultimi 90 giorni.")

_signal_history = load_signal_history()

if _signal_history:
    # Filtri
    _hist_col1, _hist_col2, _hist_col3 = st.columns(3)
    with _hist_col1:
        _hist_type = st.selectbox(
            "Tipo:", ["Tutti", "ENTRATA", "USCITA"],
            index=0, key="hist_type_filter"
        )
    with _hist_col2:
        _all_pairs_hist = sorted(set(h["pair"] for h in _signal_history if h.get("pair")))
        _hist_pair = st.selectbox(
            "Coppia:", ["Tutte"] + _all_pairs_hist,
            index=0, key="hist_pair_filter"
        )
    with _hist_col3:
        _hist_days = st.selectbox(
            "Periodo:", [7, 14, 30, 60, 90],
            index=2, key="hist_days_filter",
            format_func=lambda d: f"Ultimi {d} giorni"
        )

    # Applica filtri
    _cutoff_date = (dt.datetime.now(_ROME) - dt.timedelta(days=_hist_days)).isoformat()
    _filtered_hist = [
        h for h in _signal_history
        if h.get("timestamp", "") >= _cutoff_date
        and (_hist_type == "Tutti" or h.get("type") == _hist_type)
        and (_hist_pair == "Tutte" or h.get("pair") == _hist_pair)
    ]

    if _filtered_hist:
        _hist_rows = []
        for h in _filtered_hist[:100]:  # max 100 righe
            _type_emoji = "🟢" if h.get("type") == "ENTRATA" else "🔴"
            _dir_label = ""
            if h.get("direction") == "LONG":
                _dir_label = "⬆ LONG"
            elif h.get("direction") == "SHORT":
                _dir_label = "⬇ SHORT"
            _hist_rows.append({
                "Data": h.get("date", ""),
                "Ora": h.get("time", ""),
                "Tipo": f"{_type_emoji} {h.get('type', '')}",
                "Coppia": h.get("pair", ""),
                "Direzione": _dir_label,
                "Grado": h.get("grade", "—"),
                "Score": h.get("score", 0) if h.get("type") == "ENTRATA" else "—",
                "Δ Forza": h.get("differential", 0) if h.get("type") == "ENTRATA" else "—",
                "Sessione": h.get("session", ""),
                "Motivi": " | ".join(h.get("reasons", [])[:2]),
            })

        st.dataframe(
            pd.DataFrame(_hist_rows),
            hide_index=True,
            use_container_width=True,
            height=min(400, 35 * len(_hist_rows) + 38),
        )

        # Statistiche rapide
        _entries = [h for h in _filtered_hist if h.get("type") == "ENTRATA"]
        _exits = [h for h in _filtered_hist if h.get("type") == "USCITA"]
        _stat_cols = st.columns(4)
        with _stat_cols[0]:
            st.metric("Segnali totali", len(_filtered_hist))
        with _stat_cols[1]:
            st.metric("🟢 Entrate", len(_entries))
        with _stat_cols[2]:
            st.metric("🔴 Uscite", len(_exits))
        with _stat_cols[3]:
            _unique_pairs = len(set(h["pair"] for h in _entries))
            st.metric("Coppie uniche", _unique_pairs)
    else:
        st.info("Nessun segnale trovato con i filtri selezionati.")
else:
    st.info("Nessun segnale registrato. Lo storico si popola automaticamente "
            "ad ogni refresh quando coppie entrano/escono dalla classifica A/A+.")

# ── Calendario Economico ─────────────────────────────────────────────
st.markdown("---")
st.markdown("##### 📅 Calendario Economico")

_cal_tabs = st.tabs(["⏭ Prossimi eventi", "⏮ Eventi recenti"])

with _cal_tabs[0]:
    if upcoming_events:
        _up_rows = []
        for ev in upcoming_events[:12]:
            impact_icon = "🔴" if ev["impact"] == "high" else "🟠"
            _up_rows.append({
                "Ora": ev["time"],
                "Valuta": ev["currency"],
                "Impatto": f"{impact_icon} {ev['impact'].upper()}",
                "Evento": ev["title"],
                "Prev.": ev.get("forecast", "—"),
                "Prec.": ev.get("previous", "—"),
                "Tra": f"{ev['hours_away']:.1f}h",
            })
        st.dataframe(pd.DataFrame(_up_rows), hide_index=True, use_container_width=True)
    else:
        st.info("Nessun evento ad alto impatto nelle prossime 12 ore.")

with _cal_tabs[1]:
    if recent_events:
        _rec_rows = []
        for ev in recent_events[:10]:
            impact_icon = "🔴" if ev["impact"] == "high" else "🟠"
            _rec_rows.append({
                "Ora": ev["time"],
                "Valuta": ev["currency"],
                "Impatto": f"{impact_icon} {ev['impact'].upper()}",
                "Evento": ev["title"],
                "Attuale": ev.get("actual", "—"),
                "Prev.": ev.get("forecast", "—"),
                "Prec.": ev.get("previous", "—"),
                "Fa": f"{ev['hours_ago']:.1f}h",
            })
        st.dataframe(pd.DataFrame(_rec_rows), hide_index=True, use_container_width=True)
    else:
        st.info("Nessun evento ad alto impatto nelle ultime 4 ore.")

# Heatmap differenziale
st.markdown("---")
st.markdown("##### 🔥 Heatmap Differenziale di Forza")

diff_matrix = pd.DataFrame(index=CURRENCIES, columns=CURRENCIES, dtype=float)
for ccy1 in CURRENCIES:
    for ccy2 in CURRENCIES:
        if ccy1 == ccy2:
            diff_matrix.loc[ccy1, ccy2] = 0
        else:
            s1 = composite[ccy1]["composite"]
            s2 = composite[ccy2]["composite"]
            diff_matrix.loc[ccy1, ccy2] = round(s1 - s2, 1)

fig_heat = px.imshow(
    diff_matrix.values.astype(float),
    labels=dict(x="Quote", y="Base", color="Δ Forza"),
    x=CURRENCIES,
    y=CURRENCIES,
    color_continuous_scale="RdYlGn",
    zmin=-60, zmax=60,
    text_auto=".0f",
)
fig_heat.update_layout(height=450, margin=dict(l=40, r=20, t=30, b=40))
st.plotly_chart(fig_heat, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SEZIONE 10: MATRICE DI CORRELAZIONE VALUTARIA
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("🔗 Correlazione tra Valute (30 giorni)")
st.caption("La correlazione misura quanto due valute si muovono insieme. "
           "Valori > 0.7 indicano ridondanza, valori < -0.7 indicano copertura naturale.")

corr_matrix = compute_currency_correlation(all_pairs, window=30)
if corr_matrix is not None and not corr_matrix.empty:
    fig_corr = px.imshow(
        corr_matrix.values.astype(float),
        labels=dict(x="Valuta", y="Valuta", color="Correlazione"),
        x=corr_matrix.columns.tolist(),
        y=corr_matrix.index.tolist(),
        color_continuous_scale="RdBu_r",
        zmin=-1, zmax=1,
        text_auto=".2f",
    )
    fig_corr.update_layout(height=450, margin=dict(l=40, r=20, t=30, b=40))
    st.plotly_chart(fig_corr, use_container_width=True)

    # Avvertenze correlazioni alte
    warnings = []
    checked = set()
    for c1 in corr_matrix.columns:
        for c2 in corr_matrix.columns:
            if c1 != c2 and (c2, c1) not in checked:
                val = corr_matrix.loc[c1, c2]
                checked.add((c1, c2))
                if abs(val) > 0.70:
                    direction = "positiva" if val > 0 else "negativa"
                    emoji = "⚠️" if val > 0 else "🔄"
                    warnings.append(
                        f"{emoji} **{c1}/{c2}**: correlazione {direction} "
                        f"({val:.2f}) — {'evita posizioni nella stessa direzione' if val > 0 else 'potenziale copertura naturale'}"
                    )
    if warnings:
        with st.expander(f"⚠️ {len(warnings)} correlazioni significative trovate", expanded=False):
            for w in warnings:
                st.markdown(w)
else:
    st.info("Dati insufficienti per calcolare la matrice di correlazione.")


# ═══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.markdown("""
<div style="text-align:center; color:gray; font-size:0.85rem;">
    <b>Currency Strength Indicator v3.0</b><br>
    Dati: Yahoo Finance (prezzo/volume) | CFTC (COT Report settimanale)<br>
    Indicatori: RSI, ROC multi-periodo, EMA positioning, Volume-weighted momentum,
    ADX, Hurst Exponent, Efficiency Ratio, ATR<br>
    Analytics: Trade Setup Score, Correlazione Valutaria, Radar Chart, Volatility Regime<br>
    <br>
    <b>⏱ Frequenza ottimale:</b><br>
    H1 → aggiorna ogni 60 min a chiusura barra | H4 → aggiorna ogni 4h<br>
    Composito (H1+H4) → combina reattività H1 e stabilità H4 in un unico score<br>
    COT → check settimanale venerdì sera (dati riferiti al martedì)<br>
    Sessioni chiave: London Open (08:00 GMT), NY Open (13:00 GMT), London Close (16:00 GMT)
</div>
""", unsafe_allow_html=True)
