"""
Simulazione: Scoring Candle-9 Semplificato vs Scoring Attuale
=============================================================
Confronta la classifica corrente (RSI+ROC+EMA+momentum+trend+volatilità+etc.)
con un sistema semplificato basato SOLO su:
  - Candle-9: confronto close attuale vs close 9 periodi fa
    + direzione (maggiore/minore/uguale)
    + magnitude del movimento (%)
    + velocità (tempo impiegato / pendenza)
  - Volume (amplifica/attenua)
  - COT (bias istituzionale)

Nessun altro indicatore.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
from datetime import datetime, timezone

from config import (
    CURRENCIES, FOREX_PAIRS, FUTURES_TICKERS,
    WEIGHT_VOLUME, WEIGHT_COT,
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

LOOKBACK = 9  # confronto con 9 candele fa


# ═══════════════════════════════════════════════════════════════════════════════
# NUOVO SCORING: Candle-9 + Velocità + Volume + COT
# ═══════════════════════════════════════════════════════════════════════════════

def candle9_price_score(all_pairs: dict[str, pd.DataFrame],
                        lookback: int = LOOKBACK) -> dict[str, float]:
    """
    Score 0-100 per valuta basato SOLO sul confronto close attuale vs
    close di `lookback` candele fa.
    
    Componenti:
    1. Direzione: close > close_9 → bullish, < → bearish  
    2. Magnitude: |% change| più è grande più è forte
    3. Velocità: pendenza media del close nelle ultime 9 candele
       (quanto velocemente si muove e in che direzione)
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

        # ── 1. Magnitude: % change over 9 periods ──
        pct_change = ((current_close - past_close) / past_close) * 100

        # ── 2. Velocità: pendenza lineare del close nelle ultime N candele ──
        # Normalizzata come % per candela
        recent_segment = close.iloc[-(lookback + 1):]
        x = np.arange(len(recent_segment))
        y = recent_segment.values.astype(float)
        if len(x) >= 2 and not np.isnan(y).all():
            slope = np.polyfit(x, y, 1)[0]
            # Normalizza: slope come % del prezzo medio
            mean_price = np.mean(y)
            if mean_price > 0:
                slope_pct = (slope / mean_price) * 100  # % per candela
            else:
                slope_pct = 0
        else:
            slope_pct = 0

        # ── 3. Consistenza: quante delle 9 candele consecutive vanno nella
        #    stessa direzione? ──
        diffs = recent_segment.diff().dropna()
        if len(diffs) > 0:
            if pct_change > 0:
                consistency = float((diffs > 0).sum() / len(diffs))
            elif pct_change < 0:
                consistency = float((diffs < 0).sum() / len(diffs))
            else:
                consistency = 0.0
        else:
            consistency = 0.0

        # ── Combina in score ──
        # magnitude_score: sigmoid-like, scala pct_change a 0-100
        # ±2% → circa ±50 punti dalla base 50
        magnitude_score = 50 + np.clip(pct_change * 25, -50, 50)

        # velocity_score: slope_pct normalizzato
        velocity_score = 50 + np.clip(slope_pct * 200, -50, 50)

        # consistency_bonus: 0-10 punti
        consistency_bonus = consistency * 10

        # Score finale per coppia (weighted)
        pair_score = (
            magnitude_score * 0.50 +
            velocity_score * 0.35 +
            (50 + consistency_bonus) * 0.15
        )
        pair_score = float(np.clip(pair_score, 0, 100))

        # Base: coppia sale = base forte
        if base in ccy_scores:
            ccy_scores[base].append(pair_score)
        # Quote: coppia sale = quote debole → inverti
        if quote in ccy_scores:
            ccy_scores[quote].append(100 - pair_score)

    return {ccy: round(float(np.mean(vals)), 2) if vals else 50.0
            for ccy, vals in ccy_scores.items()}


def new_composite_scores(
    c9_price: dict[str, float],
    volume_scores: dict[str, float],
    cot_scores: dict[str, dict],
) -> dict[str, dict]:
    """
    Composito NUOVO: solo Candle-9 Price + Volume + COT.
    Pesi: Price 50%, Volume 25%, COT 25%.
    """
    results = {}
    for ccy in CURRENCIES:
        pa = c9_price.get(ccy, 50)
        vol = volume_scores.get(ccy, 50)
        cot = cot_scores.get(ccy, {}).get("score", 50)

        composite = pa * 0.50 + vol * 0.25 + cot * 0.25
        composite = round(float(np.clip(composite, 0, 100)), 1)

        if composite >= 65:
            label = "VERY STRONG" if composite >= 75 else "STRONG"
        elif composite <= 35:
            label = "VERY WEAK" if composite <= 25 else "WEAK"
        else:
            label = "NEUTRAL"

        results[ccy] = {
            "price_score": round(pa, 1),
            "volume_score": round(vol, 1),
            "cot_score": round(cot, 1),
            "composite": composite,
            "label": label,
            "alert": None,
            "cot_bias": cot_scores.get(ccy, {}).get("bias", "NEUTRAL"),
            "cot_extreme": cot_scores.get(ccy, {}).get("extreme"),
        }
    return results


def new_trade_setups(
    composite: dict[str, dict],
    cot_scores: dict[str, dict],
    all_pairs: dict[str, pd.DataFrame],
) -> list[dict]:
    """
    Trade setups SEMPLIFICATI: solo differenziale Candle-9 + Volume + COT.
    Nessun momentum, nessuna classificazione, nessuna EMA cascade, nessuna sessione.
    
    Punteggio quality 0-100:
      - Differenziale composito     : 0-35 punti
      - COT concordante             : 0-15 punti
      - Candle-9 magnitude          : 0-25 punti  
      - Candle-9 consistency        : 0-15 punti
      - Volume confirmation         : 0-10 punti
    """
    from config import EXCLUDED_PAIRS, CORRELATION_GROUPS
    
    _excluded = {frozenset({p[:3], p[3:]}) for p in EXCLUDED_PAIRS}
    
    # Pre-compute candle9 raw data per pair
    c9_raw: dict[str, dict] = {}
    for pair_name, pair_df in all_pairs.items():
        if pair_df.empty or "Close" not in pair_df.columns:
            continue
        close = pair_df["Close"]
        if len(close) < LOOKBACK + 2:
            continue
        info = FOREX_PAIRS[pair_name]
        current = float(close.iloc[-1])
        past = float(close.iloc[-(LOOKBACK + 1)])
        if past == 0:
            continue
        pct = ((current - past) / past) * 100
        
        # Consistency
        seg = close.iloc[-(LOOKBACK + 1):]
        diffs = seg.diff().dropna()
        if len(diffs) > 0:
            if pct > 0:
                cons = float((diffs > 0).sum() / len(diffs))
            elif pct < 0:
                cons = float((diffs < 0).sum() / len(diffs))
            else:
                cons = 0.0
        else:
            cons = 0.0
        
        c9_raw[pair_name] = {"pct": pct, "consistency": cons}
    
    setups = []
    
    for base in CURRENCIES:
        for quote in CURRENCIES:
            if base == quote:
                continue
            if frozenset({base, quote}) in _excluded:
                continue
                
            s_base = composite[base]["composite"]
            s_quote = composite[quote]["composite"]
            diff = s_base - s_quote
            
            if abs(diff) < 8:
                continue
                
            direction = "LONG" if diff > 0 else "SHORT"
            strong_ccy = base if diff > 0 else quote
            weak_ccy = quote if diff > 0 else base
            
            quality = 0
            reasons = []
            
            # ── 1. Differenziale composito (0-35) ──
            diff_abs = abs(diff)
            diff_pts = min(diff_abs * 1.2, 35)
            quality += diff_pts
            if diff_abs >= 20:
                reasons.append(f"Δ forte ({diff_abs:.0f})")
            elif diff_abs >= 12:
                reasons.append(f"Δ buono ({diff_abs:.0f})")
            
            # ── 2. Candle-9 magnitude per coppie correlate (0-25) ──
            pair_key = f"{base}{quote}"
            rev_key = f"{quote}{base}"
            c9_pct_list = []
            for pn in all_pairs:
                info = FOREX_PAIRS.get(pn, {})
                b, q = info.get("base", ""), info.get("quote", "")
                if (b == base and q == quote) or (b == quote and q == base):
                    if pn in c9_raw:
                        pct_raw = c9_raw[pn]["pct"]
                        # Adjust sign: if base=pair base → positive pct = strong base
                        if b == base:
                            c9_pct_list.append(pct_raw)
                        else:
                            c9_pct_list.append(-pct_raw)
            
            if not c9_pct_list:
                # Use currency-level averages
                strong_avg = np.mean([
                    c9_raw[pn]["pct"] * (1 if FOREX_PAIRS[pn]["base"] == strong_ccy else -1)
                    for pn in c9_raw
                    if FOREX_PAIRS[pn]["base"] == strong_ccy or FOREX_PAIRS[pn]["quote"] == strong_ccy
                ]) if any(
                    FOREX_PAIRS[pn]["base"] == strong_ccy or FOREX_PAIRS[pn]["quote"] == strong_ccy
                    for pn in c9_raw
                ) else 0
                c9_pct_list = [strong_avg]
            
            avg_c9 = float(np.mean(c9_pct_list)) if c9_pct_list else 0
            # Direction should be positive for our trade direction
            if direction == "LONG":
                c9_aligned = avg_c9 > 0
            else:
                c9_aligned = avg_c9 < 0
                
            c9_magnitude = abs(avg_c9)
            c9_pts = min(c9_magnitude * 12, 25) if c9_aligned else 0
            quality += c9_pts
            if c9_aligned and c9_magnitude >= 0.5:
                reasons.append(f"C9 allineato ({avg_c9:+.2f}%)")
            elif not c9_aligned and c9_magnitude >= 0.3:
                reasons.append(f"⚠️ C9 contrario ({avg_c9:+.2f}%)")
                quality -= 5
            
            # ── 3. Candle-9 consistency (0-15) ──
            cons_vals = []
            for pn in c9_raw:
                info = FOREX_PAIRS.get(pn, {})
                b, q = info.get("base", ""), info.get("quote", "")
                if b == strong_ccy or q == strong_ccy:
                    cons_vals.append(c9_raw[pn]["consistency"])
            avg_cons = float(np.mean(cons_vals)) if cons_vals else 0
            cons_pts = avg_cons * 15
            quality += cons_pts
            if avg_cons >= 0.6:
                reasons.append(f"Consistenza alta ({avg_cons:.0%})")
            
            # ── 4. COT (0-15) ──
            cot_strong = cot_scores.get(strong_ccy, {}).get("bias", "NEUTRAL")
            cot_weak = cot_scores.get(weak_ccy, {}).get("bias", "NEUTRAL")
            cot_pts = 0
            if cot_strong == "BULLISH":
                cot_pts += 7.5
                reasons.append(f"COT {strong_ccy} bullish")
            if cot_weak == "BEARISH":
                cot_pts += 7.5
                reasons.append(f"COT {weak_ccy} bearish")
            quality += cot_pts
            
            # Penalità COT crowded
            cot_s_ext = cot_scores.get(strong_ccy, {}).get("extreme")
            cot_w_ext = cot_scores.get(weak_ccy, {}).get("extreme")
            if cot_s_ext == "CROWDED_LONG":
                quality -= 10
                reasons.append("⚠️ COT crowded long")
            if cot_w_ext == "CROWDED_SHORT":
                quality -= 10
                reasons.append("⚠️ COT crowded short")
            
            # ── 5. Volume confirmation (0-10) ──
            vol_s = composite[strong_ccy].get("volume_score", 50)
            vol_w = composite[weak_ccy].get("volume_score", 50)
            if vol_s > 55 and vol_w < 45:
                quality += 10
                reasons.append("Volume conferma")
            elif vol_s > 50 or vol_w < 50:
                quality += 5
            
            quality = max(quality, 0)
            
            # Grade
            if quality >= 70:
                grade = "A+"
            elif quality >= 55:
                grade = "A"
            elif quality >= 40:
                grade = "B"
            elif quality >= 25:
                grade = "C"
            else:
                grade = "D"
            
            pair_label = f"{base}/{quote}"
            actual_pair = pair_key if pair_key in FOREX_PAIRS else (
                rev_key if rev_key in FOREX_PAIRS else pair_label)
            
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
    
    # Deduplica
    seen = set()
    unique = []
    for s in setups:
        canon = tuple(sorted([s["base"], s["quote"]]))
        if canon not in seen:
            seen.add(canon)
            unique.append(s)
    
    return unique


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN: CONFRONTO
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("  SIMULAZIONE: Scoring Candle-9 Semplificato vs Scoring Attuale")
    print("=" * 80)
    print()

    # ── 1. Fetch data ──
    print("📊 Scaricamento dati H4...")
    all_h4 = fetch_all_pairs("H4")
    print(f"   {len(all_h4)} coppie H4 scaricate")

    print("📊 Scaricamento dati H1...")
    all_h1 = fetch_all_pairs("H1")
    print(f"   {len(all_h1)} coppie H1 scaricate")

    print("📊 Scaricamento futures...")
    futures = fetch_all_futures("H4")
    print(f"   {len(futures)} futures scaricati")

    print("📊 Caricamento COT...")
    cot_raw = load_cot_data()
    cot_scores = compute_cot_scores(cot_raw)
    print(f"   {len(cot_scores)} valute COT")
    print()

    # ── 2. SISTEMA ATTUALE (full analysis) ──
    print("━" * 80)
    print("  SISTEMA ATTUALE")
    print("━" * 80)
    
    analysis_h4 = full_analysis(all_h4, futures, cot_scores)
    analysis_h1 = full_analysis(all_h1, futures, cot_scores)
    
    blended = blend_multi_timeframe(analysis_h1, analysis_h4)
    composite_old = blended["composite"]
    momentum_old = blended["momentum"]
    classification_old = blended["classification"]
    atr_old = blended["atr_context"]
    velocity_old = blended["velocity"]
    trend_struct_old = blended["trend_structure"]
    persistence_old = blended["strength_persistence"]

    print("\n📈 Classifica Forza (attuale):")
    sorted_old = sorted(composite_old.items(),
                        key=lambda x: x[1]["composite"], reverse=True)
    for rank, (ccy, info) in enumerate(sorted_old, 1):
        bar = "█" * int(info["composite"] / 2) + "░" * (50 - int(info["composite"] / 2))
        print(f"  {rank}. {ccy:4s}  {info['composite']:5.1f}  {bar}  {info['label']}")

    old_setups = compute_trade_setups(
        composite_old, momentum_old, classification_old, atr_old, cot_scores,
        velocity_scores=velocity_old,
        trend_structure=trend_struct_old,
        strength_persistence=persistence_old,
    )

    print(f"\n🎯 Trade Setups Attuale ({len(old_setups)} totali):")
    grade_count_old = {}
    for s in old_setups:
        grade_count_old[s["grade"]] = grade_count_old.get(s["grade"], 0) + 1
    print(f"   Distribuzione: {grade_count_old}")
    
    print(f"\n   Top 15:")
    for i, s in enumerate(old_setups[:15], 1):
        reasons_str = " | ".join(s["reasons"][:3])
        print(f"   {i:2d}. [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
              f"Score={s['quality_score']:5.1f}  Δ={s['differential']:+5.1f}  "
              f"— {reasons_str}")

    # ── 3. SISTEMA NUOVO (Candle-9 + Volume + COT) ──
    print("\n")
    print("━" * 80)
    print("  SISTEMA NUOVO (Candle-9 + Volume + COT)")
    print("━" * 80)

    # Price score basato su Candle-9
    c9_price_h4 = candle9_price_score(all_h4, LOOKBACK)
    c9_price_h1 = candle9_price_score(all_h1, LOOKBACK)
    
    # Blend H1/H4 (60% H4, 40% H1 per il price)
    c9_price_blended = {}
    for ccy in CURRENCIES:
        c9_price_blended[ccy] = round(
            c9_price_h4.get(ccy, 50) * 0.6 + c9_price_h1.get(ccy, 50) * 0.4, 2)

    # Volume scores (riusa stessi, basati su futures)
    vol_scores_for_new = compute_volume_scores(all_h4, futures, c9_price_blended)

    # Composite nuovo
    composite_new = new_composite_scores(c9_price_blended, vol_scores_for_new, cot_scores)

    print("\n📈 Classifica Forza (NUOVO Candle-9):")
    sorted_new = sorted(composite_new.items(),
                        key=lambda x: x[1]["composite"], reverse=True)
    for rank, (ccy, info) in enumerate(sorted_new, 1):
        bar = "█" * int(info["composite"] / 2) + "░" * (50 - int(info["composite"] / 2))
        print(f"  {rank}. {ccy:4s}  {info['composite']:5.1f}  {bar}  {info['label']}")

    new_setups = new_trade_setups(composite_new, cot_scores, all_h4)

    print(f"\n🎯 Trade Setups NUOVO ({len(new_setups)} totali):")
    grade_count_new = {}
    for s in new_setups:
        grade_count_new[s["grade"]] = grade_count_new.get(s["grade"], 0) + 1
    print(f"   Distribuzione: {grade_count_new}")
    
    print(f"\n   Top 15:")
    for i, s in enumerate(new_setups[:15], 1):
        reasons_str = " | ".join(s["reasons"][:3])
        print(f"   {i:2d}. [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
              f"Score={s['quality_score']:5.1f}  Δ={s['differential']:+5.1f}  "
              f"— {reasons_str}")

    # ── 4. CONFRONTO DETTAGLIATO ──
    print("\n")
    print("━" * 80)
    print("  CONFRONTO DETTAGLIATO")
    print("━" * 80)

    # Ranking comparison
    print("\n📊 Confronto Ranking Valute:")
    print(f"  {'Valuta':6s} {'ATTUALE':>10s} {'RANK':>5s}   {'NUOVO':>10s} {'RANK':>5s}   {'Δ Score':>8s} {'Δ Rank':>7s}")
    print(f"  {'-'*6:6s} {'-'*10:>10s} {'-'*5:>5s}   {'-'*10:>10s} {'-'*5:>5s}   {'-'*8:>8s} {'-'*7:>7s}")
    
    old_ranks = {ccy: rank for rank, (ccy, _) in enumerate(sorted_old, 1)}
    new_ranks = {ccy: rank for rank, (ccy, _) in enumerate(sorted_new, 1)}
    
    for ccy in CURRENCIES:
        old_score = composite_old[ccy]["composite"]
        new_score = composite_new.get(ccy, {}).get("composite", 50)
        old_rank = old_ranks[ccy]
        new_rank = new_ranks.get(ccy, 0)
        d_score = new_score - old_score
        d_rank = old_rank - new_rank  # positivo = migliorato
        
        rank_arrow = "↑" if d_rank > 0 else "↓" if d_rank < 0 else "="
        print(f"  {ccy:6s} {old_score:10.1f} #{old_rank:<4d}   {new_score:10.1f} #{new_rank:<4d}  "
              f" {d_score:+8.1f} {rank_arrow}{abs(d_rank):>5d}")

    # Setup comparison — focus on USD
    print("\n💵 Focus USD — Setups che coinvolgono USD:")
    print("\n  ATTUALE:")
    usd_old = [s for s in old_setups if s["base"] == "USD" or s["quote"] == "USD"]
    if usd_old:
        for s in usd_old[:10]:
            print(f"    [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
                  f"Score={s['quality_score']:5.1f}  Δ={s['differential']:+5.1f}")
    else:
        print("    (nessun setup USD)")

    print("\n  NUOVO:")
    usd_new = [s for s in new_setups if s["base"] == "USD" or s["quote"] == "USD"]
    if usd_new:
        for s in usd_new[:10]:
            print(f"    [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
                  f"Score={s['quality_score']:5.1f}  Δ={s['differential']:+5.1f}")
    else:
        print("    (nessun setup USD)")

    # A/A+ comparison
    print("\n🏆 Segnali A/A+ — Confronto:")
    aa_old = [s for s in old_setups if s["grade"] in ("A+", "A")]
    aa_new = [s for s in new_setups if s["grade"] in ("A+", "A")]

    print(f"\n  ATTUALE: {len(aa_old)} segnali A/A+")
    for s in aa_old:
        print(f"    [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
              f"Score={s['quality_score']:5.1f}  — {' | '.join(s['reasons'][:3])}")

    print(f"\n  NUOVO: {len(aa_new)} segnali A/A+")
    for s in aa_new:
        print(f"    [{s['grade']:2s}] {s['pair']:8s} {s['direction']:5s} "
              f"Score={s['quality_score']:5.1f}  — {' | '.join(s['reasons'][:3])}")

    # Candle-9 raw detail for top currencies
    print("\n📉 Candle-9 dettaglio per valuta (raw % change):")
    c9_detail = compute_candle9_signal(all_h4)
    sorted_c9 = sorted(c9_detail.items(), 
                        key=lambda x: x[1]["candle9_ratio"], reverse=True)
    for ccy, info in sorted_c9:
        ratio = info["candle9_ratio"]
        signal = info["candle9_signal"]
        bar_len = int(abs(ratio) * 20)
        if ratio > 0:
            bar = "▓" * min(bar_len, 30) + "░" * max(0, 30 - bar_len)
            print(f"  {ccy:4s}  {ratio:+.3f}%  {signal:15s}  +|{bar}")
        else:
            bar = "░" * max(0, 30 - bar_len) + "▓" * min(bar_len, 30)
            print(f"  {ccy:4s}  {ratio:+.3f}%  {signal:15s}  {bar}|-")

    # Summary
    print("\n")
    print("=" * 80)
    print("  RIASSUNTO")
    print("=" * 80)
    print(f"\n  Sistema Attuale: {len(aa_old)} segnali A/A+, top = "
          f"{aa_old[0]['pair'] if aa_old else 'nessuno'}")
    print(f"  Sistema Nuovo:   {len(aa_new)} segnali A/A+, top = "
          f"{aa_new[0]['pair'] if aa_new else 'nessuno'}")

    # USD position
    usd_old_comp = composite_old.get("USD", {}).get("composite", 50)
    usd_new_comp = composite_new.get("USD", {}).get("composite", 50)
    print(f"\n  USD Score:  Attuale={usd_old_comp:.1f} (#{old_ranks.get('USD', '?')})  "
          f"→  Nuovo={usd_new_comp:.1f} (#{new_ranks.get('USD', '?')})")

    usd_c9 = c9_detail.get("USD", {})
    print(f"  USD Candle-9: {usd_c9.get('candle9_ratio', 0):+.3f}%  "
          f"{usd_c9.get('candle9_signal', 'N/A')}")
    
    # Identify what the new system catches that the old doesn't
    old_aa_pairs = {s["pair"] for s in aa_old}
    new_aa_pairs = {s["pair"] for s in aa_new}
    only_new = new_aa_pairs - old_aa_pairs
    only_old = old_aa_pairs - new_aa_pairs
    
    if only_new:
        print(f"\n  🆕 Solo nel NUOVO (A/A+): {', '.join(only_new)}")
    if only_old:
        print(f"  ❌ Solo nell'ATTUALE (A/A+): {', '.join(only_old)}")
    if old_aa_pairs & new_aa_pairs:
        print(f"  ✅ In entrambi (A/A+): {', '.join(old_aa_pairs & new_aa_pairs)}")

    print()


if __name__ == "__main__":
    main()
