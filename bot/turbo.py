"""De 10 a 100 en cinco horas: qué haría falta, y qué cuesta intentarlo.

Este módulo NO es una estrategia. Es la aritmética de la pregunta, que tiene
respuesta exacta y conviene mirarla de frente.

Multiplicar por diez en cinco horas no se consigue acertando más, se consigue
apostando más fuerte. Si arriesgas la mitad de la cuenta en cada operación, la
misma palanca que te lleva a 100 te lleva a 0, y llega antes a 0. Aquí se
calcula el acierto exacto que haría falta, y luego se simulan 10.000 sesiones
con esa regla para ver cuántas terminan en 100 y cuántas en cero.

    python3 -m bot.turbo
    python3 -m bot.turbo --acierto 0.55    # con un acierto realista
"""
from __future__ import annotations

import argparse
import math
import random

FEE = 0.0026          # ida y vuelta se paga dos veces
FLOOR = 1.0           # por debajo de esto ningún exchange te acepta la orden


def required_winrate(start: float, target: float, trades: int, risk: float) -> float:
    """Acierto necesario para llegar al objetivo apostando `risk` cada vez.

    Con ganancia y pérdida simétricas de tamaño `risk`, el crecimiento medio
    por operación en logaritmo es p·ln(1+risk) + (1-p)·ln(1-risk). Se despeja p.
    """
    need = math.log(target / start) / trades
    up, dn = math.log(1 + risk), math.log(1 - risk)
    return (need - dn) / (up - dn)


def session(start, target, trades, risk, p, rng):
    """Una sesión. Devuelve (capital final, operaciones hechas, tocó objetivo)."""
    eq, n = start, 0
    for _ in range(trades):
        if eq < FLOOR:                       # arruinado: no se puede ni operar
            break
        eq *= 1 - 2 * FEE                    # entrar y salir cuesta
        eq *= (1 + risk) if rng.random() < p else (1 - risk)
        n += 1
        if eq >= target:
            return eq, n, True
    return eq, n, False


def montecarlo(start, target, trades, risk, p, runs=10000, seed=1):
    rng = random.Random(seed)
    hits = ruin = 0
    ends = []
    for _ in range(runs):
        eq, _, hit = session(start, target, trades, risk, p, rng)
        hits += hit
        ruin += eq < FLOOR
        ends.append(eq)
    ends.sort()
    return {
        "objetivo": hits / runs,
        "ruina": ruin / runs,
        "mediana": ends[runs // 2],
        "p10": ends[runs // 10],
        "p90": ends[runs - runs // 10],
    }


class Sesion:
    """Una sesión de $10 que se mueve, para verla en el dashboard.

    Es ficción declarada: las operaciones salen de un generador aleatorio con
    el acierto que le pongas, no de un mercado. Sirve para ver la forma que
    tiene una curva apalancada — sube en escalera y se cae de golpe — no para
    creerse el número final.
    """

    def __init__(self, inicio=10.0, objetivo=100.0, operaciones=60,
                 riesgo=0.50, acierto=None, seed=None):
        self.inicio, self.objetivo = inicio, objetivo
        self.total, self.riesgo = operaciones, riesgo
        self.acierto = acierto if acierto is not None else required_winrate(
            inicio, objetivo, operaciones, riesgo)
        self.rng = random.Random(seed)
        self.reiniciar()

    def reiniciar(self):
        self.eq = self.inicio
        self.curva = [self.inicio]
        self.ops = []
        self.fin = None                      # None | "objetivo" | "ruina" | "agotada"

    def paso(self):
        """Una operación. Devuelve False cuando la sesión ya ha terminado."""
        if self.fin:
            return False
        antes = self.eq
        self.eq *= 1 - 2 * FEE
        gana = self.rng.random() < self.acierto
        self.eq *= (1 + self.riesgo) if gana else (1 - self.riesgo)
        self.curva.append(self.eq)
        self.ops.append({"n": len(self.ops) + 1, "gana": gana,
                         "antes": round(antes, 2), "despues": round(self.eq, 2),
                         "delta": round(self.eq - antes, 2)})
        if self.eq >= self.objetivo:
            self.fin = "objetivo"
        elif self.eq < FLOOR:
            self.fin = "ruina"
        elif len(self.ops) >= self.total:
            self.fin = "agotada"
        return True

    def estado(self):
        pico = max(self.curva)
        return {
            "ficcion": True,
            "inicio": self.inicio, "objetivo": self.objetivo,
            "acierto": round(self.acierto, 4), "riesgo": self.riesgo,
            "eq": round(self.eq, 2), "curva": [round(x, 3) for x in self.curva],
            "ops": self.ops[-12:][::-1], "hechas": len(self.ops), "total": self.total,
            "pico": round(pico, 2), "fin": self.fin,
            "aciertos": sum(1 for o in self.ops if o["gana"]),
            "x": round(self.eq / self.inicio, 2),
        }


def camino(returns, inicio=10.0, meta=100.0, stop=1.0, runs=20000, seed=11):
    """Desde $10 y resampleando operaciones reales, ¿se llega a $100 o a $1?

    Es la misma pregunta del titular, pero hecha con los resultados que el
    sistema saca de verdad en vez de con una palanca inventada. La respuesta
    cambia por completo: se llega casi siempre, y se tarda una eternidad.
    """
    if not returns:
        return {"llega": 0.0, "ruina": 0.0, "mediana_ops": None}
    rng = random.Random(seed)
    llega = 0
    pasos = []
    for _ in range(runs):
        eq, n = inicio, 0
        while stop <= eq < meta and n < 200000:
            eq *= 1 + returns[rng.randrange(len(returns))]
            n += 1
        if eq >= meta:
            llega += 1
            pasos.append(n)
    pasos.sort()
    return {"llega": round(llega / runs, 4),
            "ruina": round(1 - llega / runs, 4),
            "mediana_ops": pasos[len(pasos) // 2] if pasos else None,
            "operaciones": len(returns)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inicio", type=float, default=10.0)
    ap.add_argument("--objetivo", type=float, default=100.0)
    ap.add_argument("--horas", type=float, default=5.0)
    ap.add_argument("--cada", type=int, default=5, help="minutos entre operaciones")
    ap.add_argument("--riesgo", type=float, default=0.50, help="fracción por operación")
    ap.add_argument("--acierto", type=float, default=None)
    a = ap.parse_args()

    trades = int(a.horas * 60 / a.cada)
    need = required_winrate(a.inicio, a.objetivo, trades, a.riesgo)

    print(f"De ${a.inicio:.0f} a ${a.objetivo:.0f} en {a.horas:g} horas")
    print(f"  una operación cada {a.cada} min → {trades} operaciones")
    print(f"  arriesgando el {a.riesgo:.0%} de la cuenta en cada una")
    print(f"\n  ACIERTO NECESARIO: {need:.1%}")
    print(f"  (hay que ganar {need * trades:.0f} de {trades}; "
          f"un sistema bueno de verdad anda por el 55%)")

    print(f"\n{'acierto':<10}{'llega a 100':>13}{'acaba en 0':>13}{'mediana':>11}"
          f"{'p10':>9}{'p90':>10}")
    escenarios = [a.acierto] if a.acierto else [need, 0.60, 0.55, 0.50]
    for p in escenarios:
        r = montecarlo(a.inicio, a.objetivo, trades, a.riesgo, p)
        etiqueta = f"{p:.1%}" + (" ←" if abs(p - need) < 1e-9 else "")
        print(f"{etiqueta:<10}{r['objetivo']:>12.1%}{r['ruina']:>13.1%}"
              f"{r['mediana']:>10.2f}${r['p10']:>8.2f}{r['p90']:>9.2f}")

    print("\nLa primera fila es la que hay que leer despacio: con el acierto exacto")
    print("que hace falta, sí, la mayoría llega — pero una de cada tres sesiones")
    print("termina en cero, y esa no tiene vuelta atrás. Y ese acierto no existe:")
    print("con un 55%, que ya sería un sistema bueno, el 81% de las sesiones muere.")
    print("La palanca que multiplica es exactamente la misma que divide.")


if __name__ == "__main__":
    main()
