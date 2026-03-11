"""
Currency Strength — Background Hourly Scheduler
================================================
Processo in background che ogni ora (allineato a xx:00:10 UTC):
  1. Scarica dati di prezzo, volume, COT per valute e asset.
  2. Esegue l'analisi completa (composito, momentum, etc.).
  3. Calcola i trade setup e invia alert Telegram (entrata/uscita).

Gira indipendentemente dal browser: anche se nessuno ha la dashboard
aperta, gli alert vengono comunque inviati.

Avvio:
    python scheduler.py          (blocca il terminale, log su console)
    pythonw scheduler.py         (silenzioso, senza finestra di console)
    Start-Process pythonw scheduler.py   (da PowerShell)
"""

import datetime as dt
import time
import logging
import sys
import os
import json
from zoneinfo import ZoneInfo

_ROME = ZoneInfo("Europe/Rome")

# ── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("cache/scheduler.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("scheduler")

# ── Import pipeline ─────────────────────────────────────────────────
from config import (
    CURRENCIES, DEFAULT_TIMEFRAME,
    COMPOSITE_WEIGHT_H1, COMPOSITE_WEIGHT_H4,
    ALERTS_ENABLED, ALERT_GRADES,
    ASSETS, ASSET_LABELS, ASSET_DEFAULT_TIMEFRAME,
    ASSET_COMPOSITE_WEIGHT_H4, ASSET_COMPOSITE_WEIGHT_DAILY, ASSET_COMPOSITE_WEIGHT_WEEKLY,
    ASSET_ALERT_STATE_FILE,
    GRADE_HYSTERESIS_POINTS, SIGNAL_GRACE_REFRESHES,
    SIGNAL_MIN_RESIDENCE_HOURS, SIGNAL_CONFIRMATION_REFRESHES,
)
from data_fetcher import fetch_all_pairs, fetch_all_futures
from cot_data import load_cot_data, compute_cot_scores
from strength_engine import (
    full_analysis, blend_multi_timeframe,
    compute_atr_context, compute_trade_setups,
    compute_velocity_scores, smooth_composite_scores,
)
from asset_data_fetcher import fetch_all_assets
from asset_cot_data import load_asset_cot_data, compute_asset_cot_scores
from asset_strength_engine import (
    full_asset_analysis, blend_asset_multi_timeframe,
    compute_asset_trade_setups, smooth_asset_composite_scores,
)
from alerts import check_and_send_alerts, _send_telegram
from economic_calendar import (
    get_current_sessions, fetch_calendar, get_news_impact_for_pairs,
    filter_setups_by_news, is_forex_market_open,
)


# ── Stato smoothing persistente tra esecuzioni del scheduler ─────────
_scheduler_prev_composite: dict[str, dict] | None = None
_asset_prev_composite: dict[str, dict] | None = None


# ═══════════════════════════════════════════════════════════════════════════════
#  PIPELINE VALUTE
# ═══════════════════════════════════════════════════════════════════════════════

def run_currency_pipeline() -> dict:
    """Scarica dati, analizza e invia alert per le coppie forex."""
    global _scheduler_prev_composite
    log.info("── Avvio pipeline VALUTE ──")

    tf = DEFAULT_TIMEFRAME  # tipicamente "Composito"

    # 1. Dati prezzo
    try:
        if tf == "Composito":
            all_pairs_h1 = fetch_all_pairs("H1")
            all_pairs_h4 = fetch_all_pairs("H4")
            all_pairs_d1 = fetch_all_pairs("D1")
            all_pairs = all_pairs_h4
            futures_h1 = fetch_all_futures("H1")
            futures_h4 = fetch_all_futures("H4")
            futures_d1 = fetch_all_futures("D1")
            futures = futures_h4
        else:
            all_pairs = fetch_all_pairs(tf)
            all_pairs_h1 = all_pairs_h4 = all_pairs_d1 = None
            futures = fetch_all_futures(tf)
            futures_h1 = futures_h4 = futures_d1 = None
    except Exception as e:
        log.exception(f"Errore critico nel download dati prezzo: {e}")
        _send_telegram(f"\U0001f6a8 <b>ERRORE PIPELINE VALUTE</b>\nDownload dati prezzo fallito:\n<pre>{e}</pre>")
        return {"alerts_sent": 0}

    if not all_pairs:
        log.warning("Nessun dato di prezzo disponibile, skip.")
        return {"alerts_sent": 0}

    # 2. COT (non critico: se fallisce si prosegue con score neutri)
    try:
        cot_raw = load_cot_data()
        cot_scores = compute_cot_scores(cot_raw)
    except Exception as e:
        log.warning(f"COT non disponibile, proseguo con score neutri: {e}")
        cot_scores = {
            c: {"score": 50, "bias": "NEUTRAL", "extreme": None,
                "net_spec_percentile": 50, "weekly_change": 0, "freshness_days": 999}
            for c in CURRENCIES
        }

    # 3. Analisi
    try:
        if tf == "Composito":
            analysis_h1 = full_analysis(all_pairs_h1, futures_h1, cot_scores)
            analysis_h4 = full_analysis(all_pairs_h4, futures_h4, cot_scores)
            analysis_d1 = full_analysis(all_pairs_d1, futures_d1, cot_scores)
            analysis = blend_multi_timeframe(analysis_h1, analysis_h4, analysis_d1)
        else:
            analysis = full_analysis(all_pairs, futures, cot_scores)
    except Exception as e:
        log.exception(f"Errore nell'analisi composita: {e}")
        _send_telegram(f"\U0001f6a8 <b>ERRORE PIPELINE VALUTE</b>\nAnalisi fallita:\n<pre>{e}</pre>")
        return {"alerts_sent": 0}

    composite  = analysis["composite"]
    # ── Smoothing composito (anti-flickering) ────────────────────────────
    composite = smooth_composite_scores(composite, _scheduler_prev_composite)
    _scheduler_prev_composite = composite
    analysis["composite"] = composite
    # Salva prev_composite su disco per condividerlo con la dashboard
    try:
        import json as _json
        _pc_path = os.path.join("cache", "prev_composite.json")
        os.makedirs("cache", exist_ok=True)
        with open(_pc_path, "w") as _pcf:
            _json.dump(composite, _pcf, default=str)
    except Exception:
        pass
    momentum   = analysis["momentum"]
    classification = analysis["classification"]
    atr_context = analysis.get("atr_context", {})
    velocity   = analysis.get("velocity", {})
    trend_structure = analysis.get("trend_structure", {})
    strength_persistence = analysis.get("strength_persistence", {})
    candle9    = analysis.get("candle9", {})

    # 4. Session info (serve anche per il punteggio)
    try:
        session_info = get_current_sessions()
    except Exception as e:
        log.warning(f"Session info non disponibile: {e}")
        session_info = None

    # 5. Trade setups
    try:
        trade_setups = compute_trade_setups(
            composite, momentum, classification, atr_context, cot_scores,
            velocity_scores=velocity,
            trend_structure=trend_structure,
            strength_persistence=strength_persistence,
            session_info=session_info,
            candle9=candle9,
        )
    except Exception as e:
        log.exception(f"Errore nel calcolo trade setups: {e}")
        _send_telegram(f"\U0001f6a8 <b>ERRORE PIPELINE VALUTE</b>\nCalcolo trade setup fallito:\n<pre>{e}</pre>")
        return {"alerts_sent": 0}

    # 6. Filtro notizie macro
    suppressed_setups = []
    try:
        calendar_events = fetch_calendar()
        news_impact = get_news_impact_for_pairs(calendar_events) if calendar_events else {}
        if trade_setups and news_impact:
            trade_setups, suppressed_setups = filter_setups_by_news(trade_setups, news_impact)
    except Exception as e:
        log.warning(f"Calendario economico non disponibile: {e}")

    # 6b. (Nota: i setup vengono ora salvati in alert_state.json
    #      direttamente da check_and_send_alerts — nessun file intermedio)

    # 7. Alert Telegram
    alert_result = {"alerts_sent": 0}
    if trade_setups:
        try:
            alert_result = check_and_send_alerts(
                trade_setups,
                session_info=session_info,
                suppressed_setups=suppressed_setups,
            )
            log.info(
                f"  Valute — setup A/A+: {len(alert_result['current'])} | "
                f"entrati: {len(alert_result['entered'])} | "
                f"usciti: {len(alert_result['exited'])} | "
                f"alert inviati: {alert_result['alerts_sent']}"
            )
        except Exception as e:
            log.exception(f"Errore nell'invio alert Telegram valute: {e}")
    else:
        log.info("  Valute — nessun trade setup attivo.")

    return alert_result


# ═══════════════════════════════════════════════════════════════════════════════
#  PIPELINE ASSET
# ═══════════════════════════════════════════════════════════════════════════════

def run_asset_pipeline() -> dict:
    """Scarica dati, analizza e invia alert per gli asset (con stabilizzazione)."""
    global _asset_prev_composite
    log.info("── Avvio pipeline ASSET ──")

    tf = ASSET_DEFAULT_TIMEFRAME  # tipicamente "Composito"

    # 1. Dati prezzo
    try:
        if tf == "Composito":
            all_assets_h4 = fetch_all_assets("H4")
            all_assets_daily = fetch_all_assets("Daily")
            all_assets_weekly = fetch_all_assets("Weekly")
            all_assets = all_assets_daily
        else:
            all_assets = fetch_all_assets(tf)
            all_assets_h4 = all_assets_daily = all_assets_weekly = None
    except Exception as e:
        log.exception(f"Errore critico nel download dati asset: {e}")
        _send_telegram(f"\U0001f6a8 <b>ERRORE PIPELINE ASSET</b>\nDownload dati fallito:\n<pre>{e}</pre>")
        return {"alerts_sent": 0}

    if not all_assets:
        log.warning("Nessun dato asset disponibile, skip.")
        return {"alerts_sent": 0}

    # 2. COT (non critico: se fallisce si prosegue con score neutri)
    try:
        cot_raw = load_asset_cot_data()
        cot_scores = compute_asset_cot_scores(cot_raw)
    except Exception as e:
        log.warning(f"COT asset non disponibile, proseguo con score neutri: {e}")
        cot_scores = {
            a: {"score": 50, "bias": "NEUTRAL", "extreme": None,
                "net_spec_percentile": 50, "weekly_change": 0, "freshness_days": 999}
            for a in ASSETS
        }

    # 3. Analisi
    try:
        if tf == "Composito":
            analysis_h4 = full_asset_analysis(all_assets_h4, cot_scores)
            analysis_daily = full_asset_analysis(all_assets_daily, cot_scores)
            analysis_weekly = full_asset_analysis(all_assets_weekly, cot_scores)
            analysis = blend_asset_multi_timeframe(analysis_h4, analysis_daily, analysis_weekly)
        else:
            analysis = full_asset_analysis(all_assets, cot_scores)
    except Exception as e:
        log.exception(f"Errore nell'analisi asset: {e}")
        _send_telegram(f"\U0001f6a8 <b>ERRORE PIPELINE ASSET</b>\nAnalisi fallita:\n<pre>{e}</pre>")
        return {"alerts_sent": 0}

    composite  = analysis["composite"]

    # ── Smoothing composito (anti-flickering) ────────────────────────────
    composite = smooth_asset_composite_scores(composite, _asset_prev_composite)
    _asset_prev_composite = composite
    analysis["composite"] = composite
    # Salva su disco per condividere con la dashboard
    try:
        _apc_path = os.path.join("cache", "asset_prev_composite.json")
        os.makedirs("cache", exist_ok=True)
        with open(_apc_path, "w") as _apcf:
            json.dump(composite, _apcf, default=str)
    except Exception:
        pass

    momentum   = analysis["momentum"]
    classification = analysis["classification"]
    atr_context = analysis.get("atr_context", {})
    velocity   = analysis.get("velocity", {})
    trend_structure = analysis.get("trend_structure", {})
    strength_persistence = analysis.get("strength_persistence", {})
    asset_candle9 = analysis.get("candle9", {})

    # 4. Trade setups
    try:
        trade_setups = compute_asset_trade_setups(
            composite, momentum, classification, atr_context, cot_scores, velocity,
            trend_structure=trend_structure,
            strength_persistence=strength_persistence,
            candle9=asset_candle9,
        )
    except Exception as e:
        log.exception(f"Errore nel calcolo trade setups asset: {e}")
        _send_telegram(f"\U0001f6a8 <b>ERRORE PIPELINE ASSET</b>\nCalcolo setup fallito:\n<pre>{e}</pre>")
        return {"alerts_sent": 0}

    # 4b. (Nota: i setup vengono ora salvati in asset_alert_state.json
    #      insieme allo stato di stabilizzazione — nessun file intermedio)

    # 5. Alert con stabilizzazione a 5 livelli (identica alla pipeline valute)
    now_dt = dt.datetime.now(_ROME)
    now_iso = now_dt.isoformat()

    current_top = {
        f"{s['asset']} {s['direction']}" for s in trade_setups if s["grade"] in ALERT_GRADES
    }
    current_details = {
        f"{s['asset']} {s['direction']}": s for s in trade_setups if s["grade"] in ALERT_GRADES
    }

    # Carica stato completo precedente
    prev_pairs = set()
    pair_details = {}
    pending_pairs = {}
    if os.path.exists(ASSET_ALERT_STATE_FILE):
        try:
            with open(ASSET_ALERT_STATE_FILE, "r", encoding="utf-8") as f:
                _st = json.load(f)
                prev_pairs = set(_st.get("pairs", []))
                pair_details = _st.get("pair_details", {})
                pending_pairs = _st.get("pending_pairs", {})
        except Exception:
            pass

    grade_exit_threshold = 60 - GRADE_HYSTERESIS_POINTS  # 55

    # ── Layer 1-3: Hysteresis + Residence + Grace per uscite ──────────
    retained = set()
    exited = set()
    for pk in prev_pairs:
        if pk in current_top:
            # Ancora A/A+: aggiorna dettagli
            detail = pair_details.get(pk, {})
            detail["last_seen_at"] = now_iso
            detail["grace_counter"] = 0
            detail["last_score"] = current_details[pk]["quality_score"]
            pair_details[pk] = detail
            retained.add(pk)
        else:
            detail = pair_details.get(pk, {})
            # Trova lo score attuale (potrebbe essere B/C/D)
            pk_setup = next((s for s in trade_setups
                             if f"{s['asset']} {s['direction']}" == pk), None)
            pk_score = pk_setup["quality_score"] if pk_setup else 0

            # Score 0 = segnale completamente sparito → esce subito
            if pk_score == 0:
                exited.add(pk)
                pair_details.pop(pk, None)
                continue

            # Hysteresis: score ≥ 55 → resta
            if pk_score >= grade_exit_threshold:
                detail["last_seen_at"] = now_iso
                detail["last_score"] = pk_score
                pair_details[pk] = detail
                retained.add(pk)
                continue

            # Residence: meno di N ore dall'ingresso → resta
            try:
                entered_at = dt.datetime.fromisoformat(detail.get("entered_at", now_iso))
                hours_in = (now_dt - entered_at).total_seconds() / 3600
            except (ValueError, TypeError):
                hours_in = 999
            if hours_in < SIGNAL_MIN_RESIDENCE_HOURS:
                detail["last_seen_at"] = now_iso
                detail["last_score"] = pk_score
                pair_details[pk] = detail
                retained.add(pk)
                continue

            # Grace period
            gc = detail.get("grace_counter", 0)
            if gc < SIGNAL_GRACE_REFRESHES:
                detail["grace_counter"] = gc + 1
                detail["last_seen_at"] = now_iso
                detail["last_score"] = pk_score
                pair_details[pk] = detail
                retained.add(pk)
                continue

            # Esce davvero
            exited.add(pk)
            pair_details.pop(pk, None)

    # ── Layer 4: Confirmation per nuovi ingressi ─────────────────────
    truly_entered = set()
    new_pending = {}
    for pk in current_top:
        if pk in prev_pairs or pk in retained:
            continue  # già confermato
        # Nuovo o in pending?
        if pk in pending_pairs:
            p_info = pending_pairs[pk]
            cnt = p_info.get("consecutive_count", 0) + 1
            if cnt >= SIGNAL_CONFIRMATION_REFRESHES:
                # Confermato!
                truly_entered.add(pk)
                pair_details[pk] = {
                    "entered_at": p_info.get("first_seen_at", now_iso),
                    "last_seen_at": now_iso,
                    "grace_counter": 0,
                    "last_score": current_details[pk]["quality_score"],
                }
            else:
                new_pending[pk] = {
                    "first_seen_at": p_info.get("first_seen_at", now_iso),
                    "consecutive_count": cnt,
                    "last_score": current_details[pk]["quality_score"],
                }
        else:
            # Prima volta: metti in pending
            new_pending[pk] = {
                "first_seen_at": now_iso,
                "consecutive_count": 1,
                "last_score": current_details[pk]["quality_score"],
            }

    # Stato finale
    final_pairs = retained | truly_entered

    # Prepara active_setups per la dashboard (stessi dati del Telegram)
    active_setups_list = []
    for key in sorted(final_pairs):
        s = current_details.get(key)
        if s:
            active_setups_list.append(s)
        else:
            # Mantenuto da stabilizzazione ma non più A/A+ nel calcolo grezzo
            detail = pair_details.get(key, {})
            parts = key.rsplit(" ", 1)
            active_setups_list.append({
                "asset": parts[0],
                "direction": parts[1] if len(parts) > 1 else "",
                "asset_label": ASSET_LABELS.get(parts[0], parts[0]),
                "quality_score": detail.get("last_score", 0),
                "grade": "A",
                "strength": detail.get("last_score", 0),
                "reasons": ["Mantenuto per stabilizzazione"],
            })

    # Salva stato completo (con setup per dashboard)
    try:
        os.makedirs(os.path.dirname(ASSET_ALERT_STATE_FILE) or ".", exist_ok=True)
        with open(ASSET_ALERT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "pairs": sorted(final_pairs),
                "pair_details": pair_details,
                "pending_pairs": new_pending,
                "active_setups": active_setups_list,
                "all_setups": trade_setups,
                "updated": now_iso,
            }, f, indent=2, default=str)
    except Exception:
        pass

    alerts_sent = 0
    if ALERTS_ENABLED:
        now_str = now_dt.strftime("%H:%M %d/%m")
        session_info = get_current_sessions()
        session_label = f"\n📍 Sessione: {session_info.get('session_label', 'N/A')}"

        lines = [f"📊 <b>REPORT ASSET ({now_str})</b>{session_label}\n"]

        # Solo asset genuinamente A/A+ (escludi stabilizzati)
        genuine_aa = {k for k in final_pairs if current_details.get(k)}

        if genuine_aa:
            lines.append(f"🟢 <b>SETUP ATTIVI A/A+ ({len(genuine_aa)}):</b>\n")
            for key in sorted(genuine_aa):
                s = current_details[key]
                is_new = key in truly_entered
                tag = "🆕" if is_new else "►"
                dir_lbl = "⬆ LONG" if s["direction"] == "LONG" else "⬇ SHORT"
                lbl = ASSET_LABELS.get(s["asset"], s.get("asset_label", s["asset"]))
                lines.append(
                    f"  {tag} <b>{lbl}</b> — {dir_lbl}\n"
                    f"     Grado: <b>{s['grade']}</b> | Score: {s['quality_score']:.0f}"
                )
                if is_new and s.get("reasons"):
                    lines.append(f"     💡 {' | '.join(s['reasons'][:3])}")
                lines.append("")
        else:
            lines.append("Nessun setup A/A+ attivo.\n")

        if exited:
            lines.append(f"🔴 <b>USCITI ({len(exited)}):</b>")
            for key in sorted(exited):
                parts = key.rsplit(" ", 1)
                asset_name = parts[0]
                direction = parts[1] if len(parts) > 1 else ""
                dir_lbl = "⬆ LONG" if direction == "LONG" else "⬇ SHORT"
                lbl = ASSET_LABELS.get(asset_name, asset_name)
                lines.append(f"  ✖ <b>{lbl}</b> — {dir_lbl}")
        else:
            lines.append("✅ Nessuna uscita rispetto all'ora precedente.")

        if _send_telegram("\n".join(lines)):
            alerts_sent += 1

    log.info(
        f"  Asset — setup A/A+: {len(final_pairs)} | "
        f"confermati: {len(truly_entered)} | usciti: {len(exited)} | "
        f"pending: {len(new_pending)} | alert inviati: {alerts_sent}"
    )
    return {"alerts_sent": alerts_sent, "entered": truly_entered, "exited": exited}


# ═══════════════════════════════════════════════════════════════════════════════
#  CICLO PRINCIPALE — dorme fino alla prossima ora piena, poi esegue
# ═══════════════════════════════════════════════════════════════════════════════

def _seconds_to_next_hour(margin: int = 10) -> float:
    """Secondi mancanti alla prossima ora piena + margine."""
    now = dt.datetime.now(dt.timezone.utc)
    next_hour = (now + dt.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return (next_hour - now).total_seconds() + margin


def run_once():
    """Esegue un singolo ciclo (utile per test)."""
    market = is_forex_market_open()
    if not market["is_open"]:
        log.info(f"Mercato chiuso ({market['reason']}), skip. Riapertura: {market['next_open']}")
        return

    t0 = time.time()
    try:
        run_currency_pipeline()
    except Exception as e:
        log.exception(f"Errore pipeline valute: {e}")
        try:
            _send_telegram(f"🚨 <b>ERRORE CRITICO PIPELINE VALUTE</b>\n<pre>{e}</pre>")
        except Exception:
            pass

    try:
        run_asset_pipeline()
    except Exception as e:
        log.exception(f"Errore pipeline asset: {e}")
        try:
            _send_telegram(f"🚨 <b>ERRORE CRITICO PIPELINE ASSET</b>\n<pre>{e}</pre>")
        except Exception:
            pass

    elapsed = time.time() - t0
    log.info(f"Ciclo completato in {elapsed:.1f}s")


def main():
    """Loop infinito: esegue ogni ora a xx:00."""
    log.info("=" * 60)
    log.info("  Currency Strength — Scheduler avviato")
    log.info(f"  Ora locale: {dt.datetime.now(_ROME).strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"  Alert Telegram: {'ATTIVI' if ALERTS_ENABLED else 'DISABILITATI'}")
    log.info("=" * 60)

    # Esegui subito al primo avvio
    log.info("Primo ciclo immediato...")
    run_once()

    # Poi ciclo infinito allineato alle ore piene
    while True:
        wait = _seconds_to_next_hour()
        next_run = dt.datetime.now(_ROME) + dt.timedelta(seconds=wait)
        log.info(f"Prossimo ciclo: {next_run.strftime('%H:%M:%S')} ({wait:.0f}s)")
        time.sleep(wait)
        run_once()


if __name__ == "__main__":
    os.makedirs("cache", exist_ok=True)
    main()
