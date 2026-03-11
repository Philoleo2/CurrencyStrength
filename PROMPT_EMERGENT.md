# PROMPT — Currency Strength Dashboard (Mobile App)

Crea un'applicazione mobile Android (APK) che analizza la forza relativa di 8 valute del mercato Forex in tempo reale. L'app deve scaricare dati OHLCV da Yahoo Finance su **3 timeframe (H1, H4, D1)**, calcolare indicatori tecnici incluso il **Candle-9 (C9)**, generare un punteggio composito a 4 componenti per ogni valuta e produrre trade setup con grading (12 criteri). Il sistema include il **D1 Decay** (riduzione dinamica del peso giornaliero) e un **sistema anti-flickering** per stabilizzare i segnali. Le notifiche Telegram vengono inviate per segnali A/A+. L'app deve funzionare in background.

---

## 1. CONFIGURAZIONE BASE

### 1.1 Valute e Coppie

**8 valute analizzate:** USD, EUR, GBP, JPY, CHF, AUD, NZD, CAD

**28 coppie Forex (tutte le combinazioni):**

| Coppia   | Ticker Yahoo | Base | Quote |
|----------|-------------|------|-------|
| EURUSD   | EURUSD=X    | EUR  | USD   |
| GBPUSD   | GBPUSD=X    | GBP  | USD   |
| AUDUSD   | AUDUSD=X    | AUD  | USD   |
| NZDUSD   | NZDUSD=X    | NZD  | USD   |
| USDJPY   | USDJPY=X    | USD  | JPY   |
| USDCHF   | USDCHF=X    | USD  | CHF   |
| USDCAD   | USDCAD=X    | USD  | CAD   |
| EURGBP   | EURGBP=X    | EUR  | GBP   |
| EURJPY   | EURJPY=X    | EUR  | JPY   |
| EURCHF   | EURCHF=X    | EUR  | CHF   |
| EURAUD   | EURAUD=X    | EUR  | AUD   |
| EURNZD   | EURNZD=X    | EUR  | NZD   |
| EURCAD   | EURCAD=X    | EUR  | CAD   |
| GBPJPY   | GBPJPY=X    | GBP  | JPY   |
| GBPCHF   | GBPCHF=X    | GBP  | CHF   |
| GBPAUD   | GBPAUD=X    | GBP  | AUD   |
| GBPNZD   | GBPNZD=X    | GBP  | NZD   |
| GBPCAD   | GBPCAD=X    | GBP  | CAD   |
| AUDJPY   | AUDJPY=X    | AUD  | JPY   |
| AUDCHF   | AUDCHF=X    | AUD  | CHF   |
| AUDNZD   | AUDNZD=X    | AUD  | NZD   |
| AUDCAD   | AUDCAD=X    | AUD  | CAD   |
| NZDJPY   | NZDJPY=X    | NZD  | JPY   |
| NZDCHF   | NZDCHF=X    | NZD  | CHF   |
| NZDCAD   | NZDCAD=X    | NZD  | CAD   |
| CADJPY   | CADJPY=X    | CAD  | JPY   |
| CADCHF   | CADCHF=X    | CAD  | CHF   |
| CHFJPY   | CHFJPY=X    | CHF  | JPY   |

**8 ticker Futures (per volume):**

| Valuta | Ticker Futures |
|--------|---------------|
| EUR    | 6E=F          |
| GBP    | 6B=F          |
| JPY    | 6J=F          |
| CHF    | 6S=F          |
| AUD    | 6A=F          |
| NZD    | 6N=F          |
| CAD    | 6C=F          |
| USD    | DX=F          |

### 1.2 COT — Keyword CFTC e Parametri

**Keyword per filtrare il report Legacy Futures-Only della CFTC:**

| Valuta | Keyword CFTC        |
|--------|--------------------|
| EUR    | EURO FX            |
| GBP    | BRITISH POUND      |
| JPY    | JAPANESE YEN       |
| CHF    | SWISS FRANC        |
| AUD    | AUSTRALIAN DOLLAR  |
| NZD    | NEW ZEALAND        |
| CAD    | CANADIAN DOLLAR    |
| USD    | U.S. DOLLAR INDEX  |

**URL CFTC:**
```
COT_BASE_URL = "https://www.cftc.gov/dea/newcot/deafut.txt"       # report corrente (testo CSV)
COT_HIST_URL = "https://www.cftc.gov/files/dea/history/deahistfo{year}.zip"  # storico annuale
```

**Parametri scoring:**
```
COT_PERCENTILE_LOOKBACK = 52    # settimane (1 anno) per calcolo percentile
COT_EXTREME_LONG        = 90    # percentile ≥ 90 → CROWDED_LONG
COT_EXTREME_SHORT       = 10    # percentile ≤ 10 → CROWDED_SHORT
```

### 1.3 Parametri Tecnici

```
RSI_PERIOD      = 14
ROC_FAST        = 4       # barre (H4→16 ore, H1→4 ore)
ROC_MEDIUM      = 12
ROC_SLOW        = 24
EMA_FAST        = 20
EMA_MEDIUM      = 50
EMA_SLOW        = 200
ADX_PERIOD      = 14
ATR_PERIOD      = 14
HURST_MIN_BARS  = 100
MOMENTUM_LOOKBACK = 6
```

### 1.4 Pesi Composito (4 componenti, sommano a 1.0)

```
WEIGHT_PRICE_ACTION = 0.25   # Price Action (RSI + ROC + EMA)
WEIGHT_VOLUME       = 0.20   # Volume (futures CME)
WEIGHT_COT          = 0.30   # COT (Commitment of Traders)
WEIGHT_C9           = 0.25   # Candle-9 (escursione + velocità ultimi 9 periodi)
```

**NOTA IMPORTANTE:** Il composito ha **4 componenti**, non 3. Il Candle-9 (C9) vale il 25% del punteggio totale.

### 1.5 Soglie

```
THRESHOLD_STRONG_BULL  = 70
THRESHOLD_EXTREME_BULL = 80
THRESHOLD_STRONG_BEAR  = 30
THRESHOLD_EXTREME_BEAR = 20
MOMENTUM_FAST_GAIN     =  5.0
MOMENTUM_FAST_LOSS     = -5.0
MIN_DIFFERENTIAL_THRESHOLD = 8   # differenziale minimo per qualificare un trade setup
```

### 1.6 Pesi Multi-Timeframe (H1 + H4 + D1, sommano a 1.0)

L'analisi viene eseguita su **3 timeframe** e poi blended:

```
COMPOSITE_WEIGHT_H1 = 0.30   # reattività (risposta rapida ai cambiamenti)
COMPOSITE_WEIGHT_H4 = 0.40   # stabilità (filtra il rumore, trend robusti)
COMPOSITE_WEIGHT_D1 = 0.30   # trend di fondo (direzione dominante giornaliera)
```

### 1.7 D1 Decay — Riduzione Dinamica del Peso Giornaliero

Quando H1 e H4 divergono (sono su lati opposti o distanti), il peso del D1 viene **ridotto dinamicamente** e ridistribuito a H1+H4. Questo accelera le uscite dalla top/bottom della classifica quando il mercato cambia direzione.

```
D1_DIVERGENCE_THRESHOLD = 10    # |H1−H4| minimo per attivare il decay (punti)
D1_DIVERGENCE_MAX       = 40    # |H1−H4| a cui il decay è massimo
D1_DECAY_MIN_WEIGHT     = 0.05  # peso D1 minimo (non scende mai sotto 5%)
D1_DECAY_OPPOSITE_BONUS = 0.3   # bonus extra decay se H1 e H4 su lati opposti del 50
```

**Algoritmo D1 Decay per ogni valuta:**
```
gap = |score_H1 − score_H4|
opposite_sides = (score_H1 ≥ 55 AND score_H4 ≤ 45) OR (score_H1 ≤ 45 AND score_H4 ≥ 55)

SE gap ≥ D1_DIVERGENCE_THRESHOLD AND peso_D1 > 0:
    raw_decay = min((gap − 10) / max(40 − 10, 1), 1.0)
    SE opposite_sides:
        raw_decay = min(raw_decay + 0.3, 1.0)
    
    eff_d1 = max(0.30 × (1 − raw_decay), 0.05)        # peso D1 effettivo
    freed = 0.30 − eff_d1                               # peso liberato
    ratio_h1h4 = 0.30 / (0.30 + 0.40)                  # proporzione H1/(H1+H4)
    eff_h1 = 0.30 + freed × ratio_h1h4                  # peso H1 effettivo
    eff_h4 = 0.40 + freed × (1 − ratio_h1h4)           # peso H4 effettivo
ALTRIMENTI:
    eff_h1 = 0.30, eff_h4 = 0.40, eff_d1 = 0.30        # pesi normali
```

### 1.8 Parametri Classificazione Trend

```
ADX_TREND_THRESH     = 25
ADX_RANGE_THRESH     = 20
HURST_TREND_THRESH   = 0.55
HURST_REVERT_THRESH  = 0.45
EFFICIENCY_TREND     = 0.40
EFFICIENCY_RANGE     = 0.20
CLASS_W_ADX   = 0.40
CLASS_W_HURST = 0.35
CLASS_W_ER    = 0.25
```

### 1.9 Parametri Stabilità Classifica (Anti-Flickering)

Questi parametri evitano che i segnali A/A+ entrino ed escano continuamente dalla classifica:

```
SCORE_SMOOTHING_ALPHA        = 0.5   # EMA smoothing: 50% nuovo, 50% vecchio
MIN_DIFFERENTIAL_THRESHOLD   = 8     # differenziale minimo per qualificare un setup
GRADE_HYSTERESIS_POINTS      = 5     # un A (≥60) esce solo se scende sotto 55
SIGNAL_GRACE_REFRESHES       = 2     # refresh sotto soglia prima dell'uscita (= 2 ore)
SIGNAL_MIN_RESIDENCE_HOURS   = 4     # un segnale resta almeno 4 ore in classifica
SIGNAL_CONFIRMATION_REFRESHES = 2    # deve essere A/A+ per 2 refresh consecutivi per entrare
COT_STALE_DAYS_THRESHOLD     = 10    # se dati COT più vecchi di 10 giorni, dimezza peso
```

### 1.10 Gruppi Correlazione (per filtrare i duplicati nei setup)

```
Gruppo 0: AUDNZD, AUDCAD, NZDCAD
Gruppo 1: AUDUSD, USDCAD, NZDUSD
Gruppo 2: EURUSD, GBPUSD
Gruppo 3: USDJPY, USDCHF, CHFJPY
Gruppo 4: CADJPY, NZDJPY, AUDJPY
Gruppo 5: GBPCHF, EURCHF
Gruppo 6: EURNZD, EURCAD, EURAUD
Gruppo 7: GBPNZD, GBPCAD, GBPAUD
Gruppo 8: NZDCHF, CADCHF, AUDCHF
Gruppo 9: GBPJPY, EURJPY
```

### 1.11 Coppie Escluse

**EURGBP** — mai tradate

### 1.12 Affinità Sessioni

```
Asia/Tokyo:  JPY, AUD, NZD
Londra:      EUR, GBP, CHF
New York:    USD, CAD
```

### 1.13 Telegram

```
BOT_TOKEN = "8727017446:AAEaUigln8Zw4glgqDyaGcXHmwKLQIWG3XY"
CHAT_ID   = "901682485"
ALERT_GRADES = ["A+", "A"]
MONITOR_INTERVAL_MINUTES = 60
```

---

## 2. SCARICAMENTO DATI (Data Fetcher)

### 2.1 API Yahoo Finance v8

**Endpoint:** `https://query2.finance.yahoo.com/v8/finance/chart/{TICKER}?range={PERIOD}&interval={INTERVAL}&includePrePost=false`

**IMPORTANTE — Approccio bare-minimum (NO cookies, NO crumb, NO session):**
Yahoo rate-limita in base ai cookie di sessione, non all'IP. Le richieste con cookie GDPR/consent ricevono HTTP 429. Bisogna fare richieste "nude" senza cookie.

**Headers minimi per ogni richiesta:**
```
Host: query2.finance.yahoo.com
User-Agent: Mozilla/5.0
Connection: close
```

**Non usare MAI:**
- Cookie
- Crumb/session token
- Connection pooling (ogni richiesta = nuova connessione)
- Più di un host (usare SOLO query2.finance.yahoo.com)

### 2.2 Timeframe e Parametri di Download

L'app scarica dati per **3 timeframe separati**:

| Timeframe | interval (Yahoo) | range (Yahoo) | Resample? |
|-----------|-----------------|---------------|-----------|
| H1        | `1h`            | `60d`         | No        |
| H4        | `1h`            | `60d`         | Sì → 4h  |
| D1        | `1d`            | `1y`          | No        |

**IMPORTANTE:** Yahoo Finance non supporta l'intervallo 4h direttamente. Si scaricano dati 1h e poi si resampleano a 4h localmente. Il D1 si scarica separatamente con `interval=1d&range=1y`.

### 2.3 Procedura di Fetch

1. **Fetch H1**: Per ognuna delle 28 coppie Forex, fai 1 richiesta a `range=60d&interval=1h`
2. Tra ogni richiesta, aspetta **1.5 secondi**
3. Se ricevi HTTP 429, aspetta 5 secondi e riprova UNA volta
4. Se 10 fallimenti consecutivi con 0 successi → interrompi (abort)
5. Dopo le 28 coppie, scarica gli 8 futures con la stessa logica e delay di 1.5s
6. **Resample H1 → H4**: Localmente, senza scaricare di nuovo
7. **Fetch D1**: Per ognuna delle 28 coppie, fai 1 richiesta a `range=1y&interval=1d` (stessi delay)
8. **Fetch Futures D1**: 8 futures con `range=1y&interval=1d`

### 2.4 Parsing della risposta JSON

La risposta ha questa struttura:
```json
{
  "chart": {
    "result": [{
      "timestamp": [1234567890, ...],
      "indicators": {
        "quote": [{
          "open": [...],
          "high": [...],
          "low": [...],
          "close": [...],
          "volume": [...]
        }]
      }
    }]
  }
}
```

Converti in DataFrame con colonne: Open, High, Low, Close, Volume.
L'indice è `pd.to_datetime(timestamp, unit="s", utc=True)`.
Rimuovi righe con Close NaN.

### 2.5 Resampling OHLCV

Per ottenere candele H4 dalle H1:
```
Open  → first
High  → max
Low   → min
Close → last
Volume → sum
```
Usa `df.resample("4h").agg(...)` e rimuovi righe con Close NaN.

### 2.6 COT Data — Download e Scoring

**Download:**
1. Scarica il report COT storico dell'anno precedente (zip) + anno corrente (zip) + report più recente (testo)
2. Combina i dati e filtra per le keyword delle 8 valute (sezione 1.2)
3. Estrae: `net_speculative = noncomm_long − noncomm_short` per ogni valuta/data
4. Cache locale in CSV (`cache/cot_data.csv`), refresh ogni 24 ore

**Scoring (per valuta, 0-100):**
```
# Percentile netto speculativo rispetto allo storico
# Se ci sono ≥ 52 valori: ultimi 52. Altrimenti: usa TUTTI i valori disponibili.
lookback = ultimi min(52, len(net_speculative)) valori di net_speculative
pct_rank = (count(lookback ≤ latest) / len(lookback)) × 100

# Variazione settimanale
wk_change = net_speculative[-1] − net_speculative[-2]

# Normalizzazione variazione
std_ns = std(lookback)
change_norm = clip(wk_change / std_ns, −2, 2) × 10   # ±20 punti

# Score finale
score = clip(pct_rank + change_norm, 0, 100)

# Freshness (giorni dal dato più recente)
freshness_days = (oggi − data_ultimo_report).days
```

**Classificazione:**
```
score ≥ 60 → bias = "BULLISH"
score ≤ 40 → bias = "BEARISH"
altrimenti → bias = "NEUTRAL"

pct_rank ≥ 90 → extreme = "CROWDED_LONG"
pct_rank ≤ 10 → extreme = "CROWDED_SHORT"
altrimenti → extreme = None
```

**Output per valuta:** `{score, bias, extreme, net_spec_percentile, weekly_change, freshness_days}`

### 2.7 Currency Returns

Per ogni valuta, calcola il rendimento medio da tutte le coppie in cui compare:
1. Trova l'indice comune (intersezione) di tutte le coppie
2. Per ogni coppia, calcola `pct_change(window=1)` del Close
3. Se la valuta è la **base** della coppia → somma il return così com'è
4. Se la valuta è la **quote** della coppia → somma il **negativo** del return
5. Il return della valuta = media di tutti i return delle coppie in cui compare

---

## 3. MOTORE DI ANALISI

L'analisi si compone di **12 moduli** calcolati in sequenza. Ogni modulo produce uno score o set di attributi per ciascuna delle 8 valute. L'analisi viene eseguita **3 volte** (una per H1, una per H4, una per D1), poi i risultati vengono blended.

### 3.1 Indicatori Tecnici Base

#### RSI (Relative Strength Index) — Periodo 14
```
delta = close.diff()
gain = delta.clip(lower=0)          # element-wise: ogni valore negativo diventa 0
loss = (-delta).clip(lower=0)       # element-wise: ogni valore negativo diventa 0
avg_gain = EWM(gain, alpha=1/14, min_periods=14)
avg_loss = EWM(loss, alpha=1/14, min_periods=14)
rs = avg_gain / avg_loss
RSI = 100 - (100 / (1 + rs))
```

#### ROC (Rate of Change) — Periodi 4, 12, 24
```
ROC(period) = pct_change(period) * 100
```

#### EMA (Exponential Moving Average) — Periodi 20, 50, 200
```
EMA(period) = ewm(span=period, adjust=False).mean()
```

#### ADX (Average Directional Index) — Periodo 14
```
+DM = high.diff()  (solo se > -low.diff() e > 0, altrimenti 0)
-DM = -low.diff()  (solo se > +DM e > 0, altrimenti 0)
TR = max(high-low, |high-close_prev|, |low-close_prev|)
ATR = EWM(TR, alpha=1/14, min_periods=14)
+DI = 100 * EWM(+DM, alpha=1/14) / ATR
-DI = 100 * EWM(-DM, alpha=1/14) / ATR
DX = |+DI - -DI| / (+DI + -DI) * 100
ADX = EWM(DX, alpha=1/14, min_periods=14)
```

#### ATR (Average True Range) — Periodo 14
```
TR = max(high-low, |high-close_prev|, |low-close_prev|)
ATR = EWM(TR, alpha=1/14, min_periods=14)
```

#### Hurst Exponent
Calcola l'esponente di Hurst usando il metodo Rescaled Range (R/S):
1. Prendi la serie dei returns, servono almeno 100 barre
2. Per dimensioni di finestra k da 10 a min(n/2, 200) con step 5:
   - Dividi la serie in segmenti di lunghezza k
   - Per ogni segmento: calcola media, deviata cumulata, R = max(deviata) - min(deviata), S = std(segmento)
   - Se S > 0: R/S = R/S ratio
   - Media dei R/S per quella dimensione k
3. Fai regressione lineare: log(R/S) vs log(k) → la pendenza è l'esponente di Hurst
4. Clip tra 0 e 1. Se pochi punti (<3), restituisci 0.5

**Interpretazione:**
- H > 0.55 → trending (persistente)
- H < 0.45 → mean-reverting
- H ≈ 0.50 → random walk

#### Efficiency Ratio — Periodo 20
```
direction = |close - close.shift(20)|
volatility = sum(|close.diff()|) su 20 barre rolling
ER = direction / volatility  (range 0-1)
```

### 3.2 Price Action Scores (per valuta, 0-100)

Per ogni coppia in cui la valuta compare:

**CALCOLO per singola coppia:**

1. **RSI Score** (peso 35%):
   - Se la valuta è la base della coppia: usa RSI direttamente
   - Se la valuta è la quote: usa `100 - RSI`

2. **ROC Multi-periodo Score** (peso 40%):
   ```
   avg_roc = ROC_fast * 0.5 + ROC_medium * 0.3 + ROC_slow * 0.2
   ```
   Se la valuta è la quote: moltiplica per -1
   ```
   roc_score = 50 + clip(avg_roc * 10, -50, 50)
   ```

3. **EMA Positioning Score** (peso 25%):
   Per ogni EMA (20, 50, 200):
   ```
   pct_above = ((close_ultimo / ema_ultimo) - 1) * 100
   ```
   Se la valuta è la quote: moltiplica per -1
   ```
   ema_score_singolo = 50 + clip(pct_above * 15, -50, 50)
   ```
   Media dei 3 ema_score individuali

**Score per la coppia:**
```
score_coppia = RSI_score * 0.35 + ROC_score * 0.40 + EMA_score * 0.25
clip(0, 100)
```

**Score finale per valuta:**
Media di tutti gli score delle coppie in cui la valuta compare (come base o come quote).

### 3.3 Volume Scores (per valuta, 0-100)

Per ogni valuta, usando il relativo ticker futures:

1. Calcola Volume Ratio:
   ```
   sma_volume = rolling(20).mean() del volume futures
   volume_ratio = volume_ultimo / sma_volume_ultimo
   ```
   Se non ci sono dati futures: volume_ratio = 1.0

2. Amplifica il Price Action Score:
   ```
   deviation = price_action_score - 50
   amplified = deviation * clip(volume_ratio, 0.5, 2.0)
   volume_score = clip(50 + amplified, 0, 100)
   ```

### 3.4 Composite Scores (per valuta, 0-100)

Il composito combina **4 componenti**:

```
composite = price_action × 0.25 + volume × 0.20 + cot × 0.30 + c9 × 0.25
clip(0, 100)
```

Dove:
- `price_action` = PriceAction score (sezione 3.2)
- `volume` = Volume score (sezione 3.3)
- `cot` = COT score (50 = neutral se non disponibile)
- `c9` = Candle-9 score (sezione 3.12)

**NOTA:** Se il COT non è disponibile (es. mobile senza accesso CFTC), usa 50 (neutral). Ma C9 è SEMPRE calcolato perché si basa solo sui dati di prezzo.

**Label:**
- composite ≥ 80 → "VERY STRONG"
- composite ≥ 70 → "STRONG"
- composite ≤ 20 → "VERY WEAK"
- composite ≤ 30 → "WEAK"
- altrimenti → "NEUTRAL"

**Alert:**
- composite ≥ 80 → "⚠️ ATTENZIONE: forza estrema, possibile esaurimento"
- composite ≤ 20 → "⚠️ ATTENZIONE: debolezza estrema, possibile rimbalzo"
- Se COT = CROWDED_LONG → appendere "COT: posizionamento speculativo estremo LONG"
- Se COT = CROWDED_SHORT → appendere "COT: posizionamento speculativo estremo SHORT"

### 3.5 Momentum Rankings (per valuta)

Usa i Currency Returns (sezione 2.7):

```
cum_recent = somma dei returns delle ultime 6 barre * 100
cum_prev = somma dei returns delle 6 barre prima * 100
delta = cum_recent
acceleration = cum_recent - cum_prev
```

**Label:**
- delta ≥ 5.0 → "GAINING FAST"
- delta ≤ -5.0 → "LOSING FAST"
- delta > 0 → "Gaining"
- delta < 0 → "Losing"
- delta = 0 → "Flat"

### 3.6 Classificazione Trend vs Mean-Revert (per valuta)

Tre componenti normalizzate da 0 a 100 e combinate:

1. **ADX Component:**
   - Calcola ADX medio di tutte le coppie in cui compare la valuta
   ```
   adx_norm = clip((avg_adx - 20) / (25 - 20), 0, 1) * 100
   ```

2. **Hurst Component:**
   - Calcola Hurst sui returns della valuta
   ```
   hurst_norm = clip((hurst - 0.45) / (0.55 - 0.45), 0, 1) * 100
   ```

3. **Efficiency Ratio Component:**
   - Calcola ER sui dati futures della valuta
   ```
   er_norm = clip((er - 0.20) / (0.40 - 0.20), 0, 1) * 100
   ```

4. **Trend Score finale:**
   ```
   trend_score = adx_norm * 0.40 + hurst_norm * 0.35 + er_norm * 0.25
   clip(0, 100)
   ```

**Classificazione:**
- trend_score ≥ 65 → "TREND_FOLLOWING"
- trend_score ≤ 35 → "MEAN_REVERTING"
- altrimenti → "MIXED"

### 3.7 ATR Context / Regime di Volatilità (per valuta)

Per ogni coppia in cui la valuta compare:
1. Calcola ATR su periodo 14
2. `atr_pct = (atr_corrente / close_corrente) * 100`
3. `percentile = percentuale di barre nelle ultime 50 in cui ATR era inferiore all'ATR corrente`

Media dei percentili di tutte le coppie della valuta.

**Regime:**
- percentile ≥ 85 → "EXTREME"
- percentile ≥ 65 → "HIGH"
- percentile ≥ 35 → "NORMAL"
- percentile < 35 → "LOW"

### 3.8 Velocity Scores (per valuta, 0-100)

Misura la velocità e la direzionalità del movimento:

1. Calcola i returns cumulati rolling su 20 barre
2. Sulle ultime 20 barre dei returns cumulati:
   ```
   directional_change = |ultimo - primo|
   path_length = somma(|diff| di ogni barra)
   efficiency = directional_change / path_length
   ```
3. Fattore magnitudine:
   ```
   std_recent = deviazione standard delle ultime 20 barre
   magnitude = directional_change / std_recent
   magnitude_factor = clip(magnitude / 2.0, 0.3, 1.0)
   ```
4. Score finale:
   ```
   velocity_norm = clip(efficiency * magnitude_factor * 120, 0, 100)
   ```

**Label:**
- ≥ 70 → "VERY FAST"
- ≥ 50 → "FAST"
- ≥ 35 → "MODERATE"
- ≥ 20 → "SLOW"
- < 20 → "STALE"

### 3.9 Trend Structure — EMA Cascade (per valuta)

Per ogni coppia in cui la valuta compare:
- Calcola EMA 20, 50, 200 dell'ultimo Close
- Se EMA20 > EMA50 > EMA200 → alignment = +1.0 (bull cascade)
- Se EMA20 < EMA50 < EMA200 → alignment = -1.0 (bear cascade)
- Se EMA20 > EMA200 (ma non cascade completa) → alignment = +0.3
- Se EMA20 < EMA200 → alignment = -0.3
- Altrimenti → 0.0

**Se la valuta è la quote della coppia:** invertire il segno dell'alignment.

**Score finale per valuta:** media degli alignment di tutte le coppie.

### 3.10 Strength Persistence (per valuta)

Misura la persistenza direzionale della forza di ogni valuta analizzando le ultime N barre (default 10) dello score rolling composito (sezione 3.13):

```
per le ultime 10 barre dello score composito rolling:
  above_55 = (numero di barre con score > 55) / N
  below_45 = (numero di barre con score < 45) / N

  SE above_55 ≥ below_45:
      persistence = +above_55    (range 0 a +1)
      direction = "BULL"
  ALTRIMENTI:
      persistence = -below_45    (range -1 a 0)
      direction = "BEAR"

  slope = pendenza lineare (polyfit grado 1) dello score sulle N barre
```

**Label:**
- |persistence| ≥ 0.7 → "🔒 PERSISTENTE {BULL/BEAR}"
- |persistence| ≥ 0.4 → "↗/↘ Trending {bull/bear}"
- |persistence| < 0.4 → "🔀 Inconsistente"

### 3.11 Candle-9 Price Action Signal (per valuta — DISPLAY)

Per ogni coppia in cui la valuta compare, confronta il close attuale con il close di **9 candele fa**:

```
pct_change = ((close_attuale − close_9_candele_fa) / close_9_candele_fa) × 100
```

**Aggregazione per valuta:**
- Se la valuta è la **base** della coppia: `pct_change` va così com'è (coppia sale = base forte)
- Se la valuta è la **quote** della coppia: `−pct_change` (coppia sale = quote debole)
- Score finale = **media** di tutti i pct_change delle coppie in cui la valuta compare

**Signal:**
- media > 0.05% → "🟢 BULLISH"
- media < -0.05% → "🔴 BEARISH"
- altrimenti → "➖ NEUTRO"

**Output per valuta:** `{candle9_ratio: float, candle9_signal: str, candle9_pairs: int}`

### 3.12 Candle-9 Score (per valuta, 0-100 — per COMPOSITO)

Score numerico usato nel calcolo del composito. Per ogni coppia:

**3 sotto-componenti:**

1. **Magnitude** (peso 50%): escursione % close attuale vs close 9 candele fa
   ```
   magnitude_score = 50 + clip(pct_change × 25, −50, 50)
   ```

2. **Velocity** (peso 35%): pendenza lineare del close nelle ultime 9+1 candele
   ```
   slope = polyfit(x, close_ultimi_10, grado=1)[0]
   slope_pct = (slope / mean(close)) × 100
   velocity_score = 50 + clip(slope_pct × 200, −50, 50)
   ```

3. **Consistency** (peso 15%): % di candele nella stessa direzione del movimento
   ```
   SE pct_change > 0:
       consistency = (candele con diff > 0) / totale_candele
   SE pct_change < 0:
       consistency = (candele con diff < 0) / totale_candele
   SE pct_change == 0:
       consistency = 0
   consistency_bonus = consistency × 10
   consistency_score = 50 + consistency_bonus
   ```

**Score per coppia:**
```
pair_score = magnitude_score × 0.50 + velocity_score × 0.35 + consistency_score × 0.15
clip(0, 100)
```

**Aggregazione per valuta:**
- Se la valuta è la **base** → aggiunge `pair_score`
- Se la valuta è la **quote** → aggiunge `100 − pair_score`
- Score finale = media di tutti i pair_score

### 3.13 Rolling Strength Composito (per grafici storici)

Calcola un vero score composito rolling (0-100) per ogni valuta a ogni barra, replicando la stessa logica usata per lo snapshot:

1. Calcola "prezzo sintetico" della valuta: `cum_price = cumprod(1 + returns)` per ogni valuta
2. **RSI rolling** (35%): RSI su cum_price con periodo 14
3. **ROC rolling** (40%): media ponderata dei ROC multi-periodo, normalizzata
4. **EMA positioning rolling** (25%): posizione relativa a EMA 20/50/200
5. **Price Action rolling** = RSI × 0.35 + ROC × 0.40 + EMA × 0.25
6. **Volume amplification**: se disponibili, amplifica con volume ratio dei futures
7. **COT rolling**: costante settimanale, espanso su tutte le barre (o 50 se non disponibile)
8. **C9 rolling**: per ogni barra calcola magnitude + velocity
   ```
   pct_c9 = cum_price.pct_change(9) × 100
   magnitude = 50 + clip(pct_c9 × 25, −50, 50)
   slope_series = rolling(10).apply(polyfit lineare / mean × 100)
   velocity_s = 50 + clip(slope_series × 200, −50, 50)
   c9_score = magnitude × 0.60 + velocity_s × 0.40
   clip(0, 100)
   ```
9. **Composito finale rolling:**
   ```
   composite_ts = PA × 0.25 + Volume × 0.20 + COT × 0.30 + C9 × 0.25
   clip(0, 100)
   ```

---

## 4. BLENDING MULTI-TIMEFRAME (H1 + H4 + D1)

L'analisi viene eseguita **3 volte separate**: una sui dati H1, una sui dati H4 (resampling), una sui dati D1 (scaricati separatamente).

### 4.1 Blend Composite con D1 Decay

Per ogni valuta, il blend dei composite avviene con pesi effettivi che possono variare per valuta (a causa del D1 Decay):

```
# 1. Calcola pesi effettivi (vedi sezione 1.7 per D1 Decay)
eff_h1, eff_h4, eff_d1 = calcola_d1_decay(score_H1, score_H4)

# 2. Blend di ogni sotto-score
blended_price    = price_H1 × eff_h1 + price_H4 × eff_h4 + price_D1 × eff_d1
blended_volume   = volume_H1 × eff_h1 + volume_H4 × eff_h4 + volume_D1 × eff_d1
blended_cot      = cot_H1 × eff_h1 + cot_H4 × eff_h4 + cot_D1 × eff_d1
blended_c9       = c9_H1 × eff_h1 + c9_H4 × eff_h4 + c9_D1 × eff_d1
blended_composite = composite_H1 × eff_h1 + composite_H4 × eff_h4 + composite_D1 × eff_d1
clip(0, 100)
```

**Output per valuta (aggiunge anche dettagli per timeframe):**
```json
{
  "price_score": round(blended_price, 1),
  "volume_score": round(blended_volume, 1),
  "cot_score": round(blended_cot, 1),
  "c9_score": round(blended_c9, 1),
  "composite": round(blended_composite, 1),
  "h1_score": round(score_H1_originale, 1),
  "h4_score": round(score_H4_originale, 1),
  "d1_score": round(score_D1_originale, 1),
  "d1_decay_pct": percentuale_riduzione_D1,
  "d1_eff_weight": peso_D1_effettivo,
  "h1h4_gap": |score_H1 − score_H4|,
  "h1h4_opposite": bool,
  "concordance": etichetta_concordanza,
  "label": "VERY STRONG/STRONG/NEUTRAL/WEAK/VERY WEAK",
  "alert": eventuali_alert
}
```

### 4.2 Concordance a 3 Timeframe

```
bulls = quanti tra [score_H1, score_H4, score_D1] sono ≥ 55
bears = quanti tra [score_H1, score_H4, score_D1] sono ≤ 45

SE bulls == 3 → "✅ ALLINEATI BULL"
SE bears == 3 → "✅ ALLINEATI BEAR"
SE bulls > 0 E bears > 0 → "⚠️ DIVERGENZA"
ALTRIMENTI → "➖ NEUTRO"
```

### 4.3 Blend degli altri moduli

Tutti gli altri moduli vengono blended con i pesi nominali (0.30 / 0.40 / 0.30):

- **Momentum blendato**: delta = delta_H1×0.30 + delta_H4×0.40 + delta_D1×0.30
- **Classification blendato**: trend_score = ts_H1×0.30 + ts_H4×0.40 + ts_D1×0.30
- **ATR context blendato**: percentile = p_H1×0.30 + p_H4×0.40 + p_D1×0.30
- **Velocity blendato**: velocity_norm = v_H1×0.30 + v_H4×0.40 + v_D1×0.30
- **Trend structure blendato**: alignment = a_H1×0.30 + a_H4×0.40 + a_D1×0.30
- **Strength persistence blendato**: persistence = p_H1×0.30 + p_H4×0.40 + p_D1×0.30
- **Candle-9 blendato**: ratio = r_H1×0.30 + r_H4×0.40 + r_D1×0.30
- **Rolling strength blendato**: media ponderata dei DataFrame rolling allineati sugli indici comuni

### 4.4 Smoothing Composito (Anti-Flickering)

Dopo il blend, il composito viene smussato con il valore del ciclo precedente:

```
smoothed = α × current + (1 − α) × previous
dove α = SCORE_SMOOTHING_ALPHA = 0.5
```

Si applica a: `price_score`, `volume_score`, `cot_score`, `c9_score`, `composite`, e anche a `h1_score`, `h4_score`, `d1_score` se presenti.

L'effetto: riduce le oscillazioni rapide, stabilizza la classifica, e rallenta i cambiamenti improvvisi. Un segnale A+ non scompare al primo calo perché lo smoothing mantiene in memoria il 50% dello score precedente.

Il composito precedente viene salvato in un file JSON locale (`cache/prev_composite.json`) per sopravvivere ai restart.

---

## 5. TRADE SETUP SCORING

Per ogni coppia di valute (base vs quote, 56 combinazioni uniche escluse le identiche):

### 5.1 Filtro Iniziale

Se `|composite_base - composite_quote| < 8` → scarta (differenziale troppo piccolo, MIN_DIFFERENTIAL_THRESHOLD = 8).

**Direzione:** Se diff > 0 → LONG base/quote. Se diff < 0 → SHORT base/quote.

`strong_ccy` = la valuta con composite più alto nell'operazione.
`weak_ccy` = la valuta con composite più basso.

### 5.2 Calcolo Quality Score (12 criteri)

I punti si accumulano da 12 criteri:

#### 1. Differenziale (0-30 punti)
```
quality += min(|diff| * 1.0, 30)
```
- Se |diff| ≥ 20 → ragione "Diff forte"
- Se |diff| ≥ 12 → ragione "Diff buono"

#### 2. Momentum (0-20 punti)
```
Se momentum_strong > 0 E momentum_weak < 0 → +20 ("Momentum allineato")
Se solo uno dei due → +6
```

#### 2b. Synergy bonus (0-5 punti)
```
Se |diff| ≥ 15 E momentum_strong > 0 E momentum_weak < 0 → +5
```

#### 3. Regime di Trend (0-15 punti)
```
Se classification_strong = "TREND_FOLLOWING" → +15 (+ ragione)
Se classification_strong = "MIXED" → +5
```

#### 4. Volatilità (0-15 punti, può diventare negativo)
```
Se volatility_strong ∈ {"NORMAL", "LOW"} → +10
Se volatility_strong = "HIGH" → +5
Se volatility_strong = "EXTREME" O volatility_weak = "EXTREME" → -5
```

#### 5. COT (0-10 punti, dimezzato se stale)
```
cot_multiplier = 0.5 se dati_COT_più_vecchi_di_10_giorni, altrimenti 1.0
cot_pts = 0
Se cot_bias_strong = "BULLISH" → cot_pts += 5
Se cot_bias_weak = "BEARISH" → cot_pts += 5
quality += cot_pts × cot_multiplier
```
**Penalità COT crowded contro il trade:**
```
Se cot_strong = CROWDED_LONG → −10 (speculativo estremo long sulla valuta forte)
Se cot_weak = CROWDED_SHORT → −10 (speculativo estremo short sulla valuta debole)
```
(Se COT non disponibile, score = NEUTRAL, bias = NEUTRAL, 0 punti)

#### 6. Concordance H1/H4/D1 (0-10 punti, anti-esaurimento)
```
SE concordance contiene "ALLINEATI":
    SE composite_strong ≥ 80 → +4 (ridotto: zona esaurimento, possibile inversione)
    ALTRIMENTI → +10
SE concordance contiene "DIVERGENZA" → −5
```

#### 7. Velocity (0-10 punti)
```
Se velocity_strong ≥ 65 → +10
Se velocity_strong ≥ 40 → +5
Se velocity_strong < 15 → -3
```

#### 8. Trend Structure / EMA Alignment (0-8 punti)
```
Se ema_alignment_strong ≥ 0.4 E ema_alignment_weak ≤ -0.4 → +8
Se uno dei due (strong ≥ 0.2 o weak ≤ -0.2) → +4
Se ema_alignment_strong ≤ -0.3 → -5  (penalità: strong va contro trend)
```

#### 9. Accelerazione Momentum (0-5 punti, -3 penalità)
```
Se acceleration_strong > 0 E acceleration_weak < 0 → +5
Se solo uno dei due → +2

# Penalità: valuta forte decelera E ha momentum piatto/negativo
Se acceleration_strong < 0 E momentum_strong ≤ 0 → −3
```

#### 10. Persistenza Forza (0-8 punti, -3 penalità)
```
Se persistence_strong ≥ 0.5 E persistence_weak ≤ -0.5 → +8
Se uno dei due (strong ≥ 0.3 o weak ≤ -0.3) → +4

# Penalità: nessuna persistenza su entrambe
Se |persistence_strong| < 0.2 E |persistence_weak| < 0.2 → −3
```

#### 11. Session Awareness (0-3 punti, può diventare negativo)
(Solo se ci sono sessioni attive)
```
Se entrambe le valute sono nella sessione attiva → +3
Se solo una → +1
Se nessuna → -2
```

#### 12. Candle-9 Concordante (0-25 punti, -12 penalità)
```
c9_ratio_strong = candle9_ratio della valuta forte
c9_ratio_weak = candle9_ratio della valuta debole

SE c9_ratio_strong > 0.05 E c9_ratio_weak < -0.05:
    mag = min(|c9_ratio_strong| + |c9_ratio_weak|, 1.0)
    c9_pts = round(25 × max(mag, 0.4))   # proporzionale alla magnitudine
    quality += c9_pts
    "C9 allineato"
ALTRIMENTI SE c9_ratio_strong > 0.05 OPPURE c9_ratio_weak < -0.05:
    quality += 10
    "C9 parzialmente allineato"

# Penalità: C9 in contro-direzione (forte bearish + debole bullish)
SE c9_ratio_strong < -0.05 E c9_ratio_weak > 0.05:
    quality -= 12
    "⚠️ C9 contro-direzione"
```

**NOTA:** Il C9 è il criterio con il punteggio massimo più alto (25 punti). Un C9 perfettamente allineato può da solo portare un setup dal grado B al grado A.

`quality = max(quality, 0)   # minimo 0, non può essere negativo`

### 5.3 Grading

```
quality ≥ 75 → "A+"
quality ≥ 60 → "A"
quality ≥ 45 → "B"
quality ≥ 30 → "C"
quality < 30 → "D"
```

### 5.4 Deduplicazione e Filtri

1. **Deduplicazione**: per ogni coppia di valute (es. EUR/USD e USD/EUR) tieni solo quella con quality score più alto
2. **Escludi coppie**: rimuovi coppie nella lista EXCLUDED (EURGBP)
3. **Filtro gruppi correlazione**: per ogni gruppo (es. AUDNZD, AUDCAD, NZDCAD), tieni SOLO il setup A/A+ migliore per quel gruppo. Gli altri vengono rimossi.

### 5.5 Ordinamento Finale

Ordina i setup per quality_score discendente.

---

## 6. SISTEMA DI NOTIFICHE

### 6.1 Alert Telegram — Formato Messaggi

Dopo ogni ciclo di analisi, confronta i segnali A/A+ **stabilizzati** con lo stato precedente (salvato in un file JSON locale).

**Nuovi segnali (ENTERED):**
```
🟢 NUOVI SETUP (HH:MM DD/MM)

  COPPIA — ⬆ LONG / ⬇ SHORT
  Grado: A+ | Score: 85
```

**Segnali rimossi (EXITED):**
```
🔴 SETUP RIMOSSI (HH:MM DD/MM)

  ✖ COPPIA — ⬆ LONG / ⬇ SHORT
```

### 6.2 Stabilizzazione a 5 Livelli (Anti-Flickering Segnali)

Il sistema previene l'oscillazione di segnali che entrano e escono dalla classifica A/A+ ogni 1-2 ore. L'algoritmo si applica **sia alle valute (Forex) che agli asset** (sezione 11.9).

**Parametri:**
```
GRADE_HYSTERESIS_POINTS      = 5     # un A (≥60) esce solo se scende sotto 55
SIGNAL_CONFIRMATION_REFRESHES = 2    # deve essere A/A+ per 2 refresh consecutivi per entrare
SIGNAL_MIN_RESIDENCE_HOURS   = 4     # resta in classifica almeno 4 ore
SIGNAL_GRACE_REFRESHES       = 2     # 2 refresh sotto soglia prima dell'uscita
SCORE_SMOOTHING_ALPHA        = 0.5   # smoothing EMA sul composito
```

#### Layer 1 — HYSTERESIS (uscita)

Un segnale che era A/A+ (score ≥ 60) esce dalla classifica **solo** se scende sotto `60 − GRADE_HYSTERESIS_POINTS = 55`. Se il score è tra 55 e 59 (grado nominale B), viene **mantenuto**.

Eccezione: se `score == 0` (segnale completamente sparito dal calcolo) → esce subito, nessuna stabilizzazione.

#### Layer 2 — RESIDENZA MINIMA (uscita)

Anche se il score scende sotto la soglia di hysteresis, il segnale **resta** in classifica per almeno `SIGNAL_MIN_RESIDENCE_HOURS` (4 ore) dal momento del suo ingresso (`entered_at`).

#### Layer 3 — GRACE PERIOD (uscita)

Dopo che hysteresis e residenza sono scaduti, il segnale ha ancora un **grace counter**: resta per `SIGNAL_GRACE_REFRESHES` (2) refresh consecutivi sotto soglia prima dell'uscita definitiva. Il counter viene resettato a 0 se il segnale torna A/A+.

#### Layer 4 — CONFIRMATION (ingresso) ⭐

Un segnale **nuovo** (non presente nello stato precedente) NON entra subito in classifica. Deve essere A/A+ per **`SIGNAL_CONFIRMATION_REFRESHES` refresh consecutivi** (= 2 ore con refresh orario) prima di essere promosso.

```
Flusso per un segnale nuovo:

Refresh 1: NZD/CHF LONG diventa A (score 65)
           → NON entra subito, va in "pending_pairs" con consecutive_count = 1
           → Nessun alert Telegram

Refresh 2: NZD/CHF LONG è ancora A (score 62)
           → consecutive_count passa a 2 → raggiunto SIGNAL_CONFIRMATION_REFRESHES
           → PROMOSSO: entra ufficialmente in classifica
           → Alert Telegram: "🟢 NUOVO SETUP: NZD/CHF LONG"

Flusso se il segnale sparisce prima della conferma:

Refresh 1: AUD/JPY LONG diventa A+ (score 78)
           → pending_pairs con consecutive_count = 1

Refresh 2: AUD/JPY LONG scende a B (score 52)
           → NON è più A/A+ → rimosso silenziosamente da pending
           → Nessun alert Telegram (mai entrato ufficialmente)
```

#### Layer 5 — SMOOTHING EMA (anti-oscillazione composito)

Il composito viene blendato con il valore precedente: `α × nuovo + (1 − α) × vecchio` con `α = 0.5`. Il valore precedente è persistito in `cache/prev_composite.json`.

#### Ordine di valutazione (per ogni refresh)

```
PER ogni segnale nello stato precedente (previous_top):
    1. Se è ancora A/A+ → MANTIENI, resetta grace_counter a 0
    2. Se score == 0 (sparito) → ESCI subito
    3. Se score ≥ grade_exit_threshold (55) → MANTIENI per hysteresis
    4. Se ore_dall_ingresso < MIN_RESIDENCE_HOURS (4) → MANTIENI per residenza
    5. Se grace_counter < GRACE_REFRESHES (2) → MANTIENI, incrementa grace_counter
    6. Altrimenti → ESCI definitivamente

PER ogni segnale A/A+ NON nello stato precedente:
    7. Se è in pending_pairs → incrementa consecutive_count
       Se consecutive_count ≥ CONFIRMATION_REFRESHES (2) → PROMUOVI a ingresso
       Altrimenti → resta in pending
    8. Se NON è in pending → aggiungi a pending con count = 1

SET FINALE = (precedenti mantenuti) ∪ (confermati da pending)
ENTERED = set_finale − previous_top     (nuovi ingressi veri)
EXITED  = previous_top − set_finale     (uscite vere, dopo tutti i livelli)
```

### 6.3 Stato Persistente (JSON)

```json
{
  "pairs": ["NZD/CHF LONG", "GBP/JPY SHORT"],
  "pair_details": {
    "NZD/CHF LONG": {
      "entered_at": "2026-03-04T10:00:00+01:00",
      "last_seen_at": "2026-03-04T14:00:00+01:00",
      "grace_counter": 0,
      "last_score": 65.0
    }
  },
  "pending_pairs": {
    "AUD/JPY LONG": {
      "first_seen_at": "2026-03-04T14:00:00+01:00",
      "consecutive_count": 1,
      "last_score": 62.0
    }
  },
  "active_setups": [ ... ],
  "all_setups": [ ... ],
  "suppressed_setups": [ ... ],
  "updated": "2026-03-04T14:00:00+01:00"
}
```

I campi `active_setups` / `all_setups` / `suppressed_setups` vengono usati dalla dashboard per mostrare gli stessi dati del Telegram (source of truth unica).

### 6.4 Notifiche Android Locali

Usa il sistema di notifiche native. Mostra:
- Titolo: "🟢 Nuovi Setup A/A+"
- Corpo: "Nuovi segnali: EUR/USD LONG, GBP/JPY SHORT"

### 6.5 Storico Segnali

Ogni ingresso/uscita viene registrato in `cache/signal_history.json`:
- Conserva gli ultimi `SIGNAL_HISTORY_MAX_DAYS = 90` giorni
- Registra: coppia, direzione, grado, score, timestamp_ingresso, timestamp_uscita

---

## 7. PIPELINE COMPLETA (eseguita ad ogni ciclo)

### Ordine di esecuzione:

1. **Fetch dati H1** — 28 coppie forex + 8 futures (`interval=1h, range=60d`, delay 1.5s)
2. **Resample H1 → H4** — localmente (Open→first, High→max, Low→min, Close→last, Volume→sum)
3. **Fetch dati D1** — 28 coppie forex + 8 futures (`interval=1d, range=1y`, delay 1.5s)
4. **Analisi H1** su tutti i dati H1 (12 moduli):
   - `compute_price_action_scores`
   - `compute_volume_scores`
   - `compute_candle9_scores` ← **C9 score per composito**
   - `compute_composite_scores` (PA + Volume + COT + C9)
   - `compute_momentum_rankings`
   - `classify_trend_vs_reversion`
   - `compute_rolling_strength` (include C9 rolling)
   - `compute_atr_context`
   - `compute_velocity_scores`
   - `compute_trend_structure`
   - `compute_strength_persistence`
   - `compute_candle9_signal` ← **C9 signal per display**
5. **Analisi H4** su tutti i dati H4 (stessi 12 moduli)
6. **Analisi D1** su tutti i dati D1 (stessi 12 moduli)
7. **Blend multi-timeframe** (H1 × 0.30 + H4 × 0.40 + D1 × 0.30, con D1 Decay)
8. **Smoothing composito** (EMA α=0.5 con precedente)
9. **Calcolo trade setups** sui dati blended (12 criteri incluso C9)
10. **Check & Notify** per segnali A/A+

---

## 8. INTERFACCIA UTENTE (3 Tab)

### 8.1 Tab "Dashboard" — Panoramica completa

**Sezione 1: Classifica Forza Valutaria**
- Grafico a barre orizzontali (0-100) per le 8 valute
- Ordinate dal composite più alto al più basso
- Colori: ≥80 verde brillante, ≥70 verde, ≥55 verde chiaro, ≥45 grigio, ≥35 arancione, ≥20 rosso, <20 rosso acceso
- Ogni barra mostra: CCY: score

**Sezione 2: Gauge di Forza**
- 8 gauge circolari (ProgressRing), 2 per riga
- Ogni gauge mostra: nome valuta (colorato per valuta), punteggio composito al centro del ring, label (STRONG BUY / BUY / SLIGHT BUY / NEUTRAL / SLIGHT SELL / SELL / STRONG SELL), momentum delta, **Candle-9 signal** con ratio (es. "🟢 BULLISH +0.15%"), breakdown H1/H4/D1 scores con D1 Decay indicator (es. "H1: 72 | H4: 65 | D1: 58 | ⏬D1 −35%"), concordance label (✅ ALLINEATI BULL / ⚠️ DIVERGENZA / ➖ NEUTRO)

**Colori valute:**
```
EUR: #3399FF  (blu)
GBP: #00CC00  (verde)
AUD: #FF9900  (arancione)
NZD: #00CCCC  (ciano)
CAD: #996633  (marrone)
CHF: #CC66FF  (viola)
JPY: #FF3333  (rosso)
USD: #FFFFFF  (bianco)
```

**Signal Label:**
- score ≥ 80 → "STRONG BUY"
- score ≥ 65 → "BUY"
- score ≥ 55 → "SLIGHT BUY"
- score ≥ 45 → "NEUTRAL"
- score ≥ 35 → "SLIGHT SELL"
- score ≥ 20 → "SELL"
- score < 20 → "STRONG SELL"

**Sezione 3: Confronto H1 vs H4 vs D1**
- Tabella comparativa per le 8 valute con colonne: Valuta, Score H1, Score H4, Score D1, ⏬D1 Decay, Score Composito, Concordanza
- Ogni score ha una barra di progresso 0-100
- Se D1 Decay > 0, mostra la percentuale di riduzione (es. "−35%")
- Caption: "H1 (reattività, 30%) vs H4 (stabilità, 40%) vs D1 (trend di fondo, 30%) — Se H1 e H4 divergono, il peso D1 viene ridotto (⏬Decay) per accelerare le transizioni."

**Sezione 4: Candle-9 Panoramica**
- Tabella con 3 gruppi: 🟢 BULLISH, 🔴 BEARISH, ➖ NEUTRO
- Per ogni valuta: nome, segnale, variazione vs C9 (Δ vs C9: +0.15%)
- Ordinate per candle9_ratio decrescente

**Sezione 5: Momentum**
- Lista ordinata dal delta maggiore al minore
- Per ogni valuta: icona (🚀 se positivo, 📉 se negativo, ➖ se zero), nome valuta, delta, accelerazione, rank label

**Sezione 6: Classificazione Trend / Mean Revert**
- Per ogni valuta: emoji (📈 TREND, 🔄 MEAN_REVERT, ⚖️ MIXED), nome, tipo, barra di progresso del trend_score, valore numerico, direzione suggerita (LONG se composite ≥ 50, SHORT se < 50)

**Sezione 7: Volatilità & Velocità**
- Per ogni valuta: emoji regime (🟢 LOW, 🔵 NORMAL, 🟠 HIGH, 🔴 EXTREME), nome, regime, barra ATR percentile, valore ATR, velocity label

**Sezione 8: Heatmap Differenziale**
- Matrice 8×8 delle 8 valute
- Ogni cella mostra il differenziale composito tra la riga (base) e la colonna (quote)
- Colori: verde scuro ≥15, verde ≥8, verde chiaro ≥3, rosso scuro ≤-15, rosso ≤-8, marrone ≤-3, grigio scuro altrimenti. Diagonale vuota.

### 8.2 Tab "Setup" — Trade Setups

**Sezione 1: Segnali A/A+ Attivi**
- Card evidenziate per ogni segnale con grade A+ o A
- Ogni card mostra: badge grado (verde), coppia + direzione, quality score, differenziale forza, motivi principali

**Sezione 2: Tabella Setup Completa**
- Tabella con colonne: Grado, Coppia, Direzione, Score, ΔForza, Motivi
- Mostra i top 20 setup di grado A+, A, B (se non ci sono, mostra i top 15 generici)
- Grade emoji: A+/A = 🟢, B = 🟡, C = 🟠, D = 🔴

**Sezione 3: Riepilogo Completo**
- Tabella per le 8 valute con: Valuta, Score composito, Label, Price Action, Volume, COT, C9, Momentum delta, Classificazione

### 8.3 Tab "Monitor" — Monitoraggio e Notifiche

**Controlli:**
- Pulsante "▶ Avvia Monitor" / "⏸ Ferma Monitor"
- Pulsante "🔄 Aggiorna Ora" (refresh manuale)
- Barra di progresso durante il download/analisi
- Testo di stato
- Ultimo aggiornamento timestamp

**Info Telegram:**
- Indicatore che le notifiche Telegram sono attive

**Esecuzione in Background:**
- Spiegazione che bisogna disattivare l'ottimizzazione batteria
- Pulsante per aprire le impostazioni batteria Android

**Segnali Attivi:**
- Lista dei segnali A/A+ correnti con badge colorato

**Diagnostica:**
- Banner con risultati del network probe
- Log delle ultime 50 righe (scrollabile, colorato per livello: rosso errori, giallo warning, grigio info)

---

## 9. COMPORTAMENTO DELL'APP

### 9.1 Primo Avvio
1. L'app parte sulla tab Monitor
2. Avvia automaticamente il primo ciclo di analisi (fetch + analisi)
3. Durante il download mostra la progress bar con messaggi di avanzamento
4. Dopo il primo ciclo completato, avvia automaticamente il monitor in background
5. L'utente può navigare sulle altre tab per vedere i risultati

### 9.2 Monitor in Background
- Ciclo automatico ogni 60 minuti
- Il monitor gira in un thread separato (non-daemon, per sopravvivere al background)
- Un thread di keep-alive fa un no-op ogni 30 secondi per evitare che Android uccida il processo
- Quando l'app va in background, il monitor continua a girare
- Quando l'app torna in primo piano, la UI si aggiorna con gli ultimi dati

### 9.3 Aggiornamento UI
- La progress bar e il testo di stato si aggiornano al massimo ogni 2 secondi (throttling) per evitare che page.update() blocchi il thread di download su Android
- Usa pub/sub per notificare la UI quando ci sono nuovi dati

### 9.4 Tema e Stile
- Tema scuro: sfondo #0d1117
- Card con sfondo semi-trasparente bianco (4% opacity)
- Bordi arrotondati (10px)
- Font bianchi con grigi per testo secondario
- Navigazione bottom bar con 3 tab: Dashboard (📊), Setup (📈), Monitor (🔔)

---

## 10. GESTIONE ERRORI

- Se il download fallisce completamente (0/28 coppie): mostra errore a schermo e lancia diagnostica di rete automatica
- La diagnostica testa: SSL, certificati, DNS, connessione TCP, handshake SSL, chiamata API
- Se una singola coppia fallisce: salta e continua con le altre
- Dopo 10 fallimenti consecutivi con 0 successi: abort e mostra errore
- Tutte le eccezioni vengono logate nel buffer in-memory e mostrate nella tab Monitor
- Il monitor continua a funzionare anche dopo un errore (riprova al prossimo ciclo)

---

## 11. MODULO ASSET — Dashboard Forza Asset Finanziari

L'app include una **seconda pagina** (tab "📊 Assets") che analizza **8 asset finanziari** (oro, argento, petrolio, bitcoin, indici azionari, grano) con la **stessa logica del Currency Strength** ma adattata per strumenti individuali (non coppie valutarie).

Le differenze principali rispetto alla sezione Forex sono:
- **Timeframe**: H4 + Daily + Weekly (non H1/H4/D1)
- **W Decay** al posto di D1 Decay (il peso Weekly viene ridotto quando H4 e Daily divergono)
- **Nessuna logica base/quote**: ogni asset ha un punteggio diretto (non aggregazione su 7 coppie)
- **Trade setup**: 11 criteri (non 12), confronto asset vs neutro (50), non coppia vs coppia
- **COT**: keyword CFTC specifiche per commodity/indici; solo DAX non ha report COT (indice europeo Eurex)

---

### 11.1 Asset Monitorati

**8 asset con relativi ticker Yahoo Finance:**

| Asset   | Ticker YF | Label           | Icona | Classe    |
|---------|-----------|-----------------|-------|-----------|
| GOLD    | GC=F      | Oro             | 🥇    | Commodity |
| SILVER  | SI=F      | Argento         | 🥈    | Commodity |
| WTI     | CL=F      | Petrolio WTI    | 🛢️    | Commodity |
| BITCOIN | BTC-USD   | Bitcoin         | ₿     | Crypto    |
| NASDAQ  | NQ=F      | Nasdaq 100      | 📈    | Index     |
| SP500   | ES=F      | S&P 500         | 📊    | Index     |
| DAX     | ^GDAXI    | DAX 40          | 🇩🇪    | Index     |
| WHEAT   | ZW=F      | Grano           | 🌾    | Commodity |

**Ticker Volume:** identici ai ticker principali (il volume è già incluso nel dato OHLCV di ogni asset).

### 11.2 COT — Keyword CFTC per Asset

| Asset   | Keyword CFTC    | Note                                |
|---------|----------------|--------------------------------------|
| GOLD    | GOLD           |                                      |
| SILVER  | SILVER         |                                      |
| WTI     | CRUDE OIL      | WTI Crude Oil CFTC                   |
| BITCOIN | BITCOIN        | CME Bitcoin Futures                  |
| NASDAQ  | NASDAQ         | NASDAQ-100 Consolidated              |
| SP500   | S&P 500        | S&P 500 Consolidated                 |
| DAX     | *(nessuno)*    | Non è su CFTC → score neutro 50      |
| WHEAT   | WHEAT          |                                      |

**Parametri scoring COT identici alla sezione Forex** (sezione 1.2): stessi URL CFTC, `COT_PERCENTILE_LOOKBACK = 52`, `COT_EXTREME_LONG = 90`, `COT_EXTREME_SHORT = 10`.

Il modulo `asset_cot_data.py` scarica il report Legacy Futures-Only dalla CFTC, filtra le righe per `ASSET_COT_KEYWORDS`, estrae `net_speculative = noncomm_long − noncomm_short` e calcola:
```
percentile = (somma(lookback ≤ latest) / len(lookback)) × 100
change_norm = clip(weekly_change / std(lookback), -2, 2) × 10
score = clip(percentile + change_norm, 0, 100)
```

Cache: `cache/asset_cot_data.csv`, max age 24 ore.

### 11.3 Timeframe e Download Dati

**3 timeframe** (diversi dal Forex):

| Timeframe | yfinance interval | yfinance period | Resample |
|-----------|-------------------|-----------------|----------|
| H4        | 1h                | 60d             | 4h       |
| Daily     | 1d                | 1y              | *(nessuno)* |
| Weekly    | 1wk               | 5y              | *(nessuno)* |

**Procedura di download** (identica struttura al Forex):
1. Controlla cache Parquet: `cache/asset_{ASSET}_{TIMEFRAME}.parquet` (max age 3600s)
2. Se fresco → carica da cache
3. Altrimenti: `yf.Ticker(ticker).history(period=..., interval=..., auto_adjust=True)`
4. Retry con backoff esponenziale: 3 tentativi, wait `2^(attempt+1)` secondi
5. Se download fallisce e cache esiste (anche stantia) → usa cache stantia con warning
6. Rimuovi colonne non necessarie (Dividends, Stock Splits, Capital Gains)
7. Se resample necessario (H4): aggrega OHLCV a candele 4h
8. Salva in Parquet
9. Delay `0.3s` tra download consecutivi (anti rate-limit)

**Resample OHLCV:**
```
Open  → first
High  → max
Low   → min
Close → last
Volume → sum
```

### 11.4 Pesi Multi-Timeframe (H4 + Daily + Weekly)

```
ASSET_COMPOSITE_WEIGHT_H4     = 0.30   # reattività intraday
ASSET_COMPOSITE_WEIGHT_DAILY  = 0.40   # base giornaliera
ASSET_COMPOSITE_WEIGHT_WEEKLY = 0.30   # stabilità strutturale
```

### 11.5 W Decay — Riduzione Dinamica del Peso Weekly

Quando H4 e Daily divergono (distanti o su lati opposti), il peso Weekly viene **ridotto** e ridistribuito proporzionalmente a H4 e Daily. Identica logica del D1 Decay (sezione 1.7) ma applicata al Weekly.

```
ASSET_W_DIVERGENCE_THRESHOLD = 10   # |H4−Daily| minimo per attivare il decay
ASSET_W_DIVERGENCE_MAX       = 40   # |H4−Daily| a cui il decay è massimo
ASSET_W_DECAY_MIN_WEIGHT     = 0.05 # peso W minimo (non scende mai sotto 5%)
ASSET_W_DECAY_OPPOSITE_BONUS = 0.3  # bonus extra decay se H4 e Daily su lati opposti del 50
```

**Algoritmo W Decay per ogni asset:**
```
gap = |score_H4 − score_Daily|
opposite_sides = (score_H4 ≥ 50 AND score_Daily < 50) OR (score_H4 < 50 AND score_Daily ≥ 50)

SE gap > W_DIVERGENCE_THRESHOLD:
    raw_decay = min((gap − THRESHOLD) / (MAX − THRESHOLD), 1.0)
    SE opposite_sides:
        raw_decay = min(raw_decay + OPPOSITE_BONUS, 1.0)

    eff_w = max(WEIGHT_WEEKLY × (1 − raw_decay), MIN_WEIGHT)   # peso W ridotto
    freed = WEIGHT_WEEKLY − eff_w                                # peso liberato
    ratio_h4d1 = w_h4 / (w_h4 + w_daily)
    eff_h4    = w_h4 + freed × ratio_h4d1                       # ridistribuito
    eff_daily = w_daily + freed × (1 − ratio_h4d1)              # ridistribuito
ALTRIMENTI:
    eff_h4, eff_daily, eff_w = w_h4, w_daily, w_weekly          # nessun decay
```

---

### 11.6 Motore di Analisi Asset

Ogni asset viene analizzato individualmente su ciascun timeframe. Gli indicatori tecnici sono **identici** a quelli del Forex (sezione 3): RSI(14), ROC(4/12/24), EMA(20/50/200), ADX(14), ATR(14), Hurst, Efficiency Ratio(20).

#### 11.6.1 Price Action Score (per asset)

```python
rsi_val    = RSI(close, 14)                       # 0-100 diretto
roc_f      = ROC(close, 4)
roc_m      = ROC(close, 12)
roc_s      = ROC(close, 24)
avg_roc    = roc_f × 0.5 + roc_m × 0.3 + roc_s × 0.2
roc_score  = 50 + clip(avg_roc × 10, -50, 50)

ema_score  = media di [pct_above_EMA × 15 + 50] per EMA(20), EMA(50), EMA(200)
             dove pct_above = ((close / EMA) − 1) × 100

score_PA   = rsi_val × 0.35 + roc_score × 0.40 + ema_score × 0.25
```

**Differenza dal Forex:** il punteggio è diretto sull'asset, non aggregato da 7 coppie con base/quote.

#### 11.6.2 Volume Score (per asset)

```
volume_ratio = volume_corrente / SMA(volume, 20)
deviation    = price_score − 50
amplified    = deviation × clip(volume_ratio, 0.5, 2.0)
score_VOL    = 50 + amplified
```

Il volume amplifica o attenua la deviazione dal neutro. Ratio > 1 = sopra media → amplifica.

#### 11.6.3 Candle-9 Score (C9)

Identico al Forex (sezione 3.12): 3 componenti su ultimi 9 periodi.

```
pct_change = ((close_attuale − close_9_candele_fa) / close_9_candele_fa) × 100

magnitude_score = 50 + clip(pct_change × 25, -50, 50)                    # peso 50%

slope = polyfit(x, close_ultimi_10, grado=1)[0]
slope_pct = (slope / mean(close)) × 100
velocity_score  = 50 + clip(slope_pct × 200, -50, 50)                    # peso 35%

SE pct_change > 0: consistency = (candele con diff > 0) / totale
SE pct_change < 0: consistency = (candele con diff < 0) / totale
consistency_bonus = consistency × 10
consistency_score = 50 + consistency_bonus                               # peso 15%

c9_score = magnitude_score × 0.50 + velocity_score × 0.35 + consistency_score × 0.15
clip(0, 100)
```

Nessuna inversione: il pct_change è già direzionale (positivo = asset sale, negativo = asset scende).

**Segnale Candle-9:**
Soglie per il segnale: `±0.1%` (più alto del Forex che usa ±0.05%).
```
pct_change > +0.1% → 🟢 BULLISH
pct_change < -0.1% → 🔴 BEARISH
altrimenti          → ➖ NEUTRO
```

#### 11.6.4 Composito 4 Componenti

```
composite = PA × 0.25 + Volume × 0.20 + COT × 0.30 + C9 × 0.25
```
Stessi pesi della sezione Forex (sezione 1.4).

Etichette:
```
≥ 80 → VERY STRONG
≥ 70 → STRONG
≤ 20 → VERY WEAK
≤ 30 → WEAK
altrimenti → NEUTRAL
```

Alert automatico se ≥ 80 ("Forza estrema") o ≤ 20 ("Debolezza estrema"). Aggiunta COT crowded se rilevato.

#### 11.6.5 Momentum e Accelerazione

Usa i rendimenti del prezzo di chiusura (close.pct_change), non del composito:

```
rets = close.pct_change()
cum_recent = somma dei returns delle ultime 6 barre × 100
cum_prev   = somma dei returns delle 6 barre prima × 100

delta        = cum_recent
acceleration = cum_recent − cum_prev
```

Etichette:
```
delta ≥ +5  → 🚀 GAINING FAST
delta ≤ -5  → 📉 LOSING FAST
delta > 0   → ↗ Gaining
delta < 0   → ↘ Losing
delta == 0  → → Flat
```

#### 11.6.6 Classificazione Trend vs Mean-Reversion

Identica alla sezione Forex (sezione 3.6), con le **stesse soglie** da config.py:
```
adx_norm   = clip((avg_adx − 20) / (25 − 20), 0, 1) × 100      # ADX_RANGE=20, ADX_TREND=25
hurst_norm = clip((hurst − 0.45) / (0.55 − 0.45), 0, 1) × 100  # HURST_REVERT=0.45, TREND=0.55
er_norm    = clip((er − 0.20) / (0.40 − 0.20), 0, 1) × 100     # ER_RANGE=0.20, ER_TREND=0.40

trend_score = adx_norm × 0.40 + hurst_norm × 0.35 + er_norm × 0.25
clip(0, 100)
```

Classificazione:
```
≥ 65 → TREND_FOLLOWING
≤ 35 → MEAN_REVERTING
altrimenti → MIXED
```

#### 11.6.7 ATR / Volatilità

```
atr_pct        = ATR(14) / close × 100       # ATR come % del prezzo
atr_percentile = rank percentile su finestra di lookback

Regime:
  ≥ 85 → EXTREME
  ≥ 65 → HIGH
  ≥ 35 → NORMAL
  < 35 → LOW
```

#### 11.6.8 Velocity

Identica alla sezione Forex (sezione 3.8):

```
rets = close.pct_change()
cum = rets.rolling(20).sum() × 100
recent = ultime 20 barre di cum

directional_change = |ultimo − primo|
path_length = somma(|diff| per ogni barra)
efficiency = directional_change / path_length

std_recent = deviazione standard delle ultime 20 barre
magnitude = directional_change / std_recent
magnitude_factor = clip(magnitude / 2.0, 0.3, 1.0)

velocity_norm = clip(efficiency × magnitude_factor × 120, 0, 100)
```

Etichette:
```
  ≥ 70 → ⚡ VERY FAST
  ≥ 50 → 🏃 FAST
  ≥ 35 → 🚶 MODERATE
  ≥ 20 → 🐢 SLOW
  < 20 → 🧊 STALE
```

#### 11.6.9 Trend Structure (Cascata EMA)

Identica alla sezione Forex (sezione 3.9) ma applicata al singolo asset (non aggregata su coppie):

```
EMA_FAST(20), EMA_MEDIUM(50), EMA_SLOW(200) calcolate sull'ultimo close

Se EMA20 > EMA50 > EMA200 → alignment = +1.0  (cascata completa bull)
Se EMA20 < EMA50 < EMA200 → alignment = −1.0  (cascata completa bear)
Se EMA20 > EMA200 (ma non cascade completa) → alignment = +0.3
Se EMA20 < EMA200 → alignment = −0.3
Altrimenti → alignment = 0.0
```

Etichette:
```
alignment ≥ +0.5  → 📈 CASCATA BULL
alignment ≤ −0.5  → 📉 CASCATA BEAR
alignment ≥ +0.2  → ↗ Parziale bull
alignment ≤ −0.2  → ↘ Parziale bear
altrimenti        → ➖ Nessuna cascata
```

#### 11.6.10 Rolling Strength

Forza composita mobile per ogni asset, calcolata come media mobile a 20 barre del composito.
Include il rolling del C9 con: `c9_rolling = magnitude × 0.60 + velocity × 0.40`.

#### 11.6.11 Matrice Correlazione

Matrice 8×8 di correlazione tra i rendimenti giornalieri degli asset (finestra 30 giorni). Usata nel Radar Chart per identificare asset correlati/decorrelati.

#### 11.6.12 Persistence (Persistenza Forza)

Analisi della persistenza: % di barre in cui il rolling strength è sopra 55 (bull) o sotto 45 (bear), con slope lineare.

```
persistence > 0 → direzione BULL
persistence < 0 → direzione BEAR

|persistence| ≥ 0.7 → 🔒 PERSISTENTE
|persistence| ≥ 0.4 → Trending
< 0.4              → 🔀 Inconsistente
```

#### 11.6.13 Smoothing Anti-Flickering

Per ridurre le oscillazioni del composito:
```
smoothed = α × nuovo + (1 − α) × precedente     (α = 0.5)
```
Il precedente viene salvato in `cache/asset_prev_composite.json` e ricaricato al refresh successivo.

---

### 11.7 Blending Multi-Timeframe (H4 + Daily + Weekly)

Identico al blending Forex ma con 3 timeframe H4/Daily/Weekly. Per ogni asset:

1. **Composite blendato** (con W Decay per-asset): `PA`, `Volume`, `COT`, `C9` e `composite` tutti blended con pesi effettivi (dopo decay).
2. **Momentum blendato**: `delta` e `acceleration` con pesi originali.
3. **Classification blendato**: media pesata di `adx_avg`, `hurst`, `eff_ratio`, `trend_score`.
4. **Rolling strength blendato**: merge dei DataFrame con weight, reindex+ffill per allineare frequenze diverse.
5. **Velocity blendato**: media pesata di `velocity_norm` e `bars_to_move`.
6. **ATR blendato**: media pesata di `atr_pct` e `atr_percentile`, re-label del regime.
7. **Candle-9 blendato**: media pesata del `candle9_ratio`, re-label del segnale.
8. **Trend structure blendato**: media pesata di `ema_alignment`, re-label.
9. **Persistence blendato**: media pesata di `persistence` e `slope`.

**Concordanza** (calcolata per ogni asset):
```
SE tutti i 3 TF ≥ 55 → ✅ ALLINEATI BULL
SE tutti i 3 TF ≤ 45 → ✅ ALLINEATI BEAR
SE almeno uno ≥ 55 E almeno uno ≤ 45 → ⚠️ DIVERGENZA
ALTRIMENTI → ➖ NEUTRO
```

---

### 11.8 Trade Setup Asset (11 Criteri)

Per ogni asset con composito ≥ 55 (LONG) o ≤ 45 (SHORT), viene calcolato un quality_score.

**Differenza chiave dal Forex:** il setup è per un **singolo asset** rispetto al neutro (50), non per una coppia valutaria. Il differenziale minimo è `|composito − 50| ≥ MIN_DIFFERENTIAL_THRESHOLD` (8 punti).

#### Criterio 1: Distanza dal Neutro (0-30 punti)
```
dist = |composite − 50|
pts  = min(dist × 1.0, 30)
```

#### Criterio 2: Momentum Concordante (0-20 punti)
```
SE LONG e delta > 0 (o SHORT e delta < 0) → +20 ("Momentum allineato")
SE delta ≠ 0 ma non allineato → +10 ("Momentum parziale")
```

#### Criterio 3: Regime Trending (0-15 punti)
```
TREND_FOLLOWING → +15
MIXED           → +7
```

#### Criterio 4: Volatilità (0-15 punti, -5 penalità)
```
NORMAL o LOW     → +10
HIGH             → +5
EXTREME          → −5
```

#### Criterio 5: COT Concordante (0-10 punti, dimezzato se stale)
```
SE bias allineato alla direzione → +10 (× 0.5 se COT > 10 giorni)
Penalità:
  CROWDED_LONG  e direzione LONG  → −10
  CROWDED_SHORT e direzione SHORT → −10
```

#### Criterio 6: Sinergia Forza + Momentum (0-5 punti bonus)
```
SE distanza ≥ 15 E momentum allineato alla direzione → +5
```

#### Criterio 7: Velocity (0-10 punti, -3 penalità)
```
velocity_norm ≥ 65 → +10
velocity_norm ≥ 40 → +5
velocity_norm < 15 → −3 ("Movimento stagnante")
```

#### Criterio 8: Trend Structure / EMA Alignment (0-8 punti, -5 penalità)
Per LONG:
```
ema_alignment ≥ 0.5  → +8 ("Cascata EMA rialzista")
ema_alignment ≥ 0.2  → +4
ema_alignment ≤ -0.3 → −5 ("Cascata EMA contro-tendenza")
```
Per SHORT (valori invertiti):
```
ema_alignment ≤ -0.5 → +8
ema_alignment ≤ -0.2 → +4
ema_alignment ≥ 0.3  → −5
```

#### Criterio 9: Accelerazione Momentum (0-5 punti, -3 penalità)
```
SE accelerazione allineata alla direzione → +5
SE accelerazione presente ma non allineata → +2
SE LONG e accel < 0 e delta ≤ 0 → −3 ("Momentum in decelerazione")
SE SHORT e accel > 0 e delta ≥ 0 → −3
```

#### Criterio 10: Persistenza Forza (0-8 punti, -3 penalità)
```
SE LONG e persistence ≥ 0.5 (o SHORT e persistence ≤ -0.5) → +8
SE LONG e persistence ≥ 0.3 (o SHORT e persistence ≤ -0.3) → +4
SE |persistence| < 0.2 → −3 ("Forza non persistente")
```

#### Criterio 11: Candle-9 Concordante (0-25 punti, -12 penalità)
```
SE direzione allineata e |c9_ratio| > 0.1%:
    pts = min(|c9_ratio| × 25, 25)

SE direzione allineata e |c9_ratio| > 0.05% (parziale):
    pts = +10

Penalità: C9 in contro-direzione (|c9_ratio| > 0.1%):
    pts = −12
```

#### Grading
```
quality ≥ 75 → A+
quality ≥ 60 → A
quality ≥ 45 → B
quality ≥ 30 → C
quality < 30 → D
```

**NOTA:** Manca il Criterio "Concordance H1/H4/D1" e il "Session Awareness" presenti nel Forex (criteri 6 e 11). Per gli asset: nessun criterio sessione, nessun criterio concordanza nel quality score (la concordanza è mostrata nella UI ma non entra nel calcolo del punteggio).

---

### 11.9 Sistema di Alert Asset (condiviso con Telegram Forex)

Gli alert Telegram per gli asset usano lo **stesso sistema di stabilizzazione a 5 livelli** delle valute (sezione 6):

1. **Hysteresis**: `GRADE_HYSTERESIS_POINTS = 5` → A/A+ (≥60) esce solo sotto 55
2. **Confirmation**: `SIGNAL_CONFIRMATION_REFRESHES = 2` → 2 ore consecutive come A/A+ prima dell'ingresso
3. **Min Residence**: `SIGNAL_MIN_RESIDENCE_HOURS = 4` → resta almeno 4 ore
4. **Grace Period**: `SIGNAL_GRACE_REFRESHES = 2` → 2 refresh sotto soglia prima dell'uscita
5. **Smoothing EMA**: `SCORE_SMOOTHING_ALPHA = 0.5`

**Stato**: salvato in `cache/asset_alert_state.json` con struttura:
```json
{
  "pairs": ["GOLD LONG", "NASDAQ SHORT"],
  "pair_details": { "GOLD LONG": { "entered_at": "...", "grace_counter": 0, "last_score": 72 } },
  "pending_pairs": { "SILVER LONG": { "first_seen_at": "...", "consecutive_count": 1 } },
  "active_setups": [ ... ],
  "all_setups": [ ... ],
  "updated": "2025-01-15T14:00:00+01:00"
}
```

Lo scheduler gestisce il salvataggio e l'invio Telegram. La dashboard **legge** lo stato senza modificarlo.

---

### 11.10 Pipeline Asset (nello scheduler)

La pipeline asset viene eseguita dallo scheduler **dopo** la pipeline Forex, con la stessa cadenza:

```
1. Scarica dati H4, Daily, Weekly per tutti gli 8 asset (fetch_all_assets per ciascun TF)
2. Scarica dati COT asset (load_asset_cot_data → compute_asset_cot_scores)
3. Esegui full_asset_analysis su ciascun TF (H4, Daily, Weekly)
4. Blend multi-timeframe → blend_asset_multi_timeframe
5. Smoothing composito (con stato precedente da cache/asset_prev_composite.json)
6. Calcola trade setups → compute_asset_trade_setups (11 criteri)
7. Stabilizzazione 5 livelli (hysteresis, confirmation, residence, grace, smoothing)
8. Salva stato in cache/asset_alert_state.json
9. Invia alert Telegram per nuovi ingressi/uscite
```

---

### 11.11 Interfaccia Utente — Pagina Assets

La pagina "📊 Assets" è organizzata in sezioni verticali:

**Sidebar:**
- Selettore timeframe: Composito (default) / H4 / Daily / Weekly
- Pesi blend (se Composito)
- Soglie (stesse del Forex: 70/80/30/20)
- Stato alert Telegram
- Sessione attiva corrente
- Pulsante "🔄 Aggiorna Dati Ora"

**Auto-refresh:** allineato alla chiusura candela oraria (prossima ora piena + 10s margine). Al cambio ora, `st.cache_data.clear()`.

**Sezioni principali (nell'ordine):**

1. **Banner Riassuntivo** — 5 metriche: Più Forte, Più Debole, Setup Attivi (A+/A), Bullish count, Bearish count

2. **Gauge Compositi** — Un donut chart per ogni asset (ordinati per forza), con:
   - Score numerico al centro
   - Label segnale (STRONG BUY / BUY / SLIGHT BUY / NEUTRAL / SLIGHT SELL / SELL / STRONG SELL)
   - W Decay % (se attivo)
   - Sub-score H4/Daily/Weekly (se Composito)
   - Badge momentum (delta %)
   - Badge Candle-9 (segnale + ratio %)
   - Mini sparkline ultimi 30 prezzi

3. **Classifica Forza** — Barre orizzontali 0-100, linea neutra a 50, soglie tratteggiate a 70/30

4. **Tabs per Classe** — Commodity / Crypto / Index / Tutti
   - Tabella con: Asset, Composito, Segnale, Price, Volume, COT, Momentum, Δ Mom, Candle-9, Regime, ADX, Hurst, Vol.Regime, Velocità
   - Se Composito: colonne aggiuntive H4, Daily, Weekly, Concordanza, ⏬W Decay

5. **Alert e Soglie** — Box colorati per asset con composito estremo (≥80 o ≤20) e COT crowded

6. **Momentum** — Due colonne: 🟢 Guadagnano Forza / 🔴 Perdono Forza (barre colorate con delta e accelerazione)

7. **Candle-9 Price Action** — Barchart orizzontale Δ% vs Candle 9 + tabella dettaglio

8. **Classificazione Trend** — Tre colonne: 📈 TREND FOLLOWING / ⚖️ MIXED / 🔄 MEAN REVERTING

9. **Volatilità & Velocità** — Expander con tabella: ATR%, Percentile, Vol.Regime, Velocità, Vel.Score

10. **Rolling Strength** — Grafico lineare evoluzione forza nel tempo, multiselect asset, linee soglia 50/70/30

11. **Radar Chart** — Scatterpolar con 5 assi: Price Action, Volume, COT, Trend Score, Velocity

12. **Trade Setups** — Tabella con: Grado, Asset, Direzione, Score (ProgressColumn), Forza, Stato (stabilizzazione), Motivi. Sincronizzato con scheduler Telegram se stato fresco (< 2h). Filtro per grado. Indicatori variazione: NUOVO, RIMOSSO, IN OSSERVAZIONE, PENDING.

13. **COT Overview** — Cards con percentile, bias, extreme per ogni asset + timeseries chart del net speculative storico

14. **Matrice Correlazione** — Heatmap 8×8 correlazione rendimenti 30gg (RdBu, -1 a +1)

**Footer:** versione, fonti dati, indicatori utilizzati, frequenza ottimale per timeframe.
