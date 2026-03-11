"""
Currency Strength Mobile – Yahoo Finance Data Fetcher  v4
=========================================================
Designed for Android (serious_python / Flet) where Python's SSL
may fail to find CA certificates.

Strategy:
  1. Set SSL_CERT_FILE from certifi BEFORE any HTTPS call.
  2. Try urllib.request  (stdlib, respects SSL_CERT_FILE natively).
  3. Try http.client     (stdlib, separate SSL context).
  4. Try requests        (third-party, better cookies).
  Fallback chain: whichever succeeds first is used.

Diagnostics: call run_diagnostics() to get a list of test results
that can be displayed in the UI.
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
import urllib.request
import urllib.error
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from urllib.parse import urlparse, quote

# ── Set certifi CA bundle BEFORE anything else touches SSL ──
_certifi_path = None
try:
    import certifi
    _certifi_path = certifi.where()
    os.environ["SSL_CERT_FILE"] = _certifi_path
    os.environ["REQUESTS_CA_BUNDLE"] = _certifi_path
except ImportError:
    pass

from app_config import FOREX_PAIRS, FUTURES_TICKERS, CURRENCIES

_log = logging.getLogger(__name__)

# Suppress noisy warnings
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*Unverified HTTPS.*")
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Global socket timeout – safety net against any socket hanging forever
socket.setdefaulttimeout(25)

_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)

# ═══════════════════════════════════════════════════════════════════════════════
#  SSL CONTEXTS – try multiple approaches
# ═══════════════════════════════════════════════════════════════════════════════

def _make_noverify_ctx():
    """SSL context that skips ALL certificate verification."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)        # not PROTOCOL_TLS_CLIENT
    ctx.verify_mode = ssl.CERT_NONE
    # Do NOT set check_hostname (default is already False for PROTOCOL_TLS)
    ctx.set_default_verify_paths()                # load whatever is available
    return ctx

def _make_certifi_ctx():
    """SSL context using certifi CA bundle (if available)."""
    if not _certifi_path or not os.path.exists(_certifi_path):
        return None
    try:
        ctx = ssl.create_default_context(cafile=_certifi_path)
        return ctx
    except Exception:
        return None

_ctx_noverify = _make_noverify_ctx()
_ctx_certifi  = _make_certifi_ctx()

# ═══════════════════════════════════════════════════════════════════════════════
#  DIAGNOSTICS – callable from the UI to show what works and what doesn't
# ═══════════════════════════════════════════════════════════════════════════════

_diag_results: list[str] = []

def run_diagnostics() -> list[str]:
    """
    Test every networking layer and return human-readable results.
    Call this when data fetching fails so the user can see what's broken.
    """
    global _diag_results
    results: list[str] = []

    # 1. SSL module
    try:
        results.append(f"✓ SSL: {ssl.OPENSSL_VERSION}")
    except Exception as e:
        results.append(f"✗ SSL: NON DISPONIBILE ({e})")

    # 2. certifi
    if _certifi_path:
        exists = os.path.exists(_certifi_path)
        results.append(f"{'✓' if exists else '✗'} certifi: {_certifi_path} (exists={exists})")
    else:
        results.append("✗ certifi: NON INSTALLATO")

    # 3. DNS resolution
    try:
        addrs = socket.getaddrinfo("query2.finance.yahoo.com", 443,
                                   type=socket.SOCK_STREAM)
        ip = addrs[0][4][0] if addrs else "?"
        results.append(f"✓ DNS: {ip} ({len(addrs)} indirizzi)")
    except Exception as e:
        results.append(f"✗ DNS: {type(e).__name__}: {e}")

    # 4. Raw TCP connection
    try:
        sock = socket.create_connection(
            ("query2.finance.yahoo.com", 443), timeout=10)
        results.append("✓ TCP: connesso a porta 443")

        # 5. SSL handshake (no verify)
        try:
            wrapped = _ctx_noverify.wrap_socket(
                sock, server_hostname="query2.finance.yahoo.com")
            ver = wrapped.version()
            results.append(f"✓ SSL handshake: {ver}")

            # 6. Raw HTTP over SSL
            try:
                req_bytes = (
                    b"GET /v8/finance/chart/EURUSD=X?range=1d&interval=1h "
                    b"HTTP/1.1\r\n"
                    b"Host: query2.finance.yahoo.com\r\n"
                    b"User-Agent: test\r\n"
                    b"Connection: close\r\n\r\n"
                )
                wrapped.sendall(req_bytes)
                data = b""
                while True:
                    chunk = wrapped.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if len(data) > 500:
                        break
                first_line = data.decode("utf-8", errors="replace").split("\n")[0]
                results.append(f"✓ HTTP raw: {first_line.strip()}")
            except Exception as e:
                results.append(f"✗ HTTP raw: {type(e).__name__}: {e}")

            try:
                wrapped.close()
            except Exception:
                pass
        except Exception as e:
            results.append(f"✗ SSL handshake: {type(e).__name__}: {e}")
            try:
                sock.close()
            except Exception:
                pass
    except Exception as e:
        results.append(f"✗ TCP: {type(e).__name__}: {e}")

    # 7. urllib.request test
    url_test = ("https://query2.finance.yahoo.com/v8/finance/chart/"
                "EURUSD=X?range=1d&interval=1h")
    try:
        req = urllib.request.Request(url_test, headers={"User-Agent": _UA})
        resp = urllib.request.urlopen(req, context=_ctx_noverify, timeout=12)
        body = resp.read(200)
        results.append(f"✓ urllib: HTTP {resp.status} ({len(body)}b)")
    except Exception as e:
        results.append(f"✗ urllib: {type(e).__name__}: {e}")

    # 8. http.client test
    try:
        conn = http.client.HTTPSConnection(
            "query2.finance.yahoo.com", timeout=12, context=_ctx_noverify)
        conn.request("GET",
                     "/v8/finance/chart/EURUSD=X?range=1d&interval=1h",
                     headers={"User-Agent": _UA})
        resp = conn.getresponse()
        body = resp.read(200)
        conn.close()
        results.append(f"✓ http.client: HTTP {resp.status} ({len(body)}b)")
    except Exception as e:
        results.append(f"✗ http.client: {type(e).__name__}: {e}")

    # 9. requests test
    try:
        import requests as _req
        resp = _req.get(url_test, headers={"User-Agent": _UA},
                        verify=False, timeout=(8, 12))
        results.append(f"✓ requests: HTTP {resp.status_code} ({len(resp.content)}b)")
    except Exception as e:
        results.append(f"✗ requests: {type(e).__name__}: {e}")

    _diag_results = results
    for r in results:
        _log.info(f"DIAG: {r}")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 1: urllib.request (stdlib, respects SSL_CERT_FILE)
# ═══════════════════════════════════════════════════════════════════════════════

_urllib_cookies: dict = {}


def _urllib_get(url: str, timeout: int = 15) -> tuple | None:
    """HTTP GET via urllib.request. Returns (status, body) or None on error."""
    try:
        headers = {
            "User-Agent": _UA,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
        }
        if _urllib_cookies:
            headers["Cookie"] = "; ".join(
                f"{k}={v}" for k, v in _urllib_cookies.items())

        req = urllib.request.Request(url, headers=headers)

        # Try with certifi context first, then noverify
        ctx = _ctx_certifi if _ctx_certifi else _ctx_noverify
        try:
            resp = urllib.request.urlopen(req, context=ctx, timeout=timeout)
        except ssl.SSLError:
            if ctx is not _ctx_noverify:
                resp = urllib.request.urlopen(
                    req, context=_ctx_noverify, timeout=timeout)
            else:
                raise
        except urllib.error.HTTPError as he:
            # urllib raises HTTPError for non-2xx — still a valid response
            _log.info(f"urllib HTTP {he.code} for {url[:60]}")
            body = he.read().decode("utf-8", errors="replace")
            return he.code, body

        # Store cookies from response
        for header in resp.headers.get_all("Set-Cookie") or []:
            part = header.split(";")[0].strip()
            if "=" in part:
                n, v = part.split("=", 1)
                _urllib_cookies[n.strip()] = v.strip()

        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, body
    except urllib.error.HTTPError as he:
        _log.info(f"urllib HTTP {he.code} for {url[:60]}")
        try:
            body = he.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return he.code, body
    except Exception as e:
        _log.warning(f"urllib error: {type(e).__name__}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 2: http.client (stdlib, different SSL code path)
# ═══════════════════════════════════════════════════════════════════════════════

_hc_cookies: dict = {}


def _hc_get(url: str, timeout: int = 15) -> tuple | None:
    """HTTP GET via http.client. Returns (status, body) or None."""
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    conn = None
    for _ in range(5):  # max redirects
        try:
            conn = http.client.HTTPSConnection(
                host, timeout=timeout, context=_ctx_noverify)
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
                conn = None
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
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            _log.warning(f"http.client error: {type(e).__name__}: {e}")
            return None
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKEND 3: requests.Session (third-party, best cookie handling)
# ═══════════════════════════════════════════════════════════════════════════════

_session = None
_requests_ok = None


def _get_session():
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


def _requests_get(url: str, timeout: int = 15) -> tuple | None:
    s = _get_session()
    if s is None:
        return None
    try:
        resp = s.get(url, timeout=(min(timeout, 8), timeout),
                     allow_redirects=True)
        return resp.status_code, resp.text
    except Exception as e:
        _log.warning(f"requests error: {type(e).__name__}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  UNIFIED GET — single backend with 429 retry
# ═══════════════════════════════════════════════════════════════════════════════

_last_errors: list[str] = []    # last per-request errors for diagnostics
_preferred_backend: str = "hc"  # start with http.client (proven on Android)


def _get(url: str, timeout: int = 15) -> tuple:
    """
    HTTP GET using ONE backend only (avoids tripling requests that cause 429).
    Falls back to other backends only on connection failure (not on HTTP errors).
    Retries on 429 with exponential backoff.
    Returns (status_code, body_text).
    """
    global _last_errors, _preferred_backend

    # Order backends: preferred first, then alternatives
    backends = [("hc", _hc_get), ("urllib", _urllib_get), ("requests", _requests_get)]
    if _preferred_backend == "urllib":
        backends = [("urllib", _urllib_get), ("hc", _hc_get), ("requests", _requests_get)]
    elif _preferred_backend == "requests":
        backends = [("requests", _requests_get), ("hc", _hc_get), ("urllib", _urllib_get)]

    for name, getter in backends:
        result = getter(url, timeout)
        if result is None:
            # Connection-level failure → try next backend
            _log.info(f"  {name} connection failed, trying next...")
            continue

        st, body = result
        if 200 <= st < 400:
            _preferred_backend = name  # remember what works
            return st, body

        if st == 429:
            # Rate limited — DON'T try other backends (they'll get 429 too)
            # Instead, wait and retry with the same backend
            for wait in (2, 5, 10):
                _log.info(f"  429 rate limited, waiting {wait}s...")
                time.sleep(wait)
                result = getter(url, timeout)
                if result is not None:
                    st2, body2 = result
                    if st2 == 200:
                        _preferred_backend = name
                        return st2, body2
                    if st2 != 429:
                        return st2, body2
            # Still 429 after retries
            _last_errors = [f"{name}:429_after_retries"]
            return st, body

        # Other HTTP error (401, 403, etc.) — return it
        _last_errors = [f"{name}:{st}"]
        return st, body

    _last_errors = ["all_backends_connection_failed"]
    _log.error(f"ALL BACKENDS FAILED to connect: {url[:80]}")
    return -1, "All backends failed to connect"


# ═══════════════════════════════════════════════════════════════════════════════
#  NETWORK PROBE
# ═══════════════════════════════════════════════════════════════════════════════

_probe_results = ""


def _deep_network_probe() -> str:
    global _probe_results
    results = []

    try:
        addrs = socket.getaddrinfo("query2.finance.yahoo.com", 443,
                                   type=socket.SOCK_STREAM)
        results.append(f"DNS:OK({len(addrs)})")
    except Exception as e:
        results.append(f"DNS:FAIL({type(e).__name__})")

    try:
        st, body = _get(
            "https://query2.finance.yahoo.com/v8/finance/chart/EURUSD=X"
            "?range=1d&interval=1h", timeout=10)
        results.append(f"Yahoo:{st}({len(body)}b)")
    except Exception as e:
        results.append(f"Yahoo:FAIL({type(e).__name__})")

    _probe_results = " | ".join(results)
    _log.info(f"PROBE: {_probe_results}")
    return _probe_results


# ═══════════════════════════════════════════════════════════════════════════════
#  YAHOO SESSION (crumb)
# ═══════════════════════════════════════════════════════════════════════════════

_crumb = None
_crumb_ts = 0.0


def _init_yahoo_session() -> str | None:
    global _crumb, _crumb_ts
    if _crumb and time.time() < _crumb_ts:
        return _crumb

    _log.info("Getting Yahoo crumb...")

    # Touch fc.yahoo.com for cookies (single request)
    try:
        _hc_get("https://fc.yahoo.com/", timeout=6)
    except Exception:
        pass
    time.sleep(0.3)

    # Get crumb (single host only — avoid extra requests)
    try:
        st, body = _hc_get("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=8)
        if st is not None:
            body_str = body.strip() if body else ""
            _log.info(f"  crumb: {st}, '{body_str[:30]}'")
            if st == 200 and body_str and len(body_str) < 50 and "<" not in body_str:
                _crumb = body_str
                _crumb_ts = time.time() + 3600  # cache 1 hour
                return _crumb
    except Exception as exc:
        _log.warning(f"  crumb: {exc}")

    _log.warning("No crumb — will proceed without")
    _crumb = None
    _crumb_ts = time.time() + 300  # retry after 5 min
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

# Use ONLY query2 — trying both hosts doubles requests and triggers 429
_HOSTS = ("query2.finance.yahoo.com",)


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
    """Fetch OHLCV from Yahoo chart API. Single request with 429 retry."""
    crumb = _init_yahoo_session()
    host = _HOSTS[0]

    url = (f"https://{host}/v8/finance/chart/{symbol}"
           f"?range={period}&interval={interval}&includePrePost=false")
    if crumb:
        url += f"&crumb={crumb}"

    try:
        st, body = _get(url, timeout=15)
        _log.info(f"  {symbol}: {st} ({len(body)}b)")
        if st == 200 and body:
            df = _parse_chart_json(body, symbol)
            if not df.empty:
                return df
        elif st in (401, 403):
            _log.warning(f"  {symbol}: {st} → reset crumb & retry")
            _reset_crumb()
            crumb = _init_yahoo_session()
            # Retry once with new crumb
            url2 = (f"https://{host}/v8/finance/chart/{symbol}"
                    f"?range={period}&interval={interval}&includePrePost=false")
            if crumb:
                url2 += f"&crumb={crumb}"
            time.sleep(0.5)
            st2, body2 = _get(url2, timeout=15)
            if st2 == 200 and body2:
                df = _parse_chart_json(body2, symbol)
                if not df.empty:
                    return df
        elif st == 429:
            # _get already retried 429 internally, so this means truly blocked
            _log.warning(f"  {symbol}: still 429 after retries")
        else:
            _log.warning(f"  {symbol}: HTTP {st}")
    except json.JSONDecodeError:
        _log.warning(f"  {symbol}: invalid JSON")
    except Exception as exc:
        _log.error(f"  {symbol}: {type(exc).__name__}: {exc}")

    _log.warning(f"  {symbol}: FAILED")
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
_MAX_CONSEC_FAIL = 10  # tolerant: with 429 retries, early pairs may fail


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

        if _consecutive_fail >= _MAX_CONSEC_FAIL and not results:
            _log.error(
                f"ABORT: {_consecutive_fail} consecutive failures, 0 success")
            if progress_callback:
                progress_callback(i + 1, total,
                    f"Abort: {_consecutive_fail} fallimenti consecutivi")
            break

        # IMPORTANT: 0.5s delay between pairs to avoid Yahoo 429 rate limit
        time.sleep(0.5)
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
        # 0.5s delay between futures to avoid Yahoo 429 rate limit
        time.sleep(0.5)
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
