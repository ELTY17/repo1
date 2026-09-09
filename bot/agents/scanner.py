"""Agente 2 — ESCANER DE MERCADO.

Recorre todo el universo (cripto + indices) y lo ordena por fuerza relativa:
momentum multi-horizonte, volumen anormal y volatilidad.
"""
from __future__ import annotations

from ..config import UNIVERSE
from .. import feeds, signals
from .base import Agent


class ScannerAgent(Agent):
    name = "scanner"
    role = "Escanea el universo y rankea por fuerza relativa"
    emoji = "S"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.interval = ctx.cfg.scanner_seconds

    def step(self):
        rows = []
        for inst in UNIVERSE:
            candles = feeds.get_candles(inst)
            if len(candles) < 60:
                continue
            score, d = signals.scanner_score(candles)
            rows.append({"symbol": inst.symbol, "label": inst.label, "kind": inst.kind,
                         "price": candles[-1]["c"], "score": d["score"],
                         "m6": d["m6"], "m24": d["m24"], "m72": d["m72"],
                         "vol_z": d["vol_z"], "realized_vol": d["realized_vol"],
                         "source": feeds.health.get(inst.symbol, "?")})

        rows.sort(key=lambda r: -r["score"])
        for i, r in enumerate(rows):
            r["rank"] = i + 1

        self.output = {
            "ranking": rows,
            "scores": {r["symbol"]: r["score"] for r in rows},
            "leader": rows[0]["symbol"] if rows else None,
        }
        if rows:
            top = ", ".join(f"{r['symbol']} {r['score']:+.2f}" for r in rows[:3])
            self.say(f"universo escaneado ({len(rows)}) | top: {top}")
