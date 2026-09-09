#!/usr/bin/env python3
"""Arranca el sistema multi-agente y el dashboard local.

    python3 run.py                 # $100 simulados, dashboard en :8787
    python3 run.py --cash 250      # otro capital inicial
    python3 run.py --port 9000
"""
import argparse
import sys
import time
import webbrowser

from bot.config import CONFIG
from bot.orchestrator import Orchestrator
from bot.server import serve


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=CONFIG.starting_cash)
    ap.add_argument("--port", type=int, default=CONFIG.port)
    ap.add_argument("--host", default=CONFIG.host)
    ap.add_argument("--tick", type=int, default=CONFIG.tick_seconds)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    CONFIG.starting_cash = args.cash
    CONFIG.port = args.port
    CONFIG.host = args.host
    CONFIG.tick_seconds = args.tick

    orch = Orchestrator(CONFIG)
    orch.start()

    httpd = serve(orch, args.host, args.port)
    url = f"http://{args.host}:{args.port}"
    print("=" * 62)
    print("  SISTEMA MULTI-AGENTE DE TRADING  ·  MODO PAPEL (dinero simulado)")
    print("=" * 62)
    print(f"  Capital inicial : ${args.cash:,.2f} simulados")
    print(f"  Agentes         : noticias, escaner, tecnico, riesgo, ejecucion")
    print(f"  Dashboard       : {url}")
    print(f"  Ctrl+C para parar")
    print("=" * 62)
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:                                # noqa: BLE001,S110
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nparando agentes...")
        orch.stop()
        httpd.shutdown()
        time.sleep(0.5)
        stats = orch.broker.stats(orch.prices())
        print(f"equity final: ${stats['equity']:.2f} "
              f"({stats['total_return']*100:+.2f}%) en {stats['trades_closed']} trades")
    return 0


if __name__ == "__main__":
    sys.exit(main())
