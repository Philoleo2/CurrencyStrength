import json

data = json.load(open('cache/signal_history.json', encoding='utf-8'))
chfjpy = [e for e in data if 'CHF' in e.get('pair','') and 'JPY' in e.get('pair','')]
for e in chfjpy[-30:]:
    reasons = '; '.join(e.get('reasons', []))
    print(f"{e['timestamp'][:16]} | {e['type']:8s} | {e['pair']:10s} | {e['direction']:6s} | "
          f"grade={e['grade']:3s} | score={e['score']:5.1f} | diff={e['differential']:+.1f} | {reasons}")
