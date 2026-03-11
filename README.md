# 💱 Currency Strength Indicator

Dashboard interattiva in Python per analizzare la **forza relativa delle valute** (USD, EUR, GBP, JPY, CHF, AUD, NZD, CAD) combinando **price action**, **volumi** e **dati COT**.

---

## 🚀 Quick Start

```powershell
cd C:\CurrencyStrength
pip install -r requirements.txt
streamlit run app.py
```

La dashboard si aprirà nel browser all'indirizzo `http://localhost:8501`.

---

## 📐 Architettura

```
CurrencyStrength/
├── app.py                 # Dashboard Streamlit (entry point)
├── config.py              # Configurazione, soglie, pesi, tickers
├── data_fetcher.py        # Download prezzi forex + volumi futures CME
├── cot_data.py            # Download e parsing report COT (CFTC)
├── strength_engine.py     # Motore di calcolo (score, classificazione, momentum)
├── requirements.txt       # Dipendenze Python
├── README.md              # Questa documentazione
└── cache/                 # Cache locale dati (creata automaticamente)
```

---

## 📊 Come Funziona

### Score Composito (0-100)

Ogni valuta riceve un punteggio da 0 (estremamente debole) a 100 (estremamente forte), calcolato come media ponderata di tre componenti:

| Componente | Peso | Fonte Dati | Cosa Misura |
|------------|------|------------|-------------|
| **Price Action** | 40% | Yahoo Finance (forex) | RSI, ROC multi-periodo, posizione vs EMA 20/50/200 |
| **Volume** | 30% | CME Currency Futures | Volume-weighted momentum (amplifica/attenua il segnale di prezzo) |
| **COT** | 30% | Report CFTC settimanale | Posizionamento netto speculativo (percentile + variazione) |

### Calcolo Price Action
Per ogni valuta, si analizzano **tutte le 28 coppie** che la contengono:
- **RSI(14)**: forza relativa del prezzo
- **ROC multi-periodo**: Rate of Change a 4, 12 e 24 barre (ponderato 50/30/20%)
- **EMA positioning**: posizione del prezzo rispetto a EMA 20, 50 e 200

Lo score è la media su tutte le coppie della valuta.

### Calcolo Volume
I volumi del forex OTC non sono centralizzati. Usiamo come proxy i **volumi dei futures valutari CME** (6E=F per EUR, 6B=F per GBP, ecc.):
- Volume corrente / SMA(Volume, 20) = **Volume Ratio**
- Volume Ratio > 1 → amplifica il segnale di prezzo
- Volume Ratio < 1 → attenua il segnale

### Calcolo COT
Il report **Commitments of Traders** della CFTC è pubblicato ogni venerdì (dati del martedì):
- **Net Speculative Position** = Non-Commercial Long − Non-Commercial Short
- Percentile rispetto alle ultime 52 settimane → posizionamento relativo
- Variazione settimanale → direzionalità recente
- Alert per posizionamento estremo (crowded long/short)

---

## 🔴🟢 Soglie di Attenzione

| Score | Significato | Azione |
|-------|-------------|--------|
| **≥ 80** | Forza estrema | ⚠️ Possibile esaurimento / eccesso |
| **≥ 70** | Forte bullish | Cercare opportunità LONG su coppie con questa valuta |
| **50** | Neutro | Nessun bias direzionale |
| **≤ 30** | Forte bearish | Cercare opportunità SHORT su coppie con questa valuta |
| **≤ 20** | Debolezza estrema | ⚠️ Possibile rimbalzo / eccesso ribassista |

---

## 📈 Classificazione: Trend Following vs Mean Reverting

Per ogni valuta il sistema determina se il regime corrente favorisce strategie **trend-following** o **mean-reverting** usando tre indicatori:

| Indicatore | Trend Following | Mean Reverting |
|------------|-----------------|----------------|
| **ADX** | > 25 (mercato direzionale) | < 20 (mercato laterale) |
| **Hurst Exponent** | > 0.55 (serie persistente) | < 0.45 (serie anti-persistente) |
| **Efficiency Ratio** | > 0.40 (alta efficienza direzionale) | < 0.20 (choppiness) |

Score composito: ADX (40%) + Hurst (35%) + ER (25%) → 0-100
- **≥ 65**: TREND_FOLLOWING
- **≤ 35**: MEAN_REVERTING
- **36-64**: MIXED

---

## 🚀📉 Momentum: Chi Guadagna/Perde Forza

Il delta di forza sulle ultime N barre identifica le valute in accelerazione:
- **Δ ≥ +5.0** → 🚀 Guadagno rapido di forza
- **Δ ≤ −5.0** → 📉 Perdita rapida di forza

L'**accelerazione** (delta del delta) misura se il movimento sta accelerando o decelerando.

---

## ⏱ Frequenza Ottimale per H1 / H4

### Ricerca e Raccomandazioni

| Aspetto | H1 | H4 |
|---------|----|----|
| **Refresh prezzo** | Ogni 60 min (a chiusura barra) | Ogni 4 ore (a chiusura barra) |
| **Refresh volume** | Sincronizzato con prezzo | Sincronizzato con prezzo |
| **COT** | Overlay settimanale | Overlay settimanale |
| **Dashboard auto-refresh** | 60 min | 240 min |

### Fonti Dati per il Forex

| Fonte | Tipo | Pro | Contro |
|-------|------|-----|--------|
| **Yahoo Finance** | Prezzo H1 (gratuito) | Facile, 60 giorni di storico | Tick volume, non volume reale |
| **CME Futures** | Volume reale | Volume regolamentato, affidabile | Solo orari CME, non 24h |
| **CFTC COT** | Posizionamento settimanale | Gratuito, istituzionale | Ritardo (dati del martedì, rilascio venerdì) |
| **OANDA API** | Prezzo/volume tick | Dati 24h, granulari | Richiede account, volume = tick |
| **MetaTrader 5** | Prezzo/tick volume | Accesso broker, H1/H4/M15 | Solo tick volume, dipende dal broker |

### Best Practice Operative
1. **Analisi primaria su H4** → segnali più affidabili, meno rumore
2. **Fine-tuning entrate su H1** → timing preciso
3. **COT come filtro strategico settimanale** → bias di fondo
4. **Check dashboard nelle sessioni chiave**:
   - 🇬🇧 London Open: 08:00 GMT
   - 🇺🇸 NY Open: 13:00 GMT
   - 🇬🇧 London Close: 16:00 GMT
5. **Aggiornamento COT**: venerdì sera dopo le 15:30 ET (rilascio CFTC)

### Perché H4 è Preferibile a H1
- **Rumore ridotto**: meno falsi segnali da micro-movimenti
- **Hurst più stabile**: l'esponente di Hurst su H4 è più significativo statisticamente
- **ADX più affidabile**: periodi di consolidamento sono meglio filtrati
- **Volume CME**: coincide meglio con le sessioni di trading principali
- **COT settimanale**: si integra meglio con un timeframe più lento

---

## 🔧 Personalizzazione

Tutti i parametri sono configurabili in `config.py`:

```python
# Pesi compositi
WEIGHT_PRICE_ACTION = 0.40
WEIGHT_VOLUME       = 0.30
WEIGHT_COT          = 0.30

# Soglie
THRESHOLD_STRONG_BULL  = 70
THRESHOLD_EXTREME_BULL = 80
THRESHOLD_STRONG_BEAR  = 30
THRESHOLD_EXTREME_BEAR = 20

# Classificazione
ADX_TREND_THRESH   = 25
HURST_TREND_THRESH = 0.55
EFFICIENCY_TREND   = 0.40
```

---

## 🗂 Note Tecniche

- **Cache**: i dati scaricati vengono salvati nella cartella `cache/` in formato Parquet. La cache ha un TTL configurabile (default: 1h per H1, 4h per H4).
- **COT**: se il download CFTC fallisce, il sistema genera dati neutri (score 50) e mostra un avviso.
- **Resample H4**: yfinance non supporta nativamente l'intervallo 4h, quindi i dati H1 vengono resampleati a H4 con aggregazione OHLCV corretta.
- **Volume Forex**: il forex è OTC e non ha volume centralizzato. I volumi dei futures CME sono il miglior proxy disponibile gratuitamente. Per volumi tick dal broker si può integrare MetaTrader 5 (`MetaTrader5` package).

---

## 📄 Licenza

Uso personale / educational. I dati provengono da fonti pubbliche gratuite (Yahoo Finance, CFTC).
