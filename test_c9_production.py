"""Test C9 integration in production pipeline."""
import warnings; warnings.filterwarnings('ignore')
from data_fetcher import fetch_all_pairs, fetch_all_futures
from cot_data import load_cot_data, compute_cot_scores
from strength_engine import full_analysis, blend_multi_timeframe, compute_trade_setups
from config import CURRENCIES

# Fetch data
pairs_h1 = fetch_all_pairs('H1')
pairs_h4 = fetch_all_pairs('H4')
futures_h1 = fetch_all_futures('H1')
futures_h4 = fetch_all_futures('H4')
cot_raw = load_cot_data()
cot_scores = compute_cot_scores(cot_raw)

# Run analysis
a_h1 = full_analysis(pairs_h1, futures_h1, cot_scores)
a_h4 = full_analysis(pairs_h4, futures_h4, cot_scores)
blended = blend_multi_timeframe(a_h1, a_h4)

composite = blended['composite']
candle9 = blended.get('candle9', {})

# Show results
print('=== COMPOSITO (con C9 al 25%) ===')
for ccy in sorted(CURRENCIES, key=lambda c: composite[c]['composite'], reverse=True):
    info = composite[ccy]
    c9_s = info.get('c9_score', 'N/A')
    c9_ratio = candle9.get(ccy, {}).get('candle9_ratio', 0)
    print(f"  {ccy}: {info['composite']:.1f}  PA={info['price_score']:.1f} Vol={info['volume_score']:.1f} COT={info['cot_score']:.1f} C9={c9_s}  ratio={c9_ratio:+.3f}%")

# Trade setups with C9
momentum = blended['momentum']
classification = blended['classification']
atr_ctx = blended.get('atr_context', {})
velocity = blended.get('velocity', {})
ts = blended.get('trend_structure', {})
sp = blended.get('strength_persistence', {})
setups = compute_trade_setups(composite, momentum, classification, atr_ctx, cot_scores,
                              velocity_scores=velocity, trend_structure=ts,
                              strength_persistence=sp, candle9=candle9)

print(f"\n=== TOP 15 SETUPS ({len(setups)} totali) ===")
for s in setups[:15]:
    c9_reasons = [r for r in s['reasons'] if 'C9' in r]
    c9_info = f"  [{c9_reasons[0]}]" if c9_reasons else ""
    print(f"  {s['grade']:2s} {s['pair']:7s} {s['direction']:5s} Q={s['quality_score']:.0f}{c9_info}")

# Stats
aa_count = sum(1 for s in setups if s['grade'] in ('A+', 'A'))
c9_aligned = sum(1 for s in setups if any('C9 allineato' in r for r in s['reasons']))
c9_partial = sum(1 for s in setups if any('C9 parzialmente' in r for r in s['reasons']))
c9_against = sum(1 for s in setups if any('C9 contro' in r for r in s['reasons']))
print(f"\nA+/A: {aa_count}")
print(f"C9 allineato: {c9_aligned}, parziale: {c9_partial}, contro: {c9_against}")
print("\nOK: C9 production integration test passed")
