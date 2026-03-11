"""
Grid search pesi: PA fisso a 0.25, testa tutte le combinazioni di Vol/COT/C9
che sommano a 0.75, a step di 0.05.

Backtest rolling mensile (~35 step) per ogni configurazione.
Metriche: quality media, A+/A count, predittivita' direzionale, spread ranking.
"""

import sys, statistics, itertools
import numpy as np
import pandas as pd
from collections import defaultdict

from data_fetcher import fetch_all_pairs, compute_currency_returns
from cot_data import load_cot_data, compute_cot_scores
from config import CURRENCIES
import strength_engine as SE
import config as CFG

print("=" * 76)
print("  GRID SEARCH PESI: PA=0.25 fisso, Vol+COT+C9 = 0.75")
print("=" * 76)

# ── Fetch ──────────────────────────────────────────────────────────────
print("\n[1/3] Fetch H1 + COT ...", flush=True)
all_pairs = fetch_all_pairs("H1")
if not all_pairs:
    print("ERRORE"); sys.exit(1)
min_len = min(len(df) for df in all_pairs.values())
print(f"       {len(all_pairs)} coppie, {min_len} barre")

try:
    cot_df = load_cot_data()
    cot = compute_cot_scores(cot_df)
except Exception:
    cot = {c: {"score": 50, "bias": "NEUTRAL", "freshness_days": 99} for c in CURRENCIES}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def set_weights(pa, vol, c0t, c9):
    CFG.WEIGHT_PRICE_ACTION = pa; SE.WEIGHT_PRICE_ACTION = pa
    CFG.WEIGHT_VOLUME = vol; SE.WEIGHT_VOLUME = vol
    CFG.WEIGHT_COT = c0t; SE.WEIGHT_COT = c0t
    CFG.WEIGHT_C9 = c9; SE.WEIGHT_C9 = c9

ORIG = (0.25, 0.20, 0.30, 0.25)

def slice_pairs(all_p, start, end):
    return {p: df.iloc[start:end].copy() for p, df in all_p.items()}


def evaluate_config(all_p, cot_s, weights, window, step, horizon, n_steps):
    """Backtest rolling per una configurazione di pesi."""
    available = min(len(df) for df in all_p.values())
    results = {"quality": [], "n_top": [], "dir_correct": []}

    for si in range(n_steps):
        end = available - si * step
        start = end - window
        horizon_end = min(end + horizon, available)
        if start < 0 or horizon_end <= end:
            continue

        data_now = slice_pairs(all_p, start, end)

        set_weights(*weights)
        try:
            analysis = SE.full_analysis(data_now, {}, cot_s)
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
        except Exception:
            continue
        finally:
            set_weights(*ORIG)

        # Quality & A+/A
        if setups:
            results["quality"].append(statistics.mean([s["quality_score"] for s in setups]))
            results["n_top"].append(sum(1 for s in setups if s["grade"] in ("A+", "A")))
        else:
            results["quality"].append(0)
            results["n_top"].append(0)

        # Predittivita' direzionale
        comp = {c: d["composite"] for c, d in analysis["composite"].items()}
        rank = sorted(comp.items(), key=lambda x: x[1], reverse=True)
        top3 = [r[0] for r in rank[:3]]
        bot3 = [r[0] for r in rank[-3:]]

        data_fut = slice_pairs(all_p, start, horizon_end)
        try:
            rets = compute_currency_returns(data_fut, window=1)
            if rets.empty or len(rets) < 10:
                continue
            cum = (1 + rets).cumprod()
            t_idx = min(end - start - 1, len(cum) - 1)
            h_idx = min(horizon_end - start - 1, len(cum) - 1)
            if h_idx <= t_idx:
                continue
            ok = tot = 0
            for c in top3:
                if c in cum.columns:
                    tot += 1
                    if cum[c].iloc[h_idx] - cum[c].iloc[t_idx] > 0: ok += 1
            for c in bot3:
                if c in cum.columns:
                    tot += 1
                    if cum[c].iloc[h_idx] - cum[c].iloc[t_idx] < 0: ok += 1
            results["dir_correct"].append(ok / max(tot, 1))
        except Exception:
            pass

    return {k: statistics.mean(v) if v else 0 for k, v in results.items()}


# ══════════════════════════════════════════════════════════════════════════════
# FASE 2: GRID SEARCH
# ══════════════════════════════════════════════════════════════════════════════

PA_FIXED = 0.25
REMAINDER = 0.75
STEP_SIZE = 0.05
BACKTEST_WINDOW = 500
BACKTEST_STEP = 24
BACKTEST_HORIZON = 24
BACKTEST_N_STEPS = 35

# Genera combinazioni Vol+COT+C9 che sommano a REMAINDER
combos = []
for vol_int in range(0, int(REMAINDER / STEP_SIZE) + 1):
    for cot_int in range(0, int(REMAINDER / STEP_SIZE) + 1 - vol_int):
        c9_int = int(REMAINDER / STEP_SIZE) - vol_int - cot_int
        vol = round(vol_int * STEP_SIZE, 2)
        c0t = round(cot_int * STEP_SIZE, 2)
        c9 = round(c9_int * STEP_SIZE, 2)
        if vol >= 0.05 and c0t >= 0.10 and c9 >= 0.10:  # vincoli minimi sensati
            combos.append((PA_FIXED, vol, c0t, c9))

print(f"\n[2/3] Grid search: {len(combos)} configurazioni x {BACKTEST_N_STEPS} step each\n")
print(f"  {'PA':>5} {'Vol':>5} {'COT':>5} {'C9':>5}  |  {'Q_avg':>6} {'A+/A':>5} {'Dir%':>6}  {'Score':>7}")
print(f"  {'-'*5} {'-'*5} {'-'*5} {'-'*5}  +  {'-'*6} {'-'*5} {'-'*6}  {'-'*7}")

all_results = []
for idx, w in enumerate(combos):
    r = evaluate_config(all_pairs, cot, w, BACKTEST_WINDOW, BACKTEST_STEP,
                        BACKTEST_HORIZON, BACKTEST_N_STEPS)

    # Score composito: quality(40%) + A+/A_norm(30%) + direzionalita(30%)
    # Normalizzazione: quality ~40 range, A+/A ~0-4 range, dir ~0.5-0.8 range
    score = (r["quality"] / 50 * 40 +
             r["n_top"] / 3 * 30 +
             r["dir_correct"] * 100 * 30 / 100)
    r["score"] = score
    r["weights"] = w
    all_results.append(r)

    tag = " <-- ATTUALE" if w == ORIG else ""
    print(f"  {w[0]:5.2f} {w[1]:5.2f} {w[2]:5.2f} {w[3]:5.2f}  |  "
          f"{r['quality']:6.1f} {r['n_top']:5.2f} {r['dir_correct']*100:5.1f}%  "
          f"{score:7.2f}{tag}")

    if (idx + 1) % 10 == 0:
        print(f"  ... {idx+1}/{len(combos)} completati", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# FASE 3: CLASSIFICA
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 76)
print("  CLASSIFICA CONFIGURAZIONI (per score composito)")
print("=" * 76)

all_results.sort(key=lambda x: x["score"], reverse=True)

# Trova il risultato attuale
current_score = next((r["score"] for r in all_results if r["weights"] == ORIG), 0)
current_rank = next((i+1 for i, r in enumerate(all_results) if r["weights"] == ORIG), 0)

print(f"\n  {'#':>3}  {'PA':>5} {'Vol':>5} {'COT':>5} {'C9':>5}  |  "
      f"{'Q_avg':>6} {'A+/A':>5} {'Dir%':>6}  {'Score':>7}  Note")
print(f"  {'-'*3}  {'-'*5} {'-'*5} {'-'*5} {'-'*5}  +  "
      f"{'-'*6} {'-'*5} {'-'*6}  {'-'*7}  ----")

for i, r in enumerate(all_results[:15]):
    w = r["weights"]
    tag = " <-- ATTUALE" if w == ORIG else ""
    delta = (r["score"] - current_score) / max(abs(current_score), 0.01) * 100
    delta_s = f"{delta:+.1f}%" if w != ORIG else "  base"
    print(f"  {i+1:3d}  {w[0]:5.2f} {w[1]:5.2f} {w[2]:5.2f} {w[3]:5.2f}  |  "
          f"{r['quality']:6.1f} {r['n_top']:5.2f} {r['dir_correct']*100:5.1f}%  "
          f"{r['score']:7.2f}  {delta_s}{tag}")

# Top e bottom
best = all_results[0]
worst = all_results[-1]
bw = best["weights"]
ww = worst["weights"]

print(f"\n  MIGLIORE: PA={bw[0]} Vol={bw[1]} COT={bw[2]} C9={bw[3]}  "
      f"Score={best['score']:.2f}  "
      f"(delta vs attuale: {(best['score']-current_score)/max(abs(current_score),0.01)*100:+.1f}%)")
print(f"  PEGGIORE: PA={ww[0]} Vol={ww[1]} COT={ww[2]} C9={ww[3]}  "
      f"Score={worst['score']:.2f}")
print(f"  ATTUALE:  PA=0.25 Vol=0.20 COT=0.30 C9=0.25  "
      f"Score={current_score:.2f}  (rank #{current_rank}/{len(all_results)})")

# Miglioramento vs attuale
pct_vs_best = (best["score"] - current_score) / max(abs(current_score), 0.01) * 100

print("\n" + "=" * 76)
print("  VERDETTO")
print("=" * 76)
if pct_vs_best > 3:
    print(f"\n  >>> TROVATO MIGLIORAMENTO: {pct_vs_best:+.1f}% con "
          f"Vol={bw[1]} COT={bw[2]} C9={bw[3]}")
    print(f"      Quality: {best['quality']:.1f} vs {next(r['quality'] for r in all_results if r['weights']==ORIG):.1f}")
    print(f"      A+/A:    {best['n_top']:.2f} vs {next(r['n_top'] for r in all_results if r['weights']==ORIG):.2f}")
    print(f"      Dir%:    {best['dir_correct']*100:.1f}% vs {next(r['dir_correct']*100 for r in all_results if r['weights']==ORIG):.1f}%")
elif pct_vs_best > 0:
    print(f"\n  >>> MIGLIORAMENTO MARGINALE: {pct_vs_best:+.1f}%")
    print(f"      La configurazione attuale e' gia' quasi ottimale")
else:
    print(f"\n  >>> ATTUALE GIA' OTTIMALE")

print("\n" + "=" * 76)
