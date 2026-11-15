"""Prueba rapida con velas sinteticas: python test_strategy.py"""
import math, random
import config as cfg
from strategy import analyze

random.seed(7)
price, candles = 100.0, []
for i in range(2000):
    drift = math.sin(i / 40) * 0.6 + random.uniform(-0.5, 0.5)
    o = price
    c = o + drift
    h = max(o, c) + random.uniform(0, 0.4)
    l = min(o, c) - random.uniform(0, 0.4)
    candles.append({"t": i * 300000, "o": o, "h": h, "l": l, "c": c, "v": random.uniform(50, 150)})
    price = c

cfg.SIGNAL_MAX_AGE = len(candles)  # ver todas las senales historicas
sigs = analyze(candles, cfg, 5e7)
print("senales:", len(sigs), "| longs:", sum(s["side"] == "LONG" for s in sigs))
assert sigs, "no hubo senales"
for s in sigs:
    assert 0 <= s["score"] <= 100
    if s["side"] == "LONG":
        assert s["sl"] < s["entry"] < s["tp"]
    else:
        assert s["tp"] < s["entry"] < s["sl"]
print("OK", sigs[-1])
