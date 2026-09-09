"""Clase base de agente: hilo propio, cadencia propia, estado observable."""
from __future__ import annotations

import threading
import time
import traceback
from collections import deque


class Agent:
    name = "agent"
    role = ""
    emoji = "*"
    interval = 30

    def __init__(self, ctx):
        self.ctx = ctx                    # contexto compartido (Orchestrator)
        self.status = "idle"              # idle | working | error | stopped
        self.runs = 0
        self.errors = 0
        self.last_run = 0.0
        self.last_ms = 0.0
        self.output: dict = {}
        self.log = deque(maxlen=40)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # --- ciclo de vida ---
    def start(self):
        self._thread = threading.Thread(target=self._loop, name=self.name, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.status = "stopped"

    def _loop(self):
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.status = "working"
                self.step()
                self.status = "idle"
                self.runs += 1
            except Exception as e:                       # noqa: BLE001
                self.status = "error"
                self.errors += 1
                self.say(f"ERROR: {type(e).__name__}: {e}")
                self.ctx.debug(traceback.format_exc())
            self.last_ms = (time.time() - t0) * 1000
            self.last_run = time.time()
            self._stop.wait(self.interval)

    # --- utilidades ---
    def say(self, msg: str):
        entry = {"t": int(time.time()), "agent": self.name, "msg": msg}
        self.log.appendleft(entry)
        self.ctx.feed_event(entry)

    def step(self):
        raise NotImplementedError

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "emoji": self.emoji,
            "status": self.status,
            "runs": self.runs,
            "errors": self.errors,
            "interval": self.interval,
            "last_run": self.last_run,
            "last_ms": round(self.last_ms, 1),
            "output": self.output,
            "log": list(self.log)[:8],
        }
