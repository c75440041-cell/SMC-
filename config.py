"""Configuracion desde variables de entorno (Railway -> Variables). Todo tiene valor por defecto."""
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


def _list(name, default=""):
    return [x.strip().lower() for x in _s(name, default).split(",") if x.strip()]


def _upper(name):
    return [x.strip().upper() for x in _s(name).split(",") if x.strip()]


def _windows(name, default):
    out = []
    for part in _s(name, default).split(","):
        try:
            a, b = part.strip().split("-")
            out.append((int(a), int(b)))
        except ValueError:
            continue
    return out


# ---- Telegram ----
TELEGRAM_BOT_TOKEN = _s("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _s("TELEGRAM_CHAT_ID")

# ---- Escaneo ----
TIMEFRAME = _s("TIMEFRAME", "5m")
TOP_N = _i("TOP_N", 5)                      # señales (las mejores) enviadas por scan
MAX_SAME_DIR = _i("MAX_SAME_DIR", 3)        # maximo de longs o shorts dentro del TOP (diversificacion)
MIN_SCORE = _f("MIN_SCORE", 0)              # puntuacion minima 0-100 para enviar
MIN_VOLUME_USDT = _f("MIN_VOLUME_USDT", 0)          # 0 = se analizan TODAS las monedas con volumen > 0
MIN_LIQ_USDT = _f("MIN_LIQ_USDT", 1_000_000)        # flag/puerta "liquid": volumen 24h minimo para ENVIAR senales
MAX_SYMBOLS = _i("MAX_SYMBOLS", 0)          # 0 = sin limite
INCLUDE_SYMBOLS = _upper("INCLUDE_SYMBOLS")
EXCLUDE_SYMBOLS = _upper("EXCLUDE_SYMBOLS")
REQ_PER_SEC = _f("REQ_PER_SEC", 25)         # BingX permite 500 peticiones/10 s por IP en datos de mercado
SCAN_DELAY_SEC = _f("SCAN_DELAY_SEC", 4)
CANDLES = min(_i("WARMUP_BARS", 1000), 1400)
UNIVERSE_REFRESH_MIN = _i("UNIVERSE_REFRESH_MIN", 60)
HEARTBEAT_HOURS = _f("HEARTBEAT_HOURS", 6)
SIGNAL_MAX_AGE = _i("SIGNAL_MAX_AGE", 1)

# ---- Setups y filtros ----
# smc = Order Block SMC | p7h = niveles Prev 7H + Strong Closure | zone = ruptura/retest de zona de liquidez | trail = retest del trail
SETUPS = _list("SETUPS", "smc,p7h,zone,trail")
SEND_SETUPS = _list("SEND_SETUPS", "smc,p7h,zone,trail")   # los demas solo se anotan en el diario (modo sombra)
# Puertas: flags que DEBEN cumplirse para enviar. Lo demas suma puntos y se anota en el diario.
# Flags: htf15 htf1h trend5 btc adx session weekday sweep sweep_htf disp strong zone range_pos rvol cost liquid
GATES = _list("GATES", "htf15,cost,liquid")

# ---- SMC (Order Block) ----
SWING_LEN = _i("SWING_LEN", 5)
ENTRY_MODE = _s("ENTRY_MODE", "Retest OB")           # Retest OB | Mitad del OB
OB_MITIGATION = _s("OB_MITIGATION", "Close through") # Close through | Wick through
COOLDOWN_BARS = _i("COOLDOWN_BARS", 8)
SL_BUFFER_ATR = _f("SL_BUFFER_ATR", 0.3)
OB_MIN_AGE = _i("OB_MIN_AGE", 1)
SWEEP_LOOKBACK = _i("SWEEP_LOOKBACK", 30)

# ---- Motor de tendencia (trail EMA +- ATR) ----
TRAIL_MA_LEN = _i("TRAIL_MA_LEN", 28)
TRAIL_ATR_LEN = _i("TRAIL_ATR_LEN", 15)
TRAIL_MULT = _f("TRAIL_MULT", 1.25)
TRAIL_RETEST_EXPIRY = _i("TRAIL_RETEST_EXPIRY", 20)
ADX_LEN = _i("ADX_LEN", 14)
ADX_MIN = _f("ADX_MIN", 20)

# ---- Zonas de liquidez ----
ZONE_SWING_LEN = _i("ZONE_SWING_LEN", 12)
ZONE_ATR_MULT = _f("ZONE_ATR_MULT", 0.35)
ZONE_MAX = _i("ZONE_MAX", 8)
ZONE_RETEST_EXPIRY = _i("ZONE_RETEST_EXPIRY", 30)
ZONE_CONF_PAD_ATR = _f("ZONE_CONF_PAD_ATR", 0.25)

# ---- Prev 7H + Strong Closure ----
P7H_LEVEL_PCT = _f("P7H_LEVEL_PCT", 25.0)
P7H_ALIGN = _s("P7H_ALIGN", "day").lower()           # day = velas 0-7-14-21 UTC | continuous = bloques de 7h desde epoch
P7H_MODES = _list("P7H_MODES", "retest")             # strong | retest | break (puedes poner varios)
P7H_RETEST_WIN = _i("P7H_RETEST_WIN", 6)
P7H_SL_BUFFER_ATR = _f("P7H_SL_BUFFER_ATR", 0.15)
P7H_COOLDOWN = _i("P7H_COOLDOWN", 6)
SC_BODY_PCT = _f("SC_BODY_PCT", 55.0)
SC_CLOSE_PCT = _f("SC_CLOSE_PCT", 22.0)
SC_MIN_ATR = _f("SC_MIN_ATR", 0.9)
SC_RVOL = _f("SC_RVOL", 1.25)
DISP_LOOKBACK = _i("DISP_LOOKBACK", 3)

# ---- Sesion / contexto ----
SESSION_WINDOWS = _windows("SESSION_WINDOWS", "13-21")   # horas UTC [inicio-fin)
RANGE_FAV = _f("RANGE_FAV", 0.5)                         # largo favorable si esta en el <=50% bajo del rango 7h previo

# ---- Riesgo / objetivos ----
MAX_RISK_PCT = _f("MAX_RISK_PCT", 3.0)
TP1_R = _f("TP1_R", 1.0)
TP2_R = _f("TP2_R", 2.0)
TP3_R = _f("TP3_R", 3.0)
TP_BUFFER_ATR = _f("TP_BUFFER_ATR", 0.1)    # el objetivo de liquidez se coloca justo ANTES del nivel
MIN_RR = _f("MIN_RR", 1.5)
MAX_LIQ_RR = _f("MAX_LIQ_RR", 6.0)
# Costes reales: comision taker de BingX perpetuos 0.05% por lado (=0.10% ida y vuelta) + ~0.02% de deslizamiento
COST_PCT = _f("COST_PCT", 0.12)               # % del precio, ida y vuelta
MAX_COST_R = _f("MAX_COST_R", 0.25)           # flag 'cost': los costes no pueden comerse mas de este % de 1R
MAX_CHASE_R = _f("MAX_CHASE_R", 0.25)         # no se envia si el precio actual ya se alejo mas de esto (en R) de la entrada

# ---- Tamano de posicion (opcional, 0 = no mostrar) ----
ACCOUNT_USDT = _f("ACCOUNT_USDT", 0)
RISK_PCT = _f("RISK_PCT", 1.0)                # % de la cuenta que arriesgas por senal
MAX_LEVERAGE = _f("MAX_LEVERAGE", 10)

# ---- Diario / informes ----
_VOL = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()   # Railway lo define solo si hay un Volume conectado
JOURNAL_PATH = _s("JOURNAL_PATH", os.path.join(_VOL, "journal.db") if _VOL else "journal.db")
JOURNAL_MAX_BARS = _i("JOURNAL_MAX_BARS", 96)             # velas de seguimiento antes de dar la senal por caducada
JOURNAL_KEEP_DAYS = _i("JOURNAL_KEEP_DAYS", 14)
REPORT_HOUR_UTC = _i("REPORT_HOUR_UTC", 6)
REPORT_DAYS = _i("REPORT_DAYS", 7)
