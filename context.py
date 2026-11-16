"""Calcula UNA vez todas las series que usan los setups (tendencias, niveles, zonas, sesion...).
Todo es causal: el valor en la vela i solo usa informacion disponible al cierre de i."""
import bisect

from indicators import (DAY, HOUR, TF_MS, adx_series, atr_series, map_htf, pivots, prev_levels,
                        resample, trail_engine)
from zones import ZoneTracker

H7 = 7 * HOUR


class Ctx:
    def recent_pivots(self, i, k=40):
        a = bisect.bisect_right(self.ph_bars, i)
        b = bisect.bisect_right(self.pl_bars, i)
        return self.ph_vals[max(0, a - k):a], self.pl_vals[max(0, b - k):b]


def _htf_trend(t, o, h, l, c, base_ms, tf_ms, cfg, trend5):
    n = len(c)
    if tf_ms == base_ms:
        return trend5
    if tf_ms < base_ms or tf_ms % base_ms:
        return [0] * n
    ends, ro, rh, rl, rc = resample(t, o, h, l, c, base_ms, tf_ms)
    if len(ends) < cfg.TRAIL_ATR_LEN + 3:
        return [0] * n
    tr, _ = trail_engine(rc, rh, rl, cfg.TRAIL_MA_LEN, cfg.TRAIL_ATR_LEN, cfg.TRAIL_MULT)
    return map_htf(t, base_ms, ends, tr)


def build(candles, cfg):
    x = Ctx()
    n = x.n = len(candles)
    t = x.t = [k[0] for k in candles]
    o = x.o = [k[1] for k in candles]
    h = x.h = [k[2] for k in candles]
    l = x.l = [k[3] for k in candles]
    c = x.c = [k[4] for k in candles]
    v = x.v = [k[5] for k in candles]
    base = x.base_ms = TF_MS.get(cfg.TIMEFRAME, 300_000)
    atr = x.atr = atr_series(h, l, c, 14)

    # volumen relativo (media de las 20 velas anteriores)
    pre = [0.0]
    for vv in v:
        pre.append(pre[-1] + vv)
    rvol = x.rvol = [1.0] * n
    for i in range(1, n):
        lo = max(0, i - 20)
        avg = (pre[i] - pre[lo]) / (i - lo)
        rvol[i] = v[i] / avg if avg > 0 else 1.0

    # Strong Closure
    sc_bull = x.sc_bull = [False] * n
    sc_bear = x.sc_bear = [False] * n
    for i in range(n):
        rng = h[i] - l[i]
        if rng <= 0 or not atr[i]:
            continue
        if rng < cfg.SC_MIN_ATR * atr[i] or abs(c[i] - o[i]) < rng * cfg.SC_BODY_PCT / 100 or rvol[i] < cfg.SC_RVOL:
            continue
        if c[i] > o[i] and c[i] >= h[i] - rng * cfg.SC_CLOSE_PCT / 100:
            sc_bull[i] = True
        if c[i] < o[i] and c[i] <= l[i] + rng * cfg.SC_CLOSE_PCT / 100:
            sc_bear[i] = True

    x.adx = adx_series(h, l, c, cfg.ADX_LEN)
    x.trend5, x.trail5 = trail_engine(c, h, l, cfg.TRAIL_MA_LEN, cfg.TRAIL_ATR_LEN, cfg.TRAIL_MULT)
    x.trend15 = _htf_trend(t, o, h, l, c, base, TF_MS["15m"], cfg, x.trend5)
    x.trend1h = _htf_trend(t, o, h, l, c, base, TF_MS["1h"], cfg, x.trend5)

    # sesion / fin de semana (UTC, por hora de apertura de la vela)
    x.sess = [any(a <= ((tt % DAY) // HOUR) < b for a, b in cfg.SESSION_WINDOWS) for tt in t]
    x.weekend = [((tt // DAY) + 3) % 7 >= 5 for tt in t]

    # pivotes (SMC) y barridas de pivote
    ph, pl = x.ph_conf, x.pl_conf = pivots(h, l, cfg.SWING_LEN)
    x.ph_bars = [i for i in range(n) if ph[i] is not None]
    x.ph_vals = [ph[i] for i in x.ph_bars]
    x.pl_bars = [i for i in range(n) if pl[i] is not None]
    x.pl_vals = [pl[i] for i in x.pl_bars]
    sw_hi, sw_lo = x.sw_hi, x.sw_lo = [-1] * n, [-1] * n
    lph = lpl = None
    s_hi = s_lo = -1
    for i in range(n):
        if ph[i] is not None:
            lph = ph[i]
        if pl[i] is not None:
            lpl = pl[i]
        if lph is not None and h[i] > lph and c[i] < lph:
            s_hi = i
        if lpl is not None and l[i] < lpl and c[i] > lpl:
            s_lo = i
        sw_hi[i], sw_lo[i] = s_hi, s_lo

    # zonas de liquidez
    zph, zpl = pivots(h, l, cfg.ZONE_SWING_LEN)
    zt = ZoneTracker(cfg)
    x.zone_snap, x.zone_events = [None] * n, [None] * n
    for i in range(n):
        x.zone_events[i] = zt.step(i, h, l, c, atr[i], zph[i], zpl[i])
        x.zone_snap[i] = zt.snapshot()

    # niveles del bloque previo de 7h y del dia previo
    if cfg.P7H_ALIGN == "continuous":
        kf, sf = (lambda tt: tt // H7), (lambda k: k * H7)
    else:
        kf, sf = (lambda tt: (tt // DAY, (tt % DAY) // H7)), (lambda k: k[0] * DAY + k[1] * H7)
    x.pH7, x.pL7 = prev_levels(t, h, l, kf, sf)
    x.pdh, x.pdl = prev_levels(t, h, l, lambda tt: tt // DAY, lambda k: k * DAY)

    # barridas de los extremos previos (7h / dia)
    s7_hi, s7_lo = x.sw7_hi, x.sw7_lo = [-1] * n, [-1] * n
    a = b = -1
    for i in range(n):
        for lv in (x.pH7[i], x.pdh[i]):
            if lv is not None and h[i] > lv and c[i] < lv:
                a = i
        for lv in (x.pL7[i], x.pdl[i]):
            if lv is not None and l[i] < lv and c[i] > lv:
                b = i
        s7_hi[i], s7_lo[i] = a, b
    return x
