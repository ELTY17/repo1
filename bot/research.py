"""Búsqueda sistemática de una ventaja, con las reglas honestas de siempre.

Hasta aquí probamos estrategias sueltas. Esto hace lo contrario: recorre un
espacio grande de reglas simples y bien conocidas, elige la mejor MIRANDO SOLO
el tramo de entrenamiento, y la mide en un tramo que no se ha tocado.

Ese orden es todo. Elegir mirando el resultado final es lo que hace que un
backtest parezca oro y luego no valga nada — ya nos pasó una vez en este repo.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request

CACHE = os.path.join(os.path.dirname(__file__), "..", ".research_cache.json")

# Universo amplio de Kraken: 720 velas diarias por par, ~2 años.
PAIRS = ["XBTUSD", "ETHUSD", "SOLUSD", "XRPUSD", "ADAUSD", "DOTUSD", "LINKUSD",
         "AVAXUSD", "LTCUSD", "ATOMUSD", "UNIUSD", "AAVEUSD", "ALGOUSD",
         "FILUSD", "NEARUSD", "INJUSD", "XLMUSD", "BCHUSD", "ETCUSD", "MKRUSD"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "research/1.0"})
    with urllib.request.urlopen(req, timeout=25,
                                context=ssl.create_default_context()) as r:
        return json.loads(r.read().decode())


def load(force: bool = False) -> dict[str, list[dict]]:
    """Histórico diario de todo el universo, cacheado en disco."""
    if not force and os.path.exists(CACHE):
        with open(CACHE) as f:
            d = json.load(f)
        if time.time() - d.get("t", 0) < 6 * 3600:
            return {k: v for k, v in d["data"].items()}

    out = {}
    for p in PAIRS:
        try:
            d = _get(f"https://api.kraken.com/0/public/OHLC?pair={p}&interval=1440")
            if d.get("error"):
                continue
            key = next(k for k in d["result"] if k != "last")
            rows = d["result"][key]
            if len(rows) < 400:
                continue
            # fuera la vela en curso: todavía se está moviendo
            if time.time() - int(rows[-1][0]) < 86400:
                rows = rows[:-1]
            out[p.replace("USD", "")] = [
                {"t": int(r[0]), "o": float(r[1]), "h": float(r[2]),
                 "l": float(r[3]), "c": float(r[4]), "v": float(r[6])} for r in rows]
        except Exception:                                    # noqa: BLE001,S112
            continue
        time.sleep(0.4)                                      # el contador de Kraken
    with open(CACHE, "w") as f:
        json.dump({"t": time.time(), "data": out}, f)
    return out


def aligned(data: dict[str, list[dict]]):
    """Recorta todas las series al mismo tramo de fechas."""
    stamps = [set(x["t"] for x in v) for v in data.values()]
    common = sorted(set.intersection(*stamps))
    out = {}
    for k, v in data.items():
        by = {x["t"]: x for x in v}
        out[k] = [by[t] for t in common]
    return out, common


if __name__ == "__main__":
    d = load()
    a, common = aligned(d)
    import datetime as dt
    print(f"{len(a)} activos · {len(common)} días comunes · "
          f"{dt.date.fromtimestamp(common[0])} → {dt.date.fromtimestamp(common[-1])}")
