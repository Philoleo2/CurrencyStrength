"""Test mobile pipeline locally to debug scores."""
import sys
sys.path.insert(0, "android_app")

from fetcher import fetch_all_pairs, fetch_all_futures, _get_yahoo_session, _resample_ohlcv
from engine import (
    compute_price_action_scores, compute_volume_scores,
    compute_composite_scores, full_analysis, blend_multi_timeframe,
    compute_trade_setups, compute_momentum_rankings,
    CURRENCIES
)

print("=== Step 1: Auth ===")
sess, crumb = _get_yahoo_session()
print(f"Session OK, crumb: {crumb!r}")

print("\n=== Step 2: Fetch 3 pairs (H1) ===")
test_pairs = {}
from app_config import FOREX_PAIRS
for i, pair_name in enumerate(list(FOREX_PAIRS.keys())[:3]):
    from fetcher import fetch_pair
    df = fetch_pair(pair_name, "H1")
    print(f"  {pair_name}: {len(df)} bars, columns={list(df.columns)}")
    if not df.empty:
        test_pairs[pair_name] = df
        print(f"    Close range: {df['Close'].min():.5f} - {df['Close'].max():.5f}")
        print(f"    Last close: {df['Close'].iloc[-1]:.5f}")

if not test_pairs:
    print("ERROR: No data fetched!")
    sys.exit(1)

print(f"\n=== Step 3: Price Action Scores ({len(test_pairs)} pairs) ===")
try:
    pa_scores = compute_price_action_scores(test_pairs)
    for ccy, sc in sorted(pa_scores.items(), key=lambda x: x[1], reverse=True):
        marker = " <-- NOT 50" if abs(sc - 50) > 0.1 else ""
        print(f"  {ccy}: {sc}{marker}")
except Exception as e:
    print(f"ERROR in price action: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Step 4: Fetch all pairs H1 ===")
all_h1 = fetch_all_pairs("H1")
print(f"Fetched {len(all_h1)} / {len(FOREX_PAIRS)} pairs")

print("\n=== Step 5: Resample to H4 ===")
all_h4 = {}
for pair_name, df in all_h1.items():
    resampled = _resample_ohlcv(df, "4h")
    if not resampled.empty:
        all_h4[pair_name] = resampled
print(f"Resampled {len(all_h4)} pairs to H4")
if all_h4:
    sample = list(all_h4.values())[0]
    print(f"  Sample H4 bars: {len(sample)}")

print("\n=== Step 6: Fetch futures ===")
fut_h1 = fetch_all_futures("H1")
print(f"Fetched {len(fut_h1)} futures")

print("\n=== Step 7: Full analysis H1 ===")
cot_scores = {c: {"score": 50, "bias": "NEUTRAL"} for c in CURRENCIES}
try:
    analysis_h1 = full_analysis(all_h1, fut_h1, cot_scores)
    print("H1 composite scores:")
    for ccy in CURRENCIES:
        sc = analysis_h1["composite"][ccy]["composite"]
        marker = " <-- NOT 50" if abs(sc - 50) > 0.5 else " ALL_50_BUG!"
        print(f"  {ccy}: {sc}{marker}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Step 8: Full analysis H4 ===")
fut_h4 = {ccy: _resample_ohlcv(df, "4h") for ccy, df in fut_h1.items()}
fut_h4 = {k: v for k, v in fut_h4.items() if not v.empty}
try:
    analysis_h4 = full_analysis(all_h4, fut_h4, cot_scores)
    print("H4 composite scores:")
    for ccy in CURRENCIES:
        sc = analysis_h4["composite"][ccy]["composite"]
        marker = " <-- NOT 50" if abs(sc - 50) > 0.5 else " ALL_50_BUG!"
        print(f"  {ccy}: {sc}{marker}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Step 9: Blend ===")
try:
    blended = blend_multi_timeframe(analysis_h1, analysis_h4)
    print("Blended composite scores:")
    for ccy in CURRENCIES:
        sc = blended["composite"][ccy]["composite"]
        label = blended["composite"][ccy]["label"]
        marker = " <-- NOT 50" if abs(sc - 50) > 0.5 else " ALL_50_BUG!"
        print(f"  {ccy}: {sc} ({label}){marker}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n=== Step 10: Trade setups ===")
try:
    setups = compute_trade_setups(
        blended["composite"], blended["momentum"], blended["classification"],
        blended.get("atr_context", {}), cot_scores,
        velocity_scores=blended.get("velocity"),
        trend_structure=blended.get("trend_structure"),
        strength_persistence=blended.get("strength_persistence"),
    )
    print(f"Total setups: {len(setups)}")
    for s in setups[:5]:
        print(f"  {s['grade']} {s['pair']} {s['direction']} score={s['quality_score']} diff={s['differential']}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\nDONE!")
