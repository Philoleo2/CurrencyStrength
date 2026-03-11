"""Test radar chart logic only."""
import numpy as np
import plotly.graph_objects as go
from data_fetcher import fetch_all_pairs, fetch_all_futures
from cot_data import load_cot_data, compute_cot_scores
from strength_engine import full_analysis, blend_multi_timeframe

# Load data
all_pairs_h1 = fetch_all_pairs("H1")
futures = fetch_all_futures("H1")
cot_df = load_cot_data()
cot = compute_cot_scores(cot_df)

a1 = full_analysis(all_pairs_h1, futures, cot)
all_pairs_h4 = fetch_all_pairs("H4")
a4 = full_analysis(all_pairs_h4, futures, cot)
blended = blend_multi_timeframe(a1, a4)

composite = blended["composite"]
classification = blended["classification"]
momentum = blended["momentum"]

sorted_ccys = sorted(composite.keys(), key=lambda c: composite[c]["composite"], reverse=True)

color_map = {
    "USD": "#1f77b4", "EUR": "#ff7f0e", "GBP": "#2ca02c",
    "JPY": "#d62728", "CHF": "#9467bd", "AUD": "#8c564b",
    "NZD": "#e377c2", "CAD": "#7f7f7f",
}

radar_row1 = sorted_ccys[:4]
radar_row2 = sorted_ccys[4:]

def _hex_to_rgba(hex_color, alpha=0.2):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

for row_ccys in [radar_row1, radar_row2]:
    for i, ccy in enumerate(row_ccys):
        info = composite[ccy]
        cls = classification.get(ccy, {})
        mom = momentum.get(ccy, {})

        raw_mom = mom.get("delta", 0)
        mom_norm = 50 + np.clip(raw_mom * 5, -50, 50)

        categories = ["Price Action", "Volume", "COT", "Momentum", "Trend Score"]
        values = [
            info["price_score"],
            info["volume_score"],
            info["cot_score"],
            mom_norm,
            cls.get("trend_score", 50),
        ]
        values_closed = values + [values[0]]
        cats_closed = categories + [categories[0]]

        ccy_color = color_map.get(ccy, "#888888")
        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=values_closed,
            theta=cats_closed,
            fill="toself",
            fillcolor=_hex_to_rgba(ccy_color, 0.2),
            line=dict(color=ccy_color, width=2),
            name=ccy,
        ))
        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(visible=True, range=[0, 100], showticklabels=False),
                bgcolor="#fafafa",
            ),
            showlegend=False,
            height=250,
            margin=dict(l=30, r=30, t=30, b=30),
            title=dict(text=f"<b>{ccy}</b>", x=0.5, font=dict(size=14)),
        )
        print(f"{ccy}: values={[round(v,1) for v in values]} OK")

print("\n=== RADAR CHART TEST PASSED ===")
