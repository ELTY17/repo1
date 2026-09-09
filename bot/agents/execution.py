"""Agente 5 — EJECUCION.

Ejecuta las decisiones del orquestador contra el broker en papel y vigila
las posiciones abiertas (stop-loss, take-profit, trailing).
"""
from __future__ import annotations

import time

from ..exits import roi_reached, roi_target, trailing_stop
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
        """Vigilancia de posiciones abiertas: stop, ROI que decae y trailing."""
        b = self.ctx.broker
        feats = set(self.ctx.cfg.features)
        prices = self.ctx.prices()
        now = time.time()
        closed = []
        for sym in list(b.positions):
            pos = b.positions.get(sym)
            if not pos:
                continue
            px = prices.get(sym)
            if not px:
                continue

            pos.high_water = max(pos.high_water, px)
            bars = pos.bars_open(now, self.ctx.bar_seconds)
            profit = pos.profit_ratio(px)

            if px <= pos.stop:
                t = b.sell(sym, px, "stop-loss")
                closed.append((sym, "stop-loss", t))
                continue
            if "roi" in feats and roi_reached(profit, bars, pos.atr_pct):
                tgt = roi_target(bars, pos.atr_pct)
                t = b.sell(sym, px, f"objetivo {tgt*100:.1f}%")
                closed.append((sym, "objetivo", t))
                continue

            new_stop = (trailing_stop(pos.entry, pos.high_water, pos.stop, pos.atr)
                        if "trail" in feats else pos.stop)
            if new_stop > pos.stop:
                pos.stop = new_stop
                self.say(f"{sym} +{profit*100:.1f}% · stop sube a ${new_stop:.2f} (trailing)")

        for sym, why, t in closed:
            if t:
                self.ctx.note_close(t)
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
                                plan["stop"], plan["target"], reason,
                                atr=plan.get("atr"))
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
            self.ctx.note_close(t)
            self.orders_sent += 1
            self.say(f"VENTA {symbol} @ ${t['price']:.2f} | "
                     f"PnL ${t['pnl']:+.2f} | motivo: {reason}")
        return t
