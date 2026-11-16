"""Los cuatro setups. Cada uno recorre las velas con su propio estado y devuelve candidatos
{group, setup, side, bar, entry, sl, ...}. Solo se crean candidatos para bar >= start."""


def run_smc(x, cfg, start):
    """Barrida -> MSS/CHOCH -> Order Block -> retest (port del Pine 'SMC Notebook')."""
    n, o, h, l, c, atr = x.n, x.o, x.h, x.l, x.c, x.atr
    trend = 0
    last_high = last_low = None
    ob_bull = ob_bear = None
    last_long = last_short = None
    close_through = cfg.OB_MITIGATION == "Close through"
    mid_mode = cfg.ENTRY_MODE != "Retest OB"
    out = []
    for i in range(n):
        ph, pl = x.ph_conf[i], x.pl_conf[i]
        bull_bos = trend <= 0 and last_high is not None and c[i] > last_high
        bear_bos = trend >= 0 and last_low is not None and c[i] < last_low
        bull_choch = trend == -1 and last_high is not None and c[i] > last_high
        bear_choch = trend == 1 and last_low is not None and c[i] < last_low
        if bull_choch or bull_bos:
            trend, last_low = 1, l[i]
        if bear_choch or bear_bos:
            trend, last_high = -1, h[i]
        if ph is not None:
            last_high = ph
        if pl is not None:
            last_low = pl

        # Order Blocks (ultima vela contraria antes del impulso). disp = la vela de ruptura es una Strong Closure
        if bull_choch or (bull_bos and trend == 1):
            for j in (i - 1, i - 2):
                if j >= 0 and c[j] < o[j]:
                    ob_bull = {"top": h[j], "bot": l[j], "created": i, "active": True, "disp": x.sc_bull[i]}
                    break
        if bear_choch or (bear_bos and trend == -1):
            for j in (i - 1, i - 2):
                if j >= 0 and c[j] > o[j]:
                    ob_bear = {"top": h[j], "bot": l[j], "created": i, "active": True, "disp": x.sc_bear[i]}
                    break
        if ob_bull and ob_bull["active"] and ((c[i] < ob_bull["bot"]) if close_through else (l[i] < ob_bull["bot"])):
            ob_bull["active"] = False
        if ob_bear and ob_bear["active"] and ((c[i] > ob_bear["top"]) if close_through else (h[i] > ob_bear["top"])):
            ob_bear["active"] = False

        long_entry = short_entry = False
        if ob_bull and ob_bull["active"] and i - ob_bull["created"] >= cfg.OB_MIN_AGE:
            if l[i] <= ob_bull["top"] and h[i] >= ob_bull["bot"]:
                long_entry = (c[i] > o[i] and c[i] > ob_bull["bot"]) if not mid_mode else c[i] >= (ob_bull["top"] + ob_bull["bot"]) / 2
        if ob_bear and ob_bear["active"] and i - ob_bear["created"] >= cfg.OB_MIN_AGE:
            if h[i] >= ob_bear["bot"] and l[i] <= ob_bear["top"]:
                short_entry = (c[i] < o[i] and c[i] < ob_bear["top"]) if not mid_mode else c[i] <= (ob_bear["top"] + ob_bear["bot"]) / 2

        sig_long = long_entry and (last_long is None or i - last_long > cfg.COOLDOWN_BARS)
        sig_short = short_entry and (last_short is None or i - last_short > cfg.COOLDOWN_BARS)
        if sig_long:
            last_long = i
            ob_bull["active"] = False
            if i >= start and atr[i]:
                out.append({"group": "SMC", "setup": "SMC", "side": "LONG", "bar": i, "entry": c[i],
                            "sl": ob_bull["bot"] - cfg.SL_BUFFER_ATR * atr[i],
                            "lo": ob_bull["bot"], "hi": ob_bull["top"], "disp": ob_bull["disp"]})
        if sig_short:
            last_short = i
            ob_bear["active"] = False
            if i >= start and atr[i]:
                out.append({"group": "SMC", "setup": "SMC", "side": "SHORT", "bar": i, "entry": c[i],
                            "sl": ob_bear["top"] + cfg.SL_BUFFER_ATR * atr[i],
                            "lo": ob_bear["bot"], "hi": ob_bear["top"], "disp": ob_bear["disp"]})
    return out


def run_p7h(x, cfg, start):
    """Rechazo del nivel 25% del rango del bloque previo de 7h con vela Strong Closure.
    Modos: strong (entra en la vela fuerte) | retest (REAL: el precio vuelve al nivel y rechaza) | break (continuacion)."""
    n, o, h, l, c, atr = x.n, x.o, x.h, x.l, x.c, x.atr
    pct = cfg.P7H_LEVEL_PCT / 100.0
    modes = [m for m in cfg.P7H_MODES if m in ("strong", "retest", "break")]
    states = {m: {"bear": None, "bull": None} for m in modes}
    last = {(m, s): None for m in modes for s in ("bear", "bull")}
    out = []

    def emit(m, side, i, sl):
        key = (m, "bear" if side == "SHORT" else "bull")
        if last[key] is not None and i - last[key] <= cfg.P7H_COOLDOWN:
            return
        last[key] = i
        if i >= start and atr[i]:
            out.append({"group": "P7H", "setup": "P7H-" + m, "side": side, "bar": i, "entry": c[i],
                        "sl": sl, "strong": True, "disp": True})

    for i in range(1, n):
        pH, pL = x.pH7[i], x.pL7[i]
        bear_setup = bull_setup = False
        if pH is not None and pL is not None and pH - pL > 0:
            rng = pH - pL
            up, dn = pH - rng * pct, pL + rng * pct
            bear_setup = x.sc_bear[i] and c[i] < up and (o[i] >= up or c[i - 1] >= up)
            bull_setup = x.sc_bull[i] and c[i] > dn and (o[i] <= dn or c[i - 1] <= dn)
        for m in modes:
            if m == "strong":
                continue
            st = states[m]
            for side in ("bear", "bull"):
                s = st[side]
                if s is None:
                    continue
                age = i - s["bar"]
                if age < 1:
                    continue
                if age > cfg.P7H_RETEST_WIN:
                    st[side] = None
                    continue
                if side == "bear":
                    if c[i] > s["ext"]:
                        st[side] = None
                        continue
                    trig = (h[i] >= s["lvl"] and c[i] < s["lvl"]) if m == "retest" else c[i] < s["lvl"]
                    if trig:
                        st[side] = None
                        emit(m, "SHORT", i, max(s["ext"], h[i]) + cfg.P7H_SL_BUFFER_ATR * (atr[i] or 0))
                else:
                    if c[i] < s["ext"]:
                        st[side] = None
                        continue
                    trig = (l[i] <= s["lvl"] and c[i] > s["lvl"]) if m == "retest" else c[i] > s["lvl"]
                    if trig:
                        st[side] = None
                        emit(m, "LONG", i, min(s["ext"], l[i]) - cfg.P7H_SL_BUFFER_ATR * (atr[i] or 0))
        if bear_setup:
            for m in modes:
                if m == "strong":
                    emit(m, "SHORT", i, h[i] + cfg.P7H_SL_BUFFER_ATR * (atr[i] or 0))
                else:
                    states[m]["bear"] = {"bar": i, "lvl": c[i], "ext": h[i]}
        if bull_setup:
            for m in modes:
                if m == "strong":
                    emit(m, "LONG", i, l[i] - cfg.P7H_SL_BUFFER_ATR * (atr[i] or 0))
                else:
                    states[m]["bull"] = {"bar": i, "lvl": c[i], "ext": l[i]}
    return out


def run_zone(x, cfg, start):
    """Ruptura + retest de zona de liquidez (el precio rompe un maximo/minimo y la zona cambia de rol)."""
    out = []
    last = {"LONG": None, "SHORT": None}
    h, l, c, atr = x.h, x.l, x.c, x.atr
    for i in range(x.n):
        for side, zbot, ztop in x.zone_events[i]:
            if last[side] is not None and i - last[side] <= cfg.COOLDOWN_BARS:
                continue
            last[side] = i
            if i < start or not atr[i]:
                continue
            if side == "LONG":
                sl = min(l[i], zbot) - cfg.SL_BUFFER_ATR * atr[i]
            else:
                sl = max(h[i], ztop) + cfg.SL_BUFFER_ATR * atr[i]
            out.append({"group": "ZONE", "setup": "ZONE", "side": side, "bar": i, "entry": c[i], "sl": sl, "zone": True})
    return out


def run_trail(x, cfg, start):
    """Tras un cambio de tendencia del trail, entra en el pullback que toca el trail y cierra a favor.
    A diferencia del Pine, la espera CADUCA y se usa el trail actual (no el congelado)."""
    out = []
    h, l, c, atr, tr5, trail = x.h, x.l, x.c, x.atr, x.trend5, x.trail5
    pend_dir, pend_bar = 0, -1
    last = {"LONG": None, "SHORT": None}
    for i in range(1, x.n):
        if tr5[i] != 0 and tr5[i - 1] != 0 and tr5[i] != tr5[i - 1]:
            pend_dir, pend_bar = tr5[i], i
            continue
        if pend_dir == 0:
            continue
        if tr5[i] != pend_dir or i - pend_bar > cfg.TRAIL_RETEST_EXPIRY:
            pend_dir = 0
            continue
        tr = trail[i]
        if tr is None or not atr[i]:
            continue
        if pend_dir == 1 and l[i] <= tr and c[i] >= tr:
            side, sl = "LONG", min(l[i], tr) - cfg.SL_BUFFER_ATR * atr[i]
        elif pend_dir == -1 and h[i] >= tr and c[i] <= tr:
            side, sl = "SHORT", max(h[i], tr) + cfg.SL_BUFFER_ATR * atr[i]
        else:
            continue
        pend_dir = 0
        if last[side] is not None and i - last[side] <= cfg.COOLDOWN_BARS:
            continue
        last[side] = i
        if i >= start:
            out.append({"group": "TRAIL", "setup": "TRAIL", "side": side, "bar": i, "entry": c[i], "sl": sl})
    return out
