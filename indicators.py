"""Indicadores y utilidades de series (puro Python, sin dependencias)."""

TF_MS = {"1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
HOUR = 3_600_000
DAY = 86_400_000


def ema_series(vals, period):
    a = 2.0 / (period + 1)
    out, prev = [], None
    for x in vals:
        prev = x if prev is None else prev + a * (x - prev)
        out.append(prev)
    return out


def true_range(h, l, c):
    return [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]


def atr_series(h, l, c, period=14):
    n = len(c)
    out = [None] * n
    if n < period:
        return out
    tr = true_range(h, l, c)
    val = sum(tr[:period]) / period
    out[period - 1] = val
    for i in range(period, n):
        val = (val * (period - 1) + tr[i]) / period
        out[i] = val
    return out


def adx_series(h, l, c, period=14):
    n = len(c)
    out = [None] * n
    if n < 2 * period + 1:
        return out
    tr = true_range(h, l, c)
    pdm, mdm = [0.0] * n, [0.0] * n
    for i in range(1, n):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        pdm[i] = up if (up > dn and up > 0) else 0.0
        mdm[i] = dn if (dn > up and dn > 0) else 0.0

    def dx_of(s_tr, s_p, s_m):
        if s_tr <= 0:
            return 0.0
        pdi, mdi = 100 * s_p / s_tr, 100 * s_m / s_tr
        d = pdi + mdi
        return 100 * abs(pdi - mdi) / d if d > 0 else 0.0

    s_tr, s_p, s_m = sum(tr[1:period + 1]), sum(pdm[1:period + 1]), sum(mdm[1:period + 1])
    dx = [None] * n
    dx[period] = dx_of(s_tr, s_p, s_m)
    for i in range(period + 1, n):
        s_tr += tr[i] - s_tr / period
        s_p += pdm[i] - s_p / period
        s_m += mdm[i] - s_m / period
        dx[i] = dx_of(s_tr, s_p, s_m)
    first = 2 * period - 1
    val = sum(dx[period:2 * period]) / period
    out[first] = val
    for i in range(first + 1, n):
        val = (val * (period - 1) + dx[i]) / period
        out[i] = val
    return out


def pivots(h, l, S):
    """Pivotes confirmados S velas despues. ph[i]/pl[i] = valor del pivote confirmado en la vela i.
    Maximo estricto frente a la izquierda y >= frente a la derecha (los maximos iguales no anulan el pivote)."""
    n = len(h)
    ph, pl = [None] * n, [None] * n
    for i in range(2 * S, n):
        k = i - S
        if h[k] > max(h[k - S:k]) and h[k] >= max(h[k + 1:i + 1]):
            ph[i] = h[k]
        if l[k] < min(l[k - S:k]) and l[k] <= min(l[k + 1:i + 1]):
            pl[i] = l[k]
    return ph, pl


def trail_engine(c, h, l, ma_len, atr_len, mult):
    """Motor de tendencia tipo BOSWaves: EMA +- ATR*mult con trail que solo avanza a favor."""
    n = len(c)
    ma = ema_series(c, ma_len)
    atr = atr_series(h, l, c, atr_len)
    trend, trail = [0] * n, [None] * n
    ct, ctr = 0, None
    for i in range(n):
        if atr[i] is None:
            continue
        up, dn = ma[i] - atr[i] * mult, ma[i] + atr[i] * mult
        if ctr is None:
            ct = 1 if c[i] > ma[i] else -1
            ctr = up if ct == 1 else dn
        elif ct == 1:
            ctr = max(up, ctr)
            if c[i] < ctr:
                ct, ctr = -1, dn
        else:
            ctr = min(dn, ctr)
            if c[i] > ctr:
                ct, ctr = 1, up
        trend[i], trail[i] = ct, ctr
    return trend, trail


def resample(t, o, h, l, c, base_ms, tf_ms):
    """Agrega velas base en velas de tf_ms alineadas a epoch. Solo devuelve velas COMPLETAS."""
    per = tf_ms // base_ms
    ends, ro, rh, rl, rc = [], [], [], [], []
    cur = None

    def flush(b):
        if b and b["cnt"] == per and b["first"] == b["b"] * tf_ms:
            ends.append((b["b"] + 1) * tf_ms)
            ro.append(b["o"]); rh.append(b["h"]); rl.append(b["l"]); rc.append(b["c"])

    for i in range(len(t)):
        b = t[i] // tf_ms
        if cur is None or cur["b"] != b:
            flush(cur)
            cur = {"b": b, "o": o[i], "h": h[i], "l": l[i], "c": c[i], "cnt": 1, "first": t[i]}
        else:
            cur["cnt"] += 1
            cur["h"] = max(cur["h"], h[i])
            cur["l"] = min(cur["l"], l[i])
            cur["c"] = c[i]
    flush(cur)
    return ends, ro, rh, rl, rc


def map_htf(t, base_ms, ends, values):
    """Para cada vela base, el valor de la ultima vela HTF ya CERRADA en ese momento (sin mirar al futuro)."""
    out = [0] * len(t)
    j = -1
    for i in range(len(t)):
        close_t = t[i] + base_ms
        while j + 1 < len(ends) and ends[j + 1] <= close_t:
            j += 1
        out[i] = values[j] if j >= 0 else 0
    return out


def prev_levels(t, h, l, key_fn, start_fn):
    """Maximo/minimo del bloque temporal ANTERIOR (solo si el bloque anterior esta completo desde su inicio)."""
    n = len(t)
    pH, pL = [None] * n, [None] * n
    cur_key, cH, cL, started, prev = None, None, None, False, None
    for i in range(n):
        k = key_fn(t[i])
        if k != cur_key:
            if cur_key is not None:
                prev = (cH, cL) if started else None
            cur_key, cH, cL = k, h[i], l[i]
            started = t[i] == start_fn(k)
        else:
            cH = max(cH, h[i])
            cL = min(cL, l[i])
        if prev:
            pH[i], pL[i] = prev
    return pH, pL
