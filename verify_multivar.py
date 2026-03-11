"""Quick verification of MULTI_VAR COT scoring."""
from cot_data import load_cot_data, compute_cot_scores
from asset_cot_data import load_asset_cot_data, compute_asset_cot_scores

print("=== FOREX COT (MULTI_VAR) ===")
cot = load_cot_data(use_cache=False)
scores = compute_cot_scores(cot)
for ccy in sorted(scores):
    d = scores[ccy]
    print(f"  {ccy}: score={d['score']:5.1f}  bias={d['bias']:8s}  "
          f"level_pct={d['net_spec_percentile']:5.1f}  "
          f"wkchg={d['weekly_change']:>8.0f}  extreme={d['extreme']}  "
          f"fresh={d['freshness_days']}d")

print("\n=== ASSET COT (MULTI_VAR) ===")
acot = load_asset_cot_data(use_cache=False)
ascores = compute_asset_cot_scores(acot)
for a in sorted(ascores):
    d = ascores[a]
    print(f"  {a:10s}: score={d['score']:5.1f}  bias={d['bias']:8s}  "
          f"level_pct={d['net_spec_percentile']:5.1f}  "
          f"wkchg={d['weekly_change']:>8.0f}  extreme={d['extreme']}  "
          f"fresh={d['freshness_days']}d")

# Check: no all-50 scores
forex_scores = [v['score'] for v in scores.values()]
asset_scores = [v['score'] for v in ascores.values()
                if v['freshness_days'] < 900]  # exclude neutral placeholders
print(f"\nForex score range: {min(forex_scores):.1f} - {max(forex_scores):.1f}")
print(f"Asset score range: {min(asset_scores):.1f} - {max(asset_scores):.1f}")
all_ok = len(set(forex_scores)) > 1 and len(set(asset_scores)) > 1
print(f"Differentiated scores: {'OK' if all_ok else 'FAIL'}")
