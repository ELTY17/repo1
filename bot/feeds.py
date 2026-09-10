"""Capa de datos de mercado. Precios REALES via Kraken (cripto) y Yahoo (indices).

Si la red falla, cae a un generador sintetico determinista para que el sistema
nunca se quede ciego (y lo marca claramente como degradado en el dashboard).
"""
from __future__ import annotations

import json
import math
import random
import ssl
import threading
import time
import urllib.error
import urllib.request

from .config import UNIVERSE

_UA = "Mozilla/5.0 (compatible; multi-agent-trader/1.0)"
_TIMEOUT = 15

_cache: dict[str, tuple[float, list]] = {}
_lock = threading.Lock()

# Estado de salud de cada fuente, expuesto en el dashboard
health: dict[str, str] = {}


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _kraken_ohlc(code: str, interval: int = 60) -> list[dict]:
    url = f"https://api.kraken.com/0/public/OHLC?pair={code}&interval={interval}"
    data = _get_json(url)
    if data.get("error"):
        raise RuntimeError(f"kraken: {data['error']}")
    key = next(k for k in data["result"] if k != "last")
    rows = data["result"][key]
    return [
        {"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
         "l": float(r[3]), "c": float(r[4]), "v": float(r[6])}
        for r in rows
    ]


def _yahoo_ohlc(code: str, rng: str = "60d", interval: str = "1h") -> list[dict]:
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{code}"
           f"?range={rng}&interval={interval}&includePrePost=false")
    data = _get_json(url)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        out.append({"t": int(t), "o": float(o), "h": float(h), "l": float(l),
                    "c": float(c), "v": float(q["volume"][i] or 0)})
    return out


# --- Fallback sintetico ------------------------------------------------------
_SEED_PRICE = {"BTC-USD": 78000.0, "ETH-USD": 2900.0, "SOL-USD": 135.0,
               "XRP-USD": 1.35, "DOGE-USD": 0.16, "HBAR-USD": 0.19,
               "TRX-USD": 0.28, "APT-USD": 3.4}


def _synthetic(symbol: str, n: int = 400) -> list[dict]:
    rnd = random.Random(hash(symbol) & 0xFFFF)
    price = _SEED_PRICE.get(symbol, 100.0)
    vol = 0.012 if symbol.endswith("USD") else 0.004
    now = int(time.time())
    out = []
    for i in range(n):
        drift = math.sin(i / 37.0) * vol * 0.4
        price *= math.exp(rnd.gauss(drift, vol))
        h = price * (1 + abs(rnd.gauss(0, vol / 2)))
        l = price * (1 - abs(rnd.gauss(0, vol / 2)))
        out.append({"t": now - (n - i) * 3600, "o": price, "h": h, "l": l,
                    "c": price, "v": abs(rnd.gauss(1000, 300))})
    return out


# --- API publica -------------------------------------------------------------
# temporalidades disponibles: (kraken_interval, yahoo_range, yahoo_interval)
TIMEFRAMES = {"1h": (60, "60d", "1h"), "1d": (1440, "2y", "1d")}


def get_candles(inst, ttl: int = 55, timeframe: str = "1h") -> list[dict]:
    """Velas del instrumento en la temporalidad pedida, cacheadas `ttl` segundos.

    "1h" es la que usa el sistema en vivo; "1d" da dos años de historia y es la
    que usa el backtest para tener una muestra que signifique algo.
    """
    kr_int, y_rng, y_int = TIMEFRAMES[timeframe]
    key = f"{inst.symbol}@{timeframe}"
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    try:
        if inst.venue == "kraken":
            candles = _kraken_ohlc(inst.code, kr_int)
        else:
            candles = _yahoo_ohlc(inst.code, y_rng, y_int)
        if len(candles) < 60:
            raise RuntimeError("pocas velas")
        health[inst.symbol] = "live"
    except Exception as e:                      # noqa: BLE001
        health[inst.symbol] = f"degradado: {type(e).__name__}"
        prev = _cache.get(key)
        candles = prev[1] if prev else _synthetic(inst.symbol)
    with _lock:
        _cache[key] = (time.time(), candles)
    return candles


def last_price(inst) -> float:
    c = get_candles(inst)
    return c[-1]["c"] if c else 0.0


WIDE_CRYPTO = ["XBTUSD", "ETHUSD", "SOLUSD", "XRPUSD", "ADAUSD", "DOTUSD",
               "LINKUSD", "AVAXUSD", "LTCUSD", "ATOMUSD", "UNIUSD", "AAVEUSD",
               "ALGOUSD", "FILUSD", "NEARUSD", "INJUSD", "TIAUSD", "SUIUSD",
               "XDGUSD", "BCHUSD", "ETCUSD", "XLMUSD", "HBARUSD", "TRXUSD",
               "APTUSD", "ARBUSD", "OPUSD", "SEIUSD", "ENAUSD", "ONDOUSD"]
WIDE_EQUITY: list[tuple[str, str]] = []      # solo cripto: no hay bolsa que mirar


def wide_universe() -> list[dict]:
    """Foto rapida de un universo mas ancho del que se opera.

    El sistema solo tiene posiciones en cinco instrumentos, pero mirar mas
    mercado sale casi gratis y dice en que estado esta el conjunto.
    """
    out = []
    try:
        d = _get_json("https://api.kraken.com/0/public/Ticker?pair="
                      + ",".join(WIDE_CRYPTO))
        for code, v in d.get("result", {}).items():
            o, c = float(v["o"]), float(v["c"][0])
            out.append({"symbol": code.replace("ZUSD", "").replace("USD", "")
                                      .replace("XXBT", "BTC").replace("XETH", "ETH")
                                      .replace("X", "", 1) if code.startswith("X")
                                 else code.replace("USD", ""),
                        "price": c, "chg": (c / o - 1) if o else 0.0,
                        "kind": "crypto"})
    except Exception:                                    # noqa: BLE001,S110
        pass
    for code, label in WIDE_EQUITY:
        try:
            c = _yahoo_ohlc(code, "5d", "1d")
            if len(c) >= 2:
                out.append({"symbol": code, "label": label, "price": c[-1]["c"],
                            "chg": c[-1]["c"] / c[-2]["c"] - 1, "kind": "equity"})
        except Exception:                                # noqa: BLE001,S110
            continue
    out.sort(key=lambda r: -abs(r["chg"]))
    return out


def snapshot() -> dict[str, dict]:
    """Precio y variacion reciente de todo el universo."""
    out = {}
    for inst in UNIVERSE:
        c = get_candles(inst)
        if not c:
            continue
        closes = [x["c"] for x in c]
        out[inst.symbol] = {
            "symbol": inst.symbol,
            "label": inst.label,
            "kind": inst.kind,
            "price": closes[-1],
            "chg_24h": (closes[-1] / closes[-25] - 1) if len(closes) > 25 else 0.0,
            "source": health.get(inst.symbol, "?"),
            "spark": closes[-60:],
        }
    return out
