"""
Currency Strength Mobile – Configuration
"""

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"]

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

FUTURES_TICKERS = {
    "EUR": "6E=F", "GBP": "6B=F", "JPY": "6J=F", "CHF": "6S=F",
    "AUD": "6A=F", "NZD": "6N=F", "CAD": "6C=F", "USD": "DX=F",
}

# Pesi compositi
WEIGHT_PRICE_ACTION = 0.40
WEIGHT_VOLUME       = 0.30
WEIGHT_COT          = 0.30

# Parametri tecnici
RSI_PERIOD      = 14
ROC_FAST        = 4
ROC_MEDIUM      = 12
ROC_SLOW        = 24
EMA_FAST        = 20
EMA_MEDIUM      = 50
EMA_SLOW        = 200
ADX_PERIOD      = 14
ATR_PERIOD      = 14
HURST_MIN_BARS  = 100
MOMENTUM_LOOKBACK = 6

# Soglie
THRESHOLD_STRONG_BULL  = 70
THRESHOLD_EXTREME_BULL = 80
THRESHOLD_STRONG_BEAR  = 30
THRESHOLD_EXTREME_BEAR = 20
MOMENTUM_FAST_GAIN     =  5.0
MOMENTUM_FAST_LOSS     = -5.0

# Classificazione
ADX_TREND_THRESH     = 25
ADX_RANGE_THRESH     = 20
HURST_TREND_THRESH   = 0.55
HURST_REVERT_THRESH  = 0.45
EFFICIENCY_TREND     = 0.40
EFFICIENCY_RANGE     = 0.20
CLASS_W_ADX   = 0.40
CLASS_W_HURST = 0.35
CLASS_W_ER    = 0.25

# Multi-timeframe
COMPOSITE_WEIGHT_H1 = 0.40
COMPOSITE_WEIGHT_H4 = 0.60

# COT
COT_STALE_DAYS_THRESHOLD = 10

# Gruppi correlazione
CORRELATION_GROUPS = [
    ["AUDNZD", "AUDCAD", "NZDCAD"],
    ["AUDUSD", "USDCAD", "NZDUSD"],
    ["EURUSD", "GBPUSD"],
    ["USDJPY", "USDCHF", "CHFJPY"],
    ["CADJPY", "NZDJPY", "AUDJPY"],
    ["GBPCHF", "EURCHF"],
    ["EURNZD", "EURCAD", "EURAUD"],
    ["GBPNZD", "GBPCAD", "GBPAUD"],
    ["NZDCHF", "CADCHF", "AUDCHF"],
    ["GBPJPY", "EURJPY"],
]
EXCLUDED_PAIRS = ["EURGBP"]

SESSION_CURRENCY_AFFINITY = {
    "asia":     {"JPY", "AUD", "NZD"},
    "london":   {"EUR", "GBP", "CHF"},
    "newyork":  {"USD", "CAD"},
}

# Telegram
TELEGRAM_BOT_TOKEN = "8727017446:AAEaUigln8Zw4glgqDyaGcXHmwKLQIWG3XY"
TELEGRAM_CHAT_ID   = "901682485"
ALERT_GRADES       = ["A+", "A"]

# Monitor
MONITOR_INTERVAL_MINUTES = 60
