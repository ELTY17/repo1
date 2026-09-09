"""Agente 3 — ANALISIS TECNICO.

RSI, cruce de EMAs, MACD, posicion respecto a Bollinger y ATR (para el stop).
Produce un score direccional por instrumento en [-1, 1].
"""
from __future__ import annotations

from ..config import UNIVERSE
from .. import feeds, signals
from .base import Agent


class TechnicalAgent(Agent):
    name = "technical"
    role = "Indicadores tecnicos y niveles de entrada/stop"
    emoji = "T"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.interval = ctx.cfg.technical_seconds

    def step(self):
        readings = {}
        for inst in UNIVERSE:
            candles = feeds.get_candles(inst)
            if len(candles) < 60:
                continue
            score, detail = signals.technical_score(candles)
            detail["symbol"] = inst.symbol
            detail["price"] = candles[-1]["c"]
            readings[inst.symbol] = detail

        self.output = {
            "readings": readings,
            "scores": {k: v["score"] for k, v in readings.items()},
        }
        if readings:
            best = max(readings.values(), key=lambda x: x["score"])
            blocked = [v["symbol"] for v in readings.values() if v.get("vetoed_by")]
            msg = (f"{len(readings)} activos | mejor {best['symbol']} "
                   f"{best['score']:+.2f} (RSI {best['rsi']}, ADX {best['adx']})")
            if blocked:
                msg += f" | fuera por régimen bajista: {', '.join(blocked)}"
            self.say(msg)
