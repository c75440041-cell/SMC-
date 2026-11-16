"""Orquestador: ejecuta los setups, calcula flags de confluencia, puntuacion 0-100, SL y objetivos."""
import math

from context import build
from setups import run_p7h, run_smc, run_trail, run_zone

KNOWN_FLAGS = ["htf15", "htf1h", "trend5", "btc", "adx", "session", "weekday", "sweep", "sweep_htf",
               "disp", "strong", "zone", "range_pos", "rvol", "cost", "liquid"]
FLAG_LABELS = [("htf15", "HTF15"), ("htf1h", "HTF1h"), ("trend5", "Tend5"), ("btc", "BTC"), ("adx", "ADX"),
               ("session", "Sesión"), ("sweep", "Barrida"), ("sweep_htf", "BarridaHTF"), ("disp", "Impulso"),
               ("strong", "Strong"), ("zone", "Zona"), ("range_pos", "Rango"), ("rvol", "Vol")]

# pesos de la puntuacion (se normaliza: las puertas activas se excluyen porque ya estan garantizadas)
WEIGHTS = {"htf15": 7, "htf1h": 7, "trend5": 3, "btc": 4, "adx": 4, "session": 5, "weekday": 0,
           "sweep": 8, "sweep_htf": 7, "disp": 8, "strong": 8, "zone": 6, "range_pos": 6, "rvol": 0, "cost": 0, "liquid": 0}


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _zone_overlap(x, i, side, lo, hi, pad):
    for is_high, bot, top, broken in x.zone_snap[i]:
        if not broken:
            continue
        if (side == "LONG" and is_high) or (side == "SHORT" and not is_high):
            if bot <= hi + pad and top >= lo - pad:
                return True
    return False


def _liquidity_tp(x, cfg, i, side, entry, risk, atr):
    """Objetivo de liquidez: el nivel opuesto mas cercano (pivotes, zonas sin romper, extremos 7h/dia),
    colocado justo ANTES del nivel, con R:R entre MIN_RR y MAX_LIQ_RR."""
    buf = cfg.TP_BUFFER_ATR * atr
    ph, pl = x.recent_pivots(i, 40)
    cands = []
    if side == "LONG":
        raw = [p for p in ph if p > entry]
        raw += [v for v in (x.pH7[i], x.pdh[i]) if v is not None and v > entry]
        raw += [bot for is_high, bot, top, broken in x.zone_snap[i] if is_high and not broken and bot > entry]
        cands = [r - buf for r in raw if r - buf > entry]
    else:
        raw = [p for p in pl if p < entry]
        raw += [v for v in (x.pL7[i], x.pdl[i]) if v is not None and v < entry]
        raw += [top for is_high, bot, top, broken in x.zone_snap[i] if (not is_high) and not broken and top < entry]
        cands = [r + buf for r in raw if r + buf < entry]
    good = [v for v in cands if cfg.MIN_RR <= abs(v - entry) / risk <= cfg.MAX_LIQ_RR]
    return min(good, key=lambda v: abs(v - entry)) if good else None


def finalize(x, cfg, cand, qvol, market):
    i, side, entry, sl = cand["bar"], cand["side"], cand["entry"], cand["sl"]
    atr = x.atr[i]
    risk = abs(entry - sl)
    if not atr or risk <= 0 or risk / entry * 100 > cfg.MAX_RISK_PCT:
        return None
    d = 1 if side == "LONG" else -1
    risk_pct = risk / entry * 100
    cost_r = cfg.COST_PCT / risk_pct          # coste de ida y vuelta expresado en R
    lo, hi = cand.get("lo", x.l[i]), cand.get("hi", x.h[i])

    sw = x.sw_lo[i] if side == "LONG" else x.sw_hi[i]
    sw7 = x.sw7_lo[i] if side == "LONG" else x.sw7_hi[i]
    pH, pL = x.pH7[i], x.pL7[i]
    range_pos = False
    if pH is not None and pL is not None and pH > pL:
        pos = (entry - pL) / (pH - pL)
        range_pos = pos <= cfg.RANGE_FAV if side == "LONG" else pos >= 1 - cfg.RANGE_FAV
    sc = x.sc_bull if side == "LONG" else x.sc_bear
    disp = cand.get("disp")
    if disp is None:
        disp = any(sc[j] for j in range(max(0, i - cfg.DISP_LOOKBACK + 1), i + 1))
    btc_ok = True if (market is None or cand.get("is_btc")) else market.get("t15", 0) in (d, 0)

    flags = {
        "htf15": x.trend15[i] == d,
        "htf1h": x.trend1h[i] == d,
        "trend5": x.trend5[i] == d,
        "btc": bool(btc_ok),
        "adx": x.adx[i] is not None and x.adx[i] >= cfg.ADX_MIN,
        "session": x.sess[i],
        "weekday": not x.weekend[i],
        "sweep": sw >= 0 and i - sw <= cfg.SWEEP_LOOKBACK,
        "sweep_htf": sw7 >= 0 and i - sw7 <= cfg.SWEEP_LOOKBACK,
        "disp": bool(disp),
        "strong": bool(cand.get("strong", sc[i])),
        "zone": bool(cand.get("zone", _zone_overlap(x, i, side, lo, hi, cfg.ZONE_CONF_PAD_ATR * atr))),
        "range_pos": range_pos,
        "rvol": x.rvol[i] >= cfg.SC_RVOL,
        "cost": cost_r <= cfg.MAX_COST_R,
        "liquid": qvol >= cfg.MIN_LIQ_USDT,
    }

    liq = _liquidity_tp(x, cfg, i, side, entry, risk, atr)
    rr_liq = abs(liq - entry) / risk if liq else None
    tps = [entry + d * risk * r for r in (cfg.TP1_R, cfg.TP2_R, cfg.TP3_R)]

    earned = possible = 0.0
    for k, w in WEIGHTS.items():
        if w and k not in cfg.GATES:
            possible += w
            earned += w if flags[k] else 0
    risk_atr = risk / atr
    rr_eff = rr_liq if rr_liq else cfg.TP2_R
    cont = [(8, _clamp(min(x.rvol[i], 3.0) / 3.0)), (8, _clamp(1.0 - cost_r / 0.5)),
            (8, _clamp(min(rr_eff, 4.0) / 4.0)),
            (5, _clamp(math.log10(qvol / 1e6) / 3.0) if qvol > 1e6 else 0.0)]
    for w, val in cont:
        possible += w
        earned += w * val
    score = round(100.0 * earned / possible, 1) if possible else 0.0

    return {"group": cand["group"], "setup": cand["setup"], "side": side, "bar": i, "time": x.t[i],
            "entry": entry, "sl": sl, "tp1": tps[0], "tp2": tps[1], "tp3": tps[2],
            "liq_tp": liq, "rr_liq": rr_liq, "risk_pct": risk_pct, "risk_atr": risk_atr, "cost_r": cost_r,
            "score": score, "flags": flags, "passed": all(flags.get(g, False) for g in cfg.GATES),
            "vol_ratio": x.rvol[i]}


def analyze(candles, cfg, qvol=0.0, market=None, start=None, is_btc=False):
    """candles: lista de tuplas (t,o,h,l,c,v) CERRADAS y ascendentes. Devuelve senales (pasen o no las puertas)."""
    n = len(candles)
    if n < 200:
        return []
    x = build(candles, cfg)
    if start is None:
        start = n - 1 - cfg.SIGNAL_MAX_AGE
    raw = []
    if "smc" in cfg.SETUPS:
        raw += run_smc(x, cfg, start)
    if "p7h" in cfg.SETUPS:
        raw += run_p7h(x, cfg, start)
    if "zone" in cfg.SETUPS:
        raw += run_zone(x, cfg, start)
    if "trail" in cfg.SETUPS:
        raw += run_trail(x, cfg, start)
    out = []
    for cand in raw:
        if is_btc:
            cand["is_btc"] = True
        s = finalize(x, cfg, cand, qvol, market)
        if s:
            out.append(s)
    return out


def regime(candles, cfg):
    """Tendencia actual de BTC (trail 5m/15m/1h) para el flag 'btc'."""
    if len(candles) < 200:
        return None
    x = build(candles, cfg)
    return {"t5": x.trend5[-1], "t15": x.trend15[-1], "t1h": x.trend1h[-1]}
