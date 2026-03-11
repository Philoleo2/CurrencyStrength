"""
Test: confronto tempi di INGRESSO e di USCITA dei segnali CON vs SENZA Candle-9.

Simula il ciclo di vita dei segnali facendo "rolling forward" sull'H1 reale:
  - Taglia i dati a T-N, T-N+1, ..., T (ultimi N bar)
  - A ogni step esegue full_analysis + compute_trade_setups
  - Traccia il lifecycle di ogni segnale: entry, peak quality, exit, durata

Confronto su:
  1) Tempismo di ingresso (anticipo sull'escursione)
  2) Durata media del segnale A+/A
  3) Quality al picco e al momento dell'uscita
  4) Degradazione graduale vs brusca
"""

import sys, statistics, copy
import numpy as np
import pandas as pd
from collections import defaultdict

from data_fetcher import fetch_all_pairs
from cot_data import load_cot_data, compute_cot_scores
from config import CURRENCIES
import strength_engine as SE
import config as CFG

print("=" * 72)
print("  TEST: Tempi di ingresso e uscita segnali — CON C9 vs SENZA C9")
print("=" * 72)

# ── Fetch dati ────────────────────────────────────────────────────────
print("\n[1/5] Fetch dati H1 ...", flush=True)
all_pairs = fetch_all_pairs("H1")
if not all_pairs:
    print("ERRORE: nessun dato H1 disponibile"); sys.exit(1)
print(f"       {len(all_pairs)} coppie caricate")

# Determina la lunghezza minima per avere abbastanza storia
min_len = min(len(df) for df in all_pairs.values())
print(f"       Barre disponibili (min): {min_len}")

print("[1/5] Fetch COT ...", flush=True)
try:
    cot_df = load_cot_data()
    cot = compute_cot_scores(cot_df)
except Exception:
    cot = {c: {"score": 50, "bias": "NEUTRAL", "freshness_days": 99} for c in CURRENCIES}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def set_weights(pa, vol, c0t, c9):
    """Override pesi sia in config che in strength_engine."""
    CFG.WEIGHT_PRICE_ACTION = pa; SE.WEIGHT_PRICE_ACTION = pa
    CFG.WEIGHT_VOLUME       = vol; SE.WEIGHT_VOLUME       = vol
    CFG.WEIGHT_COT          = c0t; SE.WEIGHT_COT          = c0t
    CFG.WEIGHT_C9           = c9;  SE.WEIGHT_C9           = c9


def slice_pairs(all_p, n_bars):
    """Tagliare gli ultimi n_bars da ogni coppia."""
    return {pair: df.iloc[-n_bars:].copy() for pair, df in all_p.items()}


def run_setups(data, cot_s, use_c9):
    """Full analysis → trade setups, con o senza C9."""
    if use_c9:
        set_weights(0.25, 0.20, 0.30, 0.25)
    else:
        set_weights(0.40, 0.30, 0.30, 0.00)

    analysis = SE.full_analysis(data, {}, cot_s)
    setups = SE.compute_trade_setups(
        composite=analysis["composite"],
        momentum=analysis["momentum"],
        classification=analysis["classification"],
        atr_context=analysis["atr_context"],
        cot_scores=cot_s,
        velocity_scores=analysis["velocity"],
        trend_structure=analysis["trend_structure"],
        strength_persistence=analysis["strength_persistence"],
        candle9=analysis.get("candle9", {}) if use_c9 else {},
    )
    # Ripristina pesi originali
    set_weights(0.25, 0.20, 0.30, 0.25)
    return setups


# ══════════════════════════════════════════════════════════════════════════════
# FASE 2: ROLLING FORWARD – ciclo di vita segnali
# ══════════════════════════════════════════════════════════════════════════════

# Parametri rolling
LOOKBACK_MIN = 300       # barre minime per analisi affidabile
N_STEPS = 12             # quanti snapshot temporali (ultimi 12 bar, ~12 ore H1)
# I dati devono avere almeno LOOKBACK_MIN + N_STEPS barre
required = LOOKBACK_MIN + N_STEPS
if min_len < required:
    LOOKBACK_MIN = max(min_len - N_STEPS - 5, 200)
    print(f"  (adattato LOOKBACK_MIN a {LOOKBACK_MIN} per dati disponibili)")

print(f"\n[2/5] Rolling forward: {N_STEPS} step da T-{N_STEPS-1} a T")
print(f"       Window base: {LOOKBACK_MIN} barre, step = 1 barra H1\n")


def rolling_lifecycle(all_p, cot_s, use_c9, n_steps):
    """
    Esegui analisi a T-n, T-n+1, ..., T.
    Traccia lifecycle di ogni coppia-direzione: entry, exit, peak, durata.
    """
    total_bars = LOOKBACK_MIN + n_steps
    # lifecycles[pair_dir] = {entry_step, exit_step, peak_q, peak_step, grades: [], qualitys: []}
    lifecycles = {}
    step_signals = []   # [{pair: {...}}, ...]

    for step in range(n_steps):
        # Slice: T-(n_steps-1-step)..T  →  progressivamente "avanti nel tempo"
        end_offset = n_steps - 1 - step  # 11, 10, ..., 0
        n_bars = total_bars - end_offset
        data_slice = slice_pairs(all_p, n_bars)

        setups = run_setups(data_slice, cot_s, use_c9)

        # Indice per lookup rapido
        current = {}
        for s in setups:
            key = f"{s['pair']}_{s['direction']}"
            current[key] = s

        step_signals.append(current)

        # Aggiorna lifecycle
        for key, s in current.items():
            if key not in lifecycles:
                lifecycles[key] = {
                    "pair": s["pair"], "direction": s["direction"],
                    "entry_step": step,
                    "exit_step": None,   # None = ancora attivo a T
                    "peak_q": s["quality_score"],
                    "peak_step": step,
                    "peak_grade": s["grade"],
                    "grades": [],
                    "qualitys": [],
                }
            lc = lifecycles[key]
            lc["grades"].append(s["grade"])
            lc["qualitys"].append(s["quality_score"])
            if s["quality_score"] > lc["peak_q"]:
                lc["peak_q"] = s["quality_score"]
                lc["peak_step"] = step
                lc["peak_grade"] = s["grade"]

        # Segna uscita per segnali che scompaiono
        for key, lc in lifecycles.items():
            if lc["exit_step"] is None and key not in current and len(lc["grades"]) > 0:
                # Scomparso a questo step
                lc["exit_step"] = step

    # Segna durata
    for key, lc in lifecycles.items():
        if lc["exit_step"] is None:
            lc["duration"] = n_steps - lc["entry_step"]  # ancora attivo
            lc["still_active"] = True
        else:
            lc["duration"] = lc["exit_step"] - lc["entry_step"]
            lc["still_active"] = False

        # Quality all'uscita o all'ultimo step
        lc["exit_q"] = lc["qualitys"][-1] if lc["qualitys"] else 0
        lc["entry_q"] = lc["qualitys"][0] if lc["qualitys"] else 0

        # Degradazione: differenza tra peak e last
        lc["degradation"] = lc["peak_q"] - lc["exit_q"]

        # Crescita: differenza tra entry e peak
        lc["growth"] = lc["peak_q"] - lc["entry_q"]

    return lifecycles, step_signals


print("  Running CON C9 ...", flush=True)
lc_new, steps_new = rolling_lifecycle(all_pairs, cot, use_c9=True, n_steps=N_STEPS)

print("  Running SENZA C9 ...", flush=True)
lc_old, steps_old = rolling_lifecycle(all_pairs, cot, use_c9=False, n_steps=N_STEPS)


# ══════════════════════════════════════════════════════════════════════════════
# FASE 3: Analisi metriche di lifecycle
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n[3/5] Analisi lifecycle\n")

GRADE_ORDER = {"A+": 5, "A": 4, "B": 3, "C": 2, "D": 1}

def lifecycle_stats(lifecycles, label):
    """Calcola e stampa statistiche aggregate sui lifecycle."""
    all_lc = list(lifecycles.values())
    # Solo segnali che hanno raggiunto almeno A (quality >= 60)
    high_q = [lc for lc in all_lc if lc["peak_q"] >= 60]
    # Solo A+/A
    top_grade = [lc for lc in all_lc if lc["peak_grade"] in ("A+", "A")]

    # Durate
    durations_all = [lc["duration"] for lc in all_lc]
    durations_top = [lc["duration"] for lc in top_grade]
    still_active_top = sum(1 for lc in top_grade if lc["still_active"])

    # Quality metrics
    peak_qs = [lc["peak_q"] for lc in all_lc]
    entry_qs = [lc["entry_q"] for lc in all_lc]
    exit_qs = [lc["exit_q"] for lc in all_lc]
    degradations = [lc["degradation"] for lc in all_lc if lc["duration"] >= 2]
    growths = [lc["growth"] for lc in all_lc if lc["duration"] >= 2]

    # Entry timing: quanto tempo tra entry e peak (meno = entra gia' al top)
    entry_to_peak = [lc["peak_step"] - lc["entry_step"] for lc in top_grade]

    # Sopravvivenza: % dei segnali A+/A ancora attivi a T
    survival_rate = still_active_top / max(len(top_grade), 1) * 100

    # Grade stability: per segnali multi-step, quante volte il grado cambia
    grade_changes = []
    for lc in all_lc:
        if len(lc["grades"]) >= 2:
            changes = sum(1 for i in range(1, len(lc["grades"])) if lc["grades"][i] != lc["grades"][i-1])
            grade_changes.append(changes / (len(lc["grades"]) - 1))
    
    # Consistenza quality: stdev della quality nel tempo per segnali durata >= 3
    q_consistency = []
    for lc in all_lc:
        if len(lc["qualitys"]) >= 3:
            q_consistency.append(statistics.stdev(lc["qualitys"]))

    print(f"\n  --- {label} ---")
    print(f"  Segnali unici totali    : {len(all_lc)}")
    print(f"  Segnali peak A+/A       : {len(top_grade)}")
    print(f"  Segnali A+/A attivi a T : {still_active_top}/{len(top_grade)}  ({survival_rate:.0f}%)")
    print(f"  Durata media (tutti)    : {statistics.mean(durations_all):.1f} step" if durations_all else "  N/A")
    print(f"  Durata media (A+/A)     : {statistics.mean(durations_top):.1f} step" if durations_top else "  N/A")
    print(f"  Quality entry media     : {statistics.mean(entry_qs):.1f}" if entry_qs else "  N/A")
    print(f"  Quality peak media      : {statistics.mean(peak_qs):.1f}" if peak_qs else "  N/A")
    print(f"  Quality exit media      : {statistics.mean(exit_qs):.1f}" if exit_qs else "  N/A")
    print(f"  Degradazione media      : {statistics.mean(degradations):.1f}" if degradations else "  N/A")
    print(f"  Crescita entry->peak    : {statistics.mean(growths):.1f}" if growths else "  N/A")
    print(f"  Entry-to-peak (A+/A)    : {statistics.mean(entry_to_peak):.1f} step" if entry_to_peak else "  N/A")
    print(f"  Cambio grado (freq)     : {statistics.mean(grade_changes)*100:.1f}%" if grade_changes else "  N/A")
    print(f"  Quality stdev nel tempo : {statistics.mean(q_consistency):.2f}" if q_consistency else "  N/A")

    return {
        "n_total": len(all_lc),
        "n_top": len(top_grade),
        "active_top": still_active_top,
        "survival_pct": survival_rate,
        "dur_all": statistics.mean(durations_all) if durations_all else 0,
        "dur_top": statistics.mean(durations_top) if durations_top else 0,
        "q_entry": statistics.mean(entry_qs) if entry_qs else 0,
        "q_peak": statistics.mean(peak_qs) if peak_qs else 0,
        "q_exit": statistics.mean(exit_qs) if exit_qs else 0,
        "degradation": statistics.mean(degradations) if degradations else 0,
        "growth": statistics.mean(growths) if growths else 0,
        "entry_to_peak": statistics.mean(entry_to_peak) if entry_to_peak else 0,
        "grade_change_freq": statistics.mean(grade_changes) * 100 if grade_changes else 0,
        "q_stdev": statistics.mean(q_consistency) if q_consistency else 0,
    }


stats_old = lifecycle_stats(lc_old, "SENZA C9 (OLD)")
stats_new = lifecycle_stats(lc_new, "CON C9 (NEW)")


# ══════════════════════════════════════════════════════════════════════════════
# FASE 4: Top segnali — dettaglio lifecycle
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 72)
print("  TOP SEGNALI A+/A — DETTAGLIO LIFECYCLE")
print("=" * 72)


def print_lifecycle_detail(lifecycles, label, max_show=6):
    top = sorted(lifecycles.values(), key=lambda x: x["peak_q"], reverse=True)
    top = [lc for lc in top if lc["peak_grade"] in ("A+", "A")][:max_show]

    print(f"\n  --- {label} ---")
    for lc in top:
        status = "ATTIVO" if lc["still_active"] else f"USCITO step {lc['exit_step']}"
        grade_seq = "->".join(lc["grades"])
        q_first = lc["qualitys"][0] if lc["qualitys"] else 0
        q_last = lc["qualitys"][-1] if lc["qualitys"] else 0
        print(f"  {lc['pair']:8s} {lc['direction']:5s}  "
              f"dur={lc['duration']:2d}  peak={lc['peak_q']:5.1f}({lc['peak_grade']})  "
              f"entry={q_first:5.1f} exit={q_last:5.1f}  degrad={lc['degradation']:+5.1f}  "
              f"{status}")
        print(f"           gradi: [{grade_seq}]")


print_lifecycle_detail(lc_old, "SENZA C9 (OLD)")
print_lifecycle_detail(lc_new, "CON C9 (NEW)")


# ══════════════════════════════════════════════════════════════════════════════
# FASE 5: Verdetto
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 72)
print("  VERDETTO — INGRESSO & USCITA")
print("=" * 72)

wins = 0
tests = 0


def check(label, new_val, old_val, higher_better=True, tolerance=0):
    global wins, tests
    tests += 1
    if higher_better:
        passed = new_val >= old_val - tolerance
    else:
        passed = new_val <= old_val + tolerance
    icon = "PASS" if passed else "FAIL"
    if passed:
        wins += 1
    delta = new_val - old_val
    sign = "+" if delta >= 0 else ""
    print(f"  [{icon}] {label:40s}  NEW={new_val:7.1f}  OLD={old_val:7.1f}  delta={sign}{delta:.1f}")
    return passed


print("\n  --- INGRESSO ---")
check("Quality al momento ingresso",         stats_new["q_entry"],   stats_old["q_entry"])
check("Crescita entry->peak",                stats_new["growth"],    stats_old["growth"], higher_better=False, tolerance=2)
check("Step entry-to-peak (meno = meglio)",   stats_new["entry_to_peak"], stats_old["entry_to_peak"], higher_better=False, tolerance=1)
check("Segnali A+/A (count)",                stats_new["n_top"],     stats_old["n_top"])

print("\n  --- USCITA / PERSISTENZA ---")
check("Durata media A+/A (step)",            stats_new["dur_top"],   stats_old["dur_top"])
check("Sopravvivenza A+/A a T (%)",          stats_new["survival_pct"], stats_old["survival_pct"])
check("Quality all'uscita",                  stats_new["q_exit"],     stats_old["q_exit"])
check("Degradazione (meno = meglio)",        stats_new["degradation"], stats_old["degradation"], higher_better=False, tolerance=1)
check("Freq. cambio grado (meno = stabile)", stats_new["grade_change_freq"], stats_old["grade_change_freq"], higher_better=False, tolerance=3)
check("Quality stdev nel tempo (< = stabile)", stats_new["q_stdev"], stats_old["q_stdev"], higher_better=False, tolerance=0.5)

print(f"\n  Risultato: {wins}/{tests} check superati")

if wins >= 8:
    print("\n  >>> ECCELLENTE: C9 migliora sia ingresso che uscita")
elif wins >= 6:
    print("\n  >>> BUONO: C9 migliora la maggior parte delle metriche")
elif wins == tests:
    print("\n  >>> PERFETTO: tutti i check superati")
else:
    print(f"\n  >>> DA VALUTARE: {wins}/{tests} check superati")

# ── Summary compatto ──
print("\n" + "=" * 72)
print("  RIASSUNTO")
print("=" * 72)
print(f"\n  INGRESSO:")
print(f"    C9 produce segnali con quality ingresso: {stats_new['q_entry']:.1f} vs {stats_old['q_entry']:.1f} (old)")
print(f"    Raggiunge il peak in {stats_new['entry_to_peak']:.1f} step vs {stats_old['entry_to_peak']:.1f} (old)")
print(f"\n  USCITA:")
print(f"    Segnali A+/A durano {stats_new['dur_top']:.1f} step vs {stats_old['dur_top']:.1f} (old)")
print(f"    Sopravvivenza a T: {stats_new['survival_pct']:.0f}% vs {stats_old['survival_pct']:.0f}%")
print(f"    Degradazione: {stats_new['degradation']:.1f} pts vs {stats_old['degradation']:.1f} pts (old)")
print(f"    Quality uscita: {stats_new['q_exit']:.1f} vs {stats_old['q_exit']:.1f} (old)")
print("\n" + "=" * 72)
