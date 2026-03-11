"""Test all new improvement functions."""
from strength_engine import (
    compute_atr_context, compute_trade_setups,
    compute_currency_correlation, compute_velocity_scores,
    full_analysis, blend_multi_timeframe
)
from data_fetcher import fetch_all_pairs, fetch_all_futures
from cot_data import load_cot_data, compute_cot_scores

print("All imports OK")

# Load data
all_pairs_h1 = fetch_all_pairs("H1")
print(f"H1 pairs: {len(all_pairs_h1)}")
futures = fetch_all_futures("H1")
print(f"Futures: {len(futures)}")
cot_df = load_cot_data()
cot = compute_cot_scores(cot_df)
print(f"COT scores: {len(cot)}")

# H1 analysis
a1 = full_analysis(all_pairs_h1, futures, cot)
print(f"H1 analysis: {len(a1['composite'])} currencies")
print(f"ATR context present: {'atr_context' in a1}")
print(f"Velocity present: {'velocity' in a1}")
atr = a1.get("atr_context", {})
for c, v in list(atr.items())[:3]:
    print(f"  {c}: ATR={v['atr_pct']:.4f}%, regime={v['volatility_regime']}")
vel = a1.get("velocity", {})
for c, v in list(vel.items())[:3]:
    print(f"  {c}: velocity={v['velocity_norm']}, bars={v['bars_to_move']}, {v['velocity_label']}")

# H4 analysis
all_pairs_h4 = fetch_all_pairs("H4")
a4 = full_analysis(all_pairs_h4, futures, cot)
print(f"H4 analysis: {len(a4['composite'])} currencies")

# Blend
blended = blend_multi_timeframe(a1, a4)
print(f"Blend: {len(blended['composite'])} currencies")
print(f"Blend has atr_context: {'atr_context' in blended}")
print(f"Blend has velocity: {'velocity' in blended}")
bvel = blended.get("velocity", {})
for c, v in list(bvel.items())[:3]:
    print(f"  {c}: velocity={v['velocity_norm']}, {v['velocity_label']}")

# Trade setups (with velocity)
setups = compute_trade_setups(
    blended["composite"], blended["momentum"],
    blended["classification"], blended.get("atr_context", {}),
    blended.get("cot_scores", {}),
    velocity_scores=blended.get("velocity", {}),
)
print(f"Trade setups: {len(setups)} pairs")
if setups:
    top = setups[0]
    print(f"  Best: {top['pair']} {top['direction']} grade={top['grade']} score={top['quality_score']}")
    print(f"  Reasons: {' | '.join(top['reasons'][:4])}")

# Correlation
corr = compute_currency_correlation(all_pairs_h1, window=30)
if corr is not None:
    print(f"Correlation matrix: {corr.shape}")
else:
    print("Correlation: None (insufficient data)")

print()
print("=== ALL TESTS PASSED ===")
