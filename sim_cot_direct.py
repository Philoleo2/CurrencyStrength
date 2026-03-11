"""
Test diretto: COT Percentile Variazione vs Dato Secco
======================================================
Per ogni settimana COT (61 report):
  1. Calcola COT scores con ciascun metodo
  2. Rank valute per COT score
  3. Verifica se top-3 valute hanno performato meglio di bottom-3
     nei 5 giorni successivi al report
  4. Misura correlazione rank COT → rank ritorni

Questo isola il segnale COT dagli altri componenti (PA, Volume, C9)
e misura la pura capacità predittiva di ogni approccio.
"""

import sys, statistics, numpy as np, pandas as pd, datetime as dt
from scipy import stats as scipy_stats

from data_fetcher import fetch_all_pairs, compute_currency_returns
from cot_data import load_cot_data
from config import CURRENCIES, COT_PERCENTILE_LOOKBACK

# ═══════════════════════════════════════════════════════════════════════════════
#  COT SCORING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def _prank(v, a):
    return float(np.sum(a <= v) / len(a)) * 100 if len(a) > 0 else 50.0


def score_attuale(net_specs: dict) -> dict:
    """
    ATTUALE: percentile del livello + aggiustamento change (replica).
    net_specs: {ccy: np.array di net_spec fino a questa data}
    """
    scores = {}
    for ccy in CURRENCIES:
        ns = net_specs.get(ccy)
        if ns is None or len(ns) < 2:
            scores[ccy] = 50.0; continue
        lb = ns[-COT_PERCENTILE_LOOKBACK:] if len(ns) >= COT_PERCENTILE_LOOKBACK else ns
        pct = _prank(ns[-1], lb)
        wk = float(ns[-1] - ns[-2])
        adj = 0.0
        std = np.std(lb)
        if std > 0:
            adj = np.clip(wk / std, -2, 2) * 10
        scores[ccy] = float(np.clip(pct + adj, 0, 100))
    return scores


def score_var_pura(net_specs: dict) -> dict:
    """VAR_PURA: percentile della variazione settimanale."""
    scores = {}
    for ccy in CURRENCIES:
        ns = net_specs.get(ccy)
        if ns is None or len(ns) < 3:
            scores[ccy] = 50.0; continue
        d1 = np.diff(ns)
        lb = min(COT_PERCENTILE_LOOKBACK, len(d1))
        scores[ccy] = _prank(d1[-1], d1[-lb:])
    return scores


def score_blend(net_specs: dict) -> dict:
    """BLEND: 40% percentile livello + 60% percentile variazione."""
    scores = {}
    for ccy in CURRENCIES:
        ns = net_specs.get(ccy)
        if ns is None or len(ns) < 3:
            scores[ccy] = 50.0; continue
        lb_n = min(COT_PERCENTILE_LOOKBACK, len(ns))
        pct_level = _prank(ns[-1], ns[-lb_n:])
        d1 = np.diff(ns)
        lb_d = min(COT_PERCENTILE_LOOKBACK, len(d1))
        pct_var = _prank(d1[-1], d1[-lb_d:])
        scores[ccy] = float(np.clip(0.40 * pct_level + 0.60 * pct_var, 0, 100))
    return scores


def score_multi_var(net_specs: dict) -> dict:
    """MULTI_VAR: 50% delta_1w + 30% delta_2w + 20% delta_4w."""
    scores = {}
    for ccy in CURRENCIES:
        ns = net_specs.get(ccy)
        if ns is None or len(ns) < 5:
            scores[ccy] = 50.0; continue
        d1 = np.diff(ns)
        d2 = ns[2:] - ns[:-2]
        d4 = ns[4:] - ns[:-4]
        lb = COT_PERCENTILE_LOOKBACK
        p1 = _prank(d1[-1], d1[-min(lb, len(d1)):]) if len(d1) >= 2 else 50
        p2 = _prank(d2[-1], d2[-min(lb, len(d2)):]) if len(d2) >= 2 else 50
        p4 = _prank(d4[-1], d4[-min(lb, len(d4)):]) if len(d4) >= 2 else 50
        scores[ccy] = float(np.clip(0.50 * p1 + 0.30 * p2 + 0.20 * p4, 0, 100))
    return scores


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 76)
print("  TEST DIRETTO: capacita' predittiva COT per metodo di scoring")
print("  Per ogni report settimanale → verifica ritorni 5gg dopo")
print("=" * 76)

# ── Fetch ──
print("\n[1/3] Fetch dati ...", flush=True)

# Usa H4 per avere piu' copertura temporale
all_pairs_h4 = fetch_all_pairs("H4")
if not all_pairs_h4:
    print("ERRORE H4"); sys.exit(1)
min_len_h4 = min(len(df) for df in all_pairs_h4.values())
print(f"       H4: {len(all_pairs_h4)} coppie, {min_len_h4} barre")

# Anche H1 per confronto
all_pairs_h1 = fetch_all_pairs("H1")
min_len_h1 = min(len(df) for df in all_pairs_h1.values()) if all_pairs_h1 else 0
print(f"       H1: {len(all_pairs_h1)} coppie, {min_len_h1} barre")

cot_df = load_cot_data()
print(f"       COT: {len(cot_df)} righe")

# Costruisci timeline per coppia e mappa date
ref_pair_key = list(all_pairs_h4.keys())[0]
ref_h4 = all_pairs_h4[ref_pair_key]
if "time" in ref_h4.columns:
    h4_dates = pd.to_datetime(ref_h4["time"]).reset_index(drop=True)
else:
    h4_dates = pd.Series(pd.to_datetime(ref_h4.index)).reset_index(drop=True)

# Normalizza timezone
h4_dates = h4_dates.dt.tz_localize(None) if h4_dates.dt.tz is not None else h4_dates

print(f"       H4 range: {h4_dates.iloc[0].date()} → {h4_dates.iloc[-1].date()}")

# ── Per ogni valuta: serie storica net_speculative e date COT ──
cot_series = {}
cot_dates_all = set()
for ccy in CURRENCIES:
    sub = cot_df[cot_df["currency"] == ccy].sort_values("date")
    if not sub.empty:
        cot_series[ccy] = sub[["date", "net_speculative"]].reset_index(drop=True)
        cot_dates_all.update(sub["date"].tolist())
    else:
        cot_series[ccy] = pd.DataFrame(columns=["date", "net_speculative"])

# Date COT ordinate (solo quelle nel range H4)
cot_dates = sorted(cot_dates_all)
cot_dates_in_range = [d for d in cot_dates
                      if pd.Timestamp(d) >= h4_dates.iloc[0]
                      and pd.Timestamp(d) <= h4_dates.iloc[-1]]
print(f"       COT date nel range H4: {len(cot_dates_in_range)}")

# ── Calcola ritorni valutari su H4 ──
print("\n[2/3] Calcolo ritorni e test predittivi ...", flush=True)

# Converto H4 a ritorni per valuta
rets_h4 = compute_currency_returns(all_pairs_h4, window=1)
if rets_h4.empty:
    print("ERRORE: nessun ritorno"); sys.exit(1)

# Assicurati che l'indice sia datetime
if not isinstance(rets_h4.index, pd.DatetimeIndex):
    rets_h4.index = h4_dates[:len(rets_h4)]

cum_h4 = (1 + rets_h4).cumprod()
print(f"       Cumulata: {len(cum_h4)} barre, {len(cum_h4.columns)} valute")

# ── Funzioni di scoring ──
scoring_methods = {
    "A) ATTUALE":    score_attuale,
    "B) VAR_PURA":   score_var_pura,
    "C) BLEND":      score_blend,
    "D) MULTI_VAR":  score_multi_var,
}

HORIZON_BARS_H4 = 30  # 30 barre H4 = 5 giorni di trading

results = {name: {"dir_correct": [], "rank_corr": [], "spread": [],
                   "top3_ret": [], "bot3_ret": []}
           for name in scoring_methods}

# ── Per ogni data COT, calcola scores e verifica predittivita' ──
n_tested = 0
skip_first = 8  # servono almeno 8 report per calcolare delta_4w con lookback

for i, cot_date in enumerate(cot_dates):
    cot_ts = pd.Timestamp(cot_date)

    # Trova la barra H4 piu' vicina dopo la data COT
    mask_after = h4_dates >= cot_ts
    if mask_after.sum() == 0:
        continue
    bar_idx = mask_after.idxmax() if hasattr(mask_after, "idxmax") else mask_after.values.argmax()
    if isinstance(bar_idx, (int, np.integer)):
        start_bar = int(bar_idx)
    else:
        start_bar = h4_dates.index.get_loc(bar_idx)

    end_bar = start_bar + HORIZON_BARS_H4
    if end_bar >= len(cum_h4):
        continue

    # Servono abbastanza report precedenti per i metodi di variazione
    if i < skip_first:
        continue

    # Prepara subset COT disponibile fino a questa data
    net_specs = {}
    for ccy in CURRENCIES:
        cs = cot_series.get(ccy)
        if cs is not None and not cs.empty:
            mask = cs["date"] <= cot_date
            vals = cs[mask]["net_speculative"].values
            if len(vals) > 0:
                net_specs[ccy] = vals

    # Calcola ritorni futuri per ogni valuta
    future_rets = {}
    valid_ccys = []
    for ccy in CURRENCIES:
        if ccy in cum_h4.columns and start_bar < len(cum_h4) and end_bar < len(cum_h4):
            ret = cum_h4[ccy].iloc[end_bar] / cum_h4[ccy].iloc[start_bar] - 1
            if not np.isnan(ret):
                future_rets[ccy] = ret
                valid_ccys.append(ccy)

    if len(valid_ccys) < 4:
        continue

    n_tested += 1

    # Per ogni metodo di scoring
    for method_name, score_fn in scoring_methods.items():
        scores = score_fn(net_specs)

        # Rank per score COT (alto = bullish)
        ranked = sorted(valid_ccys, key=lambda c: scores.get(c, 50), reverse=True)
        top3 = ranked[:3]
        bot3 = ranked[-3:]

        # Direzionalita': top3 devono salire, bot3 scendere
        ok = 0
        tot = 0
        for c in top3:
            tot += 1
            if future_rets[c] > 0:
                ok += 1
        for c in bot3:
            tot += 1
            if future_rets[c] < 0:
                ok += 1
        dir_correct = ok / max(tot, 1)
        results[method_name]["dir_correct"].append(dir_correct)

        # Correlazione rank COT vs rank ritorni
        cot_ranks = [scores.get(c, 50) for c in valid_ccys]
        ret_vals = [future_rets[c] for c in valid_ccys]
        if len(set(cot_ranks)) > 1 and len(set(ret_vals)) > 1:
            corr, pval = scipy_stats.spearmanr(cot_ranks, ret_vals)
            results[method_name]["rank_corr"].append(corr)

        # Spread COT
        all_scores = [scores.get(c, 50) for c in valid_ccys]
        results[method_name]["spread"].append(max(all_scores) - min(all_scores))

        # Ritorni medi top3 e bot3
        results[method_name]["top3_ret"].append(
            statistics.mean([future_rets[c] for c in top3]) * 100)
        results[method_name]["bot3_ret"].append(
            statistics.mean([future_rets[c] for c in bot3]) * 100)


# ── Report ──
print(f"\n       Settimane testate: {n_tested}")

print("\n" + "=" * 76)
print("  RISULTATI: CAPACITA' PREDITTIVA PURA DEL COT")
print("  (isolata dagli altri componenti)")
print("=" * 76)

print(f"\n  {'Metodo':<16}  {'Dir%':>6}  {'RankCorr':>8}  {'Spread':>7}  "
      f"{'Top3_ret%':>9}  {'Bot3_ret%':>9}  {'LS_ret%':>7}")
print(f"  {'─'*16}  {'─'*6}  {'─'*8}  {'─'*7}  {'─'*9}  {'─'*9}  {'─'*7}")

best_dir = 0
for name, r in results.items():
    d = statistics.mean(r["dir_correct"]) * 100 if r["dir_correct"] else 0
    rc = statistics.mean(r["rank_corr"]) if r["rank_corr"] else 0
    sp = statistics.mean(r["spread"]) if r["spread"] else 0
    t3 = statistics.mean(r["top3_ret"]) if r["top3_ret"] else 0
    b3 = statistics.mean(r["bot3_ret"]) if r["bot3_ret"] else 0
    ls = t3 - b3  # Long/short spread
    if d > best_dir:
        best_dir = d
    marker = ""  # assign later
    results[name]["_summary"] = {"dir": d, "rc": rc, "sp": sp, "t3": t3, "b3": b3, "ls": ls}

for name, r in results.items():
    s = r["_summary"]
    marker = " ◀ BEST" if s["dir"] == best_dir else ""
    print(f"  {name:<16}  {s['dir']:6.1f}  {s['rc']:+8.3f}  {s['sp']:7.1f}  "
          f"{s['t3']:+9.3f}  {s['b3']:+9.3f}  {s['ls']:+7.3f}{marker}")

# Delta
att_s = results["A) ATTUALE"]["_summary"]
print(f"\n  {'Metodo':<16}  {'ΔDir%':>7}  {'ΔRankCorr':>9}  {'ΔSpread':>8}  {'ΔLS_ret':>8}  Verdetto")
print(f"  {'─'*16}  {'─'*7}  {'─'*9}  {'─'*8}  {'─'*8}  ────────")
for name, r in results.items():
    s = r["_summary"]
    dd = s["dir"] - att_s["dir"]
    drc = s["rc"] - att_s["rc"]
    dsp = s["sp"] - att_s["sp"]
    dls = s["ls"] - att_s["ls"]
    if name == "A) ATTUALE":
        v = "BASELINE"
    elif dd > 3 and drc > 0.02:
        v = "✅ MIGLIORE"
    elif dd > 1 or (dd >= 0 and drc > 0.03):
        v = "↗ PROMETTENTE"
    elif dd > -1 and abs(drc) < 0.02:
        v = "≈ PARI"
    elif dd < -3:
        v = "❌ PEGGIORE"
    else:
        v = "↘ MISTO"
    print(f"  {name:<16}  {dd:+7.1f}  {drc:+9.3f}  {dsp:+8.1f}  {dls:+8.3f}  {v}")

# ── Dettaglio settimana per settimana per il miglior metodo ──
alt_names = [n for n in results if n != "A) ATTUALE"]
best_alt = max(alt_names, key=lambda n: results[n]["_summary"]["dir"])

print(f"\n  Dettaglio settimana per settimana: ATTUALE vs {best_alt}")
print(f"  {'Week':>4}  {'Dir_ATT':>7}  {'Dir_ALT':>7}  {'Diff':>6}")
print(f"  {'─'*4}  {'─'*7}  {'─'*7}  {'─'*6}")
att_dirs = results["A) ATTUALE"]["dir_correct"]
alt_dirs = results[best_alt]["dir_correct"]
att_wins = alt_wins = ties = 0
for w in range(min(len(att_dirs), len(alt_dirs))):
    a = att_dirs[w] * 100
    b = alt_dirs[w] * 100
    diff = b - a
    if diff > 0: alt_wins += 1
    elif diff < 0: att_wins += 1
    else: ties += 1
    marker = "  ◀ VAR" if diff > 5 else ("  ◀ ATT" if diff < -5 else "")
    print(f"  {w+1:4d}  {a:7.1f}  {b:7.1f}  {diff:+6.1f}{marker}")

print(f"\n  Score: ATTUALE vince {att_wins} / {best_alt.split(')')[0].strip('(').strip()} vince {alt_wins} / pareggi {ties}")

# ── Significatività statistica ──
if len(att_dirs) >= 5 and len(alt_dirs) >= 5:
    t_stat, p_val = scipy_stats.ttest_rel(alt_dirs[:min(len(att_dirs), len(alt_dirs))],
                                           att_dirs[:min(len(att_dirs), len(alt_dirs))])
    print(f"\n  Test t-paired: t={t_stat:.3f}, p={p_val:.4f}")
    if p_val < 0.05:
        print(f"  → Differenza STATISTICAMENTE SIGNIFICATIVA (p < 0.05)")
    else:
        print(f"  → Differenza NON significativa (p = {p_val:.3f})")

print("\n  LEGENDA:")
print("    Dir%     = % predizioni direzionali corrette (top3 sale, bot3 scende)")
print("    RankCorr = correlazione Spearman tra rank COT e rank ritorni futuri")
print("    Spread   = differenziazione COT tra valute (più alto = più discriminante)")
print("    LS_ret%  = rendimento medio Long top3 - Short bot3")
print("    ΔDir>3% e ΔRankCorr>0.02 = verdetto MIGLIORE\n")
print("=" * 76)
print("DONE")
