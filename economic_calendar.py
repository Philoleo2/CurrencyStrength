"""
Currency Strength Indicator – Economic Calendar
=================================================
Recupera il calendario economico settimanale da ForexFactory (via API non ufficiale)
e fornisce funzioni per:
  • Determinare la sessione di trading attiva (Londra, New York, Asia)
  • Identificare eventi macro ad alto impatto imminenti o recenti
  • Sopprimere coppie affette da notizie macro dall'elenco Trade Setup

Il principio: i segnali H1 arrivano alla chiusura della candela.
Se un evento ad alto impatto è avvenuto durante la candela appena chiusa,
il segnale potrebbe essere distorto da volatilità evento → SOPPRIMERE.
Se un evento è in arrivo nella prossima ora → WARNING (ma non sopprimere).
"""

import datetime as dt
import json
import logging
import os
from typing import Optional
from zoneinfo import ZoneInfo

import requests

from config import (
    CURRENCIES,
    CACHE_DIR,
    CALENDAR_CACHE_FILE,
    NEWS_SUPPRESS_HOURS_BACK,
    NEWS_WARN_HOURS_AHEAD,
    NEWS_MIN_IMPACT,
)

logger = logging.getLogger(__name__)

# Timezone di riferimento
UTC = ZoneInfo("UTC")
ET = ZoneInfo("America/New_York")  # ForexFactory usa Eastern Time

# Endpoint ForexFactory (non ufficiale, stabile)
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# Mappa da nomi ForexFactory a codici valuta ISO
_FF_CCY_MAP = {
    "USD": "USD", "EUR": "EUR", "GBP": "GBP", "JPY": "JPY",
    "CHF": "CHF", "AUD": "AUD", "NZD": "NZD", "CAD": "CAD",
    "CNY": None, "CNH": None,  # non monitoriamo
}

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

# Orari sessioni in UTC (approssimati, senza DST per semplicità)
SESSIONS = {
    "🌏 Asia/Tokyo":      (0, 8),    # 00:00 – 08:00 UTC
    "🇪🇺 Londra":         (8, 16),   # 08:00 – 16:00 UTC
    "🇺🇸 New York":       (13, 21),  # 13:00 – 21:00 UTC
}
OVERLAP_LONDON_NY = (13, 16)  # 13:00 – 16:00 UTC


def get_current_sessions() -> dict:
    """
    Restituisce info sulla sessione corrente.

    Returns
    -------
    dict con chiavi:
        active_sessions : list[str]  – nomi sessioni attive
        is_overlap      : bool       – True se siamo in overlap Londra/NY
        session_label   : str        – etichetta compatta per la UI
        utc_now         : datetime   – orario UTC corrente
    """
    now = dt.datetime.now(UTC)
    hour = now.hour

    active = []
    for name, (start, end) in SESSIONS.items():
        if start <= hour < end:
            active.append(name)

    is_overlap = OVERLAP_LONDON_NY[0] <= hour < OVERLAP_LONDON_NY[1]

    if is_overlap:
        label = "🔥 Overlap Londra/NY"
    elif active:
        label = " + ".join(active)
    else:
        label = "🌙 Mercato chiuso / Pre-Asia"

    return {
        "active_sessions": active,
        "is_overlap": is_overlap,
        "session_label": label,
        "utc_now": now,
    }


def is_market_active() -> bool:
    """True se almeno una sessione principale è attiva."""
    sessions = get_current_sessions()
    return len(sessions["active_sessions"]) > 0


def is_forex_market_open() -> dict:
    """
    Verifica se il mercato forex è aperto (non nel weekend).
    Il forex chiude venerdì ~22:00 UTC e riapre domenica ~22:00 UTC.

    Returns
    -------
    dict con chiavi:
        is_open     : bool   – True se il mercato è aperto
        reason      : str    – motivo se chiuso
        next_open   : str    – quando riapre (es. "Domenica 22:00 UTC")
    """
    now = dt.datetime.now(UTC)
    weekday = now.weekday()   # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now.hour

    # Sabato tutto il giorno → chiuso
    if weekday == 5:
        # Calcola ore fino a domenica 22:00
        hours_to_open = (24 - hour) + 22  # ore rimanenti sabato + 22h domenica
        return {
            "is_open": False,
            "reason": "Mercato chiuso — Weekend (Sabato)",
            "next_open": f"Domenica ~22:00 UTC (tra ~{hours_to_open:.0f}h)",
        }

    # Domenica prima delle 22:00 → chiuso
    if weekday == 6 and hour < 22:
        hours_to_open = 22 - hour
        return {
            "is_open": False,
            "reason": "Mercato chiuso — Weekend (Domenica)",
            "next_open": f"Domenica ~22:00 UTC (tra ~{hours_to_open:.0f}h)",
        }

    # Venerdì dopo le 22:00 → chiuso
    if weekday == 4 and hour >= 22:
        hours_to_open = (24 - hour) + 24 + 22  # ven rimanente + sab + dom fino 22
        return {
            "is_open": False,
            "reason": "Mercato chiuso — Weekend (Venerdì sera)",
            "next_open": f"Domenica ~22:00 UTC (tra ~{hours_to_open:.0f}h)",
        }

    return {
        "is_open": True,
        "reason": "",
        "next_open": "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ECONOMIC CALENDAR - FETCH & CACHE
# ═══════════════════════════════════════════════════════════════════════════════

def _cache_path() -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, CALENDAR_CACHE_FILE)


def _is_cache_fresh() -> bool:
    """Cache è 'fresca' se è stata salvata oggi."""
    path = _cache_path()
    if not os.path.exists(path):
        return False
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(path), tz=UTC)
    now = dt.datetime.now(UTC)
    # Refresh ogni 4 ore
    return (now - mtime).total_seconds() < 4 * 3600


def fetch_calendar() -> list[dict]:
    """
    Recupera il calendario economico settimanale.
    Restituisce lista di eventi con chiavi:
        title, country, date, time, impact, forecast, previous, actual
    """
    # Prova cache
    if _is_cache_fresh():
        try:
            with open(_cache_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Fetch da ForexFactory
    events = []
    try:
        resp = requests.get(FF_CALENDAR_URL, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 CurrencyStrength/1.0"
        })
        resp.raise_for_status()
        raw = resp.json()

        for ev in raw:
            ccy = ev.get("country", "").upper()
            if ccy not in _FF_CCY_MAP or _FF_CCY_MAP.get(ccy) is None:
                continue

            impact = ev.get("impact", "").lower()
            title = ev.get("title", "")
            date_str = ev.get("date", "")

            # Parse datetime — ForexFactory restituisce in formato ISO-ish
            event_dt = _parse_ff_datetime(date_str)
            if event_dt is None:
                continue

            events.append({
                "title": title,
                "currency": _FF_CCY_MAP[ccy],
                "datetime": event_dt.isoformat(),
                "impact": impact,  # "high", "medium", "low", "holiday"
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
                "actual": ev.get("actual", ""),
            })

        # Salva cache
        try:
            with open(_cache_path(), "w", encoding="utf-8") as f:
                json.dump(events, f, indent=2, default=str)
            logger.info(f"Calendario economico: {len(events)} eventi salvati in cache")
        except Exception as e:
            logger.warning(f"Errore salvataggio cache calendario: {e}")

    except Exception as e:
        logger.warning(f"Errore fetch calendario economico: {e}")
        # Fallback: prova cache anche se vecchia
        try:
            with open(_cache_path(), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return events


def _parse_ff_datetime(date_str: str) -> Optional[dt.datetime]:
    """Parse datetime string da ForexFactory JSON."""
    if not date_str:
        return None
    try:
        # Formato tipico: "2024-01-15T08:30:00-05:00" (Eastern Time)
        parsed = dt.datetime.fromisoformat(date_str)
        # Converti in UTC
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ET)
        return parsed.astimezone(UTC)
    except Exception:
        try:
            # Prova formato alternativo
            for fmt in [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S",
                "%b %d, %Y %I:%M%p",
            ]:
                try:
                    parsed = dt.datetime.strptime(date_str, fmt)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=ET)
                    return parsed.astimezone(UTC)
                except ValueError:
                    continue
        except Exception:
            pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# NEWS ANALYSIS – Suppress / Warn
# ═══════════════════════════════════════════════════════════════════════════════

def get_news_impact_for_pairs(
    events: list[dict],
    suppress_hours_back: float = NEWS_SUPPRESS_HOURS_BACK,
    warn_hours_ahead: float = NEWS_WARN_HOURS_AHEAD,
    min_impact: str = NEWS_MIN_IMPACT,
) -> dict[str, dict]:
    """
    Analizza gli eventi del calendario e restituisce per ogni valuta
    il suo stato rispetto a notizie macro.

    Parametri
    ---------
    events : lista di eventi del calendario
    suppress_hours_back : ore indietro per soppressione (default 2)
    warn_hours_ahead : ore avanti per warning (default 2)
    min_impact : livello minimo di impatto ("high" o "medium")

    Returns
    -------
    dict[currency] → {
        "status": "SUPPRESS" | "WARNING" | "CLEAR",
        "reason": str,   # descrizione evento
        "event_time": datetime | None,
        "impact": str,
    }
    """
    now = dt.datetime.now(UTC)
    impact_levels = {"high"} if min_impact == "high" else {"high", "medium"}

    ccy_status: dict[str, dict] = {
        ccy: {"status": "CLEAR", "reason": "", "event_time": None, "impact": ""}
        for ccy in CURRENCIES
    }

    for ev in events:
        ccy = ev.get("currency")
        if ccy not in CURRENCIES:
            continue

        impact = ev.get("impact", "").lower()
        if impact not in impact_levels:
            continue

        # Parse event time
        ev_time_str = ev.get("datetime", "")
        try:
            ev_time = dt.datetime.fromisoformat(ev_time_str)
            if ev_time.tzinfo is None:
                ev_time = ev_time.replace(tzinfo=UTC)
            ev_time = ev_time.astimezone(UTC)
        except Exception:
            continue

        delta_hours = (ev_time - now).total_seconds() / 3600

        # Evento nelle ultime N ore → SUPPRESS (volatilità post-evento)
        if -suppress_hours_back <= delta_hours <= 0:
            if ccy_status[ccy]["status"] != "SUPPRESS":
                ccy_status[ccy] = {
                    "status": "SUPPRESS",
                    "reason": f"🔴 {ev['title']} ({impact.upper()}) rilasciato {abs(delta_hours):.0f}h fa",
                    "event_time": ev_time,
                    "impact": impact,
                }

        # Evento nelle prossime N ore → WARNING
        elif 0 < delta_hours <= warn_hours_ahead:
            if ccy_status[ccy]["status"] == "CLEAR":
                ev_local = ev_time.strftime("%H:%M UTC")
                ccy_status[ccy] = {
                    "status": "WARNING",
                    "reason": f"⚠️ {ev['title']} ({impact.upper()}) alle {ev_local}",
                    "event_time": ev_time,
                    "impact": impact,
                }

    return ccy_status


def filter_setups_by_news(
    trade_setups: list[dict],
    news_impact: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """
    Filtra i trade setup in base agli eventi macro.

    - Se una delle 2 valute della coppia è in stato SUPPRESS → rimuovi setup
    - Se una delle 2 valute è in WARNING → aggiungi flag warning allo setup

    Returns
    -------
    (filtered_setups, suppressed_setups)
        filtered_setups: setup validi (con eventuali warning aggiunti)
        suppressed_setups: setup rimossi per macro events
    """
    filtered = []
    suppressed = []

    for setup in trade_setups:
        base = setup["base"]
        quote = setup["quote"]
        base_status = news_impact.get(base, {}).get("status", "CLEAR")
        quote_status = news_impact.get(quote, {}).get("status", "CLEAR")

        # Se una valuta è soppressa → rimuovi
        if base_status == "SUPPRESS" or quote_status == "SUPPRESS":
            reasons_suppress = []
            if base_status == "SUPPRESS":
                reasons_suppress.append(news_impact[base]["reason"])
            if quote_status == "SUPPRESS":
                reasons_suppress.append(news_impact[quote]["reason"])
            setup_copy = dict(setup)
            setup_copy["suppressed_reason"] = " | ".join(reasons_suppress)
            suppressed.append(setup_copy)
            continue

        # Se una valuta ha warning → aggiungi flag ma tieni lo setup
        setup_copy = dict(setup)
        news_warnings = []
        if base_status == "WARNING":
            news_warnings.append(news_impact[base]["reason"])
        if quote_status == "WARNING":
            news_warnings.append(news_impact[quote]["reason"])

        if news_warnings:
            setup_copy["news_warning"] = " | ".join(news_warnings)
            # Aggiungi anche alle reasons esistenti
            setup_copy["reasons"] = list(setup_copy.get("reasons", [])) + news_warnings

        filtered.append(setup_copy)

    return filtered, suppressed


# ═══════════════════════════════════════════════════════════════════════════════
# UPCOMING EVENTS (per display nella UI)
# ═══════════════════════════════════════════════════════════════════════════════

def get_upcoming_events(
    events: list[dict],
    hours_ahead: float = 24,
    min_impact: str = "medium",
) -> list[dict]:
    """
    Restituisce gli eventi nelle prossime N ore, ordinati per data.
    Utile per la visualizzazione nel calendario nella dashboard.
    """
    now = dt.datetime.now(UTC)
    impact_levels = {"high"} if min_impact == "high" else {"high", "medium"}

    upcoming = []
    for ev in events:
        ccy = ev.get("currency")
        if ccy not in CURRENCIES:
            continue

        impact = ev.get("impact", "").lower()
        if impact not in impact_levels:
            continue

        try:
            ev_time = dt.datetime.fromisoformat(ev.get("datetime", ""))
            if ev_time.tzinfo is None:
                ev_time = ev_time.replace(tzinfo=UTC)
            ev_time = ev_time.astimezone(UTC)
        except Exception:
            continue

        delta_hours = (ev_time - now).total_seconds() / 3600
        if 0 < delta_hours <= hours_ahead:
            upcoming.append({
                "title": ev["title"],
                "currency": ccy,
                "time": ev_time.strftime("%H:%M UTC"),
                "time_dt": ev_time,
                "impact": impact,
                "hours_away": round(delta_hours, 1),
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
            })

    upcoming.sort(key=lambda x: x.get("time_dt", now))
    return upcoming


def get_recent_events(
    events: list[dict],
    hours_back: float = 4,
    min_impact: str = "medium",
) -> list[dict]:
    """Restituisce gli eventi delle ultime N ore."""
    now = dt.datetime.now(UTC)
    impact_levels = {"high"} if min_impact == "high" else {"high", "medium"}

    recent = []
    for ev in events:
        ccy = ev.get("currency")
        if ccy not in CURRENCIES:
            continue

        impact = ev.get("impact", "").lower()
        if impact not in impact_levels:
            continue

        try:
            ev_time = dt.datetime.fromisoformat(ev.get("datetime", ""))
            if ev_time.tzinfo is None:
                ev_time = ev_time.replace(tzinfo=UTC)
            ev_time = ev_time.astimezone(UTC)
        except Exception:
            continue

        delta_hours = (now - ev_time).total_seconds() / 3600
        if 0 <= delta_hours <= hours_back:
            recent.append({
                "title": ev["title"],
                "currency": ccy,
                "time": ev_time.strftime("%H:%M UTC"),
                "time_dt": ev_time,
                "impact": impact,
                "hours_ago": round(delta_hours, 1),
                "actual": ev.get("actual", ""),
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
            })

    recent.sort(key=lambda x: x.get("hours_ago", 0))
    return recent
