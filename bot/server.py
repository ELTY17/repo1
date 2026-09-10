"""Servidor local del dashboard. Solo stdlib, escucha en 127.0.0.1."""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEB = os.path.join(os.path.dirname(__file__), "web")

# La investigación (backtest, ablación, Monte Carlo) tarda casi un minuto y no
# cambia mientras el proceso vive. Se calcula una vez en segundo plano y el
# dashboard la pide cuando está lista, en vez de venir incrustada a mano.
_research: dict = {"ready": False, "error": None}

def _compute_research():
    try:
        from .backtest import _series, run
        from .config import UNIVERSE, Config
        from .montecarlo import simulate, trade_returns
        from . import signals

        cfg = Config()
        stats, broker = run(cfg, verbose=False, timeframe="1d")

        # La cuenta de $10 del panel usa estos mismos resultados. Se calculan
        # aquí, en el hilo de fondo, porque el recorrido de $10 a $100 son
        # miles de operaciones por simulación y no cabe en una petición web.
        _llenar_turbo(broker)
        curve = [round(p["equity"], 4) for p in broker.equity_curve]

        abl = []
        for name, f in [("nada", set()), ("solo ADX", {"adx"}),
                        ("solo protecciones", {"prot"}), ("solo trailing", {"trail"}),
                        ("solo escalera ROI", {"roi"}), ("solo filtro régimen", {"regime"}),
                        ("las tres activas", set(cfg.features))]:
            st, _ = run(cfg, features=f, verbose=False, timeframe="1d")
            abl.append({"name": name, "ret": round(st["total_return"], 5),
                        "dd": round(st["max_drawdown"], 5),
                        "pf": (round(st["profit_factor"], 2) if st["profit_factor"] else None),
                        "trades": st["trades_closed"], "win": round(st["win_rate"], 3),
                        "on": f == set(cfg.features)})

        mc = simulate(trade_returns(broker, broker.equity_curve), 6000, 100,
                      cfg.starting_cash, cfg.max_drawdown_stop, 0.5)

        _research.update({
            "ready": True,
            "stats": {k: (round(v, 6) if isinstance(v, float) else v)
                      for k, v in stats.items() if not isinstance(v, dict)},
            "curve": curve, "ablation": abl,
            "mc": {k: mc[k] for k in ("paths", "trades", "n_returns", "p05", "p50",
                                      "p95", "prob_profit", "prob_ruin", "prob_halt",
                                      "dd_median", "bands", "sample")},
        })
    except Exception as e:                                   # noqa: BLE001
        _research.update({"ready": False, "error": f"{type(e).__name__}: {e}"})


def start_research():
    threading.Thread(target=_compute_research, name="research", daemon=True).start()


def make_handler(orch):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):                                # noqa: N802
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                with open(os.path.join(WEB, "index.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            if path == "/api/state":
                body = json.dumps(orch.state(), default=str).encode()
                return self._send(200, body)
            if path == "/api/research":
                return self._send(200, json.dumps(_research, default=str).encode())
            if path == "/api/candles":
                from urllib.parse import parse_qs, urlparse
                from . import feeds
                from .config import UNIVERSE
                q = parse_qs(urlparse(self.path).query)
                sym = (q.get("symbol") or [""])[0]
                inst = next((i for i in UNIVERSE if i.symbol == sym), None)
                if not inst:
                    return self._send(404, b'{"error":"simbolo desconocido"}')
                c = feeds.get_candles(inst, timeframe="1d")[-90:]
                body = json.dumps({"symbol": sym, "candles": [
                    [round(x["o"], 4), round(x["h"], 4), round(x["l"], 4),
                     round(x["c"], 4)] for x in c]}).encode()
                return self._send(200, body)
            if path == "/api/turbo":
                return self._send(200, json.dumps(_turbo_datos()).encode())
            if path == "/api/wide":
                from . import feeds
                return self._send(200, json.dumps(feeds.wide_universe()).encode())
            if path == "/favicon.ico":
                svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                       '<text y="26" font-size="26">🐙</text></svg>').encode()
                return self._send(200, svg, "image/svg+xml")
            if path == "/api/health":
                return self._send(200, json.dumps({"ok": True}).encode())
            return self._send(404, b'{"error":"not found"}')

        def log_message(self, *a):                       # silencio
            pass

    return Handler


# Los retornos reales de las operaciones del sistema y lo que se tarda en
# llegar a $100 con ellos. No cambia entre peticiones: se calcula una vez.
_turbo_cache: dict = {}


def _llenar_turbo(broker):
    from .montecarlo import trade_returns
    from .turbo import camino
    rets = [round(x, 6) for x in trade_returns(broker, broker.equity_curve)]
    _turbo_cache.update({"retornos": rets, "listo": True, **camino(rets, runs=5000)})


def _turbo_datos():
    """Lo que haya. Si aún no está, el panel espera y vuelve a preguntar."""
    return _turbo_cache or {"listo": False, "retornos": []}


def serve(orch, host, port):
    httpd = ThreadingHTTPServer((host, port), make_handler(orch))
    return httpd
