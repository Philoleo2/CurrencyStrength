"""Complete remaining configs from grid search."""
import sys, statistics, numpy as np, pandas as pd
from data_fetcher import fetch_all_pairs, compute_currency_returns
from cot_data import load_cot_data, compute_cot_scores
from config import CURRENCIES
import strength_engine as SE, config as CFG

all_pairs = fetch_all_pairs("H1")
try:
    cot = compute_cot_scores(load_cot_data())
except Exception:
    cot = {c: {"score":50,"bias":"NEUTRAL","freshness_days":99} for c in CURRENCIES}

min_len = min(len(df) for df in all_pairs.values())
ORIG = (0.25, 0.20, 0.30, 0.25)

def set_w(pa, vol, ct, c9):
    CFG.WEIGHT_PRICE_ACTION=pa; SE.WEIGHT_PRICE_ACTION=pa
    CFG.WEIGHT_VOLUME=vol; SE.WEIGHT_VOLUME=vol
    CFG.WEIGHT_COT=ct; SE.WEIGHT_COT=ct
    CFG.WEIGHT_C9=c9; SE.WEIGHT_C9=c9

def eval_cfg(w):
    set_w(*w)
    results = {"quality":[], "n_top":[], "dir_correct":[]}
    for si in range(35):
        end = min_len - si * 24
        start = end - 500
        h_end = min(end + 24, min_len)
        if start < 0 or h_end <= end:
            continue
        data = {p: df.iloc[start:end].copy() for p, df in all_pairs.items()}
        try:
            an = SE.full_analysis(data, {}, cot)
            su = SE.compute_trade_setups(
                composite=an["composite"], momentum=an["momentum"],
                classification=an["classification"], atr_context=an["atr_context"],
                cot_scores=cot, velocity_scores=an["velocity"],
                trend_structure=an["trend_structure"],
                strength_persistence=an["strength_persistence"],
                candle9=an.get("candle9", {}))
        except Exception:
            continue
        finally:
            set_w(*ORIG)
        if su:
            results["quality"].append(statistics.mean([s["quality_score"] for s in su]))
            results["n_top"].append(sum(1 for s in su if s["grade"] in ("A+", "A")))
        else:
            results["quality"].append(0)
            results["n_top"].append(0)
        comp = {c: d["composite"] for c, d in an["composite"].items()}
        rank = sorted(comp.items(), key=lambda x: x[1], reverse=True)
        top3 = [r[0] for r in rank[:3]]
        bot3 = [r[0] for r in rank[-3:]]
        df2 = {p: df.iloc[start:h_end].copy() for p, df in all_pairs.items()}
        try:
            rets = compute_currency_returns(df2, window=1)
            if rets.empty or len(rets) < 10:
                continue
            cum = (1 + rets).cumprod()
            ti = min(end - start - 1, len(cum) - 1)
            hi = min(h_end - start - 1, len(cum) - 1)
            if hi <= ti:
                continue
            ok = tot = 0
            for c in top3:
                if c in cum.columns:
                    tot += 1
                    if cum[c].iloc[hi] - cum[c].iloc[ti] > 0:
                        ok += 1
            for c in bot3:
                if c in cum.columns:
                    tot += 1
                    if cum[c].iloc[hi] - cum[c].iloc[ti] < 0:
                        ok += 1
            results["dir_correct"].append(ok / max(tot, 1))
        except Exception:
            pass
    return {k: statistics.mean(v) if v else 0 for k, v in results.items()}

# All configs: vol 0.30..0.60, cot 0.10+, c9 0.10+
configs = []
for vi in range(6, 13):
    for ci in range(2, 16 - vi):
        c9i = 15 - vi - ci
        if c9i < 2:
            continue
        v = round(vi * 0.05, 2)
        ct = round(ci * 0.05, 2)
        c9 = round(c9i * 0.05, 2)
        configs.append((0.25, v, ct, c9))

print(f"Testing {len(configs)} remaining configs...")
print(f"  {'PA':>5} {'Vol':>5} {'COT':>5} {'C9':>5}  |  {'Q_avg':>6} {'A+/A':>5} {'Dir%':>6}  {'Score':>7}")
for w in configs:
    r = eval_cfg(w)
    sc = r["quality"] / 50 * 40 + r["n_top"] / 3 * 30 + r["dir_correct"] * 100 * 30 / 100
    print(f"  {w[0]:.2f} {w[1]:.2f} {w[2]:.2f} {w[3]:.2f}  |  "
          f"{r['quality']:6.1f} {r['n_top']:5.2f} {r['dir_correct']*100:5.1f}%  {sc:7.2f}")

print("DONE")
