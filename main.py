"""SMC Notebook Bot v2: escanea los perpetuos USDT de BingX, puntua los setups y envia el TOP N a Telegram.
Guarda todas las senales en un diario con seguimiento de resultados y envia un informe diario.
Uso: python main.py   (todos los archivos juntos en la raiz, sin carpetas)"""
import asyncio
import html
import os
import time
import traceback
from datetime import datetime, timezone

import aiohttp

import config as cfg
from bingx import BingX
from indicators import TF_MS
from journal import Journal, report_text
from notifier import Telegram
from strategy import FLAG_LABELS, KNOWN_FLAGS, analyze, regime


def fmt(p):
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    if p >= 0.01:
        return f"{p:.5f}"
    return f"{p:.8f}"


def log(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def arrow(v):
    return "▲" if v == 1 else "▼" if v == -1 else "–"


def build_message(picks, total, scanned, market):
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    head = f"🏆 <b>TOP {len(picks)} · {html.escape(cfg.TIMEFRAME)}</b>  ({total} señales · {scanned} monedas · {now})"
    if market:
        head += f"\nBTC: 5m {arrow(market['t5'])} 15m {arrow(market['t15'])} 1h {arrow(market['t1h'])}"
    lines = [head, ""]
    for n, s in enumerate(picks, 1):
        icon = "🟢" if s["side"] == "LONG" else "🔴"
        lines.append(f"{n}) {icon} <b>{s['side']} {html.escape(s['symbol'])}</b> · {html.escape(s['setup'])} · ⭐ {s['score']:.0f}/100")
        lines.append(f"   Entrada <code>{fmt(s['entry'])}</code> · SL <code>{fmt(s['sl'])}</code> ({s['risk_pct']:.2f}%)")
        lines.append(f"   TP1 <code>{fmt(s['tp1'])}</code> · TP2 <code>{fmt(s['tp2'])}</code> · TP3 <code>{fmt(s['tp3'])}</code>")
        if s["liq_tp"]:
            lines.append(f"   Liquidez <code>{fmt(s['liq_tp'])}</code> (R:R {s['rr_liq']:.1f})")
        d = 1 if s["side"] == "LONG" else -1
        limit_px = s["entry"] + d * cfg.MAX_CHASE_R * abs(s["entry"] - s["sl"])
        lines.append(f"   Válida {'hasta' if d == 1 else 'desde'} <code>{fmt(limit_px)}</code> · costes ≈ {s['cost_r']:.2f}R")
        size = position_size(s)
        if size:
            lines.append("   " + size)
        on = [lab for key, lab in FLAG_LABELS if s["flags"].get(key)]
        lines.append("   " + (" ".join("✅" + x for x in on) if on else "—"))
        lines.append("")
    lines.append("Plan: en TP1 cierra parte y mueve el SL a break-even.")
    lines.append("⚠️ Solo señales, no es consejo financiero.")
    return "\n".join(lines)


def position_size(s):
    """Tamano de posicion para arriesgar RISK_PCT% de la cuenta (solo si ACCOUNT_USDT > 0)."""
    if cfg.ACCOUNT_USDT <= 0:
        return ""
    risk_amt = cfg.ACCOUNT_USDT * cfg.RISK_PCT / 100
    notional = risk_amt / (s["risk_pct"] / 100)
    cap = cfg.ACCOUNT_USDT * cfg.MAX_LEVERAGE
    note = ""
    if notional > cap:
        notional, risk_amt, note = cap, cap * s["risk_pct"] / 100, " (limitado por MAX_LEVERAGE)"
    return f"Tamaño: {notional:,.0f} USDT · riesgo {risk_amt:.2f} USDT · x{notional / cfg.ACCOUNT_USDT:.1f}{note}"


def pick_top(eligible):
    """Mejor senal por moneda, ordenadas por puntuacion, con tope de longs/shorts (diversificacion)."""
    best = {}
    for s in eligible:
        if s["symbol"] not in best or s["score"] > best[s["symbol"]]["score"]:
            best[s["symbol"]] = s
    out, count = [], {"LONG": 0, "SHORT": 0}
    for s in sorted(best.values(), key=lambda z: z["score"], reverse=True):
        if count[s["side"]] >= cfg.MAX_SAME_DIR:
            continue
        count[s["side"]] += 1
        out.append(s)
        if len(out) >= cfg.TOP_N:
            break
    return out


async def load_universe(api):
    last = None
    for _ in range(5):
        try:
            uni = await api.universe()
            if cfg.INCLUDE_SYMBOLS:
                uni = [u for u in uni if u[0] in cfg.INCLUDE_SYMBOLS]
            uni = [u for u in uni if u[1] > 0 and u[1] >= cfg.MIN_VOLUME_USDT and u[0] not in cfg.EXCLUDE_SYMBOLS]
            if cfg.MAX_SYMBOLS > 0:
                uni = uni[:cfg.MAX_SYMBOLS]
            if uni:
                return uni
            last = "universo vacio"
        except Exception as e:
            last = repr(e)
        await asyncio.sleep(5)
    raise SystemExit(f"No se pudo cargar el universo: {last}")


async def get_market(api):
    try:
        candles = await api.klines("BTC-USDT")
        return await asyncio.to_thread(regime, candles, cfg)
    except Exception as e:
        log(f"Sin regimen BTC: {e!r}")
        return None


async def scan(api, journal, universe, market):
    sem = asyncio.Semaphore(12)
    errors = 0
    open_map = journal.open_map()

    async def one(sym, qv):
        nonlocal errors
        async with sem:
            try:
                candles = await api.klines(sym)
            except Exception:
                errors += 1
                return []
        try:
            if sym in open_map:
                journal.resolve_symbol(open_map[sym], candles, cfg.JOURNAL_MAX_BARS)
            sigs = await asyncio.to_thread(analyze, candles, cfg, qv, market, None, sym == "BTC-USDT")
        except Exception as e:
            errors += 1
            log(f"Error analizando {sym}: {e!r}")
            return []
        price = getattr(api, "last_price", {}).get(sym)
        for s in sigs:
            s["symbol"] = sym
            risk = abs(s["entry"] - s["sl"])
            d = 1 if s["side"] == "LONG" else -1
            s["drift_r"] = d * (price - s["entry"]) / risk if price and risk else 0.0   # cuanto se ha movido ya a favor
        return sigs

    results = await asyncio.gather(*(one(s, q) for s, q in universe), return_exceptions=True)
    allsig = [s for r in results if isinstance(r, list) for s in r]
    new = [s for s in allsig if journal.add(s)]
    eligible = [s for s in new if s["passed"] and s["group"].lower() in cfg.SEND_SETUPS and s["score"] >= cfg.MIN_SCORE]
    stale = [s for s in eligible if s["drift_r"] > cfg.MAX_CHASE_R]     # la entrada ya paso: no se envia (queda en el diario)
    eligible = [s for s in eligible if s["drift_r"] <= cfg.MAX_CHASE_R]
    picks = pick_top(eligible)
    journal.mark_sent([s["id"] for s in picks])
    journal.expire_stale(int(time.time() * 1000), TF_MS.get(cfg.TIMEFRAME, 300_000), cfg.JOURNAL_MAX_BARS)
    journal.commit()
    return picks, len(eligible), len(new), errors, len(stale)


def daily_report(journal):
    since = int((time.time() - cfg.REPORT_DAYS * 86400) * 1000)
    return report_text(journal.rows_since(since), cfg.REPORT_DAYS, cfg.GATES, cfg.COST_PCT)


async def run():
    bad = [g for g in cfg.GATES if g not in KNOWN_FLAGS]
    if bad:
        log(f"AVISO: puertas desconocidas ignoradas: {bad}")
        cfg.GATES = [g for g in cfg.GATES if g in KNOWN_FLAGS]
    if len(cfg.GATES) > 3:
        log("AVISO: mas de 3 puertas activas = muy pocas senales. Mejor usa menos y deja el resto como puntuacion.")
    journal = Journal(cfg.JOURNAL_PATH)
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        api, tg = BingX(session, cfg), Telegram(session, cfg)
        universe = await load_universe(api)
        uni_t = time.time()
        total_j, open_j = journal.counts()
        log(f"Universo: {len(universe)} monedas | diario: {total_j} señales ({open_j} abiertas) en {journal.path}")
        persist = ""
        if journal.path == ":memory:":
            persist = "\n⚠️ Diario en memoria: se pierde al reiniciar."
        elif os.getenv("RAILWAY_ENVIRONMENT_NAME") and not os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
            persist = "\n⚠️ Sin Volume en Railway: el diario se borrará en cada despliegue."
        elif os.getenv("RAILWAY_VOLUME_MOUNT_PATH"):
            persist = "\n💾 Diario persistente (Volume)."
        await tg.send(
            f"✅ <b>SMC Bot iniciado</b>\n{len(universe)} perpetuos USDT analizados "
            f"({sum(1 for _, q in universe if q >= cfg.MIN_LIQ_USDT)} con liquidez suficiente para enviar) · "
            f"{html.escape(cfg.TIMEFRAME)} · TOP {cfg.TOP_N}\n"
            f"Setups: {', '.join(cfg.SETUPS)} · Puertas: {', '.join(cfg.GATES) or 'ninguna'}\n"
            f"Diario: {total_j} señales previas{persist}")
        tf = api.tf_sec
        last_beat, last_report_day, fails, last_alert = time.time(), None, 0, 0.0

        while True:
            try:
                t0 = time.time()
                if t0 - uni_t > cfg.UNIVERSE_REFRESH_MIN * 60:
                    try:
                        universe, uni_t = await load_universe(api), time.time()
                    except SystemExit:
                        log("No se pudo refrescar el universo; sigo con el anterior")
                market = await get_market(api)
                picks, n_elig, n_new, errors, n_stale = await scan(api, journal, universe, market)
                log(f"Scan {time.time() - t0:.1f}s | nuevas {n_new} | elegibles {n_elig} | caducadas {n_stale} | enviadas {len(picks)} | errores {errors}")
                if picks:
                    await tg.send(build_message(picks, n_elig, len(universe), market))
                now = datetime.now(timezone.utc)
                if now.hour == cfg.REPORT_HOUR_UTC and last_report_day != now.date():
                    last_report_day = now.date()
                    await tg.send(daily_report(journal))
                    journal.prune(cfg.JOURNAL_KEEP_DAYS, int(time.time() * 1000))
                    journal.commit()
                if cfg.HEARTBEAT_HOURS > 0 and time.time() - last_beat > cfg.HEARTBEAT_HOURS * 3600:
                    a, b = journal.counts()
                    await tg.send(f"💓 Bot activo · {len(universe)} monedas · diario {a} señales ({b} abiertas)")
                    last_beat = time.time()
                fails = 0
            except SystemExit:
                raise
            except Exception as e:
                fails += 1
                log(f"ERROR en el bucle ({fails}): {e!r}\n{traceback.format_exc()}")
                if time.time() - last_alert > 600:
                    last_alert = time.time()
                    await tg.send(f"⚠️ Error en el bot ({fails}): <code>{html.escape(repr(e))[:300]}</code>")
                if fails >= 8:
                    raise SystemExit("Demasiados errores seguidos; Railway reiniciara el servicio")
                await asyncio.sleep(15)
                continue
            now = time.time()
            nxt = (now // tf + 1) * tf + cfg.SCAN_DELAY_SEC
            await asyncio.sleep(max(1, nxt - now))


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
