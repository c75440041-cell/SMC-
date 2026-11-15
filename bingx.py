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

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            if self.next > now:
                await asyncio.sleep(self.next - now)
            self.next = max(now, self.next) + self.gap


class BingX:
    def __init__(self, session, cfg):
        self.s = session
        self.cfg = cfg
        self.rl = RateLimiter(cfg.REQ_PER_SEC)
        self.tf_sec = TF_SEC.get(cfg.TIMEFRAME, 300)

    async def _get(self, path, params=None, tries=3):
        last = None
        for k in range(tries):
            await self.rl.wait()
            try:
                async with self.s.get(BASE + path, params=params) as r:
                    data = await r.json(content_type=None)
                if isinstance(data, dict) and data.get("code") in (0, "0", None):
                    return data.get("data")
                last = f"code={data.get('code')} msg={data.get('msg')}"
            except Exception as e:  # red / json
                last = repr(e)
            await asyncio.sleep(1.5 * (k + 1))
        raise RuntimeError(f"{path} fallo: {last}")

    async def universe(self):
        """Devuelve [(symbol, quoteVolume24h)] de perpetuos USDT activos, ordenados por volumen."""
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
            if not sym.endswith("-USDT"):
                continue
            if active is not None and sym not in active:
                continue
            try:
                qv = float(x.get("quoteVolume") or 0)
            except ValueError:
                qv = 0.0
            out.append((sym, qv))
        out.sort(key=lambda z: z[1], reverse=True)
        return out

    async def klines(self, symbol):
        """Velas CERRADAS, ascendentes: [{t,o,h,l,c,v}]"""
        params = {"symbol": symbol, "interval": self.cfg.TIMEFRAME, "limit": self.cfg.CANDLES}
        try:
            data = await self._get("/openApi/swap/v3/quote/klines", params)
        except RuntimeError:
            data = await self._get("/openApi/swap/v2/quote/klines", params)
        rows = []
        for k in data or []:
            try:
                if isinstance(k, dict):
                    rows.append({"t": int(k["time"]), "o": float(k["open"]), "h": float(k["high"]),
                                 "l": float(k["low"]), "c": float(k["close"]), "v": float(k["volume"])})
                else:
                    rows.append({"t": int(k[0]), "o": float(k[1]), "h": float(k[2]),
                                 "l": float(k[3]), "c": float(k[4]), "v": float(k[5])})
            except (KeyError, ValueError, IndexError):
                continue
        rows.sort(key=lambda r: r["t"])
        now_ms = int(time.time() * 1000)
        return [r for r in rows if r["t"] + self.tf_sec * 1000 <= now_ms + 1000]
