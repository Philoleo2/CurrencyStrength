"""
Asset Strength Indicator – COT Data
=====================================
Scarica e analizza il report COT (Commitments of Traders) della CFTC
per commodity, indici e crypto: Gold, Silver, Wheat, Nasdaq, S&P 500, Bitcoin.

Per DAX non esiste un report COT standard CFTC (indice europeo Eurex),
quindi viene restituito un punteggio neutro (50).
"""

import io
import os
import zipfile
import datetime as dt
import requests
import pandas as pd
import numpy as np

from config import (
    ASSETS, ASSET_COT_KEYWORDS,
    COT_BASE_URL, COT_HIST_URL,
    COT_PERCENTILE_LOOKBACK, COT_EXTREME_LONG, COT_EXTREME_SHORT,
    CACHE_DIR, ASSET_COT_CACHE_FILE,
)


def _ensure_cache():
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cot_cache_path() -> str:
    _ensure_cache()
    return os.path.join(CACHE_DIR, ASSET_COT_CACHE_FILE)


def _find_column(df: pd.DataFrame, patterns: list[str]) -> str | None:
    cols_lower = {c.lower().strip(): c for c in df.columns}
    for pat in patterns:
        for cl, original in cols_lower.items():
            if pat.lower() in cl:
                return original
    return None


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip() for c in df.columns]
    return df


# Nomi colonne standard del report Legacy Futures-Only CFTC
_COT_COLUMN_NAMES = [
    "Market and Exchange Names","As of Date in Form YYMMDD",
    "As of Date in Form YYYY-MM-DD","CFTC Contract Market Code",
    "CFTC Market Code in Initials","CFTC Region Code","CFTC Commodity Code",
    "Open Interest (All)","Noncommercial Positions-Long (All)",
    "Noncommercial Positions-Short (All)","Noncommercial Positions-Spreading (All)",
    "Commercial Positions-Long (All)","Commercial Positions-Short (All)",
    "Total Reportable Positions-Long (All)","Total Reportable Positions-Short (All)",
    "Nonreportable Positions-Long (All)","Nonreportable Positions-Short (All)",
    "Open Interest (Old)","Noncommercial Positions-Long (Old)",
    "Noncommercial Positions-Short (Old)","Noncommercial Positions-Spreading (Old)",
    "Commercial Positions-Long (Old)","Commercial Positions-Short (Old)",
    "Total Reportable Positions-Long (Old)","Total Reportable Positions-Short (Old)",
    "Nonreportable Positions-Long (Old)","Nonreportable Positions-Short (Old)",
    "Open Interest (Other)","Noncommercial Positions-Long (Other)",
    "Noncommercial Positions-Short (Other)","Noncommercial Positions-Spreading (Other)",
    "Commercial Positions-Long (Other)","Commercial Positions-Short (Other)",
    "Total Reportable Positions-Long (Other)","Total Reportable Positions-Short (Other)",
    "Nonreportable Positions-Long (Other)","Nonreportable Positions-Short (Other)",
    "Change in Open Interest (All)","Change in Noncommercial-Long (All)",
    "Change in Noncommercial-Short (All)","Change in Noncommercial-Spreading (All)",
    "Change in Commercial-Long (All)","Change in Commercial-Short (All)",
    "Change in Total Reportable-Long (All)","Change in Total Reportable-Short (All)",
    "Change in Nonreportable-Long (All)","Change in Nonreportable-Short (All)",
]


def _has_header(text: str) -> bool:
    """Controlla se la prima riga contiene intestazioni note."""
    first_line = text.split("\n", 1)[0].lower()
    return "market and exchange names" in first_line


def _download_current_cot() -> pd.DataFrame:
    try:
        resp = requests.get(COT_BASE_URL, timeout=30)
        resp.raise_for_status()
        if _has_header(resp.text):
            df = pd.read_csv(io.StringIO(resp.text), low_memory=False)
        else:
            df = pd.read_csv(io.StringIO(resp.text), header=None, low_memory=False)
            if len(df.columns) >= len(_COT_COLUMN_NAMES):
                df.columns = _COT_COLUMN_NAMES + [
                    f"col_{i}" for i in range(len(_COT_COLUMN_NAMES), len(df.columns))
                ]
            else:
                df.columns = _COT_COLUMN_NAMES[:len(df.columns)]
        return df
    except Exception as e:
        print(f"[WARN] Impossibile scaricare COT corrente per asset: {e}")
        return pd.DataFrame()


def _download_historical_cot(year: int) -> pd.DataFrame:
    url = COT_HIST_URL.format(year=year)
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            names = zf.namelist()
            csv_name = [n for n in names if n.endswith(".txt") or n.endswith(".csv")]
            if not csv_name:
                return pd.DataFrame()
            with zf.open(csv_name[0]) as f:
                return pd.read_csv(f, low_memory=False)
    except Exception as e:
        print(f"[WARN] Impossibile scaricare COT storico {year} per asset: {e}")
        return pd.DataFrame()


def _extract_asset_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra il DataFrame COT per le sole righe relative agli asset monitorati."""
    name_col = _find_column(df, ["market_and_exchange_names", "market and exchange names",
                                  "Market_and_Exchange_Names"])
    if name_col is None:
        name_col = df.columns[0]

    rows = []
    for asset, keyword in ASSET_COT_KEYWORDS.items():
        if keyword is None:
            continue
        mask = df[name_col].astype(str).str.contains(keyword, case=False, na=False)
        subset = df[mask].copy()
        subset["asset"] = asset
        rows.append(subset)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _parse_cot_fields(df: pd.DataFrame) -> pd.DataFrame:
    """Estrae campi chiave dal report COT Legacy Futures-Only."""
    date_col = _find_column(df, ["as_of_date_in_form_yyyy-mm-dd",
                                  "as of date in form yyyy-mm-dd",
                                  "As_of_Date_In_Form_YYYY-MM-DD",
                                  "report_date_as_yyyy-mm-dd"])
    oi_col   = _find_column(df, ["open_interest_all", "Open_Interest_All"])
    nl_col   = _find_column(df, ["noncomm_positions_long_all",
                                  "NonComm_Positions_Long_All",
                                  "noncommercial positions-long (all)",
                                  "non-commercial positions-long (all)"])
    ns_col   = _find_column(df, ["noncomm_positions_short_all",
                                  "NonComm_Positions_Short_All",
                                  "noncommercial positions-short (all)",
                                  "non-commercial positions-short (all)"])
    cl_col   = _find_column(df, ["comm_positions_long_all",
                                  "Comm_Positions_Long_All",
                                  "commercial positions-long (all)"])
    cs_col   = _find_column(df, ["comm_positions_short_all",
                                  "Comm_Positions_Short_All",
                                  "commercial positions-short (all)"])
    cnl_col  = _find_column(df, ["change_in_noncomm_long_all",
                                  "Change_in_NonComm_Long_All",
                                  "change in noncommercial-long (all)"])
    cns_col  = _find_column(df, ["change_in_noncomm_short_all",
                                  "Change_in_NonComm_Short_All",
                                  "change in noncommercial-short (all)"])

    result = pd.DataFrame()
    result["asset"] = df["asset"]

    if date_col:
        result["date"] = pd.to_datetime(df[date_col], errors="coerce")
    else:
        result["date"] = pd.NaT

    def _safe_num(col_name):
        if col_name and col_name in df.columns:
            return pd.to_numeric(df[col_name].astype(str).str.replace(",", ""),
                                 errors="coerce")
        return 0

    result["open_interest"]  = _safe_num(oi_col)
    result["noncomm_long"]   = _safe_num(nl_col)
    result["noncomm_short"]  = _safe_num(ns_col)
    result["comm_long"]      = _safe_num(cl_col)
    result["comm_short"]     = _safe_num(cs_col)
    result["chg_noncomm_long"]  = _safe_num(cnl_col)
    result["chg_noncomm_short"] = _safe_num(cns_col)

    result["net_speculative"] = result["noncomm_long"] - result["noncomm_short"]
    result["net_commercial"]  = result["comm_long"] - result["comm_short"]
    result["chg_net_spec"]    = result["chg_noncomm_long"] - result["chg_noncomm_short"]

    result = result.dropna(subset=["date"]).sort_values(["asset", "date"])
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# API PUBBLICA
# ═══════════════════════════════════════════════════════════════════════════════

def load_asset_cot_data(use_cache: bool = True,
                        max_cache_age_hours: int = 24) -> pd.DataFrame:
    """
    Carica dati COT per gli asset. Tenta cache, poi scarica da CFTC.
    """
    cache_p = _cot_cache_path()

    if use_cache and os.path.exists(cache_p):
        age_h = (dt.datetime.now().timestamp() - os.path.getmtime(cache_p)) / 3600
        if age_h < max_cache_age_hours:
            try:
                return pd.read_csv(cache_p, parse_dates=["date"])
            except Exception:
                pass

    current_year = dt.datetime.now().year
    frames = []

    hist = _download_historical_cot(current_year - 1)
    if not hist.empty:
        hist = _normalize_columns(hist)
        hist = _extract_asset_rows(hist)
        if not hist.empty:
            frames.append(_parse_cot_fields(hist))

    hist_cur = _download_historical_cot(current_year)
    if not hist_cur.empty:
        hist_cur = _normalize_columns(hist_cur)
        hist_cur = _extract_asset_rows(hist_cur)
        if not hist_cur.empty:
            frames.append(_parse_cot_fields(hist_cur))

    cur = _download_current_cot()
    if not cur.empty:
        cur = _normalize_columns(cur)
        cur = _extract_asset_rows(cur)
        if not cur.empty:
            frames.append(_parse_cot_fields(cur))

    if not frames:
        print("[WARN] Nessun dato COT asset disponibile. Dati neutri.")
        return _generate_neutral_cot()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["asset", "date"]).sort_values(
        ["asset", "date"]
    )

    try:
        combined.to_csv(cache_p, index=False)
    except Exception:
        pass

    return combined


def _generate_neutral_cot() -> pd.DataFrame:
    rows = []
    today = dt.datetime.now()
    for asset in ASSETS:
        rows.append({
            "date": today, "asset": asset,
            "open_interest": 0, "noncomm_long": 0, "noncomm_short": 0,
            "comm_long": 0, "comm_short": 0,
            "net_speculative": 0, "net_commercial": 0, "chg_net_spec": 0,
            "chg_noncomm_long": 0, "chg_noncomm_short": 0,
        })
    return pd.DataFrame(rows)


def _pct_rank(value: float, array: np.ndarray) -> float:
    """Percentile rank di value rispetto ad array (0-100)."""
    if len(array) == 0:
        return 50.0
    return float(np.sum(array <= value) / len(array)) * 100


def compute_asset_cot_scores(cot_df: pd.DataFrame) -> dict[str, dict]:
    """
    MULTI_VAR scoring per asset: score basato su percentile della variazione
    a finestre multiple (1w, 2w, 4w) della posizione netta speculativa.

    Formula:  score = 50% × pct_rank(Δ1w) + 30% × pct_rank(Δ2w) + 20% × pct_rank(Δ4w)

    Per Bitcoin e DAX (senza COT) → score neutro 50.
    """
    scores = {}
    lb = COT_PERCENTILE_LOOKBACK

    for asset in ASSETS:
        if ASSET_COT_KEYWORDS.get(asset) is None:
            scores[asset] = {
                "net_spec_percentile": 50.0,
                "weekly_change": 0.0,
                "score": 50.0,
                "extreme": None,
                "bias": "NEUTRAL",
                "freshness_days": 0,
            }
            continue

        subset = cot_df[cot_df["asset"] == asset].sort_values("date")

        if subset.empty:
            scores[asset] = {
                "net_spec_percentile": 50.0,
                "weekly_change": 0.0,
                "score": 50.0,
                "extreme": None,
                "bias": "NEUTRAL",
                "freshness_days": 999,
            }
            continue

        ns = subset["net_speculative"].values

        # Percentile livello (per info e extremes)
        latest = ns[-1]
        lookback = ns[-lb:] if len(ns) >= lb else ns
        level_pct = _pct_rank(latest, lookback)

        # Freshness
        latest_date = subset["date"].max()
        if pd.notna(latest_date):
            freshness_days = (dt.datetime.now() - pd.Timestamp(latest_date).to_pydatetime().replace(tzinfo=None)).days
        else:
            freshness_days = 999

        wk_change = float(ns[-1] - ns[-2]) if len(ns) >= 2 else 0.0

        # ── MULTI_VAR scoring ──
        d1 = np.diff(ns)
        d2 = ns[2:] - ns[:-2]
        d4 = ns[4:] - ns[:-4]

        p1 = _pct_rank(d1[-1], d1[-min(lb, len(d1)):]) if len(d1) >= 2 else 50.0
        p2 = _pct_rank(d2[-1], d2[-min(lb, len(d2)):]) if len(d2) >= 2 else 50.0
        p4 = _pct_rank(d4[-1], d4[-min(lb, len(d4)):]) if len(d4) >= 2 else 50.0

        score = float(np.clip(0.50 * p1 + 0.30 * p2 + 0.20 * p4, 0, 100))

        extreme = None
        if level_pct >= COT_EXTREME_LONG:
            extreme = "CROWDED_LONG"
        elif level_pct <= COT_EXTREME_SHORT:
            extreme = "CROWDED_SHORT"

        if score >= 60:
            bias = "BULLISH"
        elif score <= 40:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        scores[asset] = {
            "net_spec_percentile": round(level_pct, 1),
            "weekly_change": round(wk_change, 0),
            "score": round(score, 1),
            "extreme": extreme,
            "bias": bias,
            "freshness_days": freshness_days,
        }

    return scores


def get_asset_cot_timeseries(cot_df: pd.DataFrame) -> pd.DataFrame:
    """Timeseries del net speculative per ogni asset."""
    if cot_df.empty or "asset" not in cot_df.columns:
        return pd.DataFrame()
    pivot = cot_df.pivot_table(
        index="date", columns="asset", values="net_speculative", aggfunc="last"
    )
    return pivot.sort_index()
