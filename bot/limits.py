"""Minimos de orden del exchange.

Kraken rechaza cualquier orden por debajo de `ordermin` (en unidades del activo)
o de `costmin` (en dolares). El agente de riesgo no lo sabia, asi que con poco
capital habria mandado ordenes que el exchange devuelve rechazadas.

Este modulo los consulta, los cachea, y expone la comprobacion que faltaba.
"""
from __future__ import annotations

import time

from . import feeds
from .config import UNIVERSE

_cache: tuple[float, dict] | None = None

# Los brokers de acciones no publican esto por API abierta. SPY y QQQ se
# compran por acciones enteras salvo que el broker permita fraccionado, asi que
# el minimo real es el precio de una accion.
EQUITY_FRACTIONAL = False


def kraken_minimums(ttl: int = 3600) -> dict[str, dict]:
    global _cache
    if _cache and time.time() - _cache[0] < ttl:
        return _cache[1]
    codes = [i.code for i in UNIVERSE if i.venue == "kraken"]
    out = {}
    try:
        d = feeds._get_json(
            "https://api.kraken.com/0/public/AssetPairs?pair=" + ",".join(codes))
        raw = d.get("result", {})
        # Kraken publica el nombre pedido en `altname`. Emparejar por prefijos
        # del codigo funcionaba con tres pares y se rompe en cuanto entran LINK
        # y LTC, o ADA y ALGO: "LIN" y "LT" casan con quien no toca.
        by_alt = {(v.get("altname") or "").upper(): v for v in raw.values()}
        for inst in UNIVERSE:
            if inst.venue != "kraken":
                continue
            v = by_alt.get(inst.code.upper())
            if v is None:                       # algunos responden con el nombre largo
                v = next((x for k, x in raw.items()
                          if k.upper() == inst.code.upper()), None)
            if v is None:
                continue
            out[inst.symbol] = {"ordermin": float(v.get("ordermin", 0) or 0),
                                "costmin": float(v.get("costmin", 0) or 0)}
    except Exception:                                    # noqa: BLE001,S110
        pass
    _cache = (time.time(), out)
    return out


def min_notional(inst, price: float) -> float:
    """Dolares minimos que hay que poner para que la orden se acepte."""
    if inst.venue == "kraken":
        m = kraken_minimums().get(inst.symbol)
        if not m:
            return 0.0
        return max(m["ordermin"] * price, m["costmin"])
    return 0.0 if EQUITY_FRACTIONAL else price       # una accion entera


def check(inst, price: float, notional: float) -> tuple[bool, str]:
    need = min_notional(inst, price)
    if notional + 1e-9 < need:
        return False, (f"por debajo del mínimo del exchange "
                       f"(${notional:.2f} < ${need:.2f})")
    return True, ""
