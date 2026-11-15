"""SMC Notebook Bot: escanea los perpetuos USDT de BingX y envia a Telegram el TOP N de senales.
Uso: python main.py   (todos los archivos juntos en la raiz, sin carpetas)"""
import asyncio
import html
import time
from datetime import datetime, timezone

import aiohttp

import config as cfg
from bingx import BingX
from notifier import Telegram
from strategy import analyze


def fmt(p):
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    if p >= 0.01:
        return f"{p:.5f}"
    return f"{p:.8f}"


def log(msg):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def build_message(top, total, scanned):
    now = datetime.now(timezone.utc).strftime("%H:%M UTC")
    lines = [f"🏆 <b>TOP {len(top)} SMC · {html.escape(cfg.TIMEFRAME)}</b>  ({total} señales de {scanned} monedas · {now})", ""]
    for n, s in enumerate(top, 1):
        icon = "🟢" if s["side"] == "LONG" else "🔴"
        sym = html.escape(s["symbol"])
        lines.append(f"{n}) {icon} <b>{s['side']} {sym}</b>  ⭐ {s['score']:.0f}/100")
        lines.append(f"   Entrada: <code>{fmt(s['entry'])}</code>")
        lines.append(f"   SL: <code>{fmt(s['sl'])}</code> ({s['risk_pct']:.2f}%)")
        lines.append(f"   TP: <code>{fmt(s['tp'])}</code>  ·  R:R {s['rr']:.1f}")
        lines.append(f"   Barrida {'✅' if s['swept'] else '—'} · Volumen x{s['vol_ratio']:.1f}")
        lines.append("")
    lines.append("⚠️ Solo señales, no es consejo financiero.")
    return "\n".join(lines)


async def load_universe(api):
    last = None
    for _ in range(5):
        try:
            uni = await api.universe()
            if cfg.INCLUDE_SYMBOLS:
                uni = [u for u in uni if u[0] in cfg.INCLUDE_SYMBOLS]
            uni = [u for u in uni if u[1] >= cfg.MIN_VOLUME_USDT and u[0] not in cfg.EXCLUDE_SYMBOLS]
            if cfg.MAX_SYMBOLS > 0:
                uni = uni[:cfg.MAX_SYMBOLS]
            if uni:
                return uni
            last = "universo vacio"
        except Exception as e:
            last = repr(e)
        await asyncio.sleep(5)
    raise SystemExit(f"No se pudo cargar el universo: {last}")


async def scan(api, universe, sent):
    sem = asyncio.Semaphore(12)
    errors = 0

    async def one(sym, qv):
        nonlocal errors
        async with sem:
            try:
                candles = await api.klines(sym)
            except Exception:
                errors += 1
                return None
        sigs = await asyncio.to_thread(analyze, candles, cfg, qv)
        if not sigs:
            return None
        best = max(sigs, key=lambda s: (s["bar"], s["score"]))
        best["symbol"] = sym
        return best

    results = await asyncio.gather(*(one(s, q) for s, q in universe))
    found = [r for r in results if r]
    fresh = []
    for s in found:
        key = (s["symbol"], s["side"], s["time"])
        if key in sent:
            continue
        sent.add(key)
        if s["score"] >= cfg.MIN_SCORE:
            fresh.append(s)
    fresh.sort(key=lambda s: s["score"], reverse=True)
    if len(sent) > 5000:
        sent.clear()
    return fresh, len(found), errors


async def run():
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        api, tg = BingX(session, cfg), Telegram(session, cfg)
        universe = await load_universe(api)
        uni_t = time.time()
        log(f"Universo: {len(universe)} monedas")
        await tg.send(f"✅ <b>SMC Bot iniciado</b>\n{len(universe)} perpetuos USDT de BingX · {html.escape(cfg.TIMEFRAME)} · TOP {cfg.TOP_N} por vela")
        sent, last_beat = set(), time.time()
        tf = api.tf_sec

        while True:
            t0 = time.time()
            if t0 - uni_t > cfg.UNIVERSE_REFRESH_MIN * 60:
                try:
                    universe, uni_t = await load_universe(api), time.time()
                except SystemExit:
                    log("No se pudo refrescar el universo; sigo con el anterior")
            fresh, total, errors = await scan(api, universe, sent)
            log(f"Scan {time.time() - t0:.1f}s | senales nuevas: {len(fresh)} | errores: {errors}")
            if fresh:
                await tg.send(build_message(fresh[:cfg.TOP_N], len(fresh), len(universe)))
            if cfg.HEARTBEAT_HOURS > 0 and time.time() - last_beat > cfg.HEARTBEAT_HOURS * 3600:
                await tg.send(f"💓 Bot activo · {len(universe)} monedas vigiladas · sin señales nuevas en este momento"
                              if not fresh else "💓 Bot activo")
                last_beat = time.time()
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
