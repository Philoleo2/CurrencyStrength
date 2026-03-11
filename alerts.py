"""
Currency Strength Indicator – Alert System (Telegram)
=====================================================
Invia notifiche push sul telefono via Telegram Bot quando:
  • Una coppia entra nella classifica A/A+ dei Trade Setup.
  • Una coppia esce dalla classifica A/A+ dei Trade Setup.

Include: sessione attiva, warning notizie macro, storico segnali.

Configurazione richiesta in config.py:
  TELEGRAM_BOT_TOKEN  – token del bot (ottenuto da @BotFather)
  TELEGRAM_CHAT_ID    – chat_id del destinatario (il tuo ID personale,
                        ottenibile mandando /start a @userinfobot)

Per abilitare/disabilitare: ALERTS_ENABLED = True / False in config.py
"""

import datetime as dt
from zoneinfo import ZoneInfo

_ROME = ZoneInfo("Europe/Rome")

import json
import os
import requests
import logging

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    ALERTS_ENABLED,
    ALERT_GRADES,
    ALERT_STATE_FILE,
    SIGNAL_HISTORY_FILE,
    SIGNAL_HISTORY_MAX_DAYS,
    GRADE_HYSTERESIS_POINTS,
    SIGNAL_GRACE_REFRESHES,
    SIGNAL_MIN_RESIDENCE_HOURS,
    SIGNAL_CONFIRMATION_REFRESHES,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# STATO PRECEDENTE (persiste tra refresh)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_previous_state() -> set[str]:
    """Carica l'elenco di coppie A/A+ dal file di stato."""
    if os.path.exists(ALERT_STATE_FILE):
        try:
            with open(ALERT_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("pairs", []))
        except Exception:
            pass
    return set()


def _load_full_state() -> dict:
    """
    Carica lo stato completo (con timestamp ingresso, contatore grace, score,
    e segnali in attesa di conferma).

    Formato:
      {
        "pairs": ["NZD/CHF LONG", ...],           # retrocompatibile
        "pair_details": {
            "NZD/CHF LONG": {
                "entered_at": "2026-03-04T10:00:00",
                "last_seen_at": "2026-03-04T12:00:00",
                "grace_counter": 0,     # quante volte consecutive sotto soglia
                "last_score": 65.0,     # ultimo quality_score
            }, ...
        },
        "pending_pairs": {
            "AUD/JPY LONG": {
                "first_seen_at": "2026-03-04T14:00:00",
                "consecutive_count": 1,  # quante volte consecutive è stato A/A+
                "last_score": 62.0,
            }, ...
        },
        "updated": "..."
      }
    """
    if os.path.exists(ALERT_STATE_FILE):
        try:
            with open(ALERT_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Retrocompatibilità: se manca pair_details, crea da pairs
                if "pair_details" not in data:
                    now_iso = dt.datetime.now(_ROME).isoformat()
                    data["pair_details"] = {
                        p: {
                            "entered_at": now_iso,
                            "last_seen_at": now_iso,
                            "grace_counter": 0,
                            "last_score": 0,
                        }
                        for p in data.get("pairs", [])
                    }
                if "pending_pairs" not in data:
                    data["pending_pairs"] = {}
                return data
        except Exception:
            pass
    return {"pairs": [], "pair_details": {}, "pending_pairs": {}, "updated": ""}


def _save_full_state(pairs: set[str], pair_details: dict[str, dict],
                     pending_pairs: dict[str, dict] | None = None,
                     active_setups: list[dict] | None = None,
                     all_setups: list[dict] | None = None,
                     suppressed_setups: list[dict] | None = None) -> None:
    """Salva lo stato completo (con timestamp, contatori grace, pending e setup).

    I campi active_setups / all_setups / suppressed_setups vengono usati
    dalla dashboard per mostrare ESATTAMENTE gli stessi dati del Telegram,
    eliminando qualsiasi divergenza tra le due viste.
    """
    try:
        os.makedirs(os.path.dirname(ALERT_STATE_FILE) or ".", exist_ok=True)
        with open(ALERT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "pairs": sorted(pairs),
                "pair_details": pair_details,
                "pending_pairs": pending_pairs or {},
                "active_setups": active_setups or [],
                "all_setups": all_setups or [],
                "suppressed_setups": suppressed_setups or [],
                "updated": dt.datetime.now(_ROME).isoformat(),
            }, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"Impossibile salvare stato alert: {e}")


def _save_current_state(pairs: set[str]) -> None:
    """Salva l'elenco corrente di coppie A/A+ nel file di stato (retrocompat)."""
    # Carica stato full per preservare pair_details
    full = _load_full_state()
    existing_details = full.get("pair_details", {})
    # Aggiorna solo la lista pairs
    _save_full_state(pairs, existing_details)


# ═══════════════════════════════════════════════════════════════════════════════
# TELEGRAM  –  invio messaggi
# ═══════════════════════════════════════════════════════════════════════════════

def _send_telegram(text: str) -> bool:
    """Invia un messaggio Telegram. Restituisce True se riuscito."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram non configurato (token o chat_id mancante)")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Alert Telegram inviato con successo")
            return True
        else:
            logger.warning(f"Telegram API errore {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.warning(f"Errore invio Telegram: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# LOGICA ALERT PRINCIPALE
# ═══════════════════════════════════════════════════════════════════════════════

def check_and_send_alerts(
    trade_setups: list[dict],
    session_info: dict | None = None,
    suppressed_setups: list[dict] | None = None,
) -> dict:
    """
    Confronta i setup A/A+ correnti con quelli dell'ultimo check.
    Invia alert Telegram per:
      • NUOVE coppie entrate in classifica
      • COPPIE USCITE dalla classifica

    Parametri
    ---------
    trade_setups : lista di setup (output di compute_trade_setups)
    session_info : dict da get_current_sessions() — sessione attiva
    suppressed_setups : setup soppressi per notizie macro

    Restituisce
    -----------
    dict con chiavi: entered, exited, current, alerts_sent, enabled
    """
    if suppressed_setups is None:
        suppressed_setups = []

    now = dt.datetime.now(_ROME)
    now_iso = now.isoformat()

    # ── Carica stato completo (con timestamp e grace counters) ──────────
    full_state = _load_full_state()
    previous_top = set(full_state.get("pairs", []))
    pair_details = full_state.get("pair_details", {})

    # ── Costruisci la mappa dei setup correnti A/A+ ─────────────────────
    current_details = {
        f"{s['pair']} {s['direction']}": s
        for s in trade_setups
        if s["grade"] in ALERT_GRADES
    }
    raw_current_top = set(current_details.keys())

    # ── Mappa dei setup con score (per isteresi) ───────────────────────
    all_setup_scores = {
        f"{s['pair']} {s['direction']}": s.get("quality_score", 0)
        for s in trade_setups
    }

    # Include score dei setup soppressi per macro news: la soppressione
    # non deve causare uscite false — le stabilizzazioni (isteresi, grace,
    # residenza) devono continuare a proteggerli.
    _suppressed_lookup = {}
    for s in suppressed_setups:
        pk = f"{s['pair']} {s['direction']}"
        all_setup_scores.setdefault(pk, s.get("quality_score", 0))
        _suppressed_lookup[pk] = s

    # ═══════════════════════════════════════════════════════════════════════
    # STABILIZZAZIONE: isteresi + grace period + residenza minima
    # ═══════════════════════════════════════════════════════════════════════

    # Soglie di grado con isteresi
    # Per entrare: score ≥ 60 (A) — come attuale
    # Per uscire: score deve scendere sotto (60 - GRADE_HYSTERESIS_POINTS) = 55
    grade_entry_thresholds = {"A+": 75, "A": 60}
    grade_exit_threshold = min(grade_entry_thresholds.values()) - GRADE_HYSTERESIS_POINTS

    # 1. ISTERESI: segnali precedenti che sono ancora sopra la soglia di uscita
    #    vengono mantenuti anche se il grado nominale è sceso a B
    #    NOTA: score == 0 → segnale completamente sparito → esce subito
    hysteresis_kept = set()
    for pair_key in previous_top:
        if pair_key in raw_current_top:
            continue  # ancora A/A+, nessun problema
        # Era A/A+, ora non lo è più — controlla isteresi
        score = all_setup_scores.get(pair_key, 0)
        if score > 0 and score >= grade_exit_threshold:
            hysteresis_kept.add(pair_key)
            # Aggiorna dettagli per il messaggio (prendi dal setup completo)
            if pair_key in _suppressed_lookup:
                current_details[pair_key] = _suppressed_lookup[pair_key]
            else:
                for s in trade_setups:
                    if f"{s['pair']} {s['direction']}" == pair_key:
                        current_details[pair_key] = s
                        break

    # 2. RESIDENZA MINIMA: segnali entrati da meno di N ore restano
    #    NOTA: score == 0 → segnale completamente sparito → esce subito
    residence_kept = set()
    for pair_key in previous_top:
        if pair_key in raw_current_top or pair_key in hysteresis_kept:
            continue
        score = all_setup_scores.get(pair_key, 0)
        if score == 0:
            continue  # sparito del tutto, nessuna stabilizzazione
        detail = pair_details.get(pair_key, {})
        entered_at_str = detail.get("entered_at", "")
        if entered_at_str:
            try:
                entered_at = dt.datetime.fromisoformat(entered_at_str)
                hours_in = (now - entered_at).total_seconds() / 3600
                if hours_in < SIGNAL_MIN_RESIDENCE_HOURS:
                    residence_kept.add(pair_key)
                    # Aggiorna dettagli
                    if pair_key in _suppressed_lookup:
                        current_details[pair_key] = _suppressed_lookup[pair_key]
                    else:
                        for s in trade_setups:
                            if f"{s['pair']} {s['direction']}" == pair_key:
                                current_details[pair_key] = s
                                break
            except (ValueError, TypeError):
                pass

    # 3. GRACE PERIOD: se il segnale è sceso ma il grace counter non è ancora esaurito
    #    NOTA: score == 0 → segnale completamente sparito → esce subito
    grace_kept = set()
    for pair_key in previous_top:
        if pair_key in raw_current_top or pair_key in hysteresis_kept or pair_key in residence_kept:
            continue
        score = all_setup_scores.get(pair_key, 0)
        if score == 0:
            continue  # sparito del tutto, nessuna stabilizzazione
        detail = pair_details.get(pair_key, {})
        grace_counter = detail.get("grace_counter", 0)
        if grace_counter < SIGNAL_GRACE_REFRESHES:
            grace_kept.add(pair_key)
            # Aggiorna dettagli
            if pair_key in _suppressed_lookup:
                current_details[pair_key] = _suppressed_lookup[pair_key]
            else:
                for s in trade_setups:
                    if f"{s['pair']} {s['direction']}" == pair_key:
                        current_details[pair_key] = s
                        break

    # ── Set finale stabilizzato ─────────────────────────────────────────
    # CONFERMA INGRESSO: segnali nuovi (non in previous_top) devono essere
    # A/A+ per SIGNAL_CONFIRMATION_REFRESHES refresh consecutivi prima
    # dell'ingresso ufficiale.  Questo filtra spike da 1 ora.
    previous_pending = full_state.get("pending_pairs", {})
    new_pending = {}
    confirmed_from_pending = set()

    for pair_key in raw_current_top:
        if pair_key in previous_top:
            continue  # già confermato in classifica, OK
        # È un segnale NUOVO — deve passare dalla pending
        pend = previous_pending.get(pair_key, {})
        count = pend.get("consecutive_count", 0) + 1  # +1 per questa ora
        current_score = all_setup_scores.get(pair_key, 0)
        # Accumula somma score per calcolo media
        score_sum = pend.get("score_sum", 0) + current_score
        avg_score = score_sum / count if count > 0 else 0
        if count >= SIGNAL_CONFIRMATION_REFRESHES and avg_score >= grade_entry_thresholds["A"]:
            # Confermato: N refresh consecutivi con media ≥ 60
            confirmed_from_pending.add(pair_key)
        elif count >= SIGNAL_CONFIRMATION_REFRESHES:
            # Ha i refresh ma media troppo bassa → resta in pending
            new_pending[pair_key] = {
                "first_seen_at": pend.get("first_seen_at", now_iso),
                "consecutive_count": count,
                "score_sum": score_sum,
                "last_score": current_score,
            }
        else:
            # Non ancora confermato → resta in pending
            new_pending[pair_key] = {
                "first_seen_at": pend.get("first_seen_at", now_iso),
                "consecutive_count": count,
                "score_sum": score_sum,
                "last_score": current_score,
            }
    # Segnali pending che NON sono più A/A+ vengono rimossi silenziosamente
    # (se consecutive_count non raggiunta, scompaiono)

    # raw_current_top per il set finale = solo quelli già in previous_top
    # + quelli appena confermati dalla pending
    effective_current_top = (raw_current_top & previous_top) | confirmed_from_pending

    current_top = effective_current_top | hysteresis_kept | residence_kept | grace_kept

    entered = current_top - previous_top   # nuove coppie (vere entrate)
    exited  = previous_top - current_top   # coppie veramente uscite (dopo grace)

    # ── Aggiorna pair_details ───────────────────────────────────────────
    new_pair_details = {}
    for pair_key in current_top:
        if pair_key in pair_details:
            # Aggiorna esistente
            d = pair_details[pair_key].copy()
            d["last_seen_at"] = now_iso
            d["last_score"] = all_setup_scores.get(pair_key, d.get("last_score", 0))
            if pair_key in raw_current_top:
                # Ancora A/A+ nominale → resetta grace counter
                d["grace_counter"] = 0
            elif pair_key in grace_kept:
                # Protetto SOLO dal grace period → incrementa counter
                d["grace_counter"] = d.get("grace_counter", 0) + 1
            else:
                # Protetto da isteresi o residenza → grace counter
                # resta a 0 così avrà il suo turno pieno quando servirà
                d["grace_counter"] = 0
            new_pair_details[pair_key] = d
        else:
            # Nuovo ingresso
            new_pair_details[pair_key] = {
                "entered_at": now_iso,
                "last_seen_at": now_iso,
                "grace_counter": 0,
                "last_score": all_setup_scores.get(pair_key, 0),
            }

    alerts_sent = 0
    result = {
        "entered": entered,
        "exited": exited,
        "current": current_top,
        "alerts_sent": 0,
        "enabled": ALERTS_ENABLED,
        # Extra info per debug/dashboard
        "hysteresis_kept": hysteresis_kept,
        "residence_kept": residence_kept,
        "grace_kept": grace_kept,
        "pending_pairs": new_pending,
        "confirmed_from_pending": confirmed_from_pending,
    }

    # ── Prepara active_setups per la dashboard ────────────────────────
    active_setups_list = []
    for pk in sorted(current_top):
        if pk in current_details:
            active_setups_list.append(current_details[pk])
        else:
            # Mantenuto da stabilizzazione ma non più in trade_setups
            detail = new_pair_details.get(pk, {})
            parts = pk.rsplit(" ", 1)
            pair_name = parts[0] if parts else pk
            direction = parts[1] if len(parts) > 1 else ""
            active_setups_list.append({
                "pair": pair_name,
                "actual_pair": pair_name,
                "direction": direction,
                "quality_score": detail.get("last_score", 0),
                "grade": "A",   # era A/A+ al momento dell'ingresso
                "differential": 0,
                "strong_score": 0,
                "weak_score": 0,
                "reasons": ["Mantenuto per stabilizzazione"],
            })

    if not ALERTS_ENABLED:
        _save_full_state(current_top, new_pair_details, new_pending,
                         active_setups=active_setups_list,
                         all_setups=trade_setups,
                         suppressed_setups=suppressed_setups or [])
        return result

    now_str = now.strftime("%H:%M %d/%m")

    # Header con sessione attiva
    session_label = ""
    if session_info:
        session_label = f"\n📍 Sessione: {session_info.get('session_label', 'N/A')}"

    # ── REPORT ORARIO COMPLETO ──────────────────────────────────────────
    # Invia SEMPRE il riepilogo: tutte le coppie A/A+ attive + uscite
    confirmed = current_top - entered   # coppie che restano (erano già presenti)

    lines = [f"📊 <b>REPORT VALUTE ({now_str})</b>{session_label}\n"]

    # Solo coppie genuinamente A/A+ (escludi grace, isteresi, residenza)
    genuine_aa = {pk for pk in current_top
                  if pk not in grace_kept
                  and pk not in hysteresis_kept
                  and pk not in residence_kept}

    if genuine_aa:
        lines.append(f"🟢 <b>SETUP ATTIVI A/A+ ({len(genuine_aa)}):</b>\n")
        for pair_key in sorted(genuine_aa):
            s = current_details.get(pair_key)
            if s:
                is_new = pair_key in entered
                tag = "🆕" if is_new else "►"
                dir_label = "⬆ LONG" if s["direction"] == "LONG" else "⬇ SHORT"
                lines.append(
                    f"  {tag} <b>{s['pair']}</b> — {dir_label}\n"
                    f"     Grado: <b>{s['grade']}</b> | Score: {s['quality_score']:.0f} "
                    f"| Δ Forza: {s['differential']:+.0f}"
                )
                if is_new and s.get("reasons"):
                    reasons_clean = [r for r in s["reasons"][:3] if not r.startswith("⚠️ ") or "Volatilità" in r]
                    if reasons_clean:
                        lines.append(f"     💡 {' | '.join(reasons_clean)}")
                news_warn = s.get("news_warning")
                if news_warn:
                    lines.append(f"     📰 {news_warn}")
                lines.append("")
            else:
                lines.append(f"  • {pair_key}\n")
    else:
        lines.append("Nessun setup A/A+ attivo.\n")

    # Sezione uscite
    if exited:
        lines.append(f"🔴 <b>USCITI ({len(exited)}):</b>")
        for pair_key in sorted(exited):
            parts = pair_key.rsplit(" ", 1)
            pair_name = parts[0]
            direction = parts[1] if len(parts) > 1 else ""
            dir_label = "⬆ LONG" if direction == "LONG" else "⬇ SHORT" if direction == "SHORT" else direction
            lines.append(f"  ✖ <b>{pair_name}</b> — {dir_label}")
    else:
        lines.append("✅ Nessuna uscita rispetto all'ora precedente.")

    msg = "\n".join(lines)
    if _send_telegram(msg):
        alerts_sent += 1

    # Salva stato aggiornato (completo con pair_details, pending e setup)
    _save_full_state(current_top, new_pair_details, new_pending,
                     active_setups=active_setups_list,
                     all_setups=trade_setups,
                     suppressed_setups=suppressed_setups or [])
    result["alerts_sent"] = alerts_sent

    # ── Registra nello storico segnali ──────────────────────────────────
    _log_signals(entered, exited, current_details, session_info)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# STORICO SEGNALI  –  log permanente di tutti gli alert
# ═══════════════════════════════════════════════════════════════════════════════

def _history_path() -> str:
    os.makedirs(os.path.dirname(SIGNAL_HISTORY_FILE) or ".", exist_ok=True)
    return SIGNAL_HISTORY_FILE


def _load_history() -> list[dict]:
    """Carica lo storico segnali dal disco."""
    path = _history_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_history(history: list[dict]) -> None:
    """Salva lo storico segnali su disco."""
    try:
        with open(_history_path(), "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"Errore salvataggio storico segnali: {e}")


def _log_signals(
    entered: set[str],
    exited: set[str],
    current_details: dict[str, dict],
    session_info: dict | None,
) -> None:
    """
    Aggiunge al log permanente i segnali entrati/usciti.
    Ogni entry contiene: timestamp, tipo (ENTRATA/USCITA), coppia, direzione,
    grado, score, differenziale, motivi, sessione.
    """
    if not entered and not exited:
        return

    history = _load_history()
    now = dt.datetime.now(_ROME)
    now_iso = now.isoformat()
    session_label = (session_info or {}).get("session_label", "N/A")

    for pair_key in entered:
        s = current_details.get(pair_key, {})
        parts = pair_key.rsplit(" ", 1)
        history.append({
            "timestamp": now_iso,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "type": "ENTRATA",
            "pair": parts[0] if parts else pair_key,
            "direction": parts[1] if len(parts) > 1 else "",
            "grade": s.get("grade", ""),
            "score": s.get("quality_score", 0),
            "differential": s.get("differential", 0),
            "reasons": s.get("reasons", [])[:3],
            "session": session_label,
        })

    for pair_key in exited:
        parts = pair_key.rsplit(" ", 1)
        history.append({
            "timestamp": now_iso,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "type": "USCITA",
            "pair": parts[0] if parts else pair_key,
            "direction": parts[1] if len(parts) > 1 else "",
            "grade": "",
            "score": 0,
            "differential": 0,
            "reasons": [],
            "session": session_label,
        })

    # Purge vecchi (oltre SIGNAL_HISTORY_MAX_DAYS)
    cutoff = (now - dt.timedelta(days=SIGNAL_HISTORY_MAX_DAYS)).isoformat()
    history = [h for h in history if h.get("timestamp", "") >= cutoff]

    _save_history(history)


def load_signal_history() -> list[dict]:
    """
    Carica lo storico segnali. Funzione pubblica per la dashboard.

    Returns
    -------
    lista di dict ordinata dal più recente al più vecchio.
    """
    history = _load_history()
    history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return history


def send_test_alert() -> bool:
    """Invia un messaggio di test per verificare la configurazione Telegram."""
    return _send_telegram(
        "✅ <b>Currency Strength Alert — Test</b>\n\n"
        "La connessione Telegram funziona correttamente.\n"
        f"Data: {dt.datetime.now(_ROME).strftime('%Y-%m-%d %H:%M:%S')}"
    )
