"""
Analisi informativa COT: quale scoring differenzia di piu'?
=============================================================
Per ogni settimana COT (61 report), calcola scores con ogni metodo e misura:
  1. Dispersione (std) degli scores tra valute → piu' alta = piu' informativo
  2. Variabilita' nel tempo (delta week-to-week) → piu' alta = piu' reattivo
  3. Entropia → distribuzione piu' uniforme vs concentrata
  4. Concordanza direzionale con returns reali (sulle settimane coperte da H1)

Se un metodo produce scores tutti uguali o tutti estremi, non aggiunge info.
Se produce scores ben distribuiti e reattivi, alimenta meglio il composito.
"""

import sys, statistics, numpy as np, pandas as pd, datetime as dt
from collections import defaultdict
from scipy import stats as sp_stats

from data_fetcher import fetch_all_pairs, compute_currency_returns
from cot_data import load_cot_data
from config import CURRENCIES, COT_PERCENTILE_LOOKBACK

# ═══════════════════════════════════════════════════════════════════════════════
#  SCORING FUNCTIONS (stesse di prima)
# ═══════════════════════════════════════════════════════════════════════════════

def _prank(v, a):
    return float(np.sum(a <= v) / len(a)) * 100 if len(a) > 0 else 50.0


def score_attuale(ns_dict):
    sc = {}
    for ccy in CURRENCIES:
        ns = ns_dict.get(ccy)
        if ns is None or len(ns) < 2:
            sc[ccy] = 50.0; continue
        lb = ns[-COT_PERCENTILE_LOOKBACK:] if len(ns) >= COT_PERCENTILE_LOOKBACK else ns
        pct = _prank(ns[-1], lb)
        wk = float(ns[-1] - ns[-2])
        adj = 0.0
        std = np.std(lb)
        if std > 0: adj = np.clip(wk / std, -2, 2) * 10
        sc[ccy] = float(np.clip(pct + adj, 0, 100))
    return sc


def score_var_pura(ns_dict):
    sc = {}
    for ccy in CURRENCIES:
        ns = ns_dict.get(ccy)
        if ns is None or len(ns) < 3:
            sc[ccy] = 50.0; continue
        d1 = np.diff(ns)
        lb = min(COT_PERCENTILE_LOOKBACK, len(d1))
        sc[ccy] = _prank(d1[-1], d1[-lb:])
    return sc


def score_blend(ns_dict):
    sc = {}
    for ccy in CURRENCIES:
        ns = ns_dict.get(ccy)
        if ns is None or len(ns) < 3:
            sc[ccy] = 50.0; continue
        lb_n = min(COT_PERCENTILE_LOOKBACK, len(ns))
        pct_level = _prank(ns[-1], ns[-lb_n:])
        d1 = np.diff(ns)
        lb_d = min(COT_PERCENTILE_LOOKBACK, len(d1))
        pct_var = _prank(d1[-1], d1[-lb_d:])
        sc[ccy] = float(np.clip(0.40 * pct_level + 0.60 * pct_var, 0, 100))
    return sc


def score_multi_var(ns_dict):
    sc = {}
    for ccy in CURRENCIES:
        ns = ns_dict.get(ccy)
        if ns is None or len(ns) < 5:
            sc[ccy] = 50.0; continue
        d1 = np.diff(ns)
        d2 = ns[2:] - ns[:-2]
        d4 = ns[4:] - ns[:-4]
        lb = COT_PERCENTILE_LOOKBACK
        p1 = _prank(d1[-1], d1[-min(lb, len(d1)):]) if len(d1) >= 2 else 50
        p2 = _prank(d2[-1], d2[-min(lb, len(d2)):]) if len(d2) >= 2 else 50
        p4 = _prank(d4[-1], d4[-min(lb, len(d4)):]) if len(d4) >= 2 else 50
        sc[ccy] = float(np.clip(0.50 * p1 + 0.30 * p2 + 0.20 * p4, 0, 100))
    return sc


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 76)
print("  ANALISI INFORMATIVA COT: quale scoring differenzia meglio?")
print("=" * 76)

# ── Carica dati ──
print("\n[1/3] Caricamento dati ...", flush=True)
cot_df = load_cot_data()
print(f"       COT: {len(cot_df)} righe, {cot_df['currency'].nunique()} valute")

# Serie per valuta
cot_series = {}
for ccy in CURRENCIES:
    sub = cot_df[cot_df["currency"] == ccy].sort_values("date")
    if not sub.empty:
        cot_series[ccy] = sub[["date", "net_speculative"]].reset_index(drop=True)
    else:
        cot_series[ccy] = pd.DataFrame(columns=["date", "net_speculative"])

# Date COT uniche ordinate
all_dates = sorted(cot_df["date"].unique())
print(f"       {len(all_dates)} date COT da {pd.Timestamp(all_dates[0]).date()} "
      f"a {pd.Timestamp(all_dates[-1]).date()}")

# ── Fetch H1 per la verifica sui ritorni ──
all_pairs = fetch_all_pairs("H1")
min_len = min(len(df) for df in all_pairs.values()) if all_pairs else 0
print(f"       H1: {min_len} barre")

# Calcola ritorni cumulati per la verifica
cum_h1 = None
h1_dates = None
if all_pairs:
    rets = compute_currency_returns(all_pairs, window=1)
    if not rets.empty:
        cum_h1 = (1 + rets).cumprod()
        ref_p = list(all_pairs.values())[0]
        if "time" in ref_p.columns:
            h1_dates = pd.to_datetime(ref_p["time"]).dt.tz_localize(None).values[:len(cum_h1)]
        else:
            h1_dates = pd.to_datetime(ref_p.index).tz_localize(None).values[:len(cum_h1)]

# ── Metodi di scoring ──
methods = {
    "ATTUALE":    score_attuale,
    "VAR_PURA":   score_var_pura,
    "BLEND":      score_blend,
    "MULTI_VAR":  score_multi_var,
}

# ── Per ogni settimana, calcola scores con ogni metodo ──
print("\n[2/3] Calcolo scores settimana per settimana ...", flush=True)

# Struttura: {method: {week_idx: {ccy: score}}}
weekly_scores = {m: {} for m in methods}
min_weeks = 8  # servono almeno 8 settimane per delta_4w

for wi, cot_date in enumerate(all_dates):
    if wi < min_weeks:
        continue

    # Subset COT fino a questa data
    ns_dict = {}
    for ccy in CURRENCIES:
        cs = cot_series[ccy]
        if not cs.empty:
            mask = cs["date"] <= cot_date
            vals = cs[mask]["net_speculative"].values
            if len(vals) > 0:
                ns_dict[ccy] = vals

    for method_name, fn in methods.items():
        weekly_scores[method_name][wi] = fn(ns_dict)

# ═══════════════════════════════════════════════════════════════════════════════
#  METRICHE INFORMATIVE
# ═══════════════════════════════════════════════════════════════════════════════

print("\n[3/3] Calcolo metriche informative ...\n", flush=True)

# 1. DISPERSIONE: std degli scores tra valute per settimana
# 2. RANGE: max - min tra valute per settimana
# 3. VARIABILITÀ: cambio settimanale medio degli scores
# 4. % allExtreme: quante valute hanno score < 10 o > 90

stats_summary = {}

for method_name in methods:
    ws = weekly_scores[method_name]
    weeks = sorted(ws.keys())

    dispersions = []
    ranges = []
    extreme_pcts = []
    deltas = []

    prev_scores = None
    for wi in weeks:
        scores = ws[wi]
        vals = [scores.get(c, 50) for c in CURRENCIES]

        dispersions.append(np.std(vals))
        ranges.append(max(vals) - min(vals))

        n_extreme = sum(1 for v in vals if v <= 10 or v >= 90)
        extreme_pcts.append(n_extreme / len(vals) * 100)

        if prev_scores is not None:
            delta = [abs(scores.get(c, 50) - prev_scores.get(c, 50)) for c in CURRENCIES]
            deltas.append(statistics.mean(delta))

        prev_scores = scores

    stats_summary[method_name] = {
        "disp_avg": statistics.mean(dispersions),
        "disp_med": statistics.median(dispersions),
        "range_avg": statistics.mean(ranges),
        "range_med": statistics.median(ranges),
        "extreme_pct": statistics.mean(extreme_pcts),
        "delta_avg": statistics.mean(deltas) if deltas else 0,
        "delta_med": statistics.median(deltas) if deltas else 0,
        "n_weeks": len(weeks),
    }

# ── Report dispersione ──
print("=" * 76)
print("  1. DISPERSIONE SCORES TRA VALUTE (per settimana)")
print("     → Più alta = il metodo differenzia meglio le valute")
print("=" * 76)

print(f"\n  {'Metodo':<12}  {'Disp_avg':>8}  {'Disp_med':>8}  {'Range_avg':>9}  "
      f"{'Range_med':>9}  {'%Estremi':>8}")
print(f"  {'─'*12}  {'─'*8}  {'─'*8}  {'─'*9}  {'─'*9}  {'─'*8}")
for m, s in stats_summary.items():
    print(f"  {m:<12}  {s['disp_avg']:8.1f}  {s['disp_med']:8.1f}  "
          f"{s['range_avg']:9.1f}  {s['range_med']:9.1f}  {s['extreme_pct']:7.1f}%")

# ── Report variabilita' ──
print(f"\n{'=' * 76}")
print("  2. VARIABILITA' NEL TEMPO (reattività settimanale)")
print("     → Più alta = il metodo reagisce di più ai nuovi dati COT")
print("=" * 76)

print(f"\n  {'Metodo':<12}  {'Delta_avg':>9}  {'Delta_med':>9}  Note")
print(f"  {'─'*12}  {'─'*9}  {'─'*9}  ────")
for m, s in stats_summary.items():
    if s["delta_avg"] > 5:
        note = "REATTIVO"
    elif s["delta_avg"] > 2:
        note = "MODERATO"
    else:
        note = "STATICO"
    print(f"  {m:<12}  {s['delta_avg']:9.2f}  {s['delta_med']:9.2f}  {note}")

# ── Profilo settimanale dettagliato ──
print(f"\n{'=' * 76}")
print("  3. PROFILO SCORES PER VALUTA (ultimi 10 report)")
print("=" * 76)

for method_name in methods:
    ws = weekly_scores[method_name]
    weeks = sorted(ws.keys())[-10:]
    print(f"\n  [{method_name}]")
    print(f"  {'Week':>4}", end="")
    for ccy in CURRENCIES:
        print(f"  {ccy:>5}", end="")
    print(f"  {'Std':>5}  {'Range':>5}")

    for wi in weeks:
        scores = ws[wi]
        vals = [scores.get(c, 50) for c in CURRENCIES]
        date_str = pd.Timestamp(all_dates[wi]).strftime("%m/%d")
        print(f"  {date_str:>5}", end="")
        for ccy in CURRENCIES:
            v = scores.get(ccy, 50)
            print(f"  {v:5.1f}", end="")
        print(f"  {np.std(vals):5.1f}  {max(vals)-min(vals):5.1f}")

# ── Verifica predittiva su periodo H1 disponibile ──
if cum_h1 is not None and h1_dates is not None:
    print(f"\n{'=' * 76}")
    print("  4. VERIFICA PREDITTIVA (su settimane coperte da dati H1)")
    print("     → Per ogni report COT nel range H1, verifica ritorni 120 barre dopo")
    print("=" * 76)

    h1_start = h1_dates[0]
    h1_end = h1_dates[-1]
    HORIZON = 120  # 120 barre H1 = 5 giorni

    pred_results = {m: {"correct": 0, "total": 0, "rank_corrs": []} for m in methods}

    for wi, cot_date in enumerate(all_dates):
        if wi < min_weeks:
            continue
        cot_ts = pd.Timestamp(cot_date)
        if cot_ts < pd.Timestamp(h1_start) or cot_ts > pd.Timestamp(h1_end):
            continue

        # Trova barra H1 dopo la data COT
        diffs = np.abs(h1_dates - np.datetime64(cot_ts))
        bar_start = int(np.argmin(diffs))
        bar_end = bar_start + HORIZON
        if bar_end >= len(cum_h1):
            continue

        # Ritorni futuri
        fut_rets = {}
        for ccy in CURRENCIES:
            if ccy in cum_h1.columns:
                r = cum_h1[ccy].iloc[bar_end] / cum_h1[ccy].iloc[bar_start] - 1
                if not np.isnan(r):
                    fut_rets[ccy] = r
        if len(fut_rets) < 4:
            continue

        valid_ccys = list(fut_rets.keys())

        for method_name in methods:
            if wi not in weekly_scores[method_name]:
                continue
            scores = weekly_scores[method_name][wi]
            cot_vals = [scores.get(c, 50) for c in valid_ccys]
            ret_vals = [fut_rets[c] for c in valid_ccys]

            # Spearman correlation
            if len(set(cot_vals)) > 1 and len(set(ret_vals)) > 1:
                corr, _ = sp_stats.spearmanr(cot_vals, ret_vals)
                pred_results[method_name]["rank_corrs"].append(corr)

            # Direzionalita' top3/bot3
            ranked = sorted(valid_ccys, key=lambda c: scores.get(c, 50), reverse=True)
            top3 = ranked[:3]
            bot3 = ranked[-3:]
            ok = 0
            for c in top3:
                if fut_rets[c] > 0: ok += 1
            for c in bot3:
                if fut_rets[c] < 0: ok += 1
            pred_results[method_name]["total"] += 1
            pred_results[method_name]["correct"] += ok

    print(f"\n  {'Metodo':<12}  {'Dir%':>6}  {'RankCorr':>8}  {'N_weeks':>7}")
    print(f"  {'─'*12}  {'─'*6}  {'─'*8}  {'─'*7}")
    for m, pr in pred_results.items():
        d = pr["correct"] / max(pr["total"], 1) * 100 / 6 * 100  # normalize
        # More precise: correct / (total * 6) since 6 predictions per week
        d2 = pr["correct"] / max(pr["total"] * 6, 1) * 100
        rc = statistics.mean(pr["rank_corrs"]) if pr["rank_corrs"] else 0
        n = pr["total"]
        print(f"  {m:<12}  {d2:6.1f}  {rc:+8.3f}  {n:7d}")

# ── Verdetto finale ──
print(f"\n{'=' * 76}")
print("  VERDETTO FINALE")
print("=" * 76)

att = stats_summary["ATTUALE"]
print()
for m, s in stats_summary.items():
    dd = s["disp_avg"] - att["disp_avg"]
    dr = s["range_avg"] - att["range_avg"]
    dv = s["delta_avg"] - att["delta_avg"]
    de = s["extreme_pct"] - att["extreme_pct"]

    if m == "ATTUALE":
        print(f"  {m:<12}: BASELINE (disp={s['disp_avg']:.1f}, delta={s['delta_avg']:.2f}, "
              f"extreme={s['extreme_pct']:.1f}%)")
        continue

    pros = []
    cons = []
    if dd > 2: pros.append(f"dispersione +{dd:.1f}")
    elif dd < -2: cons.append(f"dispersione {dd:.1f}")
    if dv > 2: pros.append(f"reattivita' +{dv:.1f}")
    elif dv < -2: cons.append(f"reattivita' {dv:.1f}")
    if de < -5: pros.append(f"meno estremi ({de:+.1f}%)")
    elif de > 5: cons.append(f"piu' estremi ({de:+.1f}%)")

    print(f"  {m:<12}: ", end="")
    if pros and not cons:
        print(f"✅ MIGLIORE — {', '.join(pros)}")
    elif pros and cons:
        print(f"↗ MISTO — Pro: {', '.join(pros)} | Contro: {', '.join(cons)}")
    elif cons:
        print(f"❌ PEGGIORE — {', '.join(cons)}")
    else:
        print(f"≈ EQUIVALENTE (differenze < 2 punti)")

print()
print("=" * 76)
print("DONE")
