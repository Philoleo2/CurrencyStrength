"""
Simulazione Pesi Candle-9: trova il peso ottimale per integrare
il segnale Candle-9 (escursione + velocità) nello scoring.

Testa N configurazioni diverse di pesi e confronta:
  1. Spread del ranking (distanza tra più forte e più debole)
  2. Numero e qualità dei segnali A/A+
  3. Rilevamento USD (score, ranking, segnali)
  4. Differenziale medio dei top setups

Integra Candle-9 in DUE punti:
  A) Composito: PA*w1 + Volume*w2 + COT*w3 + C9*w4  (w1+w2+w3+w4=1)
  B) Trade setups: aggiunge un fattore #12 "Candle-9 momentum"
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from datetime import datetime

from config import (
    CURRENCIES, FOREX_PAIRS, FUTURES_TICKERS,
    MIN_DIFFERENTIAL_THRESHOLD,
)
from data_fetcher import fetch_all_pairs, fetch_all_futures
from cot_data import load_cot_data, compute_cot_scores
from strength_engine import (
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
# CANDLE-9 SCORE: escursione + velocità per valuta
# ═══════════════════════════════════════════════════════════════════════════════

def candle9_currency_score(all_pairs: dict[str, pd.DataFrame],
                            lookback: int = LOOKBACK) -> dict[str, float]:
    """
    Score 0-100 per valuta basato su:
      - Magnitude: % escursione close attuale vs close 9 candele fa
      - Velocity: pendenza lineare del close nelle ultime 9 candele
      - Consistency: % di candele nella stessa direzione
    """
    ccy_scores: dict[str, list[float]] = {c: [] for c in CURRENCIES}

    for pair_name, pair_df in all_pairs.items():
        if pair_df.empty or "Close" not in pair_df.columns:
            continue
        close = pair_df["Close"]
        if len(close) < lookback + 2:
            continue

        info = FOREX_PAIRS[pair_name]
        base, quote = info["base"], info["quote"]

        current_close = float(close.iloc[-1])
        past_close = float(close.iloc[-(lookback + 1)])
        if past_close == 0:
            continue

        # Magnitude: % change over lookback periods
        pct_change = ((current_close - past_close) / past_close) * 100

        # Velocity: slope lineare come % per candela
        recent = close.iloc[-(lookback + 1):]
        x = np.arange(len(recent))
        y = recent.values.astype(float)
        if len(x) >= 2 and not np.isnan(y).all():
            slope = np.polyfit(x, y, 1)[0]
            mean_price = np.mean(y)
            slope_pct = (slope / mean_price) * 100 if mean_price > 0 else 0
        else:
            slope_pct = 0

        # Consistency: quante candele consecutive nella stessa direzione
        diffs = recent.diff().dropna()
        if len(diffs) > 0:
            if pct_change > 0:
                consistency = float((diffs > 0).sum() / len(diffs))
            elif pct_change < 0:
                consistency = float((diffs < 0).sum() / len(diffs))
            else:
                consistency = 0.0
        else:
            consistency = 0.0

        # Sub-scores
        magnitude_score = 50 + np.clip(pct_change * 25, -50, 50)
        velocity_score = 50 + np.clip(slope_pct * 200, -50, 50)
        consistency_bonus = consistency * 10

        pair_score = (
            magnitude_score * 0.50 +
            velocity_score * 0.35 +
            (50 + consistency_bonus) * 0.15
        )
        pair_score = float(np.clip(pair_score, 0, 100))

        if base in ccy_scores:
            ccy_scores[base].append(pair_score)
        if quote in ccy_scores:
            ccy_scores[quote].append(100 - pair_score)

    return {ccy: round(float(np.mean(vals)), 2) if vals else 50.0
            for ccy, vals in ccy_scores.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# COMPOSITO CON CANDLE-9 INTEGRATO
# ═══════════════════════════════════════════════════════════════════════════════

def composite_with_c9(
    price_scores: dict[str, float],
    volume_scores: dict[str, float],
    cot_scores: dict[str, dict],
    c9_scores: dict[str, float],
    w_pa: float, w_vol: float, w_cot: float, w_c9: float,
) -> dict[str, dict]:
    """Composito 4-componenti con Candle-9."""
    results = {}
    for ccy in CURRENCIES:
        pa = price_scores.get(ccy, 50)
        vol = volume_scores.get(ccy, 50)
        cot = cot_scores.get(ccy, {}).get("score", 50)
        c9 = c9_scores.get(ccy, 50)

        composite = pa * w_pa + vol * w_vol + cot * w_cot + c9 * w_c9
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
            "c9_score": round(c9, 1),
            "composite": composite,
            "label": label,
            "alert": alert,
            "cot_bias": cot_info.get("bias", "NEUTRAL"),
            "cot_extreme": cot_info.get("extreme"),
        }
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE SETUPS CON CANDLE-9 COME FATTORE #12
# ═══════════════════════════════════════════════════════════════════════════════

def setups_with_c9(
    composite: dict[str, dict],
    momentum: dict[str, dict],
    classification: dict[str, dict],
    atr_context: dict[str, dict],
    cot_scores: dict[str, dict],
    velocity_scores: dict[str, dict],
    trend_structure: dict[str, dict],
    strength_persistence: dict[str, dict],
    candle9: dict[str, dict],
    c9_weight: int,          # max punti per Candle-9 nel quality score
) -> list[dict]:
    """
    Identico a compute_trade_setups ma aggiunge il fattore Candle-9.
    c9_weight = max punti assegnabili (es. 10, 15, 20).
    """
    from config import (
        EXCLUDED_PAIRS, CORRELATION_GROUPS,
        SESSION_CURRENCY_AFFINITY, COT_STALE_DAYS_THRESHOLD,
    )
    _EXCLUDED_SET = {frozenset(p.split("/")) for p in EXCLUDED_PAIRS} if hasattr(__import__('config'), 'EXCLUDED_PAIRS') else set()

    setups = []
    for base in CURRENCIES:
        for quote in CURRENCIES:
            if base == quote:
                continue
            s_base = composite[base]["composite"]
            s_quote = composite[quote]["composite"]
            diff = s_base - s_quote
            if abs(diff) < MIN_DIFFERENTIAL_THRESHOLD:
                continue

            direction = "LONG" if diff > 0 else "SHORT"
            strong_ccy = base if diff > 0 else quote
            weak_ccy = quote if diff > 0 else base

            quality = 0
            reasons = []

            # 1. Differenziale (0-30)
            diff_abs = abs(diff)
            quality += min(diff_abs * 1.0, 30)
            if diff_abs >= 20:
                reasons.append(f"Δ forte ({diff_abs:.0f})")
            elif diff_abs >= 12:
                reasons.append(f"Δ buono ({diff_abs:.0f})")

            # 2. Momentum (0-20)
            mom_s = momentum.get(strong_ccy, {}).get("delta", 0)
            mom_w = momentum.get(weak_ccy, {}).get("delta", 0)
            if mom_s > 0 and mom_w < 0:
                quality += 20
                reasons.append("Momentum allineato")
            elif mom_s > 0 or mom_w < 0:
                quality += 6

            # 2b. Sinergia (0-5)
            if diff_abs >= 15 and mom_s > 0 and mom_w < 0:
                quality += 5
                reasons.append("Sinergia diff+mom")

            # 3. Trend regime (0-15)
            cls_s = classification.get(strong_ccy, {})
            if cls_s.get("classification") == "TREND_FOLLOWING":
                quality += 15
                reasons.append(f"{strong_ccy} trending")
            elif cls_s.get("classification") == "MIXED":
                quality += 5

            # 4. Volatilità (0-15)
            vol_s = atr_context.get(strong_ccy, {}).get("volatility_regime", "NORMAL")
            vol_w = atr_context.get(weak_ccy, {}).get("volatility_regime", "NORMAL")
            if vol_s in ("NORMAL", "LOW"):
                quality += 10
            elif vol_s == "HIGH":
                quality += 5
            if vol_s == "EXTREME" or vol_w == "EXTREME":
                quality -= 5

            # 5. COT (0-10)
            cot_s = cot_scores.get(strong_ccy, {})
            cot_w = cot_scores.get(weak_ccy, {})
            cot_mult = 0.5 if max(cot_s.get("freshness_days", 0),
                                   cot_w.get("freshness_days", 0)) > COT_STALE_DAYS_THRESHOLD else 1.0
            cot_pts = 0
            if cot_s.get("bias") == "BULLISH":
                cot_pts += 5
                reasons.append(f"COT {strong_ccy} bull")
            if cot_w.get("bias") == "BEARISH":
                cot_pts += 5
            quality += cot_pts * cot_mult
            if cot_s.get("extreme") == "CROWDED_LONG":
                quality -= 10
            if cot_w.get("extreme") == "CROWDED_SHORT":
                quality -= 10

            # 6. Concordanza H1/H4 (0-10)
            conc = composite[strong_ccy].get("concordance", "")
            sc = composite[strong_ccy].get("composite", 50)
            if "ALLINEATI" in conc:
                quality += 4 if sc >= 80 else 10

            # 7. Velocity (0-10)
            vel_s = velocity_scores.get(strong_ccy, {}).get("velocity_norm", 50)
            if vel_s >= 65:
                quality += 10
            elif vel_s >= 40:
                quality += 5

            # 8. Trend structure (0-8)
            al_s = trend_structure.get(strong_ccy, {}).get("ema_alignment", 0)
            al_w = trend_structure.get(weak_ccy, {}).get("ema_alignment", 0)
            if al_s >= 0.4 and al_w <= -0.4:
                quality += 8
            elif al_s >= 0.2 or al_w <= -0.2:
                quality += 4
            if al_s <= -0.3:
                quality -= 5

            # 9. Momentum acceleration (0-5)
            acc_s = momentum.get(strong_ccy, {}).get("acceleration", 0)
            acc_w = momentum.get(weak_ccy, {}).get("acceleration", 0)
            if acc_s > 0 and acc_w < 0:
                quality += 5
            elif acc_s > 0 or acc_w < 0:
                quality += 2
            if acc_s < 0 and mom_s <= 0:
                quality -= 3

            # 10. Persistence (0-8)
            p_s = strength_persistence.get(strong_ccy, {}).get("persistence", 0)
            p_w = strength_persistence.get(weak_ccy, {}).get("persistence", 0)
            if p_s >= 0.5 and p_w <= -0.5:
                quality += 8
            elif p_s >= 0.3 or p_w <= -0.3:
                quality += 4
            if abs(p_s) < 0.2 and abs(p_w) < 0.2:
                quality -= 3

            # ============================================================
            # 12. CANDLE-9: ESCURSIONE + VELOCITÀ (0-c9_weight punti)
            # ============================================================
            c9_s = candle9.get(strong_ccy, {})
            c9_w = candle9.get(weak_ccy, {})
            c9_ratio_s = c9_s.get("candle9_ratio", 0)
            c9_ratio_w = c9_w.get("candle9_ratio", 0)

            c9_pts = 0
            # Bonus: valuta forte ha C9 bullish E debole ha C9 bearish
            if c9_ratio_s > 0.05 and c9_ratio_w < -0.05:
                c9_pts = c9_weight
                reasons.append(f"C9 allineato ({c9_ratio_s:+.2f}% vs {c9_ratio_w:+.2f}%)")
            elif c9_ratio_s > 0.05 or c9_ratio_w < -0.05:
                c9_pts = int(c9_weight * 0.4)
                reasons.append(f"C9 parziale ({c9_ratio_s:+.2f}%)")
            # Extra: magnitude bonus proporzionale alla grandezza
            c9_magnitude = abs(c9_ratio_s) + abs(c9_ratio_w)
            if c9_magnitude > 0.5:
                c9_pts += min(int(c9_magnitude * 3), int(c9_weight * 0.4))

            # Penalità: C9 contrario alla direzione del trade
            if c9_ratio_s < -0.1:
                c9_pts = -int(c9_weight * 0.5)
                reasons.append(f"⚠️ C9 contrario ({c9_ratio_s:+.2f}%)")

            quality += c9_pts
            quality = max(quality, 0)

            # Grade
            if quality >= 75:
                grade = "A+"
            elif quality >= 60:
                grade = "A"
            elif quality >= 45:
                grade = "B"
            elif quality >= 30:
                grade = "C"
            else:
                grade = "D"

            pair_label = f"{base}/{quote}"
            pair_key = f"{base}{quote}"
            reverse_key = f"{quote}{base}"
            actual_pair = pair_key if pair_key in FOREX_PAIRS else (
                reverse_key if reverse_key in FOREX_PAIRS else pair_label
            )

            setups.append({
                "pair": pair_label,
                "actual_pair": actual_pair,
                "base": base,
                "quote": quote,
                "direction": direction,
                "differential": round(diff, 1),
                "quality_score": round(quality, 1),
                "grade": grade,
                "reasons": reasons,
                "strong_score": round(s_base if diff > 0 else s_quote, 1),
                "weak_score": round(s_quote if diff > 0 else s_base, 1),
            })

    setups.sort(key=lambda x: x["quality_score"], reverse=True)

    # Dedup
    seen = set()
    unique = []
    for s in setups:
        canon = tuple(sorted([s["base"], s["quote"]]))
        if canon not in seen:
            seen.add(canon)
            unique.append(s)

    # Escludi coppie escluse
    try:
        from config import EXCLUDED_PAIRS
        excluded_set = {frozenset(p.split("/")) for p in EXCLUDED_PAIRS}
        unique = [s for s in unique if frozenset({s["base"], s["quote"]}) not in excluded_set]
    except (ImportError, AttributeError):
        pass

    return unique


# ═══════════════════════════════════════════════════════════════════════════════
# METRICHE DI VALUTAZIONE
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_config(composite: dict[str, dict], setups: list[dict]) -> dict:
    """Calcola metriche per confrontare le configurazioni."""
    scores = [v["composite"] for v in composite.values()]
    spread = max(scores) - min(scores)
    std = float(np.std(scores))

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
        "std": round(std, 1),
        "n_aplus": n_aplus,
        "n_a": n_a,
        "n_aa": n_aa,
        "n_b": n_b,
        "n_total": len(setups),
        "top5_avg_qs": round(top5_avg_qs, 1),
        "top5_avg_diff": round(top5_avg_diff, 1),
        "usd_score": round(usd_score, 1),
        "usd_rank": usd_rank,
        "usd_aa_signals": len(usd_aa),
        "usd_total_signals": len(usd_setups),
        "grade_dist": grade_dist,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURAZIONI DA TESTARE
# ═══════════════════════════════════════════════════════════════════════════════

CONFIGS = [
    # (nome, w_PA, w_Vol, w_COT, w_C9_composite, c9_quality_max_pts)
    # --- Baseline ---
    ("BASELINE (no C9)",          0.40, 0.30, 0.30, 0.00, 0),
    # --- C9 peso leggero ---
    ("C9 leggero 10%",           0.35, 0.25, 0.30, 0.10, 8),
    ("C9 leggero 10% +setup15",  0.35, 0.25, 0.30, 0.10, 15),
    # --- C9 peso medio ---
    ("C9 medio 15%",             0.30, 0.25, 0.30, 0.15, 12),
    ("C9 medio 15% +setup20",   0.30, 0.25, 0.30, 0.15, 20),
    ("C9 medio 20%",             0.30, 0.20, 0.30, 0.20, 15),
    # --- C9 peso alto ---
    ("C9 alto 25%",              0.25, 0.20, 0.30, 0.25, 18),
    ("C9 alto 25% +setup25",    0.25, 0.20, 0.30, 0.25, 25),
    # --- C9 peso dominante ---
    ("C9 dominante 30%",         0.25, 0.15, 0.30, 0.30, 20),
    # --- Variazioni con meno COT ---
    ("C9 20% COT ridotto",       0.30, 0.25, 0.25, 0.20, 15),
    ("C9 25% bilanciato",        0.25, 0.25, 0.25, 0.25, 18),
]


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 90)
    print("  SIMULAZIONE PESI CANDLE-9 — Trova il peso ottimale")
    print("=" * 90)
    print()

    # ── Fetch data ──
    print("📊 Scaricamento dati...")
    all_h4 = fetch_all_pairs("H4")
    all_h1 = fetch_all_pairs("H1")
    futures = fetch_all_futures("H4")
    cot_raw = load_cot_data()
    cot_scores = compute_cot_scores(cot_raw)
    print(f"   H4: {len(all_h4)}, H1: {len(all_h1)}, Futures: {len(futures)}, COT: {len(cot_scores)}")

    # ── Dati comuni (calcolati una volta) ──
    print("\n📈 Calcolo componenti base...")
    price_scores_h4 = compute_price_action_scores(all_h4)
    price_scores_h1 = compute_price_action_scores(all_h1)
    volume_scores = compute_volume_scores(all_h4, futures, price_scores_h4)
    c9_scores_h4 = candle9_currency_score(all_h4, LOOKBACK)
    c9_scores_h1 = candle9_currency_score(all_h1, LOOKBACK)
    c9_detail = compute_candle9_signal(all_h4)

    # Blend H1/H4 per C9 (60% H4 + 40% H1)
    c9_blended = {ccy: round(c9_scores_h4.get(ccy, 50) * 0.6 + c9_scores_h1.get(ccy, 50) * 0.4, 2)
                  for ccy in CURRENCIES}

    # Analisi completa per ottenere momentum, classification, ecc.
    analysis_h4 = full_analysis(all_h4, futures, cot_scores)
    analysis_h1 = full_analysis(all_h1, futures, cot_scores)
    blended = blend_multi_timeframe(analysis_h1, analysis_h4)
    momentum = blended["momentum"]
    classification = blended["classification"]
    atr_context = blended["atr_context"]
    velocity = blended["velocity"]
    trend_struct = blended["trend_structure"]
    persistence = blended["strength_persistence"]
    candle9_data = blended["candle9"]

    # ── Candle-9 raw per valuta ──
    print("\n📉 Candle-9 raw (escursione 9 candele H4):")
    sorted_c9 = sorted(c9_detail.items(), key=lambda x: x[1]["candle9_ratio"], reverse=True)
    for ccy, info in sorted_c9:
        r = info["candle9_ratio"]
        sig = info["candle9_signal"]
        bar_len = int(abs(r) * 20)
        if r > 0:
            bar = "▓" * min(bar_len, 25) + "░" * max(0, 25 - bar_len)
            print(f"  {ccy:4s}  {r:+.3f}%  {sig:15s}  +|{bar}")
        else:
            bar = "░" * max(0, 25 - bar_len) + "▓" * min(bar_len, 25)
            print(f"  {ccy:4s}  {r:+.3f}%  {sig:15s}  {bar}|-")

    print(f"\n  C9 Score (0-100, 50=neutro):")
    for ccy in sorted(CURRENCIES, key=lambda c: c9_blended.get(c, 50), reverse=True):
        s = c9_blended[ccy]
        bar = "█" * int(s / 2) + "░" * (50 - int(s / 2))
        print(f"  {ccy:4s}  {s:5.1f}  {bar}")

    # ══════════════════════════════════════════════════════════════════════
    # SIMULAZIONE DI TUTTE LE CONFIGURAZIONI
    # ══════════════════════════════════════════════════════════════════════
    print("\n")
    print("=" * 90)
    print("  TEST CONFIGURAZIONI")
    print("=" * 90)

    results = []

    for name, w_pa, w_vol, w_cot, w_c9, c9_q_pts in CONFIGS:
        # Composito con C9 integrato
        comp = composite_with_c9(
            price_scores_h4, volume_scores, cot_scores, c9_blended,
            w_pa, w_vol, w_cot, w_c9,
        )

        # Trade setups con C9 come fattore
        setups = setups_with_c9(
            comp, momentum, classification, atr_context, cot_scores,
            velocity, trend_struct, persistence, candle9_data, c9_q_pts,
        )

        metrics = evaluate_config(comp, setups)
        metrics["name"] = name
        metrics["w_c9"] = w_c9
        metrics["c9_q_pts"] = c9_q_pts
        results.append((name, w_pa, w_vol, w_cot, w_c9, c9_q_pts, comp, setups, metrics))

    # ── Tabella riassuntiva ──
    print(f"\n{'Config':<28s} {'C9%':>4s} {'QP':>3s} {'Sprd':>5s} "
          f"{'A+':>3s} {'A':>3s} {'A/A+':>4s} {'B':>3s} "
          f"{'Top5Q':>6s} {'Top5Δ':>6s} "
          f"{'USD':>5s} {'#':>2s} {'USDsig':>6s}")
    print("─" * 90)

    for name, w_pa, w_vol, w_cot, w_c9, c9_q, comp, setups, m in results:
        print(f"{name:<28s} {w_c9*100:>3.0f}% {c9_q:>3d} {m['spread']:>5.1f} "
              f"{m['n_aplus']:>3d} {m['n_a']:>3d} {m['n_aa']:>4d} {m['n_b']:>3d} "
              f"{m['top5_avg_qs']:>6.1f} {m['top5_avg_diff']:>6.1f} "
              f"{m['usd_score']:>5.1f} #{m['usd_rank']:<1d} {m['usd_aa_signals']:>3d}AA")

    # ── Dettaglio per ogni config: ranking valute ──
    print("\n")
    print("=" * 90)
    print("  RANKING VALUTE PER CONFIGURAZIONE")
    print("=" * 90)

    header = f"  {'Valuta':6s}"
    for name, *_ in results:
        short = name[:12]
        header += f" {short:>13s}"
    print(header)
    print("  " + "─" * (6 + 14 * len(results)))

    for ccy in CURRENCIES:
        row = f"  {ccy:6s}"
        for name, w_pa, w_vol, w_cot, w_c9, c9_q, comp, setups, m in results:
            score = comp[ccy]["composite"]
            rank = sorted(CURRENCIES, key=lambda c: comp.get(c, {}).get("composite", 50), reverse=True).index(ccy) + 1
            row += f" {score:>6.1f} (#{rank})"
        print(row)

    # ── Top 5 setups per ogni config ──
    print("\n")
    print("=" * 90)
    print("  TOP 5 SETUPS PER CONFIGURAZIONE")
    print("=" * 90)

    for name, w_pa, w_vol, w_cot, w_c9, c9_q, comp, setups, m in results:
        print(f"\n  ▸ {name} (C9={w_c9*100:.0f}%, QP={c9_q})")
        print(f"    Distribuzione: {m['grade_dist']}")
        for i, s in enumerate(setups[:5], 1):
            r_str = " | ".join(s["reasons"][:3])
            print(f"    {i}. [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
                  f"Q={s['quality_score']:5.1f} Δ={s['differential']:+5.1f} — {r_str}")

    # ── FOCUS USD per ogni config ──
    print("\n")
    print("=" * 90)
    print("  FOCUS USD — SEGNALI PER CONFIGURAZIONE")
    print("=" * 90)

    for name, w_pa, w_vol, w_cot, w_c9, c9_q, comp, setups, m in results:
        usd_setups = [s for s in setups if s["base"] == "USD" or s["quote"] == "USD"]
        usd_aa = [s for s in usd_setups if s["grade"] in ("A+", "A")]
        print(f"\n  ▸ {name}  —  USD={m['usd_score']:.1f} (#{m['usd_rank']}), "
              f"segnali: {len(usd_setups)} tot, {len(usd_aa)} AA")
        for s in usd_setups[:5]:
            print(f"    [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
                  f"Q={s['quality_score']:5.1f} Δ={s['differential']:+5.1f}")

    # ══════════════════════════════════════════════════════════════════════
    # SCORE COMPOSTO PER TROVARE L'OTTIMALE
    # ══════════════════════════════════════════════════════════════════════
    print("\n")
    print("=" * 90)
    print("  CLASSIFICA FINALE — SCORE COMPOSTO")
    print("=" * 90)
    print("  (Spread×1.0 + A/A+×8 + Top5Q×0.5 + Top5Δ×0.5 + USD_AA×15 - penalità se troppi segnali)")
    print()

    scored = []
    for name, w_pa, w_vol, w_cot, w_c9, c9_q, comp, setups, m in results:
        # Punteggio composto per confronto
        score = (
            m["spread"] * 1.0 +          # spread alto = buona discriminazione
            m["n_aa"] * 8.0 +             # segnali A/A+ pesano molto
            m["n_aplus"] * 5.0 +          # A+ extra bonus  
            m["top5_avg_qs"] * 0.5 +      # qualità top setups
            m["top5_avg_diff"] * 0.5 +    # differenziale forte
            m["usd_aa_signals"] * 15.0 -  # USD A/A+ = grande bonus
            max(m["n_aa"] - 8, 0) * 3.0   # penalità troppi A/A+ (inflazione)
        )
        scored.append((score, name, m))

    scored.sort(reverse=True)
    for rank, (score, name, m) in enumerate(scored, 1):
        marker = " ◀◀ MIGLIORE" if rank == 1 else ""
        print(f"  {rank}. [{score:6.1f}] {name:<28s}  "
              f"A+={m['n_aplus']} A={m['n_a']} B={m['n_b']} "
              f"Spread={m['spread']:.1f} USD=#{m['usd_rank']}{marker}")

    # Raccomandazione
    best_name = scored[0][1]
    best_m = scored[0][2]
    baseline_m = results[0][8]  # index 0 = BASELINE

    print(f"\n  {'='*70}")
    print(f"  RACCOMANDAZIONE: {best_name}")
    print(f"  {'='*70}")
    print(f"  vs BASELINE:")
    print(f"    A/A+ : {baseline_m['n_aa']} → {best_m['n_aa']} ({best_m['n_aa'] - baseline_m['n_aa']:+d})")
    print(f"    Spread: {baseline_m['spread']:.1f} → {best_m['spread']:.1f}")
    print(f"    Top5 Q: {baseline_m['top5_avg_qs']:.1f} → {best_m['top5_avg_qs']:.1f}")
    print(f"    USD AA: {baseline_m['usd_aa_signals']} → {best_m['usd_aa_signals']}")
    print(f"    USD rank: #{baseline_m['usd_rank']} → #{best_m['usd_rank']}")
    print()


if __name__ == "__main__":
    main()
