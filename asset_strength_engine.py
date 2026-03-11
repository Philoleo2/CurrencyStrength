"""
Asset Strength Indicator – Strength Engine
=============================================
Calcola il punteggio composito di forza per ogni asset (0-100)
combinando: Price Action, Volume, COT.

Replica la stessa logica del Currency Strength Engine ma adattata
per asset individuali (non coppie valutarie).

Classifica: TREND-FOLLOWING / MEAN-REVERTING / MIXED
Indicatori: RSI, ROC multi-periodo, EMA positioning, ADX, Hurst, ER, ATR.
"""

import numpy as np
import pandas as pd

from config import (
    ASSETS, ASSET_LABELS,
    ASSET_COMPOSITE_WEIGHT_H4, ASSET_COMPOSITE_WEIGHT_DAILY, ASSET_COMPOSITE_WEIGHT_WEEKLY,
    ASSET_W_DIVERGENCE_THRESHOLD, ASSET_W_DIVERGENCE_MAX,
    ASSET_W_DECAY_MIN_WEIGHT, ASSET_W_DECAY_OPPOSITE_BONUS,
    # Pesi compositi
    WEIGHT_PRICE_ACTION, WEIGHT_VOLUME, WEIGHT_COT, WEIGHT_C9,
    # Parametri tecnici
    RSI_PERIOD, ROC_FAST, ROC_MEDIUM, ROC_SLOW,
    EMA_FAST, EMA_MEDIUM, EMA_SLOW,
    ADX_PERIOD, ATR_PERIOD, HURST_MIN_BARS,
    # Soglie
    THRESHOLD_STRONG_BULL, THRESHOLD_EXTREME_BULL,
    THRESHOLD_STRONG_BEAR, THRESHOLD_EXTREME_BEAR,
    MOMENTUM_FAST_GAIN, MOMENTUM_FAST_LOSS, MOMENTUM_LOOKBACK,
    # Classificazione
    ADX_TREND_THRESH, ADX_RANGE_THRESH,
    HURST_TREND_THRESH, HURST_REVERT_THRESH,
    EFFICIENCY_TREND, EFFICIENCY_RANGE,
    CLASS_W_ADX, CLASS_W_HURST, CLASS_W_ER,
    # COT freshness
    COT_STALE_DAYS_THRESHOLD,
    # Stabilizzazione
    SCORE_SMOOTHING_ALPHA,
    MIN_DIFFERENTIAL_THRESHOLD,
)

# Importa indicatori tecnici dal modulo forex (riusabili)
from strength_engine import (
    rsi, roc, ema, adx, hurst_exponent, efficiency_ratio, atr,
)


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE ACTION SCORE PER ASSET
# ═══════════════════════════════════════════════════════════════════════════════

def _asset_strength(df: pd.DataFrame) -> float:
    """
    Calcola un punteggio 0-100 per un singolo asset.
    Combina: RSI, ROC multi-periodo, posizione relativa a EMA.
    """
    close = df["Close"]
    if len(close) < 10:
        return 50.0

    # --- RSI normalizzato (0-100) ---
    rsi_val = rsi(close, RSI_PERIOD)
    latest_rsi = float(rsi_val.iloc[-1]) if not rsi_val.empty else 50.0

    # --- ROC multi-periodo (normalizzato a score 0-100) ---
    roc_f = float(roc(close, ROC_FAST).iloc[-1]) if len(close) > ROC_FAST else 0
    roc_m = float(roc(close, ROC_MEDIUM).iloc[-1]) if len(close) > ROC_MEDIUM else 0
    roc_s = float(roc(close, ROC_SLOW).iloc[-1]) if len(close) > ROC_SLOW else 0

    avg_roc = roc_f * 0.5 + roc_m * 0.3 + roc_s * 0.2
    roc_score = 50 + np.clip(avg_roc * 10, -50, 50)

    # --- EMA positioning (0-100) ---
    ema_scores = []
    for p in [EMA_FAST, EMA_MEDIUM, EMA_SLOW]:
        if len(close) > p:
            ema_val = float(ema(close, p).iloc[-1])
            if ema_val > 0:
                pct_above = ((float(close.iloc[-1]) / ema_val) - 1) * 100
                ema_scores.append(50 + np.clip(pct_above * 15, -50, 50))
    ema_score = np.mean(ema_scores) if ema_scores else 50.0

    # --- Composito ---
    final = latest_rsi * 0.35 + roc_score * 0.40 + ema_score * 0.25
    return float(np.clip(final, 0, 100))


def compute_asset_price_action_scores(
    all_assets: dict[str, pd.DataFrame],
) -> dict[str, float]:
    """
    Per ogni asset, calcola il punteggio price-action.
    Restituisce {asset: score 0-100}.
    """
    scores = {}
    for asset_name, df in all_assets.items():
        if df.empty or "Close" not in df.columns:
            scores[asset_name] = 50.0
            continue
        scores[asset_name] = round(_asset_strength(df), 2)
    # Fill missing
    for a in ASSETS:
        if a not in scores:
            scores[a] = 50.0
    return scores


# ═══════════════════════════════════════════════════════════════════════════════
# VOLUME SCORE PER ASSET
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_volume_scores(
    all_assets: dict[str, pd.DataFrame],
    price_scores: dict[str, float],
) -> dict[str, float]:
    """
    Il volume amplifica o attenua il segnale di prezzo.
    Restituisce {asset: score 0-100}.
    """
    scores = {}
    for asset_name in ASSETS:
        pa = price_scores.get(asset_name, 50)
        df = all_assets.get(asset_name)

        vr = 1.0
        if df is not None and not df.empty and "Volume" in df.columns:
            vol = df["Volume"].astype(float)
            sma_vol = vol.rolling(20).mean()
            if len(sma_vol.dropna()) > 0 and float(sma_vol.iloc[-1]) > 0:
                vr = float(vol.iloc[-1] / sma_vol.iloc[-1])

        deviation = pa - 50
        amplified = deviation * np.clip(vr, 0.5, 2.0)
        score = 50 + amplified
        scores[asset_name] = round(float(np.clip(score, 0, 100)), 2)

    return scores


# ═══════════════════════════════════════════════════════════════════════════════
# COMPOSITE SCORE PER ASSET
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_composite_scores(
    price_scores: dict[str, float],
    volume_scores: dict[str, float],
    cot_scores: dict[str, dict],
    c9_scores: dict[str, float] | None = None,
) -> dict[str, dict]:
    """
    Punteggio composito finale per ogni asset.
    """
    if c9_scores is None:
        c9_scores = {}
    results = {}
    for asset in ASSETS:
        pa = price_scores.get(asset, 50)
        vol = volume_scores.get(asset, 50)
        cot = cot_scores.get(asset, {}).get("score", 50)
        c9 = c9_scores.get(asset, 50)

        composite = (
            pa  * WEIGHT_PRICE_ACTION +
            vol * WEIGHT_VOLUME +
            cot * WEIGHT_COT +
            c9  * WEIGHT_C9
        )
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

        alert = None
        cot_info = cot_scores.get(asset, {})
        if composite >= THRESHOLD_EXTREME_BULL:
            alert = "⚠️ Forza estrema, possibile esaurimento"
        elif composite <= THRESHOLD_EXTREME_BEAR:
            alert = "⚠️ Debolezza estrema, possibile rimbalzo"
        if cot_info.get("extreme") == "CROWDED_LONG":
            alert = (alert or "") + " | COT: crowded LONG"
        elif cot_info.get("extreme") == "CROWDED_SHORT":
            alert = (alert or "") + " | COT: crowded SHORT"

        results[asset] = {
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
# MOMENTUM RANKING
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_momentum(
    all_assets: dict[str, pd.DataFrame],
    lookback: int = MOMENTUM_LOOKBACK,
) -> dict[str, dict]:
    """
    Cambiamento del punteggio nelle ultime N barre.
    """
    results = {}
    for asset in ASSETS:
        df = all_assets.get(asset)
        if df is None or df.empty or "Close" not in df.columns:
            results[asset] = {"delta": 0, "acceleration": 0, "rank_label": "N/A"}
            continue

        close = df["Close"]
        if len(close) < lookback * 2 + 5:
            results[asset] = {"delta": 0, "acceleration": 0, "rank_label": "N/A"}
            continue

        rets = close.pct_change()
        cum_recent = float(rets.iloc[-lookback:].sum() * 100)
        cum_prev = float(rets.iloc[-(lookback*2):-lookback].sum() * 100)

        delta = round(cum_recent, 2)
        acceleration = round(cum_recent - cum_prev, 2)

        if delta >= MOMENTUM_FAST_GAIN:
            rank_label = "🚀 GAINING FAST"
        elif delta <= MOMENTUM_FAST_LOSS:
            rank_label = "📉 LOSING FAST"
        elif delta > 0:
            rank_label = "↗ Gaining"
        elif delta < 0:
            rank_label = "↘ Losing"
        else:
            rank_label = "→ Flat"

        results[asset] = {
            "delta": delta,
            "acceleration": acceleration,
            "rank_label": rank_label,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFICAZIONE: TREND vs MEAN-REVERT
# ═══════════════════════════════════════════════════════════════════════════════

def classify_asset_trend_vs_reversion(
    all_assets: dict[str, pd.DataFrame],
) -> dict[str, dict]:
    """
    Per ogni asset: ADX, Hurst, Efficiency Ratio → trend score.
    """
    results = {}
    for asset in ASSETS:
        df = all_assets.get(asset)
        if df is None or df.empty:
            results[asset] = {
                "adx_avg": 20, "hurst": 0.5, "eff_ratio": 0.3,
                "trend_score": 50, "classification": "MIXED",
            }
            continue

        # ADX
        avg_adx = 20.0
        if len(df) > ADX_PERIOD * 3 and all(c in df.columns for c in ["High", "Low", "Close"]):
            adx_series = adx(df["High"], df["Low"], df["Close"], ADX_PERIOD)
            last_adx = float(adx_series.iloc[-1])
            if not np.isnan(last_adx):
                avg_adx = last_adx

        # Hurst
        h = 0.5
        if "Close" in df.columns and len(df) >= HURST_MIN_BARS:
            h = hurst_exponent(df["Close"].pct_change().dropna())

        # Efficiency Ratio
        er = 0.3
        if "Close" in df.columns and len(df) > 20:
            er_series = efficiency_ratio(df["Close"], 20)
            er = float(er_series.iloc[-1]) if not er_series.empty else 0.3

        # Score
        adx_norm = np.clip((avg_adx - ADX_RANGE_THRESH) /
                           (ADX_TREND_THRESH - ADX_RANGE_THRESH), 0, 1) * 100
        hurst_norm = np.clip((h - HURST_REVERT_THRESH) /
                             (HURST_TREND_THRESH - HURST_REVERT_THRESH), 0, 1) * 100
        er_norm = np.clip((er - EFFICIENCY_RANGE) /
                          (EFFICIENCY_TREND - EFFICIENCY_RANGE), 0, 1) * 100

        trend_score = (
            adx_norm   * CLASS_W_ADX +
            hurst_norm * CLASS_W_HURST +
            er_norm    * CLASS_W_ER
        )
        trend_score = round(float(np.clip(trend_score, 0, 100)), 1)

        if trend_score >= 65:
            classification = "TREND_FOLLOWING"
        elif trend_score <= 35:
            classification = "MEAN_REVERTING"
        else:
            classification = "MIXED"

        results[asset] = {
            "adx_avg": round(avg_adx, 1),
            "hurst": round(h, 3),
            "eff_ratio": round(er, 3),
            "trend_score": trend_score,
            "classification": classification,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# ATR / VOLATILITÀ PER ASSET
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_atr_context(
    all_assets: dict[str, pd.DataFrame],
) -> dict[str, dict]:
    """
    ATR corrente, percentile e regime di volatilità per ogni asset.
    """
    results = {}
    for asset in ASSETS:
        df = all_assets.get(asset)
        if df is None or df.empty or len(df) < ATR_PERIOD * 3:
            results[asset] = {"atr_pct": 0, "atr_percentile": 50, "volatility_regime": "NORMAL"}
            continue
        if not all(c in df.columns for c in ["High", "Low", "Close"]):
            results[asset] = {"atr_pct": 0, "atr_percentile": 50, "volatility_regime": "NORMAL"}
            continue

        atr_series = atr(df["High"], df["Low"], df["Close"])
        current_atr = float(atr_series.iloc[-1])
        close_price = float(df["Close"].iloc[-1])

        atr_pct = (current_atr / close_price) * 100 if close_price > 0 else 0

        lookback = min(50, len(atr_series))
        atr_window = atr_series.iloc[-lookback:]
        percentile = float((atr_window < current_atr).sum() / len(atr_window) * 100)

        if percentile >= 85:
            regime = "EXTREME"
        elif percentile >= 65:
            regime = "HIGH"
        elif percentile >= 35:
            regime = "NORMAL"
        else:
            regime = "LOW"

        results[asset] = {
            "atr_pct": round(atr_pct, 4),
            "atr_percentile": round(percentile, 1),
            "volatility_regime": regime,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# VELOCITY SCORE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_velocity(
    all_assets: dict[str, pd.DataFrame],
    lookback_bars: int = 20,
) -> dict[str, dict]:
    """
    Rapidità del movimento di ogni asset.
    Usa l'Efficiency Ratio sulla forza cumulativa:

        ER = |cambiamento direzionale| / path_length

    ER alto → movimento pulito e direzionale (trending)
    ER basso → movimento caotico e laterale

    Combina ER con la magnitudine del movimento (normalizzata per
    deviazione standard) per evitare di premiare movimenti piccoli
    ma "efficienti" o penalizzare movimenti graduali ma costanti.
    """
    results = {}
    for asset in ASSETS:
        df = all_assets.get(asset)
        if df is None or df.empty or "Close" not in df.columns:
            results[asset] = {"bars_to_move": 0, "velocity_norm": 50, "velocity_label": "N/A"}
            continue

        close = df["Close"]
        if len(close) < lookback_bars + 5:
            results[asset] = {"bars_to_move": 0, "velocity_norm": 50, "velocity_label": "N/A"}
            continue

        rets = close.pct_change()
        cum = (rets.rolling(lookback_bars).sum() * 100).dropna()
        if len(cum) < lookback_bars:
            results[asset] = {"bars_to_move": 0, "velocity_norm": 50, "velocity_label": "N/A"}
            continue

        recent = cum.iloc[-lookback_bars:]

        # --- Efficiency Ratio sulla forza cumulativa ---
        directional_change = abs(float(recent.iloc[-1] - recent.iloc[0]))
        path_length = float(recent.diff().abs().sum())
        efficiency = directional_change / path_length if path_length > 1e-10 else 0

        # --- Magnitudine normalizzata ---
        std_recent = float(recent.std()) if len(recent) > 1 else 1.0
        magnitude = directional_change / std_recent if std_recent > 1e-10 else 0
        magnitude_factor = float(np.clip(magnitude / 2.0, 0.3, 1.0))

        # --- Velocity norm (0-100) ---
        velocity_norm = efficiency * magnitude_factor * 120
        velocity_norm = round(float(np.clip(velocity_norm, 0, 100)), 1)

        # --- Bars to move (stima) ---
        avg_bar_change = path_length / lookback_bars if lookback_bars > 0 else 0
        bars_to_move = int(directional_change / avg_bar_change) if avg_bar_change > 1e-10 else 0

        # Label
        if velocity_norm >= 70:
            label = "⚡ VERY FAST"
        elif velocity_norm >= 50:
            label = "🏃 FAST"
        elif velocity_norm >= 35:
            label = "🚶 MODERATE"
        elif velocity_norm >= 20:
            label = "🐢 SLOW"
        else:
            label = "🧊 STALE"

        results[asset] = {
            "bars_to_move": bars_to_move,
            "velocity_norm": velocity_norm,
            "velocity_label": label,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# TREND STRUCTURE  (cascata EMA per asset)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_trend_structure(
    all_assets: dict[str, pd.DataFrame],
) -> dict[str, dict]:
    """
    Per ogni asset, valuta l'allineamento della cascata EMA.

    Cascata completa bullish: EMA_FAST > EMA_MEDIUM > EMA_SLOW
    Cascata completa bearish: EMA_FAST < EMA_MEDIUM < EMA_SLOW

    Restituisce {asset: {ema_alignment: float (-1..+1), structure_label: str}}
    """
    results = {}
    for asset in ASSETS:
        df = all_assets.get(asset)
        if df is None or df.empty or "Close" not in df.columns:
            results[asset] = {"ema_alignment": 0.0, "structure_label": "➖ Nessuna cascata"}
            continue

        close = df["Close"]
        if len(close) < EMA_SLOW + 5:
            results[asset] = {"ema_alignment": 0.0, "structure_label": "➖ Nessuna cascata"}
            continue

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

        if alignment >= 0.5:
            label = "📈 CASCATA BULL"
        elif alignment <= -0.5:
            label = "📉 CASCATA BEAR"
        elif alignment >= 0.2:
            label = "↗ Parziale bull"
        elif alignment <= -0.2:
            label = "↘ Parziale bear"
        else:
            label = "➖ Nessuna cascata"

        results[asset] = {
            "ema_alignment": round(alignment, 3),
            "structure_label": label,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# ROLLING STRENGTH (per grafico storico)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_rolling_strength(
    all_assets: dict[str, pd.DataFrame],
    window: int = 20,
    cot_scores: dict[str, dict] | None = None,
) -> pd.DataFrame:
    """
    Score composito rolling (0-100) per ogni asset a ogni barra.
    """
    from asset_data_fetcher import compute_asset_volume_ratio

    frames = {}
    for asset in ASSETS:
        df = all_assets.get(asset)
        if df is None or df.empty or "Close" not in df.columns:
            continue
        if len(df) < max(RSI_PERIOD, ROC_SLOW, EMA_SLOW) + 5:
            continue

        close = df["Close"]

        # RSI rolling
        rsi_vals = rsi(close, RSI_PERIOD)

        # ROC multi-periodo
        roc_f = roc(close, ROC_FAST)
        roc_m = roc(close, ROC_MEDIUM)
        roc_s = roc(close, ROC_SLOW)
        avg_roc = roc_f * 0.5 + roc_m * 0.3 + roc_s * 0.2
        roc_score = 50 + (avg_roc * 10).clip(-50, 50)

        # EMA positioning
        ema_components = []
        for p in [EMA_FAST, EMA_MEDIUM, EMA_SLOW]:
            if len(close) > p:
                e = ema(close, p)
                pct_above = ((close / e) - 1) * 100
                ema_components.append((50 + (pct_above * 15).clip(-50, 50)))
        if ema_components:
            ema_score = pd.concat(ema_components, axis=1).mean(axis=1)
        else:
            ema_score = pd.Series(50.0, index=close.index)

        # Price action
        pa_score = (rsi_vals * 0.35 + roc_score * 0.40 + ema_score * 0.25).clip(0, 100)

        # Volume amplification
        vol_score = pa_score.copy()
        if "Volume" in df.columns:
            vol = df["Volume"].astype(float)
            sma_vol = vol.rolling(20).mean()
            vr = (vol / sma_vol).replace([np.inf, -np.inf], np.nan).fillna(1.0)
            deviation = pa_score - 50
            amplified = deviation * vr.clip(0.5, 2.0)
            vol_score = (50 + amplified).clip(0, 100)

        # COT (costante)
        cot_val = cot_scores.get(asset, {}).get("score", 50) if cot_scores else 50

        # C9 rolling: magnitude + velocity
        lookback_c9 = 9
        c9_score = pd.Series(50.0, index=close.index)
        if len(close) >= lookback_c9 + 2:
            pct_c9 = close.pct_change(lookback_c9, fill_method=None) * 100
            mag = 50 + (pct_c9 * 25).clip(-50, 50)
            slope_s = close.rolling(lookback_c9 + 1).apply(
                lambda w: np.polyfit(np.arange(len(w)), w.values, 1)[0] / np.mean(w) * 100
                if len(w) >= 2 and np.mean(w) > 0 else 0,
                raw=False,
            )
            vel_s = 50 + (slope_s * 200).clip(-50, 50)
            c9_score = (mag * 0.60 + vel_s * 0.40).clip(0, 100)

        composite_ts = (
            pa_score  * WEIGHT_PRICE_ACTION +
            vol_score * WEIGHT_VOLUME +
            cot_val   * WEIGHT_COT +
            c9_score  * WEIGHT_C9
        ).clip(0, 100)

        frames[asset] = composite_ts

    if not frames:
        return pd.DataFrame()

    result = pd.DataFrame(frames)
    return result.dropna(how="all")


# ═══════════════════════════════════════════════════════════════════════════════
# CORRELAZIONE TRA ASSET
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_correlation(
    all_assets: dict[str, pd.DataFrame],
    window: int = 30,
) -> pd.DataFrame:
    """
    Matrice di correlazione rolling tra gli asset.
    """
    rets = {}
    for asset in ASSETS:
        df = all_assets.get(asset)
        if df is not None and not df.empty and "Close" in df.columns:
            rets[asset] = df["Close"].pct_change()

    if not rets:
        return pd.DataFrame(np.eye(len(ASSETS)), index=ASSETS, columns=ASSETS)

    rets_df = pd.DataFrame(rets)
    if len(rets_df) < window:
        return rets_df.corr().round(3)

    recent = rets_df.iloc[-window:]
    return recent.corr().round(3)


# ═══════════════════════════════════════════════════════════════════════════════
# STRENGTH PERSISTENCE  (persistenza direzionale per asset)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_strength_persistence(
    rolling_strength: pd.DataFrame,
    window: int = 10,
) -> dict[str, dict]:
    """
    Misura la persistenza direzionale della forza di ogni asset.
    Analizza le ultime `window` barre di rolling strength.
    """
    results = {}
    for asset in ASSETS:
        if rolling_strength.empty or asset not in rolling_strength.columns:
            results[asset] = {"persistence": 0.0, "slope": 0.0,
                              "consistency_label": "N/A"}
            continue

        col = rolling_strength[asset].dropna()
        if len(col) < window // 2:
            results[asset] = {"persistence": 0.0, "slope": 0.0,
                              "consistency_label": "N/A"}
            continue

        recent = col.iloc[-window:] if len(col) >= window else col

        above_55 = float((recent > 55).sum()) / len(recent)
        below_45 = float((recent < 45).sum()) / len(recent)

        if above_55 >= below_45:
            persistence = above_55
            direction = "BULL"
        else:
            persistence = -below_45
            direction = "BEAR"

        slope = 0.0
        if len(recent) >= 3:
            x = np.arange(len(recent))
            slope = float(np.polyfit(x, recent.values, 1)[0])

        abs_p = abs(persistence)
        if abs_p >= 0.7:
            label = f"🔒 PERSISTENTE {direction}"
        elif abs_p >= 0.4:
            label = f"{'↗' if direction == 'BULL' else '↘'} Trending {direction.lower()}"
        else:
            label = "🔀 Inconsistente"

        results[asset] = {
            "persistence": round(persistence, 3),
            "slope": round(slope, 4),
            "consistency_label": label,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# SMOOTHING COMPOSITO (anti-flickering per asset)
# ═══════════════════════════════════════════════════════════════════════════════

def smooth_asset_composite_scores(
    current: dict[str, dict],
    previous: dict[str, dict] | None,
    alpha: float = SCORE_SMOOTHING_ALPHA,
) -> dict[str, dict]:
    """
    Applica smoothing esponenziale ai punteggi compositi degli asset
    per ridurre le oscillazioni orarie.

    Formula:  smoothed = α * current + (1 − α) * previous
    """
    if previous is None or alpha >= 1.0:
        return current

    smoothed = {}
    for asset in ASSETS:
        cur = current.get(asset, {})
        prev = previous.get(asset, {})

        if not prev or prev.get("composite") is None:
            smoothed[asset] = cur
            continue

        sm = cur.copy()
        for key in ("price_score", "volume_score", "cot_score", "c9_score", "composite"):
            c_val = cur.get(key, 50)
            p_val = prev.get(key, 50)
            sm[key] = round(alpha * c_val + (1 - alpha) * p_val, 1)

        # H4, Daily, Weekly se presenti (blend composito)
        for key in ("h4_score", "daily_score", "weekly_score"):
            if key in cur and key in prev:
                sm[key] = round(alpha * cur[key] + (1 - alpha) * prev[key], 1)

        # Ricalcola label
        comp = sm["composite"]
        if comp >= THRESHOLD_EXTREME_BULL:
            sm["label"] = "VERY STRONG"
        elif comp >= THRESHOLD_STRONG_BULL:
            sm["label"] = "STRONG"
        elif comp <= THRESHOLD_EXTREME_BEAR:
            sm["label"] = "VERY WEAK"
        elif comp <= THRESHOLD_STRONG_BEAR:
            sm["label"] = "WEAK"
        else:
            sm["label"] = "NEUTRAL"

        smoothed[asset] = sm

    return smoothed


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE SETUP SCORE (confronto relative tra asset)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_trade_setups(
    composite: dict[str, dict],
    momentum: dict[str, dict],
    classification: dict[str, dict],
    atr_context: dict[str, dict],
    cot_scores: dict[str, dict],
    velocity_scores: dict[str, dict] | None = None,
    trend_structure: dict[str, dict] | None = None,
    strength_persistence: dict[str, dict] | None = None,
    candle9: dict[str, dict] | None = None,
) -> list[dict]:
    """
    Per ogni asset, calcola un punteggio di qualità del setup
    basato su: forza composita, momentum, regime, volatilità, COT, velocità,
    struttura trend, accelerazione momentum, persistenza forza.
    """
    if velocity_scores is None:
        velocity_scores = {}
    if trend_structure is None:
        trend_structure = {}
    if strength_persistence is None:
        strength_persistence = {}
    if candle9 is None:
        candle9 = {}

    setups = []
    for asset in ASSETS:
        c = composite.get(asset, {})
        score_val = c.get("composite", 50)
        diff_from_neutral = score_val - 50

        if abs(diff_from_neutral) < MIN_DIFFERENTIAL_THRESHOLD:
            continue

        direction = "LONG" if diff_from_neutral > 0 else "SHORT"

        quality = 0
        reasons = []

        # 1. Distanza dal neutro (0-30)
        dist = abs(diff_from_neutral)
        dist_pts = min(dist * 1.0, 30)
        quality += dist_pts
        if dist >= 15:
            reasons.append(f"Forza {dist:.0f} pts da neutro")

        # 2. Momentum concordante (0-20)
        mom = momentum.get(asset, {})
        mom_delta = mom.get("delta", 0)
        if (direction == "LONG" and mom_delta > 0) or \
           (direction == "SHORT" and mom_delta < 0):
            quality += 20
            reasons.append("Momentum allineato")
        elif abs(mom_delta) > 0:
            quality += 10
            reasons.append("Momentum parziale")

        # 3. Regime trending (0-15)
        cls = classification.get(asset, {})
        if cls.get("classification") == "TREND_FOLLOWING":
            quality += 15
            reasons.append("Regime trending")
        elif cls.get("classification") == "MIXED":
            quality += 7

        # 4. Volatilità (0-15)
        atr_info = atr_context.get(asset, {})
        vol_regime = atr_info.get("volatility_regime", "NORMAL")
        if vol_regime in ("NORMAL", "LOW"):
            quality += 10
            reasons.append(f"Volatilità {vol_regime.lower()}")
        elif vol_regime == "HIGH":
            quality += 5
        if vol_regime == "EXTREME":
            quality -= 5
            reasons.append("⚠️ Volatilità estrema")

        # 5. COT concordante (0-10, dimezzato se stale)
        cot_info = cot_scores.get(asset, {})
        cot_bias = cot_info.get("bias", "NEUTRAL")
        cot_fresh = cot_info.get("freshness_days", 0)
        cot_mult = 0.5 if cot_fresh > COT_STALE_DAYS_THRESHOLD else 1.0
        if cot_mult < 1.0:
            reasons.append(f"⚠️ COT non aggiornato ({cot_fresh}gg)")
        cot_pts = 0
        if (direction == "LONG" and cot_bias == "BULLISH") or \
           (direction == "SHORT" and cot_bias == "BEARISH"):
            cot_pts = 10
            reasons.append(f"COT {cot_bias.lower()}")
        quality += cot_pts * cot_mult
        if cot_info.get("extreme") == "CROWDED_LONG" and direction == "LONG":
            quality -= 10
            reasons.append("⚠️ COT crowded long")
        if cot_info.get("extreme") == "CROWDED_SHORT" and direction == "SHORT":
            quality -= 10
            reasons.append("⚠️ COT crowded short")

        # 6. Sinergia forza + momentum (0-5 bonus)
        if dist >= 15 and mom_delta != 0 and (
            (direction == "LONG" and mom_delta > 0) or
            (direction == "SHORT" and mom_delta < 0)
        ):
            quality += 5
            reasons.append("Sinergia forza+momentum")

        # 7. Velocity (0-10)
        vel = velocity_scores.get(asset, {})
        vel_n = vel.get("velocity_norm", 50)
        if vel_n >= 65:
            quality += 10
            reasons.append(f"Velocità alta ({vel_n:.0f})")
        elif vel_n >= 40:
            quality += 5
        if vel_n < 15:
            quality -= 3
            reasons.append("⚠️ Movimento stagnante")

        # 8. Trend structure — cascata EMA (0-8 punti, -5 penalità)
        ts = trend_structure.get(asset, {})
        align = ts.get("ema_alignment", 0)
        if direction == "LONG":
            if align >= 0.5:
                quality += 8
                reasons.append("Cascata EMA rialzista")
            elif align >= 0.2:
                quality += 4
            elif align <= -0.3:
                quality -= 5
                reasons.append("⚠️ Cascata EMA contro-tendenza")
        else:  # SHORT
            if align <= -0.5:
                quality += 8
                reasons.append("Cascata EMA ribassista")
            elif align <= -0.2:
                quality += 4
            elif align >= 0.3:
                quality -= 5
                reasons.append("⚠️ Cascata EMA contro-tendenza")

        # 9. Momentum acceleration (0-5 bonus, -3 penalità)
        mom = momentum.get(asset, {})
        accel = mom.get("acceleration", 0)
        if (direction == "LONG" and accel > 0) or (direction == "SHORT" and accel < 0):
            quality += 5
            reasons.append("Momentum in accelerazione")
        elif abs(accel) > 0:
            quality += 2
        if (direction == "LONG" and accel < 0 and mom_delta <= 0) or \
           (direction == "SHORT" and accel > 0 and mom_delta >= 0):
            quality -= 3
            reasons.append("⚠️ Momentum in decelerazione")

        # 10. Strength persistence (0-8 punti, -3 penalità)
        pers = strength_persistence.get(asset, {})
        p = pers.get("persistence", 0)
        if (direction == "LONG" and p >= 0.5) or (direction == "SHORT" and p <= -0.5):
            quality += 8
            reasons.append("Forza persistente")
        elif (direction == "LONG" and p >= 0.3) or (direction == "SHORT" and p <= -0.3):
            quality += 4
        if abs(p) < 0.2:
            quality -= 3
            reasons.append("⚠️ Forza non persistente")

        # 11. Candle-9 concordante (0-25 punti, -12 penalità)
        if candle9:
            c9 = candle9.get(asset, {})
            c9_ratio = c9.get("candle9_ratio", 0)
            # Asset LONG e C9 bullish → bonus
            if direction == "LONG" and c9_ratio > 0.1:
                c9_pts = round(min(abs(c9_ratio) * 25, 25))
                quality += c9_pts
                reasons.append(f"C9 allineato ({c9_ratio:+.2f}%)")
            elif direction == "SHORT" and c9_ratio < -0.1:
                c9_pts = round(min(abs(c9_ratio) * 25, 25))
                quality += c9_pts
                reasons.append(f"C9 allineato ({c9_ratio:+.2f}%)")
            elif (direction == "LONG" and c9_ratio > 0.05) or \
                 (direction == "SHORT" and c9_ratio < -0.05):
                quality += 10
                reasons.append("C9 parzialmente allineato")
            # Penalità: C9 in contro-direzione
            if (direction == "LONG" and c9_ratio < -0.1) or \
               (direction == "SHORT" and c9_ratio > 0.1):
                quality -= 12
                reasons.append("⚠️ C9 contro-direzione")

        quality = max(quality, 0)

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

        setups.append({
            "asset": asset,
            "asset_label": ASSET_LABELS.get(asset, asset),
            "direction": direction,
            "strength": round(score_val, 1),
            "differential": round(diff_from_neutral, 1),
            "quality_score": round(quality, 1),
            "grade": grade,
            "reasons": reasons,
        })

    setups.sort(key=lambda x: x["quality_score"], reverse=True)
    return setups


# ═══════════════════════════════════════════════════════════════════════════════
# CANDLE-9 SCORE (0-100) per composito — magnitude + velocity + consistency
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_candle9_scores(
    all_assets: dict[str, pd.DataFrame],
    lookback: int = 9,
) -> dict[str, float]:
    """
    Score 0-100 per asset basato su escursione e velocità rispetto a 9 candele fa.
    Componenti:
      - Magnitude (50%): % variazione close attuale vs close 9 candele fa
      - Velocity  (35%): pendenza lineare del close nelle ultime 9 candele
      - Consistency (15%): % di candele nella stessa direzione
    """
    results = {}
    for asset in ASSETS:
        df = all_assets.get(asset)
        if df is None or df.empty or "Close" not in df.columns:
            results[asset] = 50.0
            continue

        close = df["Close"]
        if len(close) < lookback + 2:
            results[asset] = 50.0
            continue

        current_close = float(close.iloc[-1])
        past_close = float(close.iloc[-(lookback + 1)])
        if past_close == 0:
            results[asset] = 50.0
            continue

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

        # Consistency: quante candele nella stessa direzione
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

        magnitude_score = 50 + np.clip(pct_change * 25, -50, 50)
        velocity_score = 50 + np.clip(slope_pct * 200, -50, 50)
        consistency_bonus = consistency * 10

        score = (
            magnitude_score * 0.50 +
            velocity_score * 0.35 +
            (50 + consistency_bonus) * 0.15
        )
        results[asset] = round(float(np.clip(score, 0, 100)), 2)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# CANDLE-9 PRICE ACTION PER ASSET (close attuale vs close 9 candele fa)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_candle9_signal(
    all_assets: dict[str, pd.DataFrame],
    lookback: int = 9,
) -> dict[str, dict]:
    """
    Per ogni asset, confronta il close della candela attuale con il close
    di N candele precedenti (default 9).

    Close attuale > close[−9] → segnale BULLISH (forza)
    Close attuale < close[−9] → segnale BEARISH (debolezza)

    Restituisce:
      {asset: {
          "candle9_ratio":  float,   # variazione % vs candela 9
          "candle9_signal": str,     # 🟢 BULLISH / 🔴 BEARISH / ➖ NEUTRO
          "candle9_current": float,  # close attuale
          "candle9_past":   float,   # close 9 candele fa
      }}
    """
    results = {}
    for asset in ASSETS:
        df = all_assets.get(asset)
        if df is None or df.empty or "Close" not in df.columns:
            results[asset] = {
                "candle9_ratio": 0.0,
                "candle9_signal": "➖ NEUTRO",
                "candle9_current": 0.0,
                "candle9_past": 0.0,
            }
            continue

        close = df["Close"]
        if len(close) < lookback + 1:
            results[asset] = {
                "candle9_ratio": 0.0,
                "candle9_signal": "➖ NEUTRO",
                "candle9_current": float(close.iloc[-1]) if len(close) > 0 else 0.0,
                "candle9_past": 0.0,
            }
            continue

        current_close = float(close.iloc[-1])
        past_close = float(close.iloc[-(lookback + 1)])

        if past_close == 0:
            pct_change = 0.0
        else:
            pct_change = ((current_close - past_close) / past_close) * 100

        # Soglia: ±0.1% per segnale (asset più volatili delle valute)
        if pct_change > 0.1:
            signal = "🟢 BULLISH"
        elif pct_change < -0.1:
            signal = "🔴 BEARISH"
        else:
            signal = "➖ NEUTRO"

        results[asset] = {
            "candle9_ratio": round(pct_change, 3),
            "candle9_signal": signal,
            "candle9_current": round(current_close, 4),
            "candle9_past": round(past_close, 4),
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# FULL ANALYSIS (entry-point)
# ═══════════════════════════════════════════════════════════════════════════════

def full_asset_analysis(
    all_assets: dict[str, pd.DataFrame],
    cot_scores: dict[str, dict],
) -> dict:
    """
    Analisi completa per tutti gli asset.
    """
    price_scores = compute_asset_price_action_scores(all_assets)
    volume_scores = compute_asset_volume_scores(all_assets, price_scores)
    c9_scores = compute_asset_candle9_scores(all_assets)
    composite = compute_asset_composite_scores(price_scores, volume_scores, cot_scores, c9_scores)
    momentum = compute_asset_momentum(all_assets)
    classification = classify_asset_trend_vs_reversion(all_assets)
    rolling = compute_asset_rolling_strength(all_assets, window=20, cot_scores=cot_scores)
    atr_ctx = compute_asset_atr_context(all_assets)
    velocity = compute_asset_velocity(all_assets)
    trend_structure = compute_asset_trend_structure(all_assets)
    persistence = compute_asset_strength_persistence(rolling)
    candle9 = compute_asset_candle9_signal(all_assets)

    return {
        "composite": composite,
        "momentum": momentum,
        "classification": classification,
        "rolling_strength": rolling,
        "atr_context": atr_ctx,
        "velocity": velocity,
        "trend_structure": trend_structure,
        "strength_persistence": persistence,
        "candle9": candle9,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BLEND MULTI-TIMEFRAME (H4 + Daily + Weekly)
# ═══════════════════════════════════════════════════════════════════════════════

def blend_asset_multi_timeframe(
    analysis_h4: dict,
    analysis_daily: dict,
    analysis_weekly: dict,
    w_h4: float = ASSET_COMPOSITE_WEIGHT_H4,
    w_daily: float = ASSET_COMPOSITE_WEIGHT_DAILY,
    w_weekly: float = ASSET_COMPOSITE_WEIGHT_WEEKLY,
) -> dict:
    """
    Unisce l'analisi H4, Daily e Weekly in un composito unico.
    H4 → reattività intraday, Daily → base, Weekly → stabilità strutturale.
    """
    composite_h = analysis_h4["composite"]
    composite_d = analysis_daily["composite"]
    composite_w = analysis_weekly["composite"]
    momentum_h  = analysis_h4["momentum"]
    momentum_d  = analysis_daily["momentum"]
    momentum_w  = analysis_weekly["momentum"]
    class_h     = analysis_h4["classification"]
    class_d     = analysis_daily["classification"]
    class_w     = analysis_weekly["classification"]
    rolling_h   = analysis_h4["rolling_strength"]
    rolling_d   = analysis_daily["rolling_strength"]
    rolling_w   = analysis_weekly["rolling_strength"]

    # 1. Composite blendato (con decay W per-asset)
    blended_composite = {}
    for asset in ASSETS:
        ch = composite_h.get(asset, {})
        cd = composite_d.get(asset, {})
        cw = composite_w.get(asset, {})

        # ── Decay accelerato W quando H4 e D1 divergono ──
        s_h4 = ch.get("composite", 50)
        s_d1 = cd.get("composite", 50)
        gap = abs(s_h4 - s_d1)
        opposite_sides = (s_h4 >= 50 and s_d1 < 50) or (s_h4 < 50 and s_d1 >= 50)

        if gap > ASSET_W_DIVERGENCE_THRESHOLD:
            raw_decay = min((gap - ASSET_W_DIVERGENCE_THRESHOLD) /
                            (ASSET_W_DIVERGENCE_MAX - ASSET_W_DIVERGENCE_THRESHOLD), 1.0)
            if opposite_sides:
                raw_decay = min(raw_decay + ASSET_W_DECAY_OPPOSITE_BONUS, 1.0)

            eff_w = max(w_weekly * (1 - raw_decay), ASSET_W_DECAY_MIN_WEIGHT)
            freed = w_weekly - eff_w
            ratio_h4d1 = w_h4 / (w_h4 + w_daily) if (w_h4 + w_daily) > 0 else 0.5
            eff_h4 = w_h4 + freed * ratio_h4d1
            eff_daily = w_daily + freed * (1 - ratio_h4d1)
            w_decay_pct = round((1 - eff_w / w_weekly) * 100) if w_weekly > 0 else 0
        else:
            eff_h4, eff_daily, eff_w = w_h4, w_daily, w_weekly
            w_decay_pct = 0
            gap = round(gap, 1)

        pa  = ch.get("price_score", 50) * eff_h4 + cd.get("price_score", 50) * eff_daily + cw.get("price_score", 50) * eff_w
        vol = ch.get("volume_score", 50) * eff_h4 + cd.get("volume_score", 50) * eff_daily + cw.get("volume_score", 50) * eff_w
        cot = ch.get("cot_score", 50) * eff_h4 + cd.get("cot_score", 50) * eff_daily + cw.get("cot_score", 50) * eff_w
        c9  = ch.get("c9_score", 50) * eff_h4 + cd.get("c9_score", 50) * eff_daily + cw.get("c9_score", 50) * eff_w
        comp = ch.get("composite", 50) * eff_h4 + cd.get("composite", 50) * eff_daily + cw.get("composite", 50) * eff_w
        comp = round(float(np.clip(comp, 0, 100)), 1)

        if comp >= THRESHOLD_EXTREME_BULL:
            label = "VERY STRONG"
        elif comp >= THRESHOLD_STRONG_BULL:
            label = "STRONG"
        elif comp <= THRESHOLD_EXTREME_BEAR:
            label = "VERY WEAK"
        elif comp <= THRESHOLD_STRONG_BEAR:
            label = "WEAK"
        else:
            label = "NEUTRAL"

        alert = None
        if comp >= THRESHOLD_EXTREME_BULL:
            alert = "⚠️ Forza estrema"
        elif comp <= THRESHOLD_EXTREME_BEAR:
            alert = "⚠️ Debolezza estrema"
        cot_ext = cw.get("cot_extreme") or cd.get("cot_extreme") or ch.get("cot_extreme")
        if cot_ext == "CROWDED_LONG":
            alert = (alert or "") + " | COT crowded LONG"
        elif cot_ext == "CROWDED_SHORT":
            alert = (alert or "") + " | COT crowded SHORT"

        concordance = _concordance_label(
            ch.get("composite", 50), cd.get("composite", 50), cw.get("composite", 50)
        )

        blended_composite[asset] = {
            "price_score": round(pa, 1),
            "volume_score": round(vol, 1),
            "cot_score": round(cot, 1),
            "c9_score": round(c9, 1),
            "composite": comp,
            "label": label,
            "alert": alert,
            "cot_bias": cw.get("cot_bias", "NEUTRAL"),
            "cot_extreme": cot_ext,
            "h4_score": round(ch.get("composite", 50), 1),
            "daily_score": round(cd.get("composite", 50), 1),
            "weekly_score": round(cw.get("composite", 50), 1),
            "concordance": concordance,
            "w_decay_pct": w_decay_pct,
            "w_eff_weight": round(eff_w, 3),
            "h4d1_gap": round(gap, 1),
            "h4d1_opposite": opposite_sides,
        }

    # 2. Momentum blendato
    blended_momentum = {}
    for asset in ASSETS:
        mh = momentum_h.get(asset, {"delta": 0, "acceleration": 0})
        md = momentum_d.get(asset, {"delta": 0, "acceleration": 0})
        mw = momentum_w.get(asset, {"delta": 0, "acceleration": 0})
        delta = mh["delta"] * w_h4 + md["delta"] * w_daily + mw["delta"] * w_weekly
        accel = mh["acceleration"] * w_h4 + md["acceleration"] * w_daily + mw["acceleration"] * w_weekly
        delta = round(delta, 2)
        accel = round(accel, 2)

        if delta >= MOMENTUM_FAST_GAIN:
            rank_label = "🚀 GAINING FAST"
        elif delta <= MOMENTUM_FAST_LOSS:
            rank_label = "📉 LOSING FAST"
        elif delta > 0:
            rank_label = "↗ Gaining"
        elif delta < 0:
            rank_label = "↘ Losing"
        else:
            rank_label = "→ Flat"

        blended_momentum[asset] = {
            "delta": delta,
            "acceleration": accel,
            "rank_label": rank_label,
        }

    # 3. Classification blendato
    blended_class = {}
    for asset in ASSETS:
        clh = class_h.get(asset, {})
        cld = class_d.get(asset, {})
        clw = class_w.get(asset, {})
        adx_avg = clh.get("adx_avg", 20) * w_h4 + cld.get("adx_avg", 20) * w_daily + clw.get("adx_avg", 20) * w_weekly
        hurst   = clh.get("hurst", 0.5) * w_h4 + cld.get("hurst", 0.5) * w_daily + clw.get("hurst", 0.5) * w_weekly
        er      = clh.get("eff_ratio", 0.3) * w_h4 + cld.get("eff_ratio", 0.3) * w_daily + clw.get("eff_ratio", 0.3) * w_weekly
        ts      = clh.get("trend_score", 50) * w_h4 + cld.get("trend_score", 50) * w_daily + clw.get("trend_score", 50) * w_weekly
        ts = round(float(np.clip(ts, 0, 100)), 1)

        if ts >= 65:
            classification = "TREND_FOLLOWING"
        elif ts <= 35:
            classification = "MEAN_REVERTING"
        else:
            classification = "MIXED"

        blended_class[asset] = {
            "adx_avg": round(adx_avg, 1),
            "hurst": round(hurst, 3),
            "eff_ratio": round(er, 3),
            "trend_score": ts,
            "classification": classification,
        }

    # 4. Rolling strength blendato
    blended_rolling = _blend_rolling_3tf(rolling_h, rolling_d, rolling_w, w_h4, w_daily, w_weekly)

    # 5. Velocity blendato
    vel_h = analysis_h4.get("velocity", {})
    vel_d = analysis_daily.get("velocity", {})
    vel_w = analysis_weekly.get("velocity", {})
    blended_velocity = {}
    for asset in ASSETS:
        vh = vel_h.get(asset, {"bars_to_move": 0, "velocity_norm": 50})
        vd = vel_d.get(asset, {"bars_to_move": 0, "velocity_norm": 50})
        vw = vel_w.get(asset, {"bars_to_move": 0, "velocity_norm": 50})
        vn = vh["velocity_norm"] * w_h4 + vd["velocity_norm"] * w_daily + vw["velocity_norm"] * w_weekly
        btm = round(vh["bars_to_move"] * w_h4 + vd["bars_to_move"] * w_daily + vw["bars_to_move"] * w_weekly)
        vn = round(float(np.clip(vn, 0, 100)), 1)
        if vn >= 70:
            vlabel = "⚡ VERY FAST"
        elif vn >= 50:
            vlabel = "🏃 FAST"
        elif vn >= 35:
            vlabel = "🚶 MODERATE"
        elif vn >= 20:
            vlabel = "🐢 SLOW"
        else:
            vlabel = "🧊 STALE"
        blended_velocity[asset] = {
            "bars_to_move": btm,
            "velocity_norm": vn,
            "velocity_label": vlabel,
        }

    # 6. ATR blendato
    atr_h = analysis_h4.get("atr_context", {})
    atr_d = analysis_daily.get("atr_context", {})
    atr_w = analysis_weekly.get("atr_context", {})
    blended_atr = {}
    for asset in ASSETS:
        ah = atr_h.get(asset, {"atr_pct": 0, "atr_percentile": 50})
        ad = atr_d.get(asset, {"atr_pct": 0, "atr_percentile": 50})
        aw = atr_w.get(asset, {"atr_pct": 0, "atr_percentile": 50})
        avg_pct = ah["atr_pct"] * w_h4 + ad["atr_pct"] * w_daily + aw["atr_pct"] * w_weekly
        avg_perc = ah["atr_percentile"] * w_h4 + ad["atr_percentile"] * w_daily + aw["atr_percentile"] * w_weekly
        if avg_perc >= 85:
            regime = "EXTREME"
        elif avg_perc >= 65:
            regime = "HIGH"
        elif avg_perc >= 35:
            regime = "NORMAL"
        else:
            regime = "LOW"
        blended_atr[asset] = {
            "atr_pct": round(avg_pct, 4),
            "atr_percentile": round(avg_perc, 1),
            "volatility_regime": regime,
        }

    # 7. Candle-9 blendato
    c9_h = analysis_h4.get("candle9", {})
    c9_d = analysis_daily.get("candle9", {})
    c9_w = analysis_weekly.get("candle9", {})
    blended_candle9 = {}
    for asset in ASSETS:
        sh = c9_h.get(asset, {"candle9_ratio": 0, "candle9_current": 0, "candle9_past": 0})
        sd = c9_d.get(asset, {"candle9_ratio": 0, "candle9_current": 0, "candle9_past": 0})
        sw = c9_w.get(asset, {"candle9_ratio": 0, "candle9_current": 0, "candle9_past": 0})
        ratio = sh["candle9_ratio"] * w_h4 + sd["candle9_ratio"] * w_daily + sw["candle9_ratio"] * w_weekly
        ratio = round(ratio, 3)
        if ratio > 0.1:
            signal = "🟢 BULLISH"
        elif ratio < -0.1:
            signal = "🔴 BEARISH"
        else:
            signal = "➖ NEUTRO"
        blended_candle9[asset] = {
            "candle9_ratio": ratio,
            "candle9_signal": signal,
            "candle9_current": sd.get("candle9_current", 0),
            "candle9_past": sd.get("candle9_past", 0),
        }

    return {
        "composite": blended_composite,
        "momentum": blended_momentum,
        "classification": blended_class,
        "rolling_strength": blended_rolling,
        "atr_context": blended_atr,
        "velocity": blended_velocity,
        "trend_structure": _blend_asset_trend_structure(analysis_h4, analysis_daily, analysis_weekly, w_h4, w_daily, w_weekly),
        "strength_persistence": _blend_asset_strength_persistence(analysis_h4, analysis_daily, analysis_weekly, w_h4, w_daily, w_weekly),
        "candle9": blended_candle9,
        "h4_analysis": analysis_h4,
        "daily_analysis": analysis_daily,
        "weekly_analysis": analysis_weekly,
    }


def _blend_rolling_3tf(r_h, r_d, r_w, w_h4, w_daily, w_weekly):
    """Blend rolling_strength DataFrame da 3 timeframe."""
    frames = [(r_h, w_h4), (r_d, w_daily), (r_w, w_weekly)]
    non_empty = [(f, w) for f, w in frames if isinstance(f, pd.DataFrame) and not f.empty]
    if not non_empty:
        return pd.DataFrame()
    if len(non_empty) == 1:
        return non_empty[0][0]
    # Usa il frame con più righe come base (tipicamente daily)
    base_df, base_w = max(non_empty, key=lambda x: len(x[0]))
    blended = base_df.copy() * base_w
    for f, w in non_empty:
        if f is base_df:
            continue
        common_cols = base_df.columns.intersection(f.columns)
        if len(common_cols) > 0:
            reindexed = f[common_cols].reindex(base_df.index, method="ffill").fillna(base_df[common_cols])
            blended[common_cols] = blended[common_cols] + reindexed * w
    return blended


def _blend_asset_trend_structure(a_h: dict, a_d: dict, a_w: dict,
                                  w_h: float, w_d: float, w_w: float) -> dict[str, dict]:
    """Blend trend_structure tra H4, Daily e Weekly."""
    ts_h = a_h.get("trend_structure", {})
    ts_d = a_d.get("trend_structure", {})
    ts_w = a_w.get("trend_structure", {})
    blended = {}
    for asset in ASSETS:
        th = ts_h.get(asset, {"ema_alignment": 0})
        td = ts_d.get(asset, {"ema_alignment": 0})
        tw = ts_w.get(asset, {"ema_alignment": 0})
        avg = th["ema_alignment"] * w_h + td["ema_alignment"] * w_d + tw["ema_alignment"] * w_w
        avg = round(avg, 3)
        if avg >= 0.5:
            label = "📈 CASCATA BULL"
        elif avg <= -0.5:
            label = "📉 CASCATA BEAR"
        elif avg >= 0.2:
            label = "↗ Parziale bull"
        elif avg <= -0.2:
            label = "↘ Parziale bear"
        else:
            label = "➖ Nessuna cascata"
        blended[asset] = {"ema_alignment": avg, "structure_label": label}
    return blended


def _blend_asset_strength_persistence(a_h: dict, a_d: dict, a_w: dict,
                                       w_h: float, w_d: float, w_w: float) -> dict[str, dict]:
    """Blend strength_persistence tra H4, Daily e Weekly."""
    p_h = a_h.get("strength_persistence", {})
    p_d = a_d.get("strength_persistence", {})
    p_w = a_w.get("strength_persistence", {})
    blended = {}
    for asset in ASSETS:
        ph_ = p_h.get(asset, {"persistence": 0, "slope": 0})
        pd_ = p_d.get(asset, {"persistence": 0, "slope": 0})
        pw_ = p_w.get(asset, {"persistence": 0, "slope": 0})
        p = ph_["persistence"] * w_h + pd_["persistence"] * w_d + pw_["persistence"] * w_w
        sl = ph_["slope"] * w_h + pd_["slope"] * w_d + pw_["slope"] * w_w
        p = round(p, 3)
        sl = round(sl, 4)
        abs_p = abs(p)
        direction = "BULL" if p >= 0 else "BEAR"
        if abs_p >= 0.7:
            label = f"🔒 PERSISTENTE {direction}"
        elif abs_p >= 0.4:
            label = f"{'↗' if direction == 'BULL' else '↘'} Trending {direction.lower()}"
        else:
            label = "🔀 Inconsistente"
        blended[asset] = {"persistence": p, "slope": sl, "consistency_label": label}
    return blended


def _concordance_label(score_h4: float, score_daily: float, score_weekly: float) -> str:
    """Concordanza tra H4, Daily e Weekly."""
    scores = [score_h4, score_daily, score_weekly]
    all_bull = all(s >= 55 for s in scores)
    all_bear = all(s <= 45 for s in scores)
    # Divergenza: almeno uno bull e almeno uno bear
    has_bull = any(s >= 55 for s in scores)
    has_bear = any(s <= 45 for s in scores)
    diverged = has_bull and has_bear

    if all_bull:
        return "✅ ALLINEATI BULL"
    elif all_bear:
        return "✅ ALLINEATI BEAR"
    elif diverged:
        return "⚠️ DIVERGENZA"
    else:
        return "➖ NEUTRO"
