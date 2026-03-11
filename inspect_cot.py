"""Quick inspection of raw COT data."""
import pandas as pd, numpy as np
from cot_data import load_cot_data
from config import CURRENCIES

df = load_cot_data()
print("=== DATI GREZZI NET_SPECULATIVE (ultimi 10 report) ===\n")
for ccy in CURRENCIES:
    sub = df[df["currency"] == ccy].sort_values("date").tail(10)
    if sub.empty:
        print(f"{ccy}: NO DATA"); continue
    vals = sub["net_speculative"].values
    dates = sub["date"].values
    deltas = np.diff(vals)
    print(f"{ccy}:")
    for i, (d, v) in enumerate(zip(dates, vals)):
        ds = f"  d={deltas[i-1]:+,.0f}" if i > 0 else ""
        print(f"  {pd.Timestamp(d).strftime('%Y-%m-%d')}  net={v:>10,.0f}{ds}")
    print(f"  Range: {vals.min():,.0f} -> {vals.max():,.0f}")
    if len(deltas) > 0:
        print(f"  Deltas: min={deltas.min():+,.0f}  max={deltas.max():+,.0f}  avg={deltas.mean():+,.1f}")
    print()

# Full history for each currency - percentile analysis
print("=== ANALISI PERCENTILI (storico completo) ===\n")
for ccy in CURRENCIES:
    sub = df[df["currency"] == ccy].sort_values("date")
    if sub.empty:
        print(f"{ccy}: NO DATA"); continue
    vals = sub["net_speculative"].values
    latest = vals[-1]
    pct = np.sum(vals <= latest) / len(vals) * 100
    
    # Deltas
    d1 = np.diff(vals)
    if len(d1) >= 2:
        latest_d = d1[-1]
        pct_d = np.sum(d1 <= latest_d) / len(d1) * 100
    else:
        latest_d = 0; pct_d = 50
    
    print(f"{ccy}: {len(vals)} obs, latest={latest:,.0f}, "
          f"pct_level={pct:.0f}%, latest_delta={latest_d:+,.0f}, pct_delta={pct_d:.0f}%")
