"""
📊 Asset Strength Dashboard
==============================
Dashboard per Oro, Argento, Bitcoin, Nasdaq, S&P 500, DAX, Grano.
Composito = blend H4 + Daily + Weekly.
Stessi indicatori e criteri della dashboard valutaria.
"""

import datetime as dt
from zoneinfo import ZoneInfo

_ROME = ZoneInfo("Europe/Rome")

import os
import json
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px

from config import (
    ASSETS, ASSET_LABELS, ASSET_ICONS, ASSET_CLASS,
    ASSET_DEFAULT_TIMEFRAME, ASSET_REFRESH_SECONDS,
    ASSET_COMPOSITE_WEIGHT_H4, ASSET_COMPOSITE_WEIGHT_DAILY, ASSET_COMPOSITE_WEIGHT_WEEKLY,
    THRESHOLD_STRONG_BULL, THRESHOLD_EXTREME_BULL,
    THRESHOLD_STRONG_BEAR, THRESHOLD_EXTREME_BEAR,
    ALERTS_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ALERT_GRADES,
    ASSET_ALERT_STATE_FILE,
    GRADE_HYSTERESIS_POINTS, SIGNAL_MIN_RESIDENCE_HOURS,
    SIGNAL_GRACE_REFRESHES, SIGNAL_CONFIRMATION_REFRESHES,
)
from asset_data_fetcher import fetch_all_assets, fetch_all_asset_volumes
from asset_cot_data import load_asset_cot_data, compute_asset_cot_scores, get_asset_cot_timeseries
from asset_strength_engine import (
    full_asset_analysis, blend_asset_multi_timeframe,
    compute_asset_correlation, compute_asset_trade_setups,
    smooth_asset_composite_scores,
)
from economic_calendar import get_current_sessions, is_forex_market_open

# ═══════════════════════════════════════════════════════════════════════════════
# STILE
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    .main-header {
        font-size: 2rem; font-weight: 700; color: #ff9800;
        text-align: center; padding: 0.5rem 0;
    }
    .summary-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 12px; padding: 1rem 1.2rem; margin: 0.3rem 0;
        border: 1px solid #333;
    }
    .summary-card h4 { color: #ff9800; margin: 0 0 0.3rem 0; font-size: 0.95rem; }
    .summary-card .big { font-size: 1.6rem; font-weight: 700; }
    .trend-follow {
        background-color: #d4edda; border-left: 4px solid #28a745;
        padding: 0.5rem 1rem; margin: 0.3rem 0; border-radius: 3px;
    }
    .mean-revert {
        background-color: #d1ecf1; border-left: 4px solid #17a2b8;
        padding: 0.5rem 1rem; margin: 0.3rem 0; border-radius: 3px;
    }
    div[data-testid="stMetricValue"] { font-size: 1.4rem; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-REFRESH allineato alla chiusura candela oraria (xx:00)
# ═══════════════════════════════════════════════════════════════════════════════
def _ms_to_next_hour() -> int:
    """Millisecondi mancanti alla prossima ora piena + 10 s di margine."""
    now = dt.datetime.now(dt.timezone.utc)
    next_hour = (now + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    delta_ms = int((next_hour - now).total_seconds() * 1000) + 10_000
    return max(delta_ms, 60_000)

st_autorefresh(interval=_ms_to_next_hour(), limit=0, key="asset_hourly_refresh")

# ── Forza refresh dati a cambio ora (allineamento candela) ──────────
# Chiave condivisa tra tutte le pagine: il clear avviene UNA sola volta
# al cambio d'ora, non quando si naviga tra pagine.
_current_hour_key = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H")
if st.session_state.get("_last_hour_global") != _current_hour_key:
    st.session_state["_last_hour_global"] = _current_hour_key
    st.cache_data.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.image("https://img.icons8.com/color/96/commodity.png", width=64)
    st.title("⚙️ Impostazioni Asset")

    asset_timeframe = st.selectbox(
        "Timeframe",
        options=["Composito", "H4", "Daily", "Weekly"],
        index=0,
        help="Composito = blend H4+Daily+Weekly, H4 = 4 ore, Daily = giornaliero, Weekly = settimanale",
    )

    _next_h = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    st.info(f"🔄 Prossimo refresh: {_next_h.astimezone(_ROME).strftime('%H:%M')} (ora candela)")

    if asset_timeframe == "Composito":
        st.divider()
        st.subheader("⚖️ Pesi Blend")
        st.write(f"H4 (reattività): **{ASSET_COMPOSITE_WEIGHT_H4:.0%}**")
        st.write(f"Daily (base): **{ASSET_COMPOSITE_WEIGHT_DAILY:.0%}**")
        st.write(f"Weekly (stabilità): **{ASSET_COMPOSITE_WEIGHT_WEEKLY:.0%}**")

    st.divider()
    st.subheader("📊 Soglie")
    st.write(f"🟢 Forte Bull: **≥ {THRESHOLD_STRONG_BULL}** | 🟢🟢 Estremo: **≥ {THRESHOLD_EXTREME_BULL}**")
    st.write(f"🔴 Forte Bear: **≤ {THRESHOLD_STRONG_BEAR}** | 🔴🔴 Estremo: **≤ {THRESHOLD_EXTREME_BEAR}**")

    st.divider()
    st.subheader("📱 Alert Telegram")
    if ALERTS_ENABLED and TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        st.success("✅ Alert attivi (sincronizzati)")
        st.caption(f"Gradi monitorati: {', '.join(ALERT_GRADES)}")
    else:
        st.warning("Alert disabilitati")

    st.divider()
    st.subheader("🕐 Sessione Attiva")
    _sb_session = get_current_sessions()
    st.markdown(f"**{_sb_session['session_label']}**")
    st.caption(f"{_sb_session['utc_now'].strftime('%H:%M')} UTC")

    st.divider()
    st.caption(f"Ultimo aggiornamento: {dt.datetime.now(_ROME).strftime('%Y-%m-%d %H:%M')}")

    if st.button("🔄 Aggiorna Dati Ora", width='stretch', key="refresh_assets"):
        st.cache_data.clear()
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════════

_market_status = is_forex_market_open()
_market_open_for_ttl = _market_status["is_open"]
_cache_ttl = ASSET_REFRESH_SECONDS.get(ASSET_DEFAULT_TIMEFRAME, 3600) if _market_open_for_ttl else 86400


@st.cache_data(ttl=_cache_ttl, show_spinner=False)
def load_all_asset_data(tf: str):
    """Carica tutti i dati per gli asset."""
    with st.spinner("📥 Scaricamento dati asset..."):
        if tf == "Composito":
            all_assets_h4 = fetch_all_assets("H4")
            all_assets_daily = fetch_all_assets("Daily")
            all_assets_weekly = fetch_all_assets("Weekly")
            all_assets = all_assets_daily
        else:
            all_assets = fetch_all_assets(tf)
            all_assets_h4 = None
            all_assets_daily = None
            all_assets_weekly = None

    with st.spinner("📥 Scaricamento dati COT asset..."):
        cot_raw = load_asset_cot_data()
        cot_scores = compute_asset_cot_scores(cot_raw)
        cot_ts = get_asset_cot_timeseries(cot_raw)

    return {
        "all_assets": all_assets,
        "cot_raw": cot_raw,
        "cot_scores": cot_scores,
        "cot_ts": cot_ts,
        "all_assets_h4": all_assets_h4,
        "all_assets_daily": all_assets_daily,
        "all_assets_weekly": all_assets_weekly,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TITOLO
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="main-header">📊 Asset Strength Dashboard</div>', unsafe_allow_html=True)

if asset_timeframe == "Composito":
    st.markdown(
        f"<p style='text-align:center; color:gray;'>"
        f"Timeframe: <b>Composito (H4 {ASSET_COMPOSITE_WEIGHT_H4:.0%} + "
        f"Daily {ASSET_COMPOSITE_WEIGHT_DAILY:.0%} + "
        f"Weekly {ASSET_COMPOSITE_WEIGHT_WEEKLY:.0%})</b> | "
        f"Dati aggiornati: {dt.datetime.now(_ROME).strftime('%H:%M:%S')}</p>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"<p style='text-align:center; color:gray;'>"
        f"Timeframe: <b>{asset_timeframe}</b> | "
        f"Dati aggiornati: {dt.datetime.now(_ROME).strftime('%H:%M:%S')}</p>",
        unsafe_allow_html=True,
    )

if not _market_status["is_open"]:
    st.warning(
        f"⚠️ **{_market_status['reason']}**\n\n"
        f"I dati visualizzati sono gli ultimi disponibili dalla cache. "
        f"Riapertura: **{_market_status['next_open']}**"
    )

try:
    data = load_all_asset_data(asset_timeframe)
    all_assets = data["all_assets"]
    cot_scores = data["cot_scores"]
    cot_ts = data["cot_ts"]
except Exception as e:
    st.error(f"Errore nel caricamento dati asset: {e}")
    st.stop()

if not all_assets:
    st.warning("Nessun dato disponibile per gli asset. Verifica la connessione internet.")
    st.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# ANALISI
# ═══════════════════════════════════════════════════════════════════════════════

if asset_timeframe == "Composito":
    analysis_h4 = full_asset_analysis(data["all_assets_h4"], cot_scores)
    analysis_daily = full_asset_analysis(data["all_assets_daily"], cot_scores)
    analysis_weekly = full_asset_analysis(data["all_assets_weekly"], cot_scores)
    analysis = blend_asset_multi_timeframe(analysis_h4, analysis_daily, analysis_weekly)
    is_composite = True
else:
    analysis = full_asset_analysis(all_assets, cot_scores)
    is_composite = False

composite = analysis["composite"]

# ── Smoothing composito (anti-flickering) ────────────────────────────
import json as _json_smooth
_apc_disk_path = os.path.join("cache", "asset_prev_composite.json")
_asset_prev_composite = None
try:
    if os.path.exists(_apc_disk_path):
        with open(_apc_disk_path, "r") as _apcf:
            _asset_prev_composite = _json_smooth.load(_apcf)
except Exception:
    pass
if _asset_prev_composite is None:
    _asset_prev_composite = st.session_state.get("_asset_prev_composite", None)
composite = smooth_asset_composite_scores(composite, _asset_prev_composite)
st.session_state["_asset_prev_composite"] = composite
analysis["composite"] = composite

momentum = analysis["momentum"]
classification = analysis["classification"]
rolling = analysis["rolling_strength"]
atr_context = analysis.get("atr_context", {})
velocity = analysis.get("velocity", {})
candle9 = analysis.get("candle9", {})

sorted_assets = sorted(ASSETS, key=lambda a: composite.get(a, {}).get("composite", 50), reverse=True)


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


def _signal_label(score: float) -> str:
    if score >= 80:   return "STRONG BUY"
    elif score >= 65: return "BUY"
    elif score >= 55: return "SLIGHT BUY"
    elif score >= 45: return "NEUTRAL"
    elif score >= 35: return "SLIGHT SELL"
    elif score >= 20: return "SELL"
    else:             return "STRONG SELL"


def _signal_color(score: float) -> str:
    if score >= 80:   return "#00c853"
    elif score >= 65: return "#4caf50"
    elif score >= 55: return "#8bc34a"
    elif score >= 45: return "#78909c"
    elif score >= 35: return "#ff9800"
    elif score >= 20: return "#f44336"
    else:             return "#b71c1c"


def _label_color(label: str) -> str:
    return {
        "STRONG BUY": "#00c853", "BUY": "#4caf50", "SLIGHT BUY": "#8bc34a",
        "NEUTRAL": "#78909c", "SLIGHT SELL": "#ff9800",
        "SELL": "#f44336", "STRONG SELL": "#b71c1c",
    }.get(label, "#78909c")


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BANNER RIASSUNTIVO (colpo d'occhio)
# ═══════════════════════════════════════════════════════════════════════════════

strongest = sorted_assets[0] if sorted_assets else None
weakest = sorted_assets[-1] if sorted_assets else None

active_setups_temp = compute_asset_trade_setups(
    composite, momentum, classification, atr_context, cot_scores, velocity,
    trend_structure=analysis.get("trend_structure"),
    strength_persistence=analysis.get("strength_persistence"),
    candle9=candle9,
)
high_grade_count = sum(1 for s in active_setups_temp if s["grade"] in ["A+", "A"])
bull_count = sum(1 for a in ASSETS if composite.get(a, {}).get("composite", 50) >= 55)
bear_count = sum(1 for a in ASSETS if composite.get(a, {}).get("composite", 50) <= 45)

banner_cols = st.columns(5)
with banner_cols[0]:
    if strongest:
        sc = composite.get(strongest, {}).get("composite", 50)
        st.metric(
            "🏆 Più Forte",
            f"{ASSET_ICONS.get(strongest, '')} {sc:.0f}",
            delta=ASSET_LABELS.get(strongest, strongest),
        )
with banner_cols[1]:
    if weakest:
        sc = composite.get(weakest, {}).get("composite", 50)
        st.metric(
            "📉 Più Debole",
            f"{ASSET_ICONS.get(weakest, '')} {sc:.0f}",
            delta=ASSET_LABELS.get(weakest, weakest),
            delta_color="inverse",
        )
with banner_cols[2]:
    st.metric("📊 Setup Attivi", f"{len(active_setups_temp)}", delta=f"{high_grade_count} grado A+/A")
with banner_cols[3]:
    st.metric("🟢 Bullish", f"{bull_count}/{len(ASSETS)}")
with banner_cols[4]:
    st.metric("🔴 Bearish", f"{bear_count}/{len(ASSETS)}")

st.divider()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GAUGE + SPARKLINE (forza composita con mini-chart del prezzo)
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("🎯 Forza Composita degli Asset")

gauge_cols = st.columns(len(ASSETS))

for i, asset in enumerate(sorted_assets):
    c = composite.get(asset, {})
    score = c.get("composite", 50)
    label = _signal_label(score)
    color = _signal_color(score)
    mom = momentum.get(asset, {})
    delta_str = f"{mom.get('delta', 0):+.1f}%" if mom.get("delta", 0) != 0 else "0%"

    with gauge_cols[i]:
        # Gauge (donut)
        fig = go.Figure()
        fig.add_trace(go.Pie(
            values=[score, 100 - score], hole=0.75,
            marker=dict(colors=[color, "#2a2a3d"], line=dict(color="#1e1e2f", width=2)),
            textinfo="none", hoverinfo="none",
            rotation=90, sort=False, direction="clockwise",
        ))
        fig.add_annotation(text=f"<b>{score:.0f}</b>", x=0.5, y=0.58,
                           xref="paper", yref="paper", showarrow=False,
                           font=dict(size=32, color="white", family="Arial Black"))
        fig.add_annotation(text=f"<b>{label}</b>", x=0.5, y=0.42,
                           xref="paper", yref="paper", showarrow=False,
                           font=dict(size=10, color=_label_color(label)))
        fig.add_annotation(text=ASSET_LABELS.get(asset, asset), x=0.5, y=0.30,
                           xref="paper", yref="paper", showarrow=False,
                           font=dict(size=11, color="#aaa"))
        fig.update_layout(
            showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            height=180, margin=dict(l=5, r=5, t=5, b=5),
        )
        st.plotly_chart(fig, width='stretch', key=f"gauge_{asset}")

        # W Decay caption (sotto gauge)
        _w_decay = c.get("w_decay_pct", 0)
        if _w_decay > 0:
            st.caption(f"H4: {c.get('h4_score',50):.0f} | D1: {c.get('daily_score',50):.0f} | W: {c.get('weekly_score',50):.0f} | ⏬W −{_w_decay}%")
        elif is_composite:
            st.caption(f"H4: {c.get('h4_score',50):.0f} | D1: {c.get('daily_score',50):.0f} | W: {c.get('weekly_score',50):.0f}")

        # Momentum badge
        mom_color = "#4caf50" if mom.get("delta", 0) > 0 else "#f44336" if mom.get("delta", 0) < 0 else "#888"
        st.markdown(
            f"<div style='text-align:center; font-size:0.85rem; color:{mom_color};'>"
            f"{mom.get('rank_label', '→ Flat')} ({delta_str})</div>",
            unsafe_allow_html=True,
        )

        # Candle-9 badge
        c9 = candle9.get(asset, {})
        c9_ratio = c9.get("candle9_ratio", 0)
        c9_color = "#4caf50" if c9_ratio > 0 else "#f44336" if c9_ratio < 0 else "#888"
        st.markdown(
            f"<div style='text-align:center; font-size:0.80rem; color:{c9_color};'>"
            f"C9: {c9.get('candle9_signal', '➖ NEUTRO')} ({c9_ratio:+.2f}%)</div>",
            unsafe_allow_html=True,
        )

        # Sparkline (ultimi 30 prezzi)
        df = all_assets.get(asset)
        if df is not None and not df.empty and "Close" in df.columns:
            spark_data = df["Close"].iloc[-30:]
            is_up = float(spark_data.iloc[-1]) >= float(spark_data.iloc[0])
            spark_color = "#4caf50" if is_up else "#f44336"
            fill_color = "rgba(76,175,80,0.1)" if is_up else "rgba(244,67,54,0.1)"
            fig_spark = go.Figure()
            fig_spark.add_trace(go.Scatter(
                x=list(range(len(spark_data))), y=spark_data.values,
                mode="lines", line=dict(color=spark_color, width=1.5),
                fill="tozeroy", fillcolor=fill_color,
                hoverinfo="none",
            ))
            fig_spark.update_layout(
                height=50, margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                xaxis=dict(visible=False), yaxis=dict(visible=False),
            )
            st.plotly_chart(fig_spark, width='stretch', key=f"spark_{asset}")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. CLASSIFICA FORZA (barre orizzontali)
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📊 Classifica Forza")

fig_bar = go.Figure()
for asset in sorted_assets:
    c = composite.get(asset, {})
    score = c.get("composite", 50)
    fig_bar.add_trace(go.Bar(
        x=[score], y=[ASSET_LABELS.get(asset, asset)],
        orientation="h",
        marker=dict(color=strength_color(score), line=dict(color="white", width=0.5)),
        text=f"  {score:.1f}",
        textposition="outside",
        textfont=dict(color="white", size=14),
        showlegend=False,
    ))

fig_bar.add_vline(x=50, line_dash="dash", line_color="gray", line_width=1)
fig_bar.add_vline(x=THRESHOLD_STRONG_BULL, line_dash="dot", line_color="green", line_width=0.5, opacity=0.5)
fig_bar.add_vline(x=THRESHOLD_STRONG_BEAR, line_dash="dot", line_color="red", line_width=0.5, opacity=0.5)
fig_bar.update_layout(
    xaxis=dict(range=[0, 100], title="Score", gridcolor="#333"),
    yaxis=dict(autorange="reversed"),
    template="plotly_dark", height=50 + 45 * len(ASSETS),
    margin=dict(l=120, r=40, t=20, b=30),
    plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
)
st.plotly_chart(fig_bar, width='stretch', key="bar_chart")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TABS PER CLASSE ASSET (Commodity / Crypto / Index)
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📋 Dettaglio per Classe")

classes = sorted(set(ASSET_CLASS.values()))
tabs = st.tabs(
    [f"{'🏗️' if c == 'Commodity' else '₿' if c == 'Crypto' else '📈'} {c}" for c in classes]
    + ["📋 Tutti"]
)

for tab_idx, tab in enumerate(tabs):
    with tab:
        if tab_idx < len(classes):
            class_name = classes[tab_idx]
            class_assets = [a for a in sorted_assets if ASSET_CLASS.get(a) == class_name]
        else:
            class_assets = sorted_assets

        if not class_assets:
            st.info("Nessun asset in questa classe.")
            continue

        table_data = []
        for asset in class_assets:
            c = composite.get(asset, {})
            m = momentum.get(asset, {})
            cl = classification.get(asset, {})
            atr_info = atr_context.get(asset, {})
            vel = velocity.get(asset, {})
            c9 = candle9.get(asset, {})

            row = {
                "Asset": ASSET_LABELS.get(asset, asset),
                "Composito": c.get("composite", 50),
                "Segnale": _signal_label(c.get("composite", 50)),
                "Price": c.get("price_score", 50),
                "Volume": c.get("volume_score", 50),
                "COT": c.get("cot_score", 50),
                "Momentum": m.get("rank_label", "N/A"),
                "Δ Mom.": m.get("delta", 0),
                "Candle 9": c9.get("candle9_signal", "➖ NEUTRO"),
                "Δ C9 %": c9.get("candle9_ratio", 0),
                "Regime": cl.get("classification", "MIXED"),
                "ADX": cl.get("adx_avg", 0),
                "Hurst": cl.get("hurst", 0.5),
                "Vol. Regime": atr_info.get("volatility_regime", "NORMAL"),
                "Velocità": vel.get("velocity_label", "N/A"),
            }

            if is_composite:
                row["H4"] = c.get("h4_score", 50)
                row["Daily"] = c.get("daily_score", 50)
                row["Weekly"] = c.get("weekly_score", 50)
                row["Concordanza"] = c.get("concordance", "")
                _wd = c.get("w_decay_pct", 0)
                row["⏬W Decay"] = f"−{_wd}%" if _wd > 0 else "—"

            table_data.append(row)

        tdf = pd.DataFrame(table_data)

        def _hl_score(val):
            if isinstance(val, (int, float)):
                if val >= THRESHOLD_STRONG_BULL:
                    return "background-color: rgba(0,200,83,0.3); color: #00c853; font-weight: bold"
                elif val <= THRESHOLD_STRONG_BEAR:
                    return "background-color: rgba(255,23,68,0.3); color: #ff1744; font-weight: bold"
            return ""

        score_cols = [c for c in ["Composito", "Price", "Volume", "COT", "H4", "Daily", "Weekly"]
                      if c in tdf.columns]
        styled = tdf.style.map(_hl_score, subset=score_cols)
        st.dataframe(styled, width='stretch', hide_index=True,
                     height=min(350, 80 + 40 * len(class_assets)))


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ALERT & SOGLIE DI ATTENZIONE
# ═══════════════════════════════════════════════════════════════════════════════

_alerts_list = []
for asset in sorted_assets:
    c = composite.get(asset, {})
    alert_msg = c.get("alert")
    if alert_msg:
        _alerts_list.append((asset, c.get("composite", 50), alert_msg))

if _alerts_list:
    st.subheader("🚨 Alert e Soglie di Attenzione")
    for asset, score, msg in _alerts_list:
        icon = ASSET_ICONS.get(asset, "")
        lbl = ASSET_LABELS.get(asset, asset)
        color = "#ff9800" if score >= 50 else "#f44336"
        st.markdown(
            f"<div style='background-color:rgba(255,152,0,0.1); border-left:4px solid {color}; "
            f"padding:0.6rem 1rem; margin:0.3rem 0; border-radius:3px;'>"
            f"<b>{icon} {lbl}</b> (Score: {score:.0f}) — {msg}</div>",
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MOMENTUM (barre colorate — chi guadagna e chi perde forza)
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("🚀 Momentum — Variazione Forza Recente")

mom_sorted = sorted(ASSETS, key=lambda a: momentum.get(a, {}).get("delta", 0), reverse=True)
gaining = [a for a in mom_sorted if momentum.get(a, {}).get("delta", 0) > 0.5]
losing = [a for a in mom_sorted if momentum.get(a, {}).get("delta", 0) < -0.5]

mom_cols = st.columns(2)
with mom_cols[0]:
    st.markdown("**🟢 Guadagnano Forza**")
    if gaining:
        for a in gaining:
            m = momentum.get(a, {})
            delta = m.get("delta", 0)
            accel = m.get("acceleration", 0)
            accel_icon = "🔺" if accel > 0 else "🔻" if accel < 0 else ""
            bar_width = min(abs(delta) * 10, 100)
            st.markdown(
                f"<div style='margin:2px 0;'>"
                f"<span style='display:inline-block; width:120px;'>"
                f"{ASSET_ICONS.get(a, '')} {a}</span>"
                f"<span style='display:inline-block; width:{bar_width}%; height:16px; "
                f"background:#4caf50; border-radius:3px; margin-right:8px;'></span>"
                f"<b style='color:#4caf50;'>+{delta:.2f}%</b> {accel_icon}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("Nessun asset in guadagno di forza significativo.")

with mom_cols[1]:
    st.markdown("**🔴 Perdono Forza**")
    if losing:
        for a in losing:
            m = momentum.get(a, {})
            delta = m.get("delta", 0)
            accel = m.get("acceleration", 0)
            accel_icon = "🔺" if accel > 0 else "🔻" if accel < 0 else ""
            bar_width = min(abs(delta) * 10, 100)
            st.markdown(
                f"<div style='margin:2px 0;'>"
                f"<span style='display:inline-block; width:120px;'>"
                f"{ASSET_ICONS.get(a, '')} {a}</span>"
                f"<span style='display:inline-block; width:{bar_width}%; height:16px; "
                f"background:#f44336; border-radius:3px; margin-right:8px;'></span>"
                f"<b style='color:#f44336;'>{delta:.2f}%</b> {accel_icon}</div>",
                unsafe_allow_html=True,
            )
    else:
        st.caption("Nessun asset in perdita di forza significativa.")


# ═══════════════════════════════════════════════════════════════════════════════
# 6B. CANDLE-9 PRICE ACTION (close attuale vs 9 candele fa)
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("🕯️ Candle-9 Price Action")
st.caption(
    "Confronta il prezzo di chiusura attuale con quello di 9 candele fa per ogni asset. "
    "Close superiore → segnale di **forza** (🟢); inferiore → segnale di **debolezza** (🔴)."
)

c9_sorted = sorted(
    [(a, candle9.get(a, {})) for a in ASSETS],
    key=lambda x: x[1].get("candle9_ratio", 0),
    reverse=True,
)

# Barchart Candle-9
fig_c9 = go.Figure()
for asset, c9 in c9_sorted:
    ratio = c9.get("candle9_ratio", 0)
    color = "#4caf50" if ratio > 0.1 else "#f44336" if ratio < -0.1 else "#78909c"
    fig_c9.add_trace(go.Bar(
        x=[ratio],
        y=[ASSET_LABELS.get(asset, asset)],
        orientation="h",
        marker=dict(color=color),
        text=f"  {ratio:+.2f}%",
        textposition="outside",
        textfont=dict(color="white", size=12),
        showlegend=False,
    ))

fig_c9.add_vline(x=0, line_dash="dash", line_color="gray", line_width=1)
fig_c9.update_layout(
    xaxis_title="Δ % vs Candle 9",
    yaxis=dict(autorange="reversed"),
    template="plotly_dark",
    height=50 + 40 * len(ASSETS),
    margin=dict(l=120, r=60, t=20, b=30),
    plot_bgcolor="#0e1117",
    paper_bgcolor="#0e1117",
)
st.plotly_chart(fig_c9, width='stretch', key="c9_chart")

# Tabella dettaglio Candle-9
c9_table = []
for asset, c9 in c9_sorted:
    c9_table.append({
        "Asset": f"{ASSET_ICONS.get(asset, '')} {ASSET_LABELS.get(asset, asset)}",
        "Segnale C9": c9.get("candle9_signal", "➖ NEUTRO"),
        "Δ %": f"{c9.get('candle9_ratio', 0):+.3f}%",
        "Close Attuale": c9.get("candle9_current", 0),
        "Close 9 Candele Fa": c9.get("candle9_past", 0),
    })
st.dataframe(pd.DataFrame(c9_table), hide_index=True, width='stretch')


# ═══════════════════════════════════════════════════════════════════════════════
# 7. CLASSIFICAZIONE TREND vs MEAN-REVERT
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📈 Classificazione: Trend Following vs Mean Reverting")

trend_cols = st.columns(3)
trend_assets = [a for a in sorted_assets
                if classification.get(a, {}).get("classification") == "TREND_FOLLOWING"]
mixed_assets = [a for a in sorted_assets
                if classification.get(a, {}).get("classification") == "MIXED"]
revert_assets = [a for a in sorted_assets
                 if classification.get(a, {}).get("classification") == "MEAN_REVERTING"]

with trend_cols[0]:
    st.markdown("**📈 TREND FOLLOWING**")
    for a in trend_assets:
        cl = classification.get(a, {})
        st.markdown(
            f"<div class='trend-follow'>{ASSET_ICONS.get(a, '')} <b>{a}</b> — "
            f"ADX {cl.get('adx_avg', 0):.0f} | H {cl.get('hurst', 0.5):.2f} | "
            f"ER {cl.get('eff_ratio', 0):.2f}</div>",
            unsafe_allow_html=True,
        )
    if not trend_assets:
        st.caption("Nessun asset in trend chiaro.")

with trend_cols[1]:
    st.markdown("**⚖️ MIXED**")
    for a in mixed_assets:
        cl = classification.get(a, {})
        st.markdown(
            f"<div style='background:#ff9800; border-left:4px solid #e65100; "
            f"padding:0.5rem 1rem; margin:0.3rem 0; border-radius:3px; color:#000000;'>"
            f"{ASSET_ICONS.get(a, '')} <b>{a}</b> — "
            f"ADX {cl.get('adx_avg', 0):.0f} | H {cl.get('hurst', 0.5):.2f}</div>",
            unsafe_allow_html=True,
        )
    if not mixed_assets:
        st.caption("—")

with trend_cols[2]:
    st.markdown("**🔄 MEAN REVERTING**")
    for a in revert_assets:
        cl = classification.get(a, {})
        st.markdown(
            f"<div class='mean-revert'>{ASSET_ICONS.get(a, '')} <b>{a}</b> — "
            f"ADX {cl.get('adx_avg', 0):.0f} | H {cl.get('hurst', 0.5):.2f} | "
            f"ER {cl.get('eff_ratio', 0):.2f}</div>",
            unsafe_allow_html=True,
        )
    if not revert_assets:
        st.caption("Nessun asset in mean-revert.")


# ═══════════════════════════════════════════════════════════════════════════════
# 8. VOLATILITÀ & VELOCITÀ
# ═══════════════════════════════════════════════════════════════════════════════

with st.expander("🌡️ Volatilità & Velocità per Asset", expanded=False):
    vol_vel_data = []
    for asset in sorted_assets:
        a = atr_context.get(asset, {})
        v = velocity.get(asset, {})
        vol_vel_data.append({
            "Asset": ASSET_LABELS.get(asset, asset),
            "ATR %": round(a.get("atr_pct", 0), 3),
            "ATR Percentile": round(a.get("atr_percentile", 50), 0),
            "Vol. Regime": a.get("volatility_regime", "NORMAL"),
            "Velocità": v.get("velocity_label", "N/A"),
            "Vel. Score": round(v.get("velocity_norm", 50), 0),
        })

    vv_df = pd.DataFrame(vol_vel_data)

    def _vol_color(val):
        if val == "EXTREME":
            return "background-color: rgba(255,23,68,0.4); color: #ff1744; font-weight: bold"
        elif val == "HIGH":
            return "background-color: rgba(255,152,0,0.3); color: #ff9800"
        elif val == "LOW":
            return "background-color: rgba(33,150,243,0.3); color: #2196f3"
        return ""

    styled_vv = vv_df.style.map(_vol_color, subset=["Vol. Regime"])
    st.dataframe(styled_vv, width='stretch', hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 9. GRAFICO STORICO (Rolling Strength)
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📈 Evoluzione Forza nel Tempo")

if not rolling.empty:
    available_assets = [a for a in sorted_assets if a in rolling.columns]

    if available_assets:
        selected_assets = st.multiselect(
            "Seleziona asset da visualizzare",
            options=available_assets,
            default=available_assets[:4],
            format_func=lambda x: ASSET_LABELS.get(x, x),
            key="rolling_select",
        )

        if selected_assets:
            fig_rolling = go.Figure()
            colors = px.colors.qualitative.Set2
            for idx, asset in enumerate(selected_assets):
                if asset in rolling.columns:
                    fig_rolling.add_trace(go.Scatter(
                        x=rolling.index, y=rolling[asset],
                        name=ASSET_LABELS.get(asset, asset),
                        line=dict(width=2, color=colors[idx % len(colors)]),
                        mode="lines",
                    ))

            fig_rolling.add_hline(y=50, line_dash="dash", line_color="gray", line_width=1)
            fig_rolling.add_hline(y=THRESHOLD_STRONG_BULL, line_dash="dot",
                                  line_color="green", line_width=0.5)
            fig_rolling.add_hline(y=THRESHOLD_STRONG_BEAR, line_dash="dot",
                                  line_color="red", line_width=0.5)
            fig_rolling.update_layout(
                template="plotly_dark", height=400,
                yaxis=dict(range=[0, 100], title="Forza Composita"),
                xaxis=dict(title=""),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=40, r=20, t=40, b=30),
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
            )
            st.plotly_chart(fig_rolling, width='stretch', key="rolling_chart")
else:
    st.info("Dati insufficienti per il grafico storico.")


# ═══════════════════════════════════════════════════════════════════════════════
# 10. RADAR CHART
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("🕸️ Radar Chart – Confronto Multi-fattore")

radar_cols = st.columns(2)
with radar_cols[0]:
    radar_assets = st.multiselect(
        "Asset da confrontare",
        options=ASSETS,
        default=ASSETS[:4],
        format_func=lambda x: ASSET_LABELS.get(x, x),
        key="radar_select",
    )

if radar_assets:
    categories = ["Price Action", "Volume", "COT", "Trend Score", "Velocity"]
    fig_radar = go.Figure()
    colors = px.colors.qualitative.Vivid

    for idx, asset in enumerate(radar_assets):
        c = composite.get(asset, {})
        cl = classification.get(asset, {})
        vel = velocity.get(asset, {})
        values = [
            c.get("price_score", 50),
            c.get("volume_score", 50),
            c.get("cot_score", 50),
            cl.get("trend_score", 50),
            vel.get("velocity_norm", 50),
        ]
        values.append(values[0])

        fig_radar.add_trace(go.Scatterpolar(
            r=values, theta=categories + [categories[0]],
            fill="toself", name=ASSET_LABELS.get(asset, asset),
            line=dict(color=colors[idx % len(colors)]), opacity=0.7,
        ))

    fig_radar.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], gridcolor="#333"),
            bgcolor="#0e1117",
        ),
        template="plotly_dark", height=450, showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15),
        paper_bgcolor="#0e1117",
    )
    st.plotly_chart(fig_radar, width='stretch', key="radar_chart")


# ═══════════════════════════════════════════════════════════════════════════════
# 11. TRADE SETUPS
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("🏆 Trade Setup – Classifica Asset")

# ── Carica setup dallo stato alert (UNICA SORGENTE = stessa del Telegram) ──
_use_scheduler_asset_setups = False
trade_setups = []
_a_state = {}   # caricato una volta, riusato per Stato colonna

try:
    if os.path.exists(ASSET_ALERT_STATE_FILE):
        with open(ASSET_ALERT_STATE_FILE, "r", encoding="utf-8") as _asf:
            _a_state = json.load(_asf)
        _aas_updated = _a_state.get("updated", "")
        if _aas_updated:
            _aas_dt = dt.datetime.fromisoformat(_aas_updated)
            _aas_age_h = (dt.datetime.now(_ROME) - _aas_dt).total_seconds() / 3600
            if _aas_age_h < 2.0 and _a_state.get("all_setups"):
                trade_setups = _a_state["all_setups"]
                _use_scheduler_asset_setups = True
except Exception:
    pass

if not _use_scheduler_asset_setups:
    trade_setups = active_setups_temp  # fallback: calcolo locale

if _use_scheduler_asset_setups:
    st.caption("📡 Dati sincronizzati con lo scheduler Telegram")
else:
    st.caption("⚠️ Dati calcolati localmente — lo scheduler non ha ancora eseguito")

if trade_setups:
    # ── Info stabilizzazione dall'alert state (stessa sorgente) ───────
    _a_prev = set(_a_state.get("pairs", []))
    _a_pair_details = _a_state.get("pair_details", {})
    _a_pending_pairs = _a_state.get("pending_pairs", {})

    # Determina set A/A+ attivo
    if _use_scheduler_asset_setups:
        # Quando sincronizzato: _a_current_top = set stabilizzato (= stessa del Telegram)
        _a_current_top = _a_prev.copy()
    else:
        _a_current_top = {
            f"{s['asset']} {s['direction']}" for s in trade_setups if s["grade"] in ALERT_GRADES
        }
    _a_confirmed_set = _a_prev
    _a_pending_set = set(_a_pending_pairs.keys())
    _a_hysteresis_set = set()
    _a_grace_set = set()
    _a_residence_set = set()
    _a_grade_exit_threshold = 60 - GRADE_HYSTERESIS_POINTS

    for pk in _a_prev:
        if pk in _a_current_top:
            continue
        _pk_setup = next((s for s in trade_setups
                          if f"{s['asset']} {s['direction']}" == pk), None)
        _pk_score = _pk_setup["quality_score"] if _pk_setup else 0
        _pk_detail = _a_pair_details.get(pk, {})
        if _pk_score >= _a_grade_exit_threshold:
            _a_hysteresis_set.add(pk)
        elif _pk_detail.get("entered_at"):
            import datetime as _dt_mod
            try:
                _entered_at = _dt_mod.datetime.fromisoformat(_pk_detail["entered_at"])
                _hours_in = (dt.datetime.now(_ROME) - _entered_at).total_seconds() / 3600
                if _hours_in < SIGNAL_MIN_RESIDENCE_HOURS:
                    _a_residence_set.add(pk)
                elif _pk_detail.get("grace_counter", 0) < SIGNAL_GRACE_REFRESHES:
                    _a_grace_set.add(pk)
            except (ValueError, TypeError):
                pass

    # Mostra indicatori di variazione
    _a_entered = _a_current_top - _a_prev - _a_pending_set
    _a_exited = _a_prev - _a_current_top
    _a_grace_signals = {k for k, v in _a_pair_details.items()
                        if v.get("grace_counter", 0) > 0 and k in _a_prev}

    if _a_entered or _a_exited or _a_grace_signals or _a_pending_pairs:
        acol1, acol2, acol3, acol4 = st.columns(4)
        with acol1:
            for p in sorted(_a_entered):
                st.success(f"🟢 NUOVO: **{p}**")
        with acol2:
            for p in sorted(_a_exited):
                st.warning(f"🔴 RIMOSSO: **{p}**")
        with acol3:
            for p in sorted(_a_grace_signals):
                gc = _a_pair_details[p].get("grace_counter", 0)
                st.info(f"⏳ IN OSSERVAZIONE: **{p}** ({gc}h)")
        with acol4:
            for p, info in sorted(_a_pending_pairs.items()):
                cnt = info.get("consecutive_count", 0)
                st.info(f"🔎 PENDING: **{p}** ({cnt}/{SIGNAL_CONFIRMATION_REFRESHES})")

    # Tabella setup con colonna Stato
    grade_emoji = {"A+": "🟢", "A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}
    _grade_order = {"A+": 0, "A": 1, "B": 2, "C": 3, "D": 4}

    # Quando sincronizzato, usa active_setups per A/A+ (include stabilizzati)
    if _use_scheduler_asset_setups:
        _a_active = _a_state.get("active_setups", [])
        _a_active_map = {f"{s['asset']} {s['direction']}": s for s in _a_active}
        _a_non_aa = [s for s in trade_setups
                     if f"{s['asset']} {s['direction']}" not in _a_active_map]
        _display_setups_all = list(_a_active) + _a_non_aa
    else:
        _display_setups_all = list(trade_setups)

    # Sort by grade (A+ → A → B → C → D), then by quality_score descending
    _display_setups_all = sorted(
        _display_setups_all,
        key=lambda s: (_grade_order.get(s.get("grade", "D"), 4),
                       -s.get("quality_score", 0)),
    )

    # Grade filter
    _all_grades = sorted(
        {s.get("grade", "D") for s in _display_setups_all},
        key=lambda g: _grade_order.get(g, 4),
    )
    _selected_grades = st.multiselect(
        "Filtra per grado",
        options=_all_grades,
        default=[g for g in _all_grades if g in ("A+", "A", "B")],
        key="asset_grade_filter",
    )
    _display_setups = [s for s in _display_setups_all
                       if s.get("grade", "D") in _selected_grades]

    setup_rows = []
    for s in _display_setups[:20]:
        pk = f"{s['asset']} {s['direction']}"

        # Determina stato per questo setup
        if s["grade"] in ALERT_GRADES:
            if pk in _a_confirmed_set:
                stato = "✅ Confermato"
            elif pk in _a_pending_set:
                cnt = _a_pending_pairs.get(pk, {}).get("consecutive_count", 0)
                stato = f"🔎 Pending ({cnt}/{SIGNAL_CONFIRMATION_REFRESHES})"
            elif pk in _a_hysteresis_set:
                stato = "🔒 Isteresi"
            elif pk in _a_residence_set:
                stato = "🕐 Residenza"
            elif pk in _a_grace_set:
                gc = _a_pair_details.get(pk, {}).get("grace_counter", 0)
                stato = f"⏳ Grace ({gc}/{SIGNAL_GRACE_REFRESHES})"
            else:
                stato = "🆕 Nuovo"
        else:
            stato = ""

        row = {
            "Grado": f"{grade_emoji.get(s['grade'], '')} {s['grade']}",
            "Asset": s["asset_label"],
            "Direzione": "⬆ LONG" if s["direction"] == "LONG" else "⬇ SHORT",
            "Score": s["quality_score"],
            "Forza": s["strength"],
            "Stato": stato,
            "Motivi": " | ".join(s.get("reasons", [])[:3]),
        }
        setup_rows.append(row)

    st.dataframe(
        pd.DataFrame(setup_rows),
        hide_index=True,
        width='stretch',
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%d"
            ),
        },
    )
else:
    st.info("Nessun setup significativo al momento.")


# ═══════════════════════════════════════════════════════════════════════════════
# 12. COT OVERVIEW + TIMESERIES
# ═══════════════════════════════════════════════════════════════════════════════

st.subheader("📰 COT Report – Posizionamento Speculativo")

# Cards
cot_card_cols = st.columns(len(ASSETS))
for i, asset in enumerate(sorted_assets):
    cot_info = cot_scores.get(asset, {})
    with cot_card_cols[i]:
        pct = cot_info.get("net_spec_percentile", 50)
        bias = cot_info.get("bias", "NEUTRAL")
        extreme = cot_info.get("extreme")
        bias_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "⚪"}.get(bias, "⚪")
        lbl = ASSET_ICONS.get(asset, "") + " " + asset

        st.markdown(f"**{lbl}**")
        st.metric("Percentile", f"{pct:.0f}",
                  delta=f"Δ {cot_info.get('weekly_change', 0):.0f}")
        st.caption(f"{bias_icon} {bias}")
        if extreme:
            st.warning(f"⚠️ {extreme}")

# Timeseries chart
if cot_ts is not None and not cot_ts.empty:
    with st.expander("📉 COT Net Speculative — Storico", expanded=False):
        cot_assets_available = [a for a in sorted_assets if a in cot_ts.columns]
        if cot_assets_available:
            selected_cot = st.multiselect(
                "Seleziona asset COT",
                options=cot_assets_available,
                default=cot_assets_available[:3],
                format_func=lambda x: ASSET_LABELS.get(x, x),
                key="cot_ts_select",
            )
            if selected_cot:
                fig_cot = go.Figure()
                cot_colors = px.colors.qualitative.Set2
                for idx, asset in enumerate(selected_cot):
                    if asset in cot_ts.columns:
                        series = cot_ts[asset].dropna()
                        fig_cot.add_trace(go.Scatter(
                            x=series.index, y=series.values,
                            name=ASSET_LABELS.get(asset, asset),
                            line=dict(width=2, color=cot_colors[idx % len(cot_colors)]),
                            mode="lines",
                        ))
                fig_cot.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
                fig_cot.update_layout(
                    template="plotly_dark", height=350,
                    yaxis=dict(title="Net Speculative Contracts"),
                    xaxis=dict(title=""),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    margin=dict(l=60, r=20, t=30, b=30),
                    plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                )
                st.plotly_chart(fig_cot, width='stretch', key="cot_ts_chart")


# ═══════════════════════════════════════════════════════════════════════════════
# 13. MATRICE CORRELAZIONE
# ═══════════════════════════════════════════════════════════════════════════════

with st.expander("🔗 Matrice di Correlazione tra Asset (30gg)", expanded=False):
    corr_matrix = compute_asset_correlation(all_assets, window=30)
    if not corr_matrix.empty:
        corr_labels = [ASSET_LABELS.get(a, a) for a in corr_matrix.index]
        fig_corr = go.Figure(data=go.Heatmap(
            z=corr_matrix.values, x=corr_labels, y=corr_labels,
            colorscale="RdBu_r", zmin=-1, zmax=1,
            text=corr_matrix.values.round(2), texttemplate="%{text}",
            textfont=dict(size=11),
        ))
        fig_corr.update_layout(
            template="plotly_dark", height=400,
            margin=dict(l=80, r=20, t=30, b=80),
            plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
        )
        st.plotly_chart(fig_corr, width='stretch', key="corr_chart")


# ═══════════════════════════════════════════════════════════════════════════════
# VARIAZIONI SETUP A/A+ (solo visualizzazione, alert gestiti dallo scheduler)
# ═══════════════════════════════════════════════════════════════════════════════

def _read_asset_alert_state(setups: list[dict]) -> dict:
    """Legge lo stato alert senza modificarlo — lo scheduler gestisce Telegram."""
    current_top = {
        f"{s['asset']} {s['direction']}" for s in setups if s["grade"] in ALERT_GRADES
    }

    previous_top = set()
    pending_pairs = {}
    if os.path.exists(ASSET_ALERT_STATE_FILE):
        try:
            with open(ASSET_ALERT_STATE_FILE, "r", encoding="utf-8") as f:
                _st = json.load(f)
                previous_top = set(_st.get("pairs", []))
                pending_pairs = _st.get("pending_pairs", {})
        except Exception:
            pass

    entered = current_top - previous_top - set(pending_pairs.keys())
    exited = previous_top - current_top
    return {"entered": entered, "exited": exited, "current": current_top}


alert_result = _read_asset_alert_state(trade_setups)

if alert_result["entered"]:
    st.toast(f"🟢 Nuovi setup asset: {len(alert_result['entered'])}", icon="📊")
if alert_result["exited"]:
    st.toast(f"🔴 Setup asset rimossi: {len(alert_result['exited'])}", icon="📊")


# ═══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.markdown("""
<div style="text-align:center; color:gray; font-size:0.85rem;">
    <b>Asset Strength Dashboard v1.1</b><br>
    Dati: Yahoo Finance (prezzo/volume) | CFTC (COT Report settimanale)<br>
    Indicatori: RSI, ROC multi-periodo, EMA positioning, Volume-weighted momentum,
    ADX, Hurst Exponent, Efficiency Ratio, ATR<br>
    Asset: Oro, Argento, Bitcoin, Nasdaq 100, S&P 500, DAX 40, Grano<br>
    <br>
    <b>⏱ Frequenza ottimale:</b>
    H4 → ogni 4 ore · Daily → ogni giorno a chiusura · Weekly → ogni lunedì ·
    Composito → blend H4 + giornaliero + settimanale ·
    COT → venerdì sera (dati martedì)
</div>
""", unsafe_allow_html=True)
