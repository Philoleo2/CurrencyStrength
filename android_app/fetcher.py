"""
Currency Strength Mobile - Yahoo Finance Data Fetcher  v6
=========================================================
MINIMAL approach: diagnostics showed raw socket with minimal
headers gets HTTP 200, while library calls with cookies get 429.
Yahoo rate-limits by session/cookies, NOT by IP.

Strategy:
  - NO cookies, NO crumb, NO session initialization
  - Single http.client connection per request with MINIMAL headers
  - Fresh connection per request (no pooling)
  - 1.5s delay between requests
  - Only 1 host, 1 attempt per symbol
"""

import os
import ssl
import time
import json
import socket
import logging
import warnings
import http.client
import numpy as np
import pandas as pd
from datetime import datetime, timezone

_certifi_path = None
try:
    import certifi
    _certifi_path = certifi.where()
    os.environ["SSL_CERT_FILE"] = _certifi_path
except ImportError:
    pass

from app_config import FOREX_PAIRS, FUTURES_TICKERS, CURRENCIES

_log = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=DeprecationWarning)

socket.setdefaulttimeout(25)

_ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)
_ssl_ctx.verify_mode = ssl.CERT_NONE

# ====================================================================
#  CORE HTTP - minimal, stateless, no cookies
# ====================================================================

_last_errors: list = []


def _get(url: str, timeout: int = 15) -> tuple:
    """
    Bare-minimum HTTPS GET. Fresh connection, minimal headers, NO cookies.
    Mimics the raw socket test that returned HTTP 200 in diagnostics.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    conn = None
    try:
        conn = http.client.HTTPSConnection(
            host, timeout=timeout, context=_ssl_ctx)
        conn.request("GET", path, headers={
            "Host": host,
            "User-Agent": "Mozilla/5.0",
            "Connection": "close",
        })
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        status = resp.status
        conn.close()
        return status, body
    except Exception as e:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        _log.warning("HTTP error: %s: %s", type(e).__name__, e)
        _last_errors.append("%s: %s" % (type(e).__name__, e))
        if len(_last_errors) > 20:
            _last_errors[:] = _last_errors[-10:]
        return -1, str(e)


# ====================================================================
#  DIAGNOSTICS
# ====================================================================

_diag_results: list = []


def run_diagnostics() -> list:
    """Test networking and return human-readable results."""
    global _diag_results
    results = []

    try:
        results.append("SSL: %s" % ssl.OPENSSL_VERSION)
    except Exception as e:
        results.append("SSL: %s" % e)

    if _certifi_path:
        results.append("certifi: %s (exists=%s)" % (
            _certifi_path, os.path.exists(_certifi_path)))
    else:
        results.append("certifi: non installato")

    try:
        addrs = socket.getaddrinfo("query2.finance.yahoo.com", 443,
                                   type=socket.SOCK_STREAM)
        results.append("DNS: %s (%d indirizzi)" % (addrs[0][4][0], len(addrs)))
    except Exception as e:
        results.append("DNS FAIL: %s" % e)

    try:
        st, body = _get(
            "https://query2.finance.yahoo.com/v8/finance/chart/EURUSD=X"
            "?range=1d&interval=1h", timeout=10)
        ok = "OK" if st == 200 else "FAIL"
        results.append("Chart API: HTTP %d (%db) %s" % (st, len(body), ok))
        if st == 200:
            try:
                d = json.loads(body)
                ts = d.get("chart", {}).get("result", [{}])[0].get("timestamp", [])
                results.append("  -> %d candele ricevute" % len(ts))
            except Exception:
                pass
    except Exception as e:
        results.append("Chart API: %s" % e)

    if _last_errors:
        results.append("Ultimi errori: %s" % "; ".join(_last_errors[-5:]))

    _diag_results = results
    for r in results:
        _log.info("DIAG: %s", r)
    return results


# ====================================================================
#  NETWORK PROBE
# ====================================================================

_probe_results = ""


def _deep_network_probe() -> str:
    global _probe_results
    results = []
    try:
        addrs = socket.getaddrinfo("query2.finance.yahoo.com", 443,
                                   type=socket.SOCK_STREAM)
        results.append("DNS:OK(%d)" % len(addrs))
    except Exception as e:
        results.append("DNS:FAIL(%s)" % type(e).__name__)

    try:
        st, body = _get(
            "https://query2.finance.yahoo.com/v8/finance/chart/EURUSD=X"
            "?range=1d&interval=1h", timeout=10)
        results.append("Yahoo:%d(%db)" % (st, len(body)))
    except Exception as e:
        results.append("Yahoo:FAIL(%s)" % type(e).__name__)

    _probe_results = " | ".join(results)
    _log.info("PROBE: %s", _probe_results)
    return _probe_results


def test_connectivity() -> dict:
    return {"probe": _deep_network_probe()}


# ====================================================================
#  CHART FETCH - no crumb, no session, one clean request per symbol
# ====================================================================

_HOST = "query2.finance.yahoo.com"


def _parse_chart_json(body: str, symbol: str) -> pd.DataFrame:
    data = json.loads(body)
    result = data.get("chart", {}).get("result")
    if not result:
        err = data.get("chart", {}).get("error", {})
        _log.warning("  %s: no chart.result, err=%s", symbol, err)
        return pd.DataFrame()
    r = result[0]
    ts = r.get("timestamp", [])
    if not ts:
        return pd.DataFrame()
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({
        "Open":   q.get("open"),
        "High":   q.get("high"),
        "Low":    q.get("low"),
        "Close":  q.get("close"),
        "Volume": q.get("volume", [0] * len(ts)),
    }, index=pd.to_datetime(ts, unit="s", utc=True))
    return df.dropna(subset=["Close"])


def _fetch_chart(symbol: str, period: str = "30d",
                 interval: str = "1h") -> pd.DataFrame:
    """Fetch OHLCV: one single clean request, no cookies, no crumb."""
    url = ("https://%s/v8/finance/chart/%s"
           "?range=%s&interval=%s&includePrePost=false" % (
               _HOST, symbol, period, interval))
    try:
        st, body = _get(url, timeout=15)
        _log.info("  %s: HTTP %d (%db)", symbol, st, len(body))

        if st == 200 and body:
            return _parse_chart_json(body, symbol)

        if st == 429:
            _log.info("  %s: 429, waiting 5s and retrying...", symbol)
            time.sleep(5)
            st2, body2 = _get(url, timeout=15)
            _log.info("  %s retry: HTTP %d (%db)", symbol, st2, len(body2))
            if st2 == 200 and body2:
                return _parse_chart_json(body2, symbol)

        if st not in (200, 429):
            _log.warning("  %s: HTTP %d", symbol, st)

    except json.JSONDecodeError:
        _log.warning("  %s: invalid JSON", symbol)
    except Exception as exc:
        _log.error("  %s: %s: %s", symbol, type(exc).__name__, exc)

    return pd.DataFrame()


# ====================================================================
#  RESAMPLE
# ====================================================================

def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"Open": "first", "High": "max", "Low": "min",
           "Close": "last", "Volume": "sum"}
    agg = {k: v for k, v in agg.items() if k in df.columns}
    return df.resample(rule).agg(agg).dropna(subset=["Close"])


# ====================================================================
#  PUBLIC API
# ====================================================================

def fetch_pair(pair_name: str, timeframe: str = "H4") -> pd.DataFrame:
    info = FOREX_PAIRS[pair_name]
    df = _fetch_chart(info["ticker"], "30d", "1h")
    if df.empty:
        return df
    if timeframe == "H4":
        df = _resample_ohlcv(df, "4h")
    return df


_consecutive_fail = 0
_MAX_CONSEC_FAIL = 10


def fetch_all_pairs(timeframe: str = "H4",
                    progress_callback=None) -> dict:
    global _consecutive_fail
    _consecutive_fail = 0
    results = {}
    total = len(FOREX_PAIRS)

    for i, pair in enumerate(FOREX_PAIRS):
        if progress_callback:
            progress_callback(i, total, "Scarico %s..." % pair)
        try:
            df = fetch_pair(pair, timeframe)
            if not df.empty:
                results[pair] = df
                _consecutive_fail = 0
                _log.info("  OK %s: %d bars", pair, len(df))
            else:
                _consecutive_fail += 1
                _log.warning("  VUOTO %s (fail#%d)", pair, _consecutive_fail)
        except Exception as exc:
            _consecutive_fail += 1
            _log.error("  ERR %s: %s (fail#%d)", pair, exc, _consecutive_fail)

        if progress_callback:
            progress_callback(i + 1, total,
                              "%s (%d/%d)" % (pair, len(results), i + 1))

        if _consecutive_fail >= _MAX_CONSEC_FAIL and not results:
            _log.error(
                "ABORT: %d consecutive failures, 0 success",
                _consecutive_fail)
            if progress_callback:
                progress_callback(i + 1, total,
                    "Abort: %d fallimenti consecutivi" % _consecutive_fail)
            break

        # 1.5s delay between requests to avoid 429
        time.sleep(1.5)
    return results


def fetch_futures_volume(currency: str,
                         timeframe: str = "H4") -> pd.DataFrame:
    ticker = FUTURES_TICKERS.get(currency)
    if not ticker:
        return pd.DataFrame()
    df = _fetch_chart(ticker, "30d", "1h")
    if df.empty:
        return df
    if timeframe == "H4":
        df = _resample_ohlcv(df, "4h")
    return df


def fetch_all_futures(timeframe: str = "H4",
                      progress_callback=None) -> dict:
    results = {}
    total = len(CURRENCIES)
    for i, ccy in enumerate(CURRENCIES):
        if progress_callback:
            progress_callback(i, total, "Futures %s..." % ccy)
        try:
            df = fetch_futures_volume(ccy, timeframe)
            if not df.empty:
                results[ccy] = df
                _log.info("  OK Futures %s: %d bars", ccy, len(df))
        except Exception as exc:
            _log.error("  ERR Futures %s: %s", ccy, exc)
        if progress_callback:
            progress_callback(i + 1, total,
                              "Futures %s (%d/%d)" % (ccy, len(results), i + 1))
        time.sleep(1.5)
    return results


# ====================================================================
#  CURRENCY RETURNS
# ====================================================================

def compute_currency_returns(all_pairs: dict,
                             window: int = 1) -> pd.DataFrame:
    if not all_pairs:
        return pd.DataFrame()

    common_idx = None
    for df in all_pairs.values():
        if common_idx is None:
            common_idx = df.index
        else:
            common_idx = common_idx.intersection(df.index)

    if common_idx is None or len(common_idx) < 2:
        return pd.DataFrame()

    ccy_ret = {c: [] for c in CURRENCIES}
    for pair, pdf in all_pairs.items():
        info = FOREX_PAIRS[pair]
        close = pdf["Close"].reindex(common_idx)
        ret = close.pct_change(window).fillna(0)
        if info["base"] in ccy_ret:
            ccy_ret[info["base"]].append(ret)
        if info["quote"] in ccy_ret:
            ccy_ret[info["quote"]].append(-ret)

    result = pd.DataFrame(index=common_idx)
    for c in CURRENCIES:
        result[c] = (pd.concat(ccy_ret[c], axis=1).mean(axis=1)
                     if ccy_ret[c] else 0.0)
    return result


# ====================================================================
#  LEGACY COMPAT - engine.py may import these
# ====================================================================

def _init_yahoo_session():
    """No-op: v6 does not use sessions/crumb."""
    return None
