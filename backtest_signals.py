"""
Backtest del sistema di segnali Currency Strength
===================================================
Simula il funzionamento della pipeline ora-per-ora su 1 mese di dati storici.
Misura la percentuale di successo dei segnali A/A+ confermati.

Metrica di successo per ogni segnale:
  - WIN:  la coppia si è mossa nella direzione prevista di almeno TARGET_PIPS
          entro EVAL_HOURS ore dall'ingresso confermato.
  - LOSS: non ha raggiunto il target oppure si è mossa contro.

Uso:
  python backtest_signals.py
"""

import sys, os, time, logging, datetime as dt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger("backtest")

from config import (
    CURRENCIES, FOREX_PAIRS,
    COMPOSITE_WEIGHT_H1, COMPOSITE_WEIGHT_H4, COMPOSITE_WEIGHT_D1,
    SCORE_SMOOTHING_ALPHA, ALERT_GRADES,
    SIGNAL_CONFIRMATION_REFRESHES, SIGNAL_GRACE_REFRESHES,
    SIGNAL_MIN_RESIDENCE_HOURS, GRADE_HYSTERESIS_POINTS,
    MIN_DIFFERENTIAL_THRESHOLD,
)

# ═══════════════════════════════════════════════════════════════════════════════
# PARAMETRI BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
BACKTEST_DAYS       = 30      # ultimo mese
WARMUP_BARS         = 220     # barre H1 di warm-up per EMA200 + indicatori
EVAL_HOURS          = [4, 8, 12, 24]  # finestre di valutazione successo
TARGET_PIPS_RATIO   = 0.0010  # 10 pips come rapporto (0.1%)
MAX_DRAWDOWN_RATIO  = 0.0020  # stop loss virtuale 20 pips
STEP_HOURS          = 1       # simula ogni ora


def download_all_data():
    """Scarica 60gg di dati H1 per tutte le coppie (max yfinance intraday)."""
    import yfinance as yf

    print("📥 Download dati H1 (60 giorni) per tutte le 28 coppie...")
    all_data = {}
    for pair_name, info in FOREX_PAIRS.items():
        ticker = info["ticker"]
        try:
            tk = yf.Ticker(ticker)
            df = tk.history(period="60d", interval="1h", auto_adjust=True)
            if not df.empty:
                for col in ["Dividends", "Stock Splits", "Capital Gains"]:
                    if col in df.columns:
                        df.drop(columns=[col], inplace=True)
                all_data[pair_name] = df
                print(f"  ✓ {pair_name}: {len(df)} barre")
            else:
                print(f"  ✗ {pair_name}: nessun dato")
        except Exception as e:
            print(f"  ✗ {pair_name}: errore — {e}")
        time.sleep(0.3)

    print(f"\n📊 Scaricate {len(all_data)}/{len(FOREX_PAIRS)} coppie\n")
    return all_data


def resample_to_h4(h1_data: dict) -> dict:
    """Resampla H1 → H4."""
    h4 = {}
    for pair, df in h1_data.items():
        agg = {"Open": "first", "High": "max", "Low": "min",
               "Close": "last", "Volume": "sum"}
        agg = {k: v for k, v in agg.items() if k in df.columns}
        r = df.resample("4h").agg(agg).dropna(subset=["Close"])
        if not r.empty:
            h4[pair] = r
    return h4


def resample_to_d1(h1_data: dict) -> dict:
    """Resampla H1 → D1."""
    d1 = {}
    for pair, df in h1_data.items():
        agg = {"Open": "first", "High": "max", "Low": "min",
               "Close": "last", "Volume": "sum"}
        agg = {k: v for k, v in agg.items() if k in df.columns}
        r = df.resample("1D").agg(agg).dropna(subset=["Close"])
        if not r.empty:
            d1[pair] = r
    return d1


def slice_data(all_data: dict, up_to: pd.Timestamp) -> dict:
    """Ritaglia i dati fino a un certo timestamp."""
    sliced = {}
    for pair, df in all_data.items():
        s = df[df.index <= up_to]
        if not s.empty and len(s) >= 50:
            sliced[pair] = s
    return sliced


def get_pair_price_at(all_h1: dict, pair_name: str, timestamp: pd.Timestamp) -> float | None:
    """Ottiene il prezzo Close della coppia al timestamp più vicino."""
    df = all_h1.get(pair_name)
    if df is None or df.empty:
        return None
    # Trova il prezzo più vicino (avanti)
    mask = df.index >= timestamp
    if mask.any():
        return float(df.loc[mask, "Close"].iloc[0])
    return float(df["Close"].iloc[-1])


def evaluate_signal(all_h1: dict, pair_name: str, direction: str,
                    entry_time: pd.Timestamp, entry_price: float) -> dict:
    """
    Valuta il risultato di un segnale a diverse finestre temporali.
    Restituisce dict con risultati per ogni finestra EVAL_HOURS.
    """
    df = all_h1.get(pair_name)
    if df is None:
        return {h: {"result": "NO_DATA", "pnl": 0} for h in EVAL_HOURS}

    results = {}
    for hours in EVAL_HOURS:
        end_time = entry_time + pd.Timedelta(hours=hours)
        window = df[(df.index > entry_time) & (df.index <= end_time)]

        if window.empty:
            results[hours] = {"result": "NO_DATA", "pnl": 0}
            continue

        if direction == "LONG":
            # Max favorable = max High, max adverse = min Low
            max_fav = float(window["High"].max())
            max_adv = float(window["Low"].min())
            exit_price = float(window["Close"].iloc[-1])
            pnl = (exit_price - entry_price) / entry_price
            max_fav_pnl = (max_fav - entry_price) / entry_price
            max_adv_pnl = (max_adv - entry_price) / entry_price
        else:  # SHORT
            max_fav = float(window["Low"].min())
            max_adv = float(window["High"].max())
            exit_price = float(window["Close"].iloc[-1])
            pnl = (entry_price - exit_price) / entry_price
            max_fav_pnl = (entry_price - max_fav) / entry_price
            max_adv_pnl = (entry_price - max_adv) / entry_price

        # Classificazione
        if max_fav_pnl >= TARGET_PIPS_RATIO:
            result = "WIN"      # ha raggiunto il target
        elif pnl > 0:
            result = "SMALL_WIN"  # positivo ma sotto target
        elif max_adv_pnl <= -MAX_DRAWDOWN_RATIO:
            result = "STOPPED"    # avrebbe preso lo stop
        else:
            result = "LOSS"

        results[hours] = {
            "result": result,
            "pnl": round(pnl * 10000, 1),        # in pips (x10000)
            "max_fav": round(max_fav_pnl * 10000, 1),
            "max_adv": round(max_adv_pnl * 10000, 1),
            "exit_price": exit_price,
        }

    return results


def run_backtest():
    """Esegue il backtest completo."""
    from strength_engine import (
        full_analysis, blend_multi_timeframe, smooth_composite_scores,
        compute_trade_setups,
    )
    from cot_data import load_cot_data, compute_cot_scores

    # ── 1. Download dati ────────────────────────────────────────────────
    all_h1_full = download_all_data()
    if len(all_h1_full) < 20:
        print("❌ Troppi pochi dati scaricati, impossibile eseguire il backtest.")
        return

    # Determina range temporale
    first_pair = next(iter(all_h1_full.values()))
    all_timestamps = first_pair.index
    last_ts = all_timestamps[-1]
    start_ts = last_ts - pd.Timedelta(days=BACKTEST_DAYS)

    # Filtra solo ore lavorative (forex chiuso sabato/domenica)
    hourly_steps = pd.date_range(start=start_ts, end=last_ts, freq="1h")
    hourly_steps = [ts for ts in hourly_steps if ts.weekday() < 5]  # lun-ven

    print(f"📅 Periodo backtest: {start_ts.strftime('%Y-%m-%d')} → {last_ts.strftime('%Y-%m-%d')}")
    print(f"⏱️  {len(hourly_steps)} ore da simulare (lun-ven)")
    print(f"🔧 Parametri: MIN_DIFF={MIN_DIFFERENTIAL_THRESHOLD}, "
          f"CONFIRM={SIGNAL_CONFIRMATION_REFRESHES}, "
          f"ALPHA={SCORE_SMOOTHING_ALPHA}")
    print()

    # ── 2. COT (statico, non cambia ora per ora) ────────────────────────
    try:
        cot_raw = load_cot_data()
        cot_scores = compute_cot_scores(cot_raw)
    except Exception:
        print("⚠️  COT non disponibile, uso score neutri")
        cot_scores = {
            c: {"score": 50, "bias": "NEUTRAL", "extreme": None,
                "net_spec_percentile": 50, "weekly_change": 0, "freshness_days": 999}
            for c in CURRENCIES
        }

    # ── 3. Simulazione ora-per-ora ──────────────────────────────────────
    prev_composite = None
    # Stato simulato (replica alerts.py)
    active_signals = {}     # pair_key → {entered_at, last_score, grace_counter}
    pending_signals = {}    # pair_key → {first_seen_at, consecutive_count}

    # Raccolta risultati
    all_entries = []        # ogni ingresso confermato
    total_refreshes = 0
    skipped = 0

    grade_exit_threshold = 60 - GRADE_HYSTERESIS_POINTS  # 55

    print("🔄 Simulazione in corso...\n")
    progress_interval = max(1, len(hourly_steps) // 20)

    for i, ts in enumerate(hourly_steps):
        if i % progress_interval == 0:
            pct = i / len(hourly_steps) * 100
            print(f"  [{pct:5.1f}%] {ts.strftime('%Y-%m-%d %H:%M')} — "
                  f"segnali attivi: {len(active_signals)}, "
                  f"pending: {len(pending_signals)}, "
                  f"entries totali: {len(all_entries)}")

        # Slice dati fino a questa ora
        h1_slice = slice_data(all_h1_full, ts)
        if len(h1_slice) < 15:
            skipped += 1
            continue

        h4_slice = resample_to_h4(h1_slice)
        d1_slice = resample_to_d1(h1_slice)

        # Filtra coppie con dati insufficienti
        h4_ok = {k: v for k, v in h4_slice.items() if len(v) >= 50}
        d1_ok = {k: v for k, v in d1_slice.items() if len(v) >= 20}

        if len(h4_ok) < 15 or len(d1_ok) < 10:
            skipped += 1
            continue

        # Crea futures "vuoti" (nel backtest non usiamo volume futures per velocità)
        empty_futures = {}

        try:
            analysis_h1 = full_analysis(h1_slice, empty_futures, cot_scores)
            analysis_h4 = full_analysis(h4_ok, empty_futures, cot_scores)
            analysis_d1 = full_analysis(d1_ok, empty_futures, cot_scores)
            analysis = blend_multi_timeframe(analysis_h1, analysis_h4, analysis_d1)
        except Exception as e:
            skipped += 1
            continue

        composite = analysis["composite"]

        # Smoothing
        composite = smooth_composite_scores(composite, prev_composite)
        prev_composite = composite
        analysis["composite"] = composite

        momentum = analysis["momentum"]
        classification = analysis["classification"]
        atr_context = analysis.get("atr_context", {})
        velocity = analysis.get("velocity", {})

        # Trade setups
        try:
            trade_setups = compute_trade_setups(
                composite, momentum, classification, atr_context, cot_scores,
                velocity_scores=velocity,
                trend_structure=analysis.get("trend_structure"),
                strength_persistence=analysis.get("strength_persistence"),
            )
        except Exception:
            skipped += 1
            continue

        total_refreshes += 1

        # ═══════════════════════════════════════════════════════════════
        # SIMULAZIONE LOGICA STABILIZZAZIONE (replica di alerts.py)
        # ═══════════════════════════════════════════════════════════════

        # Mappa setup correnti A/A+
        current_aa = {}
        all_scores = {}
        for s in trade_setups:
            key = f"{s['pair']} {s['direction']}"
            all_scores[key] = s.get("quality_score", 0)
            if s["grade"] in ALERT_GRADES:
                current_aa[key] = s

        raw_current = set(current_aa.keys())
        prev_active = set(active_signals.keys())

        # 1. ISTERESI
        hysteresis_kept = set()
        for pk in prev_active:
            if pk in raw_current:
                continue
            score = all_scores.get(pk, 0)
            if score >= grade_exit_threshold:
                hysteresis_kept.add(pk)

        # 2. RESIDENZA
        residence_kept = set()
        for pk in prev_active:
            if pk in raw_current or pk in hysteresis_kept:
                continue
            info = active_signals.get(pk, {})
            entered_at = info.get("entered_at")
            if entered_at:
                hours_in = (ts - entered_at).total_seconds() / 3600
                if hours_in < SIGNAL_MIN_RESIDENCE_HOURS:
                    residence_kept.add(pk)

        # 3. GRACE PERIOD
        grace_kept = set()
        for pk in prev_active:
            if pk in raw_current or pk in hysteresis_kept or pk in residence_kept:
                continue
            info = active_signals.get(pk, {})
            gc = info.get("grace_counter", 0)
            if gc < SIGNAL_GRACE_REFRESHES:
                grace_kept.add(pk)

        # 4. CONFERMA INGRESSO
        new_pending = {}
        confirmed_from_pending = set()
        for pk in raw_current:
            if pk in prev_active:
                continue  # già attivo
            pend = pending_signals.get(pk, {})
            count = pend.get("consecutive_count", 0) + 1
            if count >= SIGNAL_CONFIRMATION_REFRESHES:
                confirmed_from_pending.add(pk)
            else:
                new_pending[pk] = {
                    "first_seen_at": pend.get("first_seen_at", ts),
                    "consecutive_count": count,
                }

        # Set finale
        effective_current = (raw_current & prev_active) | confirmed_from_pending
        current_top = effective_current | hysteresis_kept | residence_kept | grace_kept

        entered = current_top - prev_active
        exited = prev_active - current_top

        # Aggiorna stato attivo
        new_active = {}
        for pk in current_top:
            if pk in active_signals:
                info = active_signals[pk].copy()
                info["last_score"] = all_scores.get(pk, 0)
                if pk in raw_current:
                    info["grace_counter"] = 0
                elif pk in grace_kept:
                    info["grace_counter"] = info.get("grace_counter", 0) + 1
                else:
                    info["grace_counter"] = 0
                new_active[pk] = info
            else:
                # Nuovo ingresso confermato
                s = current_aa.get(pk)
                # Cerca il pair forex per il prezzo di ingresso
                pair_label = pk.rsplit(" ", 1)[0] if " " in pk else pk
                pair_forex = pair_label.replace("/", "")
                reverse_key = pair_forex[3:] + pair_forex[:3]
                actual_pair = pair_forex if pair_forex in all_h1_full else (
                    reverse_key if reverse_key in all_h1_full else None
                )

                entry_price = None
                if actual_pair:
                    entry_price = get_pair_price_at(all_h1_full, actual_pair, ts)

                direction = pk.rsplit(" ", 1)[1] if " " in pk else "LONG"

                new_active[pk] = {
                    "entered_at": ts,
                    "grace_counter": 0,
                    "last_score": all_scores.get(pk, 0),
                    "entry_price": entry_price,
                    "actual_pair": actual_pair,
                    "direction": direction,
                    "grade": s["grade"] if s else "A",
                    "quality_score": s["quality_score"] if s else 0,
                    "differential": s["differential"] if s else 0,
                }

                # Registra l'ingresso
                all_entries.append({
                    "pair_key": pk,
                    "actual_pair": actual_pair,
                    "direction": direction,
                    "entry_time": ts,
                    "entry_price": entry_price,
                    "grade": s["grade"] if s else "A",
                    "quality_score": s["quality_score"] if s else 0,
                    "differential": s["differential"] if s else 0,
                })

        active_signals = new_active
        pending_signals = new_pending

    # ── Fine simulazione ────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"⏱️  Refresh simulati: {total_refreshes} (skipped: {skipped})")
    print(f"📊 Segnali confermati totali: {len(all_entries)}")

    if not all_entries:
        print("❌ Nessun segnale generato nel periodo. Il sistema è troppo restrittivo!")
        return

    # ── 4. Valutazione risultati ────────────────────────────────────────
    print(f"\n{'='*60}")
    print("📈 VALUTAZIONE RISULTATI")
    print(f"{'='*60}\n")
    print(f"Target: {TARGET_PIPS_RATIO*10000:.0f} pips | "
          f"Stop: {MAX_DRAWDOWN_RATIO*10000:.0f} pips\n")

    for hours in EVAL_HOURS:
        wins = 0
        small_wins = 0
        losses = 0
        stopped = 0
        no_data = 0
        total_pnl = 0
        pnl_list = []

        for entry in all_entries:
            if entry["entry_price"] is None or entry["actual_pair"] is None:
                no_data += 1
                continue

            eval_result = evaluate_signal(
                all_h1_full, entry["actual_pair"], entry["direction"],
                entry["entry_time"], entry["entry_price"],
            )

            r = eval_result.get(hours, {})
            res = r.get("result", "NO_DATA")
            pnl = r.get("pnl", 0)

            if res == "WIN":
                wins += 1
            elif res == "SMALL_WIN":
                small_wins += 1
            elif res == "STOPPED":
                stopped += 1
            elif res == "LOSS":
                losses += 1
            else:
                no_data += 1

            total_pnl += pnl
            pnl_list.append(pnl)

        valid = wins + small_wins + losses + stopped
        if valid == 0:
            print(f"  ⏰ Finestra {hours:2d}h: nessun dato valido")
            continue

        win_rate = (wins + small_wins) / valid * 100
        strict_win_rate = wins / valid * 100
        avg_pnl = total_pnl / valid
        median_pnl = float(np.median(pnl_list)) if pnl_list else 0

        print(f"  ⏰ Finestra {hours:2d}h:")
        print(f"     WIN (≥{TARGET_PIPS_RATIO*10000:.0f}pip): {wins:3d} | "
              f"Small win: {small_wins:3d} | "
              f"Loss: {losses:3d} | "
              f"Stopped: {stopped:3d} | "
              f"N/A: {no_data}")
        print(f"     Win rate (strict):  {strict_win_rate:5.1f}%")
        print(f"     Win rate (totale):  {win_rate:5.1f}%")
        print(f"     PnL medio: {avg_pnl:+.1f} pips | "
              f"PnL mediano: {median_pnl:+.1f} pips | "
              f"PnL totale: {total_pnl:+.1f} pips")
        print()

    # ── 5. Dettaglio per grado ──────────────────────────────────────────
    print(f"\n{'='*60}")
    print("📋 DETTAGLIO PER GRADO (finestra 8h)")
    print(f"{'='*60}\n")

    for grade in ["A+", "A"]:
        grade_entries = [e for e in all_entries if e["grade"] == grade]
        if not grade_entries:
            continue

        wins = 0
        total = 0
        pnl_sum = 0
        for entry in grade_entries:
            if entry["entry_price"] is None or entry["actual_pair"] is None:
                continue
            r = evaluate_signal(
                all_h1_full, entry["actual_pair"], entry["direction"],
                entry["entry_time"], entry["entry_price"],
            ).get(8, {})
            res = r.get("result", "NO_DATA")
            if res == "NO_DATA":
                continue
            total += 1
            if res in ("WIN", "SMALL_WIN"):
                wins += 1
            pnl_sum += r.get("pnl", 0)

        if total > 0:
            print(f"  Grado {grade}: {total} segnali, "
                  f"win rate {wins/total*100:.1f}%, "
                  f"PnL medio {pnl_sum/total:+.1f} pips")

    # ── 6. Top/Bottom segnali ───────────────────────────────────────────
    print(f"\n{'='*60}")
    print("🏆 TOP 10 SEGNALI (per PnL a 8h)")
    print(f"{'='*60}\n")

    entry_results = []
    for entry in all_entries:
        if entry["entry_price"] is None or entry["actual_pair"] is None:
            continue
        r = evaluate_signal(
            all_h1_full, entry["actual_pair"], entry["direction"],
            entry["entry_time"], entry["entry_price"],
        ).get(8, {})
        if r.get("result") != "NO_DATA":
            entry_results.append({**entry, "pnl_8h": r.get("pnl", 0), "result_8h": r.get("result", "")})

    if entry_results:
        entry_results.sort(key=lambda x: x["pnl_8h"], reverse=True)
        print(f"  {'Coppia':<18} {'Dir':<6} {'Grado':<5} {'Score':<6} {'PnL 8h':>8}  {'Risultato':<10} {'Data'}")
        print(f"  {'─'*80}")
        for e in entry_results[:10]:
            print(f"  {e['pair_key']:<18} {e['direction']:<6} {e['grade']:<5} "
                  f"{e['quality_score']:<6.0f} {e['pnl_8h']:>+7.1f}p  "
                  f"{e['result_8h']:<10} {e['entry_time'].strftime('%m-%d %H:%M')}")
        print(f"\n  {'─'*80}")
        print(f"  PEGGIORI 5:")
        for e in entry_results[-5:]:
            print(f"  {e['pair_key']:<18} {e['direction']:<6} {e['grade']:<5} "
                  f"{e['quality_score']:<6.0f} {e['pnl_8h']:>+7.1f}p  "
                  f"{e['result_8h']:<10} {e['entry_time'].strftime('%m-%d %H:%M')}")

    print(f"\n{'='*60}")
    print("✅ Backtest completato.")


if __name__ == "__main__":
    run_backtest()
