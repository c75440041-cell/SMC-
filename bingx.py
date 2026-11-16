"""Cliente minimo de la API publica de BingX (futuros perpetuos USDT)."""
import asyncio
import time

BASE = "https://open-api.bingx.com"
TF_SEC = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400}


class RateLimiter:
    def __init__(self, per_sec):
        self.gap = 1.0 / max(per_sec, 0.1)
        self.lock = asyncio.Lock()
        self.next = 0.0
        self.block_until = 0.0

    def block(self, seconds):
        self.block_until = max(self.block_until, time.monotonic() + seconds)

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            target = max(self.next, self.block_until, now)
            if target > now:
                await asyncio.sleep(target - now)
            self.next = target + self.gap


class BingX:
    def __init__(self, session, cfg):
        self.s = session
        self.cfg = cfg
        self.rl = RateLimiter(cfg.REQ_PER_SEC)
        self.tf_sec = TF_SEC.get(cfg.TIMEFRAME, 300)
        self.last_price = {}   # precio actual (vela en formacion) por simbolo, para detectar entradas ya pasadas

    async def _get(self, path, params=None, tries=3):
        last = None
        for k in range(tries):
            await self.rl.wait()
            try:
                async with self.s.get(BASE + path, params=params) as r:
                    status = r.status
                    data = await r.json(content_type=None)
                if status == 429 or (isinstance(data, dict) and data.get("code") in (100410, "100410")):
                    self.rl.block(3.0 * (k + 1))
                    last = "limite de tasa (429)"
                    continue
                if isinstance(data, dict) and data.get("code") in (0, "0", None):
                    return data.get("data")
                last = f"code={data.get('code')} msg={data.get('msg')}"
            except Exception as e:
                last = repr(e)
            await asyncio.sleep(1.0 * (k + 1))
        raise RuntimeError(f"{path} fallo: {last}")

    async def universe(self):
        """[(symbol, quoteVolume24h)] de perpetuos USDT activos, ordenados por volumen."""
        tickers = await self._get("/openApi/swap/v2/quote/ticker")
        active = None
        try:
            contracts = await self._get("/openApi/swap/v2/quote/contracts")
            active = {x["symbol"] for x in contracts if str(x.get("status", 1)) == "1"}
        except Exception:
            pass
        out = []
        for x in tickers or []:
            sym = x.get("symbol", "")
            if not sym.endswith("-USDT") or (active is not None and sym not in active):
                continue
            try:
                qv = float(x.get("quoteVolume") or 0)
            except ValueError:
                qv = 0.0
            out.append((sym, qv))
        out.sort(key=lambda z: z[1], reverse=True)
        return out

    @staticmethod
    def _parse(data):
        rows = []
        for k in data or []:
            try:
                if isinstance(k, dict):
                    rows.append((int(k["time"]), float(k["open"]), float(k["high"]), float(k["low"]),
                                 float(k["close"]), float(k["volume"])))
                else:
                    rows.append((int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
            except (KeyError, ValueError, IndexError, TypeError):
                continue
        return rows

    async def _klines_raw(self, params):
        try:
            data = await self._get("/openApi/swap/v3/quote/klines", params)
        except RuntimeError:
            data = await self._get("/openApi/swap/v2/quote/klines", params)
        return self._parse(data)

    def _closed(self, rows):
        now_ms = int(time.time() * 1000)
        by_t = {r[0]: r for r in rows}
        return [by_t[t] for t in sorted(by_t) if t + self.tf_sec * 1000 <= now_ms + 1000]

    async def klines(self, symbol):
        """Velas CERRADAS ascendentes: [(t,o,h,l,c,v)]"""
        rows = await self._klines_raw({"symbol": symbol, "interval": self.cfg.TIMEFRAME, "limit": self.cfg.CANDLES})
        if rows:
            self.last_price[symbol] = max(rows)[4]
        return self._closed(rows)

    async def history(self, symbol, bars):
        """Historico paginado hacia atras (para el backtest)."""
        got = {}
        end = None
        while len(got) < bars:
            params = {"symbol": symbol, "interval": self.cfg.TIMEFRAME, "limit": 1440}
            if end:
                params["endTime"] = end
            rows = await self._klines_raw(params)
            new = 0
            for r in rows:
                if r[0] not in got:
                    got[r[0]] = r
                    new += 1
            if not rows or new == 0:
                break
            end = min(got) - 1
        return self._closed(list(got.values()))[-bars:]
