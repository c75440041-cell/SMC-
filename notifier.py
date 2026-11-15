"""Envio de mensajes a Telegram."""
import html


class Telegram:
    def __init__(self, session, cfg):
        self.s = session
        self.token = cfg.TELEGRAM_BOT_TOKEN
        self.chat = cfg.TELEGRAM_CHAT_ID

    async def send(self, text):
        if not self.token or not self.chat:
            print("[telegram no configurado] " + html.unescape(text), flush=True)
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat, "text": text, "parse_mode": "HTML",
                   "disable_web_page_preview": True}
        try:
            async with self.s.post(url, json=payload) as r:
                body = await r.json(content_type=None)
            if not body.get("ok"):
                print(f"[telegram] error: {body}", flush=True)
                return False
            return True
        except Exception as e:
            print(f"[telegram] excepcion: {e!r}", flush=True)
            return False
