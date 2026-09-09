"""Bróker en papel: contabilidad real, dinero simulado.

`LiveBroker` existe solo como interfaz y lanza NotImplementedError a proposito.
Nada en este repo puede mover dinero real.
"""
from __future__ import annotations

import threading
import time
import uuid


class Position:
    def __init__(self, symbol, qty, entry, stop, target, opened_at):
        self.symbol = symbol
        self.qty = qty
        self.entry = entry
        self.stop = stop
        self.target = target
        self.opened_at = opened_at

    def market_value(self, price):
        return self.qty * price

    def unrealized(self, price):
        return (price - self.entry) * self.qty

    def to_dict(self, price):
        cost = self.entry * self.qty
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "entry": self.entry,
            "price": price,
            "stop": self.stop,
            "target": self.target,
            "value": self.market_value(price),
            "pnl": self.unrealized(price),
            "pnl_pct": (self.unrealized(price) / cost) if cost else 0.0,
            "opened_at": self.opened_at,
        }


class PaperBroker:
    def __init__(self, cash: float, fee_rate: float, slippage_rate: float):
        self.starting_cash = cash
        self.cash = cash
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.positions: dict[str, Position] = {}
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.peak_equity = cash
        self.fees_paid = 0.0
        self.lock = threading.RLock()

    # --- contabilidad ---
    def equity(self, prices: dict[str, float]) -> float:
        with self.lock:
            v = self.cash
            for s, p in self.positions.items():
                v += p.market_value(prices.get(s, p.entry))
            return v

    def mark(self, prices: dict[str, float]):
        eq = self.equity(prices)
        with self.lock:
            self.peak_equity = max(self.peak_equity, eq)
            self.equity_curve.append({"t": int(time.time()), "equity": eq})
            if len(self.equity_curve) > 2000:
                self.equity_curve = self.equity_curve[-2000:]
        return eq

    def drawdown(self, prices) -> float:
        eq = self.equity(prices)
        if self.peak_equity <= 0:
            return 0.0
        return (eq / self.peak_equity) - 1.0

    # --- ordenes ---
    def buy(self, symbol, qty, price, stop, target, reason=""):
        with self.lock:
            fill = price * (1 + self.slippage_rate)
            cost = fill * qty
            fee = cost * self.fee_rate
            if qty <= 0 or cost + fee > self.cash + 1e-9:
                return None
            self.cash -= cost + fee
            self.fees_paid += fee
            self.positions[symbol] = Position(symbol, qty, fill, stop, target, int(time.time()))
            t = {"id": uuid.uuid4().hex[:8], "t": int(time.time()), "side": "BUY",
                 "symbol": symbol, "qty": qty, "price": fill, "fee": fee,
                 "pnl": None, "reason": reason}
            self.trades.append(t)
            return t

    def sell(self, symbol, price, reason=""):
        with self.lock:
            pos = self.positions.pop(symbol, None)
            if not pos:
                return None
            fill = price * (1 - self.slippage_rate)
            proceeds = fill * pos.qty
            fee = proceeds * self.fee_rate
            self.cash += proceeds - fee
            self.fees_paid += fee
            pnl = (fill - pos.entry) * pos.qty - fee
            t = {"id": uuid.uuid4().hex[:8], "t": int(time.time()), "side": "SELL",
                 "symbol": symbol, "qty": pos.qty, "price": fill, "fee": fee,
                 "pnl": pnl, "reason": reason}
            self.trades.append(t)
            return t

    def stats(self, prices):
        with self.lock:
            closed = [t for t in self.trades if t["side"] == "SELL"]
            wins = [t for t in closed if t["pnl"] > 0]
            losses = [t for t in closed if t["pnl"] <= 0]
            gross_win = sum(t["pnl"] for t in wins)
            gross_loss = -sum(t["pnl"] for t in losses)
            eq = self.equity(prices)
            return {
                "equity": eq,
                "cash": self.cash,
                "starting_cash": self.starting_cash,
                "total_return": (eq / self.starting_cash - 1) if self.starting_cash else 0.0,
                "realized_pnl": sum(t["pnl"] for t in closed),
                "unrealized_pnl": sum(
                    p.unrealized(prices.get(s, p.entry)) for s, p in self.positions.items()),
                "drawdown": self.drawdown(prices),
                "peak_equity": self.peak_equity,
                "trades_closed": len(closed),
                "wins": len(wins),
                "losses": len(losses),
                "win_rate": (len(wins) / len(closed)) if closed else 0.0,
                "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
                "fees_paid": self.fees_paid,
            }


class LiveBroker:
    """Interfaz para un bróker real. Deliberadamente NO implementada."""

    def __init__(self, *a, **kw):
        raise NotImplementedError(
            "El modo 'live' no esta implementado. Este sistema solo opera en papel. "
            "Conectar dinero real requiere tus propias claves, tu propia auditoria "
            "del codigo y asumir tu el riesgo de perderlo todo."
        )
