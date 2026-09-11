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
from .agents import (CorrelationAgent, ExecutionAgent, LearningAgent, NewsAgent,
                     OracleAgent, RiskAgent, ScannerAgent, TechnicalAgent)
from .broker import PaperBroker
from .config import CONFIG, UNIVERSE


class Orchestrator:
    def __init__(self, cfg=CONFIG):
        self.cfg = cfg
        self.bar_seconds = 3600          # el sistema en vivo trabaja en velas de 1 h
        self.broker = PaperBroker(cfg.starting_cash, cfg.fee_rate, cfg.slippage_rate)
        self.started_at = time.time()
        self.cycles = 0
        # El bot arranca ENCENDIDO pero se puede parar a mano; el bloqueo es
        # otra cosa y solo lo levanta una persona.
        self.activo = True
        self.bloqueado = False
        self.bloqueo_motivo = ""
        self.events = deque(maxlen=300)
        self.debug_log = deque(maxlen=50)
        self.decisions: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self.news = NewsAgent(self)
        self.scanner = ScannerAgent(self)
        self.technical = TechnicalAgent(self)
        self.correlation = CorrelationAgent(self)
        self.learning = LearningAgent(self)
        self.risk = RiskAgent(self)
        self.execution = ExecutionAgent(self)
        # El octavo llega el ultimo a proposito: habla despues de riesgo y solo
        # sobre lo que riesgo ya ha aprobado.
        self.oraculo = OracleAgent(self)
        self.agents = [self.news, self.scanner, self.technical,
                       self.correlation, self.learning, self.risk,
                       self.execution, self.oraculo]

    # --- utilidades compartidas ---
    def feed_event(self, entry):
        with self._lock:
            self.events.appendleft(entry)

    def debug(self, msg):
        self.debug_log.appendleft(msg)

    def note_close(self, trade):
        """Avisa a las protecciones de que se ha cerrado una operacion."""
        if not trade or trade.get("side") not in ("SELL", "COVER"):
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
            # El ultimo filtro: Claude, y solo sobre lo que ya esta aprobado.
            # Sin clave o sin presupuesto devuelve "sin opinion" y esto es un
            # no-op exacto, igual que antes de existir.
            voz = self.oraculo.opina(sym, c, prices[sym], plan,
                                     readings.get(sym))
            if not voz["ok"]:
                decisions.append({"symbol": sym, "action": "VETO",
                                  "score": c["score"],
                                  "note": f"oraculo: {voz['motivo']}"})
                continue
            reason = (f"score {c['score']:+.2f} (news {c['votes']['news']:+.2f}, "
                      f"scan {c['votes']['scanner']:+.2f}, "
                      f"tech {c['votes']['technical']:+.2f})")
            if voz["fuente"] == "claude":
                reason += f" · oraculo {voz['confianza']:.0%}: {voz['motivo']}"
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

    # --- interruptor y bloqueo -------------------------------------------
    def activar(self, on: bool):
        """Encender o parar el bot a mano. Parar no cierra nada: solo deja de
        abrir. Cerrar posiciones a destiempo es una decision, no una pausa.

        Con el candado echado, encender no hace nada: hay que soltarlo antes.
        """
        if on and self.bloqueado:
            self.log("no se puede activar: hay un bloqueo sin revisar")
            return False
        self.activo = bool(on)
        self.log("bot ACTIVADO" if self.activo else "bot EN PAUSA (a mano)")
        return self.activo

    def bloquear(self, motivo: str):
        """Candado duro. Cuando pasa algo que el sistema no sabe interpretar, no
        improvisa: se para del todo y hace falta una mano humana para soltarlo.

        Un bot que sigue operando con un fallo que no entiende es peor que un
        bot parado. Esto no se levanta solo ni con el boton de activar.
        """
        if self.bloqueado:
            return
        self.bloqueado = True
        self.bloqueo_motivo = motivo
        self.activo = False
        self.log(f"BLOQUEO TOTAL: {motivo}. No se abre nada mas hasta revisarlo.")

    def desbloquear(self):
        """Levantar el candado NO reanuda: deja el bot en pausa a proposito.

        Quien lo suelta tiene que decidir aparte que vuelva a operar. Si una
        sola accion hiciera las dos cosas, se reanudaria sin querer.
        """
        self.bloqueado = False
        self.bloqueo_motivo = ""
        self.activo = False
        self.log("bloqueo levantado a mano; el bot queda EN PAUSA")

    def _loop(self):
        time.sleep(3)                     # deja que los agentes hagan su primera pasada
        fallos = 0
        while not self._stop.is_set():
            try:
                self.salud()
                if self.activo and not self.bloqueado:
                    self.decide()
                    fallos = 0
            except Exception as e:                       # noqa: BLE001
                fallos += 1
                self.log(f"ERROR en ciclo de decision: {type(e).__name__}: {e}")
                # Un fallo puede ser la red. Tres seguidos es que algo va mal de
                # verdad y nadie sabe el que: se echa el candado.
                if fallos >= 3:
                    self.bloquear(f"3 ciclos seguidos fallando ({type(e).__name__})")
            self._stop.wait(self.cfg.tick_seconds)

    def stop(self):
        self._stop.set()
        for a in self.agents:
            a.stop()

    # --- vista para el dashboard ---
    def salud(self):
        """Vigila a los agentes. Si uno se atasca o revienta, candado."""
        for a in self.agents:
            if a.errors >= 5:
                self.bloquear(f"el agente '{a.name}' lleva {a.errors} errores")
                return
            # Un agente que lleva diez cadencias sin correr esta colgado.
            if a.runs and a.last_run and time.time() - a.last_run > a.interval * 10:
                self.bloquear(f"el agente '{a.name}' no responde")
                return

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
            "activo": self.activo,
            "bloqueado": self.bloqueado,
            "bloqueo_motivo": self.bloqueo_motivo,
            "locks": self.risk.protections.active(time.time()),
            "readings": (self.technical.output or {}).get("readings", {}),
            "live": getattr(self.broker, "validate", None) is not None,
        }
