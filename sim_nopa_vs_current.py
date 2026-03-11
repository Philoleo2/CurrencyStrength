"""
Simulazione: Sistema SENZA Price Action (Vol 30% + COT 30% + C9 40%)
vs Sistema ATTUALE (PA 25% + Vol 20% + COT 30% + C9 25%).

1) Snapshot attuale: classifica, segnali, qualita'
2) Backtest mensile rolling: ~720 barre H1 (~30 giorni), step ogni 24 barre
   Misura: ranking stability, signal quality, grade consistency,
           predittivita' direzionale (la classifica prevede il movimento futuro?)
"""

import sys, statistics
import numpy as np
import pandas as pd
from collections import defaultdict

from data_fetcher import fetch_all_pairs
from cot_data import load_cot_data, compute_cot_scores
from config import CURRENCIES
import strength_engine as SE
import config as CFG

print("=" * 76)
print("  SIMULAZIONE: NO-PA (Vol30+COT30+C9=40) vs ATTUALE (PA25+Vol20+COT30+C9=25)")
print("=" * 76)

# ── Fetch ──────────────────────────────────────────────────────────────
print("\n[1/4] Fetch H1 ...", flush=True)
all_pairs = fetch_all_pairs("H1")
if not all_pairs:
    print("ERRORE: nessun dato"); sys.exit(1)
min_len = min(len(df) for df in all_pairs.values())
print(f"       {len(all_pairs)} coppie, {min_len} barre minime")

print("[1/4] Fetch COT ...", flush=True)
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
    CFG.WEIGHT_VOLUME       = vol; SE.WEIGHT_VOLUME       = vol
    CFG.WEIGHT_COT          = c0t; SE.WEIGHT_COT          = c0t
    CFG.WEIGHT_C9           = c9;  SE.WEIGHT_C9           = c9

WEIGHTS_CURRENT = (0.25, 0.20, 0.30, 0.25)  # PA, Vol, COT, C9
WEIGHTS_NOPA    = (0.00, 0.30, 0.30, 0.40)   # No PA, Vol, COT, C9


def slice_pairs(all_p, start, end):
    return {pair: df.iloc[start:end].copy() for pair, df in all_p.items()}


def run_full(data, cot_s, weights):
    set_weights(*weights)
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
        candle9=analysis.get("candle9", {}),
    )
    set_weights(*WEIGHTS_CURRENT)  # ripristina
    return analysis, setups


# ══════════════════════════════════════════════════════════════════════════════
# FASE 2: SNAPSHOT ATTUALE — classifica e segnali
# ══════════════════════════════════════════════════════════════════════════════

print("\n[2/4] Snapshot attuale\n")

an_cur, setups_cur = run_full(all_pairs, cot, WEIGHTS_CURRENT)
an_nopa, setups_nopa = run_full(all_pairs, cot, WEIGHTS_NOPA)


def print_ranking(analysis, label):
    comp = analysis["composite"]
    ranking = sorted(comp.items(), key=lambda x: x[1]["composite"], reverse=True)
    print(f"\n  Classifica — {label}")
    print(f"  {'#':>3}  {'CCY':4}  {'Composite':>9}  {'PA':>6}  {'Vol':>6}  {'COT':>6}  {'C9':>6}  Label")
    for i, (ccy, d) in enumerate(ranking, 1):
        print(f"  {i:3d}  {ccy:4s}  {d['composite']:9.1f}  "
              f"{d['price_score']:6.1f}  {d['volume_score']:6.1f}  "
              f"{d['cot_score']:6.1f}  {d['c9_score']:6.1f}  {d['label']}")


def print_setups(setups, label, n=6):
    print(f"\n  Top segnali — {label}")
    for i, s in enumerate(setups[:n], 1):
        print(f"  {i}. {s['pair']:8s} {s['direction']:5s}  "
              f"Q={s['quality_score']:5.1f}  G={s['grade']:2s}  diff={s['differential']:+5.1f}")


print_ranking(an_cur, "ATTUALE (PA25+Vol20+COT30+C9=25)")
print_ranking(an_nopa, "NO-PA (Vol30+COT30+C9=40)")
print_setups(setups_cur, "ATTUALE", 6)
print_setups(setups_nopa, "NO-PA", 6)

# Confronto ranking
rank_cur = [ccy for ccy, _ in sorted(an_cur["composite"].items(),
            key=lambda x: x[1]["composite"], reverse=True)]
rank_nopa = [ccy for ccy, _ in sorted(an_nopa["composite"].items(),
             key=lambda x: x[1]["composite"], reverse=True)]

print(f"\n  Ranking ATTUALE : {' > '.join(rank_cur)}")
print(f"  Ranking NO-PA   : {' > '.join(rank_nopa)}")

# Kendall tau (ordinamento)
from itertools import combinations
concordant = discordant = 0
for i, j in combinations(range(len(CURRENCIES)), 2):
    ci_cur = rank_cur.index(CURRENCIES[i]) - rank_cur.index(CURRENCIES[j])
    ci_nopa = rank_nopa.index(CURRENCIES[i]) - rank_nopa.index(CURRENCIES[j])
    if ci_cur * ci_nopa > 0:
        concordant += 1
    elif ci_cur * ci_nopa < 0:
        discordant += 1
n_c = len(CURRENCIES)
tau = (concordant - discordant) / (n_c * (n_c - 1) / 2)
print(f"\n  Kendall tau (correlazione ranking): {tau:.3f}  "
      f"({'molto simili' if tau > 0.8 else 'divergenti' if tau < 0.5 else 'moderata'})")


# ══════════════════════════════════════════════════════════════════════════════
# FASE 3: BACKTEST MENSILE ROLLING
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 76)
print("  BACKTEST MENSILE ROLLING (~30gg H1)")
print("=" * 76)

WINDOW = 500       # barre per analisi (~21 giorni)
STEP   = 24        # ogni 24 barre (~1 giorno)
HORIZON = 24       # predittivita': guarda 24 barre avanti per verificare
# Serve: WINDOW + HORIZON barre, partendo dal fondo
total_needed = WINDOW + HORIZON
available = min_len

n_steps = (available - total_needed) // STEP
if n_steps < 5:
    WINDOW = 300
    n_steps = (available - WINDOW - HORIZON) // STEP
print(f"  Window={WINDOW}, Step={STEP}, Horizon={HORIZON} barre")
print(f"  Step disponibili: {n_steps}\n")

# Metriche da raccogliere per ogni step
metrics_cur  = {"quality": [], "n_top": [], "avg_diff": [], "dir_correct": [], "rank_spread": []}
metrics_nopa = {"quality": [], "n_top": [], "avg_diff": [], "dir_correct": [], "rank_spread": []}


def evaluate_step(all_p, cot_s, weights, start, end, horizon_end):
    """Esegui analisi su [start:end], poi verifica direzionalita' su [end:horizon_end]."""
    data_now = slice_pairs(all_p, start, end)
    data_future = slice_pairs(all_p, start, horizon_end)

    _, setups = run_full(data_now, cot_s, weights)

    # Composite corrente
    an, _ = run_full(data_now, cot_s, weights)
    comp_now = {ccy: d["composite"] for ccy, d in an["composite"].items()}

    # Classifica attuale: top 3 e bottom 3
    rank = sorted(comp_now.items(), key=lambda x: x[1], reverse=True)
    top3 = [r[0] for r in rank[:3]]
    bot3 = [r[0] for r in rank[-3:]]
    spread = rank[0][1] - rank[-1][1]

    # Verifica direzionalita' futura: le valute forti si sono effettivamente mosse su?
    # Calcola prezzo medio di ogni valuta (cum returns) a T e T+horizon
    from data_fetcher import compute_currency_returns
    try:
        rets_full = compute_currency_returns(data_future, window=1)
        if rets_full.empty or len(rets_full) < 10:
            return None
        cum = (1 + rets_full).cumprod()
        # Prezzo a T (fine analisi) e T+horizon
        t_idx = min(end - start - 1, len(cum) - 1)
        h_idx = min(horizon_end - start - 1, len(cum) - 1)
        if h_idx <= t_idx:
            return None

        dir_correct = 0
        dir_total = 0
        for ccy in top3:
            if ccy in cum.columns:
                move = cum[ccy].iloc[h_idx] - cum[ccy].iloc[t_idx]
                dir_total += 1
                if move > 0:
                    dir_correct += 1
        for ccy in bot3:
            if ccy in cum.columns:
                move = cum[ccy].iloc[h_idx] - cum[ccy].iloc[t_idx]
                dir_total += 1
                if move < 0:
                    dir_correct += 1

        dir_pct = dir_correct / max(dir_total, 1)
    except Exception:
        dir_pct = 0.5

    # Stats segnali
    top_setups = [s for s in setups if s["grade"] in ("A+", "A")]
    avg_q = statistics.mean([s["quality_score"] for s in setups]) if setups else 0
    avg_diff = statistics.mean([abs(s["differential"]) for s in setups]) if setups else 0

    return {
        "quality": avg_q,
        "n_top": len(top_setups),
        "avg_diff": avg_diff,
        "dir_correct": dir_pct,
        "rank_spread": spread,
    }


print("  Backtesting ...", flush=True)
for step_i in range(n_steps):
    end = available - step_i * STEP
    start = end - WINDOW
    horizon_end = min(end + HORIZON, available)

    if start < 0:
        break

    r_cur = evaluate_step(all_pairs, cot, WEIGHTS_CURRENT, start, end, horizon_end)
    r_nopa = evaluate_step(all_pairs, cot, WEIGHTS_NOPA, start, end, horizon_end)

    if r_cur and r_nopa:
        for k in metrics_cur:
            metrics_cur[k].append(r_cur[k])
            metrics_nopa[k].append(r_nopa[k])

    # Progress
    if (step_i + 1) % 5 == 0 or step_i == n_steps - 1:
        print(f"    step {step_i+1}/{n_steps}", flush=True)

n_valid = len(metrics_cur["quality"])
print(f"\n  Step validi: {n_valid}")


# ══════════════════════════════════════════════════════════════════════════════
# FASE 4: RISULTATI BACKTEST
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 76)
print("  RISULTATI BACKTEST")
print("=" * 76)


def avg(lst):
    return statistics.mean(lst) if lst else 0


def print_comparison(name, cur_vals, nopa_vals, higher_better=True, pct=False):
    c = avg(cur_vals)
    n = avg(nopa_vals)
    if c != 0:
        delta_pct = (n - c) / abs(c) * 100
    else:
        delta_pct = 0
    arrow = "+" if delta_pct >= 0 else ""
    suffix = "%" if pct else ""
    better = (delta_pct > 0) == higher_better
    icon = ">>>" if better else "---"

    print(f"  {icon} {name:40s}  ATT={c:7.2f}{suffix}  NOPA={n:7.2f}{suffix}  "
          f"delta={arrow}{delta_pct:+.1f}%")
    return delta_pct, better


results = []

print("\n  --- Qualita' segnali ---")
results.append(print_comparison("Quality media segnali",     metrics_cur["quality"],   metrics_nopa["quality"]))
results.append(print_comparison("Conteggio A+/A medio",      metrics_cur["n_top"],     metrics_nopa["n_top"]))
results.append(print_comparison("Differenziale medio",       metrics_cur["avg_diff"],  metrics_nopa["avg_diff"]))

print("\n  --- Predittivita' ---")
results.append(print_comparison("Direzionalita' corretta (%)", metrics_cur["dir_correct"], metrics_nopa["dir_correct"], pct=True))

print("\n  --- Stabilita' ---")
results.append(print_comparison("Spread ranking (top-bottom)", metrics_cur["rank_spread"], metrics_nopa["rank_spread"]))


# ══════════════════════════════════════════════════════════════════════════════
# VERDETTO
# ══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 76)
print("  VERDETTO FINALE")
print("=" * 76)

wins_nopa = sum(1 for _, better in results if better)
wins_cur  = len(results) - wins_nopa

# Calcolo miglioramento/peggioramento globale
pct_changes = [d for d, _ in results]
avg_change = statistics.mean(pct_changes) if pct_changes else 0

print(f"\n  Metriche dove NO-PA vince : {wins_nopa}/{len(results)}")
print(f"  Metriche dove ATTUALE vince: {wins_cur}/{len(results)}")
print(f"\n  Variazione media complessiva: {avg_change:+.1f}%")

if avg_change > 5:
    print(f"\n  >>> NO-PA MIGLIORE: +{avg_change:.1f}% di miglioramento medio")
    print(f"  >>> Consiglio: valutare adozione pesi Vol30+COT30+C9=40")
elif avg_change < -5:
    print(f"\n  >>> ATTUALE MIGLIORE: {avg_change:.1f}% (peggiorerebbe senza PA)")
    print(f"  >>> Consiglio: mantenere sistema attuale PA25+Vol20+COT30+C9=25")
else:
    print(f"\n  >>> DIFFERENZA MARGINALE: {avg_change:+.1f}%")
    print(f"  >>> I due sistemi sono sostanzialmente equivalenti")

# Dettaglio predittivita'
dir_cur = avg(metrics_cur["dir_correct"]) * 100
dir_nopa = avg(metrics_nopa["dir_correct"]) * 100
print(f"\n  Predittivita' direzionale:")
print(f"    ATTUALE : {dir_cur:.1f}% (top3 salgono, bottom3 scendono)")
print(f"    NO-PA   : {dir_nopa:.1f}%")
print(f"    Delta   : {dir_nopa - dir_cur:+.1f}pp")

print("\n" + "=" * 76)
