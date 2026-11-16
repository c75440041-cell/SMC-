"""Pruebas: python test_all.py   (no necesita red)"""
import asyncio
import os
import tempfile

import config as cfg
from backtest import make_synthetic, simulate_rows
from context import build
from indicators import adx_series, atr_series, map_htf, pivots, prev_levels, resample, trail_engine
from journal import Journal, advance, new_state, outcomes, report_text, summarize
from strategy import analyze, regime
from zones import ZoneTracker


def test_indicators():
    h = [10 + i * 0.1 + (i % 3) * 0.2 for i in range(100)]
    l = [x - 1 for x in h]
    c = [x - 0.5 for x in h]
    a = atr_series(h, l, c, 14)
    assert a[12] is None and a[13] > 0
    ad = adx_series(h, l, c, 14)
    assert ad[26] is None and 0 <= ad[27] <= 100 and ad[-1] > 20   # tendencia limpia -> ADX alto
    tr, trail = trail_engine(c, h, l, 28, 15, 1.25)
    assert tr[-1] == 1 and trail[-1] < c[-1]
    # empates en maximos: el pivote NO se anula
    ph, _ = pivots([1, 2, 3, 5, 3, 2, 1, 5, 1], [0] * 9, 2)
    assert 5.0 in [v for v in ph if v is not None]
    print("indicadores OK")


def test_htf_no_lookahead():
    base = 300_000
    t = [1_704_067_200_000 + i * base for i in range(60)]
    o = [float(i) for i in range(60)]
    h = [x + 1 for x in o]
    l = [x - 1 for x in o]
    c = [x + 0.5 for x in o]
    ends, ro, rh, rl, rc = resample(t, o, h, l, c, base, 900_000)
    assert len(ends) == 20
    vals = list(range(len(ends)))
    m = map_htf(t, base, ends, vals)
    # velas 0 y 1 (dentro de la 1a vela de 15m) no ven nada; la 3a (cierra la vela de 15m) ya ve la 0
    assert m[0] == 0 and m[1] == 0 and m[2] == 0 and m[3] == 0
    # al cierre de la 3a vela base (indice 2) la 1a vela HTF ya esta cerrada -> valor 0 (indice) pero existe;
    # lo importante: en la vela 5 (cierra la 2a HTF) vale 1, y en la 4 sigue valiendo 0
    assert m[4] == 0 and m[5] == 1
    # vela incompleta al final se excluye
    e2 = resample(t[:-1], o[:-1], h[:-1], l[:-1], c[:-1], base, 900_000)[0]
    assert len(e2) == 19
    print("HTF sin mirar al futuro OK")


def test_prev_levels():
    DAY, H = 86_400_000, 3_600_000
    t0 = 1_704_067_200_000  # 00:00 UTC
    t = [t0 + i * H for i in range(30)]
    h = [10 + (i == 3) * 5 for i in range(30)]   # maximo 15 en la hora 3 (bloque 0-7)
    l = [5 - (i == 4) * 2 for i in range(30)]
    H7 = 7 * H
    kf = lambda tt: (tt // DAY, (tt % DAY) // H7)
    sf = lambda k: k[0] * DAY + k[1] * H7
    pH, pL = prev_levels(t, h, l, kf, sf)
    assert pH[6] is None and pH[7] == 15 and pL[7] == 3     # bloque 7-14 ve el anterior 0-7
    assert pH[21] == 10                                      # bloque 21-24 ve el 14-21
    print("niveles previos OK")


class _C:  # cfg minimo para zonas
    ZONE_ATR_MULT, ZONE_MAX, ZONE_RETEST_EXPIRY = 0.35, 8, 30


def test_zones_symmetric():
    hcl = [(10.5, 9.5, 10), (9.5, 8.5, 9), (8.5, 7.5, 8), (7.5, 6.5, 7), (7, 6, 6.5), (7.5, 6.5, 7.2), (8.5, 7.5, 8),
           (9.5, 8.5, 9), (10, 9, 9.5), (9.5, 8, 8.5), (8.5, 6.8, 7), (7.2, 5.4, 5.6), (5.9, 5.2, 5.4), (6.2, 5.3, 5.8)]
    h = [x[0] for x in hcl]; l = [x[1] for x in hcl]; c = [x[2] for x in hcl]
    ph, pl = pivots(h, l, 2)
    zt = ZoneTracker(_C)
    ev = []
    for i in range(len(h)):
        ev += [(i,) + e for e in zt.step(i, h, l, c, 1.0, ph[i], pl[i])]
    shorts = [e for e in ev if e[1] == "SHORT"]
    assert shorts and shorts[0][0] == 13, ev           # el retest BAJISTA funciona (en el Pine original nunca dispara)
    # espejo -> retest alcista
    h2 = [20 - x for x in l]; l2 = [20 - x for x in h]; c2 = [20 - x for x in c]
    ph, pl = pivots(h2, l2, 2)
    zt = ZoneTracker(_C)
    ev = []
    for i in range(len(h2)):
        ev += [(i,) + e for e in zt.step(i, h2, l2, c2, 1.0, ph[i], pl[i])]
    assert [e for e in ev if e[1] == "LONG" and e[0] == 13], ev
    print("zonas simetricas OK")


def test_advance():
    tps = (102.0, 104.0, 106.0)
    def run(candles, side="LONG", sl=99.0, entry=100.0, mb=10):
        st = new_state()
        for cd in candles:
            advance(st, side, entry, sl, tps, cd, mb)
        return st
    cd = lambda h, l, c=100: (0, 100, h, l, c, 1)
    st = run([cd(105, 98)])                      # misma vela toca TP y SL -> SL primero
    assert st["stopped"] and not st["hit1"]
    st = run([cd(102.5, 100), cd(101, 98.5)])    # TP1 y luego SL
    assert st["hit1"] and not st["hit2"] and st["stopped"]
    o = outcomes({**st, "entry": 100, "sl": 99, "tp1": 102, "tp2": 104, "tp3": 106})
    assert o == [2.0, -1.0, -1.0], o
    st = run([cd(107, 100)])                     # llega a TP3
    assert st["hit3"] and st["status"] == "closed"
    st = run([cd(101, 99.5, 100.5)] * 3, mb=3)   # caduca
    assert st["status"] == "closed" and abs(st["exp_r"] - 0.5) < 1e-9
    tps_s = (98.0, 96.0, 94.0)                   # corto: TP1 alcanzado, SL no
    st = new_state(); advance(st, "SHORT", 100.0, 101.0, tps_s, cd(100.5, 97.9), 10)
    assert st["hit1"] and not st["stopped"]
    print("seguimiento de resultados OK")


def test_signals_and_flags():
    cfg.SIGNAL_MAX_AGE = 10**9
    candles = make_synthetic(30000, seed=3)
    sigs = analyze(candles, cfg, 5e7, None, start=300)
    by = {}
    for s in sigs:
        by.setdefault(s["setup"], []).append(s)
        assert 0 <= s["score"] <= 100
        d = 1 if s["side"] == "LONG" else -1
        assert (s["sl"] - s["entry"]) * d < 0 and (s["tp1"] - s["entry"]) * d > 0 < (s["tp3"] - s["tp1"]) * d
        if s["liq_tp"]:
            assert (s["liq_tp"] - s["entry"]) * d > 0
        assert set(s["flags"]) >= {"htf15", "htf1h", "zone", "range_pos", "sweep_htf"}
    print({k: len(v) for k, v in by.items()})
    for need in ("SMC", "P7H-retest", "ZONE", "TRAIL"):
        assert by.get(need), f"el setup {need} no genero senales"
    cfg.SIGNAL_MAX_AGE = 1
    print("setups y flags OK")


def test_causality():
    """Las senales hasta la vela k NO cambian si se recortan los datos posteriores (sin mirar al futuro)."""
    cfg.SIGNAL_MAX_AGE = 10**9
    candles = make_synthetic(6000, seed=5)
    full = analyze(candles, cfg, 5e7, None, start=300)
    for k in (3500, 4700):
        part = analyze(candles[:k], cfg, 5e7, None, start=300)
        key = lambda s: (s["setup"], s["side"], s["bar"], round(s["entry"], 9), round(s["sl"], 9), s["score"], s["passed"])
        a = sorted(key(s) for s in full if s["bar"] < k)
        b = sorted(key(s) for s in part)
        assert a == b, (k, len(a), len(b), set(a) ^ set(b))
    cfg.SIGNAL_MAX_AGE = 1
    print("causalidad (sin lookahead) OK")


def test_gates_and_p7h_modes():
    cfg.SIGNAL_MAX_AGE = 10**9
    old = cfg.GATES, cfg.P7H_MODES
    candles = make_synthetic(20000, seed=9)
    cfg.GATES = []
    allp = analyze(candles, cfg, 5e7, None, start=300)
    assert all(s["passed"] for s in allp)
    cfg.GATES = ["htf15", "htf1h"]
    g = analyze(candles, cfg, 5e7, None, start=300)
    assert 0 < sum(s["passed"] for s in g) < len(g)
    assert all(s["flags"]["htf15"] and s["flags"]["htf1h"] for s in g if s["passed"])
    cfg.P7H_MODES = ["strong", "retest", "break"]
    m = analyze(candles, cfg, 5e7, None, start=300)
    names = {s["setup"] for s in m}
    assert {"P7H-strong", "P7H-retest", "P7H-break"} <= names, names
    cfg.GATES, cfg.P7H_MODES = old
    cfg.SIGNAL_MAX_AGE = 1
    print("puertas y modos P7H OK")


def test_journal_and_report():
    cfg.SIGNAL_MAX_AGE = 10**9
    candles = make_synthetic(15000, seed=11)
    rows = simulate_rows("TEST-USDT", candles)
    closed = [r for r in rows if r["status"] == "closed"]
    assert len(closed) > 50
    s = summarize(closed)
    assert 0 <= s["p1"] <= 1 and s["p1"] >= s["p2"] >= s["p3"]
    txt = report_text(rows, 7, cfg.GATES)
    assert "Informe" in txt and len(txt) < 4000
    with tempfile.TemporaryDirectory() as d:
        j = Journal(os.path.join(d, "j.db"))
        sig = analyze(candles[:4000], cfg, 5e7, None, start=300)[0]
        sig["symbol"] = "X-USDT"
        assert j.add(sig) and not j.add(sig)            # no duplica
        j.commit()
        om = j.open_map()
        assert "X-USDT" in om
        j.resolve_symbol(om["X-USDT"], candles[:], 96)
        j.commit()
        rr = j.rows_since(0)
        assert rr[0]["status"] in ("open", "closed") and rr[0]["bars"] > 0
        j2 = Journal(os.path.join(d, "j.db"))           # persistencia
        assert j2.counts()[0] == 1
    cfg.SIGNAL_MAX_AGE = 1
    print("diario e informe OK")


def test_scan_end_to_end():
    import main
    candles_by = {f"S{i}-USDT": make_synthetic(1000, seed=20 + i)[:] for i in range(6)}
    candles_by["BTC-USDT"] = make_synthetic(1000, seed=99)

    class Fake:
        async def klines(self, sym):
            if sym == "FAIL-USDT":
                raise RuntimeError("boom")
            return candles_by[sym]

    cfg.SIGNAL_MAX_AGE = 10**9
    cfg.GATES = []
    j = Journal(":memory:")
    uni = [(s, 5e7) for s in candles_by] + [("FAIL-USDT", 1e7)]
    market = asyncio.run(main.get_market(Fake()))
    assert market and set(market) == {"t5", "t15", "t1h"}
    picks, n_elig, n_new, errors, n_stale = asyncio.run(main.scan(Fake(), j, uni, market))
    assert errors == 1 and n_new > 0 and len(picks) <= cfg.TOP_N
    assert sum(1 for p in picks if p["side"] == "LONG") <= cfg.MAX_SAME_DIR
    msg = main.build_message(picks, n_elig, len(uni), market)
    assert "TP1" in msg and len(msg) < 4000 * 2
    # segundo scan: sin duplicados
    picks2, _, n_new2, _, _ = asyncio.run(main.scan(Fake(), j, uni, market))
    assert n_new2 == 0 and not picks2
    cfg.SIGNAL_MAX_AGE = 1
    cfg.GATES = ["htf15", "cost", "liquid"]
    print("scan extremo a extremo OK")
    print(msg[:700])


def test_costs_and_significance():
    from journal import suggestions
    row = {"status": "closed", "entry": 100.0, "sl": 99.0, "tp1": 101.0, "tp2": 102.0, "tp3": 103.0,
           "hit1": 1, "hit2": 0, "hit3": 0, "stopped": 1, "exp_r": None}
    assert outcomes(row) == [1.0, -1.0, -1.0]
    o = outcomes(row, 0.12)                         # riesgo 1% -> coste 0.12R
    assert abs(o[0] - 0.88) < 1e-9 and abs(o[1] + 1.12) < 1e-9
    # flag con ventaja enorme y muestra grande -> conclusion solida; ruido -> ninguna
    import random
    rnd = random.Random(1)
    rows = []
    for i in range(400):
        good = i % 2 == 0
        win = rnd.random() < (0.7 if good else 0.3)
        rows.append({**row, "setup": "SMC", "passed": True, "flags": {"magic": good, "noise": rnd.random() < 0.5},
                     "hit1": int(win), "hit2": int(win), "hit3": 0, "stopped": int(not win)})
    sug = suggestions(rows, 0.0)
    assert any("magic" in x and "GATES" in x for x in sug), sug
    assert not any("noise" in x for x in sug), sug
    print("costes y significancia OK")


def test_optimize():
    from optimize import optimize
    cfg.SIGNAL_MAX_AGE = 10**9
    rows = []
    for sd in range(1, 5):
        rows += simulate_rows(f"S{sd}-USDT", make_synthetic(20000, seed=sd))
    txt = optimize(rows, cfg.COST_PCT, 2, 2)
    assert "TRAIN" in txt and "sin puertas" in txt
    assert "Muy pocas" in optimize(rows[:50], cfg.COST_PCT)
    cfg.SIGNAL_MAX_AGE = 1
    print("optimizador OK")


def test_stale_size_and_path():
    import main
    cfg.SIGNAL_MAX_AGE = 10**9
    cfg.GATES = []
    candles = make_synthetic(1000, seed=31)

    class Fake:
        def __init__(self, price): self.last_price = {"A-USDT": price}
        async def klines(self, sym): return candles

    sigs = analyze(candles, cfg, 5e7, None)
    assert sigs
    ref = sigs[-1]
    # precio actual muy lejos a favor -> ninguna senal se envia
    far = ref["entry"] * (1.5 if ref["side"] == "LONG" else 0.5)
    j = Journal(":memory:")
    picks, n_elig, n_new, err, n_stale = asyncio.run(main.scan(Fake(far), j, [("A-USDT", 5e7)], None))
    assert n_new > 0 and n_stale > 0 and not [p for p in picks if p["symbol"] == "A-USDT" and p["side"] == ref["side"] and p["drift_r"] > 0.25]
    # tamano de posicion
    cfg.ACCOUNT_USDT, cfg.RISK_PCT, cfg.MAX_LEVERAGE = 1000.0, 1.0, 10.0
    sig = dict(ref, symbol="A-USDT")
    txt = main.position_size(sig)
    expect = 10.0 / (ref["risk_pct"] / 100)
    assert "Tamaño" in txt and (str(int(min(expect, 10000))) in txt.replace(",", "") or "limitado" in txt), (txt, expect)
    cfg.ACCOUNT_USDT = 0
    assert main.position_size(sig) == ""
    msg = main.build_message([dict(sig, drift_r=0.0)], 1, 1, {"t5": 1, "t15": 1, "t1h": -1})
    assert "Válida" in msg and "costes" in msg
    cfg.SIGNAL_MAX_AGE = 1
    cfg.GATES = ["htf15", "cost", "liquid"]
    # ruta del diario en Railway
    import importlib, os
    os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = "/data"
    os.environ.pop("JOURNAL_PATH", None)
    importlib.reload(cfg)
    assert cfg.JOURNAL_PATH == "/data/journal.db"
    del os.environ["RAILWAY_VOLUME_MOUNT_PATH"]
    importlib.reload(cfg)
    assert cfg.JOURNAL_PATH == "journal.db"
    print("filtro de entrada pasada, tamaño y ruta del diario OK")


if __name__ == "__main__":
    for fn in [test_indicators, test_htf_no_lookahead, test_prev_levels, test_zones_symmetric, test_advance,
               test_signals_and_flags, test_causality, test_gates_and_p7h_modes, test_journal_and_report,
               test_costs_and_significance, test_optimize, test_scan_end_to_end, test_stale_size_and_path]:
        fn()
    print("\nTODAS LAS PRUEBAS OK")
