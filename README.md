# SMC Bot v2 (BingX · Telegram · Railway)

Escanea **todos** los perpetuos USDT de BingX (sin filtro de volumen; la puerta `liquid` solo deja enviar señales de monedas con volumen 24h ≥ `MIN_LIQ_USDT`; las demás quedan en el diario), puntúa los setups y envía a Telegram el **TOP 5** al cierre de cada vela.
Solo señales: no opera. **Todos los archivos van en la raíz del repo, sin carpetas.**

## Archivos
`main.py` (bucle) · `strategy.py` (flags, puntuación, SL/TP) · `setups.py` (4 setups) · `context.py` (series causales) · `indicators.py` · `zones.py` ·
`journal.py` (diario + informe) · `bingx.py` · `notifier.py` · `backtest.py` · `test_all.py` · `start.py` · `Procfile` · `railway.json` · `requirements.txt` ·
`_env.example` `_gitignore` `_python-version` (renómbralos con punto: `.env.example`, `.gitignore`, `.python-version`; son opcionales).

## Setups
- **SMC**: barrida → MSS/CHOCH → Order Block → retest (port del Pine "SMC Notebook").
- **P7H**: nivel 25% del rango de la vela anterior de 7h + vela *Strong Closure*. El modo `retest` es un retest real (el Pine original actuaba como ruptura).
- **ZONE**: ruptura + retest de zonas de liquidez (pivotes con grosor ATR), simétrico arriba y abajo (el Pine solo funcionaba al alza).
- **TRAIL**: retest del trail (EMA ± ATR) tras un cambio de tendencia; la espera caduca.

## Flags y puntuación (0–100)
Cada señal lleva flags: `htf15 htf1h trend5 btc adx session weekday sweep sweep_htf disp strong zone range_pos rvol`.
`GATES` = flags obligatorios para enviar (por defecto `htf15,cost,liquid`). `cost` exige que las comisiones (taker 0,05% por lado en BingX perpetuos + deslizamiento = `COST_PCT` 0,12%) no se coman más del 25% de 1R. El resto suma puntos; las puertas activas se excluyen de la puntuación para no contarlas dos veces.
Objetivos: TP1/TP2/TP3 (1R/2R/3R) y un objetivo de **liquidez** colocado justo antes del nivel opuesto más cercano. Plan: en TP1 cierra parte y mueve el SL a break-even.
El TOP limita a `MAX_SAME_DIR` longs o shorts para no apostar cinco veces a lo mismo.
Cada mensaje indica hasta qué precio sigue válida la entrada (`MAX_CHASE_R`); si el precio ya se alejó, la señal no se envía (queda en el diario). Con `ACCOUNT_USDT` > 0 muestra también el tamaño de posición para arriesgar `RISK_PCT`%.

## Diario y modo sombra
Todas las señales (también las que no pasan las puertas) se guardan en SQLite y se siguen vela a vela: TP1/TP2/TP3 alcanzados antes del SL, SL, o caducada.
Cada día a `REPORT_HOUR_UTC` llega un **informe** con win rate y expectativa en R **neta de costes**, con error estándar, por setup y por flag. La sección *Conclusiones sólidas* solo propone cambios si son estadísticamente claros (z ≥ 3); si no, dice que es ruido.
**Railway:** conecta un *Volume* al servicio (Railway define `RAILWAY_VOLUME_MOUNT_PATH` y el bot lo usa solo). Sin volumen el diario se borra en cada despliegue y el bot te avisa al arrancar.

## Despliegue
1. Telegram: @BotFather → `TELEGRAM_BOT_TOKEN`; escríbele un mensaje y saca tu `TELEGRAM_CHAT_ID` (p. ej. con @userinfobot).
2. Sube TODOS los archivos a GitHub (sin carpetas) y despliega en Railway como servicio *worker*.
3. Variables: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (+ las de `_env.example` que quieras cambiar).
4. Railway → Settings → Deploy → Custom Start Command: vacío o `python main.py`.

## Backtest y pruebas
```
pip install -r requirements.txt
python test_all.py                                   # pruebas (sin red)
python backtest.py --symbols BTC-USDT,ETH-USDT --days 30
python backtest.py --top 20 --days 30
python backtest.py --top 20 --days 30 --optimize     # busca puertas con validación train/test
```
`--optimize` prueba combinaciones de hasta 3 puertas en el 70% inicial y las comprueba en el 30% final. Con 13 flags hay cientos de combinaciones, así que la mejor en train casi siempre es suerte: solo cuenta lo que sigue positivo en test (n ≥ 100). Si dice "ninguna es creíble", no cambies nada.
El backtest usa la misma lógica que el bot en vivo (el flag `btc` se asume cumplido). `--synthetic` usa datos inventados solo para comprobar que funciona: **sus resultados no significan nada**.

## Notas
- La vela de 7h: por defecto bloques 0-7-14-21 UTC (`P7H_ALIGN=day`). Compáralo con tu gráfico de BingX; si no coincide, prueba `continuous`.
- Consumo: ~500 monedas × 1000 velas por scan (unos 10 ms de CPU por moneda). Si Railway da 429, baja `REQ_PER_SEC`; si va justo de CPU, baja `WARMUP_BARS` (mínimo ~800 para el filtro de 1h).
- Trading con apalancamiento = riesgo de pérdida total. Sin garantías.
