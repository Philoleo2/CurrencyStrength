"""
sim_kijun.py – Test empirico: Kijun-sen come componente aggiuntivo
===================================================================
Misura:
1) Correlazione tra Kijun score e PA score esistente (overlap)
2) Valore predittivo indipendente della Kijun
3) Confronto 4-comp vs 5-comp con backtest rolling

Kijun-sen = (HH26 + LL26) / 2
Score logica:
  - price > kijun → bullish (score > 50)
  - price < kijun → bearish (score < 50)
  - price nel range HH26/LL26 ma vicino a kijun → neutro (~50)
  - Magnitudine: distanza relativa price/kijun normalizzata
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
from config import (
    CURRENCIES, FOREX_PAIRS, WEIGHT_PRICE_ACTION, WEIGHT_VOLUME,
    WEIGHT_COT, WEIGHT_C9, COT_PERCENTILE_LOOKBACK,
)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. KIJUN SCORE
# ═══════════════════════════════════════════════════════════════════════════════

KIJUN_PERIOD = 26  # standard Ichimoku


def kijun_score_pair(pair_df: pd.DataFrame, is_base: bool,
                     period: int = KIJUN_PERIOD) -> float:
    """
    Score 0-100 per una coppia basato su Kijun-sen.
    
    Logica:
      - Calcola Kijun = (HH_period + LL_period) / 2
      - hh = max(High, period), ll = min(Low, period)
      - range_size = hh - ll
      - Se range_size ~ 0 → neutro (50)
      - position = (close - kijun) / range_size  → [-0.5, +0.5]
      - Normalizza a 0-100 con zona neutra al centro
    """
    if len(pair_df) < period:
        return 50.0
    
    high = pair_df["High"].values
    low = pair_df["Low"].values
    close = pair_df["Close"].values[-1]
    
    hh = np.max(high[-period:])
    ll = np.min(low[-period:])
    kijun = (hh + ll) / 2.0
    range_size = hh - ll
    
    if range_size == 0:
        return 50.0
    
    # position: -0.5 (al minimo) a +0.5 (al massimo)
    position = (close - kijun) / range_size
    
    # Se quote (non base), inverti segno
    sign = 1.0 if is_base else -1.0
    position *= sign
    
    # Mappa a 0-100 con amplificazione nelle zone estreme
    # position in [-0.5, 0.5] → score in [0, 100]
    # Con curva sigmoidale per enfatizzare breakout oltre kijun
    score = 50.0 + position * 100.0  # lineare: 0-100
    
    return float(np.clip(score, 0, 100))


def compute_kijun_scores(all_pairs: dict[str, pd.DataFrame]) -> dict[str, float]:
    """Score Kijun per ogni valuta (media su tutte le coppie)."""
    ccy_scores: dict[str, list[float]] = {c: [] for c in CURRENCIES}
    
    for pair_name, pair_df in all_pairs.items():
        if pair_df.empty or "Close" not in pair_df.columns:
            continue
        info = FOREX_PAIRS[pair_name]
        base, quote = info["base"], info["quote"]
        
        if base in ccy_scores:
            s = kijun_score_pair(pair_df, is_base=True)
            ccy_scores[base].append(s)
        if quote in ccy_scores:
            s = kijun_score_pair(pair_df, is_base=False)
            ccy_scores[quote].append(s)
    
    return {ccy: round(float(np.mean(vals)), 2) if vals else 50.0
            for ccy, vals in ccy_scores.items()}


# ═══════════════════════════════════════════════════════════════════════════════
# 2. DATI & ANALISI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    from data_fetcher import fetch_all_pairs
    from strength_engine import compute_price_action_scores
    from cot_data import load_cot_data, compute_cot_scores
    
    print("=" * 70)
    print("  SIMULAZIONE KIJUN-SEN – Analisi valore aggiuntivo")
    print("=" * 70)
    
    # ── Scarico dati ─────────────────────────────────────────────────────
    print("\n[1/5] Scaricamento dati H1...", flush=True)
    all_pairs = fetch_all_pairs("H1")
    if not all_pairs:
        print("ERRORE: nessun dato disponibile")
        return
    
    # Prendi il pair con più barre per riferimento temporale
    ref_pair = max(all_pairs.values(), key=len)
    n_bars = len(ref_pair)
    print(f"  → {len(all_pairs)} coppie, {n_bars} barre")
    
    # ── Calcolo componenti attuali ───────────────────────────────────────
    print("[2/5] Calcolo score PA + Kijun attuali...", flush=True)
    pa_scores = compute_price_action_scores(all_pairs)
    kijun_scores = compute_kijun_scores(all_pairs)
    
    # ── Analisi correlazione PA vs Kijun ────────────────────────────────
    print("[3/5] Analisi correlazione PA ↔ Kijun...\n")
    
    ccys = sorted([c for c in CURRENCIES if c not in ("USD", "NZD")])
    pa_arr = np.array([pa_scores[c] for c in ccys])
    kj_arr = np.array([kijun_scores[c] for c in ccys])
    
    corr_snapshot = np.corrcoef(pa_arr, kj_arr)[0, 1]
    print(f"  Correlazione istantanea PA ↔ Kijun: {corr_snapshot:+.3f}")
    print(f"  {'ALTA SOVRAPPOSIZIONE' if abs(corr_snapshot) > 0.7 else 'SOVRAPPOSIZIONE MODERATA' if abs(corr_snapshot) > 0.4 else 'BASSA SOVRAPPOSIZIONE'}")
    
    print(f"\n  {'CCY':>5s}  {'PA':>6s}  {'Kijun':>6s}  {'Diff':>6s}")
    print(f"  {'─'*5}  {'─'*6}  {'─'*6}  {'─'*6}")
    for c in ccys:
        diff = kijun_scores[c] - pa_scores[c]
        print(f"  {c:>5s}  {pa_scores[c]:6.1f}  {kijun_scores[c]:6.1f}  {diff:+6.1f}")
    
    # ── Rolling backtest ─────────────────────────────────────────────────
    print("\n[4/5] Backtest rolling: 4-comp attuale vs 5-comp con Kijun...")
    print("  (Ricalcola PA, Kijun, C9 su finestre successive)\n", flush=True)
    
    # Dividi in finestre rolling (step = 6 barre H1)
    window_size = 100  # barre per calcolo score
    step = 6           # ogni 6 barre (6h per H1)
    forward = 12       # orizzonte previsione (12h)
    
    results_4comp = []  # score attuale (4 comp)
    results_5comp = []  # score con Kijun (5 comp)
    actual_dirs = []    # direzione effettiva
    
    # Per ogni valuta + finestra, calcola score e controlla direzione
    for ccy in ccys:
        # Prendi tutte le coppie che contengono questa valuta
        ccy_pairs = {}
        for pname, pdf in all_pairs.items():
            info = FOREX_PAIRS[pname]
            if info["base"] == ccy or info["quote"] == ccy:
                ccy_pairs[pname] = pdf
        
        if not ccy_pairs:
            continue
        
        # Usa la coppia con più dati come proxy per direzione
        ref_name = max(ccy_pairs, key=lambda k: len(ccy_pairs[k]))
        ref = ccy_pairs[ref_name]
        is_base = FOREX_PAIRS[ref_name]["base"] == ccy
        
        max_start = len(ref) - window_size - forward
        if max_start < 10:
            continue
        
        for start in range(0, max_start, step):
            end = start + window_size
            
            # Sliced pairs per questa finestra
            sliced = {}
            for pn, pdf in ccy_pairs.items():
                if len(pdf) >= end + forward:
                    sliced[pn] = pdf.iloc[start:end].copy()
            
            if not sliced:
                continue
            
            # PA score (semplificato: solo per questa valuta)
            pa_vals = []
            kj_vals = []
            for pn, spdf in sliced.items():
                info = FOREX_PAIRS[pn]
                ib = info["base"] == ccy
                # PA: RSI + ROC + EMA positioning (semplificato)
                close = spdf["Close"]
                if len(close) < 30:
                    continue
                
                # ROC semplice
                roc5 = (close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) > 5 else 0
                roc20 = (close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) > 20 else 0
                sign = 1.0 if ib else -1.0
                pa_s = 50 + np.clip((roc5 * 0.6 + roc20 * 0.4) * sign * 10, -50, 50)
                pa_vals.append(pa_s)
                
                # Kijun score
                kj_s = kijun_score_pair(spdf, is_base=ib)
                kj_vals.append(kj_s)
            
            if not pa_vals:
                continue
            
            pa_avg = np.mean(pa_vals)
            kj_avg = np.mean(kj_vals)
            
            # Score 4-comp (PA prende tutto il peso non-COT perché
            # volume e c9 non cambiano: semplifichiamo)
            score_4 = pa_avg  # proxy: PA è il driver principale
            
            # Score 5-comp: blend PA (60%) + Kijun (40%)
            score_5 = pa_avg * 0.60 + kj_avg * 0.40
            
            # Direzione effettiva futura
            ref_full = ccy_pairs[ref_name]
            future_close = ref_full["Close"].iloc[end + forward - 1]
            current_close = ref_full["Close"].iloc[end - 1]
            actual_dir = 1 if future_close > current_close else -1
            if not is_base:
                actual_dir = -actual_dir
            
            pred_4 = 1 if score_4 > 50 else -1
            pred_5 = 1 if score_5 > 50 else -1
            
            results_4comp.append(pred_4 == actual_dir)
            results_5comp.append(pred_5 == actual_dir)
            actual_dirs.append(actual_dir)
    
    n_tests = len(results_4comp)
    if n_tests < 20:
        print(f"  ATTENZIONE: solo {n_tests} test, risultati poco significativi")
    
    dir_4 = np.mean(results_4comp) * 100 if results_4comp else 50
    dir_5 = np.mean(results_5comp) * 100 if results_5comp else 50
    delta = dir_5 - dir_4
    
    print(f"  Test eseguiti: {n_tests}")
    print(f"  PA-only Dir%:         {dir_4:.1f}%")
    print(f"  PA+Kijun blend Dir%:  {dir_5:.1f}%")
    print(f"  Delta:                {delta:+.1f}%")
    
    # ── Analisi overlap rolling ──────────────────────────────────────────
    print("\n[5/5] Analisi concordanza segnali PA vs Kijun...\n", flush=True)
    
    concordant = 0
    discordant = 0
    total_windows = 0
    kijun_wins = 0
    pa_wins = 0
    
    for ccy in ccys:
        ccy_pairs = {}
        for pname, pdf in all_pairs.items():
            info = FOREX_PAIRS[pname]
            if info["base"] == ccy or info["quote"] == ccy:
                ccy_pairs[pname] = pdf
        if not ccy_pairs:
            continue
        
        ref_name = max(ccy_pairs, key=lambda k: len(ccy_pairs[k]))
        ref = ccy_pairs[ref_name]
        is_base = FOREX_PAIRS[ref_name]["base"] == ccy
        max_start = len(ref) - window_size - forward
        if max_start < 10:
            continue
        
        for start in range(0, max_start, step):
            end = start + window_size
            
            sliced = {}
            for pn, pdf in ccy_pairs.items():
                if len(pdf) >= end + forward:
                    sliced[pn] = pdf.iloc[start:end].copy()
            if not sliced:
                continue
            
            pa_vals = []
            kj_vals = []
            for pn, spdf in sliced.items():
                info = FOREX_PAIRS[pn]
                ib = info["base"] == ccy
                close = spdf["Close"]
                if len(close) < 30:
                    continue
                roc5 = (close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) > 5 else 0
                sign = 1.0 if ib else -1.0
                pa_s = 50 + np.clip(roc5 * sign * 15, -50, 50)
                pa_vals.append(pa_s)
                kj_vals.append(kijun_score_pair(spdf, is_base=ib))
            
            if not pa_vals:
                continue
            
            pa_signal = 1 if np.mean(pa_vals) > 55 else (-1 if np.mean(pa_vals) < 45 else 0)
            kj_signal = 1 if np.mean(kj_vals) > 55 else (-1 if np.mean(kj_vals) < 45 else 0)
            
            if pa_signal == 0 or kj_signal == 0:
                continue
            
            total_windows += 1
            
            if pa_signal == kj_signal:
                concordant += 1
            else:
                discordant += 1
                # Chi ha ragione quando discordano?
                ref_full = ccy_pairs[ref_name]
                if len(ref_full) > end + forward:
                    future_close = ref_full["Close"].iloc[end + forward - 1]
                    current_close = ref_full["Close"].iloc[end - 1]
                    actual = 1 if future_close > current_close else -1
                    if not is_base:
                        actual = -actual
                    if pa_signal == actual:
                        pa_wins += 1
                    elif kj_signal == actual:
                        kijun_wins += 1
    
    if total_windows > 0:
        conc_pct = concordant / total_windows * 100
        disc_pct = discordant / total_windows * 100
        print(f"  Finestre con segnale: {total_windows}")
        print(f"  Concordanti:  {concordant:4d} ({conc_pct:.1f}%)")
        print(f"  Discordanti:  {discordant:4d} ({disc_pct:.1f}%)")
        if discordant > 0:
            print(f"    → PA vince:    {pa_wins:4d} ({pa_wins/discordant*100:.1f}%)")
            print(f"    → Kijun vince: {kijun_wins:4d} ({kijun_wins/discordant*100:.1f}%)")
            print(f"    → Nessuno:     {discordant-pa_wins-kijun_wins:4d}")
    
    # ── Verdetto ─────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  VERDETTO")
    print("=" * 70)
    
    if abs(delta) < 1.0:
        print("  → Kijun NON aggiunge valore significativo.")
        print("    L'informazione è già catturata da PA (RSI + ROC + EMA).")
        print("    RACCOMANDAZIONE: Non implementare.")
    elif delta > 0:
        print(f"  → Kijun migliora Dir% di {delta:+.1f}%")
        if delta > 2.0:
            print("    RACCOMANDAZIONE: Considerare integrazione nel PA score.")
        else:
            print("    Miglioramento marginale. Valutare se vale la complessità.")
    else:
        print(f"  → Kijun PEGGIORA Dir% di {delta:.1f}%")
        print("    RACCOMANDAZIONE: Non implementare.")
    
    # Info overlap
    if total_windows > 0 and conc_pct > 75:
        print(f"\n  NOTA: {conc_pct:.0f}% concordanza PA↔Kijun = alta sovrapposizione")
        print("  → La Kijun cattura informazione già presente nel PA score.")


if __name__ == "__main__":
    main()
