"""
Currency Strength Mobile – Yahoo Finance Data Fetcher
=====================================================
Dual-backend HTTP fetcher: tries requests first, falls back to http.client.
Designed for Android (serious_python) where requests/urllib3 may hang.
"""

import os
import sys
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
from urllib.parse import urlparse

from app_config import FOREX_PAIRS, FUTURES_TICKERS, CURRENCIES

_log = logging.getLogger(__name__)

# Suppress urllib3/requests version warnings
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*charset.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Global socket timeout: prevents ANY socket from hanging forever
socket.setdefaulttimeout(20)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# SSL context for http.client fallback (no cert verification)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 1: http.client (stdlib — always available, no native deps)
# ═══════════════════════════════════════════════════════════════════════════════

_hc_cookies: dict = {}


def _hc_get(url: str, timeout: int = 12) -> tuple:
    """HTTP GET via http.client. Returns (status, body_str). Follows redirects."""
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    for _ in range(5):  # max redirects
        try:
            conn = http.client.HTTPSConnection(host, timeout=timeout,
                                                context=_ssl_ctx)
            headers = {
                "User-Agent": _UA,
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.5",
            }
            if _hc_cookies:
                headers["Cookie"] = "; ".join(
                    f"{k}={v}" for k, v in _hc_cookies.items())
            conn.request("GET", path, headers=headers)
            resp = conn.getresponse()

            # Store cookies
            for key, val in resp.getheaders():
                if key.lower() == "set-cookie":
                    part = val.split(";")[0].strip()
                    if "=" in part:
                        n, v = part.split("=", 1)
                        _hc_cookies[n.strip()] = v.strip()

            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location", "")
                resp.read()
                conn.close()
                if loc:
                    if loc.startswith("http"):
                        p2 = urlparse(loc)
                        host = p2.netloc
                        path = p2.path + ("?" + p2.query if p2.query else "")
                    else:
                        path = loc
                    continue
                break

            body = resp.read().decode("utf-8", errors="replace")
            conn.close()
            return resp.status, body
        except Exception as e:
            try:
                conn.close()
            except Exception:
                pass
            return -1, f"{type(e).__name__}: {e}"
    return 0, "too many redirects"


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 2: requests.Session (better cookies/redirect handling)
# ═══════════════════════════════════════════════════════════════════════════════

_session = None
_requests_ok = None  # None = untested, True/False = tested


def _get_session():
    """Lazy-init requests.Session. Returns None if requests is broken."""
    global _session, _requests_ok
    if _requests_ok is False:
        return None
    if _session is not None:
        return _session
    try:
        import requests
        from requests.adapters import HTTPAdapter
        s = requests.Session()
        s.headers.update({
            "User-Agent": _UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
        })
        adapter = HTTPAdapter(max_retries=1)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.verify = False
        _session = s
        _requests_ok = True
        _log.info("requests.Session created OK")
        return s
    except Exception as e:
        _log.warning(f"requests unavailable: {e}")
        _requests_ok = False
        return None


def _requests_get(url: str, timeout: int = 12) -> tuple:
    """HTTP GET via requests. Returns (status, body) or None if unavailable."""
    s = _get_session()
    if s is None:
        return None
    try:
        # Use tuple timeout: (connect_timeout, read_timeout)
        resp = s.get(url, timeout=(min(timeout, 8), timeout),
                     allow_redirects=True)
        return resp.status_code, resp.text
    except Exception as e:
        _log.warning(f"requests error: {type(e).__name__}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  UNIFIED GET — tries requests first, falls back to http.client
# ═══════════════════════════════════════════════════════════════════════════════


def _get(url: str, timeout: int = 12) -> tuple:
    """HTTP GET with automatic fallback. Returns (status_code, body_text)."""
    # Try requests first (better cookie/redirect handling)
    result = _requests_get(url, timeout)
    if result is not None:
        st, body = result
        if st > 0:
            return st, body
        # requests got an error, try http.client
        _log.info(f"  requests returned {st}, trying http.client...")

    # Fallback to http.client
    return _hc_get(url, timeout)


# ═══════════════════════════════════════════════════════════════════════════════
#  NETWORK PROBE — fast, non-blocking connectivity test
# ═══════════════════════════════════════════════════════════════════════════════

_probe_results = ""


def _deep_network_probe() -> str:
    """Quick connectivity test. Very short timeouts to avoid hanging."""
    global _probe_results
    results = []

    # 1. DNS test (fast, tells us if networking works at all)
    try:
        addrs = socket.getaddrinfo("query2.finance.yahoo.com", 443,
                                    type=socket.SOCK_STREAM)
        results.append(f"DNS:OK({len(addrs)})")
        _log.info(f"PROBE DNS OK ({len(addrs)} addrs)")
    except Exception as e:
        results.append(f"DNS:FAIL({type(e).__name__})")
        _log.error(f"PROBE DNS FAIL: {e}")

    # 2. Quick Yahoo chart fetch (the only thing we actually need)
    try:
        st, body = _get(
            "https://query2.finance.yahoo.com/v8/finance/chart/EURUSD=X"
            "?range=1d&interval=1h", timeout=8)
        results.append(f"Yahoo:{st}({len(body)}b)")
        _log.info(f"PROBE Yahoo: {st}, {len(body)}b")
    except Exception as e:
        results.append(f"Yahoo:FAIL({type(e).__name__})")
        _log.error(f"PROBE Yahoo: {e}")

    _probe_results = " | ".join(results)
    _log.info(f"PROBE: {_probe_results}")
    return _probe_results


# ═══════════════════════════════════════════════════════════════════════════════
#  YAHOO SESSION — crumb (lightweight, no GDPR dance)
# ═══════════════════════════════════════════════════════════════════════════════

_crumb = None
_crumb_ts = 0.0


def _init_yahoo_session() -> str | None:
    """Get Yahoo crumb. Lightweight — skips GDPR consent flow."""
    global _crumb, _crumb_ts

    if _crumb and time.time() < _crumb_ts:
        return _crumb

    _log.info("Getting Yahoo crumb...")

    # Step 1: Touch fc.yahoo.com to get consent cookies (fast, one request)
    try:
        _get("https://fc.yahoo.com/", timeout=6)
    except Exception:
        pass

    # Step 2: Get crumb
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        try:
            st, body = _get(f"https://{host}/v1/test/getcrumb", timeout=6)
            body = body.strip()
            _log.info(f"  crumb@{host}: {st}, '{body[:30]}'")
            if st == 200 and body and len(body) < 50 and "<" not in body:
                _crumb = body
                _crumb_ts = time.time() + 1800
                return _crumb
        except Exception as exc:
            _log.warning(f"  crumb@{host}: {exc}")

    _log.warning("  No crumb — will proceed without")
    _crumb = None
    _crumb_ts = time.time() + 120
    return None


def _reset_crumb():
    global _crumb, _crumb_ts, _session
    _crumb = None
    _crumb_ts = 0
    if _session is not None:
        try:
            _session.close()
        except Exception:
            pass
        _session = None


# ═══════════════════════════════════════════════════════════════════════════════
#  CONNECTIVITY / DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════════════

def test_connectivity() -> dict:
    return {"probe": _deep_network_probe()}


# ═══════════════════════════════════════════════════════════════════════════════
#  CHART FETCH
# ═══════════════════════════════════════════════════════════════════════════════

_HOSTS = ("query2.finance.yahoo.com", "query1.finance.yahoo.com")


def _parse_chart_json(body: str, symbol: str) -> pd.DataFrame:
    data = json.loads(body)
    result = data.get("chart", {}).get("result")
    if not result:
        err = data.get("chart", {}).get("error", {})
        _log.warning(f"  {symbol}: no chart.result, err={err}")
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
    """Fetch OHLCV from Yahoo chart API via requests.Session."""
    crumb = _init_yahoo_session()

    for host in _HOSTS:
        url = (f"https://{host}/v8/finance/chart/{symbol}"
               f"?range={period}&interval={interval}&includePrePost=false")
        if crumb:
            url += f"&crumb={crumb}"

        try:
            st, body = _get(url, timeout=15)
            _log.info(f"  {symbol}@{host}: {st} ({len(body)}b)")
            if st == 200 and body:
                df = _parse_chart_json(body, symbol)
                if not df.empty:
                    return df
            elif st in (401, 403):
                _log.warning(f"  {symbol}@{host}: {st} → reset crumb & retry")
                _reset_crumb()
                crumb = _init_yahoo_session()
            else:
                _log.warning(f"  {symbol}@{host}: HTTP {st}")
        except json.JSONDecodeError:
            _log.warning(f"  {symbol}@{host}: invalid JSON")
        except Exception as exc:
            _log.error(f"  {symbol}@{host}: {type(exc).__name__}: {exc}")

    # Final fallback: try WITHOUT crumb
    try:
        url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
               f"?range={period}&interval={interval}&includePrePost=false")
        st, body = _get(url, timeout=15)
        _log.info(f"  {symbol}@query2(no-crumb): {st} ({len(body)}b)")
        if st == 200 and body:
            df = _parse_chart_json(body, symbol)
            if not df.empty:
                return df
    except Exception as exc:
        _log.error(f"  {symbol} no-crumb fallback: {type(exc).__name__}: {exc}")

    _log.warning(f"  {symbol}: FAILED all attempts")
    return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════════════════
#  RESAMPLE
# ═══════════════════════════════════════════════════════════════════════════════

def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"Open": "first", "High": "max", "Low": "min",
           "Close": "last", "Volume": "sum"}
    agg = {k: v for k, v in agg.items() if k in df.columns}
    return df.resample(rule).agg(agg).dropna(subset=["Close"])


# ═══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_pair(pair_name: str, timeframe: str = "H4") -> pd.DataFrame:
    info = FOREX_PAIRS[pair_name]
    df = _fetch_chart(info["ticker"], "30d", "1h")
    if df.empty:
        return df
    if timeframe == "H4":
        df = _resample_ohlcv(df, "4h")
    return df


_consecutive_fail = 0
_MAX_CONSEC_FAIL = 5          # abort early when network is dead


def fetch_all_pairs(timeframe: str = "H4",
                    progress_callback=None) -> dict:
    global _consecutive_fail
    _consecutive_fail = 0
    results: dict[str, pd.DataFrame] = {}
    total = len(FOREX_PAIRS)

    for i, pair in enumerate(FOREX_PAIRS):
        if progress_callback:
            progress_callback(i, total, f"Scarico {pair}…")
        try:
            df = fetch_pair(pair, timeframe)
            if not df.empty:
                results[pair] = df
                _consecutive_fail = 0
                _log.info(f"  ✓ {pair}: {len(df)} bars")
            else:
                _consecutive_fail += 1
                _log.warning(f"  ✗ {pair} vuoto (fail#{_consecutive_fail})")
        except Exception as exc:
            _consecutive_fail += 1
            _log.error(f"  ✗ {pair}: {exc} (fail#{_consecutive_fail})")

        if progress_callback:
            progress_callback(i + 1, total, f"{pair} ({len(results)}/{i+1})")

        # early abort
        if _consecutive_fail >= _MAX_CONSEC_FAIL and not results:
            _log.error(
                f"ABORT: {_consecutive_fail} consecutive failures, 0 success")
            if progress_callback:
                progress_callback(i + 1, total,
                    f"Abort: {_consecutive_fail} fallimenti consecutivi")
            break
        time.sleep(0.05)
    return results


def fetch_futures_volume(currency: str, timeframe: str = "H4") -> pd.DataFrame:
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
    results: dict[str, pd.DataFrame] = {}
    total = len(CURRENCIES)
    for i, ccy in enumerate(CURRENCIES):
        if progress_callback:
            progress_callback(i, total, f"Futures {ccy}…")
        try:
            df = fetch_futures_volume(ccy, timeframe)
            if not df.empty:
                results[ccy] = df
                _log.info(f"  ✓ Futures {ccy}: {len(df)} bars")
        except Exception as exc:
            _log.error(f"  ✗ Futures {ccy}: {exc}")
        if progress_callback:
            progress_callback(i + 1, total,
                              f"Futures {ccy} ({len(results)}/{i+1})")
        time.sleep(0.05)
    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  CURRENCY RETURNS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_currency_returns(all_pairs: dict, window: int = 1) -> pd.DataFrame:
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
