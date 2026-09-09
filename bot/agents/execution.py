"""Agente 5 — EJECUCION.

Ejecuta las decisiones del orquestador contra el broker en papel y vigila
las posiciones abiertas (stop-loss, take-profit, trailing).
"""
from __future__ import annotations

from .base import Agent


class ExecutionAgent(Agent):
    name = "execution"
    role = "Ejecuta ordenes y vigila stops / take-profit"
    emoji = "E"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.interval = 10
        self.orders_sent = 0

    def step(self):
        """Vigilancia de posiciones abiertas: stop, objetivo y trailing."""
        b = self.ctx.broker
        prices = self.ctx.prices()
        closed = []
        for sym in list(b.positions):
            pos = b.positions.get(sym)
            if not pos:
                continue
            px = prices.get(sym)
            if not px:
                continue
            if px <= pos.stop:
                t = b.sell(sym, px, "stop-loss")
                closed.append((sym, "stop-loss", t))
            elif px >= pos.target:
                t = b.sell(sym, px, "take-profit")
                closed.append((sym, "take-profit", t))
            else:
                # trailing: una vez en +1R, el stop sube a break-even
                r = pos.entry - pos.stop
                if r > 0 and px >= pos.entry + r and pos.stop < pos.entry:
                    pos.stop = pos.entry
                    self.say(f"{sym} en +1R -> stop movido a break-even ${pos.entry:.2f}")

        for sym, why, t in closed:
            if t:
                self.say(f"CIERRE {sym} por {why} a ${t['price']:.2f} "
                         f"| PnL ${t['pnl']:+.2f}")

        b.mark(prices)
        self.output = {
            "orders_sent": self.orders_sent,
            "open_positions": [p.to_dict(prices.get(s, p.entry))
                               for s, p in b.positions.items()],
            "last_trades": list(reversed(b.trades[-12:])),
        }

    # --- llamado por el orquestador ---
    def execute_buy(self, symbol, price, plan, reason):
        t = self.ctx.broker.buy(symbol, plan["qty"], price,
                                plan["stop"], plan["target"], reason)
        if t:
            self.orders_sent += 1
            self.say(f"COMPRA {symbol} {plan['qty']:.6f} @ ${t['price']:.2f} "
                     f"(${plan['notional']:.2f}) | stop ${plan['stop']:.2f} "
                     f"| objetivo ${plan['target']:.2f}")
        else:
            self.say(f"orden de compra {symbol} rechazada por el broker")
        return t

    def execute_sell(self, symbol, price, reason):
        t = self.ctx.broker.sell(symbol, price, reason)
        if t:
            self.orders_sent += 1
            self.say(f"VENTA {symbol} @ ${t['price']:.2f} | "
                     f"PnL ${t['pnl']:+.2f} | motivo: {reason}")
        return t
