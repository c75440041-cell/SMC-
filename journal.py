"""Diario de senales con seguimiento de resultados (SQLite) + estadisticas.
Guarda TODAS las senales (tambien las que no pasan las puertas = modo sombra) para medir cada filtro con datos reales."""
import json
import math
import os
import sqlite3

SCHEMA = """CREATE TABLE IF NOT EXISTS signals(
 id TEXT PRIMARY KEY, symbol TEXT, grp TEXT, setup TEXT, side TEXT, t INTEGER,
 entry REAL, sl REAL, tp1 REAL, tp2 REAL, tp3 REAL, liq_tp REAL, score REAL,
 passed INTEGER, sent INTEGER DEFAULT 0, flags TEXT,
 status TEXT DEFAULT 'open', hit1 INTEGER DEFAULT 0, hit2 INTEGER DEFAULT 0, hit3 INTEGER DEFAULT 0,
 stopped INTEGER DEFAULT 0, exp_r REAL, bars INTEGER DEFAULT 0, last_t INTEGER)"""


def new_state():
    return {"hit1": 0, "hit2": 0, "hit3": 0, "stopped": 0, "bars": 0, "status": "open", "exp_r": None}


def advance(st, side, entry, sl, tps, candle, max_bars):
    """Avanza el seguimiento con una vela cerrada. Si la vela toca SL y TP a la vez, se asume SL primero (conservador).
    Cada TPk se cuenta 'alcanzado' solo si llega antes que el SL inicial (sin break-even)."""
    if st["status"] == "closed":
        return
    _, _, h, l, c, _ = candle
    st["bars"] += 1
    long_ = side == "LONG"
    if (l <= sl) if long_ else (h >= sl):
        st["stopped"], st["status"] = 1, "closed"
        return
    for k, tp in enumerate(tps, 1):
        if (h >= tp) if long_ else (l <= tp):
            st["hit%d" % k] = 1
    if st["hit3"]:
        st["status"] = "closed"
        return
    if st["bars"] >= max_bars:
        risk = abs(entry - sl)
        st["exp_r"] = ((c - entry) if long_ else (entry - c)) / risk
        st["status"] = "closed"


def outcomes(r, cost_pct=0.0):
    """Resultado en R si se usara cada TP como unico objetivo, NETO de costes (cost_pct = % ida y vuelta).
    None si la senal sigue abierta."""
    if r["status"] != "closed":
        return None
    risk = abs(r["entry"] - r["sl"])
    cost_r = (cost_pct / (risk / r["entry"] * 100)) if cost_pct else 0.0
    out = []
    for k in (1, 2, 3):
        rk = abs(r["tp%d" % k] - r["entry"]) / risk
        if r["hit%d" % k]:
            v = rk
        elif r["stopped"]:
            v = -1.0
        else:
            v = r["exp_r"] if r["exp_r"] is not None else 0.0
        out.append(v - cost_r)
    return out


def summarize(rows, cost_pct=0.0):
    res = []
    for r in rows:
        o = outcomes(r, cost_pct)
        if o is not None:
            res.append((r, o))
    n = len(res)
    if n == 0:
        return {"n": 0}
    s = {"n": n}
    for k in (1, 2, 3):
        vals = [o[k - 1] for _, o in res]
        m = sum(vals) / n
        var = sum((v - m) ** 2 for v in vals) / (n - 1) if n > 1 else 0.0
        s["p%d" % k] = sum(r["hit%d" % k] for r, _ in res) / n
        s["e%d" % k] = m
        s["se%d" % k] = math.sqrt(var / n)
    return s


def _fe(v):
    return f"{v:+.2f}"


def _line(label, s):
    if s["n"] == 0:
        return f"{label}: sin datos"
    return (f"{label}: n={s['n']} · TP1 {s['p1']*100:.0f}% TP2 {s['p2']*100:.0f}% TP3 {s['p3']*100:.0f}% · "
            f"E1 {_fe(s['e1'])} E2 {_fe(s['e2'])}±{s['se2']:.2f} E3 {_fe(s['e3'])}")


def suggestions(rows, cost_pct, min_group=30, z_min=3.0):
    """Conclusiones SOLO si son estadisticamente solidas (z>=3 por la cantidad de comparaciones)."""
    out = []
    for g in sorted({r["setup"] for r in rows}):
        s = summarize([r for r in rows if r["setup"] == g and r["passed"]], cost_pct)
        if s["n"] >= 50:
            if s["e2"] + 1.96 * s["se2"] < 0:
                out.append(f"⛔ {g}: E2 neto {_fe(s['e2'])}±{s['se2']:.2f} (n={s['n']}) → quítalo de SEND_SETUPS")
            elif s["e2"] - 1.96 * s["se2"] > 0:
                out.append(f"✅ {g}: ventaja significativa, E2 neto {_fe(s['e2'])}±{s['se2']:.2f} (n={s['n']})")
    for k in sorted({k for r in rows for k in r["flags"]}):
        y = summarize([r for r in rows if r["flags"].get(k)], cost_pct)
        n_ = summarize([r for r in rows if not r["flags"].get(k)], cost_pct)
        if y["n"] >= min_group and n_["n"] >= min_group:
            se = math.sqrt(y["se2"] ** 2 + n_["se2"] ** 2)
            z = (y["e2"] - n_["e2"]) / se if se > 0 else 0.0
            if abs(z) >= z_min:
                diff = y["e2"] - n_["e2"]
                out.append(f"{'✅' if diff > 0 else '⛔'} {k}: {_fe(diff)}R de diferencia (z={z:.1f}) → "
                           + ("ponlo en GATES" if diff > 0 else "evítalo / no lo pongas en GATES"))
    return out


def report_text(rows, days, gates, cost_pct=0.0):
    closed = [r for r in rows if r["status"] == "closed"]
    if not closed:
        return "📊 <b>Informe</b>: todavía no hay señales resueltas."
    lines = [f"📊 <b>Informe {days}d</b> · {len(closed)} resueltas · {len(rows) - len(closed)} abiertas",
             f"<i>E = expectativa en R usando ese TP como único objetivo (SL inicial, sin break-even), "
             f"neta de costes ({cost_pct:.2f}% ida y vuelta). ± = error estándar.</i>", ""]
    lines.append("<b>Por setup (solo las que pasan las puertas)</b>")
    for g in sorted({r["setup"] for r in rows}):
        lines.append(_line(g, summarize([r for r in rows if r["setup"] == g and r["passed"]], cost_pct)))
    lines.append("")
    lines.append(f"<b>Puertas activas: {', '.join(gates) or 'ninguna'}</b>")
    lines.append(_line("Pasan", summarize([r for r in rows if r["passed"]], cost_pct)))
    lines.append(_line("No pasan", summarize([r for r in rows if not r["passed"]], cost_pct)))
    lines.append("")
    lines.append("<b>Cada flag (todas las señales, E2 neto)</b>")
    flag_rows = []
    for k in sorted({k for r in rows for k in r["flags"]}):
        yes = summarize([r for r in rows if r["flags"].get(k)], cost_pct)
        no = summarize([r for r in rows if not r["flags"].get(k)], cost_pct)
        if yes["n"] >= 5 and no["n"] >= 5:
            flag_rows.append((yes["e2"] - no["e2"], k, yes, no))
    for diff, k, yes, no in sorted(flag_rows, reverse=True):
        lines.append(f"{k}: Sí n={yes['n']} {_fe(yes['e2'])} | No n={no['n']} {_fe(no['e2'])}")
    lines.append("")
    sug = suggestions(rows, cost_pct)
    lines.append("<b>Conclusiones sólidas</b>")
    lines += sug if sug else ["Ninguna todavía: con pocas señales las diferencias son ruido (normal)."]
    if len(closed) < 100:
        lines.append("⚠️ Menos de 100 señales resueltas: aún no es concluyente.")
    return "\n".join(lines)[:3900]


class Journal:
    def __init__(self, path):
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            self.db = sqlite3.connect(path)
            self.path = path
        except Exception as e:
            print(f"[diario] no puedo abrir {path}: {e!r}; uso memoria (se pierde al reiniciar)", flush=True)
            self.db = sqlite3.connect(":memory:")
            self.path = ":memory:"
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_status ON signals(status)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ix_t ON signals(t)")
        self.db.commit()

    def add(self, s):
        sid = f"{s['symbol']}|{s['setup']}|{s['side']}|{s['time']}"
        s["id"] = sid
        cur = self.db.execute(
            "INSERT OR IGNORE INTO signals(id,symbol,grp,setup,side,t,entry,sl,tp1,tp2,tp3,liq_tp,score,passed,flags,last_t)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, s["symbol"], s["group"], s["setup"], s["side"], s["time"], s["entry"], s["sl"], s["tp1"], s["tp2"],
             s["tp3"], s["liq_tp"], s["score"], int(s["passed"]), json.dumps(s["flags"]), s["time"]))
        return cur.rowcount == 1

    def mark_sent(self, ids):
        self.db.executemany("UPDATE signals SET sent=1 WHERE id=?", [(i,) for i in ids])

    def open_map(self):
        out = {}
        for r in self.db.execute("SELECT * FROM signals WHERE status='open'"):
            out.setdefault(r["symbol"], []).append(dict(r))
        return out

    def resolve_symbol(self, rows, candles, max_bars):
        for r in rows:
            st = {k: r[k] for k in ("hit1", "hit2", "hit3", "stopped", "bars", "status", "exp_r")}
            before = st["bars"]
            last_t = r["last_t"] or r["t"]
            tps = (r["tp1"], r["tp2"], r["tp3"])
            for cd in candles:
                if cd[0] <= last_t:
                    continue
                advance(st, r["side"], r["entry"], r["sl"], tps, cd, max_bars)
                last_t = cd[0]
                if st["status"] == "closed":
                    break
            if st["bars"] != before:
                self.db.execute(
                    "UPDATE signals SET hit1=?,hit2=?,hit3=?,stopped=?,bars=?,status=?,exp_r=?,last_t=? WHERE id=?",
                    (st["hit1"], st["hit2"], st["hit3"], st["stopped"], st["bars"], st["status"], st["exp_r"], last_t, r["id"]))

    def expire_stale(self, now_ms, tf_ms, max_bars):
        """Cierra senales abiertas sin datos nuevos (p. ej. la moneda salio del universo)."""
        self.db.execute("UPDATE signals SET status='closed', exp_r=0.0 WHERE status='open' AND t < ?",
                        (now_ms - (max_bars + 30) * tf_ms,))

    def rows_since(self, ts_ms):
        out = []
        for r in self.db.execute("SELECT * FROM signals WHERE t >= ?", (ts_ms,)):
            d = dict(r)
            d["flags"] = json.loads(d["flags"] or "{}")
            out.append(d)
        return out

    def prune(self, keep_days, now_ms):
        self.db.execute("DELETE FROM signals WHERE t < ?", (now_ms - keep_days * 86_400_000,))

    def counts(self):
        a = self.db.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        b = self.db.execute("SELECT COUNT(*) FROM signals WHERE status='open'").fetchone()[0]
        return a, b

    def commit(self):
        self.db.commit()
