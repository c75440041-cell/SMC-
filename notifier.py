"""Envio de mensajes a Telegram (con reintentos y division de mensajes largos)."""
import asyncio
import html


def _chunks(text, limit=3900):
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > limit and cur:
            parts.append(cur)
            cur = ""
        cur += (("\n\n" if cur else "") + block)
    if cur:
        parts.append(cur)
    return parts


class Telegram:
    def __init__(self, session, cfg):
        self.s = session
        self.token = cfg.TELEGRAM_BOT_TOKEN
        self.chat = cfg.TELEGRAM_CHAT_ID

    async def send(self, text):
        if not self.token or not self.chat:
            print("[telegram no configurado] " + html.unescape(text), flush=True)
            return False
        ok = True
        for part in _chunks(text):
            ok = await self._send_one(part) and ok
        return ok

    async def _send_one(self, text):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        for attempt in range(3):
            try:
                async with self.s.post(url, json=payload) as r:
                    body = await r.json(content_type=None)
                if body.get("ok"):
                    return True
                wait = (body.get("parameters") or {}).get("retry_after")
                print(f"[telegram] error: {body}", flush=True)
                if wait:
                    await asyncio.sleep(min(int(wait) + 1, 30))
                    continue
                return False
            except Exception as e:
                print(f"[telegram] excepcion: {e!r}", flush=True)
                await asyncio.sleep(2 * (attempt + 1))
        return False
