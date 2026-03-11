"""
Currency Strength Indicator - Configuration
============================================
Parametri globali, tickers, soglie e pesi per il calcolo della forza valutaria.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# VALUTE MONITORATE
# ═══════════════════════════════════════════════════════════════════════════════
CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"]

# ═══════════════════════════════════════════════════════════════════════════════
# COPPIE FOREX  (yfinance tickers)
# base = valuta al numeratore, quote = denominatore
# ═══════════════════════════════════════════════════════════════════════════════
FOREX_PAIRS = {
    "EURUSD": {"ticker": "EURUSD=X", "base": "EUR", "quote": "USD"},
    "GBPUSD": {"ticker": "GBPUSD=X", "base": "GBP", "quote": "USD"},
    "AUDUSD": {"ticker": "AUDUSD=X", "base": "AUD", "quote": "USD"},
    "NZDUSD": {"ticker": "NZDUSD=X", "base": "NZD", "quote": "USD"},
    "USDJPY": {"ticker": "USDJPY=X", "base": "USD", "quote": "JPY"},
    "USDCHF": {"ticker": "USDCHF=X", "base": "USD", "quote": "CHF"},
    "USDCAD": {"ticker": "USDCAD=X", "base": "USD", "quote": "CAD"},
    "EURGBP": {"ticker": "EURGBP=X", "base": "EUR", "quote": "GBP"},
    "EURJPY": {"ticker": "EURJPY=X", "base": "EUR", "quote": "JPY"},
    "EURCHF": {"ticker": "EURCHF=X", "base": "EUR", "quote": "CHF"},
    "EURAUD": {"ticker": "EURAUD=X", "base": "EUR", "quote": "AUD"},
    "EURNZD": {"ticker": "EURNZD=X", "base": "EUR", "quote": "NZD"},
    "EURCAD": {"ticker": "EURCAD=X", "base": "EUR", "quote": "CAD"},
    "GBPJPY": {"ticker": "GBPJPY=X", "base": "GBP", "quote": "JPY"},
    "GBPCHF": {"ticker": "GBPCHF=X", "base": "GBP", "quote": "CHF"},
    "GBPAUD": {"ticker": "GBPAUD=X", "base": "GBP", "quote": "AUD"},
    "GBPNZD": {"ticker": "GBPNZD=X", "base": "GBP", "quote": "NZD"},
    "GBPCAD": {"ticker": "GBPCAD=X", "base": "GBP", "quote": "CAD"},
    "AUDJPY": {"ticker": "AUDJPY=X", "base": "AUD", "quote": "JPY"},
    "AUDCHF": {"ticker": "AUDCHF=X", "base": "AUD", "quote": "CHF"},
    "AUDNZD": {"ticker": "AUDNZD=X", "base": "AUD", "quote": "NZD"},
    "AUDCAD": {"ticker": "AUDCAD=X", "base": "AUD", "quote": "CAD"},
    "NZDJPY": {"ticker": "NZDJPY=X", "base": "NZD", "quote": "JPY"},
    "NZDCHF": {"ticker": "NZDCHF=X", "base": "NZD", "quote": "CHF"},
    "NZDCAD": {"ticker": "NZDCAD=X", "base": "NZD", "quote": "CAD"},
    "CADJPY": {"ticker": "CADJPY=X", "base": "CAD", "quote": "JPY"},
    "CADCHF": {"ticker": "CADCHF=X", "base": "CAD", "quote": "CHF"},
    "CHFJPY": {"ticker": "CHFJPY=X", "base": "CHF", "quote": "JPY"},
}

# ═══════════════════════════════════════════════════════════════════════════════
# FUTURES CME  (volume proxy per il forex OTC)
# ═══════════════════════════════════════════════════════════════════════════════
FUTURES_TICKERS = {
    "EUR": "6E=F",
    "GBP": "6B=F",
    "JPY": "6J=F",
    "CHF": "6S=F",
    "AUD": "6A=F",
    "NZD": "6N=F",
    "CAD": "6C=F",
    "USD": "DX=F",   # Dollar Index
}

# ═══════════════════════════════════════════════════════════════════════════════
# COT  –  keyword per filtrare il report CFTC (Legacy Futures-Only)
# ═══════════════════════════════════════════════════════════════════════════════
COT_KEYWORDS = {
    "EUR": "EURO FX",
    "GBP": "BRITISH POUND",
    "JPY": "JAPANESE YEN",
    "CHF": "SWISS FRANC",
    "AUD": "AUSTRALIAN DOLLAR",
    "NZD": "NEW ZEALAND",
    "CAD": "CANADIAN DOLLAR",
    "USD": "U.S. DOLLAR INDEX",
}

# URL CFTC  –  Legacy, Futures-Only, formato testo combinato (anno corrente)
COT_BASE_URL = "https://www.cftc.gov/dea/newcot/deafut.txt"
COT_HIST_URL = "https://www.cftc.gov/files/dea/history/deahistfo{year}.zip"

# ═══════════════════════════════════════════════════════════════════════════════
# PESI COMPOSITI  (sommano a 1.0)
# ═══════════════════════════════════════════════════════════════════════════════
WEIGHT_PRICE_ACTION = 0.25
WEIGHT_VOLUME       = 0.20
WEIGHT_COT          = 0.30
WEIGHT_C9           = 0.25   # Candle-9: escursione + velocità

# ═══════════════════════════════════════════════════════════════════════════════
# PARAMETRI TECNICI
# ═══════════════════════════════════════════════════════════════════════════════
RSI_PERIOD      = 14
ROC_FAST        = 4       # barre (H4→16 ore, H1→4 ore)
ROC_MEDIUM      = 12      # barre
ROC_SLOW        = 24      # barre
EMA_FAST        = 20
EMA_MEDIUM      = 50
EMA_SLOW        = 200
ADX_PERIOD      = 14
ATR_PERIOD      = 14
HURST_MIN_BARS  = 100     # minimo per calcolo esponente di Hurst

# ═══════════════════════════════════════════════════════════════════════════════
# SOGLIE  (Currency Strength Score 0-100)
# ═══════════════════════════════════════════════════════════════════════════════
THRESHOLD_STRONG_BULL     = 70   # forza bullish
THRESHOLD_EXTREME_BULL    = 80   # attenzione: possibile esaurimento
THRESHOLD_STRONG_BEAR     = 30   # forza bearish
THRESHOLD_EXTREME_BEAR    = 20   # attenzione: possibile esaurimento

# Soglie di accelerazione del momentum (variazione score / periodo)
MOMENTUM_FAST_GAIN  =  5.0   # punti guadagnati in N barre → "guadagno rapido"
MOMENTUM_FAST_LOSS  = -5.0   # punti persi in N barre → "perdita rapida"
MOMENTUM_LOOKBACK   =  6     # barre per calcolo accelerazione

# ═══════════════════════════════════════════════════════════════════════════════
# CLASSIFICAZIONE TREND-FOLLOWING vs MEAN-REVERTING
# ═══════════════════════════════════════════════════════════════════════════════
ADX_TREND_THRESH     = 25    # ADX > 25 → trending
ADX_RANGE_THRESH     = 20    # ADX < 20 → ranging / mean-reverting
HURST_TREND_THRESH   = 0.55  # H > 0.55 → persistente (trend)
HURST_REVERT_THRESH  = 0.45  # H < 0.45 → anti-persistente (mean-revert)
EFFICIENCY_TREND     = 0.40  # ER > 0.40 → direzionale
EFFICIENCY_RANGE     = 0.20  # ER < 0.20 → erratico

# Pesi classificazione
CLASS_W_ADX   = 0.40
CLASS_W_HURST = 0.35
CLASS_W_ER    = 0.25

# ═══════════════════════════════════════════════════════════════════════════════
# COT  –  parametri di scoring
# ═══════════════════════════════════════════════════════════════════════════════
COT_PERCENTILE_LOOKBACK = 52   # settimane (1 anno)
COT_EXTREME_LONG  = 90         # percentile ≥ 90 → crowded long
COT_EXTREME_SHORT = 10         # percentile ≤ 10 → crowded short

# ═══════════════════════════════════════════════════════════════════════════════
# PESI COMPOSITO MULTI-TIMEFRAME (H1 + H4 + D1)
# ═══════════════════════════════════════════════════════════════════════════════
# H1 → reattività (risposta rapida ai cambiamenti)
# H4 → stabilità  (filtra il rumore, trend robusti)
# D1 → trend di fondo (direzione dominante giornaliera)
COMPOSITE_WEIGHT_H1 = 0.30   # peso H1 nel blend
COMPOSITE_WEIGHT_H4 = 0.40   # peso H4 nel blend
COMPOSITE_WEIGHT_D1 = 0.30   # peso D1 nel blend

# ── Decay accelerato D1 quando H1 e H4 divergono ─────────────────────────
# Se H1 e H4 sono su lati opposti (bull vs bear) o distanti > soglia,
# il peso D1 viene ridotto (decay) e ridistribuito proporzionalmente a H1+H4.
# Questo accelera le uscite dalla top/bottom del pannello principale.
D1_DIVERGENCE_THRESHOLD = 10   # |H1−H4| minimo per attivare il decay (punti)
D1_DIVERGENCE_MAX       = 40   # |H1−H4| a cui il decay è massimo
D1_DECAY_MIN_WEIGHT     = 0.05 # peso D1 minimo (non scende mai sotto 5%)
D1_DECAY_OPPOSITE_BONUS = 0.3  # bonus extra decay (0-1) se H1 e H4 sono su lati opposti del 50

# ═══════════════════════════════════════════════════════════════════════════════
# TIMEFRAME & REFRESH
# ═══════════════════════════════════════════════════════════════════════════════
DEFAULT_TIMEFRAME   = "Composito"     # "H1", "H4", "D1" oppure "Composito"
YFINANCE_INTERVAL   = {"H1": "1h", "H4": "1h", "D1": "1d"}  # yfinance supporta max 1h per intraday
YFINANCE_PERIOD     = {"H1": "60d", "H4": "60d", "D1": "1y"}
RESAMPLE_MAP        = {"H1": None, "H4": "4h", "D1": None}  # None = nessun resample

# Frequenza refresh consigliata (secondi)
REFRESH_SECONDS     = {"H1": 3600, "H4": 14400, "D1": 86400, "Composito": 3600}

# ═══════════════════════════════════════════════════════════════════════════════
# ASSET MONITORED (Oro, Argento, Bitcoin, Indici, Materie Prime)
# ═══════════════════════════════════════════════════════════════════════════════
ASSETS = ["GOLD", "SILVER", "WTI", "BITCOIN", "NASDAQ", "SP500", "DAX", "WHEAT"]

# Ticker yfinance per ogni asset
ASSET_TICKERS = {
    "GOLD":    "GC=F",       # Gold Futures
    "SILVER":  "SI=F",       # Silver Futures
    "WTI":     "CL=F",       # WTI Crude Oil Futures
    "BITCOIN": "BTC-USD",    # Bitcoin
    "NASDAQ":  "NQ=F",       # Nasdaq 100 Futures
    "SP500":   "ES=F",       # S&P 500 E-mini Futures
    "DAX":     "^GDAXI",     # DAX Index
    "WHEAT":   "ZW=F",       # Wheat Futures
}

# Etichette leggibili
ASSET_LABELS = {
    "GOLD":    "🥇 Oro",
    "SILVER":  "🥈 Argento",
    "WTI":     "🛢️ WTI Petrolio",
    "BITCOIN": "₿ Bitcoin",
    "NASDAQ":  "📈 Nasdaq 100",
    "SP500":   "📊 S&P 500",
    "DAX":     "🇩🇪 DAX 40",
    "WHEAT":   "🌾 Grano",
}

# Emoji per icone rapide
ASSET_ICONS = {
    "GOLD": "🥇", "SILVER": "🥈", "WTI": "🛢️", "BITCOIN": "₿",
    "NASDAQ": "📈", "SP500": "📊", "DAX": "🇩🇪", "WHEAT": "🌾",
}

# Classe di asset (per raggruppamento)
ASSET_CLASS = {
    "GOLD":    "Commodity",
    "SILVER":  "Commodity",
    "WTI":     "Commodity",
    "BITCOIN": "Crypto",
    "NASDAQ":  "Index",
    "SP500":   "Index",
    "DAX":     "Index",
    "WHEAT":   "Commodity",
}

# Volume proxy: ticker futures con volume reale (per asset che ne hanno bisogno)
ASSET_VOLUME_TICKERS = {
    "GOLD":    "GC=F",
    "SILVER":  "SI=F",
    "WTI":     "CL=F",
    "BITCOIN": "BTC-USD",
    "NASDAQ":  "NQ=F",
    "SP500":   "ES=F",
    "DAX":     "^GDAXI",
    "WHEAT":   "ZW=F",
}

# COT keywords per il report CFTC (solo commodity + indici con futures regolamentati)
ASSET_COT_KEYWORDS = {
    "GOLD":    "GOLD",
    "SILVER":  "SILVER",
    "WTI":     "CRUDE OIL",     # WTI Crude Oil CFTC
    "BITCOIN": "BITCOIN",       # CME Bitcoin Futures — report CFTC disponibile
    "NASDAQ":  "NASDAQ",        # NASDAQ-100 Consolidated
    "SP500":   "S&P 500",       # S&P 500 Consolidated
    "DAX":     None,            # DAX non è su CFTC
    "WHEAT":   "WHEAT",
}

# ═══════════════════════════════════════════════════════════════════════════════
# ASSET TIMEFRAME & REFRESH (H4 + Daily + Weekly composite)
# ═══════════════════════════════════════════════════════════════════════════════
ASSET_DEFAULT_TIMEFRAME = "Composito"     # "H4", "Daily", "Weekly" oppure "Composito"

ASSET_YFINANCE_INTERVAL = {"H4": "1h",  "Daily": "1d", "Weekly": "1wk"}
ASSET_YFINANCE_PERIOD   = {"H4": "60d", "Daily": "1y",  "Weekly": "5y"}
ASSET_RESAMPLE_MAP      = {"H4": "4h",  "Daily": None,  "Weekly": None}

# Pesi composito multi-timeframe (H4 + Daily + Weekly)
ASSET_COMPOSITE_WEIGHT_H4     = 0.30   # reattività intraday
ASSET_COMPOSITE_WEIGHT_DAILY  = 0.40   # base giornaliera
ASSET_COMPOSITE_WEIGHT_WEEKLY = 0.30   # stabilità settimanale

# ── Decay accelerato W quando H4 e D1 divergono ──────────────────────────
# Se H4 e D1 sono distanti > soglia o su lati opposti (bull vs bear),
# il peso Weekly viene ridotto (decay) e ridistribuito a H4+D1.
# Accelera le uscite dalla top/bottom del pannello asset.
ASSET_W_DIVERGENCE_THRESHOLD = 10   # |H4−D1| minimo per attivare il decay
ASSET_W_DIVERGENCE_MAX       = 40   # |H4−D1| a cui il decay è massimo
ASSET_W_DECAY_MIN_WEIGHT     = 0.05 # peso W minimo (non scende mai sotto 5%)
ASSET_W_DECAY_OPPOSITE_BONUS = 0.3  # bonus extra decay se H4 e D1 su lati opposti del 50

# Frequenza refresh consigliata (secondi)
ASSET_REFRESH_SECONDS = {"H4": 14400, "Daily": 3600, "Weekly": 86400, "Composito": 3600}

# ═══════════════════════════════════════════════════════════════════════════════
# CACHE / PERCORSI
# ═══════════════════════════════════════════════════════════════════════════════
CACHE_DIR = "cache"
COT_CACHE_FILE = "cot_data.csv"
ASSET_COT_CACHE_FILE = "asset_cot_data.csv"
ASSET_ALERT_STATE_FILE = "cache/asset_alert_state.json"

# ═══════════════════════════════════════════════════════════════════════════════
# ALERT TELEGRAM
# ═══════════════════════════════════════════════════════════════════════════════
# 1. Crea un bot su Telegram: parla con @BotFather → /newbot → copia il TOKEN
# 2. Ottieni il tuo chat_id: parla con @userinfobot → /start → copia il numero
# 3. Incolla qui sotto e imposta ALERTS_ENABLED = True

ALERTS_ENABLED     = True                         # True per abilitare
TELEGRAM_BOT_TOKEN = "8727017446:AAEaUigln8Zw4glgqDyaGcXHmwKLQIWG3XY"
TELEGRAM_CHAT_ID   = "901682485"
ALERT_GRADES       = ["A+", "A"]                  # gradi monitorati
ALERT_STATE_FILE   = "cache/alert_state.json"     # file di stato (non toccare)

# ═══════════════════════════════════════════════════════════════════════════════
# CALENDARIO ECONOMICO & FILTRO NOTIZIE
# ═══════════════════════════════════════════════════════════════════════════════
# Se un dato macro HIGH viene rilasciato durante la candela H1 appena chiusa,
# il segnale potrebbe essere distorto → SOPPRIMI la coppia dal Trade Setup.
# Se un dato macro è in arrivo nelle prossime ore → WARNING (non sopprimere).

CALENDAR_CACHE_FILE   = "calendar_events.json"     # file cache in CACHE_DIR
NEWS_SUPPRESS_HOURS_BACK = 2    # ore indietro: evento recente → SOPPRESSIONE
NEWS_WARN_HOURS_AHEAD    = 2    # ore avanti: evento imminente → WARNING
NEWS_MIN_IMPACT          = "high"  # "high" = solo rosso, "medium" = anche arancione

# ═══════════════════════════════════════════════════════════════════════════════
# STORICO SEGNALI
# ═══════════════════════════════════════════════════════════════════════════════
SIGNAL_HISTORY_FILE = "cache/signal_history.json"   # log permanente segnali
SIGNAL_HISTORY_MAX_DAYS = 90                         # giorni di storico conservati

# ═══════════════════════════════════════════════════════════════════════════════
# STABILITÀ CLASSIFICA  –  anti-flickering segnali A/A+
# ═══════════════════════════════════════════════════════════════════════════════
# Problema: segnali che entrano e escono dalla classifica dopo 1-2 ore.
# Soluzioni implementate:
#
# 1. ISTERESI (hysteresis): per entrare serve score ≥ soglia_entry,
#    per uscire deve scendere sotto soglia_exit (più bassa).
# 2. GRACE PERIOD: dopo che un segnale scende sotto soglia, resta in
#    classifica per N refresh consecutivi prima dell'uscita ufficiale.
# 3. RESIDENZA MINIMA: un segnale resta in classifica almeno N ore
#    dopo l'ingresso, anche se il punteggio scende.
# 4. SMOOTHING: il composite score viene blendato con il precedente
#    per smorzare le oscillazioni (EMA-like).

# Differenziale minimo per qualificare un trade setup (punti composito)
# Sotto questa soglia la coppia viene ignorata (troppo noise).
MIN_DIFFERENTIAL_THRESHOLD = 8   # era 5, alzato per eliminare setup deboli

# Isteresi sulle soglie di grado (punti quality_score)
GRADE_HYSTERESIS_POINTS  = 5     # un A (≥60) esce solo se scende sotto 55

# Grace period: N refresh consecutivi sotto soglia prima dell'uscita
SIGNAL_GRACE_REFRESHES   = 2     # = 2 ore con refresh orario

# Residenza minima (ore): un segnale resta in classifica almeno N ore
SIGNAL_MIN_RESIDENCE_HOURS = 4   # era 3, alzato per più stabilità

# Conferma ingresso: un segnale deve essere A/A+ per N refresh consecutivi
# prima di entrare ufficialmente in classifica. Previene spike da 1 ora.
SIGNAL_CONFIRMATION_REFRESHES = 2  # richiede 2 ore consecutive come A/A+

# Smoothing EMA: α = peso del dato nuovo (1-α = peso del dato precedente)
# α=1.0 → nessuno smoothing, α=0.5 → media mobile esponenziale forte
SCORE_SMOOTHING_ALPHA    = 0.5   # 50% nuovo, 50% vecchio (era 0.6)

# ═══════════════════════════════════════════════════════════════════════════════
# GRUPPI DI CORRELAZIONE (coppie col medesimo tema direzionale)
# ═══════════════════════════════════════════════════════════════════════════════
# Se un segnale A/A+ esiste per una coppia in un gruppo, le altre coppie
# dello stesso gruppo vengono automaticamente escluse → evita segnali ridondanti.
CORRELATION_GROUPS = [
    ["AUDNZD", "AUDCAD", "NZDCAD"],       # 1: commodity bloc crosses
    ["AUDUSD", "USDCAD", "NZDUSD"],       # 2: commodity vs USD
    ["EURUSD", "GBPUSD"],                  # 3: majors vs USD
    ["USDJPY", "USDCHF", "CHFJPY"],       # 4: USD vs safe-haven + cross
    ["CADJPY", "NZDJPY", "AUDJPY"],       # 5: commodity vs JPY
    ["GBPCHF", "EURCHF"],                  # 6: EUR/GBP vs CHF
    ["EURNZD", "EURCAD", "EURAUD"],       # 7: EUR vs commodity
    ["GBPNZD", "GBPCAD", "GBPAUD"],       # 8: GBP vs commodity
    ["NZDCHF", "CADCHF", "AUDCHF"],       # 9: commodity vs CHF
    ["GBPJPY", "EURJPY"],                  # 10: EUR/GBP vs JPY
]
EXCLUDED_PAIRS = ["EURGBP"]                # coppie mai tradate

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION / CURRENCY AFFINITY (bonus se le valute sono nella sessione giusta)
# ═══════════════════════════════════════════════════════════════════════════════
SESSION_CURRENCY_AFFINITY = {
    "asia":     {"JPY", "AUD", "NZD"},
    "london":   {"EUR", "GBP", "CHF"},
    "newyork":  {"USD", "CAD"},
}

# ═══════════════════════════════════════════════════════════════════════════════
# COT FRESHNESS
# ═══════════════════════════════════════════════════════════════════════════════
COT_STALE_DAYS_THRESHOLD = 10   # se dati COT più vecchi di N giorni, dimezza peso


# ═══════════════════════════════════════════════════════════════════════════════
# PORTAFOGLIO DI INVESTIMENTO
# ═══════════════════════════════════════════════════════════════════════════════
# Regime: USA Stagflazione / Europa Reflazione → Feb 2026
# Bilanciato US + EU, mix ETF + azioni, valuta conto EUR
# Ribilanciamento: alert automatico se peso devia > REBALANCE_THRESHOLD_PCT

PORTFOLIO_FILE = "cache/portfolio.json"     # stato posizioni (open + closed)
PORTFOLIO_CURRENCY = "EUR"                  # valuta di denominazione conto
PORTFOLIO_CAPITAL = 1000.0                  # capitale iniziale €
REBALANCE_THRESHOLD_PCT = 5.0              # alert se peso reale devia di ±5% dal target

# Composizione target e posizioni iniziali  (ticker eToro-compatibili)
# ─────────────────────────────────────────────────────────────────────
# Logica allocativa:
#   • Stagflazione USA → Oro (copertura inflazione), Energy (pricing power),
#     Dividendi USA difensivi (cash-flow reali vs growth)
#   • Reflazione Europa → Finanziari EU (curva tassi sale), Broad EU (ciclici)
#
# Tutti i ticker sono quotati su NYSE/NASDAQ in USD — disponibili su eToro.
#
# Ticker  │ eToro │ Peso │ Razionale
# ────────┼───────┼──────┼─────────────────────────────────────────────
# GLD     │  ✅   │ 20%  │ SPDR Gold — hedge inflazione/stagflazione
# EUFN    │  ✅   │ 20%  │ iShares Europe Financials — reflazione EU
# XLE     │  ✅   │ 15%  │ Energy Select SPDR — pricing power, dividendi
# VGK     │  ✅   │ 20%  │ Vanguard FTSE Europe — broad EU, reflazione
# SCHD    │  ✅   │ 15%  │ Schwab US Dividend — cash flow, difensivo
# Cash    │  —    │ 10%  │ Riserva ribilanciamento
# ────────┴───────┴──────┴─────────────────────────────────────────────

PORTFOLIO_POSITIONS = [
    {
        "ticker": "GLD",
        "name": "SPDR Gold Shares",
        "asset_class": "Commodity",
        "region": "Global",
        "currency": "USD",
        "target_weight": 0.20,
        "rationale": "Oro fisico — hedge inflazione/stagflazione",
    },
    {
        "ticker": "EUFN",
        "name": "iShares MSCI Europe Financials ETF",
        "asset_class": "Equity",
        "region": "Europa",
        "currency": "USD",
        "target_weight": 0.20,
        "rationale": "Finanziari EU — beneficiano della reflazione e tassi in salita",
    },
    {
        "ticker": "XLE",
        "name": "Energy Select Sector SPDR Fund",
        "asset_class": "Equity",
        "region": "USA",
        "currency": "USD",
        "target_weight": 0.15,
        "rationale": "Energia US — pricing power, dividendi alti, stagflazione-proof",
    },
    {
        "ticker": "VGK",
        "name": "Vanguard FTSE Europe ETF",
        "asset_class": "Equity",
        "region": "Europa",
        "currency": "USD",
        "target_weight": 0.20,
        "rationale": "Broad Europe — reflazione favorisce ciclici EU",
    },
    {
        "ticker": "SCHD",
        "name": "Schwab US Dividend Equity ETF",
        "asset_class": "Equity",
        "region": "USA",
        "currency": "USD",
        "target_weight": 0.15,
        "rationale": "Dividendi US — cash flow reali, difensivo vs stagflazione",
    },
]

# FX per conversione prezzi in EUR (yfinance)
# Tutti i ticker sono quotati in USD, serve solo EURUSD.
PORTFOLIO_FX_TICKERS = {
    "USD": "EURUSD=X",   # 1 EUR = X USD → prezzo_eur = prezzo_usd / rate
}
