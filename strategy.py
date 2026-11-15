"""Port del indicador Pine 'SMC Notebook': Barrida -> MSS -> CHOCH -> OB -> retest.
Trabaja solo con velas cerradas. Devuelve senales puntuadas (0-100) para el ranking."""
import math


def _atr(h, l, c, period=14):
    n = len(c)
    out = [None] * n
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, n)]
    if n < period:
        return out
    val = sum(tr[:period]) / period
    out[period - 1] = val
    for i in range(period, n):
        val = (val * (period - 1) + tr[i]) / period
        out[i] = val
    return out


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def analyze(candles, cfg, qvol=0.0):
    """candles: lista de dicts {t,o,h,l,c,v} ordenada y SOLO cerradas. Devuelve lista de senales recientes."""
    n = len(candles)
    S = cfg.SWING_LEN
    if n < max(60, 4 * S):
        return []
    t = [x["t"] for x in candles]
    o = [x["o"] for x in candles]
    h = [x["h"] for x in candles]
    l = [x["l"] for x in candles]
    c = [x["c"] for x in candles]
    v = [x["v"] for x in candles]
    atr = _atr(h, l, c)

    trend = 0
    last_ph = last_pl = None
    last_high = last_low = None
    ph_list, pl_list = [], []
    sweep_hi_bar = sweep_lo_bar = None
    ob_bull = ob_bear = None
    last_long = last_short = None
    close_through = cfg.OB_MITIGATION == "Close through"
    mid_mode = cfg.ENTRY_MODE != "Retest OB"
    signals = []

    for i in range(n):
        # --- pivotes (confirmados S velas despues) ---
        piv_h = piv_l = None
        if i >= 2 * S:
            k = i - S
            wh = h[k - S:k + S + 1]
            wl = l[k - S:k + S + 1]
            if h[k] == max(wh) and wh.count(h[k]) == 1:
                piv_h = h[k]
            if l[k] == min(wl) and wl.count(l[k]) == 1:
                piv_l = l[k]
        if piv_h is not None:
            last_ph = piv_h
            ph_list.append(piv_h)
        if piv_l is not None:
            last_pl = piv_l
            pl_list.append(piv_l)

        # --- barridas ---
        if last_ph is not None and h[i] > last_ph and c[i] < last_ph:
            sweep_hi_bar = i
        if last_pl is not None and l[i] < last_pl and c[i] > last_pl:
            sweep_lo_bar = i

        # --- estructura ---
        bull_bos = trend <= 0 and last_high is not None and c[i] > last_high
        bear_bos = trend >= 0 and last_low is not None and c[i] < last_low
        bull_choch = trend == -1 and last_high is not None and c[i] > last_high
        bear_choch = trend == 1 and last_low is not None and c[i] < last_low
        if bull_choch or bull_bos:
            trend = 1
            last_low = l[i]
        if bear_choch or bear_bos:
            trend = -1
            last_high = h[i]
        if piv_h is not None:
            last_high = piv_h
        if piv_l is not None:
            last_low = piv_l

        # --- order blocks ---
        if bull_choch or (bull_bos and trend == 1):
            for j in (i - 1, i - 2):
                if j >= 0 and c[j] < o[j]:
                    ob_bull = {"top": h[j], "bot": l[j], "bar": j, "created": i, "active": True}
                    break
        if bear_choch or (bear_bos and trend == -1):
            for j in (i - 1, i - 2):
                if j >= 0 and c[j] > o[j]:
                    ob_bear = {"top": h[j], "bot": l[j], "bar": j, "created": i, "active": True}
                    break

        if ob_bull and ob_bull["active"]:
            if (c[i] < ob_bull["bot"]) if close_through else (l[i] < ob_bull["bot"]):
                ob_bull["active"] = False
        if ob_bear and ob_bear["active"]:
            if (c[i] > ob_bear["top"]) if close_through else (h[i] > ob_bear["top"]):
                ob_bear["active"] = False

        # --- entrada ---
        long_entry = short_entry = False
        if ob_bull and ob_bull["active"] and i - ob_bull["created"] >= cfg.OB_MIN_AGE:
            if l[i] <= ob_bull["top"] and h[i] >= ob_bull["bot"]:
                if not mid_mode:
                    long_entry = c[i] > o[i] and c[i] > ob_bull["bot"]
                else:
                    long_entry = c[i] >= (ob_bull["top"] + ob_bull["bot"]) / 2
        if ob_bear and ob_bear["active"] and i - ob_bear["created"] >= cfg.OB_MIN_AGE:
            if h[i] >= ob_bear["bot"] and l[i] <= ob_bear["top"]:
                if not mid_mode:
                    short_entry = c[i] < o[i] and c[i] < ob_bear["top"]
                else:
                    short_entry = c[i] <= (ob_bear["top"] + ob_bear["bot"]) / 2

        sig_long = long_entry and (last_long is None or i - last_long > cfg.COOLDOWN_BARS)
        sig_short = short_entry and (last_short is None or i - last_short > cfg.COOLDOWN_BARS)

        if cfg.REQUIRE_SWEEP:
            if sig_long and not (sweep_lo_bar is not None and i - sweep_lo_bar <= cfg.SWEEP_LOOKBACK):
                sig_long = False
            if sig_short and not (sweep_hi_bar is not None and i - sweep_hi_bar <= cfg.SWEEP_LOOKBACK):
                sig_short = False

        used_bull, used_bear = ob_bull, ob_bear
        if sig_long:
            last_long = i
            ob_bull["active"] = False
        if sig_short:
            last_short = i
            ob_bear["active"] = False

        # --- construir senal solo si es reciente ---
        if (sig_long or sig_short) and i >= n - 1 - cfg.SIGNAL_MAX_AGE and atr[i]:
            side = "LONG" if sig_long else "SHORT"
            ob = used_bull if sig_long else used_bear
            entry = c[i]
            if side == "LONG":
                sl = ob["bot"] - cfg.SL_BUFFER_ATR * atr[i]
                risk = entry - sl
                cands = [p for p in ph_list[-60:] if p > entry]
                swept = sweep_lo_bar is not None and i - sweep_lo_bar <= cfg.SWEEP_LOOKBACK
            else:
                sl = ob["top"] + cfg.SL_BUFFER_ATR * atr[i]
                risk = sl - entry
                cands = [p for p in pl_list[-60:] if p < entry]
                swept = sweep_hi_bar is not None and i - sweep_hi_bar <= cfg.SWEEP_LOOKBACK
            if risk <= 0 or risk / entry * 100 > cfg.MAX_RISK_PCT:
                continue
            tp = None
            if cfg.USE_LIQUIDITY_TP:
                good = [p for p in cands if cfg.MIN_RR <= abs(p - entry) / risk <= 6.0]
                if good:
                    tp = min(good) if side == "LONG" else max(good)
            if tp is None:
                tp = entry + risk * cfg.RR_TARGET if side == "LONG" else entry - risk * cfg.RR_TARGET
            rr = abs(tp - entry) / risk

            # puntuacion 0-100
            avg_v = sum(v[max(0, i - 20):i]) / max(1, len(v[max(0, i - 20):i]))
            vol_ratio = v[i] / avg_v if avg_v > 0 else 1.0
            rng = h[i] - l[i]
            body = abs(c[i] - o[i]) / rng if rng > 0 else 0
            risk_atr = risk / atr[i]
            score = (
                min(rr, 4.0) / 4.0 * 30
                + (20 if swept else 0)
                + _clamp(1.0 - (risk_atr - 0.5) / 4.0) * 15
                + min(vol_ratio, 3.0) / 3.0 * 15
                + body * 10
                + (_clamp(math.log10(qvol / 1e6) / 3.0) * 10 if qvol > 1e6 else 0)
            )
            signals.append({
                "side": side, "bar": i, "time": t[i], "entry": entry, "sl": sl, "tp": tp,
                "rr": rr, "score": round(score, 1), "swept": swept, "vol_ratio": vol_ratio,
                "risk_pct": risk / entry * 100,
            })
    return signals
