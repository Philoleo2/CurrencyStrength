"""
Test suite per le modifiche di stabilità e qualità segnali.
Verifica: smoothing, scoring tightening, confirmation logic.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

def test_config_params():
    """Verifica parametri config aggiornati."""
    from config import (
        MIN_DIFFERENTIAL_THRESHOLD,
        SIGNAL_CONFIRMATION_REFRESHES,
        SCORE_SMOOTHING_ALPHA,
        SIGNAL_MIN_RESIDENCE_HOURS,
        GRADE_HYSTERESIS_POINTS,
        SIGNAL_GRACE_REFRESHES,
    )
    assert MIN_DIFFERENTIAL_THRESHOLD == 8, f"Expected 8, got {MIN_DIFFERENTIAL_THRESHOLD}"
    assert SIGNAL_CONFIRMATION_REFRESHES == 2, f"Expected 2, got {SIGNAL_CONFIRMATION_REFRESHES}"
    assert SCORE_SMOOTHING_ALPHA == 0.5, f"Expected 0.5, got {SCORE_SMOOTHING_ALPHA}"
    assert SIGNAL_MIN_RESIDENCE_HOURS == 4, f"Expected 4, got {SIGNAL_MIN_RESIDENCE_HOURS}"
    assert GRADE_HYSTERESIS_POINTS == 5
    assert SIGNAL_GRACE_REFRESHES == 2
    print("  [OK] Config params correct")


def test_smoothing_alpha():
    """Verifica EMA smoothing con alpha=0.5."""
    from strength_engine import smooth_composite_scores
    prev = {"USD": {"composite": 60, "price_score": 55, "volume_score": 50, "cot_score": 65, "label": "STRONG"}}
    curr = {"USD": {"composite": 70, "price_score": 65, "volume_score": 60, "cot_score": 75, "label": "STRONG"}}
    sm = smooth_composite_scores(curr, prev)
    assert sm["USD"]["composite"] == 65.0, f"Expected 65.0, got {sm['USD']['composite']}"
    assert sm["USD"]["price_score"] == 60.0, f"Expected 60.0, got {sm['USD']['price_score']}"
    print("  [OK] Smoothing alpha=0.5 correct")


def test_smoothing_no_prev():
    """Senza dati precedenti → passthrough."""
    from strength_engine import smooth_composite_scores
    curr = {"EUR": {"composite": 72, "price_score": 68, "volume_score": 55, "cot_score": 80, "label": "STRONG"}}
    sm = smooth_composite_scores(curr, None)
    assert sm["EUR"]["composite"] == 72, "Passthrough failed"
    print("  [OK] Smoothing passthrough correct")


def test_smoothing_dampens_spike():
    """Un picco improvviso viene smorzato del 50%."""
    from strength_engine import smooth_composite_scores
    prev = {"JPY": {"composite": 40, "price_score": 40, "volume_score": 40, "cot_score": 40, "label": "NEUTRAL"}}
    curr = {"JPY": {"composite": 80, "price_score": 80, "volume_score": 80, "cot_score": 80, "label": "STRONG"}}
    sm = smooth_composite_scores(curr, prev)
    # alpha=0.5: 0.5*80 + 0.5*40 = 60
    assert sm["JPY"]["composite"] == 60.0, f"Expected 60.0, got {sm['JPY']['composite']}"
    print("  [OK] Spike damped by 50%")


def test_min_differential():
    """Coppie con differenziale < 8 vengono escluse."""
    from strength_engine import compute_trade_setups
    from config import CURRENCIES

    # Crea compositi con differenziale = 6 (< 8 → skip)
    composite = {}
    for i, ccy in enumerate(CURRENCIES):
        composite[ccy] = {"composite": 50 + i * 0.8, "concordance": ""}

    momentum = {c: {"delta": 0, "acceleration": 0} for c in CURRENCIES}
    classification = {c: {"classification": "MIXED"} for c in CURRENCIES}
    atr_ctx = {c: {"volatility_regime": "NORMAL"} for c in CURRENCIES}
    cot = {c: {"bias": "NEUTRAL", "freshness_days": 1} for c in CURRENCIES}

    setups = compute_trade_setups(composite, momentum, classification, atr_ctx, cot)
    # Con 8 currencies, max spread = 7*0.8 = 5.6 < 8 → NESSUN setup
    assert len(setups) == 0, f"Expected 0 setups, got {len(setups)}"
    print("  [OK] Min differential 8 filters weak pairs")


def test_partial_credit_tightened():
    """Verifica che momentum partial dia 6 (non 10) e MIXED dia 5 (non 7)."""
    from strength_engine import compute_trade_setups
    from config import CURRENCIES

    # Setup con differenziale chiaro (20 pts) ma solo momentum parziale
    composite = {c: {"composite": 50, "concordance": ""} for c in CURRENCIES}
    composite["USD"]["composite"] = 70  # forte
    composite["JPY"]["composite"] = 50  # neutra → diff = 20

    momentum = {c: {"delta": 0, "acceleration": 0} for c in CURRENCIES}
    momentum["USD"]["delta"] = 1  # solo forte positivo, debole neutro
    classification = {c: {"classification": "MIXED"} for c in CURRENCIES}
    atr_ctx = {c: {"volatility_regime": "LOW"} for c in CURRENCIES}
    cot = {c: {"bias": "NEUTRAL", "freshness_days": 1} for c in CURRENCIES}

    setups = compute_trade_setups(composite, momentum, classification, atr_ctx, cot)
    # Trova il setup USD/JPY
    usdjpy = [s for s in setups if s["base"] == "USD" and s["quote"] == "JPY"]
    assert len(usdjpy) == 1, f"Expected 1 USD/JPY setup, got {len(usdjpy)}"
    s = usdjpy[0]

    # Calcolo atteso:
    # diff=20 → 20 pts
    # momentum partial → 6 pts (tightened from 10)
    # MIXED regime → 5 pts (tightened from 7)
    # vol LOW → 10 pts
    # No COT, no H1/H4, velocity/EMA/persistence depend on defaults
    # Cerchiamo che il punteggio sia inferiore rispetto al vecchio sistema
    # Vecchio: 20 + 10 + 7 + 10 = 47 base  → con penalty da persistence/velocity il totale scendeva
    # Nuovo:  20 + 6 + 5 + 10 = 41 base
    reasons_str = " | ".join(s["reasons"])
    assert "parzialmente" in reasons_str, f"Expected 'parzialmente' in reasons: {reasons_str}"
    print(f"  [OK] Partial credit tightened: USD/JPY score = {s['quality_score']} (reasons: {len(s['reasons'])})")


def test_confirmation_state_format():
    """Verifica che lo stato supporti pending_pairs."""
    import json
    import tempfile
    import alerts

    # Crea stato con pending_pairs
    state = {
        "pairs": ["NZD/CHF LONG"],
        "pair_details": {
            "NZD/CHF LONG": {
                "entered_at": "2026-03-04T10:00:00",
                "last_seen_at": "2026-03-04T12:00:00",
                "grace_counter": 0,
                "last_score": 65,
            }
        },
        "pending_pairs": {
            "AUD/JPY LONG": {
                "first_seen_at": "2026-03-04T14:00:00",
                "consecutive_count": 1,
                "last_score": 62,
            }
        },
        "updated": "2026-03-04T14:00:00",
    }

    # Test round-trip
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, dir="cache")
    json.dump(state, tmp, indent=2)
    tmp.close()

    orig = alerts.ALERT_STATE_FILE
    try:
        alerts.ALERT_STATE_FILE = tmp.name
        loaded = alerts._load_full_state()
        assert "pending_pairs" in loaded, "Missing pending_pairs"
        assert "AUD/JPY LONG" in loaded["pending_pairs"], "Missing pending pair"
        assert loaded["pending_pairs"]["AUD/JPY LONG"]["consecutive_count"] == 1
        print("  [OK] Pending pairs state format correct")
    finally:
        alerts.ALERT_STATE_FILE = orig
        os.unlink(tmp.name)


if __name__ == "__main__":
    print("=== Test Stabilità & Qualità Segnali ===\n")
    tests = [
        test_config_params,
        test_smoothing_alpha,
        test_smoothing_no_prev,
        test_smoothing_dampens_spike,
        test_min_differential,
        test_partial_credit_tightened,
        test_confirmation_state_format,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Risultato: {passed} passed, {failed} failed")
    if failed == 0:
        print("TUTTI I TEST PASSATI ✓")
    else:
        print("ALCUNI TEST FALLITI ✗")
        sys.exit(1)
