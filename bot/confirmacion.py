"""Operar poco y confirmado, en vez de mucho y a la primera que pique.

El sistema abría cuando el voto compuesto pasaba de +0,35. Un solo número
decidía. Esto añade una segunda llave: además del voto, tienen que estar de
acuerdo las reglas que el bot ya tiene APRENDIDAS —las que demostraron ventaja
en bot/aprendizaje.py, no las que a alguien le gustan.

Dos llaves distintas para la misma puerta. Si solo hay una, no se abre.

La honestidad de esto depende de una cosa: las reglas que confirman tienen que
haberse aprendido en un tramo y usarse en otro. Aprenderlas y usarlas sobre los
mismos días es mirarse al espejo y llamarlo confirmación.
"""
from __future__ import annotations

from . import aprendizaje, playbook

# Cuántas reglas aprendidas tienen que decir "dentro" para abrir.
MIN_CONFIRMAN = 1


def aprender(series: dict, hasta: int) -> list[str]:
    """Reglas con ventaja demostrada usando SOLO los días anteriores a `hasta`."""
    m = aprendizaje.Memoria(ruta="/dev/null")
    m.reglas = {}
    aprendizaje.estudiar(m, series, desde=200, hasta=hasta)
    return [n for n, r in m.reglas.items() if r.estado == "aprendido"]


class Confirmador:
    """Sabe qué reglas están aprendidas y si dan el visto bueno hoy."""

    def __init__(self, nombres: list[str]):
        self.nombres = list(nombres)
        cat = {n: fn for n, _, fn in playbook.CATALOG}
        self.fns = [(n, cat[n]) for n in self.nombres if n in cat]

    def __bool__(self):
        return bool(self.fns)

    def confirman(self, pre, i) -> list[str]:
        out = []
        for n, fn in self.fns:
            try:
                if fn(pre, i):
                    out.append(n)
            except Exception:                            # noqa: BLE001,S112
                continue
        return out

    def ok(self, pre, i, minimo: int = MIN_CONFIRMAN):
        c = self.confirman(pre, i)
        if len(c) >= minimo:
            return True, c
        return False, c
