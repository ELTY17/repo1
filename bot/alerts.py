"""Avisos.

Un bot que falla en silencio es peor que no tener bot: sigues creyendo que algo
vigila el mercado cuando lleva horas muerto. Esto avisa de lo que importa.

Sin configurar, escribe en el log. Con ALERT_WEBHOOK definido, manda tambien un
POST con un JSON (vale para Discord, Slack o lo que sea). Nunca incluye claves.
"""
from __future__ import annotations

import json
import os
import ssl
import threading
import time
import urllib.request

LEVELS = {"info": 0, "warn": 1, "critical": 2}


class Alerts:
    def __init__(self, log=print, webhook: str | None = None, min_level: str = "warn"):
        self.log = log
        self.webhook = webhook if webhook is not None else os.environ.get("ALERT_WEBHOOK", "")
        self.min = LEVELS.get(min_level, 1)
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def send(self, level: str, key: str, msg: str, cooldown: float = 900):
        """`key` agrupa avisos repetidos para no inundar el canal."""
        with self._lock:
            now = time.time()
            if now - self._seen.get(key, 0) < cooldown:
                return
            self._seen[key] = now
        self.log(f"[{level.upper()}] {msg}")
        if not self.webhook or LEVELS.get(level, 0) < self.min:
            return
        try:
            body = json.dumps({"content": f"[{level.upper()}] {msg}"}).encode()
            req = urllib.request.Request(self.webhook, data=body,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=8, context=ssl.create_default_context())
        except Exception as e:                              # noqa: BLE001
            self.log(f"[alerts] no se pudo enviar el aviso: {type(e).__name__}")

    # --- comprobaciones que merecen un aviso ---
    def check(self, orch):
        cfg, b = orch.cfg, orch.broker
        prices = orch.prices()
        try:
            dd = b.drawdown(prices)
        except Exception:                                   # noqa: BLE001
            return
        limit = cfg.max_drawdown_stop
        if dd <= -limit:
            self.send("critical", "killswitch",
                      f"KILL SWITCH: drawdown {dd*100:.1f}% ha alcanzado el límite "
                      f"de {-limit*100:.0f}%. Operativa detenida.", cooldown=3600)
        elif dd <= -limit * 0.7:
            self.send("warn", "dd-near",
                      f"drawdown {dd*100:.1f}%, acercándose al límite "
                      f"de {-limit*100:.0f}%")

        # posiciones sin stop puesto en el exchange
        for sym, p in getattr(b, "positions", {}).items():
            if hasattr(p, "stop_txid") and not p.stop_txid:
                self.send("critical", f"nostop-{sym}",
                          f"{sym} está abierta SIN stop en el exchange. "
                          f"Si este proceso se cae, la posición queda sin protección.")

        # agentes caídos: uno que no late en 10 cadencias es un agente muerto
        now = time.time()
        for a in orch.agents:
            if a.last_run and now - a.last_run > a.interval * 10:
                self.send("warn", f"stale-{a.name}",
                          f"el agente '{a.name}' no responde desde hace "
                          f"{(now-a.last_run)/60:.0f} min")
            if a.errors and a.status == "error":
                self.send("warn", f"err-{a.name}",
                          f"el agente '{a.name}' lleva {a.errors} errores")
