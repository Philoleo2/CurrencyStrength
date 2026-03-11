"""
Asset Strength Indicator – Data Fetcher
=========================================
Scarica dati OHLCV per oro, argento, bitcoin, indici e materie prime
via yfinance. Supporta timeframe H4, Daily e Weekly.
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
    ASSETS, ASSET_TICKERS, ASSET_VOLUME_TICKERS,
    ASSET_YFINANCE_INTERVAL, ASSET_YFINANCE_PERIOD,
    ASSET_RESAMPLE_MAP, CACHE_DIR,
)

# ─── helpers ────────────────────────────────────────────────────────────────

def _ensure_cache():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(name: str) -> str:
    _ensure_cache()
    return os.path.join(CACHE_DIR, f"{name}.parquet")


def _is_fresh(path: str, max_age_s: int = 3600) -> bool:
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

def fetch_asset(asset_name: str, timeframe: str = "Daily",
                max_cache_age: int = 3600) -> pd.DataFrame:
    """
    Scarica dati OHLCV di un asset.
    Restituisce DataFrame con colonne: Open, High, Low, Close, Volume.
    """
    cache_key = f"asset_{asset_name}_{timeframe}"
    cp = _cache_path(cache_key)
    if _is_fresh(cp, max_cache_age):
        try:
            return pd.read_parquet(cp)
        except Exception:
            pass

    ticker = ASSET_TICKERS.get(asset_name)
    if not ticker:
        return pd.DataFrame()

    interval = ASSET_YFINANCE_INTERVAL.get(timeframe, "1d")
    period = ASSET_YFINANCE_PERIOD.get(timeframe, "1y")

    df = _fetch_with_retry(ticker, period, interval)

    if df.empty:
        if os.path.exists(cp):
            age_h = (time.time() - os.path.getmtime(cp)) / 3600
            _log.warning(f"⚠️ {asset_name}: dati live non disponibili, uso cache stantia ({age_h:.0f}h)")
            try:
                return pd.read_parquet(cp)
            except Exception:
                pass
        return pd.DataFrame()

    # pulizia colonne
    for col in ["Dividends", "Stock Splits", "Capital Gains"]:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    # Resample se necessario
    resample_rule = ASSET_RESAMPLE_MAP.get(timeframe)
    if resample_rule:
        df = _resample_ohlcv(df, resample_rule)

    try:
        df.to_parquet(cp)
    except Exception:
        pass

    return df


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }
    agg = {k: v for k, v in agg.items() if k in df.columns}
    resampled = df.resample(rule).agg(agg).dropna(subset=["Close"])
    return resampled


def fetch_all_assets(timeframe: str = "Daily",
                     max_cache_age: int = 3600) -> dict[str, pd.DataFrame]:
    """
    Scarica tutti gli asset configurati.
    Restituisce {nome_asset: DataFrame}.
    """
    results = {}
    for asset_name in ASSETS:
        df = fetch_asset(asset_name, timeframe, max_cache_age)
        if not df.empty:
            results[asset_name] = df
        time.sleep(0.3)
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# VOLUME DATA
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_asset_volume(asset_name: str, timeframe: str = "Daily",
                       max_cache_age: int = 3600) -> pd.DataFrame:
    """
    Scarica dati OHLCV con volume per l'asset.
    Per la maggior parte degli asset il volume è già incluso nel ticker principale.
    """
    ticker = ASSET_VOLUME_TICKERS.get(asset_name)
    if not ticker:
        return pd.DataFrame()

    cache_key = f"asset_vol_{asset_name}_{timeframe}"
    cp = _cache_path(cache_key)
    if _is_fresh(cp, max_cache_age):
        try:
            return pd.read_parquet(cp)
        except Exception:
            pass

    interval = ASSET_YFINANCE_INTERVAL.get(timeframe, "1d")
    period = ASSET_YFINANCE_PERIOD.get(timeframe, "1y")

    df = _fetch_with_retry(ticker, period, interval)

    if df.empty:
        if os.path.exists(cp):
            age_h = (time.time() - os.path.getmtime(cp)) / 3600
            _log.warning(f"⚠️ Volume {asset_name}: dati live non disponibili, uso cache stantia ({age_h:.0f}h)")
            try:
                return pd.read_parquet(cp)
            except Exception:
                pass
        return pd.DataFrame()

    if df.empty:
        return df

    for col in ["Dividends", "Stock Splits", "Capital Gains"]:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    resample_rule = ASSET_RESAMPLE_MAP.get(timeframe)
    if resample_rule:
        df = _resample_ohlcv(df, resample_rule)

    try:
        df.to_parquet(cp)
    except Exception:
        pass

    return df


def fetch_all_asset_volumes(timeframe: str = "Daily",
                            max_cache_age: int = 3600) -> dict[str, pd.DataFrame]:
    """
    Scarica i volumi per tutti gli asset.
    Restituisce {asset_name: DataFrame}.
    """
    results = {}
    for asset_name in ASSETS:
        df = fetch_asset_volume(asset_name, timeframe, max_cache_age)
        if not df.empty:
            results[asset_name] = df
        time.sleep(0.3)
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# VOLUME RATIO PER ASSET
# ═══════════════════════════════════════════════════════════════════════════════

def compute_asset_volume_ratio(asset_data: dict[str, pd.DataFrame],
                               window: int = 20) -> dict[str, pd.Series]:
    """
    Per ogni asset, calcola Volume / SMA(Volume, window).
    > 1 = volumi sopra media, < 1 = sotto media.
    """
    ratios = {}
    for asset_name, df in asset_data.items():
        if df.empty or "Volume" not in df.columns:
            continue
        vol = df["Volume"].astype(float)
        sma = vol.rolling(window).mean()
        ratio = (vol / sma).replace([np.inf, -np.inf], np.nan).dropna()
        ratios[asset_name] = ratio
    return ratios
