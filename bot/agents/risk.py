"""Agente 4 — RIESGO.

Tiene poder de veto sobre cualquier operacion y es quien decide el tamano.
Reglas duras: riesgo fijo por trade, tope de exposicion, limite de posiciones,
tope de concentracion por clase de activo y kill switch por drawdown.
"""
from __future__ import annotations

import time

from .. import feeds
from ..config import UNIVERSE
from ..limits import check as check_min
from ..protections import ProtectionManager
from .base import Agent

_INST = {i.symbol: i for i in UNIVERSE}


class RiskAgent(Agent):
    name = "risk"
    role = "Dimensiona posiciones, pone stops y puede vetar (kill switch)"
    emoji = "R"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.interval = 15
        self.halted = False
        self.halt_reason = ""
        self.protections = ProtectionManager()

    # --- evaluacion periodica del estado de la cuenta ---
    def step(self):
        prices = self.ctx.prices()
        b = self.ctx.broker
        dd = b.drawdown(prices)
        eq = b.equity(prices)

        if not self.halted and dd <= -self.ctx.cfg.max_drawdown_stop:
            self.halted = True
            self.halt_reason = (f"drawdown {dd*100:.1f}% supera el limite "
                                f"{-self.ctx.cfg.max_drawdown_stop*100:.0f}%")
            self.say(f"KILL SWITCH ACTIVADO: {self.halt_reason}. "
                     f"Cerrando todo y dejando de abrir.")
            for sym in list(b.positions):
                b.sell(sym, prices.get(sym, b.positions[sym].entry), "kill switch")

        exposure = sum(p.market_value(prices.get(s, p.entry))
                       for s, p in b.positions.items())
        self.output = {
            "halted": self.halted,
            "locks": self.protections.active(time.time()),
            "halt_reason": self.halt_reason,
            "equity": eq,
            "drawdown": dd,
            "max_drawdown_stop": self.ctx.cfg.max_drawdown_stop,
            "exposure": exposure,
            "exposure_pct": (exposure / eq) if eq else 0.0,
            "open_positions": len(b.positions),
            "max_positions": self.ctx.cfg.max_positions,
            "risk_per_trade": self.ctx.cfg.risk_per_trade,
            "risk_budget_usd": eq * self.ctx.cfg.risk_per_trade,
        }
        if self.runs % 8 == 0 and not self.halted:
            self.say(f"equity ${eq:.2f} | DD {dd*100:+.1f}% | "
                     f"exposicion {self.output['exposure_pct']*100:.0f}% | "
                     f"{len(b.positions)}/{self.ctx.cfg.max_positions} posiciones")

    # --- API usada por el orquestador antes de cada compra ---
    def approve(self, symbol: str, price: float, atr_value: float | None) -> dict:
        cfg = self.ctx.cfg
        b = self.ctx.broker
        prices = self.ctx.prices()
        eq = b.equity(prices)

        if self.halted:
            return {"ok": False, "reason": f"sistema detenido ({self.halt_reason})"}
        if symbol in b.positions:
            return {"ok": False, "reason": "ya hay posicion abierta"}
        if len(b.positions) >= cfg.max_positions:
            return {"ok": False, "reason": f"limite de {cfg.max_positions} posiciones"}
        if price <= 0:
            return {"ok": False, "reason": "precio invalido"}

        # protecciones de cartera (cooldown, guardia de stops, drawdown, activo en perdidas)
        if "prot" in self.ctx.cfg.features:
            ok, why = self.protections.check(symbol, time.time())
            if not ok:
                return {"ok": False, "reason": why}

        # Stop por ATR; si no hay ATR, 3% por defecto
        stop_dist = (atr_value * cfg.stop_atr_mult) if atr_value else price * 0.03
        stop_dist = max(stop_dist, price * 0.005)          # nunca un stop absurdo
        stop = price - stop_dist
        target = price + stop_dist * cfg.take_profit_r

        risk_usd = eq * cfg.risk_per_trade
        qty = risk_usd / stop_dist

        # Tope por peso maximo en un solo activo
        max_notional = min(eq * cfg.max_position_weight, b.cash * 0.98)
        if qty * price > max_notional:
            qty = max_notional / price

        notional = qty * price
        if notional < 1.0:
            return {"ok": False, "reason": f"tamano demasiado pequeno (${notional:.2f})"}

        # el exchange rechaza las ordenes por debajo de su minimo
        ok, why = check_min(_INST[symbol], price, notional)
        if not ok:
            return {"ok": False, "reason": why}
        if notional + notional * cfg.fee_rate > b.cash:
            return {"ok": False, "reason": "efectivo insuficiente"}

        # Concentracion por clase de activo (max 2 posiciones del mismo tipo)
        kind = _INST[symbol].kind
        same = sum(1 for s in b.positions if _INST[s].kind == kind)
        if same >= 2:
            return {"ok": False, "reason": f"ya hay {same} posiciones en {kind}"}

        return {"ok": True, "qty": qty, "stop": stop, "target": target,
                "risk_usd": risk_usd, "notional": notional,
                "stop_pct": stop_dist / price, "atr": atr_value}
