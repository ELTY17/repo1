"""Barrido sistemático: muchas reglas simples, elegidas a ciegas.

El método importa más que las reglas. Partimos las ~720 velas diarias en dos
mitades. En la PRIMERA se prueban todas las combinaciones y se elige la mejor.
La SEGUNDA no se toca hasta que la elección ya está hecha, y es la única cifra
que se reporta como resultado.

Todo lo demás es lo de siempre: comisiones reales de Kraken en cada rotación,
mínimos de orden, y buy-and-hold como listón. Si la regla ganadora no le gana
al listón fuera de muestra, la respuesta correcta es que no hay ventaja.

    python -m bot.sweep            # barrido completo
    python -m bot.sweep --top 15   # ver la cola de candidatas
"""
from __future__ import annotations

import argparse
import datetime as dt
import itertools

from bot import research

FEE = 0.0026          # taker de Kraken, por lado
MIN_NOTIONAL = 5.0    # costmin típico de Kraken en pares USD
START = 100.0

# --- espacio de búsqueda -----------------------------------------------------
MOM = [5, 10, 20, 30, 60, 90, 120]   # momentum: mejor rendimiento pasado
REV = [1, 3, 5, 10]                  # reversión: peor rendimiento pasado
HOLD = [1, 3, 5]                     # cuántos activos a la vez
REBAL = [1, 5, 10]                   # cada cuántos días se rota
TREND = [0, 20, 50, 100, 200]        # 0 = sin filtro; si no, exigir c > SMA(n)


def _sma(closes, i, n):
    if n == 0 or i + 1 < n:
        return None
    return sum(closes[i - n + 1:i + 1]) / n


def signal(closes, i, look, kind):
    """Rendimiento pasado del activo. Devuelve None si no hay historia."""
    if i < look:
        return None
    prev = closes[i - look]
    if prev <= 0:
        return None
    r = closes[i] / prev - 1.0
    return r if kind == "mom" else -r


def simulate(series, lo, hi, look, kind, hold, rebal, trend):
    """Cartera equiponderada sobre el tramo [lo, hi). Devuelve (retorno, ops)."""
    names = sorted(series)
    equity, held, trades = START, {}, 0
    for i in range(lo, hi):
        # marcar a mercado con el cierre de hoy
        if held:
            equity = sum(q * series[n][i]["c"] for n, q in held.items())
        if (i - lo) % rebal:
            continue
        ranked = []
        for n in names:
            cl = [x["c"] for x in series[n]]
            s = signal(cl, i, look, kind)
            if s is None:
                continue
            if trend:
                m = _sma(cl, i, trend)
                if m is None or cl[i] <= m:
                    continue
            ranked.append((s, n))
        ranked.sort(reverse=True)
        want = {n for _, n in ranked[:hold]}
        if set(held) == want:
            continue
        slice_ = equity / max(len(want), 1)
        if want and slice_ < MIN_NOTIONAL:      # el exchange rechazaría la orden
            want = set(list(want)[:max(int(equity // MIN_NOTIONAL), 0)])
            slice_ = equity / len(want) if want else 0.0
        # coste: vender lo que sale, comprar lo que entra
        turn = sum(q * series[n][i]["c"] for n, q in held.items() if n not in want)
        turn += slice_ * len(want - set(held))
        equity -= turn * FEE
        trades += len(set(held) ^ want)
        slice_ = equity / len(want) if want else 0.0
        held = {n: slice_ / series[n][i]["c"] for n in want}
    if held:
        end = hi - 1
        equity = sum(q * series[n][end]["c"] for n, q in held.items())
        equity -= equity * FEE          # liquidar al final también cuesta
    return equity / START - 1.0, trades


def hold_all(series, lo, hi):
    """Listón: comprar todo el universo a partes iguales y no tocar nada."""
    names = sorted(series)
    slice_ = START * (1 - FEE) / len(names)
    q = {n: slice_ / series[n][lo]["c"] for n in names}
    end = sum(q[n] * series[n][hi - 1]["c"] for n in names) * (1 - FEE)
    return end / START - 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    series, common = research.aligned(research.load(force=a.force))
    n = len(common)
    warm = max(TREND + MOM)                      # historia mínima antes de operar
    split = warm + (n - warm) // 2               # dos mitades iguales YA operables
    print(f"{len(series)} activos · {n} días · "
          f"{dt.date.fromtimestamp(common[0])} → {dt.date.fromtimestamp(common[-1])}")
    print(f"entreno {dt.date.fromtimestamp(common[warm])} → "
          f"{dt.date.fromtimestamp(common[split - 1])} | "
          f"prueba {dt.date.fromtimestamp(common[split])} → "
          f"{dt.date.fromtimestamp(common[-1])}")

    space = []
    for look, kind in [(l, "mom") for l in MOM] + [(l, "rev") for l in REV]:
        for hold, rebal, trend in itertools.product(HOLD, REBAL, TREND):
            space.append((look, kind, hold, rebal, trend))
    print(f"{len(space)} combinaciones\n")

    # --- fase 1: elegir mirando SOLO el entrenamiento -------------------------
    res = []
    for cfg in space:
        r, t = simulate(series, warm, split, *cfg)
        res.append((r, t, cfg))
    res.sort(reverse=True)

    bh_tr = hold_all(series, warm, split)
    print(f"ENTRENO — comprar y esperar: {bh_tr:+.2%}")
    print(f"{'regla':<34}{'entreno':>10}{'ops':>7}")
    for r, t, cfg in res[:a.top]:
        look, kind, hold, rebal, trend = cfg
        name = (f"{kind}{look} top{hold} rot{rebal}"
                + (f" >sma{trend}" if trend else ""))
        print(f"{name:<34}{r:>+10.2%}{t:>7}")

    # --- fase 2: la elegida, en el tramo intacto -----------------------------
    best = res[0][2]
    look, kind, hold, rebal, trend = best
    name = (f"{kind}{look} top{hold} rot{rebal}"
            + (f" >sma{trend}" if trend else ""))
    te, tt = simulate(series, split, n, *best)
    bh_te = hold_all(series, split, n)

    print(f"\nPRUEBA (nunca vista) — elegida a ciegas: {name}")
    print(f"  regla            {te:+.2%}  ({tt} ops)")
    print(f"  comprar y esperar {bh_te:+.2%}")
    print(f"  diferencia       {te - bh_te:+.2%}")

    # ¿fue suerte la ganadora, o el tipo de regla aguanta?
    top = res[:20]
    avg = sum(simulate(series, split, n, *c)[0] for _, _, c in top) / len(top)
    print(f"\n  las 20 mejores del entreno, promedio en prueba: {avg:+.2%}")
    # ¿cuántas reglas del espacio entero le ganan al listón fuera de muestra?
    beat = sum(1 for _, _, c in res if simulate(series, split, n, *c)[0] > bh_te)
    print(f"  reglas que baten al listón en prueba: {beat}/{len(res)} "
          f"({beat / len(res):.0%}) — al azar se esperaría ~50%")
    print(f"  veredicto: {'hay algo que mirar' if te > bh_te and avg > bh_te else 'sin ventaja demostrable'}")


if __name__ == "__main__":
    main()
