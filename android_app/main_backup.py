"""
Currency Strength Mobile – Main Flet App
=========================================
Android app with background monitoring and push notifications
for A/A+ trade setup signals.
"""

import flet as ft
import threading
import time
import logging
import json
import os
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL STATE
# ═══════════════════════════════════════════════════════════════════════════════

_monitor_running = False
_monitor_thread = None
_last_result = None
_last_update_time = None


def _strength_color(score: float) -> str:
    if score >= 80:
        return "#00c853"
    elif score >= 70:
        return "#66bb6a"
    elif score <= 20:
        return "#ff1744"
    elif score <= 30:
        return "#ef5350"
    else:
        return "#78909c"


def _grade_color(grade: str) -> str:
    return {
        "A+": "#00c853", "A": "#4caf50", "B": "#ffc107",
        "C": "#ff9800", "D": "#f44336",
    }.get(grade, "#78909c")


def _grade_emoji(grade: str) -> str:
    return {"A+": "🟢", "A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}.get(grade, "")


# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND MONITOR
# ═══════════════════════════════════════════════════════════════════════════════

def _run_analysis_cycle(progress_callback=None):
    """Run one analysis cycle: fetch data, analyze, notify."""
    global _last_result, _last_update_time

    try:
        from engine import run_full_pipeline
        from notifier import check_and_notify

        result = run_full_pipeline(progress_callback=progress_callback)
        _last_result = result
        _last_update_time = datetime.now(timezone.utc)

        # Check for A/A+ signals and send notifications
        if result.get("trade_setups"):
            check_and_notify(result["trade_setups"])

        return result
    except RuntimeError as e:
        _log.error(f"Analysis runtime error: {e}")
        raise  # Let caller handle UI feedback
    except Exception as e:
        _log.error(f"Analysis error: {e}")
        raise  # Let caller handle UI feedback


def _monitor_loop(interval_minutes: int, page: ft.Page):
    """Background loop that runs analysis every interval_minutes."""
    global _monitor_running
    while _monitor_running:
        try:
            _run_analysis_cycle()
            if page:
                page.pubsub.send_all("data_updated")
        except Exception as e:
            _log.error(f"Monitor error: {e}")
            # Don't crash the loop, just log and retry next cycle

        # Sleep in small increments so we can stop quickly
        for _ in range(interval_minutes * 60):
            if not _monitor_running:
                break
            time.sleep(1)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════════════════════

def main(page: ft.Page):
    global _monitor_running, _monitor_thread

    page.title = "Currency Strength"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 10
    page.scroll = ft.ScrollMode.AUTO

    # ── State refs ──
    strength_list = ft.Column(spacing=4)
    setups_list = ft.Column(spacing=4)
    status_text = ft.Text("Pronto", size=14, color=ft.Colors.WHITE70)
    progress_bar = ft.ProgressBar(visible=False, color=ft.Colors.BLUE_400)
    monitor_btn = ft.ElevatedButton("▶ Avvia Monitor", color=ft.Colors.WHITE)
    last_update_text = ft.Text("Mai aggiornato", size=12, color=ft.Colors.WHITE54)
    active_signals_list = ft.Column(spacing=4)

    from app_config import MONITOR_INTERVAL_MINUTES

    # ── Build UI sections ──

    def build_strength_cards(composite: dict):
        """Build currency strength cards."""
        strength_list.controls.clear()
        if not composite:
            strength_list.controls.append(
                ft.Text("Nessun dato disponibile", color=ft.Colors.WHITE54)
            )
            return

        sorted_ccys = sorted(composite.keys(),
                             key=lambda c: composite[c]["composite"], reverse=True)

        for ccy in sorted_ccys:
            data = composite[ccy]
            score = data["composite"]
            label = data.get("label", "")
            color = _strength_color(score)

            card = ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Text(ccy, size=18, weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.WHITE),
                        width=60,
                    ),
                    ft.Column([
                        ft.ProgressBar(
                            value=score / 100,
                            color=color,
                            bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.WHITE),
                            width=180,
                            bar_height=12,
                        ),
                    ], spacing=2, expand=True),
                    ft.Text(f"{score:.0f}", size=18, weight=ft.FontWeight.BOLD,
                            color=color),
                    ft.Text(label, size=11, color=ft.Colors.WHITE54, width=90),
                ], alignment=ft.MainAxisAlignment.START, spacing=10),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
                bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
                border_radius=8,
            )
            strength_list.controls.append(card)

    def build_setups_table(trade_setups: list[dict]):
        """Build trade setups table."""
        setups_list.controls.clear()
        if not trade_setups:
            setups_list.controls.append(
                ft.Text("Nessun setup disponibile", color=ft.Colors.WHITE54)
            )
            return

        # Header
        header = ft.Container(
            content=ft.Row([
                ft.Text("Grado", size=11, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE70, width=55),
                ft.Text("Coppia", size=11, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE70, width=80),
                ft.Text("Dir.", size=11, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE70, width=65),
                ft.Text("Score", size=11, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE70, width=50),
                ft.Text("ΔForza", size=11, weight=ft.FontWeight.BOLD,
                        color=ft.Colors.WHITE70, width=55),
            ], spacing=4),
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            bgcolor=ft.Colors.with_opacity(0.1, ft.Colors.WHITE),
            border_radius=ft.border_radius.only(top_left=8, top_right=8),
        )
        setups_list.controls.append(header)

        # Show top 20 setups with grade B or better
        filtered = [s for s in trade_setups if s["grade"] in ("A+", "A", "B")][:20]
        if not filtered:
            filtered = trade_setups[:15]

        for s in filtered:
            grade = s["grade"]
            grade_color = _grade_color(grade)
            dir_text = "⬆ LONG" if s["direction"] == "LONG" else "⬇ SHORT"
            dir_color = "#4caf50" if s["direction"] == "LONG" else "#f44336"

            row = ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Text(f"{_grade_emoji(grade)} {grade}",
                                        size=12, weight=ft.FontWeight.BOLD,
                                        color=grade_color),
                        width=55,
                    ),
                    ft.Text(s["pair"], size=12, color=ft.Colors.WHITE, width=80),
                    ft.Text(dir_text, size=11, color=dir_color, width=65),
                    ft.Text(f"{s['quality_score']:.0f}", size=12,
                            color=ft.Colors.WHITE, width=50),
                    ft.Text(f"{s['differential']:+.0f}", size=12,
                            color=ft.Colors.WHITE70, width=55),
                ], spacing=4),
                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.WHITE),
                border=ft.border.only(
                    bottom=ft.BorderSide(0.5, ft.Colors.with_opacity(0.1, ft.Colors.WHITE))
                ),
            )
            setups_list.controls.append(row)

    def build_active_signals(trade_setups: list[dict]):
        """Build list of active A/A+ signals."""
        active_signals_list.controls.clear()
        aa_setups = [s for s in (trade_setups or []) if s["grade"] in ("A+", "A")]

        if not aa_setups:
            active_signals_list.controls.append(
                ft.Container(
                    content=ft.Text("Nessun segnale A/A+ attivo",
                                    size=13, color=ft.Colors.WHITE54),
                    padding=10,
                )
            )
            return

        for s in aa_setups:
            dir_icon = "⬆" if s["direction"] == "LONG" else "⬇"
            dir_color = "#4caf50" if s["direction"] == "LONG" else "#f44336"

            signal_card = ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Text(s["grade"], size=16, weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.WHITE),
                        bgcolor=_grade_color(s["grade"]),
                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                        border_radius=6,
                    ),
                    ft.Column([
                        ft.Text(f"{s['pair']} {dir_icon} {s['direction']}",
                                size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        ft.Text(f"Score: {s['quality_score']:.0f} | ΔForza: {s['differential']:+.0f}",
                                size=11, color=ft.Colors.WHITE70),
                    ], spacing=2, expand=True),
                ], spacing=10),
                padding=10,
                bgcolor=ft.Colors.with_opacity(0.08, _grade_color(s["grade"])),
                border_radius=8,
                border=ft.border.all(1, ft.Colors.with_opacity(0.3, _grade_color(s["grade"]))),
            )
            active_signals_list.controls.append(signal_card)

    # ── Actions ──

    def refresh_ui():
        """Refresh all UI components with latest data."""
        global _last_result
        if _last_result:
            build_strength_cards(_last_result.get("composite", {}))
            build_setups_table(_last_result.get("trade_setups", []))
            build_active_signals(_last_result.get("trade_setups", []))
            if _last_update_time:
                last_update_text.value = f"Ultimo aggiornamento: {_last_update_time.strftime('%H:%M:%S UTC')}"
        page.update()

    def on_pubsub_message(msg):
        if msg == "data_updated":
            refresh_ui()

    page.pubsub.subscribe(on_pubsub_message)

    def on_refresh_click(e):
        """Manual refresh button."""
        status_text.value = "Scaricamento dati in corso..."
        status_text.color = ft.Colors.WHITE70
        progress_bar.visible = True
        page.update()

        def do_refresh():
            try:
                def progress_cb(done, total, msg):
                    status_text.value = msg
                    progress_bar.value = done / max(total, 1)
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
                status_text.value = f"⚠ Errore: {ex}"
                status_text.color = ft.Colors.RED_400
                progress_bar.visible = False
                try:
                    page.update()
                except Exception:
                    pass

        threading.Thread(target=do_refresh, daemon=True).start()

    def on_monitor_toggle(e):
        """Start/stop background monitor."""
        global _monitor_running, _monitor_thread

        if _monitor_running:
            _monitor_running = False
            monitor_btn.text = "▶ Avvia Monitor"
            monitor_btn.bgcolor = None
            status_text.value = "Monitor fermato"
        else:
            _monitor_running = True
            monitor_btn.text = "⏸ Ferma Monitor"
            monitor_btn.bgcolor = ft.Colors.with_opacity(0.3, ft.Colors.GREEN)
            status_text.value = f"Monitor attivo (ogni {MONITOR_INTERVAL_MINUTES} min)"
            _monitor_thread = threading.Thread(
                target=_monitor_loop,
                args=(MONITOR_INTERVAL_MINUTES, page),
                daemon=True,
            )
            _monitor_thread.start()
        page.update()

    monitor_btn.on_click = on_monitor_toggle

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 1: DASHBOARD (Currency Strength)
    # ═══════════════════════════════════════════════════════════════════════

    dashboard_tab = ft.Column([
        ft.Container(
            content=ft.Column([
                ft.Text("💱 Forza Valutaria", size=20, weight=ft.FontWeight.BOLD,
                         color=ft.Colors.WHITE),
                ft.Text("Score Composito 0-100 (H1+H4)",
                         size=12, color=ft.Colors.WHITE54),
            ], spacing=4),
            padding=ft.padding.only(bottom=10),
        ),
        strength_list,
    ], scroll=ft.ScrollMode.AUTO, expand=True)

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 2: TRADE SETUPS
    # ═══════════════════════════════════════════════════════════════════════

    setups_tab = ft.Column([
        ft.Container(
            content=ft.Column([
                ft.Text("🎯 Trade Setup Score", size=20, weight=ft.FontWeight.BOLD,
                         color=ft.Colors.WHITE),
                ft.Text("Classifica coppie per qualità (A+ ≥75, A ≥60)",
                         size=12, color=ft.Colors.WHITE54),
            ], spacing=4),
            padding=ft.padding.only(bottom=10),
        ),
        setups_list,
    ], scroll=ft.ScrollMode.AUTO, expand=True)

    # ═══════════════════════════════════════════════════════════════════════
    # TAB 3: MONITOR & SIGNALS
    # ═══════════════════════════════════════════════════════════════════════

    monitor_tab = ft.Column([
        ft.Container(
            content=ft.Column([
                ft.Text("📱 Monitor & Notifiche", size=20, weight=ft.FontWeight.BOLD,
                         color=ft.Colors.WHITE),
                ft.Text("Monitoraggio automatico segnali A/A+",
                         size=12, color=ft.Colors.WHITE54),
            ], spacing=4),
            padding=ft.padding.only(bottom=10),
        ),

        # Controls
        ft.Container(
            content=ft.Column([
                ft.Row([
                    monitor_btn,
                    ft.ElevatedButton(
                        "🔄 Aggiorna Ora",
                        on_click=on_refresh_click,
                        color=ft.Colors.WHITE,
                    ),
                ], spacing=10),
                progress_bar,
                status_text,
                last_update_text,
            ], spacing=8),
            padding=15,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
            border_radius=10,
        ),

        ft.Container(height=15),

        # Telegram status
        ft.Container(
            content=ft.Column([
                ft.Text("📬 Telegram", size=16, weight=ft.FontWeight.BOLD,
                         color=ft.Colors.WHITE),
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_400, size=18),
                    ft.Text("Alert configurati e attivi",
                            size=13, color=ft.Colors.GREEN_400),
                ], spacing=6),
                ft.Text("Riceverai notifiche Telegram quando compaiono nuovi segnali A o A+",
                         size=11, color=ft.Colors.WHITE54),
            ], spacing=6),
            padding=15,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
            border_radius=10,
        ),

        ft.Container(height=15),

        # Active signals
        ft.Container(
            content=ft.Column([
                ft.Text("🔔 Segnali A/A+ Attivi", size=16, weight=ft.FontWeight.BOLD,
                         color=ft.Colors.WHITE),
                active_signals_list,
            ], spacing=8),
            padding=15,
            bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.WHITE),
            border_radius=10,
        ),
    ], scroll=ft.ScrollMode.AUTO, expand=True)

    # ═══════════════════════════════════════════════════════════════════════
    # NAVIGATION
    # ═══════════════════════════════════════════════════════════════════════

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
        selected_index=2,  # Start on Monitor tab
        on_change=on_nav_change,
        bgcolor=ft.Colors.with_opacity(0.95, "#1a1a2e"),
        destinations=[
            ft.NavigationBarDestination(
                icon=ft.Icons.BAR_CHART,
                selected_icon=ft.Icons.BAR_CHART,
                label="Forza",
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

    # ── Page layout ──
    page.bgcolor = "#0d1117"
    page.navigation_bar = nav_bar

    page.add(content_area)
    show_tab(2)  # Start on Monitor tab

    # Auto-start: run first analysis
    status_text.value = "Primo avvio - scaricamento dati..."
    progress_bar.visible = True
    progress_bar.value = None  # indeterminate
    page.update()

    def initial_load():
        try:
            def progress_cb(done, total, msg):
                status_text.value = msg
                progress_bar.value = done / max(total, 1)
                try:
                    page.update()
                except Exception:
                    pass

            _run_analysis_cycle(progress_callback=progress_cb)
            progress_bar.visible = False
            status_text.value = "Pronto! Avvia il monitor per il monitoraggio continuo."
            status_text.color = ft.Colors.GREEN_400
            page.pubsub.send_all("data_updated")
        except Exception as ex:
            progress_bar.visible = False
            status_text.value = f"⚠ Errore caricamento: {ex}"
            status_text.color = ft.Colors.RED_400
            _log.error(f"Initial load failed: {ex}")
            try:
                page.update()
            except Exception:
                pass

    threading.Thread(target=initial_load, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

ft.app(target=main)
