"""Agente 3 — ANALISIS TECNICO.

RSI, cruce de EMAs, MACD, posicion respecto a Bollinger y ATR (para el stop).
Produce un score direccional por instrumento en [-1, 1].
"""
from __future__ import annotations

from ..config import UNIVERSE
from .. import feeds
from ..indicators import atr, clamp, ema, macd, rsi, sma, stdev
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
            closes = [c["c"] for c in candles]
            price = closes[-1]

            r = rsi(closes, 14)
            e_fast, e_slow = ema(closes, 12), ema(closes, 26)
            m, sig, hist = macd(closes)
            a = atr(candles, 14)
            mid = sma(closes, 20)
            sd = stdev(closes[-20:])

            parts = {}
            # RSI: premia zona 40-65 (impulso sano), penaliza sobrecompra extrema
            if r is not None:
                if r < 30:
                    parts["rsi"] = 0.5          # sobreventa -> rebote potencial
                elif r > 75:
                    parts["rsi"] = -0.8         # sobrecompra -> mal sitio para entrar
                else:
                    parts["rsi"] = clamp((r - 50) / 25.0) * 0.6
            # Tendencia: EMA rapida sobre lenta
            if e_fast and e_slow:
                parts["trend"] = clamp((e_fast / e_slow - 1) * 40)
            # MACD: histograma normalizado por precio
            if hist is not None:
                parts["macd"] = clamp((hist / price) * 300)
            # Bollinger: penaliza comprar en la banda alta
            if mid and sd > 0:
                parts["bollinger"] = clamp(-((price - mid) / (2 * sd)) * 0.5)

            score = clamp(sum(parts.values()) / max(len(parts), 1))
            readings[inst.symbol] = {
                "symbol": inst.symbol,
                "price": price,
                "rsi": round(r, 1) if r is not None else None,
                "ema12": e_fast, "ema26": e_slow,
                "macd_hist": hist,
                "atr": a,
                "atr_pct": (a / price) if a else None,
                "parts": {k: round(v, 3) for k, v in parts.items()},
                "score": round(score, 3),
            }

        self.output = {
            "readings": readings,
            "scores": {k: v["score"] for k, v in readings.items()},
        }
        if readings:
            best = max(readings.values(), key=lambda x: x["score"])
            self.say(f"{len(readings)} activos analizados | "
                     f"mejor setup: {best['symbol']} score {best['score']:+.2f} "
                     f"(RSI {best['rsi']})")
