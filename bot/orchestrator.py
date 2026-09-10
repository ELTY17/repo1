"""Orquestador: arranca los 5 agentes, agrega sus votos y decide.

Cada agente corre en su propio hilo con su propia cadencia. El orquestador
combina noticias + escaner + tecnico en un score compuesto, pide permiso al
agente de riesgo y, si lo aprueba, manda la orden al agente de ejecucion.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from . import feeds
from .agents import ExecutionAgent, NewsAgent, RiskAgent, ScannerAgent, TechnicalAgent
from .broker import PaperBroker
from .config import CONFIG, UNIVERSE


class Orchestrator:
    def __init__(self, cfg=CONFIG):
        self.cfg = cfg
        self.bar_seconds = 3600          # el sistema en vivo trabaja en velas de 1 h
        self.broker = PaperBroker(cfg.starting_cash, cfg.fee_rate, cfg.slippage_rate)
        self.started_at = time.time()
        self.cycles = 0
        self.events = deque(maxlen=300)
        self.debug_log = deque(maxlen=50)
        self.decisions: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self.news = NewsAgent(self)
        self.scanner = ScannerAgent(self)
        self.technical = TechnicalAgent(self)
        self.risk = RiskAgent(self)
        self.execution = ExecutionAgent(self)
        self.agents = [self.news, self.scanner, self.technical, self.risk, self.execution]

    # --- utilidades compartidas ---
    def feed_event(self, entry):
        with self._lock:
            self.events.appendleft(entry)

    def debug(self, msg):
        self.debug_log.appendleft(msg)

    def note_close(self, trade):
        """Avisa a las protecciones de que se ha cerrado una operacion."""
        if not trade or trade.get("side") != "SELL":
            return
        self.risk.protections.register_close(
            trade["symbol"], trade["pnl"], trade.get("pnl_pct", 0.0),
            trade["reason"], trade["t"], self.broker.equity(self.prices()))

    def prices(self) -> dict[str, float]:
        return {i.symbol: feeds.last_price(i) for i in UNIVERSE}

    def log(self, msg):
        self.feed_event({"t": int(time.time()), "agent": "orchestrator", "msg": msg})

    # --- ciclo de decision ---
    def composite(self) -> dict[str, dict]:
        w = self.cfg.weights
        news = (self.news.output or {}).get("sentiment", {})
        scan = (self.scanner.output or {}).get("scores", {})
        tech = (self.technical.output or {}).get("scores", {})
        out = {}
        for inst in UNIVERSE:
            s = inst.symbol
            votes = {
                "news": news.get(s, 0.0),
                "scanner": scan.get(s, 0.0),
                "technical": tech.get(s, 0.0),
            }
            score = sum(votes[k] * w[k] for k in w)
            # consenso: cuantos agentes apuntan en la misma direccion
            signs = [1 if votes[k] > 0.05 else (-1 if votes[k] < -0.05 else 0) for k in w]
            agree = abs(sum(signs)) / 3.0
            out[s] = {"symbol": s, "votes": votes, "score": round(score, 3),
                      "consensus": round(agree, 2)}
        return out

    def decide(self):
        cfg = self.cfg
        comp = self.composite()
        prices = self.prices()
        readings = (self.technical.output or {}).get("readings", {})
        decisions = []

        # 1) salidas por deterioro de la senal
        for sym in list(self.broker.positions):
            sc = comp.get(sym, {}).get("score", 0.0)
            if sc <= cfg.exit_threshold:
                self.execution.execute_sell(sym, prices[sym],
                                            f"senal debilitada ({sc:+.2f})")
                decisions.append({"symbol": sym, "action": "SELL", "score": sc,
                                  "note": "score por debajo del umbral de salida"})

        # 2) entradas, mejores candidatos primero
        ranked = sorted(comp.values(), key=lambda c: -c["score"])
        for c in ranked:
            sym = c["symbol"]
            if c["score"] < cfg.buy_threshold:
                decisions.append({"symbol": sym, "action": "HOLD", "score": c["score"],
                                  "note": f"score < umbral {cfg.buy_threshold}"})
                continue
            atr_v = (readings.get(sym) or {}).get("atr")
            plan = self.risk.approve(sym, prices[sym], atr_v)
            if not plan["ok"]:
                decisions.append({"symbol": sym, "action": "VETO", "score": c["score"],
                                  "note": f"riesgo: {plan['reason']}"})
                continue
            reason = (f"score {c['score']:+.2f} (news {c['votes']['news']:+.2f}, "
                      f"scan {c['votes']['scanner']:+.2f}, "
                      f"tech {c['votes']['technical']:+.2f})")
            self.execution.execute_buy(sym, prices[sym], plan, reason)
            decisions.append({"symbol": sym, "action": "BUY", "score": c["score"],
                              "note": reason})

        self.decisions = decisions
        self.cycles += 1
        return decisions

    # --- arranque ---
    def start(self):
        self.log(f"arrancando en modo {self.cfg.mode.upper()} con "
                 f"${self.cfg.starting_cash:.2f} simulados")
        for a in self.agents:
            a.start()
        threading.Thread(target=self._loop, name="orchestrator", daemon=True).start()

    def _loop(self):
        time.sleep(3)                     # deja que los agentes hagan su primera pasada
        while not self._stop.is_set():
            try:
                self.decide()
            except Exception as e:                       # noqa: BLE001
                self.log(f"ERROR en ciclo de decision: {type(e).__name__}: {e}")
            self._stop.wait(self.cfg.tick_seconds)

    def stop(self):
        self._stop.set()
        for a in self.agents:
            a.stop()

    # --- vista para el dashboard ---
    def state(self) -> dict:
        prices = self.prices()
        return {
            "ts": int(time.time()),
            "mode": self.cfg.mode,
            "uptime": int(time.time() - self.started_at),
            "cycles": self.cycles,
            "config": {
                "starting_cash": self.cfg.starting_cash,
                "risk_per_trade": self.cfg.risk_per_trade,
                "max_positions": self.cfg.max_positions,
                "max_drawdown_stop": self.cfg.max_drawdown_stop,
                "buy_threshold": self.cfg.buy_threshold,
                "weights": self.cfg.weights,
            },
            "agents": [a.snapshot() for a in self.agents],
            "market": feeds.snapshot(),
            "composite": list(self.composite().values()),
            "decisions": self.decisions,
            "portfolio": self.broker.stats(prices),
            "positions": [p.to_dict(prices.get(s, p.entry))
                          for s, p in self.broker.positions.items()],
            "trades": list(reversed(self.broker.trades))[:30],
            "equity_curve": self.broker.equity_curve[-300:],
            "events": list(self.events)[:60],
            "headlines": (self.news.output or {}).get("headlines", []),
            "halted": self.risk.halted,
            "halt_reason": self.risk.halt_reason,
            "locks": self.risk.protections.active(time.time()),
            "readings": (self.technical.output or {}).get("readings", {}),
            "live": getattr(self.broker, "validate", None) is not None,
        }
