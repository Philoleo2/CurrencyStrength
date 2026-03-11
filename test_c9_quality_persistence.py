"""
Test: confronto qualità e persistenza dei segnali CON vs SENZA Candle-9.

Verifica che C9 non produca solo più segnali, ma segnali:
  1) Di qualità media superiore
  2) Con gradi più alti (A+/A vs B/C)
  3) Con differenziali più netti
  4) Più persistenti (stabili tra snapshot successivi)
"""

import sys, copy, statistics
import numpy as np
import pandas as pd

# ── Fetch dati reali ──────────────────────────────────────────────────
from data_fetcher import fetch_all_pairs
from config import (
    CURRENCIES, WEIGHT_PRICE_ACTION, WEIGHT_VOLUME, WEIGHT_COT, WEIGHT_C9,
)
from cot_data import load_cot_data, compute_cot_scores

print("=" * 72)
print("  TEST: Qualita' e persistenza segnali — CON C9 vs SENZA C9")
print("=" * 72)

# Scarica dati H1
print("\n[1/5] Fetch dati H1 ...", flush=True)
all_pairs = fetch_all_pairs("H1")
if not all_pairs:
    print("ERRORE: nessun dato H1 disponibile"); sys.exit(1)
print(f"       {len(all_pairs)} coppie caricate")

print("[1/5] Fetch COT ...", flush=True)
try:
    cot_df = load_cot_data()
    cot = compute_cot_scores(cot_df)
except Exception:
    cot = {c: {"score": 50, "bias": "NEUTRAL", "freshness_days": 99} for c in CURRENCIES}

# ── Import engine ─────────────────────────────────────────────────────
import strength_engine as SE
import config as CFG

# ══════════════════════════════════════════════════════════════════════════════
# HELPER: esegui analisi completa + trade setups
# ══════════════════════════════════════════════════════════════════════════════

def run_analysis_with_c9(all_p, cot_s):
    """Analisi con pesi correnti (incluso C9)."""
    analysis = SE.full_analysis(all_p, {}, cot_s)
    setups = SE.compute_trade_setups(
        composite=analysis["composite"],
        momentum=analysis["momentum"],
        classification=analysis["classification"],
        atr_context=analysis["atr_context"],
        cot_scores=cot_s,
        velocity_scores=analysis["velocity"],
        trend_structure=analysis["trend_structure"],
        strength_persistence=analysis["strength_persistence"],
        candle9=analysis.get("candle9", {}),
    )
    return analysis, setups


def run_analysis_without_c9(all_p, cot_s):
    """Analisi identica ma con pesi OLD (PA 0.40, Vol 0.30, COT 0.30, C9 0)."""
    # Salva pesi originali
    orig_pa  = CFG.WEIGHT_PRICE_ACTION
    orig_vol = CFG.WEIGHT_VOLUME
    orig_cot = CFG.WEIGHT_COT
    orig_c9  = CFG.WEIGHT_C9

    # Override pesi old
    CFG.WEIGHT_PRICE_ACTION = 0.40
    CFG.WEIGHT_VOLUME       = 0.30
    CFG.WEIGHT_COT          = 0.30
    CFG.WEIGHT_C9           = 0.00

    # Aggiorna anche nel modulo engine (importa i pesi a livello modulo)
    SE.WEIGHT_PRICE_ACTION = 0.40
    SE.WEIGHT_VOLUME       = 0.30
    SE.WEIGHT_COT          = 0.30
    SE.WEIGHT_C9           = 0.00

    analysis = SE.full_analysis(all_p, {}, cot_s)
    # Setup SENZA candle9
    setups = SE.compute_trade_setups(
        composite=analysis["composite"],
        momentum=analysis["momentum"],
        classification=analysis["classification"],
        atr_context=analysis["atr_context"],
        cot_scores=cot_s,
        velocity_scores=analysis["velocity"],
        trend_structure=analysis["trend_structure"],
        strength_persistence=analysis["strength_persistence"],
        candle9={},   # NO candle9
    )

    # Ripristina pesi originali
    CFG.WEIGHT_PRICE_ACTION = orig_pa
    CFG.WEIGHT_VOLUME       = orig_vol
    CFG.WEIGHT_COT          = orig_cot
    CFG.WEIGHT_C9           = orig_c9
    SE.WEIGHT_PRICE_ACTION  = orig_pa
    SE.WEIGHT_VOLUME        = orig_vol
    SE.WEIGHT_COT           = orig_cot
    SE.WEIGHT_C9            = orig_c9

    return analysis, setups


# ══════════════════════════════════════════════════════════════════════════════
# FASE 2: Qualità statica
# ══════════════════════════════════════════════════════════════════════════════

print("\n[2/5] Analisi SENZA C9 (pesi old: PA40 Vol30 COT30) ...", flush=True)
_, setups_old = run_analysis_without_c9(all_pairs, cot)

print("[2/5] Analisi CON C9 (pesi new: PA25 Vol20 COT30 C9=25) ...", flush=True)
_, setups_new = run_analysis_with_c9(all_pairs, cot)


def grade_stats(setups, label):
    """Stampa statistiche su qualità e gradi."""
    grades = {"A+": 0, "A": 0, "B": 0, "C": 0, "D": 0}
    quality_scores = []
    differentials = []
    for s in setups:
        g = s["grade"]
        if g in grades:
            grades[g] += 1
        quality_scores.append(s["quality_score"])
        differentials.append(abs(s["differential"]))

    n = len(setups)
    avg_q = statistics.mean(quality_scores) if quality_scores else 0
    med_q = statistics.median(quality_scores) if quality_scores else 0
    avg_d = statistics.mean(differentials) if differentials else 0
    top3_q = statistics.mean(sorted(quality_scores, reverse=True)[:3]) if len(quality_scores) >= 3 else avg_q
    a_plus_a = grades["A+"] + grades["A"]

    print(f"\n  --- {label} ---")
    print(f"  Segnali totali       : {n}")
    print(f"  A+={grades['A+']}  A={grades['A']}  B={grades['B']}  C={grades['C']}  D={grades['D']}")
    print(f"  % A+/A               : {a_plus_a/n*100:.1f}%" if n else "  N/A")
    print(f"  Quality media        : {avg_q:.1f}")
    print(f"  Quality mediana      : {med_q:.1f}")
    print(f"  Quality top-3 media  : {top3_q:.1f}")
    print(f"  Differenziale medio  : {avg_d:.1f}")

    return {
        "n": n, "grades": grades, "avg_q": avg_q, "med_q": med_q,
        "top3_q": top3_q, "avg_diff": avg_d, "a_plus_a": a_plus_a,
        "quality_scores": quality_scores,
    }


print("\n" + "=" * 72)
print("  CONFRONTO QUALITA' STATICA")
print("=" * 72)

stats_old = grade_stats(setups_old, "SENZA C9 (OLD)")
stats_new = grade_stats(setups_new, "CON C9 (NEW)")


# ══════════════════════════════════════════════════════════════════════════════
# FASE 3: Top segnali dettagliati
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 72)
print("  TOP 5 SEGNALI — DETTAGLIO")
print("=" * 72)

def print_top(setups, label, n=5):
    print(f"\n  --- {label} ---")
    for i, s in enumerate(setups[:n]):
        reasons_short = "; ".join(s["reasons"][:4])
        print(f"  {i+1}. {s['pair']:8s} {s['direction']:5s}  "
              f"Q={s['quality_score']:5.1f}  G={s['grade']:2s}  "
              f"diff={s['differential']:+5.1f}  | {reasons_short}")

print_top(setups_old, "SENZA C9 (OLD)")
print_top(setups_new, "CON C9 (NEW)")


# ══════════════════════════════════════════════════════════════════════════════
# FASE 4: Test persistenza — simula perturbazioni dati
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 72)
print("  TEST PERSISTENZA (5 snapshot con noise)")
print("=" * 72)

N_SNAPSHOTS = 5
NOISE_STD = 0.0003   # Piccola perturbazione su Close (~0.03%)

rng = np.random.default_rng(42)

def perturb_data(all_p, noise_std):
    """Aggiunge piccolo rumore gaussiano all'ultimo Close per simulare tick successivo."""
    perturbed = {}
    for pair, df in all_p.items():
        df2 = df.copy()
        if "Close" in df2.columns and len(df2) > 0:
            last_close = df2["Close"].iloc[-1]
            noise = rng.normal(0, noise_std * last_close)
            df2.loc[df2.index[-1], "Close"] = last_close + noise
            # Aggiorna High/Low coerentemente
            if "High" in df2.columns:
                df2.loc[df2.index[-1], "High"] = max(
                    df2["High"].iloc[-1], df2["Close"].iloc[-1])
            if "Low" in df2.columns:
                df2.loc[df2.index[-1], "Low"] = min(
                    df2["Low"].iloc[-1], df2["Close"].iloc[-1])
        perturbed[pair] = df2
    return perturbed


def compute_persistence(all_p, cot_s, use_c9: bool, n_snapshots: int):
    """
    Esegui n_snapshots analisi con piccole perturbazioni.
    Ritorna: stabilità top-N (quante coppie restano nelle top-5),
    stabilità gradi, stabilità direzione.
    """
    all_top5_pairs = []
    all_top5_grades = []
    all_top5_directions = []
    all_quality_scores = []

    for i in range(n_snapshots):
        if i == 0:
            data_i = all_p
        else:
            data_i = perturb_data(all_p, NOISE_STD)

        if use_c9:
            _, setups_i = run_analysis_with_c9(data_i, cot_s)
        else:
            _, setups_i = run_analysis_without_c9(data_i, cot_s)

        top5 = setups_i[:5]
        all_top5_pairs.append(set(s["pair"] for s in top5))
        all_top5_grades.append({s["pair"]: s["grade"] for s in top5})
        all_top5_directions.append({s["pair"]: s["direction"] for s in top5})
        all_quality_scores.append({s["pair"]: s["quality_score"] for s in top5})

    # Calcola stabilità
    # 1. Quante coppie della snapshot 0 rimangono nelle top-5 successive
    base_pairs = all_top5_pairs[0]
    pair_persistence = []
    for i in range(1, n_snapshots):
        overlap = len(base_pairs & all_top5_pairs[i])
        pair_persistence.append(overlap / max(len(base_pairs), 1))

    # 2. Stabilità gradi: per le coppie presenti in tutte le snapshot, quante mantengono il grado
    common_pairs = base_pairs
    for s in all_top5_pairs[1:]:
        common_pairs = common_pairs & s
    grade_stability = []
    dir_stability = []
    quality_stability = []
    for pair in common_pairs:
        grades_per_snap = [all_top5_grades[i].get(pair) for i in range(n_snapshots)]
        dirs_per_snap = [all_top5_directions[i].get(pair) for i in range(n_snapshots)]
        qs_per_snap = [all_top5_scores.get(pair, 0) for all_top5_scores in all_quality_scores]
        # Grado stabile = uguale in tutti gli snapshot
        if all(g == grades_per_snap[0] for g in grades_per_snap):
            grade_stability.append(1.0)
        else:
            grade_stability.append(0.0)
        # Direzione stabile
        if all(d == dirs_per_snap[0] for d in dirs_per_snap):
            dir_stability.append(1.0)
        else:
            dir_stability.append(0.0)
        # Variazione quality_score
        if len(qs_per_snap) > 1:
            quality_stability.append(statistics.stdev(qs_per_snap))
        else:
            quality_stability.append(0.0)

    return {
        "pair_persistence": statistics.mean(pair_persistence) if pair_persistence else 0,
        "common_pairs": len(common_pairs),
        "grade_stability": statistics.mean(grade_stability) if grade_stability else 0,
        "dir_stability": statistics.mean(dir_stability) if dir_stability else 0,
        "quality_stdev": statistics.mean(quality_stability) if quality_stability else 0,
    }


print("\n  Testing persistenza SENZA C9 ...", flush=True)
pers_old = compute_persistence(all_pairs, cot, use_c9=False, n_snapshots=N_SNAPSHOTS)

print("  Testing persistenza CON C9 ...", flush=True)
pers_new = compute_persistence(all_pairs, cot, use_c9=True, n_snapshots=N_SNAPSHOTS)


def print_persistence(p, label):
    print(f"\n  --- {label} ---")
    print(f"  Pair persistence TOP-5   : {p['pair_persistence']*100:.1f}%  (coppie stabili tra snapshot)")
    print(f"  Coppie comuni in tutti   : {p['common_pairs']}/5")
    print(f"  Stabilita' gradi         : {p['grade_stability']*100:.1f}%")
    print(f"  Stabilita' direzione     : {p['dir_stability']*100:.1f}%")
    print(f"  Quality score stdev media: {p['quality_stdev']:.2f}  (piu' basso = piu' stabile)")


print_persistence(pers_old, "SENZA C9 (OLD)")
print_persistence(pers_new, "CON C9 (NEW)")


# ══════════════════════════════════════════════════════════════════════════════
# FASE 5: Verdetto
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 72)
print("  VERDETTO FINALE")
print("=" * 72)

wins = 0
tests = 0
results = []

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
    results.append((label, icon, new_val, old_val, delta))
    print(f"  [{icon}] {label:35s}  NEW={new_val:7.1f}  OLD={old_val:7.1f}  delta={sign}{delta:.1f}")
    return passed

print()
# Qualità
check("Segnali A+/A (count)",         stats_new["a_plus_a"], stats_old["a_plus_a"])
check("Quality media",                 stats_new["avg_q"],    stats_old["avg_q"])
check("Quality mediana",               stats_new["med_q"],    stats_old["med_q"])
check("Quality top-3 media",           stats_new["top3_q"],   stats_old["top3_q"])
check("Differenziale medio",           stats_new["avg_diff"],  stats_old["avg_diff"], tolerance=1.0)
check("% A+/A",
      stats_new["a_plus_a"]/max(stats_new["n"],1)*100,
      stats_old["a_plus_a"]/max(stats_old["n"],1)*100)

# Persistenza
check("Pair persistence TOP-5 (%)",    pers_new["pair_persistence"]*100, pers_old["pair_persistence"]*100, tolerance=5)
check("Stabilita' gradi (%)",          pers_new["grade_stability"]*100,  pers_old["grade_stability"]*100, tolerance=5)
check("Stabilita' direzione (%)",      pers_new["dir_stability"]*100,    pers_old["dir_stability"]*100, tolerance=5)
check("Quality stdev (lower=better)",  pers_new["quality_stdev"],        pers_old["quality_stdev"],        higher_better=False, tolerance=0.5)

print(f"\n  Risultato: {wins}/{tests} check superati")

if wins >= 7:
    print("\n  >>> ECCELLENTE: C9 migliora sia qualita' che persistenza")
elif wins >= 5:
    print("\n  >>> BUONO: C9 migliora la maggior parte delle metriche")
elif wins == tests:
    print("\n  >>> PERFETTO: tutti i check superati")
else:
    print(f"\n  >>> ATTENZIONE: solo {wins}/{tests} check superati — verificare")

print("\n" + "=" * 72)
