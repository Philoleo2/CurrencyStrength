"""
Simulazione: Candle-9 DENTRO la Price Action
=============================================
Integra il segnale Candle-9 (escursione + velocità rispetto a 9 candele fa)
come componente INTERNO del price-action score per coppia.

Attuale:  RSI 35% + ROC 40% + EMA 25%  → PA (40%) + Vol (30%) + COT (30%)
Nuovo:    RSI w1 + ROC w2 + EMA w3 + C9 w4 = 100%  → PA (40%) + Vol (30%) + COT (30%)

Testa diverse distribuzioni interne e confronta con:
  A) Baseline attuale (no C9)
  B) Migliore config precedente (C9 come 4° componente separato al 25%)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from config import (
    CURRENCIES, FOREX_PAIRS, FUTURES_TICKERS,
    MIN_DIFFERENTIAL_THRESHOLD,
    RSI_PERIOD, ROC_FAST, ROC_MEDIUM, ROC_SLOW,
    EMA_FAST, EMA_MEDIUM, EMA_SLOW,
    WEIGHT_PRICE_ACTION, WEIGHT_VOLUME, WEIGHT_COT,
    COT_STALE_DAYS_THRESHOLD,
)
from data_fetcher import fetch_all_pairs, fetch_all_futures
from cot_data import load_cot_data, compute_cot_scores
from strength_engine import (
    rsi, roc, ema,
    compute_price_action_scores,
    compute_volume_scores,
    compute_composite_scores,
    compute_trade_setups,
    compute_momentum_rankings,
    classify_trend_vs_reversion,
    compute_atr_context,
    compute_candle9_signal,
    compute_velocity_scores,
    compute_trend_structure,
    compute_strength_persistence,
    compute_rolling_strength,
    full_analysis,
    blend_multi_timeframe,
)

LOOKBACK = 9


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE ACTION CON C9 INTEGRATO (per coppia)
# ═══════════════════════════════════════════════════════════════════════════════

def _pair_strength_with_c9(pair_df: pd.DataFrame, currency: str,
                            is_base: bool, lookback: int,
                            w_rsi: float, w_roc: float,
                            w_ema: float, w_c9: float) -> float:
    """
    Price-action per coppia con Candle-9 integrato.
    RSI*w_rsi + ROC*w_roc + EMA*w_ema + C9*w_c9 = score 0-100
    """
    close = pair_df["Close"]
    sign = 1.0 if is_base else -1.0

    # --- RSI ---
    rsi_val = rsi(close, RSI_PERIOD)
    latest_rsi = rsi_val.iloc[-1] if not rsi_val.empty else 50
    if not is_base:
        latest_rsi = 100 - latest_rsi

    # --- ROC multi-periodo ---
    roc_f = roc(close, ROC_FAST).iloc[-1] if len(close) > ROC_FAST else 0
    roc_m = roc(close, ROC_MEDIUM).iloc[-1] if len(close) > ROC_MEDIUM else 0
    roc_s = roc(close, ROC_SLOW).iloc[-1] if len(close) > ROC_SLOW else 0
    avg_roc = (roc_f * 0.5 + roc_m * 0.3 + roc_s * 0.2) * sign
    roc_score = 50 + np.clip(avg_roc * 10, -50, 50)

    # --- EMA positioning ---
    ema_scores = []
    for p in [EMA_FAST, EMA_MEDIUM, EMA_SLOW]:
        if len(close) > p:
            ema_val = ema(close, p).iloc[-1]
            pct_above = ((close.iloc[-1] / ema_val) - 1) * 100
            if not is_base:
                pct_above = -pct_above
            ema_scores.append(50 + np.clip(pct_above * 15, -50, 50))
    ema_score = np.mean(ema_scores) if ema_scores else 50

    # --- CANDLE-9: escursione + velocità ---
    c9_score = 50  # default neutro
    if len(close) >= lookback + 2:
        current_close = float(close.iloc[-1])
        past_close = float(close.iloc[-(lookback + 1)])
        if past_close > 0:
            # Magnitude: % escursione
            pct_change = ((current_close - past_close) / past_close) * 100
            if not is_base:
                pct_change = -pct_change

            # Velocity: slope lineare delle ultime N+1 candele
            recent = close.iloc[-(lookback + 1):]
            x = np.arange(len(recent))
            y = recent.values.astype(float)
            slope_pct = 0
            if len(x) >= 2 and not np.isnan(y).all():
                slope = np.polyfit(x, y, 1)[0]
                mean_price = np.mean(y)
                if mean_price > 0:
                    slope_pct = (slope / mean_price) * 100
                    if not is_base:
                        slope_pct = -slope_pct

            # Consistency: % candele nella stessa direzione
            diffs = recent.diff().dropna()
            if len(diffs) > 0:
                if pct_change > 0:
                    consistency = float((diffs > 0).sum() / len(diffs))
                elif pct_change < 0:
                    consistency = float((diffs < 0).sum() / len(diffs))
                else:
                    consistency = 0.0
                if not is_base:
                    # Per quote, il pct_change è già invertito, consistency va bene
                    pass
            else:
                consistency = 0.0

            # Sub-scores
            mag_score = 50 + np.clip(pct_change * 25, -50, 50)
            vel_score = 50 + np.clip(slope_pct * 200, -50, 50)
            cons_bonus = consistency * 10

            c9_score = (
                mag_score * 0.50 +
                vel_score * 0.35 +
                (50 + cons_bonus) * 0.15
            )
            c9_score = float(np.clip(c9_score, 0, 100))

    # --- Composito interno ---
    final = latest_rsi * w_rsi + roc_score * w_roc + ema_score * w_ema + c9_score * w_c9
    return float(np.clip(final, 0, 100))


def compute_pa_with_c9(all_pairs: dict[str, pd.DataFrame],
                        lookback: int, w_rsi: float, w_roc: float,
                        w_ema: float, w_c9: float) -> dict[str, float]:
    """Price action scores con C9 integrato, aggregato per valuta."""
    ccy_scores: dict[str, list[float]] = {c: [] for c in CURRENCIES}

    for pair_name, pair_df in all_pairs.items():
        if pair_df.empty or "Close" not in pair_df.columns:
            continue
        info = FOREX_PAIRS[pair_name]
        base, quote = info["base"], info["quote"]

        if base in ccy_scores:
            s = _pair_strength_with_c9(pair_df, base, True, lookback,
                                        w_rsi, w_roc, w_ema, w_c9)
            ccy_scores[base].append(s)
        if quote in ccy_scores:
            s = _pair_strength_with_c9(pair_df, quote, False, lookback,
                                        w_rsi, w_roc, w_ema, w_c9)
            ccy_scores[quote].append(s)

    return {ccy: round(float(np.mean(vals)), 2) if vals else 50.0
            for ccy, vals in ccy_scores.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# COMPOSITO STANDARD (PA 40% + Vol 30% + COT 30%)
# ═══════════════════════════════════════════════════════════════════════════════

def composite_standard(price_scores, volume_scores, cot_scores):
    """Composito con pesi standard 40/30/30."""
    results = {}
    for ccy in CURRENCIES:
        pa = price_scores.get(ccy, 50)
        vol = volume_scores.get(ccy, 50)
        cot = cot_scores.get(ccy, {}).get("score", 50)

        composite = pa * 0.40 + vol * 0.30 + cot * 0.30
        composite = round(float(np.clip(composite, 0, 100)), 1)

        if composite >= 75:
            label = "VERY STRONG"
        elif composite >= 62:
            label = "STRONG"
        elif composite <= 25:
            label = "VERY WEAK"
        elif composite <= 38:
            label = "WEAK"
        else:
            label = "NEUTRAL"

        cot_info = cot_scores.get(ccy, {})
        alert = None
        if composite >= 75:
            alert = "⚠️ Forza estrema"
        elif composite <= 25:
            alert = "⚠️ Debolezza estrema"

        results[ccy] = {
            "price_score": round(pa, 1),
            "volume_score": round(vol, 1),
            "cot_score": round(cot, 1),
            "composite": composite,
            "label": label,
            "alert": alert,
            "cot_bias": cot_info.get("bias", "NEUTRAL"),
            "cot_extreme": cot_info.get("extreme"),
        }
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# METRICHE
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate(composite, setups):
    scores = [v["composite"] for v in composite.values()]
    spread = max(scores) - min(scores)
    std_val = float(np.std(scores))

    grade_dist = {}
    for s in setups:
        grade_dist[s["grade"]] = grade_dist.get(s["grade"], 0) + 1

    n_aplus = grade_dist.get("A+", 0)
    n_a = grade_dist.get("A", 0)
    n_aa = n_aplus + n_a
    n_b = grade_dist.get("B", 0)

    top5_avg_qs = float(np.mean([s["quality_score"] for s in setups[:5]])) if len(setups) >= 5 else 0
    top5_avg_diff = float(np.mean([abs(s["differential"]) for s in setups[:5]])) if len(setups) >= 5 else 0

    usd_setups = [s for s in setups if s["base"] == "USD" or s["quote"] == "USD"]
    usd_aa = [s for s in usd_setups if s["grade"] in ("A+", "A")]
    usd_score = composite.get("USD", {}).get("composite", 50)
    usd_rank = sorted(CURRENCIES, key=lambda c: composite.get(c, {}).get("composite", 50), reverse=True).index("USD") + 1

    return {
        "spread": round(spread, 1),
        "std": round(std_val, 1),
        "n_aplus": n_aplus,
        "n_a": n_a,
        "n_aa": n_aa,
        "n_b": n_b,
        "n_total": len(setups),
        "top5_avg_qs": round(top5_avg_qs, 1),
        "top5_avg_diff": round(top5_avg_diff, 1),
        "usd_score": round(usd_score, 1),
        "usd_rank": usd_rank,
        "usd_aa": len(usd_aa),
        "usd_signals": len(usd_setups),
        "grade_dist": grade_dist,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURAZIONI INTERNE PA
# ═══════════════════════════════════════════════════════════════════════════════

# (nome, w_rsi, w_roc, w_ema, w_c9) — somma = 1.0
# Il composito resta SEMPRE PA 40% + Vol 30% + COT 30%
INTERNAL_CONFIGS = [
    # Baseline: no C9
    ("BASELINE (RSI35+ROC40+EMA25)",     0.35, 0.40, 0.25, 0.00),
    # C9 leggero (10%)
    ("C9 10% (RSI30+ROC35+EMA25+C9_10)", 0.30, 0.35, 0.25, 0.10),
    # C9 15% — toglie da RSI e ROC
    ("C9 15% (RSI25+ROC35+EMA25+C9_15)", 0.25, 0.35, 0.25, 0.15),
    ("C9 15% (RSI30+ROC30+EMA25+C9_15)", 0.30, 0.30, 0.25, 0.15),
    # C9 20% — redistribuisce
    ("C9 20% (RSI25+ROC30+EMA25+C9_20)", 0.25, 0.30, 0.25, 0.20),
    ("C9 20% (RSI30+ROC30+EMA20+C9_20)", 0.30, 0.30, 0.20, 0.20),
    ("C9 20% (RSI25+ROC35+EMA20+C9_20)", 0.25, 0.35, 0.20, 0.20),
    # C9 25% — peso forte
    ("C9 25% (RSI25+ROC25+EMA25+C9_25)", 0.25, 0.25, 0.25, 0.25),
    ("C9 25% (RSI20+ROC30+EMA25+C9_25)", 0.20, 0.30, 0.25, 0.25),
    # C9 30% — domina
    ("C9 30% (RSI20+ROC25+EMA25+C9_30)", 0.20, 0.25, 0.25, 0.30),
    ("C9 30% (RSI25+ROC25+EMA20+C9_30)", 0.25, 0.25, 0.20, 0.30),
    # C9 35% — molto forte
    ("C9 35% (RSI20+ROC25+EMA20+C9_35)", 0.20, 0.25, 0.20, 0.35),
]


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 95)
    print("  SIMULAZIONE: Candle-9 DENTRO la Price Action")
    print("  Composito fisso: PA 40% + Volume 30% + COT 30%")
    print("  Variabile: pesi interni PA = RSI + ROC + EMA + C9")
    print("=" * 95)
    print()

    # ── Fetch ──
    print("📊 Scaricamento dati...")
    all_h4 = fetch_all_pairs("H4")
    all_h1 = fetch_all_pairs("H1")
    futures = fetch_all_futures("H4")
    cot_raw = load_cot_data()
    cot_scores = compute_cot_scores(cot_raw)
    print(f"   H4: {len(all_h4)}, H1: {len(all_h1)}, Futures: {len(futures)}, COT: {len(cot_scores)}")

    # ── Analisi completa per ottenere momentum, classification, ecc. ──
    print("📈 Calcolo analisi completa (per trade setups)...")
    analysis_h4 = full_analysis(all_h4, futures, cot_scores)
    analysis_h1 = full_analysis(all_h1, futures, cot_scores)
    blended = blend_multi_timeframe(analysis_h1, analysis_h4)
    momentum = blended["momentum"]
    classification = blended["classification"]
    atr_context = blended["atr_context"]
    velocity = blended["velocity"]
    trend_struct = blended["trend_structure"]
    persistence = blended["strength_persistence"]

    # ── Candle-9 raw ──
    c9_detail = compute_candle9_signal(all_h4)
    print("\n📉 Candle-9 raw H4:")
    for ccy, info in sorted(c9_detail.items(), key=lambda x: x[1]["candle9_ratio"], reverse=True):
        r = info["candle9_ratio"]
        sig = info["candle9_signal"]
        print(f"  {ccy:4s}  {r:+.3f}%  {sig}")

    # ══════════════════════════════════════════════════════════════════════
    # TEST CONFIGURAZIONI
    # ══════════════════════════════════════════════════════════════════════
    print("\n")
    print("=" * 95)
    print("  TEST CONFIGURAZIONI (C9 dentro PA, composito 40/30/30)")
    print("=" * 95)

    all_results = []

    for name, w_rsi, w_roc, w_ema, w_c9 in INTERNAL_CONFIGS:
        # Price action con C9 integrato (H4)
        pa_h4 = compute_pa_with_c9(all_h4, LOOKBACK, w_rsi, w_roc, w_ema, w_c9)
        # Volume (usa PA come base per amplificazione)
        vol_scores = compute_volume_scores(all_h4, futures, pa_h4)
        # Composito standard 40/30/30
        comp = composite_standard(pa_h4, vol_scores, cot_scores)
        # Trade setups (usa il composito + gli altri fattori blendati)
        setups = compute_trade_setups(
            comp, momentum, classification, atr_context, cot_scores,
            velocity_scores=velocity,
            trend_structure=trend_struct,
            strength_persistence=persistence,
        )
        metrics = evaluate(comp, setups)
        all_results.append((name, w_rsi, w_roc, w_ema, w_c9, comp, setups, metrics))

    # ── Anche la config "C9 come 4° componente al 25%" dalla sim precedente ──
    # Per confronto diretto
    from sim_candle9_weights import candle9_currency_score, composite_with_c9
    c9_blended = {ccy: round(
        candle9_currency_score(all_h4, LOOKBACK).get(ccy, 50) * 0.6 +
        candle9_currency_score(all_h1, LOOKBACK).get(ccy, 50) * 0.4, 2)
        for ccy in CURRENCIES}
    pa_baseline = compute_price_action_scores(all_h4)
    vol_baseline = compute_volume_scores(all_h4, futures, pa_baseline)
    comp_4comp = composite_with_c9(pa_baseline, vol_baseline, cot_scores, c9_blended,
                                    0.25, 0.20, 0.30, 0.25)
    setups_4comp = compute_trade_setups(
        comp_4comp, momentum, classification, atr_context, cot_scores,
        velocity_scores=velocity, trend_structure=trend_struct,
        strength_persistence=persistence,
    )
    m_4comp = evaluate(comp_4comp, setups_4comp)

    # ── Tabella riassuntiva ──
    print(f"\n{'Config':<42s} {'Sprd':>5s} {'A+':>3s} {'A':>3s} {'A/A+':>4s} {'B':>3s} "
          f"{'Top5Q':>6s} {'Top5Δ':>6s} {'USD':>5s} {'#':>2s} {'USDaa':>5s}")
    print("─" * 95)

    for name, w_rsi, w_roc, w_ema, w_c9, comp, setups, m in all_results:
        print(f"{name:<42s} {m['spread']:>5.1f} {m['n_aplus']:>3d} {m['n_a']:>3d} "
              f"{m['n_aa']:>4d} {m['n_b']:>3d} {m['top5_avg_qs']:>6.1f} "
              f"{m['top5_avg_diff']:>6.1f} {m['usd_score']:>5.1f} #{m['usd_rank']:<1d} "
              f"{m['usd_aa']:>3d}AA")

    # Riga di confronto: 4° componente
    print("─" * 95)
    print(f"{'[RIF] C9 4°comp 25% (PA25+V20+C30+C9_25)':<42s} {m_4comp['spread']:>5.1f} "
          f"{m_4comp['n_aplus']:>3d} {m_4comp['n_a']:>3d} {m_4comp['n_aa']:>4d} "
          f"{m_4comp['n_b']:>3d} {m_4comp['top5_avg_qs']:>6.1f} "
          f"{m_4comp['top5_avg_diff']:>6.1f} {m_4comp['usd_score']:>5.1f} "
          f"#{m_4comp['usd_rank']:<1d} {m_4comp['usd_aa']:>3d}AA")

    # ── Ranking valute per config ──
    print("\n")
    print("=" * 95)
    print("  RANKING VALUTE")
    print("=" * 95)

    # Seleziona: baseline, migliore C9-inside, 4° componente
    baseline = all_results[0]
    # Trova la migliore C9-inside
    best_inside = max(all_results[1:],  # escludi baseline
                      key=lambda x: (x[7]["n_aa"], x[7]["spread"], x[7]["top5_avg_qs"]))

    configs_to_show = [
        ("BASELINE", baseline[5]),
        (f"BEST inside ({best_inside[0][:25]})", best_inside[5]),
        ("4°comp 25%", comp_4comp),
    ]

    print(f"\n  {'Valuta':6s}", end="")
    for label, _ in configs_to_show:
        print(f" {label:>18s}", end="")
    print()
    print("  " + "─" * (6 + 19 * len(configs_to_show)))

    for ccy in CURRENCIES:
        print(f"  {ccy:6s}", end="")
        for label, comp in configs_to_show:
            score = comp[ccy]["composite"]
            rank = sorted(CURRENCIES, key=lambda c: comp.get(c, {}).get("composite", 50),
                          reverse=True).index(ccy) + 1
            print(f" {score:>8.1f} (#{rank})", end="")
        print()

    # ── Top 5 setups confronto ──
    print("\n")
    print("=" * 95)
    print("  TOP 5 SETUPS — CONFRONTO")
    print("=" * 95)

    setups_to_show = [
        ("BASELINE", baseline[6]),
        (f"BEST inside", best_inside[6]),
        ("4°comp 25%", setups_4comp),
    ]

    for label, setups in setups_to_show:
        print(f"\n  ▸ {label}:")
        for i, s in enumerate(setups[:5], 1):
            r_str = " | ".join(s["reasons"][:3])
            print(f"    {i}. [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
                  f"Q={s['quality_score']:5.1f} Δ={s['differential']:+5.1f} — {r_str}")

    # ── Focus USD ──
    print("\n")
    print("=" * 95)
    print("  FOCUS USD")
    print("=" * 95)

    usd_configs = [
        ("BASELINE", baseline[5], baseline[6]),
        (f"BEST inside", best_inside[5], best_inside[6]),
        ("4°comp 25%", comp_4comp, setups_4comp),
    ]

    for label, comp, setups in usd_configs:
        usd_s = [s for s in setups if s["base"] == "USD" or s["quote"] == "USD"]
        usd_aa = [s for s in usd_s if s["grade"] in ("A+", "A")]
        usd_rank = sorted(CURRENCIES, key=lambda c: comp.get(c, {}).get("composite", 50),
                          reverse=True).index("USD") + 1
        print(f"\n  ▸ {label}  —  USD={comp['USD']['composite']:.1f} (#{usd_rank}), "
              f"{len(usd_s)} segnali, {len(usd_aa)} AA")
        for s in usd_s[:6]:
            print(f"    [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
                  f"Q={s['quality_score']:5.1f} Δ={s['differential']:+5.1f}")

    # ══════════════════════════════════════════════════════════════════════
    # CLASSIFICA FINALE
    # ══════════════════════════════════════════════════════════════════════
    print("\n")
    print("=" * 95)
    print("  CLASSIFICA FINALE — C9 DENTRO PA vs C9 COME 4° COMPONENTE")
    print("=" * 95)

    # Score composto
    scored = []
    for name, w_rsi, w_roc, w_ema, w_c9, comp, setups, m in all_results:
        score = (
            m["spread"] * 1.0 +
            m["n_aa"] * 8.0 +
            m["n_aplus"] * 5.0 +
            m["top5_avg_qs"] * 0.5 +
            m["top5_avg_diff"] * 0.5 +
            m["usd_aa"] * 15.0 -
            max(m["n_aa"] - 8, 0) * 3.0
        )
        scored.append((score, name, m, "INSIDE"))

    # Aggiungi il 4° componente per confronto
    score_4comp = (
        m_4comp["spread"] * 1.0 +
        m_4comp["n_aa"] * 8.0 +
        m_4comp["n_aplus"] * 5.0 +
        m_4comp["top5_avg_qs"] * 0.5 +
        m_4comp["top5_avg_diff"] * 0.5 +
        m_4comp["usd_aa"] * 15.0 -
        max(m_4comp["n_aa"] - 8, 0) * 3.0
    )
    scored.append((score_4comp, "[RIF] C9 4°comp 25%", m_4comp, "4TH_COMP"))

    scored.sort(reverse=True)

    print(f"\n  {'#':>3s} {'Score':>7s} {'Tipo':>10s} {'Config':<42s} "
          f"{'A+':>3s} {'A':>3s} {'Sprd':>5s} {'USD#':>4s}")
    print("  " + "─" * 85)

    for rank, (score, name, m, tipo) in enumerate(scored, 1):
        marker = " ◀◀ MIGLIORE" if rank == 1 else ""
        print(f"  {rank:>3d} [{score:6.1f}] {tipo:>10s} {name:<42s} "
              f"{m['n_aplus']:>3d} {m['n_a']:>3d} {m['spread']:>5.1f} "
              f"#{m['usd_rank']:<3d}{marker}")

    # Confronto diretto: migliore INSIDE vs 4° comp vs baseline
    best_inside_m = best_inside[7]
    baseline_m = baseline[7]

    print(f"\n  {'='*80}")
    print(f"  CONFRONTO DIRETTO")
    print(f"  {'='*80}")
    print(f"  {'Metrica':<20s} {'Baseline':>12s} {'Best INSIDE':>12s} {'4° Comp 25%':>12s}")
    print(f"  {'─'*20:20s} {'─'*12:>12s} {'─'*12:>12s} {'─'*12:>12s}")
    print(f"  {'A+ segnali':<20s} {baseline_m['n_aplus']:>12d} {best_inside_m['n_aplus']:>12d} {m_4comp['n_aplus']:>12d}")
    print(f"  {'A segnali':<20s} {baseline_m['n_a']:>12d} {best_inside_m['n_a']:>12d} {m_4comp['n_a']:>12d}")
    print(f"  {'A/A+ totali':<20s} {baseline_m['n_aa']:>12d} {best_inside_m['n_aa']:>12d} {m_4comp['n_aa']:>12d}")
    print(f"  {'B segnali':<20s} {baseline_m['n_b']:>12d} {best_inside_m['n_b']:>12d} {m_4comp['n_b']:>12d}")
    print(f"  {'Spread ranking':<20s} {baseline_m['spread']:>12.1f} {best_inside_m['spread']:>12.1f} {m_4comp['spread']:>12.1f}")
    print(f"  {'Top5 Quality':<20s} {baseline_m['top5_avg_qs']:>12.1f} {best_inside_m['top5_avg_qs']:>12.1f} {m_4comp['top5_avg_qs']:>12.1f}")
    print(f"  {'Top5 Δ medio':<20s} {baseline_m['top5_avg_diff']:>12.1f} {best_inside_m['top5_avg_diff']:>12.1f} {m_4comp['top5_avg_diff']:>12.1f}")
    print(f"  {'USD Score':<20s} {baseline_m['usd_score']:>12.1f} {best_inside_m['usd_score']:>12.1f} {m_4comp['usd_score']:>12.1f}")
    print(f"  {'USD Rank':<20s} {'#'+str(baseline_m['usd_rank']):>12s} {'#'+str(best_inside_m['usd_rank']):>12s} {'#'+str(m_4comp['usd_rank']):>12s}")
    print(f"  {'USD segnali AA':<20s} {baseline_m['usd_aa']:>12d} {best_inside_m['usd_aa']:>12d} {m_4comp['usd_aa']:>12d}")
    print()


if __name__ == "__main__":
    main()
