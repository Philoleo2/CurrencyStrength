"""
Simulazione COT Rolling: Percentile Variazione vs Dato Secco
==============================================================
A DIFFERENZA della versione precedente, qui ricalcoliamo i COT scores
ad ogni step del backtest usando solo i dati COT disponibili fino a
quel punto temporale. Questo simula il comportamento reale.

Varianti:
  A) ATTUALE : percentile(livello_netto) + aggiustamento change
  B) VAR_PURA: percentile(delta settimanale) puro
  C) BLEND   : 40% livello + 60% variazione
  D) MULTI_VAR: 50% delta_1w + 30% delta_2w + 20% delta_4w
"""

import sys, statistics, numpy as np, pandas as pd, datetime as dt

from data_fetcher import fetch_all_pairs, compute_currency_returns
from cot_data import load_cot_data
from config import CURRENCIES, COT_PERCENTILE_LOOKBACK, COT_EXTREME_LONG, COT_EXTREME_SHORT
import strength_engine as SE
import config as CFG


# ═══════════════════════════════════════════════════════════════════════════════
#  COT SCORING — ATTUALE (replica esatta di compute_cot_scores)
# ═══════════════════════════════════════════════════════════════════════════════

def _pct_rank(val, arr):
    if len(arr) == 0:
        return 50.0
    return float(np.sum(arr <= val) / len(arr)) * 100


def cot_scores_current(cot_sub: dict) -> dict:
    """Replica di compute_cot_scores ma su subset pre-filtrato per data."""
    scores = {}
    for ccy in CURRENCIES:
        ns = cot_sub.get(ccy)
        if ns is None or len(ns) < 2:
            scores[ccy] = {"score": 50.0, "bias": "NEUTRAL", "freshness_days": 99}
            continue

        latest = ns[-1]
        lb = ns[-COT_PERCENTILE_LOOKBACK:] if len(ns) >= COT_PERCENTILE_LOOKBACK else ns
        pct = _pct_rank(latest, lb)

        # Aggiustamento variazione (come attuale)
        wk_change = float(ns[-1] - ns[-2])
        change_norm = 0.0
        if len(lb) > 1:
            std_ns = np.std(lb)
            if std_ns > 0:
                change_norm = np.clip(wk_change / std_ns, -2, 2) * 10
        score = float(np.clip(pct + change_norm, 0, 100))

        if score >= 60: bias = "BULLISH"
        elif score <= 40: bias = "BEARISH"
        else: bias = "NEUTRAL"

        scores[ccy] = {"score": round(score, 1), "bias": bias, "freshness_days": 3,
                        "extreme": None, "weekly_change": round(wk_change, 0),
                        "net_spec_percentile": round(pct, 1)}
    return scores


def cot_scores_variation(cot_sub: dict, mode: str) -> dict:
    """COT scoring basato sul percentile della variazione."""
    scores = {}
    for ccy in CURRENCIES:
        ns = cot_sub.get(ccy)
        if ns is None or len(ns) < 3:
            scores[ccy] = {"score": 50.0, "bias": "NEUTRAL", "freshness_days": 99}
            continue

        lookback = min(COT_PERCENTILE_LOOKBACK, len(ns))

        # Percentile livello
        pct_level = _pct_rank(ns[-1], ns[-lookback:])

        # Delta settimanali
        d1 = np.diff(ns)
        d2 = ns[2:] - ns[:-2]
        d4 = ns[4:] - ns[:-4] if len(ns) >= 5 else d1

        # Percentile variazione 1w
        if len(d1) >= 2:
            pv1 = _pct_rank(d1[-1], d1[-min(lookback, len(d1)):])
        else:
            pv1 = 50.0
        # Percentile variazione 2w
        if len(d2) >= 2:
            pv2 = _pct_rank(d2[-1], d2[-min(lookback, len(d2)):])
        else:
            pv2 = 50.0
        # Percentile variazione 4w
        if len(d4) >= 2:
            pv4 = _pct_rank(d4[-1], d4[-min(lookback, len(d4)):])
        else:
            pv4 = 50.0

        if mode == "VAR_PURA":
            score = pv1
        elif mode == "BLEND":
            score = 0.40 * pct_level + 0.60 * pv1
        elif mode == "MULTI_VAR":
            score = 0.50 * pv1 + 0.30 * pv2 + 0.20 * pv4
        else:
            score = pv1

        score = float(np.clip(score, 0, 100))
        if score >= 60: bias = "BULLISH"
        elif score <= 40: bias = "BEARISH"
        else: bias = "NEUTRAL"

        scores[ccy] = {"score": round(score, 1), "bias": bias, "freshness_days": 3,
                        "extreme": None, "weekly_change": float(d1[-1]) if len(d1) else 0,
                        "net_spec_percentile": round(pct_level, 1)}
    return scores


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKTEST ROLLING CON COT DINAMICO
# ═══════════════════════════════════════════════════════════════════════════════

ORIG_W = (0.25, 0.20, 0.30, 0.25)

def set_weights(pa, vol, ct, c9):
    CFG.WEIGHT_PRICE_ACTION = pa; SE.WEIGHT_PRICE_ACTION = pa
    CFG.WEIGHT_VOLUME = vol; SE.WEIGHT_VOLUME = vol
    CFG.WEIGHT_COT = ct; SE.WEIGHT_COT = ct
    CFG.WEIGHT_C9 = c9; SE.WEIGHT_C9 = c9


def build_cot_timeline(cot_df: pd.DataFrame):
    """
    Costruisce un dizionario {ccy: [(date, net_spec), ...]} ordinato per data.
    """
    timeline = {}
    for ccy in CURRENCIES:
        sub = cot_df[cot_df["currency"] == ccy].sort_values("date")
        if not sub.empty:
            timeline[ccy] = list(zip(sub["date"].values, sub["net_speculative"].values))
        else:
            timeline[ccy] = []
    return timeline


def cot_available_at(timeline, ref_date):
    """
    Dato un riferimento temporale, restituisce per ogni valuta
    l'array di net_spec disponibili fino a quella data (inclusa).
    """
    result = {}
    for ccy in CURRENCIES:
        entries = timeline.get(ccy, [])
        vals = [v for d, v in entries if d <= ref_date]
        if vals:
            result[ccy] = np.array(vals)
        else:
            result[ccy] = None
    return result


def backtest_rolling(all_pairs, cot_timeline, bar_dates, mode_name, score_fn,
                     n_steps=35, window=500, step=24, horizon=24):
    """
    Backtest rolling. Ad ogni step ricalcola i COT scores usando solo i dati
    disponibili fino alla data della barra corrente.
    """
    min_len = min(len(df) for df in all_pairs.values())
    results = {"quality": [], "n_top": [], "dir_correct": [], "grade_list": [],
               "cot_spread": []}

    for si in range(n_steps):
        end = min_len - si * step
        start = end - window
        h_end = min(end + horizon, min_len)
        if start < 0 or h_end <= end:
            continue

        data = {p: df.iloc[start:end].copy() for p, df in all_pairs.items()}

        # Data di riferimento per il COT
        ref_date = bar_dates[end - 1] if end - 1 < len(bar_dates) else bar_dates[-1]
        cot_sub = cot_available_at(cot_timeline, ref_date)

        # Calcola scores COT con la funzione specifica del mode
        cot_s = score_fn(cot_sub)

        set_weights(*ORIG_W)
        try:
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
        except Exception:
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

        # COT spread: quanto sono diversi i COT scores tra valute?
        cot_vals = [cot_s[c]["score"] for c in CURRENCIES if c in cot_s]
        if len(cot_vals) >= 2:
            results["cot_spread"].append(max(cot_vals) - min(cot_vals))

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
                    if cum[c].iloc[h_idx] - cum[c].iloc[t_idx] > 0: ok += 1
            for c in bot3:
                if c in cum.columns:
                    tot += 1
                    if cum[c].iloc[h_idx] - cum[c].iloc[t_idx] < 0: ok += 1
            results["dir_correct"].append(ok / max(tot, 1))
        except Exception:
            pass

    return results


def summarize(results):
    q = results["quality"]
    d = results["dir_correct"]
    n = results["n_top"]
    cs = results.get("cot_spread", [])
    grades = results["grade_list"]
    gd = {g: grades.count(g) for g in ["A+", "A", "B", "C", "D"]}
    total = max(len(grades), 1)
    return {
        "q_avg": statistics.mean(q) if q else 0,
        "q_med": statistics.median(q) if q else 0,
        "dir_avg": statistics.mean(d) * 100 if d else 0,
        "dir_med": statistics.median(d) * 100 if d else 0,
        "n_top_avg": statistics.mean(n) if n else 0,
        "n_signals": len([x for x in n if x > 0]),
        "cot_spread": statistics.mean(cs) if cs else 0,
        "grade_dist": gd,
        "pct_top": round((gd.get("A+", 0) + gd.get("A", 0)) / total * 100, 1),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 76)
print("  SIMULAZIONE COT ROLLING: Percentile Variazione vs Dato Secco")
print("  Pesi: PA=0.25  Vol=0.20  COT=0.30  C9=0.25 (invariati)")
print("  COT ricalcolato ad ogni step usando dati disponibili a quel punto")
print("=" * 76)

print("\n[1/4] Fetch dati ...", flush=True)
all_pairs = fetch_all_pairs("H1")
if not all_pairs:
    print("ERRORE"); sys.exit(1)
min_len = min(len(df) for df in all_pairs.values())
print(f"       {len(all_pairs)} coppie, {min_len} barre")

cot_df = load_cot_data()
print(f"       COT: {len(cot_df)} righe, {cot_df['currency'].nunique()} valute")

# Allinea date: prendi le date dalle barre di una coppia qualunque
ref_pair = list(all_pairs.values())[0]
if "time" in ref_pair.columns:
    bar_dates = pd.to_datetime(ref_pair["time"]).values
elif ref_pair.index.dtype == "datetime64[ns]":
    bar_dates = ref_pair.index.values
else:
    # Genera date fittizie (H1) partendo dall'ultima data COT
    last_cot = cot_df["date"].max()
    bar_dates = pd.date_range(end=last_cot, periods=min_len, freq="h").values

print(f"       Barre da {pd.Timestamp(bar_dates[0]).date()} a {pd.Timestamp(bar_dates[-1]).date()}")

# ── Timeline COT ──
print("\n[2/4] Costruzione timeline COT ...", flush=True)
cot_timeline = build_cot_timeline(cot_df)
for ccy in CURRENCIES:
    n = len(cot_timeline.get(ccy, []))
    if n > 0:
        first = pd.Timestamp(cot_timeline[ccy][0][0]).date()
        last = pd.Timestamp(cot_timeline[ccy][-1][0]).date()
        print(f"       {ccy}: {n} report ({first} → {last})")

# ── Varianti ──
modes = [
    ("A) ATTUALE",    lambda sub: cot_scores_current(sub)),
    ("B) VAR_PURA",   lambda sub: cot_scores_variation(sub, "VAR_PURA")),
    ("C) BLEND",      lambda sub: cot_scores_variation(sub, "BLEND")),
    ("D) MULTI_VAR",  lambda sub: cot_scores_variation(sub, "MULTI_VAR")),
]

# ── Backtest ──
print("\n[3/4] Backtest rolling con COT dinamico (35 step × 4 varianti) ...", flush=True)

all_summaries = {}
for label, score_fn in modes:
    print(f"  → {label} ...", end=" ", flush=True)
    res = backtest_rolling(all_pairs, cot_timeline, bar_dates, label, score_fn)
    s = summarize(res)
    all_summaries[label] = s
    print(f"Dir={s['dir_avg']:.1f}%  Q={s['q_avg']:.1f}  A+/A={s['n_top_avg']:.2f}  "
          f"COT_spread={s['cot_spread']:.1f}")

# ── Report ──
print("\n" + "=" * 76)
print("  RISULTATI COMPARATIVI (COT ricalcolato ad ogni step)")
print("=" * 76)

print(f"\n  {'Variante':<16}  {'Dir%':>6}  {'Dir_Med':>7}  {'Q_avg':>6}  {'Q_med':>6}  "
      f"{'A+/A':>5}  {'%A+/A':>6}  {'COT_spr':>7}  {'Sig':>4}")
print(f"  {'─'*16}  {'─'*6}  {'─'*7}  {'─'*6}  {'─'*6}  {'─'*5}  {'─'*6}  {'─'*7}  {'─'*4}")

best_dir = max(s["dir_avg"] for s in all_summaries.values())
for label, s in all_summaries.items():
    marker = " ◀" if s["dir_avg"] == best_dir else ""
    print(f"  {label:<16}  {s['dir_avg']:6.1f}  {s['dir_med']:7.1f}  {s['q_avg']:6.1f}  "
          f"{s['q_med']:6.1f}  {s['n_top_avg']:5.2f}  {s['pct_top']:5.1f}%  "
          f"{s['cot_spread']:7.1f}  {s['n_signals']:4d}{marker}")

att = all_summaries["A) ATTUALE"]
print(f"\n  {'Variante':<16}  {'ΔDir%':>7}  {'ΔQ_avg':>7}  {'ΔA+/A':>7}  {'ΔCOT_spr':>8}  Verdetto")
print(f"  {'─'*16}  {'─'*7}  {'─'*7}  {'─'*7}  {'─'*8}  ────────")
for label, s in all_summaries.items():
    dd = s["dir_avg"] - att["dir_avg"]
    dq = s["q_avg"] - att["q_avg"]
    dn = s["n_top_avg"] - att["n_top_avg"]
    ds = s["cot_spread"] - att["cot_spread"]
    if label == "A) ATTUALE":
        verdict = "BASELINE"
    elif dd > 1.5:
        verdict = "✅ MIGLIORE"
    elif dd > 0.5:
        verdict = "↗ MARGINALE+"
    elif dd > -0.5:
        verdict = "≈ PARI"
    elif dd > -1.5:
        verdict = "↘ MARGINALE-"
    else:
        verdict = "❌ PEGGIORE"
    print(f"  {label:<16}  {dd:+7.1f}  {dq:+7.1f}  {dn:+7.2f}  {ds:+8.1f}  {verdict}")

# ── Grade distribution ──
print(f"\n  Distribuzione Gradi:")
print(f"  {'Variante':<16}  {'A+':>4}  {'A':>4}  {'B':>4}  {'C':>4}  {'D':>4}")
print(f"  {'─'*16}  {'─'*4}  {'─'*4}  {'─'*4}  {'─'*4}  {'─'*4}")
for label, s in all_summaries.items():
    gd = s["grade_dist"]
    print(f"  {label:<16}  {gd.get('A+',0):4d}  {gd.get('A',0):4d}  "
          f"{gd.get('B',0):4d}  {gd.get('C',0):4d}  {gd.get('D',0):4d}")

# ── Interpretazione ──
print(f"\n  NOTA: COT_spread = differenza tra il COT score massimo e minimo")
print(f"        tra le 8 valute. Spread piu' alto = piu' discriminazione.")
print(f"        Se una variante ha Dir% superiore E spread maggiore,")
print(f"        vuol dire che il segnale COT e' piu' informativo.\n")
print("=" * 76)
print("DONE")
