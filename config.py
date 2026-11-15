"""Configuracion desde variables de entorno (Railway -> Variables)."""
import os


def _s(name, default=""):
    return os.getenv(name, default).strip()


def _i(name, default):
    try:
        return int(float(_s(name, str(default)) or default))
    except ValueError:
        return default


def _f(name, default):
    try:
        return float(_s(name, str(default)) or default)
    except ValueError:
        return default


def _b(name, default):
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on", "si", "sí")


def _list(name):
    return [x.strip().upper() for x in _s(name).split(",") if x.strip()]


TELEGRAM_BOT_TOKEN = _s("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _s("TELEGRAM_CHAT_ID")

TIMEFRAME = _s("TIMEFRAME", "5m")
TOP_N = _i("TOP_N", 5)                       # cuantas senales (las mejores) se envian en cada scan
MIN_SCORE = _f("MIN_SCORE", 0)               # puntuacion minima (0-100) para enviar

# Universo
MIN_VOLUME_USDT = _f("MIN_VOLUME_USDT", 1_000_000)
MAX_SYMBOLS = _i("MAX_SYMBOLS", 0)           # 0 = sin limite
INCLUDE_SYMBOLS = _list("INCLUDE_SYMBOLS")
EXCLUDE_SYMBOLS = _list("EXCLUDE_SYMBOLS")
REQ_PER_SEC = _f("REQ_PER_SEC", 8)
SCAN_DELAY_SEC = _f("SCAN_DELAY_SEC", 4)
CANDLES = _i("WARMUP_BARS", 300)
UNIVERSE_REFRESH_MIN = _i("UNIVERSE_REFRESH_MIN", 60)
HEARTBEAT_HOURS = _f("HEARTBEAT_HOURS", 6)   # mensaje "sigo vivo" (0 = desactivado)
SIGNAL_MAX_AGE = _i("SIGNAL_MAX_AGE", 1)     # velas de antiguedad maxima de una senal

# Estrategia (igual al Pine)
SWING_LEN = _i("SWING_LEN", 5)
ENTRY_MODE = _s("ENTRY_MODE", "Retest OB")           # Retest OB | Mitad del OB
OB_MITIGATION = _s("OB_MITIGATION", "Close through") # Close through | Wick through
COOLDOWN_BARS = _i("COOLDOWN_BARS", 8)
SL_BUFFER_ATR = _f("SL_BUFFER_ATR", 0.1)
RR_TARGET = _f("RR_TARGET", 2.5)
USE_LIQUIDITY_TP = _b("USE_LIQUIDITY_TP", True)

# Filtros extra
MIN_RR = _f("MIN_RR", 1.5)
MAX_RISK_PCT = _f("MAX_RISK_PCT", 3.0)
REQUIRE_SWEEP = _b("REQUIRE_SWEEP", False)
SWEEP_LOOKBACK = _i("SWEEP_LOOKBACK", 30)
OB_MIN_AGE = _i("OB_MIN_AGE", 1)
