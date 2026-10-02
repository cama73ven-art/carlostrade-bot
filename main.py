import ccxt
import pandas as pd
import numpy as np
import time
import csv
import os
from datetime import datetime
from telegram import Bot

# ============ CONFIGURACIÓN ============
API_KEY = os.environ.get("BINANCE_API_KEY", "TU_API_KEY_AQUI")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "TU_API_SECRET_AQUI")
SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"
CAPITAL_INICIAL = 30.0
RIESGO = 0.01
ATR_PERIOD = 14
SL_MULT = 1.5
TP_MULT = 2.0
LOTE_MIN = 0.001
NOTIONAL_MIN = 100
CHECK_EVERY = 60
CSV_LOG = "trades_log.csv"

# ===== TELEGRAM =====
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1004497332834")
tg_bot = Bot(token=TELEGRAM_TOKEN)

def notify(text):
    """Envía un mensaje a tu canal de Telegram."""
    try:
        tg_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text)
    except Exception as e:
        print("⚠️ No se pudo notificar a Telegram:", e)

# ============ CONEXIÓN TESTNET ============
exchange = ccxt.binance({
    "apiKey": API_KEY,
    "secret": API_SECRET,
    "enableRateLimit": True,
    "options": {"defaultType": "future"},
    "urls": {
        "api": {
            "public": "https://testnet.binancefuture.com/api",
            "private": "https://testnet.binancefuture.com/api",
        }
    },
})

def log_trade(row):
    file_exists = os.path.isfile(CSV_LOG)
    with open(CSV_LOG, "a", newline="") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["timestamp","symbol","side","price","size","sl","tp","pnl","reason"])
        w.writerow(row)

def get_ohlcv():
    bars = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=ATR_PERIOD + 5)
    df = pd.DataFrame(bars, columns=["ts","open","high","low","close","volume"])
    return df

def compute_atr(df):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean().iloc[-1]

def get_position():
    pos = exchange.fetch_positions([SYMBOL])
    for p in pos:
        if float(p["contracts"]) != 0:
            return p
    return None

def place_order(side, amount, sl, tp):
    params = {}
    order = exchange.create_order(SYMBOL, "MARKET", side, amount, params=params)
    try:
        exchange.create_order(SYMBOL, "STOP_MARKET",
            "sell" if side == "buy" else "buy", amount,
            params={"stopPrice": round(sl, 2), "reduceOnly": True})
        exchange.create_order(SYMBOL, "TAKE_PROFIT_MARKET",
            "sell" if side == "buy" else "buy", amount,
            params={"stopPrice": round(tp, 2), "reduceOnly": True})
    except Exception as e:
        print("⚠️ SL/TP no colocados:", e)
    return order

def report_status():
    """Te informa saldo y posición actual."""
    bal = exchange.fetch_balance()
    free = bal["USDT"]["free"]
    pos = get_position()
    msg = f"💰 SALDO: {free:.2f} USDT\n"
    if pos:
        msg += (f"📊 POSICIÓN ABIERTA\nLado: {pos['side']}\n"
                f"Contratos: {pos['contracts']}\n"
                f"Precio entrada: {pos['entryPrice']}\n"
                f"PnL no realizado: {pos['unrealizedPnl']}")
    else:
        msg += "📭 Sin posiciones abiertas"
    notify(msg)

# ===== ARRANQUE =====
print("🤖 Bot testnet iniciado:", datetime.now())
bal_inicio = exchange.fetch_balance()["USDT"]["free"]
print("Saldo:", bal_inicio, "USDT")
notify(f"🚀 Bot de testnet iniciado\nSaldo inicial: {bal_inicio:.2f} USDT")

last_report = time.time()

while True:
    try:
        df = get_ohlcv()
        atr = compute_atr(df)
        close = df["close"].iloc[-1]
        pos = get_position()

        if pos is None:
            sl_dist = atr * SL_MULT
            sl = close - sl_dist
            tp = close + atr * TP_MULT

            lote = (CAPITAL_INICIAL * RIESGO) / sl_dist
            lote = max(round(lote, 5), LOTE_MIN)
            if lote * close < NOTIONAL_MIN:
                lote = round(NOTIONAL_MIN / close, 5)

            print(f"📈 Señal LONG | entry≈{close:.2f} sl={sl:.2f} tp={tp:.2f} lote={lote}")
            order = place_order("buy", lote, sl, tp)
            log_trade([datetime.now(), SYMBOL, "buy", close, lote,
                       round(sl,2), round(tp,2), "", "open"])
            print("✅ Orden abierta:", order["id"])
            notify(
                f"🟢 TRADE ABIERTO\n"
                f"Par: {SYMBOL}\n"
                f"Lado: LONG (buy)\n"
                f"Entrada: {close:.2f}\n"
                f"SL: {sl:.2f}\n"
                f"TP: {tp:.2f}\n"
                f"Lote: {lote}"
            )
        else:
            print("⏳ Ya hay posición abierta, esperando cierre por SL/TP...")

        # Reporte de saldo cada 10 min
        if time.time() - last_report > 600:
            report_status()
            last_report = time.time()

    except Exception as e:
        print("❌ Error:", e)
        notify(f"❌ Error en bot: {e}")

    time.sleep(CHECK_EVERY)
