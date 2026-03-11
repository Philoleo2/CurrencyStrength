"""
Simulazione: COT Percentile di Variazione vs COT Dato Secco
=============================================================
Confronta il sistema attuale (percentile del livello netto speculativo)
con un sistema basato sul percentile della VARIAZIONE settimanale
(flow momentum).

Ipotesi: il percentile della variazione cattura l'accelerazione dei flussi
istituzionali, un segnale più dinamico del semplice livello.

Approcci testati:
  A) ATTUALE: percentile(net_spec) + aggiustamento change
  B) VAR_PURA: percentile(delta_settimanale)
  C) BLEND: 40% percentile livello + 60% percentile variazione
  D) MULTI_VAR: percentile(delta 1w)*0.5 + percentile(delta 2w)*0.3 + percentile(delta 4w)*0.2
"""

import sys, statistics, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict

from data_fetcher import fetch_all_pairs, compute_currency_returns
from cot_data import load_cot_data, compute_cot_scores
from config import CURRENCIES, COT_PERCENTILE_LOOKBACK
import strength_engine as SE
import config as CFG


# ═══════════════════════════════════════════════════════════════════════════════
# COT SCORING VARIANTS
# ═══════════════════════════════════════════════════════════════════════════════

def _percentile_rank(value, array):
    """Percentile rank di value rispetto ad array (0-100)."""
    if len(array) == 0:
        return 50.0
    return float(np.sum(array <= value) / len(array)) * 100


def compute_cot_variation_scores(cot_df, mode="VAR_PURA"):
    """
    Calcola COT scores basati sul percentile della variazione.

    mode:
      VAR_PURA  - solo percentile del delta settimanale
      BLEND     - 40% percentile livello + 60% percentile variazione
      MULTI_VAR - media ponderata percentili delta 1w/2w/4w
    """
    scores = {}

    for ccy in CURRENCIES:
        subset = cot_df[cot_df["currency"] == ccy].sort_values("date")

        if len(subset) < 3:
            scores[ccy] = {"score": 50.0, "bias": "NEUTRAL", "freshness_days": 999}
            continue

        net_spec = subset["net_speculative"].values
        lookback = min(COT_PERCENTILE_LOOKBACK, len(net_spec))

        # Freshness
        latest_date = subset["date"].max()
        if pd.notna(latest_date):
            freshness_days = (dt.datetime.now() - pd.Timestamp(latest_date).to_pydatetime().replace(tzinfo=None)).days
        else:
            freshness_days = 999

        # ── Delta settimanali (1w, 2w, 4w) ──
        delta_1w = np.diff(net_spec)                     # variazione 1 settimana
        delta_2w = net_spec[2:] - net_spec[:-2]          # variazione 2 settimane
        delta_4w = net_spec[4:] - net_spec[:-4] if len(net_spec) >= 5 else delta_1w

        # ── Percentile del livello (come attuale) ──
        latest_level = net_spec[-1]
        level_lb = net_spec[-lookback:]
        pct_level = _percentile_rank(latest_level, level_lb)

        # ── Percentile della variazione 1w ──
        if len(delta_1w) >= 2:
            latest_d1 = delta_1w[-1]
            d1_lb = delta_1w[-min(lookback, len(delta_1w)):]
            pct_var_1w = _percentile_rank(latest_d1, d1_lb)
        else:
            pct_var_1w = 50.0

        # ── Percentile della variazione 2w ──
        if len(delta_2w) >= 2:
            latest_d2 = delta_2w[-1]
            d2_lb = delta_2w[-min(lookback, len(delta_2w)):]
            pct_var_2w = _percentile_rank(latest_d2, d2_lb)
        else:
            pct_var_2w = 50.0

        # ── Percentile della variazione 4w ──
        if len(delta_4w) >= 2:
            latest_d4 = delta_4w[-1]
            d4_lb = delta_4w[-min(lookback, len(delta_4w)):]
            pct_var_4w = _percentile_rank(latest_d4, d4_lb)
        else:
            pct_var_4w = 50.0

        # ── Score in base al mode ──
        if mode == "VAR_PURA":
            score = pct_var_1w
        elif mode == "BLEND":
            score = 0.40 * pct_level + 0.60 * pct_var_1w
        elif mode == "MULTI_VAR":
            score = 0.50 * pct_var_1w + 0.30 * pct_var_2w + 0.20 * pct_var_4w
        else:
            score = pct_var_1w

        score = float(np.clip(score, 0, 100))

        if score >= 60:
            bias = "BULLISH"
        elif score <= 40:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        scores[ccy] = {
            "score": round(score, 1),
            "bias": bias,
            "freshness_days": freshness_days,
            "net_spec_percentile": round(pct_level, 1),
            "var_1w_pct": round(pct_var_1w, 1),
            "var_2w_pct": round(pct_var_2w, 1),
            "var_4w_pct": round(pct_var_4w, 1),
            "extreme": None,
            "weekly_change": float(delta_1w[-1]) if len(delta_1w) > 0 else 0.0,
        }

    return scores


# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

ORIG_W = (0.25, 0.20, 0.30, 0.25)

def set_weights(pa, vol, ct, c9):
    CFG.WEIGHT_PRICE_ACTION = pa; SE.WEIGHT_PRICE_ACTION = pa
    CFG.WEIGHT_VOLUME = vol; SE.WEIGHT_VOLUME = vol
    CFG.WEIGHT_COT = ct; SE.WEIGHT_COT = ct
    CFG.WEIGHT_C9 = c9; SE.WEIGHT_C9 = c9


def backtest_cot_mode(all_pairs, cot_scores_dict, label, n_steps=35,
                      window=500, step=24, horizon=24):
    """Backtest rolling con un dato set di COT scores."""
    min_len = min(len(df) for df in all_pairs.values())
    results = {"quality": [], "n_top": [], "dir_correct": [], "grade_list": []}

    for si in range(n_steps):
        end = min_len - si * step
        start = end - window
        h_end = min(end + horizon, min_len)
        if start < 0 or h_end <= end:
            continue

        data = {p: df.iloc[start:end].copy() for p, df in all_pairs.items()}

        set_weights(*ORIG_W)
        try:
            analysis = SE.full_analysis(data, {}, cot_scores_dict)
            setups = SE.compute_trade_setups(
                composite=analysis["composite"],
                momentum=analysis["momentum"],
                classification=analysis["classification"],
                atr_context=analysis["atr_context"],
                cot_scores=cot_scores_dict,
                velocity_scores=analysis["velocity"],
                trend_structure=analysis["trend_structure"],
                strength_persistence=analysis["strength_persistence"],
                candle9=analysis.get("candle9", {}),
            )
        except Exception as e:
            continue
        finally:
            set_weights(*ORIG_W)

        # Quality & grades
        if setups:
            results["quality"].append(statistics.mean([s["quality_score"] for s in setups]))
            results["n_top"].append(sum(1 for s in setups if s["grade"] in ("A+", "A")))
            results["grade_list"].extend([s["grade"] for s in setups])
        else:
            results["quality"].append(0)
            results["n_top"].append(0)

        # Predittivita direzionale
        comp = {c: d["composite"] for c, d in analysis["composite"].items()}
        rank = sorted(comp.items(), key=lambda x: x[1], reverse=True)
        top3 = [r[0] for r in rank[:3]]
        bot3 = [r[0] for r in rank[-3:]]

        data_fut = {p: df.iloc[start:h_end].copy() for p, df in all_pairs.items()}
        try:
            rets = compute_currency_returns(data_fut, window=1)
            if rets.empty or len(rets) < 10:
                continue
            cum = (1 + rets).cumprod()
            t_idx = min(end - start - 1, len(cum) - 1)
            h_idx = min(h_end - start - 1, len(cum) - 1)
            if h_idx <= t_idx:
                continue
            ok = tot = 0
            for c in top3:
                if c in cum.columns:
                    tot += 1
                    if cum[c].iloc[h_idx] - cum[c].iloc[t_idx] > 0:
                        ok += 1
            for c in bot3:
                if c in cum.columns:
                    tot += 1
                    if cum[c].iloc[h_idx] - cum[c].iloc[t_idx] < 0:
                        ok += 1
            results["dir_correct"].append(ok / max(tot, 1))
        except Exception:
            pass

    return results


def summarize(results):
    """Metriche sintetiche."""
    q = results["quality"]
    d = results["dir_correct"]
    n = results["n_top"]
    grades = results["grade_list"]
    grade_dist = {g: grades.count(g) for g in ["A+", "A", "B", "C", "D"]}
    total_g = max(len(grades), 1)

    return {
        "q_avg": statistics.mean(q) if q else 0,
        "q_med": statistics.median(q) if q else 0,
        "dir_avg": statistics.mean(d) * 100 if d else 0,
        "dir_med": statistics.median(d) * 100 if d else 0,
        "n_top_avg": statistics.mean(n) if n else 0,
        "n_signals": len([x for x in n if x > 0]),
        "grade_dist": grade_dist,
        "grade_pct_top": round((grade_dist.get("A+", 0) + grade_dist.get("A", 0)) / total_g * 100, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 76)
print("  SIMULAZIONE: COT Percentile Variazione vs Dato Secco")
print("  Pesi: PA=0.25  Vol=0.20  COT=0.30  C9=0.25 (invariati)")
print("=" * 76)

# ── Fetch ──
print("\n[1/4] Fetch dati H1 + COT ...", flush=True)
all_pairs = fetch_all_pairs("H1")
if not all_pairs:
    print("ERRORE: no pair data"); sys.exit(1)
print(f"       {len(all_pairs)} coppie, {min(len(df) for df in all_pairs.values())} barre")

cot_df = load_cot_data()
print(f"       COT: {len(cot_df)} righe, {cot_df['currency'].nunique()} valute")

# ── Prepara le 4 varianti di COT scores ──
print("\n[2/4] Calcolo 4 varianti COT scores ...", flush=True)

# A) ATTUALE - dato secco (percentile livello + aggiustamento)
cot_attuale = compute_cot_scores(cot_df)

# B) VAR_PURA - solo percentile della variazione settimanale
cot_var_pura = compute_cot_variation_scores(cot_df, mode="VAR_PURA")

# C) BLEND - 40% livello + 60% variazione
cot_blend = compute_cot_variation_scores(cot_df, mode="BLEND")

# D) MULTI_VAR - percentile multi-timeframe (1w/2w/4w)
cot_multi = compute_cot_variation_scores(cot_df, mode="MULTI_VAR")

# Mostra differenze per ogni valuta
print(f"\n  {'CCY':>4}  {'ATTUALE':>8}  {'VAR_PURA':>9}  {'BLEND':>8}  {'MULTI_VAR':>10}  {'Bias_att':>9}  {'Bias_var':>9}")
print(f"  {'─'*4}  {'─'*8}  {'─'*9}  {'─'*8}  {'─'*10}  {'─'*9}  {'─'*9}")
for ccy in CURRENCIES:
    sa = cot_attuale[ccy]["score"]
    sv = cot_var_pura[ccy]["score"]
    sb = cot_blend[ccy]["score"]
    sm = cot_multi[ccy]["score"]
    ba = cot_attuale[ccy]["bias"]
    bv = cot_var_pura[ccy]["bias"]
    print(f"  {ccy:>4}  {sa:8.1f}  {sv:9.1f}  {sb:8.1f}  {sm:10.1f}  {ba:>9}  {bv:>9}")

# ── Backtest ──
print("\n[3/4] Backtest rolling (35 step × 4 varianti) ...", flush=True)

modes = [
    ("A) ATTUALE (livello)",  cot_attuale),
    ("B) VAR_PURA (delta 1w)", cot_var_pura),
    ("C) BLEND (40L+60V)",    cot_blend),
    ("D) MULTI_VAR (1w/2w/4w)", cot_multi),
]

all_summaries = {}
for label, cot_s in modes:
    print(f"  → {label} ...", end=" ", flush=True)
    res = backtest_cot_mode(all_pairs, cot_s, label)
    s = summarize(res)
    all_summaries[label] = s
    print(f"Dir={s['dir_avg']:.1f}%  Q={s['q_avg']:.1f}  A+/A={s['n_top_avg']:.2f}")

# ── Report finale ──
print("\n" + "=" * 76)
print("  RISULTATI COMPARATIVI")
print("=" * 76)

print(f"\n  {'Variante':<28}  {'Dir%':>6}  {'Dir_Med':>7}  {'Q_avg':>6}  {'Q_med':>6}  "
      f"{'A+/A':>5}  {'%A+/A':>6}  {'Sig':>4}")
print(f"  {'─'*28}  {'─'*6}  {'─'*7}  {'─'*6}  {'─'*6}  {'─'*5}  {'─'*6}  {'─'*4}")

best_dir = max(s["dir_avg"] for s in all_summaries.values())
for label, s in all_summaries.items():
    marker = " ◀ BEST DIR" if s["dir_avg"] == best_dir else ""
    print(f"  {label:<28}  {s['dir_avg']:6.1f}  {s['dir_med']:7.1f}  {s['q_avg']:6.1f}  "
          f"{s['q_med']:6.1f}  {s['n_top_avg']:5.2f}  {s['grade_pct_top']:5.1f}%  "
          f"{s['n_signals']:4d}{marker}")

# ── Delta vs attuale ──
att = all_summaries[list(all_summaries.keys())[0]]
print(f"\n  {'Variante':<28}  {'ΔDir%':>7}  {'ΔQ_avg':>7}  {'ΔA+/A':>7}  Verdetto")
print(f"  {'─'*28}  {'─'*7}  {'─'*7}  {'─'*7}  ────────")
for label, s in all_summaries.items():
    dd = s["dir_avg"] - att["dir_avg"]
    dq = s["q_avg"] - att["q_avg"]
    dn = s["n_top_avg"] - att["n_top_avg"]
    if dd > 1.0:
        verdict = "✅ MIGLIORE"
    elif dd > 0:
        verdict = "≈ MARGINALE"
    elif dd < -1.0:
        verdict = "❌ PEGGIORE"
    else:
        verdict = "≈ PARI"
    if label == list(all_summaries.keys())[0]:
        verdict = "BASELINE"
    print(f"  {label:<28}  {dd:+7.1f}  {dq:+7.1f}  {dn:+7.2f}  {verdict}")

# ── Grade distribution ──
print(f"\n  Distribuzione Gradi:")
print(f"  {'Variante':<28}  {'A+':>4}  {'A':>4}  {'B':>4}  {'C':>4}  {'D':>4}")
print(f"  {'─'*28}  {'─'*4}  {'─'*4}  {'─'*4}  {'─'*4}  {'─'*4}")
for label, s in all_summaries.items():
    gd = s["grade_dist"]
    print(f"  {label:<28}  {gd.get('A+',0):4d}  {gd.get('A',0):4d}  "
          f"{gd.get('B',0):4d}  {gd.get('C',0):4d}  {gd.get('D',0):4d}")

print("\n" + "=" * 76)
print("DONE")
