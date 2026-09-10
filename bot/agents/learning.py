"""Agente 7 — APRENDIZAJE.

Los demas deciden. Este mira lo que paso DESPUES de cada decision y lleva la
cuenta. Cada barra nueva comprueba, para cada regla del catalogo y cada activo,
si la regla decia "dentro" en la barra anterior, y apunta lo que hizo el precio.

No promociona nada por corazonadas: una regla pasa a APRENDIDA cuando su
ventaja media se separa del cero por mas de dos errores estandar con muestra
suficiente. Y la promocion se puede perder: el estado se recalcula con todo lo
acumulado, asi que una regla que deje de funcionar vuelve al banquillo.
"""
from __future__ import annotations

from .. import aprendizaje, feeds, playbook
from ..config import UNIVERSE
from .base import Agent


class LearningAgent(Agent):
    name = "aprendizaje"
    role = "Comprueba que reglas funcionan de verdad y cuanto falta para saberlo"
    emoji = "A"

    def __init__(self, ctx):
        super().__init__(ctx)
        # La evidencia se acumula por barra diaria: mirarla mas a menudo no
        # trae informacion nueva, solo repite la misma vela.
        self.interval = max(ctx.cfg.scanner_seconds * 5, 300)
        self.memoria = aprendizaje.Memoria()
        self._ultima: dict[str, int] = {}      # ultimo timestamp ya contado

    def step(self):
        nuevas = 0
        for inst in UNIVERSE:
            try:
                c = feeds.get_candles(inst, timeframe="1d")
            except Exception:                            # noqa: BLE001,S112
                continue
            if len(c) < 260:
                continue
            pre = playbook.prepare(c)
            i = len(c) - 2                     # la ultima cerrada y su siguiente
            if self._ultima.get(inst.symbol) == c[-1]["t"]:
                continue                       # esa barra ya se conto
            self._ultima[inst.symbol] = c[-1]["t"]
            r = c[i + 1]["c"] / c[i]["c"] - 1 - 2 * aprendizaje.FEE
            for nombre, _, fn in playbook.CATALOG:
                if nombre == "comprar y esperar":
                    continue
                try:
                    if fn(pre, i):
                        self.memoria.observa(nombre, r)
                        nuevas += 1
                except Exception:                        # noqa: BLE001,S112
                    continue
        if nuevas:
            self.memoria.guardar()

        r = self.memoria.resumen(top=40)
        self.output = r
        self.say(f"{r['aprendidas']} aprendidas · {r['descartadas']} descartadas · "
                 f"{r['total'] - r['aprendidas'] - r['descartadas']} en juicio "
                 f"({r['progreso']:.0%} de avance) · +{nuevas} observaciones")

    # --- lo que el orquestador puede consultar ---
    def aprendidas(self) -> list[str]:
        return [n for n, reg in self.memoria.reglas.items()
                if reg.estado == "aprendido"]
