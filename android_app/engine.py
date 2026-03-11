"""
Currency Strength Mobile – Analysis Engine
Complete analysis pipeline: technical indicators, composite scoring,
trend classification, and trade setup grading.
"""

import numpy as np
import pandas as pd

from app_config import (
    CURRENCIES, FOREX_PAIRS,
    WEIGHT_PRICE_ACTION, WEIGHT_VOLUME, WEIGHT_COT,
    COMPOSITE_WEIGHT_H1, COMPOSITE_WEIGHT_H4,
    RSI_PERIOD, ROC_FAST, ROC_MEDIUM, ROC_SLOW,
    EMA_FAST, EMA_MEDIUM, EMA_SLOW,
    ADX_PERIOD, ATR_PERIOD, HURST_MIN_BARS,
    THRESHOLD_STRONG_BULL, THRESHOLD_EXTREME_BULL,
    THRESHOLD_STRONG_BEAR, THRESHOLD_EXTREME_BEAR,
    MOMENTUM_FAST_GAIN, MOMENTUM_FAST_LOSS, MOMENTUM_LOOKBACK,
    ADX_TREND_THRESH, ADX_RANGE_THRESH,
    HURST_TREND_THRESH, HURST_REVERT_THRESH,
    EFFICIENCY_TREND, EFFICIENCY_RANGE,
    CLASS_W_ADX, CLASS_W_HURST, CLASS_W_ER,
    CORRELATION_GROUPS, EXCLUDED_PAIRS,
    SESSION_CURRENCY_AFFINITY, COT_STALE_DAYS_THRESHOLD,
)

# ── Lookup tabelle gruppi correlazione ──
_GROUP_LOOKUP: dict[frozenset, int] = {}
for _gid, _pairs in enumerate(CORRELATION_GROUPS):
    for _p in _pairs:
        _GROUP_LOOKUP[frozenset({_p[:3], _p[3:]})] = _gid
_EXCLUDED_SET = {frozenset({p[:3], p[3:]}) for p in EXCLUDED_PAIRS}


def _get_active_session_types(session_info: dict | None = None) -> set[str]:
    if not session_info:
        return set()
    types = set()
    for s in session_info.get("active_sessions", []):
        s_lower = s.lower()
        if "asia" in s_lower or "tokyo" in s_lower:
            types.add("asia")
        if "londra" in s_lower or "london" in s_lower:
            types.add("london")
        if "new york" in s_lower or "york" in s_lower:
            types.add("newyork")
    return types


# ═══════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ═══════════════════════════════════════════════════════════════════════════════

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def roc(series: pd.Series, period: int = 1) -> pd.Series:
    return series.pct_change(period, fill_method=None) * 100


def ema(series: pd.Series, period: int = 20) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_val = tr.ewm(alpha=1/period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr_val)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr_val)

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    dx = dx.replace([np.inf, -np.inf], 0)
    return dx.ewm(alpha=1/period, min_periods=period).mean()


def hurst_exponent(series: pd.Series) -> float:
    ts = series.dropna().values
    n = len(ts)
    if n < HURST_MIN_BARS:
        return 0.5

    # Simplified for mobile: fewer subdivisions, max 100
    max_k = min(n // 2, 100)
    rs_list, sizes = [], []

    for k in range(10, max_k, 10):  # step=10 instead of 5 for speed
        sub_rs = []
        for start in range(0, n - k, k):
            subset = ts[start:start + k]
            m = np.mean(subset)
            deviate = np.cumsum(subset - m)
            r = np.max(deviate) - np.min(deviate)
            s = np.std(subset, ddof=1)
            if s > 1e-10:
                sub_rs.append(r / s)
        if sub_rs:
            rs_list.append(np.mean(sub_rs))
            sizes.append(k)

    if len(rs_list) < 3:
        return 0.5

    slope, _ = np.polyfit(np.log(sizes), np.log(rs_list), 1)
    return float(np.clip(slope, 0, 1))


def efficiency_ratio(series: pd.Series, period: int = 20) -> pd.Series:
    direction = (series - series.shift(period)).abs()
    volatility = series.diff().abs().rolling(period).sum()
    er = direction / volatility
    return er.replace([np.inf, -np.inf], 0).fillna(0)


def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = ATR_PERIOD) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period).mean()


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE ACTION SCORES
# ═══════════════════════════════════════════════════════════════════════════════

def _pair_strength_for_currency(pair_df: pd.DataFrame, is_base: bool) -> float:
    close = pair_df["Close"]
    sign = 1.0 if is_base else -1.0

    # RSI
    rsi_val = rsi(close, RSI_PERIOD)
    latest_rsi = rsi_val.iloc[-1] if not rsi_val.empty else 50
    if not is_base:
        latest_rsi = 100 - latest_rsi

    # ROC multi-period
    roc_f = roc(close, ROC_FAST).iloc[-1] if len(close) > ROC_FAST else 0
    roc_m = roc(close, ROC_MEDIUM).iloc[-1] if len(close) > ROC_MEDIUM else 0
    roc_s = roc(close, ROC_SLOW).iloc[-1] if len(close) > ROC_SLOW else 0
    avg_roc = (roc_f * 0.5 + roc_m * 0.3 + roc_s * 0.2) * sign
    roc_score = 50 + np.clip(avg_roc * 10, -50, 50)

    # EMA positioning
    ema_scores = []
    for p in [EMA_FAST, EMA_MEDIUM, EMA_SLOW]:
        if len(close) > p:
            ema_val = ema(close, p).iloc[-1]
            pct_above = ((close.iloc[-1] / ema_val) - 1) * 100
            if not is_base:
                pct_above = -pct_above
            ema_scores.append(50 + np.clip(pct_above * 15, -50, 50))
    ema_score = np.mean(ema_scores) if ema_scores else 50

    final = latest_rsi * 0.35 + roc_score * 0.40 + ema_score * 0.25
    return float(np.clip(final, 0, 100))


def compute_price_action_scores(all_pairs: dict[str, pd.DataFrame]) -> dict[str, float]:
    ccy_scores: dict[str, list[float]] = {c: [] for c in CURRENCIES}

    for pair_name, pair_df in all_pairs.items():
        if pair_df.empty or "Close" not in pair_df.columns:
            continue
        info = FOREX_PAIRS[pair_name]
        base, quote = info["base"], info["quote"]

        if base in ccy_scores:
            ccy_scores[base].append(_pair_strength_for_currency(pair_df, is_base=True))
        if quote in ccy_scores:
            ccy_scores[quote].append(_pair_strength_for_currency(pair_df, is_base=False))

    return {ccy: round(float(np.mean(vals)), 2) if vals else 50.0
            for ccy, vals in ccy_scores.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# VOLUME SCORES
# ═══════════════════════════════════════════════════════════════════════════════

def compute_volume_scores(futures_data: dict[str, pd.DataFrame],
                          price_scores: dict[str, float]) -> dict[str, float]:
    volume_ratios = {}
    for ccy in CURRENCIES:
        fdf = futures_data.get(ccy)
        if fdf is not None and not fdf.empty and "Volume" in fdf.columns:
            vol = fdf["Volume"].astype(float)
            sma_vol = vol.rolling(20).mean()
            if len(sma_vol.dropna()) > 0 and sma_vol.iloc[-1] > 0:
                volume_ratios[ccy] = float(vol.iloc[-1] / sma_vol.iloc[-1])
            else:
                volume_ratios[ccy] = 1.0
        else:
            volume_ratios[ccy] = 1.0

    scores = {}
    for ccy in CURRENCIES:
        pa = price_scores.get(ccy, 50)
        vr = volume_ratios.get(ccy, 1.0)
        deviation = pa - 50
        amplified = deviation * np.clip(vr, 0.5, 2.0)
        scores[ccy] = round(float(np.clip(50 + amplified, 0, 100)), 2)
    return scores


# ═══════════════════════════════════════════════════════════════════════════════
# COMPOSITE SCORES
# ═══════════════════════════════════════════════════════════════════════════════

def compute_composite_scores(price_scores, volume_scores, cot_scores) -> dict[str, dict]:
    results = {}
    for ccy in CURRENCIES:
        pa = price_scores.get(ccy, 50)
        vol = volume_scores.get(ccy, 50)
        cot = cot_scores.get(ccy, {}).get("score", 50) if isinstance(cot_scores.get(ccy), dict) else 50

        composite = pa * WEIGHT_PRICE_ACTION + vol * WEIGHT_VOLUME + cot * WEIGHT_COT
        composite = round(float(np.clip(composite, 0, 100)), 1)

        if composite >= THRESHOLD_EXTREME_BULL:
            label = "VERY STRONG"
        elif composite >= THRESHOLD_STRONG_BULL:
            label = "STRONG"
        elif composite <= THRESHOLD_EXTREME_BEAR:
            label = "VERY WEAK"
        elif composite <= THRESHOLD_STRONG_BEAR:
            label = "WEAK"
        else:
            label = "NEUTRAL"

        results[ccy] = {
            "price_score": round(pa, 1),
            "volume_score": round(vol, 1),
            "cot_score": round(cot, 1),
            "composite": composite,
            "label": label,
        }
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# MOMENTUM
# ═══════════════════════════════════════════════════════════════════════════════

def compute_momentum_rankings(all_pairs, lookback=MOMENTUM_LOOKBACK) -> dict[str, dict]:
    from fetcher import compute_currency_returns

    rets = compute_currency_returns(all_pairs, window=1)
    if rets.empty or len(rets) < lookback + 5:
        return {c: {"delta": 0, "acceleration": 0, "rank_label": "N/A"} for c in CURRENCIES}

    results = {}
    for ccy in CURRENCIES:
        if ccy not in rets.columns:
            results[ccy] = {"delta": 0, "acceleration": 0, "rank_label": "N/A"}
            continue

        cum_recent = rets[ccy].iloc[-lookback:].sum() * 100
        cum_prev = (rets[ccy].iloc[-(lookback*2):-lookback].sum() * 100
                    if len(rets) >= lookback * 2 else 0)

        delta = round(cum_recent, 2)
        acceleration = round(cum_recent - cum_prev, 2)

        if delta >= MOMENTUM_FAST_GAIN:
            rank_label = "GAINING FAST"
        elif delta <= MOMENTUM_FAST_LOSS:
            rank_label = "LOSING FAST"
        elif delta > 0:
            rank_label = "Gaining"
        elif delta < 0:
            rank_label = "Losing"
        else:
            rank_label = "Flat"

        results[ccy] = {"delta": delta, "acceleration": acceleration, "rank_label": rank_label}
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION: TREND vs MEAN-REVERT
# ═══════════════════════════════════════════════════════════════════════════════

def classify_trend_vs_reversion(all_pairs, futures_data) -> dict[str, dict]:
    from fetcher import compute_currency_returns
    rets = compute_currency_returns(all_pairs, window=1)
    results = {}

    for ccy in CURRENCIES:
        # ADX average
        adx_values = []
        for pair_name, pair_df in all_pairs.items():
            info = FOREX_PAIRS[pair_name]
            if info["base"] == ccy or info["quote"] == ccy:
                if len(pair_df) > ADX_PERIOD * 3 and all(
                    c in pair_df.columns for c in ["High", "Low", "Close"]
                ):
                    adx_series = adx(pair_df["High"], pair_df["Low"], pair_df["Close"], ADX_PERIOD)
                    last_adx = adx_series.iloc[-1]
                    if not np.isnan(last_adx):
                        adx_values.append(last_adx)
        avg_adx = float(np.mean(adx_values)) if adx_values else 20

        # Hurst
        h = 0.5
        if ccy in rets.columns:
            ret_series = rets[ccy].dropna()
            if len(ret_series) >= HURST_MIN_BARS:
                h = hurst_exponent(ret_series)

        # Efficiency Ratio
        er = 0.3
        fut_df = futures_data.get(ccy)
        if fut_df is not None and not fut_df.empty and "Close" in fut_df.columns:
            er_series = efficiency_ratio(fut_df["Close"], 20)
            er = float(er_series.iloc[-1]) if not er_series.empty else 0.3

        # Score
        adx_norm = np.clip((avg_adx - ADX_RANGE_THRESH) / (ADX_TREND_THRESH - ADX_RANGE_THRESH), 0, 1) * 100
        hurst_norm = np.clip((h - HURST_REVERT_THRESH) / (HURST_TREND_THRESH - HURST_REVERT_THRESH), 0, 1) * 100
        er_norm = np.clip((er - EFFICIENCY_RANGE) / (EFFICIENCY_TREND - EFFICIENCY_RANGE), 0, 1) * 100

        trend_score = adx_norm * CLASS_W_ADX + hurst_norm * CLASS_W_HURST + er_norm * CLASS_W_ER
        trend_score = round(float(np.clip(trend_score, 0, 100)), 1)

        if trend_score >= 65:
            classification = "TREND_FOLLOWING"
        elif trend_score <= 35:
            classification = "MEAN_REVERTING"
        else:
            classification = "MIXED"

        results[ccy] = {
            "adx_avg": round(avg_adx, 1), "hurst": round(h, 3),
            "eff_ratio": round(er, 3), "trend_score": trend_score,
            "classification": classification,
        }
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# ATR CONTEXT
# ═══════════════════════════════════════════════════════════════════════════════

def compute_atr_context(all_pairs) -> dict[str, dict]:
    ccy_atrs: dict[str, list[dict]] = {c: [] for c in CURRENCIES}

    for pair_name, pair_df in all_pairs.items():
        if pair_df.empty or len(pair_df) < ATR_PERIOD * 3:
            continue
        if not all(c in pair_df.columns for c in ["High", "Low", "Close"]):
            continue

        info = FOREX_PAIRS[pair_name]
        atr_series = atr(pair_df["High"], pair_df["Low"], pair_df["Close"])
        if atr_series.empty:
            continue

        current_atr = float(atr_series.iloc[-1])
        close_price = float(pair_df["Close"].iloc[-1])
        atr_pct = (current_atr / close_price) * 100 if close_price > 0 else 0

        lookback = min(50, len(atr_series))
        atr_window = atr_series.iloc[-lookback:]
        percentile = float((atr_window < current_atr).sum() / len(atr_window) * 100)

        entry = {"atr_pct": atr_pct, "percentile": percentile}
        base, quote = info["base"], info["quote"]
        if base in ccy_atrs:
            ccy_atrs[base].append(entry)
        if quote in ccy_atrs:
            ccy_atrs[quote].append(entry)

    results = {}
    for ccy in CURRENCIES:
        entries = ccy_atrs[ccy]
        avg_perc = float(np.mean([e["percentile"] for e in entries])) if entries else 50

        if avg_perc >= 85:
            regime = "EXTREME"
        elif avg_perc >= 65:
            regime = "HIGH"
        elif avg_perc >= 35:
            regime = "NORMAL"
        else:
            regime = "LOW"

        results[ccy] = {
            "atr_percentile": round(avg_perc, 1),
            "volatility_regime": regime,
        }
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# VELOCITY SCORES
# ═══════════════════════════════════════════════════════════════════════════════

def compute_velocity_scores(all_pairs, composite, lookback_bars=20) -> dict[str, dict]:
    from fetcher import compute_currency_returns
    rets = compute_currency_returns(all_pairs, window=1)
    default = {c: {"velocity_norm": 50, "velocity_label": "N/A"} for c in CURRENCIES}

    if rets.empty or len(rets) < lookback_bars + 5:
        return default

    cum = (rets.rolling(lookback_bars).sum() * 100).dropna(how="all")
    if len(cum) < 2:
        return default

    results = {}
    for ccy in CURRENCIES:
        if ccy not in cum.columns or len(cum[ccy].dropna()) < lookback_bars:
            results[ccy] = {"velocity_norm": 50, "velocity_label": "N/A"}
            continue

        recent = cum[ccy].dropna().iloc[-lookback_bars:]
        directional_change = abs(float(recent.iloc[-1] - recent.iloc[0]))
        path_length = float(recent.diff().abs().sum())
        efficiency = directional_change / path_length if path_length > 1e-10 else 0

        std_recent = float(recent.std()) if len(recent) > 1 else 1.0
        magnitude = directional_change / std_recent if std_recent > 1e-10 else 0
        magnitude_factor = float(np.clip(magnitude / 2.0, 0.3, 1.0))

        velocity_norm = round(float(np.clip(efficiency * magnitude_factor * 120, 0, 100)), 1)

        if velocity_norm >= 70:
            label = "VERY FAST"
        elif velocity_norm >= 50:
            label = "FAST"
        elif velocity_norm >= 35:
            label = "MODERATE"
        elif velocity_norm >= 20:
            label = "SLOW"
        else:
            label = "STALE"

        results[ccy] = {"velocity_norm": velocity_norm, "velocity_label": label}
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# TREND STRUCTURE (EMA cascade)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_trend_structure(all_pairs) -> dict[str, dict]:
    ccy_alignments: dict[str, list[float]] = {c: [] for c in CURRENCIES}

    for pair_name, pair_df in all_pairs.items():
        if pair_df.empty or "Close" not in pair_df.columns:
            continue
        close = pair_df["Close"]
        if len(close) < EMA_SLOW + 5:
            continue

        info = FOREX_PAIRS[pair_name]
        ema_f = float(ema(close, EMA_FAST).iloc[-1])
        ema_m = float(ema(close, EMA_MEDIUM).iloc[-1])
        ema_s = float(ema(close, EMA_SLOW).iloc[-1])

        if ema_f > ema_m > ema_s:
            alignment = 1.0
        elif ema_f < ema_m < ema_s:
            alignment = -1.0
        elif ema_f > ema_s:
            alignment = 0.3
        elif ema_f < ema_s:
            alignment = -0.3
        else:
            alignment = 0.0

        base, quote = info["base"], info["quote"]
        if base in ccy_alignments:
            ccy_alignments[base].append(alignment)
        if quote in ccy_alignments:
            ccy_alignments[quote].append(-alignment)

    results = {}
    for ccy in CURRENCIES:
        vals = ccy_alignments[ccy]
        avg = float(np.mean(vals)) if vals else 0.0
        results[ccy] = {"ema_alignment": round(avg, 3)}
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# STRENGTH PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_strength_persistence(all_pairs, lookback=12) -> dict[str, dict]:
    from fetcher import compute_currency_returns
    rets = compute_currency_returns(all_pairs, window=1)
    results = {}

    for ccy in CURRENCIES:
        if ccy not in rets.columns or len(rets) < lookback:
            results[ccy] = {"persistence": 0.0}
            continue

        recent = rets[ccy].iloc[-lookback:]
        positive_ratio = (recent > 0).sum() / len(recent)
        persistence = (positive_ratio - 0.5) * 2  # -1 to +1
        results[ccy] = {"persistence": round(persistence, 3)}
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE SETUP SCORE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_trade_setups(
    composite, momentum, classification, atr_context, cot_scores,
    velocity_scores=None, trend_structure=None, strength_persistence=None,
    session_info=None,
) -> list[dict]:
    if velocity_scores is None:
        velocity_scores = {}
    if trend_structure is None:
        trend_structure = {}
    if strength_persistence is None:
        strength_persistence = {}
    session_types = _get_active_session_types(session_info)
    setups = []

    for base in CURRENCIES:
        for quote in CURRENCIES:
            if base == quote:
                continue

            s_base = composite[base]["composite"]
            s_quote = composite[quote]["composite"]
            diff = s_base - s_quote

            if abs(diff) < 5:
                continue

            direction = "LONG" if diff > 0 else "SHORT"
            strong_ccy = base if diff > 0 else quote
            weak_ccy = quote if diff > 0 else base

            quality = 0
            reasons = []

            # 1. Differential (0-30)
            diff_abs = abs(diff)
            quality += min(diff_abs * 1.0, 30)
            if diff_abs >= 20:
                reasons.append(f"Diff forte ({diff_abs:.0f})")
            elif diff_abs >= 12:
                reasons.append(f"Diff buono ({diff_abs:.0f})")

            # 2. Momentum (0-20)
            mom_strong = momentum.get(strong_ccy, {}).get("delta", 0)
            mom_weak = momentum.get(weak_ccy, {}).get("delta", 0)
            if mom_strong > 0 and mom_weak < 0:
                quality += 20
                reasons.append("Momentum allineato")
            elif mom_strong > 0 or mom_weak < 0:
                quality += 10

            # 2b. Synergy (0-5)
            if diff_abs >= 15 and mom_strong > 0 and mom_weak < 0:
                quality += 5

            # 3. Trend regime (0-15)
            cls_strong = classification.get(strong_ccy, {})
            if cls_strong.get("classification") == "TREND_FOLLOWING":
                quality += 15
                reasons.append(f"{strong_ccy} trending")
            elif cls_strong.get("classification") == "MIXED":
                quality += 7

            # 4. Volatility (0-15)
            vol_strong = atr_context.get(strong_ccy, {}).get("volatility_regime", "NORMAL")
            vol_weak = atr_context.get(weak_ccy, {}).get("volatility_regime", "NORMAL")
            if vol_strong in ("NORMAL", "LOW"):
                quality += 10
            elif vol_strong == "HIGH":
                quality += 5
            if vol_strong == "EXTREME" or vol_weak == "EXTREME":
                quality -= 5

            # 5. COT (0-10)
            cot_strong_info = cot_scores.get(strong_ccy, {})
            cot_weak_info = cot_scores.get(weak_ccy, {})
            cot_strong_bias = cot_strong_info.get("bias", "NEUTRAL") if isinstance(cot_strong_info, dict) else "NEUTRAL"
            cot_weak_bias = cot_weak_info.get("bias", "NEUTRAL") if isinstance(cot_weak_info, dict) else "NEUTRAL"
            cot_pts = 0
            if cot_strong_bias == "BULLISH":
                cot_pts += 5
            if cot_weak_bias == "BEARISH":
                cot_pts += 5
            quality += cot_pts

            # 6. H1/H4 concordance (0-10)
            concordance = composite[strong_ccy].get("concordance", "")
            if "ALLINEATI" in str(concordance):
                quality += 10
            elif "DIVERGENZA" in str(concordance):
                quality -= 5

            # 7. Velocity (0-10)
            vel_s = velocity_scores.get(strong_ccy, {}).get("velocity_norm", 50)
            if vel_s >= 65:
                quality += 10
            elif vel_s >= 40:
                quality += 5
            if vel_s < 15:
                quality -= 3

            # 8. Trend structure (0-8)
            align_s = trend_structure.get(strong_ccy, {}).get("ema_alignment", 0)
            align_w = trend_structure.get(weak_ccy, {}).get("ema_alignment", 0)
            if align_s >= 0.4 and align_w <= -0.4:
                quality += 8
            elif align_s >= 0.2 or align_w <= -0.2:
                quality += 4
            if align_s <= -0.3:
                quality -= 5

            # 9. Momentum acceleration (0-5)
            mom_accel_s = momentum.get(strong_ccy, {}).get("acceleration", 0)
            mom_accel_w = momentum.get(weak_ccy, {}).get("acceleration", 0)
            if mom_accel_s > 0 and mom_accel_w < 0:
                quality += 5
            elif mom_accel_s > 0 or mom_accel_w < 0:
                quality += 2

            # 10. Strength persistence (0-8)
            p_s = strength_persistence.get(strong_ccy, {}).get("persistence", 0)
            p_w = strength_persistence.get(weak_ccy, {}).get("persistence", 0)
            if p_s >= 0.5 and p_w <= -0.5:
                quality += 8
            elif p_s >= 0.3 or p_w <= -0.3:
                quality += 4

            # 11. Session awareness (0-3)
            if session_types:
                strong_in = any(strong_ccy in SESSION_CURRENCY_AFFINITY.get(s, set()) for s in session_types)
                weak_in = any(weak_ccy in SESSION_CURRENCY_AFFINITY.get(s, set()) for s in session_types)
                if strong_in and weak_in:
                    quality += 3
                elif strong_in or weak_in:
                    quality += 1
                else:
                    quality -= 2

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
                "base": base, "quote": quote,
                "direction": direction,
                "differential": round(diff, 1),
                "quality_score": round(quality, 1),
                "grade": grade,
                "reasons": reasons,
                "strong_score": round(s_base if diff > 0 else s_quote, 1),
                "weak_score": round(s_quote if diff > 0 else s_base, 1),
            })

    setups.sort(key=lambda x: x["quality_score"], reverse=True)

    # Deduplicate
    seen_pairs: set[tuple[str, str]] = set()
    unique_setups = []
    for s in setups:
        canonical = tuple(sorted([s["base"], s["quote"]]))
        if canonical not in seen_pairs:
            seen_pairs.add(canonical)
            unique_setups.append(s)

    # Exclude
    unique_setups = [s for s in unique_setups
                     if frozenset({s["base"], s["quote"]}) not in _EXCLUDED_SET]

    # Correlation group filter
    covered_groups: dict[int, int] = {}
    for i, s in enumerate(unique_setups):
        if s["grade"] not in ("A+", "A"):
            continue
        pair_key = frozenset({s["base"], s["quote"]})
        group_id = _GROUP_LOOKUP.get(pair_key)
        if group_id is not None and group_id not in covered_groups:
            covered_groups[group_id] = i

    if covered_groups:
        filtered = []
        for i, s in enumerate(unique_setups):
            pair_key = frozenset({s["base"], s["quote"]})
            group_id = _GROUP_LOOKUP.get(pair_key)
            if group_id is not None and group_id in covered_groups:
                if i != covered_groups[group_id]:
                    continue
            filtered.append(s)
        unique_setups = filtered

    return unique_setups


# ═══════════════════════════════════════════════════════════════════════════════
# FULL ANALYSIS PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

import logging as _logging
_elog = _logging.getLogger(__name__)


def full_analysis(all_pairs, futures_data, cot_scores) -> dict:
    """Run the complete analysis pipeline. Returns dict with all results."""
    _elog.info(f"full_analysis: {len(all_pairs)} pairs, {len(futures_data)} futures")
    try:
        price_scores = compute_price_action_scores(all_pairs)
        _elog.info("  price_action_scores OK")
    except Exception as e:
        _elog.error(f"  price_action_scores FAILED: {e}")
        price_scores = {c: {"composite": 50, "price_score": 50} for c in CURRENCIES}

    try:
        volume_scores = compute_volume_scores(futures_data, price_scores)
        _elog.info("  volume_scores OK")
    except Exception as e:
        _elog.error(f"  volume_scores FAILED: {e}")
        volume_scores = {c: {"volume_score": 50} for c in CURRENCIES}

    try:
        composite = compute_composite_scores(price_scores, volume_scores, cot_scores)
        _elog.info("  composite_scores OK")
    except Exception as e:
        _elog.error(f"  composite_scores FAILED: {e}")
        composite = {c: {"composite": 50, "price_score": 50, "volume_score": 50, "cot_score": 50, "label": "NEUTRAL"} for c in CURRENCIES}

    try:
        momentum = compute_momentum_rankings(all_pairs)
        _elog.info("  momentum OK")
    except Exception as e:
        _elog.error(f"  momentum FAILED: {e}")
        momentum = {c: {"rank_now": 4, "rank_prev": 4, "delta": 0, "fast_move": "STABLE", "assessment": "NEUTRAL"} for c in CURRENCIES}

    try:
        classification = classify_trend_vs_reversion(all_pairs, futures_data)
        _elog.info("  classification OK")
    except Exception as e:
        _elog.error(f"  classification FAILED: {e}")
        classification = {c: {"adx_avg": 20, "hurst": 0.5, "eff_ratio": 0.3, "trend_score": 50, "classification": "MIXED"} for c in CURRENCIES}

    try:
        atr_ctx = compute_atr_context(all_pairs)
        _elog.info("  atr_context OK")
    except Exception as e:
        _elog.error(f"  atr_context FAILED: {e}")
        atr_ctx = {c: {"avg_atr_pct": 0.5, "regime": "NORMAL", "percentile": 50} for c in CURRENCIES}

    try:
        velocity = compute_velocity_scores(all_pairs, composite)
        _elog.info("  velocity OK")
    except Exception as e:
        _elog.error(f"  velocity FAILED: {e}")
        velocity = {c: {"score": 50, "accel": 0} for c in CURRENCIES}

    try:
        trend_struct = compute_trend_structure(all_pairs)
        _elog.info("  trend_structure OK")
    except Exception as e:
        _elog.error(f"  trend_structure FAILED: {e}")
        trend_struct = {c: {"alignment": "NEUTRAL", "score": 50} for c in CURRENCIES}

    try:
        persistence = compute_strength_persistence(all_pairs)
        _elog.info("  persistence OK")
    except Exception as e:
        _elog.error(f"  persistence FAILED: {e}")
        persistence = {c: {"bars_strong": 0, "bars_weak": 0, "persistence_score": 50} for c in CURRENCIES}

    _elog.info("full_analysis complete")
    return {
        "composite": composite,
        "momentum": momentum,
        "classification": classification,
        "atr_context": atr_ctx,
        "velocity": velocity,
        "trend_structure": trend_struct,
        "strength_persistence": persistence,
    }


def blend_multi_timeframe(analysis_h1, analysis_h4) -> dict:
    """Blend H1 and H4 analysis using configured weights."""
    w1, w4 = COMPOSITE_WEIGHT_H1, COMPOSITE_WEIGHT_H4
    blended_composite = {}

    for ccy in CURRENCIES:
        c1 = analysis_h1["composite"].get(ccy, {})
        c4 = analysis_h4["composite"].get(ccy, {})
        score_1 = c1.get("composite", 50)
        score_4 = c4.get("composite", 50)
        blended_score = round(score_1 * w1 + score_4 * w4, 1)

        # Concordance
        if abs(score_1 - score_4) < 10:
            concordance = "ALLINEATI"
        else:
            concordance = "DIVERGENZA"

        if blended_score >= THRESHOLD_EXTREME_BULL:
            label = "VERY STRONG"
        elif blended_score >= THRESHOLD_STRONG_BULL:
            label = "STRONG"
        elif blended_score <= THRESHOLD_EXTREME_BEAR:
            label = "VERY WEAK"
        elif blended_score <= THRESHOLD_STRONG_BEAR:
            label = "WEAK"
        else:
            label = "NEUTRAL"

        blended_composite[ccy] = {
            "composite": blended_score, "label": label,
            "concordance": concordance,
            "price_score": round(c1.get("price_score", 50) * w1 + c4.get("price_score", 50) * w4, 1),
            "volume_score": round(c1.get("volume_score", 50) * w1 + c4.get("volume_score", 50) * w4, 1),
            "cot_score": c4.get("cot_score", 50),
        }

    # Use H4 for slower indicators
    return {
        "composite": blended_composite,
        "momentum": analysis_h4["momentum"],
        "classification": analysis_h4["classification"],
        "atr_context": analysis_h4["atr_context"],
        "velocity": analysis_h4["velocity"],
        "trend_structure": analysis_h4["trend_structure"],
        "strength_persistence": analysis_h4["strength_persistence"],
    }


def run_full_pipeline(progress_callback=None) -> dict:
    """
    Fetch all data and run the full analysis pipeline.
    Optimized: fetches 1h data once and resamples for H4 to avoid double-fetching.
    Returns dict with 'analysis', 'trade_setups', 'composite'.
    """
    from fetcher import fetch_all_pairs, fetch_all_futures, _resample_ohlcv
    import time as _time
    _start = _time.time()

    # ── Fetch 1h data ONCE (used for both H1 and H4) ──
    if progress_callback:
        progress_callback(0, 100, "Connessione a Yahoo Finance...")

    # Try to authenticate (non-blocking — if it fails, fetcher retries per-pair)
    try:
        from fetcher import _init_yahoo_session
        crumb = _init_yahoo_session()
        if crumb:
            if progress_callback:
                progress_callback(5, 100, "Sessione pronta ✓")
        else:
            if progress_callback:
                progress_callback(5, 100, "Scarico dati senza crumb...")
    except Exception as e:
        _elog.warning(f"Session init skipped: {e}")
        if progress_callback:
            progress_callback(5, 100, "Scarico dati...")

    def pair_progress(done, total, msg):
        # Map pair progress to 5-55% range
        pct = 5 + int(done / max(total, 1) * 50)
        if progress_callback:
            progress_callback(pct, 100, f"Forex: {msg}")

    _elog.info("Fetching H1 forex pairs...")
    all_pairs_h1 = fetch_all_pairs("H1", progress_callback=pair_progress)
    _elog.info(f"Fetched {len(all_pairs_h1)}/28 pairs in {_time.time()-_start:.1f}s")

    if not all_pairs_h1:
        raise RuntimeError(
            f"Impossibile scaricare dati forex (0/28 coppie). "
            f"Controlla la connessione. Tempo: {_time.time()-_start:.0f}s")

    if progress_callback:
        progress_callback(55, 100, f"Ricampionamento H4 ({len(all_pairs_h1)} coppie)...")

    # Resample H1 -> H4 locally (avoid re-downloading)
    all_pairs_h4 = {}
    for pair_name, df in all_pairs_h1.items():
        try:
            resampled = _resample_ohlcv(df, "4h")
            if not resampled.empty:
                all_pairs_h4[pair_name] = resampled
        except Exception as e:
            _elog.warning(f"Resample failed for {pair_name}: {e}")

    if progress_callback:
        progress_callback(58, 100, "Scarico futures...")

    def futures_progress(done, total, msg):
        pct = 58 + int(done / max(total, 1) * 12)
        if progress_callback:
            progress_callback(pct, 100, f"Futures: {msg}")

    _elog.info("Fetching H1 futures...")
    futures_h1 = fetch_all_futures("H1", progress_callback=futures_progress)
    _elog.info(f"Fetched {len(futures_h1)}/8 futures in {_time.time()-_start:.1f}s")

    # Resample futures H1 -> H4
    futures_h4 = {}
    for ccy, df in futures_h1.items():
        try:
            resampled = _resample_ohlcv(df, "4h")
            if not resampled.empty:
                futures_h4[ccy] = resampled
        except Exception as e:
            _elog.warning(f"Resample futures failed for {ccy}: {e}")

    if progress_callback:
        progress_callback(72, 100, "Analisi H1...")

    # Neutral COT scores (simplified for mobile)
    cot_scores = {c: {"score": 50, "bias": "NEUTRAL"} for c in CURRENCIES}

    _elog.info("Running H1 analysis...")
    analysis_h1 = full_analysis(all_pairs_h1, futures_h1, cot_scores)

    if progress_callback:
        progress_callback(82, 100, "Analisi H4...")

    _elog.info("Running H4 analysis...")
    analysis_h4 = full_analysis(all_pairs_h4, futures_h4, cot_scores)

    if progress_callback:
        progress_callback(90, 100, "Blending multi-timeframe...")

    analysis = blend_multi_timeframe(analysis_h1, analysis_h4)

    if progress_callback:
        progress_callback(95, 100, "Calcolo trade setups...")

    _elog.info("Computing trade setups...")
    trade_setups = compute_trade_setups(
        analysis["composite"],
        analysis["momentum"],
        analysis["classification"],
        analysis["atr_context"],
        cot_scores,
        velocity_scores=analysis["velocity"],
        trend_structure=analysis["trend_structure"],
        strength_persistence=analysis["strength_persistence"],
    )

    elapsed = _time.time() - _start
    _elog.info(f"Pipeline complete in {elapsed:.1f}s — {len(trade_setups)} setups")

    if progress_callback:
        progress_callback(100, 100, f"Completato in {elapsed:.0f}s!")

    return {
        "analysis": analysis,
        "trade_setups": trade_setups,
        "composite": analysis["composite"],
    }
