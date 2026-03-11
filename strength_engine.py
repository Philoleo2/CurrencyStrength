"""
Currency Strength Indicator – Strength Engine
===============================================
Calcola il punteggio composito di forza per ogni valuta (0-100)
combinando: Price Action, Volume, COT.

Classifica ogni valuta come TREND-FOLLOWING o MEAN-REVERTING
usando Hurst Exponent, ADX ed Efficiency Ratio.

Identifica le valute che stanno guadagnando/perdendo forza rapidamente.
"""

import numpy as np
import pandas as pd

from config import (
    CURRENCIES, FOREX_PAIRS,
    # Pesi compositi
    WEIGHT_PRICE_ACTION, WEIGHT_VOLUME, WEIGHT_COT, WEIGHT_C9,
    # Pesi multi-timeframe
    COMPOSITE_WEIGHT_H1, COMPOSITE_WEIGHT_H4, COMPOSITE_WEIGHT_D1,
    D1_DIVERGENCE_THRESHOLD, D1_DIVERGENCE_MAX,
    D1_DECAY_MIN_WEIGHT, D1_DECAY_OPPOSITE_BONUS,
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
    # Gruppi correlazione, sessioni, COT freshness
    CORRELATION_GROUPS, EXCLUDED_PAIRS,
    SESSION_CURRENCY_AFFINITY, COT_STALE_DAYS_THRESHOLD,
    # Stabilità classifica
    SCORE_SMOOTHING_ALPHA,
    MIN_DIFFERENTIAL_THRESHOLD,
)


# ── Lookup tabelle gruppi correlazione (module-level, calcolato una volta) ───
_GROUP_LOOKUP: dict[frozenset, int] = {}
for _gid, _pairs in enumerate(CORRELATION_GROUPS):
    for _p in _pairs:
        _GROUP_LOOKUP[frozenset({_p[:3], _p[3:]})] = _gid
_EXCLUDED_SET = {frozenset({p[:3], p[3:]}) for p in EXCLUDED_PAIRS}


def _get_active_session_types(session_info: dict | None = None) -> set[str]:
    """Normalizza session_info in set di tipi sessione ('asia','london','newyork')."""
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
# INDICATORI TECNICI BASE
# ═══════════════════════════════════════════════════════════════════════════════

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calcola RSI (Relative Strength Index)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def roc(series: pd.Series, period: int = 1) -> pd.Series:
    """Rate of Change percentuale."""
    return series.pct_change(period, fill_method=None) * 100


def ema(series: pd.Series, period: int = 20) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """Average Directional Index (ADX)."""
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, min_periods=period).mean() / atr)

    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    dx = dx.replace([np.inf, -np.inf], 0)
    adx_val = dx.ewm(alpha=1/period, min_periods=period).mean()
    return adx_val


def hurst_exponent(series: pd.Series) -> float:
    """
    Calcola l'esponente di Hurst tramite analisi R/S (Rescaled Range).
      H > 0.5  →  serie persistente (trending)
      H = 0.5  →  random walk
      H < 0.5  →  anti-persistente (mean-reverting)
    """
    ts = series.dropna().values
    n = len(ts)
    if n < HURST_MIN_BARS:
        return 0.5  # non abbastanza dati, supponi random walk

    max_k = min(n // 2, 200)
    rs_list = []
    sizes = []

    for k in range(10, max_k, 5):
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

    log_rs = np.log(rs_list)
    log_sizes = np.log(sizes)
    slope, _ = np.polyfit(log_sizes, log_rs, 1)
    return float(np.clip(slope, 0, 1))


def efficiency_ratio(series: pd.Series, period: int = 20) -> pd.Series:
    """
    Kaufman Efficiency Ratio:
      ER = |Direzione| / Volatilità
    Valori alti → tendenza forte, valori bassi → choppiness.
    """
    direction = (series - series.shift(period)).abs()
    volatility = series.diff().abs().rolling(period).sum()
    er = direction / volatility
    return er.replace([np.inf, -np.inf], 0).fillna(0)


def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = ATR_PERIOD) -> pd.Series:
    """Average True Range."""
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period).mean()


# ═══════════════════════════════════════════════════════════════════════════════
# VOLATILITÀ (ATR) PER VALUTA
# ═══════════════════════════════════════════════════════════════════════════════

def compute_atr_context(all_pairs: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """
    Per ogni valuta calcola il contesto ATR:
      - atr_current: ATR corrente normalizzato
      - atr_percentile: percentile dell'ATR vs ultimi 50 periodi
      - volatility_regime: LOW / NORMAL / HIGH / EXTREME

    ATR basso + trend forte = trend pulito (ideale per trend-following)
    ATR alto + trend forte = breakout / momentum forte
    ATR alto + no trend = mercato caotico (cautela)
    """
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

        # ATR normalizzato come % del prezzo
        atr_pct = (current_atr / close_price) * 100 if close_price > 0 else 0

        # Percentile rolling
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
        if entries:
            avg_pct = float(np.mean([e["atr_pct"] for e in entries]))
            avg_perc = float(np.mean([e["percentile"] for e in entries]))
        else:
            avg_pct = 0
            avg_perc = 50

        if avg_perc >= 85:
            regime = "EXTREME"
        elif avg_perc >= 65:
            regime = "HIGH"
        elif avg_perc >= 35:
            regime = "NORMAL"
        else:
            regime = "LOW"

        results[ccy] = {
            "atr_pct": round(avg_pct, 4),
            "atr_percentile": round(avg_perc, 1),
            "volatility_regime": regime,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# TREND STRUCTURE  (cascata EMA per valuta)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_trend_structure(
    all_pairs: dict[str, pd.DataFrame],
) -> dict[str, dict]:
    """
    Per ogni valuta, valuta l'allineamento della cascata EMA
    su tutte le coppie che la contengono.

    Cascata completa bullish: EMA_FAST > EMA_MEDIUM > EMA_SLOW
    Cascata completa bearish: EMA_FAST < EMA_MEDIUM < EMA_SLOW
    Mista: le EMA si incrociano → struttura incerta

    Restituisce {valuta: {ema_alignment: float (-1..+1), structure_label: str}}
    """
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

        # Cascade: +1 = full bullish, -1 = full bearish, ±0.3 = partial
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

        # Base: bullish cascade = base stronger; Quote: inverted
        base, quote = info["base"], info["quote"]
        if base in ccy_alignments:
            ccy_alignments[base].append(alignment)
        if quote in ccy_alignments:
            ccy_alignments[quote].append(-alignment)

    results = {}
    for ccy in CURRENCIES:
        vals = ccy_alignments[ccy]
        avg = float(np.mean(vals)) if vals else 0.0

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

        results[ccy] = {
            "ema_alignment": round(avg, 3),
            "structure_label": label,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# VELOCITY SCORE  (rapidità del movimento)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_velocity_scores(
    all_pairs: dict[str, pd.DataFrame],
    composite: dict[str, dict],
    lookback_bars: int = 20,
) -> dict[str, dict]:
    """
    Misura *quanto rapidamente e in modo direzionale* ogni valuta si sta
    muovendo.  Usa l'Efficiency Ratio sulla forza cumulativa:

        ER = |cambiamento direzionale| / path_length

    ER alto → movimento pulito e direzionale (trending)
    ER basso → movimento caotico e laterale

    Combina ER con la magnitudine del movimento (normalizzata per
    deviazione standard) per evitare di premiare movimenti piccoli
    ma "efficienti" o penalizzare movimenti graduali ma costanti.

    Chiavi restituite per valuta::

        {
          "bars_to_move":   int,   # stima barre per il cambiamento
          "velocity_norm":  float, # 0-100 (100 = movimento più rapido possibile)
          "velocity_label": str,   # etichetta leggibile
        }
    """
    from data_fetcher import compute_currency_returns

    rets = compute_currency_returns(all_pairs, window=1)
    if rets.empty or len(rets) < lookback_bars + 5:
        return {c: {"bars_to_move": 0, "velocity_norm": 50,
                     "velocity_label": "N/A"} for c in CURRENCIES}

    # Forza cumulativa rolling per ogni valuta (in punti %)
    cum = (rets.rolling(lookback_bars).sum() * 100).dropna(how="all")
    if len(cum) < 2:
        return {c: {"bars_to_move": 0, "velocity_norm": 50,
                     "velocity_label": "N/A"} for c in CURRENCIES}

    results = {}
    for ccy in CURRENCIES:
        if ccy not in cum.columns:
            results[ccy] = {"bars_to_move": 0, "velocity_norm": 50,
                            "velocity_label": "N/A"}
            continue

        col = cum[ccy].dropna()
        if len(col) < lookback_bars:
            results[ccy] = {"bars_to_move": 0, "velocity_norm": 50,
                            "velocity_label": "N/A"}
            continue

        recent = col.iloc[-lookback_bars:]

        # --- Efficiency Ratio sulla forza cumulativa ---
        # ER = |cambiamento direzionale| / percorso totale
        directional_change = abs(float(recent.iloc[-1] - recent.iloc[0]))
        path_length = float(recent.diff().abs().sum())
        efficiency = directional_change / path_length if path_length > 1e-10 else 0

        # --- Magnitudine normalizzata (evita di premiare micro-movimenti) ---
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

        results[ccy] = {
            "bars_to_move": bars_to_move,
            "velocity_norm": velocity_norm,
            "velocity_label": label,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# CORRELAZIONE TRA VALUTE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_currency_correlation(
    all_pairs: dict[str, pd.DataFrame],
    window: int = 30,
) -> pd.DataFrame:
    """
    Calcola la matrice di correlazione rolling tra le valute.
    Utile per evitare trade ridondanti (es. long AUD + long NZD).
    Restituisce DataFrame 8x8 con correlazioni.
    """
    from data_fetcher import compute_currency_returns

    rets = compute_currency_returns(all_pairs, window=1)
    if rets.empty or len(rets) < window:
        return pd.DataFrame(
            np.eye(len(CURRENCIES)),
            index=CURRENCIES, columns=CURRENCIES,
        )

    # Usa gli ultimi `window` periodi
    recent = rets.iloc[-window:]
    corr = recent.corr()
    return corr.round(3)


# ═══════════════════════════════════════════════════════════════════════════════
# TRADE SETUP SCORE PER COPPIA
# ═══════════════════════════════════════════════════════════════════════════════

def compute_trade_setups(
    composite: dict[str, dict],
    momentum: dict[str, dict],
    classification: dict[str, dict],
    atr_context: dict[str, dict],
    cot_scores: dict[str, dict],
    velocity_scores: dict[str, dict] | None = None,
    trend_structure: dict[str, dict] | None = None,
    strength_persistence: dict[str, dict] | None = None,
    session_info: dict | None = None,
    candle9: dict[str, dict] | None = None,
) -> list[dict]:
    """
    Per ogni coppia possibile, calcola un punteggio di qualità del setup
    combinando: differenziale di forza, concordanza momentum, regime,
    volatilità, COT e velocità del movimento.

    Restituisce lista ordinata per qualità decrescente.
    Ogni entry: {pair, base, quote, direction, differential, quality_score,
                 grade, reasons}
    """
    if velocity_scores is None:
        velocity_scores = {}
    if trend_structure is None:
        trend_structure = {}
    if strength_persistence is None:
        strength_persistence = {}
    if candle9 is None:
        candle9 = {}
    session_types = _get_active_session_types(session_info)
    setups = []

    for base in CURRENCIES:
        for quote in CURRENCIES:
            if base == quote:
                continue

            s_base = composite[base]["composite"]
            s_quote = composite[quote]["composite"]
            diff = s_base - s_quote

            if abs(diff) < MIN_DIFFERENTIAL_THRESHOLD:  # differenziale troppo piccolo, skip
                continue

            direction = "LONG" if diff > 0 else "SHORT"
            strong_ccy = base if diff > 0 else quote
            weak_ccy = quote if diff > 0 else base

            quality = 0
            reasons = []

            # --- 1. Differenziale (0-30 punti) ---
            diff_abs = abs(diff)
            diff_pts = min(diff_abs * 1.0, 30)
            quality += diff_pts
            if diff_abs >= 20:
                reasons.append(f"Differenziale forte ({diff_abs:.0f} pts)")
            elif diff_abs >= 12:
                reasons.append(f"Differenziale buono ({diff_abs:.0f} pts)")

            # --- 2. Momentum concordante (0-20 punti) ---
            mom_strong = momentum.get(strong_ccy, {}).get("delta", 0)
            mom_weak = momentum.get(weak_ccy, {}).get("delta", 0)
            if mom_strong > 0 and mom_weak < 0:
                quality += 20
                reasons.append("Momentum allineato (forte ↑ debole ↓)")
            elif mom_strong > 0 or mom_weak < 0:
                quality += 6
                reasons.append("Momentum parzialmente allineato")

            # --- 2b. Sinergia differenziale + momentum (0-5 punti bonus) ---
            if diff_abs >= 15 and mom_strong > 0 and mom_weak < 0:
                quality += 5
                reasons.append("Sinergia diff+momentum")

            # --- 3. Regime trend-following sulla valuta forte (0-15 punti) ---
            cls_strong = classification.get(strong_ccy, {})
            if cls_strong.get("classification") == "TREND_FOLLOWING":
                quality += 15
                reasons.append(f"{strong_ccy} in regime trending")
            elif cls_strong.get("classification") == "MIXED":
                quality += 5

            # --- 4. Volatilità favorevole (0-15 punti) ---
            atr_strong = atr_context.get(strong_ccy, {})
            atr_weak = atr_context.get(weak_ccy, {})
            vol_strong = atr_strong.get("volatility_regime", "NORMAL")
            vol_weak = atr_weak.get("volatility_regime", "NORMAL")

            if vol_strong in ("NORMAL", "LOW"):
                quality += 10  # trend pulito senza eccessiva volatilità
                reasons.append(f"{strong_ccy} volatilità {vol_strong.lower()}")
            elif vol_strong == "HIGH":
                quality += 5   # potrebbe essere breakout
            # Penalità per volatilità estrema
            if vol_strong == "EXTREME" or vol_weak == "EXTREME":
                quality -= 5
                reasons.append("⚠️ Volatilità estrema")

            # --- 5. COT concordante (0-10 punti, dimezzato se stale) ---
            cot_strong_info = cot_scores.get(strong_ccy, {})
            cot_weak_info = cot_scores.get(weak_ccy, {})
            cot_strong_bias = cot_strong_info.get("bias", "NEUTRAL")
            cot_weak_bias = cot_weak_info.get("bias", "NEUTRAL")
            # Freshness: se dati COT > COT_STALE_DAYS_THRESHOLD, dimezza il bonus
            cot_fresh_s = cot_strong_info.get("freshness_days", 0)
            cot_fresh_w = cot_weak_info.get("freshness_days", 0)
            cot_multiplier = 0.5 if max(cot_fresh_s, cot_fresh_w) > COT_STALE_DAYS_THRESHOLD else 1.0
            if cot_multiplier < 1.0:
                reasons.append(f"⚠️ COT non aggiornato ({max(cot_fresh_s, cot_fresh_w)}gg)")
            cot_pts = 0
            if cot_strong_bias == "BULLISH":
                cot_pts += 5
                reasons.append(f"COT {strong_ccy} bullish")
            if cot_weak_bias == "BEARISH":
                cot_pts += 5
                reasons.append(f"COT {weak_ccy} bearish")
            quality += cot_pts * cot_multiplier

            # Penalità COT crowded contro il trade
            cot_strong_ext = cot_strong_info.get("extreme")
            cot_weak_ext = cot_weak_info.get("extreme")
            if cot_strong_ext == "CROWDED_LONG":
                quality -= 10
                reasons.append("⚠️ COT crowded long sulla valuta forte")
            if cot_weak_ext == "CROWDED_SHORT":
                quality -= 10
                reasons.append("⚠️ COT crowded short sulla valuta debole")

            # --- 6. Concordanza H1/H4 se disponibile (0-10 punti) ---
            # Anti-esaurimento: se il composito della valuta forte è ≥ 80
            # (zona estrema), la concordanza conta meno — potrebbe essere
            # un segnale di esaurimento, non di continuazione.
            concordance = composite[strong_ccy].get("concordance", "")
            strong_composite = composite[strong_ccy].get("composite", 50)
            if "ALLINEATI" in concordance:
                if strong_composite >= 80:
                    quality += 4  # ridotto: zona esaurimento
                    reasons.append("H1/H4 allineati (⚠️ zona estrema)")
                else:
                    quality += 10
                    reasons.append("H1/H4 allineati")
            elif "DIVERGENZA" in concordance:
                quality -= 5
                reasons.append("⚠️ Divergenza H1/H4")

            # --- 7. Velocity — rapidità del movimento (0-10 punti) ---
            vel_strong = velocity_scores.get(strong_ccy, {})
            vel_weak = velocity_scores.get(weak_ccy, {})
            vel_s = vel_strong.get("velocity_norm", 50)
            vel_w = vel_weak.get("velocity_norm", 50)

            # Bonus: la valuta forte si muove rapidamente
            if vel_s >= 65:
                quality += 10
                reasons.append(f"{strong_ccy} velocità alta ({vel_s:.0f})")
            elif vel_s >= 40:
                quality += 5

            # Penalità lieve: movimento molto stagnante
            if vel_s < 15:
                quality -= 3
                reasons.append(f"⚠️ {strong_ccy} movimento stagnante")

            # --- 8. Trend structure — cascata EMA (0-8 punti, -5 penalità) ---
            ts_strong = trend_structure.get(strong_ccy, {})
            ts_weak = trend_structure.get(weak_ccy, {})
            align_s = ts_strong.get("ema_alignment", 0)
            align_w = ts_weak.get("ema_alignment", 0)

            if align_s >= 0.4 and align_w <= -0.4:
                quality += 8
                reasons.append("Struttura EMA allineata forte↑ debole↓")
            elif align_s >= 0.2 or align_w <= -0.2:
                quality += 4
            # Penalità se la struttura contraddice la direzione
            if align_s <= -0.3:
                quality -= 5
                reasons.append(f"⚠️ {strong_ccy} cascata EMA contro-tendenza")

            # --- 9. Momentum acceleration (0-5 bonus, -3 penalità) ---
            mom_accel_s = momentum.get(strong_ccy, {}).get("acceleration", 0)
            mom_accel_w = momentum.get(weak_ccy, {}).get("acceleration", 0)

            if mom_accel_s > 0 and mom_accel_w < 0:
                quality += 5
                reasons.append("Momentum in accelerazione")
            elif mom_accel_s > 0 or mom_accel_w < 0:
                quality += 2
            # Penalità: forte decelera E ha momentum piatto/negativo
            if mom_accel_s < 0 and mom_strong <= 0:
                quality -= 3
                reasons.append(f"⚠️ {strong_ccy} momentum in decelerazione")

            # --- 10. Strength persistence (0-8 punti, -3 penalità) ---
            pers_s = strength_persistence.get(strong_ccy, {})
            pers_w = strength_persistence.get(weak_ccy, {})
            p_s = pers_s.get("persistence", 0)
            p_w = pers_w.get("persistence", 0)

            if p_s >= 0.5 and p_w <= -0.5:
                quality += 8
                reasons.append("Forza persistente su entrambe")
            elif p_s >= 0.3 or p_w <= -0.3:
                quality += 4
            # Penalità: nessuna persistenza
            if abs(p_s) < 0.2 and abs(p_w) < 0.2:
                quality -= 3
                reasons.append("⚠️ Forza non persistente")

            # --- 11. Session awareness (0-3 bonus, -2 penalità) ---
            if session_types:
                strong_in_session = any(
                    strong_ccy in SESSION_CURRENCY_AFFINITY.get(s, set())
                    for s in session_types
                )
                weak_in_session = any(
                    weak_ccy in SESSION_CURRENCY_AFFINITY.get(s, set())
                    for s in session_types
                )
                if strong_in_session and weak_in_session:
                    quality += 3
                    reasons.append("Sessione favorevole per entrambe")
                elif strong_in_session or weak_in_session:
                    quality += 1
                else:
                    quality -= 2
                    reasons.append("⚠️ Sessione non ottimale")

            # --- 12. Candle-9 concordante (0-25 punti, -12 penalità) ---
            if candle9:
                c9_strong = candle9.get(strong_ccy, {})
                c9_weak = candle9.get(weak_ccy, {})
                c9_r_s = c9_strong.get("candle9_ratio", 0)
                c9_r_w = c9_weak.get("candle9_ratio", 0)
                # Forte bullish E debole bearish → pieno punteggio
                if c9_r_s > 0.05 and c9_r_w < -0.05:
                    c9_pts = 25
                    # Bonus magnitudine proporzionale
                    mag = min(abs(c9_r_s) + abs(c9_r_w), 1.0)
                    c9_pts = round(c9_pts * max(mag, 0.4))
                    quality += c9_pts
                    reasons.append(f"C9 allineato ({c9_r_s:+.2f}% / {c9_r_w:+.2f}%)")
                elif c9_r_s > 0.05 or c9_r_w < -0.05:
                    quality += 10
                    reasons.append("C9 parzialmente allineato")
                # Penalità: C9 in contro-direzione
                if c9_r_s < -0.05 and c9_r_w > 0.05:
                    quality -= 12
                    reasons.append("⚠️ C9 contro-direzione")

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

            # Cerca il pair name reale
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

    # Ordina per qualità
    setups.sort(key=lambda x: x["quality_score"], reverse=True)

    # ── Deduplicazione: per ogni coppia, tieni solo la versione migliore ──
    # Es. se c'è NZD/CHF (LONG, score 70) e CHF/NZD (SHORT, score 70),
    # sono lo stesso trade → tieni quello con quality_score più alto.
    seen_pairs: set[tuple[str, str]] = set()
    unique_setups: list[dict] = []
    for s in setups:
        b, q = s["base"], s["quote"]
        canonical = tuple(sorted([b, q]))   # (CHF, NZD) in entrambi i casi
        if canonical not in seen_pairs:
            seen_pairs.add(canonical)
            unique_setups.append(s)

    # ── Escludi coppie mai tradate (es. EURGBP) ─────────────────────────
    unique_setups = [
        s for s in unique_setups
        if frozenset({s["base"], s["quote"]}) not in _EXCLUDED_SET
    ]

    # ── Filtro gruppi correlazione ───────────────────────────────────────
    # Se un segnale A/A+ copre un gruppo, le altre coppie dello stesso
    # gruppo vengono rimosse → un solo segnale per tema direzionale.
    covered_groups: dict[int, int] = {}   # group_id → indice rappresentante
    for i, s in enumerate(unique_setups):
        if s["grade"] not in ("A+", "A"):
            continue
        pair_key = frozenset({s["base"], s["quote"]})
        group_id = _GROUP_LOOKUP.get(pair_key)
        if group_id is not None and group_id not in covered_groups:
            covered_groups[group_id] = i

    if covered_groups:
        filtered: list[dict] = []
        for i, s in enumerate(unique_setups):
            pair_key = frozenset({s["base"], s["quote"]})
            group_id = _GROUP_LOOKUP.get(pair_key)
            if group_id is not None and group_id in covered_groups:
                if i != covered_groups[group_id]:
                    continue  # skip: coperto da un A/A+ migliore
            filtered.append(s)
        unique_setups = filtered

    return unique_setups


# ═══════════════════════════════════════════════════════════════════════════════
# SCORE PRICE ACTION PER VALUTA
# ═══════════════════════════════════════════════════════════════════════════════

def _pair_strength_for_currency(pair_df: pd.DataFrame, currency: str,
                                 is_base: bool) -> float:
    """
    Calcola un punteggio 0-100 per una singola coppia rispetto alla valuta data.
    Combina: RSI, ROC multi-periodo, posizione relativa a EMA.
    """
    close = pair_df["Close"]
    if len(close) < EMA_SLOW:
        # non abbastanza dati per tutte le EMA, usa quello che c'è
        pass

    sign = 1.0 if is_base else -1.0  # se quote, il segno è inverso

    # --- RSI normalizzato (0-100) ---
    rsi_val = rsi(close, RSI_PERIOD)
    latest_rsi = rsi_val.iloc[-1] if not rsi_val.empty else 50
    if not is_base:
        latest_rsi = 100 - latest_rsi  # inverti per valuta quotata

    # --- ROC multi-periodo (normalizzato a score 0-100) ---
    roc_f = roc(close, ROC_FAST).iloc[-1] if len(close) > ROC_FAST else 0
    roc_m = roc(close, ROC_MEDIUM).iloc[-1] if len(close) > ROC_MEDIUM else 0
    roc_s = roc(close, ROC_SLOW).iloc[-1] if len(close) > ROC_SLOW else 0

    # Media ponderata dei ROC, poi normalizza con sigmoid-like
    avg_roc = (roc_f * 0.5 + roc_m * 0.3 + roc_s * 0.2) * sign
    roc_score = 50 + np.clip(avg_roc * 10, -50, 50)  # scala a 0-100

    # --- EMA positioning (0-100) ---
    ema_scores = []
    for p in [EMA_FAST, EMA_MEDIUM, EMA_SLOW]:
        if len(close) > p:
            ema_val = ema(close, p).iloc[-1]
            pct_above = ((close.iloc[-1] / ema_val) - 1) * 100
            if not is_base:
                pct_above = -pct_above
            ema_scores.append(50 + np.clip(pct_above * 15, -50, 50))
    ema_score = np.mean(ema_scores) if ema_scores else 50

    # --- Composito ---
    final = latest_rsi * 0.35 + roc_score * 0.40 + ema_score * 0.25
    return float(np.clip(final, 0, 100))


def compute_price_action_scores(all_pairs: dict[str, pd.DataFrame]
                                 ) -> dict[str, float]:
    """
    Per ogni valuta, media dei punteggi price-action su tutte le coppie
    che la contengono. Restituisce {valuta: score 0-100}.
    """
    ccy_scores: dict[str, list[float]] = {c: [] for c in CURRENCIES}

    for pair_name, pair_df in all_pairs.items():
        if pair_df.empty or "Close" not in pair_df.columns:
            continue
        info = FOREX_PAIRS[pair_name]
        base = info["base"]
        quote = info["quote"]

        if base in ccy_scores:
            s = _pair_strength_for_currency(pair_df, base, is_base=True)
            ccy_scores[base].append(s)
        if quote in ccy_scores:
            s = _pair_strength_for_currency(pair_df, quote, is_base=False)
            ccy_scores[quote].append(s)

    return {ccy: round(float(np.mean(vals)), 2) if vals else 50.0
            for ccy, vals in ccy_scores.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# SCORE VOLUME PER VALUTA
# ═══════════════════════════════════════════════════════════════════════════════

def compute_volume_scores(all_pairs: dict[str, pd.DataFrame],
                          futures_data: dict[str, pd.DataFrame],
                          price_scores: dict[str, float]
                          ) -> dict[str, float]:
    """
    Il volume amplifica o attenua il segnale di prezzo.
      - Volume alto + prezzo forte  →  conferma, score si avvicina a estremo
      - Volume basso + prezzo forte →  sospetto, score si attenua
      - Volume alto + prezzo debole →  conferma debolezza

    Usa i volumi dei futures CME come proxy.
    Restituisce {valuta: score 0-100}.
    """
    volume_ratios: dict[str, float] = {}

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

        # vr > 1 = volumi sopra la media → amplifica il segnale
        # vr < 1 = volumi sotto la media → attenua
        # Moltiplichiamo la deviazione dal neutro (50) per il ratio volume
        deviation = pa - 50
        amplified = deviation * np.clip(vr, 0.5, 2.0)
        score = 50 + amplified
        scores[ccy] = round(float(np.clip(score, 0, 100)), 2)

    return scores


# ═══════════════════════════════════════════════════════════════════════════════
# SCORE COMPOSITO
# ═══════════════════════════════════════════════════════════════════════════════

def compute_composite_scores(
    price_scores: dict[str, float],
    volume_scores: dict[str, float],
    cot_scores: dict[str, dict],
    c9_scores: dict[str, float] | None = None,
) -> dict[str, dict]:
    """
    Calcola il punteggio composito finale per ogni valuta.
    Restituisce dict con:
      {valuta: {
          price_score, volume_score, cot_score, c9_score,
          composite, label, alert
      }}
    """
    if c9_scores is None:
        c9_scores = {}
    results = {}
    for ccy in CURRENCIES:
        pa = price_scores.get(ccy, 50)
        vol = volume_scores.get(ccy, 50)
        cot = cot_scores.get(ccy, {}).get("score", 50)
        c9 = c9_scores.get(ccy, 50)

        composite = (
            pa  * WEIGHT_PRICE_ACTION +
            vol * WEIGHT_VOLUME +
            cot * WEIGHT_COT +
            c9  * WEIGHT_C9
        )
        composite = round(float(np.clip(composite, 0, 100)), 1)

        # Label
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

        # Alert
        alert = None
        cot_info = cot_scores.get(ccy, {})
        if composite >= THRESHOLD_EXTREME_BULL:
            alert = "⚠️ ATTENZIONE: forza estrema, possibile esaurimento"
        elif composite <= THRESHOLD_EXTREME_BEAR:
            alert = "⚠️ ATTENZIONE: debolezza estrema, possibile rimbalzo"
        if cot_info.get("extreme") == "CROWDED_LONG":
            alert = (alert or "") + " | COT: posizionamento speculativo estremo LONG"
        elif cot_info.get("extreme") == "CROWDED_SHORT":
            alert = (alert or "") + " | COT: posizionamento speculativo estremo SHORT"

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
# SMOOTHING COMPOSITO  –  EMA-like per stabilità ranking
# ═══════════════════════════════════════════════════════════════════════════════

def smooth_composite_scores(
    current: dict[str, dict],
    previous: dict[str, dict] | None,
    alpha: float = SCORE_SMOOTHING_ALPHA,
) -> dict[str, dict]:
    """
    Applica smoothing esponenziale ai punteggi compositi per ridurre
    le oscillazioni orarie.

    Formula:  smoothed = α * current + (1 − α) * previous

    Parametri
    ---------
    current : dict attuale da compute_composite_scores / blend
    previous : dict dal refresh precedente (None → nessuno smoothing)
    alpha : peso del dato corrente (default SCORE_SMOOTHING_ALPHA)

    Restituisce
    -----------
    Nuovo dict con gli stessi campi di `current` ma score smussati.
    I sotto-score (price/volume/cot) e il composite vengono tutti smussati.
    """
    if previous is None or alpha >= 1.0:
        return current

    smoothed = {}
    for ccy in CURRENCIES:
        cur = current.get(ccy, {})
        prev = previous.get(ccy, {})

        if not prev or prev.get("composite") is None:
            smoothed[ccy] = cur
            continue

        # Smoothing sui sotto-score e sul composito
        sm = cur.copy()
        for key in ("price_score", "volume_score", "cot_score", "c9_score", "composite"):
            c_val = cur.get(key, 50)
            p_val = prev.get(key, 50)
            sm[key] = round(alpha * c_val + (1 - alpha) * p_val, 1)

        # Anche h1_score, h4_score, d1_score se presenti (blend composito)
        for key in ("h1_score", "h4_score", "d1_score"):
            if key in cur and key in prev:
                sm[key] = round(alpha * cur[key] + (1 - alpha) * prev[key], 1)

        # Ricalcola label basata sul composito smussato
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

        smoothed[ccy] = sm

    return smoothed


# ═══════════════════════════════════════════════════════════════════════════════
# MOMENTUM  (chi sta guadagnando/perdendo forza rapidamente)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_momentum_rankings(
    all_pairs: dict[str, pd.DataFrame],
    lookback: int = MOMENTUM_LOOKBACK,
) -> dict[str, dict]:
    """
    Calcola il cambiamento del punteggio price-action nelle ultime N barre.
    Restituisce {valuta: {delta, acceleration, rank_label}}.
    """
    from data_fetcher import compute_currency_returns

    rets = compute_currency_returns(all_pairs, window=1)
    if rets.empty or len(rets) < lookback + 5:
        return {c: {"delta": 0, "acceleration": 0, "rank_label": "N/A"}
                for c in CURRENCIES}

    # Calcola lo score rolling
    results = {}
    for ccy in CURRENCIES:
        if ccy not in rets.columns:
            results[ccy] = {"delta": 0, "acceleration": 0, "rank_label": "N/A"}
            continue

        # Usa rendimento cumulativo come proxy del cambiamento di forza
        cum_recent = rets[ccy].iloc[-lookback:].sum() * 100
        cum_prev = rets[ccy].iloc[-(lookback*2):-lookback].sum() * 100 \
            if len(rets) >= lookback * 2 else 0

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

        results[ccy] = {
            "delta": delta,
            "acceleration": acceleration,
            "rank_label": rank_label,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFICAZIONE: TREND-FOLLOWING vs MEAN-REVERTING
# ═══════════════════════════════════════════════════════════════════════════════

def classify_trend_vs_reversion(
    all_pairs: dict[str, pd.DataFrame],
    futures_data: dict[str, pd.DataFrame],
) -> dict[str, dict]:
    """
    Per ogni valuta determina se il regime corrente favorisce
    strategie trend-following o mean-reverting.

    Usa tre indicatori:
      1. ADX medio su tutte le coppie della valuta
      2. Hurst Exponent dei rendimenti
      3. Efficiency Ratio di Kaufman

    Restituisce {valuta: {
        adx_avg, hurst, eff_ratio,
        trend_score (0=mean-revert, 100=trend),
        classification: "TREND_FOLLOWING" | "MEAN_REVERTING" | "MIXED"
    }}
    """
    from data_fetcher import compute_currency_returns

    results = {}
    rets = compute_currency_returns(all_pairs, window=1)

    for ccy in CURRENCIES:
        # --- ADX medio ---
        adx_values = []
        for pair_name, pair_df in all_pairs.items():
            info = FOREX_PAIRS[pair_name]
            if info["base"] == ccy or info["quote"] == ccy:
                if len(pair_df) > ADX_PERIOD * 3 and all(
                    c in pair_df.columns for c in ["High", "Low", "Close"]
                ):
                    adx_series = adx(pair_df["High"], pair_df["Low"],
                                     pair_df["Close"], ADX_PERIOD)
                    last_adx = adx_series.iloc[-1]
                    if not np.isnan(last_adx):
                        adx_values.append(last_adx)

        avg_adx = float(np.mean(adx_values)) if adx_values else 20

        # --- Hurst Exponent ---
        h = 0.5
        if ccy in rets.columns:
            ret_series = rets[ccy].dropna()
            if len(ret_series) >= HURST_MIN_BARS:
                h = hurst_exponent(ret_series)

        # --- Efficiency Ratio ---
        er = 0.3  # default
        fut_df = futures_data.get(ccy)
        if fut_df is not None and not fut_df.empty and "Close" in fut_df.columns:
            er_series = efficiency_ratio(fut_df["Close"], 20)
            er = float(er_series.iloc[-1]) if not er_series.empty else 0.3
        elif ccy in rets.columns and len(rets[ccy].dropna()) > 20:
            # Fallback: usa rendimenti cumulativi come proxy
            cum = (1 + rets[ccy].dropna()).cumprod()
            er_series = efficiency_ratio(cum, 20)
            er = float(er_series.iloc[-1]) if not er_series.empty else 0.3

        # --- Score trend 0-100 ---
        # ADX component: 0-100
        adx_norm = np.clip((avg_adx - ADX_RANGE_THRESH) /
                           (ADX_TREND_THRESH - ADX_RANGE_THRESH), 0, 1) * 100

        # Hurst component: 0-100
        hurst_norm = np.clip((h - HURST_REVERT_THRESH) /
                             (HURST_TREND_THRESH - HURST_REVERT_THRESH), 0, 1) * 100

        # ER component: 0-100
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

        results[ccy] = {
            "adx_avg": round(avg_adx, 1),
            "hurst": round(h, 3),
            "eff_ratio": round(er, 3),
            "trend_score": trend_score,
            "classification": classification,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITY: STORIA DEGLI SCORE (per grafici temporali)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rolling_strength(all_pairs: dict[str, pd.DataFrame],
                              window: int = 20,
                              futures_data: dict[str, pd.DataFrame] | None = None,
                              cot_scores: dict[str, dict] | None = None,
                              ) -> pd.DataFrame:
    """
    Calcola un vero score composito rolling (0-100) per ogni valuta a ogni barra,
    replicando la stessa logica usata per lo snapshot singolo:
      • RSI (35%)  →  rolling RSI sui rendimenti valutari
      • ROC multi-periodo (40%)  →  rolling ROC fast/medium/slow
      • EMA positioning (25%)  →  posizione relativa a EMA
    Poi integra Volume e COT come nel composito finale:
      • Price Action 40% + Volume 30% + COT 30%

    Restituisce DataFrame con indice datetime e colonne = valute, scala 0-100.
    """
    from data_fetcher import compute_currency_returns, compute_volume_ratio

    # ── 1. Rendimenti per valuta (media su tutte le coppie) ─────────────
    rets = compute_currency_returns(all_pairs, window=1)
    if rets.empty or len(rets) < max(RSI_PERIOD, ROC_SLOW, EMA_SLOW) + 5:
        # fallback: non abbastanza dati, restituisce vuoto
        return pd.DataFrame()

    # ── 2. Forza cumulativa (usata come "prezzo sintetico" per la valuta)
    cum_price = (1 + rets).cumprod()

    # ── 3. Calcola RSI rolling sui ritorni di ogni valuta ───────────────
    rsi_df = pd.DataFrame(index=rets.index, columns=CURRENCIES, dtype=float)
    for ccy in CURRENCIES:
        if ccy in cum_price.columns:
            rsi_df[ccy] = rsi(cum_price[ccy], RSI_PERIOD)

    # ── 4. ROC multi-periodo rolling ────────────────────────────────────
    roc_score_df = pd.DataFrame(index=rets.index, columns=CURRENCIES, dtype=float)
    for ccy in CURRENCIES:
        if ccy not in cum_price.columns:
            continue
        cp = cum_price[ccy]
        roc_f = roc(cp, ROC_FAST)
        roc_m = roc(cp, ROC_MEDIUM)
        roc_s = roc(cp, ROC_SLOW)
        avg_roc = roc_f * 0.5 + roc_m * 0.3 + roc_s * 0.2
        roc_score_df[ccy] = 50 + (avg_roc * 10).clip(-50, 50)

    # ── 5. EMA positioning rolling ──────────────────────────────────────
    ema_score_df = pd.DataFrame(index=rets.index, columns=CURRENCIES, dtype=float)
    for ccy in CURRENCIES:
        if ccy not in cum_price.columns:
            continue
        cp = cum_price[ccy]
        ema_components = []
        for p in [EMA_FAST, EMA_MEDIUM, EMA_SLOW]:
            if len(cp) > p:
                e = ema(cp, p)
                pct_above = ((cp / e) - 1) * 100
                ema_components.append((50 + (pct_above * 15).clip(-50, 50)))
        if ema_components:
            ema_score_df[ccy] = pd.concat(ema_components, axis=1).mean(axis=1)
        else:
            ema_score_df[ccy] = 50.0

    # ── 6. Price Action score rolling (composito dei 3 indicatori) ──────
    pa_score_df = (
        rsi_df * 0.35 +
        roc_score_df * 0.40 +
        ema_score_df * 0.25
    ).clip(0, 100)

    # ── 7. Volume amplification (se disponibili i futures) ──────────────
    vol_score_df = pa_score_df.copy()
    if futures_data:
        vol_ratios = compute_volume_ratio(futures_data, window=20)
        for ccy in CURRENCIES:
            if ccy in vol_ratios and ccy in vol_score_df.columns:
                vr = vol_ratios[ccy].reindex(vol_score_df.index, method="ffill").fillna(1.0)
                deviation = pa_score_df[ccy] - 50
                amplified = deviation * vr.clip(0.5, 2.0)
                vol_score_df[ccy] = (50 + amplified).clip(0, 100)

    # ── 8. COT score (costante settimanale, espanso su tutte le barre) ──
    cot_val = {}
    if cot_scores:
        for ccy in CURRENCIES:
            cot_val[ccy] = cot_scores.get(ccy, {}).get("score", 50)
    else:
        cot_val = {c: 50.0 for c in CURRENCIES}

    cot_series = pd.DataFrame(
        {ccy: cot_val[ccy] for ccy in CURRENCIES},
        index=pa_score_df.index,
    )

    # ── 9. Composito finale: PA + Volume + COT + C9 ──────────────────────
    # C9 rolling: per ogni barra, calcola magnitude score dalle variazioni
    c9_score_df = pd.DataFrame(50.0, index=pa_score_df.index, columns=CURRENCIES)
    lookback_c9 = 9
    for ccy in CURRENCIES:
        if ccy not in cum_price.columns:
            continue
        cp = cum_price[ccy]
        if len(cp) < lookback_c9 + 2:
            continue
        pct_c9 = cp.pct_change(lookback_c9, fill_method=None) * 100
        magnitude = 50 + (pct_c9 * 25).clip(-50, 50)
        # Slope rolling
        slope_series = cp.rolling(lookback_c9 + 1).apply(
            lambda w: np.polyfit(np.arange(len(w)), w.values, 1)[0] / np.mean(w) * 100
            if len(w) >= 2 and np.mean(w) > 0 else 0,
            raw=False,
        )
        velocity_s = 50 + (slope_series * 200).clip(-50, 50)
        c9_score_df[ccy] = (magnitude * 0.60 + velocity_s * 0.40).clip(0, 100)

    composite_ts = (
        pa_score_df   * WEIGHT_PRICE_ACTION +
        vol_score_df  * WEIGHT_VOLUME +
        cot_series    * WEIGHT_COT +
        c9_score_df   * WEIGHT_C9
    ).clip(0, 100)

    return composite_ts.dropna(how="all")


# ═══════════════════════════════════════════════════════════════════════════════
# STRENGTH PERSISTENCE  (persistenza direzionale)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_strength_persistence(
    rolling_strength: pd.DataFrame,
    window: int = 10,
) -> dict[str, dict]:
    """
    Misura la persistenza direzionale della forza di ogni valuta.
    Analizza le ultime `window` barre di rolling strength:
      - Quante sono sopra 55 (bull) o sotto 45 (bear)?
      - Qual è la pendenza del trend recente?

    Restituisce {valuta: {persistence: float -1..+1, slope: float,
                          consistency_label: str}}
    """
    results = {}
    for ccy in CURRENCIES:
        if rolling_strength.empty or ccy not in rolling_strength.columns:
            results[ccy] = {"persistence": 0.0, "slope": 0.0,
                            "consistency_label": "N/A"}
            continue

        col = rolling_strength[ccy].dropna()
        if len(col) < window // 2:
            results[ccy] = {"persistence": 0.0, "slope": 0.0,
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

        results[ccy] = {
            "persistence": round(persistence, 3),
            "slope": round(slope, 4),
            "consistency_label": label,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# CANDLE-9 PRICE ACTION (close attuale vs close 9 candele fa)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_candle9_signal(
    all_pairs: dict[str, pd.DataFrame],
    lookback: int = 9,
) -> dict[str, dict]:
    """
    Per ogni valuta, confronta il close della candela attuale con il close
    di N candele precedenti (default 9).

    Se close attuale > close[−9]:
      - per la Base → segnale BULLISH (la coppia sale = base forte)
      - per la Quote → segnale BEARISH
    Viceversa se close attuale < close[−9].

    Aggrega su tutte le coppie che contengono la valuta e restituisce:
      {valuta: {
          "candle9_ratio":  float,   # media % variazione vs candela 9
          "candle9_signal": str,     # 🟢 BULLISH / 🔴 BEARISH / ➖ NEUTRO
          "candle9_pairs":  int,     # numero coppie analizzate
          "candle9_detail": list,    # dettaglio per coppia
      }}
    """
    ccy_signals: dict[str, list[float]] = {c: [] for c in CURRENCIES}
    ccy_details: dict[str, list[dict]] = {c: [] for c in CURRENCIES}

    for pair_name, pair_df in all_pairs.items():
        if pair_df.empty or "Close" not in pair_df.columns:
            continue
        close = pair_df["Close"]
        if len(close) < lookback + 1:
            continue

        info = FOREX_PAIRS[pair_name]
        base, quote = info["base"], info["quote"]

        current_close = float(close.iloc[-1])
        past_close = float(close.iloc[-(lookback + 1)])

        if past_close == 0:
            continue

        # Variazione % rispetto a N candele fa
        pct_change = ((current_close - past_close) / past_close) * 100

        detail = {
            "pair": pair_name,
            "current": round(current_close, 5),
            "past_9": round(past_close, 5),
            "pct": round(pct_change, 3),
        }

        # Base: coppia sale = base forte → pct positivo = bullish per base
        if base in ccy_signals:
            ccy_signals[base].append(pct_change)
            ccy_details[base].append({**detail, "direction": "base"})

        # Quote: coppia sale = quote debole → invertiamo il segno
        if quote in ccy_signals:
            ccy_signals[quote].append(-pct_change)
            ccy_details[quote].append({**detail, "direction": "quote"})

    results = {}
    for ccy in CURRENCIES:
        vals = ccy_signals[ccy]
        if vals:
            avg_ratio = float(np.mean(vals))
        else:
            avg_ratio = 0.0

        # Soglia per segnale: ±0.05% di media
        if avg_ratio > 0.05:
            signal = "🟢 BULLISH"
        elif avg_ratio < -0.05:
            signal = "🔴 BEARISH"
        else:
            signal = "➖ NEUTRO"

        results[ccy] = {
            "candle9_ratio": round(avg_ratio, 3),
            "candle9_signal": signal,
            "candle9_pairs": len(vals),
            "candle9_detail": ccy_details[ccy],
        }

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# CANDLE-9 SCORE (0-100) per composito — magnitude + velocity + consistency
# ═══════════════════════════════════════════════════════════════════════════════

def compute_candle9_scores(
    all_pairs: dict[str, pd.DataFrame],
    lookback: int = 9,
) -> dict[str, float]:
    """
    Score 0-100 per valuta basato su escursione e velocità rispetto a 9 candele fa.
    Componenti:
      - Magnitude (50%): % variazione close attuale vs close 9 candele fa
      - Velocity  (35%): pendenza lineare del close nelle ultime 9 candele
      - Consistency (15%): % di candele nella stessa direzione del movimento
    Per ogni coppia calcola il sub-score, poi media per valuta.
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

        # Consistency: quante candele nella stessa direzione del movimento
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

        pair_score = (
            magnitude_score * 0.50 +
            velocity_score * 0.35 +
            (50 + consistency_bonus) * 0.15
        )
        pair_score = float(np.clip(pair_score, 0, 100))

        # Base: coppia sale → base forte
        if base in ccy_scores:
            ccy_scores[base].append(pair_score)
        # Quote: inverso
        if quote in ccy_scores:
            ccy_scores[quote].append(100 - pair_score)

    return {ccy: round(float(np.mean(vals)), 2) if vals else 50.0
            for ccy, vals in ccy_scores.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# RIEPILOGO COMPLETO (entry-point per la dashboard)
# ═══════════════════════════════════════════════════════════════════════════════

def full_analysis(
    all_pairs: dict[str, pd.DataFrame],
    futures_data: dict[str, pd.DataFrame],
    cot_scores: dict[str, dict],
) -> dict:
    """
    Esegue l'analisi completa e restituisce un dizionario strutturato
    pronto per la dashboard.
    """
    # 1. Price Action
    price_scores = compute_price_action_scores(all_pairs)

    # 2. Volume
    volume_scores = compute_volume_scores(all_pairs, futures_data, price_scores)

    # 3. Candle-9 scores (0-100) per composito
    c9_scores = compute_candle9_scores(all_pairs)

    # 4. Composito (PA + Volume + COT + C9)
    composite = compute_composite_scores(price_scores, volume_scores, cot_scores, c9_scores)

    # 5. Momentum
    momentum = compute_momentum_rankings(all_pairs)

    # 6. Classificazione Trend/MeanRevert
    classification = classify_trend_vs_reversion(all_pairs, futures_data)

    # 7. Forza rolling composita (per grafico storico)
    rolling = compute_rolling_strength(all_pairs, window=20,
                                       futures_data=futures_data,
                                       cot_scores=cot_scores)

    # 8. ATR / Volatilità
    atr_ctx = compute_atr_context(all_pairs)

    # 9. Velocity (rapidità del movimento)
    velocity = compute_velocity_scores(all_pairs, composite)

    # 10. Trend structure (cascata EMA)
    trend_structure = compute_trend_structure(all_pairs)

    # 11. Strength persistence (persistenza direzionale)
    persistence = compute_strength_persistence(rolling)

    # 12. Candle-9 Price Action signal (display)
    candle9 = compute_candle9_signal(all_pairs)

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
# BLEND MULTI-TIMEFRAME (H1 + H4 + D1)
# ═══════════════════════════════════════════════════════════════════════════════

def blend_multi_timeframe(analysis_h1: dict, analysis_h4: dict,
                          analysis_d1: dict | None = None,
                          w_h1: float = COMPOSITE_WEIGHT_H1,
                          w_h4: float = COMPOSITE_WEIGHT_H4,
                          w_d1: float = COMPOSITE_WEIGHT_D1) -> dict:
    """
    Unisce i risultati dell'analisi su H1, H4 e D1 in un unico dato composito.

    H1 contribuisce con la **reattività** (risposta rapida ai movimenti),
    H4 contribuisce con la **stabilità** (trend robusti, meno rumore),
    D1 contribuisce con il **trend di fondo** (direzione dominante giornaliera).

    Se analysis_d1 è None, il blend avviene solo su H1 e H4 (retrocompatibilità).
    """

    # Retrocompatibilità: se D1 non è presente, rinormalizza i pesi H1+H4
    if analysis_d1 is None:
        _total = w_h1 + w_h4
        w_h1, w_h4, w_d1 = w_h1 / _total, w_h4 / _total, 0.0
        # Usa H4 come fallback per D1 
        analysis_d1 = analysis_h4

    composite_h1 = analysis_h1["composite"]
    composite_h4 = analysis_h4["composite"]
    composite_d1 = analysis_d1["composite"]
    momentum_h1  = analysis_h1["momentum"]
    momentum_h4  = analysis_h4["momentum"]
    momentum_d1  = analysis_d1["momentum"]
    class_h1     = analysis_h1["classification"]
    class_h4     = analysis_h4["classification"]
    class_d1     = analysis_d1["classification"]
    rolling_h1   = analysis_h1["rolling_strength"]
    rolling_h4   = analysis_h4["rolling_strength"]
    rolling_d1   = analysis_d1["rolling_strength"]

    # ── 1. Composite scores blendati ──────────────────────────────────────
    blended_composite = {}
    for ccy in CURRENCIES:
        c1 = composite_h1.get(ccy, {})
        c4 = composite_h4.get(ccy, {})
        cd = composite_d1.get(ccy, {})

        # ── Decay accelerato D1 quando H1 e H4 divergono ────────────────
        s_h1 = c1.get("composite", 50)
        s_h4 = c4.get("composite", 50)
        gap = abs(s_h1 - s_h4)
        opposite_sides = (s_h1 >= 55 and s_h4 <= 45) or (s_h1 <= 45 and s_h4 >= 55)

        if gap >= D1_DIVERGENCE_THRESHOLD and w_d1 > 0:
            # Decay lineare: 0 alla soglia → 1 al max
            raw_decay = min((gap - D1_DIVERGENCE_THRESHOLD) /
                            max(D1_DIVERGENCE_MAX - D1_DIVERGENCE_THRESHOLD, 1), 1.0)
            # Bonus se H1 e H4 su lati opposti del 50
            if opposite_sides:
                raw_decay = min(raw_decay + D1_DECAY_OPPOSITE_BONUS, 1.0)
            # Peso D1 effettivo per questa valuta
            eff_d1 = max(w_d1 * (1 - raw_decay), D1_DECAY_MIN_WEIGHT)
            # Ridistribuisci il peso tolto a D1 verso H1 e H4 proporzionalmente
            freed = w_d1 - eff_d1
            ratio_h1h4 = w_h1 / (w_h1 + w_h4) if (w_h1 + w_h4) > 0 else 0.5
            eff_h1 = w_h1 + freed * ratio_h1h4
            eff_h4 = w_h4 + freed * (1 - ratio_h1h4)
            decay_pct = round((1 - eff_d1 / w_d1) * 100) if w_d1 > 0 else 0
        else:
            eff_h1, eff_h4, eff_d1 = w_h1, w_h4, w_d1
            raw_decay = 0.0
            decay_pct = 0

        # Blend di ogni sotto-score (con pesi effettivi)
        pa  = c1.get("price_score", 50) * eff_h1 + c4.get("price_score", 50) * eff_h4 + cd.get("price_score", 50) * eff_d1
        vol = c1.get("volume_score", 50) * eff_h1 + c4.get("volume_score", 50) * eff_h4 + cd.get("volume_score", 50) * eff_d1
        cot = c1.get("cot_score", 50) * eff_h1 + c4.get("cot_score", 50) * eff_h4 + cd.get("cot_score", 50) * eff_d1
        c9  = c1.get("c9_score", 50) * eff_h1 + c4.get("c9_score", 50) * eff_h4 + cd.get("c9_score", 50) * eff_d1
        comp = c1.get("composite", 50) * eff_h1 + c4.get("composite", 50) * eff_h4 + cd.get("composite", 50) * eff_d1
        comp = round(float(np.clip(comp, 0, 100)), 1)

        # Label basata sul composito blendato
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

        # Alert — prende da entrambi i timeframe
        alert = None
        if comp >= THRESHOLD_EXTREME_BULL:
            alert = "⚠️ ATTENZIONE: forza estrema, possibile esaurimento"
        elif comp <= THRESHOLD_EXTREME_BEAR:
            alert = "⚠️ ATTENZIONE: debolezza estrema, possibile rimbalzo"
        # Conserva COT alert (uguale su entrambi i TF)
        cot_info_alert = c4.get("cot_extreme") or c1.get("cot_extreme")
        if cot_info_alert == "CROWDED_LONG":
            alert = (alert or "") + " | COT: posizionamento speculativo estremo LONG"
        elif cot_info_alert == "CROWDED_SHORT":
            alert = (alert or "") + " | COT: posizionamento speculativo estremo SHORT"

        # Concordanza / divergenza tra H1, H4 e D1
        concordance = _concordance_label(
            c1.get("composite", 50), c4.get("composite", 50),
            cd.get("composite", 50)
        )

        blended_composite[ccy] = {
            "price_score": round(pa, 1),
            "volume_score": round(vol, 1),
            "cot_score": round(cot, 1),
            "c9_score": round(c9, 1),
            "composite": comp,
            "label": label,
            "alert": alert,
            "cot_bias": c4.get("cot_bias", "NEUTRAL"),
            "cot_extreme": cot_info_alert,
            # Extra: dettaglio per TF
            "h1_score": round(c1.get("composite", 50), 1),
            "h4_score": round(c4.get("composite", 50), 1),
            "d1_score": round(cd.get("composite", 50), 1),
            "concordance": concordance,
            # Info decay D1
            "d1_decay_pct": decay_pct,
            "d1_eff_weight": round(eff_d1, 3),
            "h1h4_gap": round(gap, 1),
            "h1h4_opposite": opposite_sides,
        }

    # ── 2. Momentum blendato ─────────────────────────────────────────────
    blended_momentum = {}
    for ccy in CURRENCIES:
        m1 = momentum_h1.get(ccy, {"delta": 0, "acceleration": 0})
        m4 = momentum_h4.get(ccy, {"delta": 0, "acceleration": 0})
        md = momentum_d1.get(ccy, {"delta": 0, "acceleration": 0})

        delta = m1["delta"] * w_h1 + m4["delta"] * w_h4 + md["delta"] * w_d1
        accel = m1["acceleration"] * w_h1 + m4["acceleration"] * w_h4 + md["acceleration"] * w_d1
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

        blended_momentum[ccy] = {
            "delta": delta,
            "acceleration": accel,
            "rank_label": rank_label,
        }

    # ── 3. Classificazione blended ───────────────────────────────────────
    blended_class = {}
    for ccy in CURRENCIES:
        cl1 = class_h1.get(ccy, {})
        cl4 = class_h4.get(ccy, {})
        cld = class_d1.get(ccy, {})

        adx_avg = cl1.get("adx_avg", 20) * w_h1 + cl4.get("adx_avg", 20) * w_h4 + cld.get("adx_avg", 20) * w_d1
        hurst   = cl1.get("hurst", 0.5) * w_h1 + cl4.get("hurst", 0.5) * w_h4 + cld.get("hurst", 0.5) * w_d1
        er      = cl1.get("eff_ratio", 0.3) * w_h1 + cl4.get("eff_ratio", 0.3) * w_h4 + cld.get("eff_ratio", 0.3) * w_d1
        ts      = cl1.get("trend_score", 50) * w_h1 + cl4.get("trend_score", 50) * w_h4 + cld.get("trend_score", 50) * w_d1
        ts = round(float(np.clip(ts, 0, 100)), 1)

        if ts >= 65:
            classification = "TREND_FOLLOWING"
        elif ts <= 35:
            classification = "MEAN_REVERTING"
        else:
            classification = "MIXED"

        blended_class[ccy] = {
            "adx_avg": round(adx_avg, 1),
            "hurst": round(hurst, 3),
            "eff_ratio": round(er, 3),
            "trend_score": ts,
            "classification": classification,
        }

    # ── 4. Rolling strength blendato ─────────────────────────────────────
    dfs_rolling = []
    weights_rolling = []
    for rdf, w in [(rolling_h1, w_h1), (rolling_h4, w_h4), (rolling_d1, w_d1)]:
        if rdf is not None and not rdf.empty and w > 0:
            dfs_rolling.append(rdf)
            weights_rolling.append(w)

    if len(dfs_rolling) >= 2:
        # Allinea sugli indici comuni
        common_idx = dfs_rolling[0].index
        for df in dfs_rolling[1:]:
            common_idx = common_idx.intersection(df.index)
        if len(common_idx) > 0:
            blended_rolling = sum(
                df.loc[common_idx] * w for df, w in zip(dfs_rolling, weights_rolling)
            )
        else:
            blended_rolling = dfs_rolling[-1]  # fallback al TF più alto
    elif len(dfs_rolling) == 1:
        blended_rolling = dfs_rolling[0]
    else:
        blended_rolling = pd.DataFrame()

    # ── 5. Velocity blendato ──────────────────────────────────────────────
    vel_h1 = analysis_h1.get("velocity", {})
    vel_h4 = analysis_h4.get("velocity", {})
    vel_d1 = analysis_d1.get("velocity", {})
    blended_velocity = {}
    for ccy in CURRENCIES:
        v1 = vel_h1.get(ccy, {"bars_to_move": 0, "velocity_norm": 50})
        v4 = vel_h4.get(ccy, {"bars_to_move": 0, "velocity_norm": 50})
        vd = vel_d1.get(ccy, {"bars_to_move": 0, "velocity_norm": 50})
        vn = v1["velocity_norm"] * w_h1 + v4["velocity_norm"] * w_h4 + vd["velocity_norm"] * w_d1
        btm = round(v1["bars_to_move"] * w_h1 + v4["bars_to_move"] * w_h4 + vd["bars_to_move"] * w_d1)
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
        blended_velocity[ccy] = {
            "bars_to_move": btm,
            "velocity_norm": vn,
            "velocity_label": vlabel,
        }

    # ── 6. ATR context blendato ──────────────────────────────────────────
    atr_h1 = analysis_h1.get("atr_context", {})
    atr_h4 = analysis_h4.get("atr_context", {})
    atr_d1 = analysis_d1.get("atr_context", {})
    blended_atr = {}
    for ccy in CURRENCIES:
        a1 = atr_h1.get(ccy, {"atr_pct": 0, "atr_percentile": 50})
        a4 = atr_h4.get(ccy, {"atr_pct": 0, "atr_percentile": 50})
        ad = atr_d1.get(ccy, {"atr_pct": 0, "atr_percentile": 50})
        avg_pct = a1["atr_pct"] * w_h1 + a4["atr_pct"] * w_h4 + ad["atr_pct"] * w_d1
        avg_perc = a1["atr_percentile"] * w_h1 + a4["atr_percentile"] * w_h4 + ad["atr_percentile"] * w_d1
        if avg_perc >= 85:
            regime = "EXTREME"
        elif avg_perc >= 65:
            regime = "HIGH"
        elif avg_perc >= 35:
            regime = "NORMAL"
        else:
            regime = "LOW"
        blended_atr[ccy] = {
            "atr_pct": round(avg_pct, 4),
            "atr_percentile": round(avg_perc, 1),
            "volatility_regime": regime,
        }

    # ── 7. Candle-9 blendato ─────────────────────────────────────────────
    c9_h1 = analysis_h1.get("candle9", {})
    c9_h4 = analysis_h4.get("candle9", {})
    c9_d1 = analysis_d1.get("candle9", {})
    blended_candle9 = {}
    for ccy in CURRENCIES:
        s1 = c9_h1.get(ccy, {"candle9_ratio": 0, "candle9_pairs": 0, "candle9_detail": []})
        s4 = c9_h4.get(ccy, {"candle9_ratio": 0, "candle9_pairs": 0, "candle9_detail": []})
        sd = c9_d1.get(ccy, {"candle9_ratio": 0, "candle9_pairs": 0, "candle9_detail": []})
        ratio = s1["candle9_ratio"] * w_h1 + s4["candle9_ratio"] * w_h4 + sd["candle9_ratio"] * w_d1
        ratio = round(ratio, 3)
        if ratio > 0.05:
            signal = "🟢 BULLISH"
        elif ratio < -0.05:
            signal = "🔴 BEARISH"
        else:
            signal = "➖ NEUTRO"
        blended_candle9[ccy] = {
            "candle9_ratio": ratio,
            "candle9_signal": signal,
            "candle9_pairs": max(s1["candle9_pairs"], s4["candle9_pairs"], sd["candle9_pairs"]),
            "candle9_detail": [],
        }

    return {
        "composite": blended_composite,
        "momentum": blended_momentum,
        "classification": blended_class,
        "rolling_strength": blended_rolling,
        "atr_context": blended_atr,
        "velocity": blended_velocity,
        "trend_structure": _blend_trend_structure(analysis_h1, analysis_h4, analysis_d1, w_h1, w_h4, w_d1),
        "strength_persistence": _blend_strength_persistence(analysis_h1, analysis_h4, analysis_d1, w_h1, w_h4, w_d1),
        "candle9": blended_candle9,
        # Extra: analisi separate per confronto
        "h1_analysis": analysis_h1,
        "h4_analysis": analysis_h4,
        "d1_analysis": analysis_d1,
    }


def _blend_trend_structure(a_h1: dict, a_h4: dict, a_d1: dict,
                           w_h1: float, w_h4: float, w_d1: float) -> dict[str, dict]:
    """Blend trend_structure tra H1, H4 e D1."""
    ts_h1 = a_h1.get("trend_structure", {})
    ts_h4 = a_h4.get("trend_structure", {})
    ts_d1 = a_d1.get("trend_structure", {})
    blended = {}
    for ccy in CURRENCIES:
        t1 = ts_h1.get(ccy, {"ema_alignment": 0})
        t4 = ts_h4.get(ccy, {"ema_alignment": 0})
        td = ts_d1.get(ccy, {"ema_alignment": 0})
        avg = t1["ema_alignment"] * w_h1 + t4["ema_alignment"] * w_h4 + td["ema_alignment"] * w_d1
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
        blended[ccy] = {"ema_alignment": avg, "structure_label": label}
    return blended


def _blend_strength_persistence(a_h1: dict, a_h4: dict, a_d1: dict,
                                w_h1: float, w_h4: float, w_d1: float) -> dict[str, dict]:
    """Blend strength_persistence tra H1, H4 e D1."""
    p_h1 = a_h1.get("strength_persistence", {})
    p_h4 = a_h4.get("strength_persistence", {})
    p_d1 = a_d1.get("strength_persistence", {})
    blended = {}
    for ccy in CURRENCIES:
        ph1 = p_h1.get(ccy, {"persistence": 0, "slope": 0})
        ph4 = p_h4.get(ccy, {"persistence": 0, "slope": 0})
        pd1 = p_d1.get(ccy, {"persistence": 0, "slope": 0})
        p = ph1["persistence"] * w_h1 + ph4["persistence"] * w_h4 + pd1["persistence"] * w_d1
        sl = ph1["slope"] * w_h1 + ph4["slope"] * w_h4 + pd1["slope"] * w_d1
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
        blended[ccy] = {"persistence": p, "slope": sl, "consistency_label": label}
    return blended


def _concordance_label(score_h1: float, score_h4: float,
                       score_d1: float | None = None) -> str:
    """
    Restituisce un'etichetta di concordanza tra H1, H4 e D1.
    Se tutti sono dalla stessa parte → ALLINEATI
    Se divergono → DIVERGENZA PARZIALE o FORTE
    """
    scores = [score_h1, score_h4]
    if score_d1 is not None:
        scores.append(score_d1)

    bulls = sum(1 for s in scores if s >= 55)
    bears = sum(1 for s in scores if s <= 45)
    n = len(scores)

    if bulls == n:
        return "✅ ALLINEATI BULL"
    elif bears == n:
        return "✅ ALLINEATI BEAR"
    elif bulls > 0 and bears > 0:
        return "⚠️ DIVERGENZA"
    else:
        return "➖ NEUTRO"
