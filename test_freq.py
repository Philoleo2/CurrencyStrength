import yfinance as yf
import pandas as pd
from datetime import datetime

tk = yf.Ticker("6E=F")
df = tk.history(period="5d", interval="1h")
df = df[df["Volume"] > 0]

print("=== FREQUENZA AGGIORNAMENTO 6E=F (ultime 5 gg, solo barre con volume) ===")
print(f"Totale barre con volume: {len(df)}")
print(f"Prima barra: {df.index[0]}")
print(f"Ultima barra: {df.index[-1]}")
print(f"Ora attuale:  {datetime.now()}")
print()

gaps = df.index.to_series().diff().dropna()
print(f"Gap medio tra barre:    {gaps.mean()}")
print(f"Gap massimo tra barre:  {gaps.max()}")
print(f"Gap minimo tra barre:   {gaps.min()}")
print()

print("=== ULTIME 20 BARRE H1 ===")
for ts, row in df.tail(20).iterrows():
    vol = int(row["Volume"])
    print(f"  {ts}  Vol: {vol:>10,}")

print()
h4 = df["Volume"].resample("4h").sum()
h4 = h4[h4 > 0]
print("=== BARRE H4 (volume aggregato) ===")
for ts, v in h4.tail(10).items():
    print(f"  {ts}  Vol H4: {int(v):>10,}")

print()
print("=== ORARI DI TRADING CME (quando ci sono dati) ===")
hours = df.index.hour
from collections import Counter
c = Counter(hours)
for h in sorted(c.keys()):
    print(f"  Ora {h:02d}:00 -> {c[h]} barre nei 5 gg")
