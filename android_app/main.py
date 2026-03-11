"""
Currency Strength Mobile – Main Flet App (Full Dashboard)
===========================================================
Android app with complete dashboard: strength bars, gauges, momentum,
classification, trade setups, heatmap, and background monitoring.
"""

import flet as ft
import threading
import time
import logging
import json
import os
import sys
import math
from datetime import datetime, timezone

# ── Configure logging to capture fetcher/engine diagnostics ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger(__name__)

# In-memory log buffer for diagnostics display
_log_buffer = []
_LOG_BUFFER_MAX = 200

class _BufferHandler(logging.Handler):
    """Capture log records to an in-memory buffer for the diagnostics panel."""
    def emit(self, record):
        msg = self.format(record)
        _log_buffer.append(msg)
        if len(_log_buffer) > _LOG_BUFFER_MAX:
            _log_buffer.pop(0)

_buf_handler = _BufferHandler()
_buf_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
logging.getLogger().addHandler(_buf_handler)

# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL STATE
# ═══════════════════════════════════════════════════════════════════════════════

_monitor_running = False
_monitor_thread = None
_last_result = None
_last_update_time = None
_app_in_background = False
_wake_lock_thread = None
_wake_lock_active = False

# Currency colors (MetaTrader style)
CCY_COLORS = {
    "EUR": "#3399FF", "GBP": "#00CC00", "AUD": "#FF9900", "NZD": "#00CCCC",
    "CAD": "#996633", "CHF": "#CC66FF", "JPY": "#FF3333", "USD": "#FFFFFF",
}


def _strength_color(score: float) -> str:
    if score >= 80:
        return "#00c853"
    elif score >= 70:
        return "#66bb6a"
    elif score >= 55:
        return "#8bc34a"
    elif score >= 45:
        return "#78909c"
    elif score >= 35:
        return "#ff9800"
    elif score >= 20:
        return "#f44336"
    else:
        return "#ff1744"


def _signal_label(score: float) -> str:
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


def _grade_color(grade: str) -> str:
    return {"A+": "#00c853", "A": "#4caf50", "B": "#ffc107",
            "C": "#ff9800", "D": "#f44336"}.get(grade, "#78909c")


def _grade_emoji(grade: str) -> str:
    return {"A+": "🟢", "A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}.get(grade, "")


def _class_emoji(cls: str) -> str:
    return {"TREND_FOLLOWING": "📈", "MEAN_REVERTING": "🔄", "MIXED": "⚖️"}.get(cls, "")


def _vol_emoji(regime: str) -> str:
    return {"LOW": "🟢", "NORMAL": "🔵", "HIGH": "🟠", "EXTREME": "🔴"}.get(regime, "")


# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND MONITOR
# ═══════════════════════════════════════════════════════════════════════════════

def _run_analysis_cycle(progress_callback=None):
    """Run one analysis cycle: fetch data, analyze, notify."""
    global _last_result, _last_update_time
    try:
        # Go directly to analysis — no separate connectivity check.
        # The fetcher handles errors per-request with fallback backends.
        if progress_callback:
            progress_callback(0, 100, "Avvio analisi...")

        from engine import run_full_pipeline
        from notifier import check_and_notify
        result = run_full_pipeline(progress_callback=progress_callback)
        _last_result = result
        _last_update_time = datetime.now(timezone.utc)
        if result.get("trade_setups"):
            check_and_notify(result["trade_setups"])
        return result
    except Exception as e:
        _log.error(f"Analysis error: {type(e).__name__}: {e}", exc_info=True)
        raise


_last_probe_text = ""   # stored for UI display


def _check_connectivity():
    """Run deep network probe via fetcher — raises if nothing works."""
    global _last_probe_text
    from fetcher import _deep_network_probe
    _log.info("Running deep network probe...")
    summary = _deep_network_probe()
    _last_probe_text = summary
    _log.info(f"Probe summary: {summary}")
    # Pass if any backend got any HTTP response
    if any(tok in summary for tok in ("OK", ":200", ":301", ":302")):
        _log.info(f"Network OK: {summary}")
        return
    raise RuntimeError(
        f"Nessuna connessione.\n"
        f"Probe: {summary}"
    )


def _monitor_loop(interval_minutes: int, page: ft.Page):
    global _monitor_running
    _log.info(f"Monitor loop started (every {interval_minutes} min)")
    while _monitor_running:
        try:
            _run_analysis_cycle()
            if page:
                try:
                    page.pubsub.send_all("data_updated")
                except Exception:
                    pass  # page may be detached in background
        except Exception as e:
            _log.error(f"Monitor error: {e}")
        # Sleep in small increments so we can stop quickly
        for _ in range(interval_minutes * 60):
            if not _monitor_running:
                break
            time.sleep(1)
    _log.info("Monitor loop stopped")


def _keep_alive_loop():
    """Lightweight keep-alive loop to prevent Android from killing the process.
    Performs minimal CPU work every 30s to signal the OS the process is active."""
    global _wake_lock_active
    _log.info("Keep-alive loop started")
    while _wake_lock_active:
        time.sleep(30)
    _log.info("Keep-alive loop stopped")


# ═══════════════════════════════════════════════════════════════════════════════
# UI HELPER: Section Card
# ═══════════════════════════════════════════════════════════════════════════════

def _section(title: str, subtitle: str = "", content=None):
    """Creates a styled section container."""
    header = [ft.Text(title, size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)]
    if subtitle:
        header.append(ft.Text(subtitle, size=11, color=ft.Colors.WHITE54))
    children = [ft.Column(header, spacing=2)]
    if content:
        children.append(ft.Container(height=8))
        if isinstance(content, list):
            children.extend(content)
        else:
            children.append(content)
    return ft.Container(
        content=ft.Column(children, spacing=0),
        padding=12,
        bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.WHITE),
        border_radius=10,
        margin=ft.margin.only(bottom=10),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════════════════════

def main(page: ft.Page):
    global _monitor_running, _monitor_thread, _wake_lock_active, _wake_lock_thread

    page.title = "Currency Strength"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 6
    page.bgcolor = "#0d1117"

    from app_config import MONITOR_INTERVAL_MINUTES, CURRENCIES

    # ── Lifecycle handling: keep monitor alive in background ──
    def on_lifecycle_change(e: ft.AppLifecycleStateChangeEvent):
        global _app_in_background
        state = e.state
        _log.info(f"Lifecycle state: {state}")
        if state == ft.AppLifecycleState.RESUME:
            _app_in_background = False
            # Refresh UI when coming back to foreground
            if _last_result:
                try:
                    page.pubsub.send_all("data_updated")
                except Exception:
                    pass
        elif state in (ft.AppLifecycleState.PAUSE,
                       ft.AppLifecycleState.HIDE,
                       ft.AppLifecycleState.INACTIVE):
            _app_in_background = True
            _log.info("App in background — monitor continues running")

    page.on_app_lifecycle_state_change = on_lifecycle_change

    # ── Back button: minimize instead of closing the app ──
    def on_close(e):
        """Intercept close/back to prevent killing the process."""
        _log.info("Close event intercepted — app will minimize")
        # On Android, the back button triggers on_close.
        # We do nothing here so the app stays in background.

    page.on_close = on_close

    # ── Dynamic content areas ──
    dashboard_content = ft.Column(spacing=6)
    setups_content = ft.Column(spacing=6)
    monitor_content = ft.Column(spacing=6)

    status_text = ft.Text("Pronto", size=13, color=ft.Colors.WHITE70)
    progress_bar = ft.ProgressBar(visible=False, color=ft.Colors.BLUE_400)
    monitor_btn = ft.ElevatedButton("▶ Avvia Monitor", color=ft.Colors.WHITE)
    last_update_text = ft.Text("Mai aggiornato", size=11, color=ft.Colors.WHITE54)

    # ═══════════════════════════════════════════════════════════════════════
    # BUILD DASHBOARD TAB (all sections)
    # ═══════════════════════════════════════════════════════════════════════

    def _build_dashboard(result: dict):
        dashboard_content.controls.clear()
        if not result:
            dashboard_content.controls.append(
                ft.Text("Premi 🔄 Aggiorna per caricare i dati",
                        size=14, color=ft.Colors.WHITE54)
            )
            return

        composite = result.get("composite", {})
        analysis = result.get("analysis", {})
        momentum = analysis.get("momentum", {})
        classification = analysis.get("classification", {})
        atr_context = analysis.get("atr_context", {})
        velocity = analysis.get("velocity", {})
        trade_setups = result.get("trade_setups", [])

        sorted_ccys = sorted(composite.keys(),
                             key=lambda c: composite[c]["composite"], reverse=True)

        # ─────────────────────────────────────────────────────────────────
        # SECTION 1: Classifica Forza (Horizontal bar chart)
        # ─────────────────────────────────────────────────────────────────
        bar_groups = []
        for i, ccy in enumerate(reversed(sorted_ccys)):
            score = composite[ccy]["composite"]
            color = _strength_color(score)
            bar_groups.append(
                ft.BarChartGroup(x=i, bar_rods=[
                    ft.BarChartRod(
                        from_y=0, to_y=score, width=22,
                        color=color, border_radius=4,
                        tooltip=f"{ccy}: {score:.1f}",
                    )
                ])
            )

        bar_chart = ft.BarChart(
            bar_groups=bar_groups,
            horizontal=True,
            max_y=100,
            height=max(280, len(sorted_ccys) * 38),
            left_axis=ft.ChartAxis(
                labels=[
                    ft.ChartAxisLabel(value=i,
                        label=ft.Text(ccy, size=13, weight=ft.FontWeight.BOLD,
                                      color=CCY_COLORS.get(ccy, "#FFF")))
                    for i, ccy in enumerate(reversed(sorted_ccys))
                ],
                labels_size=45,
            ),
            bottom_axis=ft.ChartAxis(
                labels=[
                    ft.ChartAxisLabel(value=v,
                        label=ft.Text(str(v), size=9, color=ft.Colors.WHITE54))
                    for v in [0, 25, 50, 75, 100]
                ],
                labels_size=20,
            ),
            bgcolor=ft.Colors.TRANSPARENT,
            groups_space=6,
            interactive=True,
        )

        dashboard_content.controls.append(
            _section("🏆 Classifica Forza Valutaria",
                     "Score Composito 0-100 (H1+H4)", bar_chart)
        )

        # ─────────────────────────────────────────────────────────────────
        # SECTION 2: Gauge Cards (2 per row)
        # ─────────────────────────────────────────────────────────────────
        gauge_rows = []
        for row_start in range(0, len(sorted_ccys), 2):
            row_ccys = sorted_ccys[row_start:row_start + 2]
            row_controls = []
            for ccy in row_ccys:
                score = composite[ccy]["composite"]
                label = _signal_label(score)
                color = _strength_color(score)
                mom_delta = momentum.get(ccy, {}).get("delta", 0)
                mom_color = "#4caf50" if mom_delta > 0 else (
                    "#f44336" if mom_delta < 0 else "#888")
                pa = composite[ccy].get("price_score", 50)
                vol = composite[ccy].get("volume_score", 50)
                cot = composite[ccy].get("cot_score", 50)
                concordance = composite[ccy].get("concordance", "")

                gauge_card = ft.Container(
                    content=ft.Column([
                        ft.Text(ccy, size=16, weight=ft.FontWeight.BOLD,
                                color=CCY_COLORS.get(ccy, "#FFF"),
                                text_align=ft.TextAlign.CENTER),
                        ft.Stack([
                            ft.Container(
                                content=ft.ProgressRing(
                                    value=score / 100, stroke_width=8,
                                    color=color,
                                    bgcolor=ft.Colors.with_opacity(
                                        0.15, ft.Colors.WHITE),
                                    width=80, height=80,
                                ),
                                alignment=ft.alignment.center,
                            ),
                            ft.Container(
                                content=ft.Text(f"{score:.1f}", size=20,
                                                weight=ft.FontWeight.BOLD,
                                                color=ft.Colors.WHITE),
                                alignment=ft.alignment.center,
                                width=80, height=80,
                            ),
                        ], width=80, height=80),
                        ft.Text(label, size=10, weight=ft.FontWeight.BOLD,
                                color=color, text_align=ft.TextAlign.CENTER),
                        ft.Text(f"Mom: {mom_delta:+.1f}", size=10,
                                color=mom_color,
                                text_align=ft.TextAlign.CENTER),
                        ft.Text(f"PA:{pa:.0f} Vol:{vol:.0f} COT:{cot:.0f}",
                                size=9, color=ft.Colors.WHITE54,
                                text_align=ft.TextAlign.CENTER),
                        ft.Text(concordance, size=9,
                                color=ft.Colors.WHITE38,
                                text_align=ft.TextAlign.CENTER)
                        if concordance else ft.Container(),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=3),
                    padding=10,
                    bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.WHITE),
                    border_radius=10,
                    border=ft.border.all(
                        1, ft.Colors.with_opacity(0.15, color)),
                    expand=True,
                )
                row_controls.append(gauge_card)

            gauge_rows.append(ft.Row(row_controls, spacing=8))

        dashboard_content.controls.append(
            _section("📊 Gauge di Forza per Valuta", "",
                     ft.Column(gauge_rows, spacing=8))
        )

        # ─────────────────────────────────────────────────────────────────
        # SECTION 3: Momentum (Gainers / Losers)
        # ─────────────────────────────────────────────────────────────────
        if momentum:
            gainers = sorted(momentum.items(),
                             key=lambda x: x[1].get("delta", 0), reverse=True)
            mom_items = []
            for ccy, m in gainers:
                delta = m.get("delta", 0)
                accel = m.get("acceleration", 0)
                rank = m.get("rank_label", "N/A")
                if delta > 0:
                    icon, delta_color = "🚀", "#4caf50"
                elif delta < 0:
                    icon, delta_color = "📉", "#f44336"
                else:
                    icon, delta_color = "➖", "#888"

                mom_items.append(ft.Container(
                    content=ft.Row([
                        ft.Text(f"{icon} {ccy}", size=13,
                                weight=ft.FontWeight.BOLD,
                                color=CCY_COLORS.get(ccy, "#FFF"), width=65),
                        ft.Text(f"{delta:+.2f}", size=13,
                                weight=ft.FontWeight.BOLD,
                                color=delta_color, width=55),
                        ft.Text(f"Acc: {accel:+.2f}", size=11,
                                color=ft.Colors.WHITE54, width=75),
                        ft.Text(rank, size=10,
                                color=ft.Colors.WHITE38, expand=True),
                    ], spacing=4),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE),
                ))

            dashboard_content.controls.append(
                _section("🚀 Momentum (Chi guadagna / perde forza)",
                         "Delta forza e accelerazione nel periodo",
                         ft.Column(mom_items, spacing=2))
            )

        # ─────────────────────────────────────────────────────────────────
        # SECTION 4: Trend vs Mean Revert Classification
        # ─────────────────────────────────────────────────────────────────
        if classification:
            class_items = []
            for ccy in sorted_ccys:
                cls = classification.get(ccy, {})
                cls_type = cls.get("classification", "MIXED")
                trend_score = cls.get("trend_score", 50)
                emoji = _class_emoji(cls_type)

                if cls_type == "TREND_FOLLOWING":
                    bg = ft.Colors.with_opacity(0.08, "#4caf50")
                elif cls_type == "MEAN_REVERTING":
                    bg = ft.Colors.with_opacity(0.08, "#2196f3")
                else:
                    bg = ft.Colors.with_opacity(0.03, ft.Colors.WHITE)

                comp_score = composite[ccy]["composite"]
                direction = "LONG" if comp_score >= 50 else "SHORT"

                class_items.append(ft.Container(
                    content=ft.Row([
                        ft.Text(f"{emoji} {ccy}", size=13,
                                weight=ft.FontWeight.BOLD,
                                color=CCY_COLORS.get(ccy, "#FFF"), width=60),
                        ft.Text(cls_type.replace("_", " "), size=10,
                                color=ft.Colors.WHITE70, width=90),
                        ft.Container(
                            content=ft.ProgressBar(
                                value=trend_score / 100,
                                color="#4caf50" if trend_score >= 50
                                else "#2196f3",
                                bgcolor=ft.Colors.with_opacity(
                                    0.15, ft.Colors.WHITE),
                                bar_height=8,
                            ),
                            width=60,
                        ),
                        ft.Text(f"{trend_score:.0f}", size=11,
                                color=ft.Colors.WHITE, width=30),
                        ft.Text(direction, size=10,
                                color="#4caf50" if direction == "LONG"
                                else "#f44336",
                                width=45),
                    ], spacing=4),
                    padding=ft.padding.symmetric(horizontal=6, vertical=5),
                    bgcolor=bg,
                    border_radius=4,
                ))

            dashboard_content.controls.append(
                _section("📈 Classificazione Trend / Mean Revert",
                         "ADX, Hurst, Efficiency Ratio → Trend Score",
                         ft.Column(class_items, spacing=3))
            )

        # ─────────────────────────────────────────────────────────────────
        # SECTION 5: Volatility & Velocity
        # ─────────────────────────────────────────────────────────────────
        if atr_context:
            vol_items = []
            for ccy in sorted_ccys:
                ac = atr_context.get(ccy, {})
                vc = velocity.get(ccy, {})
                regime = ac.get("volatility_regime", "NORMAL")
                atr_pct = ac.get("atr_percentile", 50)
                vel_label = vc.get("velocity_label", "N/A")

                vol_items.append(ft.Container(
                    content=ft.Row([
                        ft.Text(f"{_vol_emoji(regime)} {ccy}", size=12,
                                weight=ft.FontWeight.BOLD,
                                color=CCY_COLORS.get(ccy, "#FFF"), width=65),
                        ft.Text(regime, size=10,
                                color=ft.Colors.WHITE54, width=60),
                        ft.Container(
                            content=ft.ProgressBar(
                                value=atr_pct / 100,
                                color="#ff9800" if atr_pct >= 65
                                else "#4caf50",
                                bgcolor=ft.Colors.with_opacity(
                                    0.15, ft.Colors.WHITE),
                                bar_height=6,
                            ),
                            width=50,
                        ),
                        ft.Text(f"ATR:{atr_pct:.0f}", size=10,
                                color=ft.Colors.WHITE54, width=48),
                        ft.Text(vel_label, size=10,
                                color=ft.Colors.WHITE38, expand=True),
                    ], spacing=4),
                    padding=ft.padding.symmetric(horizontal=6, vertical=4),
                ))

            dashboard_content.controls.append(
                _section("🌊 Volatilità & Velocità",
                         "ATR percentile e velocità di movimento",
                         ft.Column(vol_items, spacing=2))
            )

        # ─────────────────────────────────────────────────────────────────
        # SECTION 6: Strength Heatmap (Differential Matrix)
        # ─────────────────────────────────────────────────────────────────
        ccys_list = list(sorted_ccys)
        heatmap_rows = []
        # Header row
        header_cells = [ft.Container(width=35)]
        for ccy in ccys_list:
            header_cells.append(ft.Container(
                content=ft.Text(ccy, size=9, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE70,
                                text_align=ft.TextAlign.CENTER),
                width=35, alignment=ft.alignment.center,
            ))
        heatmap_rows.append(ft.Row(header_cells, spacing=1))

        for ccy1 in ccys_list:
            row_cells = [ft.Container(
                content=ft.Text(ccy1, size=9, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE70),
                width=35, alignment=ft.alignment.center_right,
            )]
            s1 = composite[ccy1]["composite"]
            for ccy2 in ccys_list:
                if ccy1 == ccy2:
                    cell_color, cell_text, text_color = "#1a1a2e", "—", "#555"
                else:
                    diff = s1 - composite[ccy2]["composite"]
                    if diff >= 15:
                        cell_color = "#1b5e20"
                    elif diff >= 8:
                        cell_color = "#2e7d32"
                    elif diff >= 3:
                        cell_color = "#33691e"
                    elif diff <= -15:
                        cell_color = "#b71c1c"
                    elif diff <= -8:
                        cell_color = "#c62828"
                    elif diff <= -3:
                        cell_color = "#4e342e"
                    else:
                        cell_color = "#263238"
                    cell_text = f"{diff:+.0f}"
                    text_color = "#FFF"

                row_cells.append(ft.Container(
                    content=ft.Text(cell_text, size=8, color=text_color,
                                    text_align=ft.TextAlign.CENTER),
                    width=35, height=28,
                    bgcolor=cell_color,
                    border_radius=3,
                    alignment=ft.alignment.center,
                ))
            heatmap_rows.append(ft.Row(row_cells, spacing=1))

        dashboard_content.controls.append(
            _section("🔥 Heatmap Differenziale di Forza",
                     "Base (righe) vs Quote (colonne)",
                     ft.Column(heatmap_rows, spacing=1))
        )

    # ═══════════════════════════════════════════════════════════════════════
    # BUILD SETUPS TAB
    # ═══════════════════════════════════════════════════════════════════════

    def _build_setups(result: dict):
        setups_content.controls.clear()
        if not result:
            setups_content.controls.append(
                ft.Text("Premi 🔄 Aggiorna per caricare i dati",
                        size=14, color=ft.Colors.WHITE54)
            )
            return

        trade_setups = result.get("trade_setups", [])
        composite = result.get("composite", {})

        # ── A/A+ Signals highlight ──
        aa_setups = [s for s in trade_setups if s["grade"] in ("A+", "A")]
        if aa_setups:
            signal_cards = []
            for s in aa_setups:
                dir_icon = "⬆" if s["direction"] == "LONG" else "⬇"
                reasons_text = " | ".join(s.get("reasons", [])[:3])

                signal_cards.append(ft.Container(
                    content=ft.Row([
                        ft.Container(
                            content=ft.Text(s["grade"], size=16,
                                            weight=ft.FontWeight.BOLD,
                                            color=ft.Colors.WHITE),
                            bgcolor=_grade_color(s["grade"]),
                            padding=ft.padding.symmetric(
                                horizontal=10, vertical=6),
                            border_radius=6,
                        ),
                        ft.Column([
                            ft.Text(
                                f"{s['pair']} {dir_icon} {s['direction']}",
                                size=14, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE),
                            ft.Text(
                                f"Score: {s['quality_score']:.0f} | "
                                f"ΔForza: {s['differential']:+.1f}",
                                size=11, color=ft.Colors.WHITE70),
                            ft.Text(reasons_text, size=9,
                                    color=ft.Colors.WHITE38)
                            if reasons_text else ft.Container(),
                        ], spacing=2, expand=True),
                    ], spacing=10),
                    padding=10,
                    bgcolor=ft.Colors.with_opacity(
                        0.1, _grade_color(s["grade"])),
                    border_radius=8,
                    border=ft.border.all(
                        1, ft.Colors.with_opacity(
                            0.3, _grade_color(s["grade"]))),
                ))

            setups_content.controls.append(
                _section("🔔 Segnali A/A+ Attivi",
                         f"{len(aa_setups)} segnali top",
                         ft.Column(signal_cards, spacing=6))
            )

        # ── Full setup table ──
        if trade_setups:
            header = ft.Container(
                content=ft.Row([
                    ft.Text("Grado", size=10, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=50),
                    ft.Text("Coppia", size=10, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=70),
                    ft.Text("Dir.", size=10, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=60),
                    ft.Text("Score", size=10, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=40),
                    ft.Text("ΔForza", size=10, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=45),
                    ft.Text("Motivi", size=10, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, expand=True),
                ], spacing=3),
                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.WHITE),
                border_radius=ft.border_radius.only(
                    top_left=8, top_right=8),
            )

            rows = [header]
            filtered = [s for s in trade_setups
                        if s["grade"] in ("A+", "A", "B")][:20]
            if not filtered:
                filtered = trade_setups[:15]

            for s in filtered:
                grade = s["grade"]
                gc = _grade_color(grade)
                dir_text = ("⬆ LONG" if s["direction"] == "LONG"
                            else "⬇ SHORT")
                dir_color = ("#4caf50" if s["direction"] == "LONG"
                             else "#f44336")
                reasons_short = ", ".join(s.get("reasons", [])[:2])

                rows.append(ft.Container(
                    content=ft.Row([
                        ft.Text(f"{_grade_emoji(grade)} {grade}", size=11,
                                weight=ft.FontWeight.BOLD,
                                color=gc, width=50),
                        ft.Text(s["pair"], size=11,
                                color=ft.Colors.WHITE, width=70),
                        ft.Text(dir_text, size=10,
                                color=dir_color, width=60),
                        ft.Text(f"{s['quality_score']:.0f}", size=11,
                                color=ft.Colors.WHITE, width=40),
                        ft.Text(f"{s['differential']:+.0f}", size=11,
                                color=ft.Colors.WHITE70, width=45),
                        ft.Text(reasons_short, size=9,
                                color=ft.Colors.WHITE38, expand=True),
                    ], spacing=3),
                    padding=ft.padding.symmetric(horizontal=8, vertical=5),
                    bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE),
                    border=ft.border.only(
                        bottom=ft.BorderSide(
                            0.5, ft.Colors.with_opacity(
                                0.08, ft.Colors.WHITE))),
                ))

            setups_content.controls.append(
                _section("🎯 Trade Setup Score",
                         f"Top {len(filtered)} setup "
                         f"(A+ ≥75, A ≥60, B ≥45)",
                         ft.Column(rows, spacing=0))
            )
        else:
            setups_content.controls.append(
                _section("🎯 Trade Setup Score",
                         "Nessun setup trovato")
            )

        # ── Summary table ──
        if composite:
            analysis = result.get("analysis", {})
            momentum = analysis.get("momentum", {})
            classification = analysis.get("classification", {})
            sorted_ccys = sorted(
                composite.keys(),
                key=lambda c: composite[c]["composite"], reverse=True)

            summary_items = []
            summary_items.append(ft.Container(
                content=ft.Row([
                    ft.Text("Val", size=9, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=35),
                    ft.Text("Score", size=9, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=38),
                    ft.Text("Label", size=9, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=70),
                    ft.Text("PA", size=9, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=28),
                    ft.Text("Vol", size=9, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=28),
                    ft.Text("COT", size=9, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=28),
                    ft.Text("Mom", size=9, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, width=38),
                    ft.Text("Class", size=9, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE70, expand=True),
                ], spacing=2),
                padding=ft.padding.symmetric(horizontal=6, vertical=4),
                bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.WHITE),
            ))

            for ccy in sorted_ccys:
                info = composite[ccy]
                mom = momentum.get(ccy, {})
                cls = classification.get(ccy, {})
                score = info["composite"]
                delta = mom.get("delta", 0)
                delta_color = ("#4caf50" if delta > 0
                               else ("#f44336" if delta < 0 else "#888"))
                cls_type = cls.get("classification", "N/A")

                summary_items.append(ft.Container(
                    content=ft.Row([
                        ft.Text(ccy, size=10, weight=ft.FontWeight.BOLD,
                                color=CCY_COLORS.get(ccy, "#FFF"),
                                width=35),
                        ft.Text(f"{score:.1f}", size=10,
                                weight=ft.FontWeight.BOLD,
                                color=_strength_color(score), width=38),
                        ft.Text(info.get("label", ""), size=9,
                                color=ft.Colors.WHITE54, width=70),
                        ft.Text(f"{info.get('price_score', 50):.0f}",
                                size=9, color=ft.Colors.WHITE54, width=28),
                        ft.Text(f"{info.get('volume_score', 50):.0f}",
                                size=9, color=ft.Colors.WHITE54, width=28),
                        ft.Text(f"{info.get('cot_score', 50):.0f}",
                                size=9, color=ft.Colors.WHITE54, width=28),
                        ft.Text(f"{delta:+.1f}", size=9,
                                color=delta_color, width=38),
                        ft.Text(
                            f"{_class_emoji(cls_type)} "
                            f"{cls_type.replace('_', ' ')[:10]}",
                            size=8, color=ft.Colors.WHITE38,
                            expand=True),
                    ], spacing=2),
                    padding=ft.padding.symmetric(horizontal=6, vertical=3),
                    bgcolor=ft.Colors.with_opacity(
                        0.02, ft.Colors.WHITE),
                ))

            setups_content.controls.append(
                _section("📋 Riepilogo Completo",
                         "Price Action, Volume, COT, Momentum, Regime",
                         ft.Column(summary_items, spacing=1))
            )

    # ═══════════════════════════════════════════════════════════════════════
    # BUILD MONITOR TAB
    # ═══════════════════════════════════════════════════════════════════════

    def _build_monitor(result: dict):
        monitor_content.controls.clear()

        # Controls section
        monitor_content.controls.append(ft.Container(
            content=ft.Column([
                ft.Text("📱 Monitor & Notifiche", size=18,
                         weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Text("Monitoraggio automatico segnali A/A+",
                         size=11, color=ft.Colors.WHITE54),
                ft.Container(height=8),
                ft.Row([
                    monitor_btn,
                    ft.ElevatedButton("🔄 Aggiorna Ora",
                                      on_click=on_refresh_click,
                                      color=ft.Colors.WHITE),
                ], spacing=10),
                progress_bar,
                status_text,
                last_update_text,
            ], spacing=6),
            padding=15,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
            border_radius=10,
        ))

        # Telegram status
        monitor_content.controls.append(ft.Container(
            content=ft.Column([
                ft.Text("📬 Telegram", size=15, weight=ft.FontWeight.BOLD,
                         color=ft.Colors.WHITE),
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE,
                            color=ft.Colors.GREEN_400, size=16),
                    ft.Text("Alert configurati e attivi", size=12,
                            color=ft.Colors.GREEN_400),
                ], spacing=6),
                ft.Text("Notifiche per nuovi segnali A/A+",
                         size=10, color=ft.Colors.WHITE54),
            ], spacing=4),
            padding=12,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
            border_radius=10,
            margin=ft.margin.only(top=10),
        ))

        # Background execution section
        monitor_content.controls.append(ft.Container(
            content=ft.Column([
                ft.Text("🔋 Esecuzione in Background", size=15,
                         weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Text(
                    "Per ricevere notifiche con l'app chiusa, "
                    "disattiva l'ottimizzazione batteria per questa app.",
                    size=10, color=ft.Colors.WHITE54),
                ft.Container(height=4),
                ft.ElevatedButton(
                    "⚙️ Impostazioni Batteria",
                    on_click=lambda _: _request_battery_optimization_exemption(),
                    color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.ORANGE),
                ),
                ft.Container(height=4),
                ft.Text(
                    "Il monitor si avvia automaticamente.\n"
                    "L'app continua a funzionare in background e "
                    "invia notifiche Telegram per segnali A/A+.",
                    size=10, color=ft.Colors.WHITE38),
            ], spacing=4),
            padding=12,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
            border_radius=10,
            margin=ft.margin.only(top=10),
        ))

        # Active A/A+ signals
        if result:
            trade_setups = result.get("trade_setups", [])
            aa_setups = [s for s in trade_setups
                         if s["grade"] in ("A+", "A")]

            signals_children = []
            if aa_setups:
                for s in aa_setups:
                    dir_icon = "⬆" if s["direction"] == "LONG" else "⬇"
                    signals_children.append(ft.Container(
                        content=ft.Row([
                            ft.Container(
                                content=ft.Text(
                                    s["grade"], size=14,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE),
                                bgcolor=_grade_color(s["grade"]),
                                padding=ft.padding.symmetric(
                                    horizontal=8, vertical=4),
                                border_radius=6,
                            ),
                            ft.Column([
                                ft.Text(
                                    f"{s['pair']} {dir_icon} "
                                    f"{s['direction']}",
                                    size=13,
                                    weight=ft.FontWeight.BOLD,
                                    color=ft.Colors.WHITE),
                                ft.Text(
                                    f"Score: {s['quality_score']:.0f}"
                                    f" | ΔForza: "
                                    f"{s['differential']:+.1f}",
                                    size=10,
                                    color=ft.Colors.WHITE70),
                            ], spacing=2, expand=True),
                        ], spacing=8),
                        padding=8,
                        bgcolor=ft.Colors.with_opacity(
                            0.08, _grade_color(s["grade"])),
                        border_radius=8,
                    ))
            else:
                signals_children.append(
                    ft.Text("Nessun segnale A/A+ attivo",
                            size=12, color=ft.Colors.WHITE54))

            monitor_content.controls.append(ft.Container(
                content=ft.Column([
                    ft.Text(
                        f"🔔 Segnali A/A+ Attivi ({len(aa_setups)})",
                        size=15, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE),
                    *signals_children,
                ], spacing=6),
                padding=12,
                bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
                border_radius=10,
                margin=ft.margin.only(top=10),
            ))

        # ── Diagnostics: Probe Results + Log ──
        probe_text = _last_probe_text or "(probe non ancora eseguito)"
        # Colour: green if any backend says 200, red if all fail
        probe_color = (ft.Colors.GREEN_300 if ":200" in probe_text
                       else ft.Colors.AMBER_300 if "OK" in probe_text
                       else ft.Colors.RED_300)
        probe_bg = (ft.Colors.with_opacity(0.15, ft.Colors.GREEN)
                    if ":200" in probe_text
                    else ft.Colors.with_opacity(0.15, ft.Colors.RED))

        log_lines = _log_buffer[-50:] if _log_buffer else ["(nessun log)"]
        monitor_content.controls.append(ft.Container(
            content=ft.Column([
                ft.Text("🔍 Diagnostica", size=15,
                         weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                # ── Prominent probe results banner ──
                ft.Container(
                    content=ft.Column([
                        ft.Text("NETWORK PROBE", size=10,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.WHITE),
                        ft.Text(probe_text, size=8,
                                color=probe_color, selectable=True),
                    ], spacing=2),
                    bgcolor=probe_bg,
                    padding=10,
                    border_radius=6,
                ),
                ft.Container(height=2),
                ft.Text("Ultimi log:", size=10, color=ft.Colors.WHITE38),
                ft.Container(
                    content=ft.Column(
                        [ft.Text(line, size=8,
                                 color=ft.Colors.RED_300 if "ERROR" in line
                                 else ft.Colors.AMBER_300 if "WARNING" in line
                                 else ft.Colors.WHITE54,
                                 selectable=True)
                         for line in log_lines],
                        spacing=1,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    bgcolor=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
                    padding=8,
                    border_radius=6,
                    height=250,
                ),
            ], spacing=4),
            padding=12,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
            border_radius=10,
            margin=ft.margin.only(top=10),
        ))

    # ═══════════════════════════════════════════════════════════════════════
    # REFRESH ALL UI
    # ═══════════════════════════════════════════════════════════════════════

    def refresh_ui():
        if _last_result:
            _build_dashboard(_last_result)
            _build_setups(_last_result)
            _build_monitor(_last_result)
            if _last_update_time:
                last_update_text.value = (
                    f"Ultimo aggiornamento: "
                    f"{_last_update_time.strftime('%H:%M:%S UTC')}")
        page.update()

    def on_pubsub_message(msg):
        if msg == "data_updated":
            refresh_ui()

    page.pubsub.subscribe(on_pubsub_message)

    # ── Actions ──

    def on_refresh_click(e):
        status_text.value = "Scaricamento dati in corso..."
        status_text.color = ft.Colors.WHITE70
        progress_bar.visible = True
        page.update()

        def do_refresh():
            try:
                _last_ui_update = [0.0]

                def progress_cb(done, total, msg):
                    status_text.value = msg
                    progress_bar.value = done / max(total, 1)
                    now = time.time()
                    if now - _last_ui_update[0] >= 2.0:
                        _last_ui_update[0] = now
                        try:
                            page.update()
                        except Exception:
                            pass

                _run_analysis_cycle(progress_callback=progress_cb)
                status_text.value = "Analisi completata!"
                status_text.color = ft.Colors.GREEN_400
                progress_bar.visible = False
                page.pubsub.send_all("data_updated")
            except Exception as ex:
                # Show detailed error on screen
                err_msg = str(ex)
                if len(err_msg) > 200:
                    err_msg = err_msg[:200] + "..."
                status_text.value = f"❌ {err_msg}"
                status_text.color = ft.Colors.RED_400
                progress_bar.visible = False
                _log.error(f"Refresh failed: {type(ex).__name__}: {ex}")
                # Rebuild monitor to show diagnostics log
                try:
                    _build_monitor(None)
                    page.update()
                except Exception:
                    pass

        threading.Thread(target=do_refresh, daemon=True).start()

    def _start_keep_alive():
        """Start background keep-alive thread to prevent process kill."""
        global _wake_lock_active, _wake_lock_thread
        if not _wake_lock_active:
            _wake_lock_active = True
            _wake_lock_thread = threading.Thread(
                target=_keep_alive_loop, daemon=False)
            _wake_lock_thread.start()
            _log.info("Keep-alive started")

    def _stop_keep_alive():
        """Stop background keep-alive thread."""
        global _wake_lock_active
        _wake_lock_active = False
        _log.info("Keep-alive stopped")

    def _send_persistent_notification(active: bool):
        """Show/clear persistent notification for background monitor."""
        try:
            from notifier import send_android_notification
            if active:
                send_android_notification(
                    "📊 Currency Strength Monitor",
                    f"Monitoraggio attivo — aggiornamento ogni {MONITOR_INTERVAL_MINUTES} min"
                )
        except Exception as ex:
            _log.warning(f"Persistent notification error: {ex}")

    def _request_battery_optimization_exemption():
        """Ask Android to exempt this app from battery optimization."""
        try:
            # Try the specific per-app request first
            page.launch_url(
                "intent:#Intent;"
                "action=android.settings.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS;"
                "data=package:com.currencystrength.currencystrength;"
                "end"
            )
        except Exception:
            try:
                # Fallback: open general battery optimization settings
                page.launch_url(
                    "intent:#Intent;"
                    "action=android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS;"
                    "end"
                )
            except Exception as ex:
                _log.warning(f"Battery optimization request failed: {ex}")

    def on_monitor_toggle(e):
        global _monitor_running, _monitor_thread
        if _monitor_running:
            _monitor_running = False
            _stop_keep_alive()
            monitor_btn.text = "▶ Avvia Monitor"
            monitor_btn.bgcolor = None
            status_text.value = "Monitor fermato"
        else:
            _monitor_running = True
            monitor_btn.text = "⏸ Ferma Monitor"
            monitor_btn.bgcolor = ft.Colors.with_opacity(
                0.3, ft.Colors.GREEN)
            status_text.value = (
                f"Monitor attivo (ogni {MONITOR_INTERVAL_MINUTES} min)")
            # Start monitor thread (daemon=False so it survives background)
            _monitor_thread = threading.Thread(
                target=_monitor_loop,
                args=(MONITOR_INTERVAL_MINUTES, page),
                daemon=False,
            )
            _monitor_thread.start()
            # Start keep-alive and persistent notification
            _start_keep_alive()
            _send_persistent_notification(True)
        page.update()

    monitor_btn.on_click = on_monitor_toggle

    # ═══════════════════════════════════════════════════════════════════════
    # NAVIGATION
    # ═══════════════════════════════════════════════════════════════════════

    dashboard_tab = ft.Column(
        [dashboard_content], scroll=ft.ScrollMode.AUTO, expand=True)
    setups_tab = ft.Column(
        [setups_content], scroll=ft.ScrollMode.AUTO, expand=True)
    monitor_tab = ft.Column(
        [monitor_content], scroll=ft.ScrollMode.AUTO, expand=True)

    content_area = ft.Column(expand=True)

    def show_tab(index: int):
        content_area.controls.clear()
        if index == 0:
            content_area.controls.append(dashboard_tab)
        elif index == 1:
            content_area.controls.append(setups_tab)
        elif index == 2:
            content_area.controls.append(monitor_tab)
        page.update()

    def on_nav_change(e):
        show_tab(e.control.selected_index)

    nav_bar = ft.NavigationBar(
        selected_index=0,
        on_change=on_nav_change,
        bgcolor=ft.Colors.with_opacity(0.95, "#1a1a2e"),
        destinations=[
            ft.NavigationBarDestination(
                icon=ft.Icons.BAR_CHART,
                selected_icon=ft.Icons.BAR_CHART,
                label="Dashboard",
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.TABLE_CHART,
                selected_icon=ft.Icons.TABLE_CHART,
                label="Setup",
            ),
            ft.NavigationBarDestination(
                icon=ft.Icons.NOTIFICATIONS,
                selected_icon=ft.Icons.NOTIFICATIONS_ACTIVE,
                label="Monitor",
            ),
        ],
    )

    page.navigation_bar = nav_bar
    page.add(content_area)

    # Initialize monitor tab (needs controls before data)
    _build_monitor(None)
    show_tab(2)  # Show monitor first

    # Auto-start: run first analysis and AUTO-START monitor
    status_text.value = "Primo avvio - scaricamento dati..."
    progress_bar.visible = True
    progress_bar.value = None
    page.update()

    def initial_load():
        try:
            _last_ui_update = [0.0]  # mutable for closure

            def progress_cb(done, total, msg):
                status_text.value = msg
                progress_bar.value = done / max(total, 1)
                # Throttle page.update() to max once every 2s
                # On Android, page.update() is SYNCHRONOUS and blocks
                # the download thread if Android throttles the UI.
                now = time.time()
                if now - _last_ui_update[0] >= 2.0:
                    _last_ui_update[0] = now
                    try:
                        page.update()
                    except Exception:
                        pass

            _run_analysis_cycle(progress_callback=progress_cb)
            progress_bar.visible = False
            status_text.color = ft.Colors.GREEN_400
            page.pubsub.send_all("data_updated")

            # Auto-start the monitor after first successful load
            global _monitor_running, _monitor_thread
            if not _monitor_running:
                _monitor_running = True
                _monitor_thread = threading.Thread(
                    target=_monitor_loop,
                    args=(MONITOR_INTERVAL_MINUTES, page),
                    daemon=False,
                )
                _monitor_thread.start()
                _start_keep_alive()
                _send_persistent_notification(True)
                monitor_btn.text = "⏸ Ferma Monitor"
                monitor_btn.bgcolor = ft.Colors.with_opacity(
                    0.3, ft.Colors.GREEN)
                status_text.value = (
                    f"Monitor attivo (ogni {MONITOR_INTERVAL_MINUTES} min)")
            else:
                status_text.value = "Pronto! Vai su Dashboard."
        except Exception as ex:
            progress_bar.visible = False
            err_msg = str(ex)
            if len(err_msg) > 200:
                err_msg = err_msg[:200] + "..."
            status_text.value = f"❌ {err_msg}"
            status_text.color = ft.Colors.RED_400
            _log.error(f"Initial load failed: {type(ex).__name__}: {ex}")

            # Run network diagnostics and show results
            try:
                from fetcher import run_diagnostics, _last_errors
                _log.info("Running network diagnostics after failure...")
                diag = run_diagnostics()
                diag_text = "\n".join(diag) if diag else "Nessun risultato"
                if _last_errors:
                    diag_text += f"\n\nUltimi errori: {', '.join(_last_errors)}"

                # Show diagnostics in a dialog
                def close_dlg(e):
                    dlg.open = False
                    page.update()

                dlg = ft.AlertDialog(
                    title=ft.Text("Diagnostica Rete", size=18,
                                  weight=ft.FontWeight.BOLD),
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text("Risultati test connessione:",
                                    size=13, color=ft.Colors.WHITE70),
                            ft.Text(diag_text, size=11,
                                    selectable=True,
                                    color=ft.Colors.WHITE),
                        ], scroll=ft.ScrollMode.AUTO, spacing=8),
                        width=350, height=400,
                    ),
                    actions=[
                        ft.TextButton("Chiudi", on_click=close_dlg),
                    ],
                )
                page.overlay.append(dlg)
                dlg.open = True
                page.update()
            except Exception as diag_err:
                _log.error(f"Diagnostics failed: {diag_err}")

            # Rebuild monitor to show diagnostics log
            try:
                _build_monitor(None)
                page.update()
            except Exception:
                pass

    threading.Thread(target=initial_load, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

ft.app(target=main)
