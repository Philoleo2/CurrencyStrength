"""
💼 Portfolio Dashboard
======================
Portafoglio di investimento a lungo termine.
Regime: USA Stagflazione + Europa Reflazione.
Mix ETF + azioni, ribilanciamento semestrale con alert automatico.
"""

import datetime as dt
from zoneinfo import ZoneInfo

_ROME = ZoneInfo("Europe/Rome")

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from config import (
    PORTFOLIO_CAPITAL, PORTFOLIO_CURRENCY,
    REBALANCE_THRESHOLD_PCT, PORTFOLIO_POSITIONS,
)
from portfolio_manager import (
    load_portfolio, save_portfolio,
    compute_portfolio_metrics, record_snapshot,
    open_position, close_position, update_sl_tp,
    fetch_historical_prices, convert_to_eur,
)


# ═══════════════════════════════════════════════════════════════════════════════
# STILE
# ═══════════════════════════════════════════════════════════════════════════════

st.set_page_config(page_title="Portfolio", page_icon="💼", layout="wide")

st.markdown("""
<style>
    .main-header {
        font-size: 2rem; font-weight: 700; color: #4caf50;
        text-align: center; padding: 0.5rem 0;
    }
    .pnl-positive { color: #00c853; font-weight: 700; }
    .pnl-negative { color: #ff1744; font-weight: 700; }
    .regime-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 12px; padding: 1rem 1.2rem; margin: 0.3rem 0;
        border: 1px solid #333;
    }
    .regime-card h4 { color: #ff9800; margin: 0 0 0.3rem 0; font-size: 0.95rem; }
    div[data-testid="stMetricValue"] { font-size: 1.4rem; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-REFRESH allineato alla chiusura candela oraria (xx:00)
# ═══════════════════════════════════════════════════════════════════════════════
def _ms_to_next_hour() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    next_hour = (now + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    delta_ms = int((next_hour - now).total_seconds() * 1000) + 10_000
    return max(delta_ms, 60_000)

st_autorefresh(interval=_ms_to_next_hour(), limit=0, key="portfolio_hourly_refresh")

_current_hour_key = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H")
if st.session_state.get("_last_hour_global") != _current_hour_key:
    st.session_state["_last_hour_global"] = _current_hour_key
    st.cache_data.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — Gestione posizioni
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.image("https://img.icons8.com/color/96/portfolio.png", width=64)
    st.title("💼 Portafoglio")

    _next_h = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
    st.info(f"🔄 Prossimo refresh: {_next_h.astimezone(_ROME).strftime('%H:%M')}")

    st.divider()
    st.subheader("📝 Gestione Posizioni")

    portfolio = load_portfolio()
    pos_tickers = [p["ticker"] for p in portfolio["positions"]]
    pos_names = [f"{p['ticker']} — {p['name']}" for p in portfolio["positions"]]

    action = st.radio("Azione:", ["Apri/Modifica posizione", "Aggiorna SL/TP", "Chiudi posizione"],
                       key="portfolio_action")

    selected_idx = st.selectbox("Seleziona posizione:", range(len(pos_names)),
                                 format_func=lambda i: pos_names[i], key="pos_select")

    if action == "Apri/Modifica posizione":
        with st.form("open_pos_form"):
            sel_pos = portfolio["positions"][selected_idx]
            st.caption(f"Target: {sel_pos['target_weight']:.0%} del portafoglio "
                       f"(€{PORTFOLIO_CAPITAL * sel_pos['target_weight']:.0f})")
            entry_price = st.number_input("Prezzo di entrata", min_value=0.0,
                                           value=float(sel_pos.get("entry_price") or 0),
                                           format="%.4f", key="entry_price")
            entry_price_eur = st.number_input("Prezzo in EUR (se diversa valuta)",
                                               min_value=0.0,
                                               value=float(sel_pos.get("entry_price_eur") or 0),
                                               format="%.4f", key="entry_eur")
            quantity = st.number_input("Quantità / Quote", min_value=0.0,
                                        value=float(sel_pos.get("quantity") or 0),
                                        format="%.4f", key="qty")
            entry_date = st.date_input("Data entrata",
                                        value=dt.date.today(), key="entry_date")
            sl_val = st.number_input("Stop Loss (prezzo, 0=nessuno)", min_value=0.0,
                                      value=float(sel_pos.get("sl") or 0),
                                      format="%.4f", key="sl")
            tp_val = st.number_input("Take Profit (prezzo, 0=nessuno)", min_value=0.0,
                                      value=float(sel_pos.get("tp") or 0),
                                      format="%.4f", key="tp")
            notes = st.text_input("Note", value=sel_pos.get("notes", ""), key="notes")

            if st.form_submit_button("💾 Salva", use_container_width=True):
                open_position(
                    portfolio, sel_pos["ticker"],
                    entry_price=entry_price if entry_price > 0 else None,
                    entry_price_eur=entry_price_eur if entry_price_eur > 0 else None,
                    quantity=quantity,
                    entry_date=str(entry_date),
                    sl=sl_val if sl_val > 0 else None,
                    tp=tp_val if tp_val > 0 else None,
                    notes=notes,
                )
                st.toast("✅ Posizione salvata!", icon="💾")
                st.rerun()

    elif action == "Aggiorna SL/TP":
        with st.form("sltp_form"):
            sel_pos = portfolio["positions"][selected_idx]
            sl_new = st.number_input("Nuovo Stop Loss (0=rimuovi)", min_value=0.0,
                                      value=float(sel_pos.get("sl") or 0), format="%.4f")
            tp_new = st.number_input("Nuovo Take Profit (0=rimuovi)", min_value=0.0,
                                      value=float(sel_pos.get("tp") or 0), format="%.4f")
            if st.form_submit_button("💾 Aggiorna SL/TP", use_container_width=True):
                update_sl_tp(portfolio, sel_pos["ticker"],
                             sl=sl_new if sl_new > 0 else None,
                             tp=tp_new if tp_new > 0 else None)
                st.toast("✅ SL/TP aggiornati!", icon="🎯")
                st.rerun()

    elif action == "Chiudi posizione":
        with st.form("close_form"):
            sel_pos = portfolio["positions"][selected_idx]
            exit_price = st.number_input("Prezzo di uscita", min_value=0.0, format="%.4f")
            exit_price_eur = st.number_input("Prezzo uscita in EUR", min_value=0.0, format="%.4f")
            exit_date = st.date_input("Data uscita", value=dt.date.today())
            if st.form_submit_button("🔴 Chiudi posizione", use_container_width=True):
                if exit_price > 0:
                    close_position(portfolio, sel_pos["ticker"],
                                   exit_price, exit_price_eur or exit_price, str(exit_date))
                    st.toast("🔴 Posizione chiusa!", icon="📊")
                    st.rerun()
                else:
                    st.error("Inserisci il prezzo di uscita")

    st.divider()
    st.caption(f"Ultimo aggiornamento: {dt.datetime.now(_ROME).strftime('%Y-%m-%d %H:%M')}")

    if st.button("🔄 Aggiorna Prezzi", use_container_width=True, key="refresh_portfolio"):
        st.cache_data.clear()
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="main-header">💼 Portafoglio di Investimento</div>',
            unsafe_allow_html=True)
st.markdown(
    f"<p style='text-align:center; color:gray;'>"
    f"Regime: <b>🇺🇸 Stagflazione</b> + <b>🇪🇺 Reflazione</b> | "
    f"Capitale: <b>€{PORTFOLIO_CAPITAL:,.0f}</b> | "
    f"Aggiornato: {dt.datetime.now(_ROME).strftime('%H:%M:%S')}</p>",
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════════════════════
# CALCOLO METRICHE
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def _load_metrics():
    pf = load_portfolio()
    m = compute_portfolio_metrics(pf)
    record_snapshot(pf, m)
    save_portfolio(pf)
    return m, pf

try:
    with st.spinner("📥 Caricamento prezzi portafoglio..."):
        metrics, portfolio = _load_metrics()
except Exception as e:
    st.error(f"Errore caricamento portafoglio: {e}")
    st.stop()

positions = metrics["positions"]
has_open = any(p["quantity"] > 0 for p in positions)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. KPI BANNER
# ═══════════════════════════════════════════════════════════════════════════════

kpi_cols = st.columns(5)
with kpi_cols[0]:
    st.metric("💰 Valore Totale",
              f"€{metrics['total_value']:,.2f}",
              delta=f"€{metrics['total_pnl']:+,.2f}" if has_open else None)
with kpi_cols[1]:
    color = "normal" if metrics['total_pnl'] >= 0 else "inverse"
    st.metric("📈 P&L Totale",
              f"€{metrics['total_pnl']:+,.2f}",
              delta=f"{metrics['total_pnl_pct']:+.2f}%" if has_open else None,
              delta_color=color)
with kpi_cols[2]:
    st.metric("💵 Cash Disponibile",
              f"€{metrics['cash_eur']:,.2f}",
              delta=f"{metrics['cash_actual_weight']:.0%} del totale")
with kpi_cols[3]:
    st.metric("📊 Posizioni Attive",
              f"{sum(1 for p in positions if p['quantity'] > 0)}/{len(positions)}")
with kpi_cols[4]:
    n_alerts = len(metrics["rebalance_alerts"])
    if n_alerts:
        st.metric("⚠️ Alert Ribilanciamento", f"{n_alerts}", delta="Azione richiesta",
                  delta_color="inverse")
    else:
        st.metric("✅ Bilanciamento", "OK", delta="In linea col target")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ALERT RIBILANCIAMENTO
# ═══════════════════════════════════════════════════════════════════════════════

if metrics["rebalance_alerts"]:
    st.divider()
    st.subheader("⚠️ Alert Ribilanciamento")
    st.caption(f"Soglia di deviazione: ±{REBALANCE_THRESHOLD_PCT}%")
    for alert in metrics["rebalance_alerts"]:
        icon = "🔺" if alert["deviation"] > 0 else "🔻"
        st.warning(
            f"{icon} **{alert['name']}** ({alert['ticker']}) — "
            f"**{alert['direction'].upper()}** di {abs(alert['deviation']):.1f}%  \n"
            f"Peso target: {alert['target']:.0%} → Peso attuale: {alert['actual']:.0%}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. REGIME ECONOMICO E RAZIONALE
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
with st.expander("🌍 Regime Economico e Razionale Allocativo", expanded=False):
    reg_cols = st.columns(2)
    with reg_cols[0]:
        st.markdown("""
        <div class="regime-card">
            <h4>🇺🇸 USA — Stagflazione</h4>
            <p style="color:#ccc; font-size:0.85rem;">
            Crescita debole + inflazione persistente.<br>
            <b>Favoriti:</b> Oro (hedge), Energy (pricing power), Value/Dividendi (cash flow reale).<br>
            <b>Sfavoriti:</b> Growth/Tech (duration lunga), Bond nominali.
            </p>
        </div>
        """, unsafe_allow_html=True)
    with reg_cols[1]:
        st.markdown("""
        <div class="regime-card">
            <h4>🇪🇺 Europa — Reflazione</h4>
            <p style="color:#ccc; font-size:0.85rem;">
            Crescita in recupero + inflazione moderata in salita.<br>
            <b>Favoriti:</b> Banche (curva tassi), Ciclici, Value, Industriali.<br>
            <b>Sfavoriti:</b> Difensivi puri, Bond safe-haven.
            </p>
        </div>
        """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TABELLA POSIZIONI DETTAGLIATA
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.subheader("📋 Posizioni Portafoglio")

if not has_open:
    st.info(
        "📝 **Nessuna posizione aperta.** Usa la sidebar per inserire le posizioni.\n\n"
        "Per ogni ETF, inserisci il prezzo di acquisto, la quantità e la data.\n\n"
        "**Composizione target:**"
    )
    target_df = pd.DataFrame([
        {
            "ETF": p["name"],
            "Ticker": p["ticker"],
            "Peso": f"{p['target_weight']:.0%}",
            "Budget": f"€{PORTFOLIO_CAPITAL * p['target_weight']:.0f}",
            "Classe": p["asset_class"],
            "Regione": p["region"],
            "Razionale": p.get("rationale", ""),
        }
        for p in PORTFOLIO_POSITIONS
    ])
    target_df = pd.concat([target_df, pd.DataFrame([{
        "ETF": "Cash (riserva ribilanciamento)",
        "Ticker": "—",
        "Peso": f"{portfolio.get('cash_target_weight', 0.10):.0%}",
        "Budget": f"€{PORTFOLIO_CAPITAL * portfolio.get('cash_target_weight', 0.10):.0f}",
        "Classe": "Cash",
        "Regione": "—",
        "Razionale": "Riserva per ribilanciamento semestrale",
    }])], ignore_index=True)

    st.dataframe(target_df, use_container_width=True, hide_index=True)

    # Mostra comunque i prezzi correnti
    st.divider()
    st.subheader("📊 Prezzi Correnti")
    price_rows = []
    for pm in positions:
        if pm["current_price"] > 0:
            price_rows.append({
                "Ticker": pm["ticker"],
                "Nome": pm["name"],
                "Prezzo": f"{pm['current_price']:.2f} {pm['currency']}",
                "Prezzo EUR": f"€{pm['current_price_eur']:.2f}",
                "Var. Giorno": f"{pm['change_pct']:+.2f}%",
                "Classe": pm["asset_class"],
            })
    if price_rows:
        st.dataframe(pd.DataFrame(price_rows), use_container_width=True, hide_index=True)

else:
    # Tabella posizioni complete
    rows = []
    for pm in positions:
        if pm["quantity"] > 0:
            pnl_str = f"€{pm['pnl_eur']:+,.2f} ({pm['pnl_pct']:+.1f}%)"
            sl_str = f"{pm['sl']:.2f}" if pm["sl"] else "—"
            tp_str = f"{pm['tp']:.2f}" if pm["tp"] else "—"
            rr_str = f"{pm['rr_ratio']:.1f}:1" if pm["rr_ratio"] else "—"
            sl_dist = f"{pm['sl_distance_pct']:.1f}%" if pm["sl_distance_pct"] is not None else "—"
            weight_dev = pm["weight_deviation_pct"]
            dev_icon = "⚠️" if abs(weight_dev) > REBALANCE_THRESHOLD_PCT else "✅"

            rows.append({
                "Ticker": pm["ticker"],
                "Nome": pm["name"],
                "Dir": "⬆" if pm["direction"] == "LONG" else "⬇",
                "Qty": pm["quantity"],
                "Prezzo Entrata": f"€{pm['entry_price_eur']:.2f}" if pm["entry_price_eur"] else "—",
                "Prezzo Attuale": f"€{pm['current_price_eur']:.2f}",
                "P&L": pnl_str,
                "Valore": f"€{pm['current_value_eur']:,.2f}",
                "Peso Reale": f"{pm['actual_weight']:.1%}",
                "Target": f"{pm['target_weight']:.0%}",
                f"Dev {dev_icon}": f"{weight_dev:+.1f}%",
                "SL": sl_str,
                "TP": tp_str,
                "R/R": rr_str,
                "Dist. SL": sl_dist,
            })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


    # ═══════════════════════════════════════════════════════════════════════════
    # 5. GRAFICI ESPOSIZIONE
    # ═══════════════════════════════════════════════════════════════════════════

    st.divider()
    exp_cols = st.columns(2)

    with exp_cols[0]:
        st.subheader("🧩 Esposizione per Asset Class")
        exp_class = metrics["exposure_class"]
        if exp_class:
            fig_class = go.Figure(data=[go.Pie(
                labels=list(exp_class.keys()),
                values=list(exp_class.values()),
                hole=0.45,
                textinfo="label+percent",
                marker=dict(colors=px.colors.qualitative.Set2),
            )])
            fig_class.update_layout(
                template="plotly_dark", height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                showlegend=False,
            )
            st.plotly_chart(fig_class, use_container_width=True)

    with exp_cols[1]:
        st.subheader("🌍 Esposizione per Regione")
        exp_region = metrics["exposure_region"]
        if exp_region:
            fig_region = go.Figure(data=[go.Pie(
                labels=list(exp_region.keys()),
                values=list(exp_region.values()),
                hole=0.45,
                textinfo="label+percent",
                marker=dict(colors=px.colors.qualitative.Pastel),
            )])
            fig_region.update_layout(
                template="plotly_dark", height=350,
                margin=dict(l=20, r=20, t=20, b=20),
                plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
                showlegend=False,
            )
            st.plotly_chart(fig_region, use_container_width=True)


    # ═══════════════════════════════════════════════════════════════════════════
    # 6. PESO REALE VS TARGET (Bar chart)
    # ═══════════════════════════════════════════════════════════════════════════

    st.divider()
    st.subheader("⚖️ Peso Reale vs Target")

    weight_data = []
    for pm in positions:
        weight_data.append({"Nome": pm["name"][:25], "Tipo": "Target",
                            "Peso": pm["target_weight"] * 100})
        weight_data.append({"Nome": pm["name"][:25], "Tipo": "Reale",
                            "Peso": pm["actual_weight"] * 100})
    # Cash
    weight_data.append({"Nome": "Cash", "Tipo": "Target",
                        "Peso": metrics["cash_target_weight"] * 100})
    weight_data.append({"Nome": "Cash", "Tipo": "Reale",
                        "Peso": metrics["cash_actual_weight"] * 100})

    fig_weights = px.bar(
        pd.DataFrame(weight_data), x="Nome", y="Peso", color="Tipo",
        barmode="group", text_auto=".1f",
        color_discrete_map={"Target": "#546e7a", "Reale": "#4caf50"},
    )
    fig_weights.update_layout(
        template="plotly_dark", height=350,
        margin=dict(l=20, r=20, t=20, b=80),
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
        xaxis_title="", yaxis_title="Peso (%)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig_weights, use_container_width=True)


    # ═══════════════════════════════════════════════════════════════════════════
    # 7. RISK PER POSIZIONE
    # ═══════════════════════════════════════════════════════════════════════════

    risk_positions = [p for p in positions if p["quantity"] > 0 and p.get("risk_eur")]
    if risk_positions:
        st.divider()
        st.subheader("🛡️ Rischio per Posizione")
        risk_rows = []
        for pm in risk_positions:
            risk_rows.append({
                "Posizione": pm["name"],
                "Valore": f"€{pm['current_value_eur']:,.2f}",
                "Rischio (€)": f"€{pm['risk_eur']:,.2f}",
                "Rischio (% port.)": f"{(pm['risk_eur'] / metrics['total_value'] * 100):.1f}%"
                    if metrics['total_value'] > 0 else "—",
                "SL dist.": f"{pm['sl_distance_pct']:.1f}%" if pm["sl_distance_pct"] else "—",
                "R/R": f"{pm['rr_ratio']:.1f}:1" if pm["rr_ratio"] else "—",
            })
        st.dataframe(pd.DataFrame(risk_rows), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 8. EQUITY CURVE
# ═══════════════════════════════════════════════════════════════════════════════

snapshots = portfolio.get("snapshots", [])
if len(snapshots) >= 2:
    st.divider()
    st.subheader("📈 Equity Curve")

    snap_df = pd.DataFrame(snapshots)
    snap_df["date"] = pd.to_datetime(snap_df["date"])

    fig_equity = go.Figure()
    fig_equity.add_trace(go.Scatter(
        x=snap_df["date"], y=snap_df["total_value"],
        mode="lines+markers", name="Valore Portafoglio",
        line=dict(color="#4caf50", width=2),
        fill="tozeroy", fillcolor="rgba(76,175,80,0.1)",
    ))
    fig_equity.add_hline(
        y=PORTFOLIO_CAPITAL, line_dash="dash", line_color="gray",
        annotation_text="Capitale iniziale",
    )
    fig_equity.update_layout(
        template="plotly_dark", height=350,
        margin=dict(l=20, r=20, t=20, b=20),
        plot_bgcolor="#0e1117", paper_bgcolor="#0e1117",
        xaxis_title="Data", yaxis_title="Valore (€)",
    )
    st.plotly_chart(fig_equity, use_container_width=True)
elif has_open:
    st.divider()
    st.info("📈 L'equity curve apparirà qui dopo almeno 2 giorni di dati.")


# ═══════════════════════════════════════════════════════════════════════════════
# 9. STORICO POSIZIONI CHIUSE
# ═══════════════════════════════════════════════════════════════════════════════

closed = portfolio.get("closed", [])
if closed:
    st.divider()
    st.subheader("📜 Storico Posizioni Chiuse")

    closed_rows = []
    for c in reversed(closed):  # più recenti prima
        pnl = c.get("pnl_eur", 0)
        icon = "🟢" if pnl >= 0 else "🔴"
        closed_rows.append({
            "": icon,
            "Ticker": c["ticker"],
            "Nome": c["name"],
            "Dir": c.get("direction", "LONG"),
            "Entrata": c.get("entry_date", "—"),
            "Uscita": c.get("exit_date", "—"),
            "P. Entrata EUR": f"€{c.get('entry_price_eur', 0):.2f}",
            "P. Uscita EUR": f"€{c.get('exit_price_eur', 0):.2f}",
            "Qty": c.get("quantity", 0),
            "P&L": f"€{pnl:+,.2f}",
        })
    st.dataframe(pd.DataFrame(closed_rows), use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════════════════════

st.divider()
st.markdown("""
<div style="text-align:center; color:gray; font-size:0.85rem;">
    <b>Portfolio Dashboard v1.0</b><br>
    Dati: Yahoo Finance | Valuta: EUR | Ribilanciamento: semestrale con alert automatico<br>
    Regime: 🇺🇸 Stagflazione + 🇪🇺 Reflazione | Mix ETF US-listed (eToro compatibili)<br>
    <br>
    <b>⏱ Aggiornamento:</b> Prezzi live ogni ora a chiusura candela ·
    Equity curve giornaliera · Alert ribilanciamento continuo
</div>
""", unsafe_allow_html=True)
