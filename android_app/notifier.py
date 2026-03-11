"""
Currency Strength Mobile – Notification System
Telegram notifications + local Android notification via plyer.
"""

import json
import os
import ssl
import logging
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

from app_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ALERT_GRADES

_log = logging.getLogger(__name__)

# State file path (will be in app's data directory)
_STATE_DIR = os.path.join(os.path.expanduser("~"), ".currency_strength")
_STATE_FILE = os.path.join(_STATE_DIR, "alert_state.json")


def _ensure_state_dir():
    os.makedirs(_STATE_DIR, exist_ok=True)


def load_previous_state() -> set[str]:
    _ensure_state_dir()
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("pairs", []))
        except Exception:
            pass
    return set()


def save_current_state(pairs: set[str]):
    _ensure_state_dir()
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "pairs": sorted(pairs),
                "updated": datetime.now(timezone.utc).isoformat(),
            }, f, indent=2)
    except Exception as e:
        _log.warning(f"Cannot save state: {e}")


def send_telegram(text: str) -> bool:
    """Send a Telegram message. Returns True if successful."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers={
            "Content-Type": "application/json",
            "User-Agent": "CurrencyStrength/1.0",
        })
        ctx = ssl._create_unverified_context()
        resp = urlopen(req, timeout=10, context=ctx)
        return resp.status == 200
    except Exception as e:
        _log.warning(f"Telegram error: {e}")
        return False


def send_android_notification(title: str, message: str):
    """Send a local Android notification using plyer."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message,
            app_name="Currency Strength",
            timeout=0,  # persistent (0 = no auto-dismiss)
        )
    except Exception as e:
        _log.warning(f"Notification error: {e}")


def send_monitor_status_notification(active: bool, interval_min: int = 60):
    """Show persistent notification indicating monitor is active/stopped."""
    try:
        if active:
            send_android_notification(
                "📊 Monitor Attivo",
                f"Analisi automatica ogni {interval_min} min — "
                f"Notifiche Telegram per segnali A/A+"
            )
        # When stopped, we don't send another notification
    except Exception as e:
        _log.warning(f"Monitor notification error: {e}")


def check_and_notify(trade_setups: list[dict]) -> dict:
    """
    Compare current A/A+ signals with previous state.
    Send notifications for new signals.
    Returns dict with entered, exited, current sets.
    """
    current_top = {
        f"{s['pair']} {s['direction']}"
        for s in trade_setups
        if s["grade"] in ALERT_GRADES
    }

    current_details = {
        f"{s['pair']} {s['direction']}": s
        for s in trade_setups
        if s["grade"] in ALERT_GRADES
    }

    previous_top = load_previous_state()
    entered = current_top - previous_top
    exited = previous_top - current_top

    now_str = datetime.now(timezone.utc).strftime("%H:%M %d/%m")

    # Send notifications for NEW signals
    if entered:
        lines = [f"🟢 <b>NUOVI SETUP ({now_str})</b>\n"]
        for pair_key in sorted(entered):
            s = current_details.get(pair_key)
            if s:
                dir_label = "⬆ LONG" if s["direction"] == "LONG" else "⬇ SHORT"
                lines.append(
                    f"  <b>{s['pair']}</b> — {dir_label}\n"
                    f"  Grado: <b>{s['grade']}</b> | Score: {s['quality_score']:.0f}"
                )
        msg = "\n".join(lines)
        send_telegram(msg)

        # Android notification
        pairs_list = ", ".join(sorted(entered))
        send_android_notification(
            "🟢 Nuovi Setup A/A+",
            f"Nuovi segnali: {pairs_list}"
        )

    # Send notifications for REMOVED signals
    if exited:
        lines = [f"🔴 <b>SETUP RIMOSSI ({now_str})</b>\n"]
        for pair_key in sorted(exited):
            parts = pair_key.rsplit(" ", 1)
            pair_name = parts[0]
            direction = parts[1] if len(parts) > 1 else ""
            dir_label = "⬆ LONG" if direction == "LONG" else "⬇ SHORT"
            lines.append(f"  ✖ <b>{pair_name}</b> — {dir_label}")
        send_telegram("\n".join(lines))

    # Save updated state
    save_current_state(current_top)

    return {
        "entered": entered,
        "exited": exited,
        "current": current_top,
        "alerts_sent": len(entered) + len(exited),
    }
