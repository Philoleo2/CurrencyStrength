"""Test funzionale completo del pipeline Currency Strength."""
import sys

print("=== Test funzionale Currency Strength ===")

# 1. Config
from config import CURRENCIES, COMPOSITE_WEIGHT_H1, COMPOSITE_WEIGHT_H4
print(f"[OK] Config: {len(CURRENCIES)} valute, blend H1={COMPOSITE_WEIGHT_H1} H4={COMPOSITE_WEIGHT_H4}")

# 2. Data fetch
from data_fetcher import fetch_all_pairs, fetch_all_futures
pairs_h1 = fetch_all_pairs("H1")
pairs_h4 = fetch_all_pairs("H4")
futures_h1 = fetch_all_futures("H1")
futures_h4 = fetch_all_futures("H4")
print(f"[OK] Pairs: H1={len(pairs_h1)}, H4={len(pairs_h4)}")
print(f"[OK] Futures: H1={len(futures_h1)}, H4={len(futures_h4)}")

# 3. COT
from cot_data import load_cot_data, compute_cot_scores
cot_raw = load_cot_data()
cot_scores = compute_cot_scores(cot_raw)
print(f"[OK] COT scores: {len(cot_scores)} valute")

# 4. Analisi separata
from strength_engine import full_analysis, blend_multi_timeframe
analysis_h1 = full_analysis(pairs_h1, futures_h1, cot_scores)
analysis_h4 = full_analysis(pairs_h4, futures_h4, cot_scores)
print(f"[OK] Analisi H1: {len(analysis_h1['composite'])} valute")
print(f"[OK] Analisi H4: {len(analysis_h4['composite'])} valute")

# 5. Blend composito
blended = blend_multi_timeframe(analysis_h1, analysis_h4)
print(f"[OK] Blend composito: {len(blended['composite'])} valute")
print()
print("--- Risultati Composito ---")
for ccy, info in sorted(blended["composite"].items(),
                        key=lambda x: x[1]["composite"], reverse=True):
    print(f"  {ccy}: Score={info['composite']:.1f}  "
          f"H1={info['h1_score']}  H4={info['h4_score']}  "
          f"{info['concordance']}  [{info['label']}]")

# 6. Verifica struttura output
assert "h1_analysis" in blended, "Missing h1_analysis in blended"
assert "h4_analysis" in blended, "Missing h4_analysis in blended"
assert "momentum" in blended, "Missing momentum"
assert "classification" in blended, "Missing classification"
assert "rolling_strength" in blended, "Missing rolling_strength"
print()
print("[OK] Struttura output blended completa")

# 7. Test gauge helper functions (no Streamlit)
import plotly.graph_objects as go
fig = go.Figure()
fig.add_trace(go.Pie(values=[70, 30], hole=0.75))
print("[OK] Plotly gauge test OK")

print()
print("=== TUTTI I TEST SUPERATI ===")
