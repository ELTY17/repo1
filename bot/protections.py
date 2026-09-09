"""Protecciones de cartera.

Reimplementacion de los mecanismos de `freqtrade/plugins/protections`
(freqtrade/freqtrade, GPL-3.0) adaptada a este sistema: aqui no hay base de
datos ni objetos Trade, solo la lista de operaciones cerradas del broker, y el
tiempo se toma de la marca temporal de la vela (asi vale igual en vivo que en
backtest).

Equivalencias con el original:
  CooldownPeriod          -> cooldown
  StoplossGuard           -> stoploss_guard
  LowProfitPairs          -> low_profit
  MaxDrawdownProtection   -> max_drawdown
"""
from __future__ import annotations

from dataclasses import dataclass, field

HOUR = 3600
GLOBAL = "*"


@dataclass
class ProtectionConfig:
    # CooldownPeriod: tras cerrar en un activo, no se vuelve a entrar en el
    cooldown_h: float = 3.0
    # StoplossGuard: N stops en la ventana -> bloqueo global
    sl_guard_trades: int = 3
    sl_guard_lookback_h: float = 24.0
    sl_guard_lock_h: float = 12.0
    # LowProfitPairs: si el activo pierde dinero neto en la ventana, se bloquea
    low_profit_trades: int = 2
    low_profit_lookback_h: float = 48.0
    low_profit_required: float = 0.0
    low_profit_lock_h: float = 12.0
    # MaxDrawdownProtection: caida del equity en la ventana -> bloqueo global
    dd_trades: int = 3
    dd_lookback_h: float = 48.0
    dd_max: float = 0.08
    dd_lock_h: float = 24.0


@dataclass
class Lock:
    scope: str          # simbolo o "*"
    until: float        # unix seconds
    reason: str


class ProtectionManager:
    """Decide si se puede abrir posicion en un activo en un momento dado."""

    def __init__(self, cfg: ProtectionConfig | None = None):
        self.cfg = cfg or ProtectionConfig()
        self.locks: list[Lock] = []
        self.history: list[dict] = []      # operaciones cerradas
        self.events: list[dict] = []       # bloqueos aplicados, para el dashboard

    # --- registro ---
    def register_close(self, symbol: str, pnl: float, pnl_pct: float,
                       reason: str, ts: float, equity: float):
        self.history.append({"symbol": symbol, "pnl": pnl, "pnl_pct": pnl_pct,
                             "reason": reason, "ts": ts, "equity": equity})
        self._evaluate(ts)

    def _lock(self, scope: str, until: float, reason: str, ts: float):
        for l in self.locks:
            if l.scope == scope and l.until >= until:
                return                      # ya hay uno igual o mas largo
        self.locks = [l for l in self.locks if l.scope != scope]
        self.locks.append(Lock(scope, until, reason))
        self.events.append({"ts": ts, "scope": scope, "until": until, "reason": reason})

    # --- reglas ---
    def _evaluate(self, now: float):
        c = self.cfg
        last = self.history[-1]

        # 1) CooldownPeriod: siempre, tras cualquier cierre
        self._lock(last["symbol"], now + c.cooldown_h * HOUR,
                   f"enfriamiento {c.cooldown_h:g} h tras operar", now)

        # 2) StoplossGuard: demasiados stops seguidos -> parar del todo
        win = [t for t in self.history if t["ts"] >= now - c.sl_guard_lookback_h * HOUR]
        stops = [t for t in win if t["reason"].startswith("stop") and t["pnl"] < 0]
        if len(stops) >= c.sl_guard_trades:
            self._lock(GLOBAL, now + c.sl_guard_lock_h * HOUR,
                       f"{len(stops)} stops en {c.sl_guard_lookback_h:g} h", now)

        # 3) LowProfitPairs: el activo esta drenando dinero -> bloquear ese activo
        pw = [t for t in self.history
              if t["symbol"] == last["symbol"]
              and t["ts"] >= now - c.low_profit_lookback_h * HOUR]
        if len(pw) >= c.low_profit_trades:
            tot = sum(t["pnl_pct"] for t in pw)
            if tot < c.low_profit_required:
                self._lock(last["symbol"], now + c.low_profit_lock_h * HOUR,
                           f"{tot*100:+.1f}% acumulado en {len(pw)} operaciones", now)

        # 4) MaxDrawdownProtection: caida del equity en la ventana
        dw = [t for t in self.history if t["ts"] >= now - c.dd_lookback_h * HOUR]
        if len(dw) >= c.dd_trades:
            peak, worst = 0.0, 0.0
            for t in dw:
                peak = max(peak, t["equity"])
                if peak > 0:
                    worst = min(worst, t["equity"] / peak - 1)
            if -worst > c.dd_max:
                self._lock(GLOBAL, now + c.dd_lock_h * HOUR,
                           f"drawdown {worst*100:.1f}% en {c.dd_lookback_h:g} h", now)

    # --- consulta ---
    def check(self, symbol: str, now: float) -> tuple[bool, str]:
        """(permitido, motivo_si_no)."""
        self.locks = [l for l in self.locks if l.until > now]
        for l in self.locks:
            if l.scope in (GLOBAL, symbol):
                h = (l.until - now) / HOUR
                what = "todo el sistema" if l.scope == GLOBAL else l.scope
                return False, f"{what} bloqueado {h:.1f} h más — {l.reason}"
        return True, ""

    def active(self, now: float) -> list[dict]:
        self.locks = [l for l in self.locks if l.until > now]
        return [{"scope": l.scope, "reason": l.reason,
                 "hours_left": round((l.until - now) / HOUR, 1)} for l in self.locks]
