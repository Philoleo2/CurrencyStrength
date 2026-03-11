"""Test volumi Yahoo Finance - Forex Spot vs CME Futures"""
import yfinance as yf
import pandas as pd

print("=" * 70)
print("TEST VOLUMI YAHOO FINANCE - FOREX vs FUTURES CME")
print("=" * 70)

# 1. Test FOREX spot (tick volume)
print("\n--- FOREX SPOT (=X tickers) ---")
forex_pairs = {"EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY",
               "AUDUSD=X": "AUD/USD", "USDCAD=X": "USD/CAD"}
for tk, name in forex_pairs.items():
    try:
        data = yf.Ticker(tk).history(period="5d", interval="1h")
        if "Volume" in data.columns:
            vol = data["Volume"]
            non_zero = (vol > 0).sum()
            total = len(vol)
            pct = non_zero / total * 100 if total > 0 else 0
            print(f"  {name:10s} | Barre: {total:4d} | Vol>0: {non_zero:4d} ({pct:.0f}%) | Ultimo: {vol.iloc[-1]:>12,.0f} | Media: {vol.mean():>12,.0f}")
        else:
            print(f"  {name:10s} | NESSUNA colonna Volume")
    except Exception as e:
        print(f"  {name:10s} | ERRORE: {e}")

# 2. Test FUTURES CME (volume reale)
print("\n--- FUTURES CME (volume reale regolamentato) ---")
futures = {"6E=F": "EUR Fut", "6B=F": "GBP Fut", "6J=F": "JPY Fut",
           "6A=F": "AUD Fut", "6C=F": "CAD Fut", "6S=F": "CHF Fut",
           "6N=F": "NZD Fut", "DX=F": "DXY Fut"}
for tk, name in futures.items():
    try:
        data = yf.Ticker(tk).history(period="5d", interval="1h")
        if "Volume" in data.columns:
            vol = data["Volume"]
            non_zero = (vol > 0).sum()
            total = len(vol)
            pct = non_zero / total * 100 if total > 0 else 0
            print(f"  {name:10s} | Barre: {total:4d} | Vol>0: {non_zero:4d} ({pct:.0f}%) | Ultimo: {vol.iloc[-1]:>12,.0f} | Media: {vol.mean():>12,.0f}")
        else:
            print(f"  {name:10s} | NESSUNA colonna Volume")
    except Exception as e:
        print(f"  {name:10s} | ERRORE: {e}")

# 3. Confronto dettagliato
print("\n--- CONFRONTO: EURUSD=X vs 6E=F (ultime 10 barre) ---")
try:
    fx = yf.Ticker("EURUSD=X").history(period="5d", interval="1h")
    ft = yf.Ticker("6E=F").history(period="5d", interval="1h")

    fx_vol = fx["Volume"]
    ft_vol = ft["Volume"]

    print(f"  EURUSD=X  volumi unici: {fx_vol.nunique():5d} | tutti zero? {(fx_vol == 0).all()}")
    print(f"  6E=F      volumi unici: {ft_vol.nunique():5d} | tutti zero? {(ft_vol == 0).all()}")

    print("\n  Ultime 10 barre EURUSD=X:")
    for idx, row in fx.tail(10).iterrows():
        print(f"    {idx}  Vol: {row['Volume']:>12,.0f}")

    print("\n  Ultime 10 barre 6E=F:")
    for idx, row in ft.tail(10).iterrows():
        print(f"    {idx}  Vol: {row['Volume']:>12,.0f}")
except Exception as e:
    print(f"  ERRORE: {e}")

print("\n" + "=" * 70)
print("CONCLUSIONE")
print("=" * 70)
