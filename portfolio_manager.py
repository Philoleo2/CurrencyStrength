"""
Portfolio Manager — Gestione posizioni e calcolo metriche
=========================================================
Modulo backend per il portafoglio di investimento.
Gestisce: persistenza posizioni, fetch prezzi live, calcolo P&L,
esposizione, deviazione pesi, equity curve.
"""

import datetime as dt
import json
import os
import logging
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from config import (
    PORTFOLIO_FILE,
    PORTFOLIO_CURRENCY,
    PORTFOLIO_CAPITAL,
    PORTFOLIO_POSITIONS,
    PORTFOLIO_FX_TICKERS,
    REBALANCE_THRESHOLD_PCT,
)

_ROME = ZoneInfo("Europe/Rome")
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# PERSISTENZA — salvataggio/caricamento stato portafoglio
# ═══════════════════════════════════════════════════════════════════════════════

def _portfolio_path() -> str:
    os.makedirs(os.path.dirname(PORTFOLIO_FILE) or ".", exist_ok=True)
    return PORTFOLIO_FILE


def load_portfolio() -> dict:
    """
    Carica il portafoglio da disco.
    Se non esiste, inizializza con le posizioni di default da config.
    
    Struttura:
    {
      "capital": 1000.0,
      "currency": "EUR",
      "positions": [ {ticker, name, asset_class, region, target_weight,
                       entry_price, entry_date, quantity, sl, tp, notes, ...} ],
      "closed": [ ... ],
      "snapshots": [ {date, total_value, ...} ]
    }
    """
    path = _portfolio_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Errore caricamento portfolio: {e}")

    # Prima volta: inizializza da config
    return _init_portfolio()


def save_portfolio(portfolio: dict) -> None:
    """Salva il portafoglio su disco."""
    try:
        portfolio["last_updated"] = dt.datetime.now(_ROME).isoformat()
        with open(_portfolio_path(), "w", encoding="utf-8") as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"Errore salvataggio portfolio: {e}")


def _init_portfolio() -> dict:
    """Crea il portafoglio iniziale dalle posizioni target in config."""
    positions = []
    cash_weight = 1.0 - sum(p["target_weight"] for p in PORTFOLIO_POSITIONS)

    for pos_cfg in PORTFOLIO_POSITIONS:
        positions.append({
            "ticker": pos_cfg["ticker"],
            "name": pos_cfg["name"],
            "asset_class": pos_cfg["asset_class"],
            "region": pos_cfg["region"],
            "currency": pos_cfg.get("currency", "USD"),
            "target_weight": pos_cfg["target_weight"],
            "rationale": pos_cfg.get("rationale", ""),
            "entry_price": None,      # da compilare al primo acquisto
            "entry_price_eur": None,   # prezzo in EUR al momento dell'entrata
            "entry_date": None,
            "quantity": 0.0,
            "sl": None,
            "tp": None,
            "notes": "",
            "direction": "LONG",
        })

    portfolio = {
        "capital": PORTFOLIO_CAPITAL,
        "currency": PORTFOLIO_CURRENCY,
        "cash_target_weight": round(cash_weight, 4),
        "positions": positions,
        "closed": [],
        "snapshots": [],
        "created": dt.datetime.now(_ROME).isoformat(),
    }

    save_portfolio(portfolio)
    return portfolio


# ═══════════════════════════════════════════════════════════════════════════════
# FETCH PREZZI LIVE
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_live_prices(tickers: list[str]) -> dict[str, dict]:
    """
    Scarica ultimo prezzo per ogni ticker.
    Restituisce {ticker: {"price": float, "change_pct": float, "prev_close": float}}.
    La valuta di quotazione è definita nel campo 'currency' di ogni posizione in config,
    così evitiamo la chiamata lenta e inaffidabile a yfinance .info.
    """
    results = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            if hist.empty:
                continue
            last_price = hist["Close"].iloc[-1]
            prev_price = hist["Close"].iloc[-2] if len(hist) >= 2 else last_price
            change_pct = ((last_price - prev_price) / prev_price) * 100

            results[ticker] = {
                "price": last_price,
                "change_pct": change_pct,
                "prev_close": prev_price,
            }
        except Exception as e:
            logger.warning(f"Errore fetch prezzo {ticker}: {e}")
    return results


def fetch_fx_rates() -> dict[str, float]:
    """
    Scarica i tassi di cambio per convertire in EUR.
    Restituisce {currency_code: rate} dove rate = 1 EUR in quella valuta.
    Es: {"USD": 1.18, "GBP": 0.86, "GBp": 86.0}
    """
    rates = {"EUR": 1.0}
    for ccy, fx_ticker in PORTFOLIO_FX_TICKERS.items():
        try:
            t = yf.Ticker(fx_ticker)
            hist = t.history(period="5d")
            if not hist.empty:
                rate = hist["Close"].iloc[-1]
                rates[ccy] = rate
        except Exception as e:
            logger.warning(f"Errore fetch FX {ccy}: {e}")
    return rates


def convert_to_eur(price: float, currency: str, fx_rates: dict) -> float:
    """Converte un prezzo nella valuta indicata in EUR.
    rate = quante unità di `currency` vale 1 EUR.
    Es: EURUSD=1.08 → prezzo_eur = prezzo_usd / 1.08
    """
    if currency == "EUR":
        return price
    rate = fx_rates.get(currency, 1.0)
    if rate == 0:
        return price
    return price / rate


# ═══════════════════════════════════════════════════════════════════════════════
# CALCOLO METRICHE PORTAFOGLIO
# ═══════════════════════════════════════════════════════════════════════════════

def compute_portfolio_metrics(portfolio: dict) -> dict:
    """
    Calcola tutte le metriche del portafoglio:
    - Valore totale, P&L per posizione e totale
    - Peso reale vs target, deviazioni
    - Esposizione per asset class e regione
    - Risk / Reward per posizione
    
    Restituisce un dict dettagliato pronto per la dashboard.
    """
    positions = portfolio["positions"]
    capital = portfolio["capital"]
    cash_target = portfolio.get("cash_target_weight", 0.10)

    # Tutti i ticker nel portafoglio (anche senza posizioni aperte, per mostrare prezzi)
    active_tickers = list({p["ticker"] for p in positions})
    
    # Fetch prezzi e FX
    prices = fetch_live_prices(active_tickers)
    fx_rates = fetch_fx_rates()

    # Calcolo per posizione
    pos_metrics = []
    total_invested = 0.0
    total_current = 0.0
    total_pnl = 0.0

    for pos in positions:
        ticker = pos["ticker"]
        qty = pos.get("quantity", 0) or 0
        entry_price = pos.get("entry_price")
        entry_price_eur = pos.get("entry_price_eur")
        
        live = prices.get(ticker, {})
        current_price = live.get("price", 0)
        # Valuta dalla configurazione posizione (non da yfinance .info)
        ccy = pos.get("currency", "USD")
        change_pct = live.get("change_pct", 0)

        # Fallback: se il prezzo live non è disponibile, usa il prezzo di entrata
        if current_price == 0 and entry_price_eur and qty:
            current_price_eur = entry_price_eur
        else:
            # Prezzo in EUR dal prezzo live
            current_price_eur = convert_to_eur(current_price, ccy, fx_rates)

        # Valore posizione
        current_value_eur = current_price_eur * qty if qty else 0
        
        # P&L
        if entry_price_eur and qty:
            invested_eur = entry_price_eur * qty
            pnl_eur = current_value_eur - invested_eur
            pnl_pct = (pnl_eur / invested_eur * 100) if invested_eur else 0
        elif entry_price and qty:
            # Fallback: usa entry_price nella valuta originale
            entry_eur = convert_to_eur(entry_price, ccy, fx_rates)
            invested_eur = entry_eur * qty
            pnl_eur = current_value_eur - invested_eur
            pnl_pct = (pnl_eur / invested_eur * 100) if invested_eur else 0
        else:
            invested_eur = 0
            pnl_eur = 0
            pnl_pct = 0

        # SL / TP in EUR
        sl = pos.get("sl")
        tp = pos.get("tp")
        sl_eur = convert_to_eur(sl, ccy, fx_rates) if sl else None
        tp_eur = convert_to_eur(tp, ccy, fx_rates) if tp else None

        # Risk/Reward
        risk_eur = abs(current_price_eur - sl_eur) * qty if sl_eur and qty else None
        reward_eur = abs(tp_eur - current_price_eur) * qty if tp_eur and qty else None
        rr_ratio = (reward_eur / risk_eur) if risk_eur and reward_eur and risk_eur > 0 else None

        # Distanza da SL
        sl_distance_pct = None
        if sl and current_price and current_price > 0:
            if pos.get("direction", "LONG") == "LONG":
                sl_distance_pct = ((current_price - sl) / current_price) * 100
            else:
                sl_distance_pct = ((sl - current_price) / current_price) * 100

        total_invested += invested_eur
        total_current += current_value_eur
        total_pnl += pnl_eur

        pos_metrics.append({
            "ticker": ticker,
            "name": pos["name"],
            "asset_class": pos["asset_class"],
            "region": pos["region"],
            "direction": pos.get("direction", "LONG"),
            "target_weight": pos["target_weight"],
            "quantity": qty,
            "entry_price": entry_price,
            "entry_price_eur": entry_price_eur,
            "entry_date": pos.get("entry_date"),
            "current_price": current_price,
            "current_price_eur": current_price_eur,
            "currency": ccy,
            "change_pct": change_pct,
            "current_value_eur": current_value_eur,
            "invested_eur": invested_eur,
            "pnl_eur": pnl_eur,
            "pnl_pct": pnl_pct,
            "sl": sl,
            "tp": tp,
            "sl_eur": sl_eur,
            "tp_eur": tp_eur,
            "risk_eur": risk_eur,
            "reward_eur": reward_eur,
            "rr_ratio": rr_ratio,
            "sl_distance_pct": sl_distance_pct,
            "rationale": pos.get("rationale", ""),
            "notes": pos.get("notes", ""),
        })

    # Cash
    cash_eur = capital - total_invested if total_invested < capital else 0
    total_value = total_current + cash_eur

    # Pesi reali e deviazioni
    rebalance_alerts = []
    for pm in pos_metrics:
        if total_value > 0:
            pm["actual_weight"] = pm["current_value_eur"] / total_value
        else:
            pm["actual_weight"] = 0
        deviation = (pm["actual_weight"] - pm["target_weight"]) * 100
        pm["weight_deviation_pct"] = deviation
        if abs(deviation) > REBALANCE_THRESHOLD_PCT:
            direction = "sovrappeso" if deviation > 0 else "sottopeso"
            rebalance_alerts.append({
                "ticker": pm["ticker"],
                "name": pm["name"],
                "target": pm["target_weight"],
                "actual": pm["actual_weight"],
                "deviation": deviation,
                "direction": direction,
            })

    cash_actual_weight = cash_eur / total_value if total_value > 0 else 1.0
    cash_deviation = (cash_actual_weight - cash_target) * 100

    # Esposizione per asset class
    exposure_class = {}
    for pm in pos_metrics:
        ac = pm["asset_class"]
        exposure_class[ac] = exposure_class.get(ac, 0) + pm["current_value_eur"]
    exposure_class["Cash"] = cash_eur

    # Esposizione per regione
    exposure_region = {}
    for pm in pos_metrics:
        rg = pm["region"]
        exposure_region[rg] = exposure_region.get(rg, 0) + pm["current_value_eur"]

    # P&L totale
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    return {
        "positions": pos_metrics,
        "total_value": total_value,
        "total_invested": total_invested,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "cash_eur": cash_eur,
        "cash_actual_weight": cash_actual_weight,
        "cash_target_weight": cash_target,
        "cash_deviation": cash_deviation,
        "capital": capital,
        "rebalance_alerts": rebalance_alerts,
        "exposure_class": exposure_class,
        "exposure_region": exposure_region,
        "fx_rates": fx_rates,
        "prices": prices,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SNAPSHOT EQUITY CURVE
# ═══════════════════════════════════════════════════════════════════════════════

def record_snapshot(portfolio: dict, metrics: dict) -> None:
    """Registra un punto nell'equity curve (max 1 al giorno)."""
    today = dt.datetime.now(_ROME).strftime("%Y-%m-%d")
    snapshots = portfolio.get("snapshots", [])

    # Evita doppi per lo stesso giorno
    if snapshots and snapshots[-1].get("date") == today:
        snapshots[-1] = {
            "date": today,
            "total_value": round(metrics["total_value"], 2),
            "total_pnl": round(metrics["total_pnl"], 2),
            "total_pnl_pct": round(metrics["total_pnl_pct"], 2),
        }
    else:
        snapshots.append({
            "date": today,
            "total_value": round(metrics["total_value"], 2),
            "total_pnl": round(metrics["total_pnl"], 2),
            "total_pnl_pct": round(metrics["total_pnl_pct"], 2),
        })

    # Mantieni max 365 giorni
    if len(snapshots) > 365:
        snapshots = snapshots[-365:]

    portfolio["snapshots"] = snapshots


# ═══════════════════════════════════════════════════════════════════════════════
# STORICO PREZZI PER EQUITY CURVE DETTAGLIATA
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_historical_prices(tickers: list[str], period: str = "6mo") -> dict[str, pd.DataFrame]:
    """Scarica lo storico prezzi per i ticker indicati."""
    results = {}
    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period)
            if not hist.empty:
                results[ticker] = hist
        except Exception as e:
            logger.warning(f"Errore fetch storico {ticker}: {e}")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# GESTIONE POSIZIONI — apertura, modifica, chiusura
# ═══════════════════════════════════════════════════════════════════════════════

def open_position(portfolio: dict, ticker: str, entry_price: float,
                  entry_price_eur: float, quantity: float,
                  entry_date: str, sl: float | None = None,
                  tp: float | None = None, notes: str = "") -> bool:
    """Imposta prezzo/quantità per una posizione esistente nel portafoglio."""
    for pos in portfolio["positions"]:
        if pos["ticker"] == ticker:
            pos["entry_price"] = entry_price
            pos["entry_price_eur"] = entry_price_eur
            pos["entry_date"] = entry_date
            pos["quantity"] = quantity
            pos["sl"] = sl
            pos["tp"] = tp
            pos["notes"] = notes
            save_portfolio(portfolio)
            return True
    return False


def close_position(portfolio: dict, ticker: str, exit_price: float,
                   exit_price_eur: float, exit_date: str) -> bool:
    """Chiude una posizione e la sposta nello storico."""
    for pos in portfolio["positions"]:
        if pos["ticker"] == ticker and pos.get("quantity", 0) > 0:
            closed = {
                **pos,
                "exit_price": exit_price,
                "exit_price_eur": exit_price_eur,
                "exit_date": exit_date,
                "pnl_eur": (exit_price_eur - (pos.get("entry_price_eur") or 0)) * pos["quantity"],
            }
            portfolio.setdefault("closed", []).append(closed)
            pos["quantity"] = 0
            pos["entry_price"] = None
            pos["entry_price_eur"] = None
            pos["entry_date"] = None
            pos["sl"] = None
            pos["tp"] = None
            save_portfolio(portfolio)
            return True
    return False


def update_sl_tp(portfolio: dict, ticker: str,
                 sl: float | None, tp: float | None) -> bool:
    """Aggiorna SL/TP di una posizione."""
    for pos in portfolio["positions"]:
        if pos["ticker"] == ticker:
            pos["sl"] = sl
            pos["tp"] = tp
            save_portfolio(portfolio)
            return True
    return False
