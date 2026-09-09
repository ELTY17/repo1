"""Agente 2 — ESCANER DE MERCADO.

Recorre todo el universo (cripto + indices) y lo ordena por fuerza relativa:
momentum multi-horizonte, volumen anormal y volatilidad.
"""
from __future__ import annotations

from ..config import UNIVERSE
from .. import feeds
from ..indicators import clamp, pct_change, stdev, zscore
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
            closes = [c["c"] for c in candles]
            vols = [c["v"] for c in candles]

            m6 = pct_change(closes, 6) or 0.0      # ~6h
            m24 = pct_change(closes, 24) or 0.0    # ~1d
            m72 = pct_change(closes, 72) or 0.0    # ~3d
            vol_z = zscore(vols[-1], vols[-48:]) if len(vols) >= 48 else 0.0
            realized_vol = stdev([closes[i] / closes[i - 1] - 1
                                  for i in range(-48, 0)]) if len(closes) > 49 else 0.0

            # momentum normalizado por volatilidad (evita premiar solo al mas volatil)
            denom = max(realized_vol, 1e-4)
            momentum = (0.5 * m6 + 0.3 * m24 + 0.2 * m72) / (denom * 8)
            score = clamp(0.75 * clamp(momentum) + 0.25 * clamp(vol_z / 3.0))

            rows.append({
                "symbol": inst.symbol,
                "label": inst.label,
                "kind": inst.kind,
                "price": closes[-1],
                "m6": m6, "m24": m24, "m72": m72,
                "vol_z": round(vol_z, 2),
                "realized_vol": realized_vol,
                "score": round(score, 3),
                "source": feeds.health.get(inst.symbol, "?"),
            })

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
