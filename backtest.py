"""Backtest con historico de BingX usando EXACTAMENTE la misma logica que el bot en vivo.
Mide cada setup y cada filtro (flag) con expectativa en R, sin arriesgar dinero.

  python backtest.py --symbols BTC-USDT,ETH-USDT,SOL-USDT --days 30
  python backtest.py --top 20 --days 30
  python backtest.py --top 20 --days 30 --optimize      (busca puertas, validando fuera de muestra)
  python backtest.py --synthetic            (datos inventados, solo para comprobar que funciona)

Notas: el flag 'btc' se asume cumplido en el backtest (solo existe el regimen de BTC en vivo).
Solo cuenta senales de las ultimas velas descargadas; el SL se asume antes que el TP si ambos caen en la misma vela."""
import argparse
import asyncio
import json
import math
import random
import re

import aiohttp

import config as cfg
from bingx import BingX
from journal import advance, new_state, report_text
from optimize import optimize
from strategy import analyze


def make_synthetic(n, seed=1, t0=1_704_067_200_000, tf=300_000):
    """Serie sintetica con regimenes de tendencia/rango y volatilidad cambiante (solo para pruebas)."""
    rnd = random.Random(seed)
    price, drift, vol, left = 100.0, 0.0, 0.003, 0
    out = []
    for i in range(n):
        if left <= 0:
            left = rnd.randint(40, 400)
            drift = rnd.choice([-1, 0, 0, 1]) * rnd.uniform(0.0003, 0.0012)
            vol = rnd.uniform(0.002, 0.006)
        left -= 1
        o = price
        ret = drift + rnd.gauss(0, vol)
        if rnd.random() < 0.03:
            ret *= rnd.uniform(2.0, 3.5)
        c = o * (1 + ret)
        h = max(o, c) * (1 + abs(rnd.gauss(0, vol * 0.4)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, vol * 0.4)))
        v = 100 * (1 + abs(ret) / vol * rnd.uniform(0.3, 1.2)) * rnd.uniform(0.6, 1.4)
        out.append((t0 + i * tf, o, h, l, c, v))
        price = c
    return out


def simulate_rows(symbol, candles, start=300, qvol=5e7):
    rows = []
    sigs = analyze(candles, cfg, qvol, None, start=start)
    n = len(candles)
    for s in sigs:
        st = new_state()
        tps = (s["tp1"], s["tp2"], s["tp3"])
        for k in range(s["bar"] + 1, n):
            advance(st, s["side"], s["entry"], s["sl"], tps, candles[k], cfg.JOURNAL_MAX_BARS)
            if st["status"] == "closed":
                break
        row = {"symbol": symbol, "setup": s["setup"], "side": s["side"], "entry": s["entry"], "sl": s["sl"],
               "tp1": s["tp1"], "tp2": s["tp2"], "tp3": s["tp3"], "passed": s["passed"], "flags": s["flags"],
               "score": s["score"], "t": s["time"]}
        row.update(st)
        rows.append(row)
    return rows


async def fetch_all(symbols, days):
    bars = int(days * 86400 / {"1m": 60, "3m": 180, "5m": 300, "15m": 900}.get(cfg.TIMEFRAME, 300))
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        api = BingX(session, cfg)
        cfg.CANDLES = 1400
        out = {}
        for sym in symbols:
            try:
                out[sym] = await api.history(sym, bars)
                print(f"  {sym}: {len(out[sym])} velas", flush=True)
            except Exception as e:
                print(f"  {sym}: error {e!r}", flush=True)
        return out


async def top_symbols(n):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        uni = await BingX(session, cfg).universe()
        return [s for s, _ in uni[:n]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--days", type=float, default=30)
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--optimize", action="store_true", help="busca combinaciones de puertas con validacion train/test")
    ap.add_argument("--target", type=int, default=2, choices=[1, 2, 3], help="TP usado como objetivo unico en --optimize")
    ap.add_argument("--max-gates", type=int, default=3)
    ap.add_argument("--setups", default="", help="restringe --optimize a estos setups, p. ej. smc,zone")
    a = ap.parse_args()
    if a.synthetic:
        data = {f"SYN{i}-USDT": make_synthetic(int(a.days * 288), seed=i) for i in range(1, 6)}
    else:
        syms = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
        if a.top:
            syms = asyncio.run(top_symbols(a.top))
        if not syms:
            ap.error("indica --symbols, --top o --synthetic")
        print("Descargando historico...")
        data = asyncio.run(fetch_all(syms, a.days))
    rows = []
    for sym, candles in data.items():
        if len(candles) > 400:
            rows += simulate_rows(sym, candles)
    text = report_text(rows, a.days, cfg.GATES, cfg.COST_PCT)
    print(re.sub(r"</?[a-z]+>", "", text))
    if a.optimize:
        sel = [x.strip().lower() for x in a.setups.split(",") if x.strip()] or None
        print("\n" + optimize(rows, cfg.COST_PCT, a.target, a.max_gates, setups=sel))
    print(f"\nTotal senales simuladas: {len(rows)} (incluye las que no pasan las puertas)")


if __name__ == "__main__":
    main()
