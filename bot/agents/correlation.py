"""Agente 6 — CORRELACION.

Los otros cinco miran cada activo por separado. Este mira lo que tienen en
comun, que es lo que nadie estaba mirando: con diecisiete criptos en el
universo, tener cuatro posiciones abiertas puede ser la misma apuesta cuatro
veces con nombres distintos.

No vota direccion. Mide la correlacion de los rendimientos diarios y le dice a
Riesgo cuando un candidato es un duplicado de algo que ya esta abierto. Es el
unico agente que no opina de si algo va a subir: opina de si ya lo tienes.
"""
from __future__ import annotations

from .. import correlacion, feeds
from ..config import UNIVERSE
from .base import Agent


class CorrelationAgent(Agent):
    name = "correlacion"
    role = "Mide si dos posiciones son en realidad la misma apuesta"
    emoji = "C"

    def __init__(self, ctx):
        super().__init__(ctx)
        # La correlacion se mueve despacio: no hace falta recalcularla a menudo.
        self.interval = max(ctx.cfg.scanner_seconds * 4, 240)
        self.velas: dict[str, list] = {}

    def step(self):
        self.velas = {}
        for inst in UNIVERSE:
            try:
                c = feeds.get_candles(inst, timeframe="1d")
            except Exception:                            # noqa: BLE001,S112
                continue
            if len(c) >= correlacion.VENTANA + 1:
                self.velas[inst.symbol] = c
        if len(self.velas) < 2:
            self.say("sin suficientes series para correlacionar")
            self.output = {"pares": {}, "media": None, "duplicados": []}
            return

        m = correlacion.matriz(self.velas)
        media = sum(m.values()) / len(m)
        altos = sorted((v, k) for k, v in m.items() if v > correlacion.UMBRAL)

        # Lo que de verdad importa: la cartera de ahora mismo.
        abiertas = list(getattr(self.ctx.broker, "positions", {}))
        avisos = []
        for i, a in enumerate(abiertas):
            for b in abiertas[i + 1:]:
                c = m.get(f"{a}|{b}") or m.get(f"{b}|{a}")
                if c is not None and c > correlacion.UMBRAL:
                    avisos.append({"a": a, "b": b, "c": c})

        self.output = {
            "pares": m, "media": round(media, 3),
            "umbral": correlacion.UMBRAL, "ventana": correlacion.VENTANA,
            "altos": [{"par": k, "c": v} for v, k in altos[::-1][:8]],
            "duplicados": avisos,
            "n": len(self.velas),
        }
        if avisos:
            peor = max(avisos, key=lambda x: x["c"])
            self.say(f"{peor['a']} y {peor['b']} van a la vez "
                     f"({peor['c']:.2f}): no es diversificar")
        else:
            self.say(f"{len(self.velas)} activos · correlacion media "
                     f"{media:.2f} · {len(altos)} pares por encima de "
                     f"{correlacion.UMBRAL}")

    # --- lo que Riesgo consulta antes de aprobar una entrada ---
    def permite(self, symbol: str, abiertas: list[str]):
        """(ok, motivo). Sin datos aun, no bloquea: el silencio no es un veto."""
        if symbol not in self.velas or not abiertas:
            return True, ""
        tengo = {s: self.velas[s] for s in abiertas if s in self.velas}
        if not tengo:
            return True, ""
        return correlacion.permite(self.velas[symbol], tengo)
