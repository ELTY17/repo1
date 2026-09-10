"""Qué da de sí una cuenta pequeña en un plazo corto.

No es una simulación ni una opinión: son las cifras del propio mercado. Cuánto se
mueve un activo en un día, cuánto cuesta entrar y salir, y qué queda.

    python3 -m bot.reality --cash 19 --hours 24
"""
from __future__ import annotations

import argparse
import statistics as st

from .backtest import _series
from .config import UNIVERSE, Config
from .limits import min_notional


def main(cash: float, hours: int, fee: float = 0.0026, slip: float = 0.0010):
    cfg = Config(); warmup = 120
    tf = "1d" if hours >= 24 else "1h"
    series = _series(warmup, tf)
    n = min(len(c) for c in series.values())
    bars = max(1, round(hours / (24 if tf == "1d" else 1)))

    print("=" * 72)
    print(f"  ${cash:.0f} EN {hours} HORAS · lo que dice el mercado, no lo que promete nadie")
    print("=" * 72)

    ok, no = [], []
    for inst in UNIVERSE:
        c = series.get(inst.symbol)
        if not c:
            no.append(inst.symbol); continue
        stake = min(cash / cfg.max_positions, cash * cfg.max_position_weight)
        (ok if stake >= min_notional(inst, c[-1]["c"]) else no).append(inst.symbol)
    print(f"  Puede operar : {', '.join(ok) or 'NINGUNO'}")
    print(f"  Le rechazan  : {', '.join(no) or '—'}  (mínimo del exchange)")

    stake = min(cash / cfg.max_positions, cash * cfg.max_position_weight)
    cost = stake * (fee + slip) * 2
    print(f"  Tamaño       : ${stake:.2f} por posición")
    print(f"  Ida y vuelta : ${cost:.3f} de comisión y deslizamiento")

    rets = []
    for sym in ok:
        w = series[sym][len(series[sym]) - n:][warmup:]
        rets += [w[i]["c"] / w[i - bars]["c"] - 1 for i in range(bars, len(w))]
    if not rets:
        print("\n  Con este capital no puede abrir nada. Fin del análisis.")
        return
    rets.sort()

    def q(p): return rets[min(int(p * len(rets)), len(rets) - 1)]
    print("-" * 72)
    print(f"  Repartiendo {len(rets)} ventanas reales de {hours} h:")
    for name, p in [("peor 5 %", .05), ("cuartil bajo", .25), ("mediana", .50),
                    ("cuartil alto", .75), ("mejor 5 %", .95)]:
        neto = stake * q(p) - cost
        print(f"    {name:<14}{q(p)*100:>7.2f}%   →  {neto:+.3f} $ netos")
    gana = sum(1 for r in rets if stake * r > cost) / len(rets)
    print("-" * 72)
    print(f"  Solo el {gana*100:.0f} % de las ventanas se mueve lo bastante")
    print(f"  para cubrir la comisión. La mediana deja {stake*q(.5)-cost:+.3f} $.")
    print()
    print(f"  Rango realista del resultado: entre {stake*q(.05)-cost:+.2f} $ "
          f"y {stake*q(.95)-cost:+.2f} $.")
    print("  Eso no es una prueba de si el sistema funciona: es una moneda al aire.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=19.0)
    ap.add_argument("--hours", type=int, default=24)
    a = ap.parse_args()
    main(a.cash, a.hours)
