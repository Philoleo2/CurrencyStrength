"""
Currency Strength Indicator – Data Fetcher
============================================
Scarica dati di prezzo (forex) e volumi (futures CME) via yfinance.
Gestisce il resampling H1 → H4 e la cache locale.
"""

import os
import time
import logging
import datetime as dt
import pandas as pd
import numpy as np
import yfinance as yf

_log = logging.getLogger(__name__)

from config import (
    FOREX_PAIRS, FUTURES_TICKERS, CURRENCIES,
    YFINANCE_INTERVAL, YFINANCE_PERIOD, RESAMPLE_MAP, CACHE_DIR,
)

# ─── helpers ────────────────────────────────────────────────────────────────

def _ensure_cache():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(name: str) -> str:
    _ensure_cache()
    return os.path.join(CACHE_DIR, f"{name}.parquet")


def _is_fresh(path: str, max_age_s: int = 3600) -> bool:
    """Restituisce True se il file esiste ed è più recente di max_age_s secondi."""
    if not os.path.exists(path):
        return False
    age = time.time() - os.path.getmtime(path)
    return age < max_age_s


def _fetch_with_retry(ticker_symbol: str, period: str, interval: str,
                      max_retries: int = 3) -> pd.DataFrame:
    """Fetch yfinance data con retry e backoff esponenziale."""
    for attempt in range(max_retries):
        try:
            tk = yf.Ticker(ticker_symbol)
            df = tk.history(period=period, interval=interval, auto_adjust=True)
            if not df.empty:
                return df
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
        except Exception as e:
            wait = 2 ** (attempt + 1)
            _log.warning(f"Tentativo {attempt+1}/{max_retries} per {ticker_symbol}: {e}. Retry in {wait}s")
            if attempt < max_retries - 1:
                time.sleep(wait)
    return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════════
# PRICE DATA
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_pair(pair_name: str, timeframe: str = "H4",
               max_cache_age: int = 3600) -> pd.DataFrame:
    """
    Scarica i dati OHLCV di una coppia forex.
    Se timeframe == "H4", resampla da 1h a 4h.
    Restituisce DataFrame con colonne: Open, High, Low, Close, Volume.
    """
    cache_key = f"pair_{pair_name}_{timeframe}"
    cp = _cache_path(cache_key)
    if _is_fresh(cp, max_cache_age):
        return pd.read_parquet(cp)

    info = FOREX_PAIRS[pair_name]
    interval = YFINANCE_INTERVAL[timeframe]
    period = YFINANCE_PERIOD[timeframe]

    df = _fetch_with_retry(info["ticker"], period, interval)

    if df.empty:
        # Fallback: cache stantia
        if os.path.exists(cp):
            age_h = (time.time() - os.path.getmtime(cp)) / 3600
            _log.warning(f"⚠️ {pair_name}: dati live non disponibili, uso cache stantia ({age_h:.0f}h)")
            return pd.read_parquet(cp)
        return df

    # pulizia colonne
    for col in ["Dividends", "Stock Splits", "Capital Gains"]:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    # Resample se necessario (H4)
    resample_rule = RESAMPLE_MAP.get(timeframe)
    if resample_rule:
        df = _resample_ohlcv(df, resample_rule)

    df.to_parquet(cp)
    return df


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resampla dati OHLCV da intervallo minore a maggiore."""
    agg = {
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }
    # Filtra solo colonne esistenti
    agg = {k: v for k, v in agg.items() if k in df.columns}
    resampled = df.resample(rule).agg(agg).dropna(subset=["Close"])
    return resampled


def fetch_all_pairs(timeframe: str = "H4",
                    max_cache_age: int = 3600) -> dict[str, pd.DataFrame]:
    """
    Scarica tutte le coppie forex configurate.
    Restituisce {nome_coppia: DataFrame}.
    """
    results = {}
    for pair_name in FOREX_PAIRS:
        df = fetch_pair(pair_name, timeframe, max_cache_age)
        if not df.empty:
            results[pair_name] = df
        time.sleep(0.25)  # gentile con yfinance
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# VOLUME DATA  (Futures CME come proxy)
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_futures_volume(currency: str, timeframe: str = "H4",
                         max_cache_age: int = 3600) -> pd.DataFrame:
    """
    Scarica dati OHLCV del future CME per la valuta data.
    Utile per estrarre il volume reale (non tick volume).
    """
    ticker = FUTURES_TICKERS.get(currency)
    if not ticker:
        return pd.DataFrame()

    cache_key = f"fut_{currency}_{timeframe}"
    cp = _cache_path(cache_key)
    if _is_fresh(cp, max_cache_age):
        return pd.read_parquet(cp)

    interval = YFINANCE_INTERVAL[timeframe]
    period = YFINANCE_PERIOD[timeframe]

    df = _fetch_with_retry(ticker, period, interval)

    if df.empty:
        if os.path.exists(cp):
            age_h = (time.time() - os.path.getmtime(cp)) / 3600
            _log.warning(f"⚠️ Futures {currency}: dati live non disponibili, uso cache stantia ({age_h:.0f}h)")
            return pd.read_parquet(cp)
        return df

    for col in ["Dividends", "Stock Splits", "Capital Gains"]:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    resample_rule = RESAMPLE_MAP.get(timeframe)
    if resample_rule:
        df = _resample_ohlcv(df, resample_rule)

    df.to_parquet(cp)
    return df


def fetch_all_futures(timeframe: str = "H4",
                      max_cache_age: int = 3600) -> dict[str, pd.DataFrame]:
    """
    Scarica i futures per tutte le valute.
    Restituisce {valuta: DataFrame}.
    """
    results = {}
    for ccy in CURRENCIES:
        df = fetch_futures_volume(ccy, timeframe, max_cache_age)
        if not df.empty:
            results[ccy] = df
        time.sleep(0.25)
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# RETURNS PER VALUTA  (aggregazione da tutte le coppie)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_currency_returns(all_pairs: dict[str, pd.DataFrame],
                             window: int = 1) -> pd.DataFrame:
    """
    Per ciascuna valuta, calcola il rendimento medio ponderato usando
    tutte le coppie che la contengono.

    Se la valuta è al numeratore (base), il rendimento è positivo quando
    il prezzo sale; se è al denominatore (quote), è inverso.

    Restituisce un DataFrame con indice datetime e colonne = valute,
    valori = rendimento percentuale medio.
    """
    ccy_returns: dict[str, list[pd.Series]] = {c: [] for c in CURRENCIES}

    for pair_name, df in all_pairs.items():
        if df.empty or "Close" not in df.columns:
            continue
        info = FOREX_PAIRS[pair_name]
        ret = df["Close"].pct_change(window)

        base = info["base"]
        quote = info["quote"]

        if base in ccy_returns:
            ccy_returns[base].append(ret.rename(pair_name))
        if quote in ccy_returns:
            ccy_returns[quote].append((-ret).rename(pair_name))  # inverso

    # media aritmetica dei rendimenti su tutte le coppie
    result = {}
    for ccy, series_list in ccy_returns.items():
        if series_list:
            combined = pd.concat(series_list, axis=1)
            result[ccy] = combined.mean(axis=1)
        else:
            result[ccy] = pd.Series(dtype=float)

    return pd.DataFrame(result).sort_index().dropna(how="all")


def compute_currency_cumulative(all_pairs: dict[str, pd.DataFrame],
                                lookback: int = 50) -> pd.DataFrame:
    """
    Restituisce la forza cumulativa di ogni valuta nelle ultime `lookback` barre.
    Utile per grafici di line-strength.
    """
    rets = compute_currency_returns(all_pairs, window=1)
    if rets.empty:
        return rets
    rets = rets.iloc[-lookback:]
    cum = (1 + rets).cumprod() - 1
    return cum * 100  # in punti percentuali


# ═══════════════════════════════════════════════════════════════════════════════
# VOLUME NORMALIZZATO PER VALUTA
# ═══════════════════════════════════════════════════════════════════════════════

def compute_volume_ratio(futures_data: dict[str, pd.DataFrame],
                         window: int = 20) -> dict[str, pd.Series]:
    """
    Per ogni valuta, calcola il rapporto Volume / SMA(Volume, window).
    Un valore > 1 indica volumi sopra la media, < 1 sotto la media.
    """
    ratios = {}
    for ccy, df in futures_data.items():
        if df.empty or "Volume" not in df.columns:
            continue
        vol = df["Volume"].astype(float)
        sma = vol.rolling(window).mean()
        ratio = (vol / sma).replace([np.inf, -np.inf], np.nan).dropna()
        ratios[ccy] = ratio
    return ratios
