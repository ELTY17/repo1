"""Correlación entre lo que se tiene y lo que se quiere comprar.

El tope de posiciones por clase de activo es un parche. Dice "no más de dos
criptos" porque midiendo salió que tres o cuatro empeoraban, pero no sabe POR
QUÉ: no distingue entre comprar BTC y ETH —que se mueven juntos y son la misma
apuesta con dos nombres— y comprar BTC y XLM, que se parecen bastante menos.

Esto lo mide. Correlación de Pearson sobre los rendimientos diarios de la
ventana reciente, que es el número que dice si estás diversificando o si te
estás engañando.
"""
from __future__ import annotations

VENTANA = 60          # días de rendimientos que se miran
UMBRAL = 0.75         # por encima de esto, es la misma apuesta otra vez


def rendimientos(candles, n: int = VENTANA) -> list[float]:
    c = [x["c"] for x in candles[-(n + 1):]]
    return [c[i] / c[i - 1] - 1 for i in range(1, len(c)) if c[i - 1] > 0]


def pearson(a: list[float], b: list[float]) -> float | None:
    m = min(len(a), len(b))
    if m < 20:
        return None
    a, b = a[-m:], b[-m:]
    ma, mb = sum(a) / m, sum(b) / m
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / (va * vb) ** 0.5


def corr_con_cartera(candidato, abiertas: dict, n: int = VENTANA):
    """Correlación media del candidato con lo que ya hay abierto.

    Devuelve (media, máxima, con_quién). Sin posiciones abiertas devuelve None:
    la primera compra nunca se bloquea por correlación.
    """
    if not abiertas:
        return None, None, None
    r0 = rendimientos(candidato, n)
    peor, quien, suma, cuenta = None, None, 0.0, 0
    for sym, velas in abiertas.items():
        c = pearson(r0, rendimientos(velas, n))
        if c is None:
            continue
        suma += c
        cuenta += 1
        if peor is None or c > peor:
            peor, quien = c, sym
    if not cuenta:
        return None, None, None
    return suma / cuenta, peor, quien


def permite(candidato, abiertas: dict, umbral: float = UMBRAL, n: int = VENTANA):
    """(ok, motivo). El veto mira la correlación MÁXIMA, no la media.

    Una media baja puede esconder un par idéntico: si ya tienes BTC, comprar
    ETH es repetir la apuesta aunque el resto de la cartera no se le parezca.
    """
    _, peor, quien = corr_con_cartera(candidato, abiertas, n)
    if peor is None:
        return True, ""
    if peor > umbral:
        return False, f"correlación {peor:.2f} con {quien}: es la misma apuesta"
    return True, ""


def matriz(series: dict, n: int = VENTANA) -> dict:
    """Correlación de todos contra todos, para enseñarla en el dashboard."""
    rs = {s: rendimientos(v, n) for s, v in series.items()}
    out = {}
    for a in rs:
        for b in rs:
            if a < b:
                c = pearson(rs[a], rs[b])
                if c is not None:
                    out[f"{a}|{b}"] = round(c, 3)
    return out


if __name__ == "__main__":
    from . import feeds
    from .config import UNIVERSE
    datos = {}
    for i in UNIVERSE:
        try:
            datos[i.symbol] = feeds.get_candles(i, timeframe="1d")
        except Exception:                                    # noqa: BLE001
            continue
    m = matriz(datos)
    pares = sorted(m.items(), key=lambda x: -x[1])
    print(f"{len(datos)} activos · {len(m)} pares · ventana {VENTANA} días\n")
    print("Los que más se parecen (comprar los dos es comprar uno dos veces):")
    for k, v in pares[:8]:
        print(f"  {k.replace('|', ' ~ '):<26}{v:>6.2f}")
    print("\nLos que menos:")
    for k, v in pares[-5:]:
        print(f"  {k.replace('|', ' ~ '):<26}{v:>6.2f}")
    media = sum(m.values()) / len(m)
    altos = sum(1 for v in m.values() if v > UMBRAL)
    print(f"\nCorrelación media del universo: {media:.2f}")
    print(f"Pares por encima de {UMBRAL}: {altos} de {len(m)} ({altos/len(m):.0%})")
