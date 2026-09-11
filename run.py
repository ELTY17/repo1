#!/usr/bin/env python3
"""Arranca el sistema multi-agente y el dashboard local.

    python3 run.py                 # $100 simulados, dashboard en :8787
    python3 run.py --cash 250      # otro capital inicial
    python3 run.py --port 9000
"""
import argparse
import sys
import threading
import time
import time
import webbrowser

from bot.alerts import Alerts
from bot.config import CONFIG
from bot.orchestrator import Orchestrator
from bot.server import serve, start_research


def _watch(orch, alerts):
    """Vigilante: comprueba periódicamente que todo sigue en pie."""
    while True:
        time.sleep(30)
        try:
            alerts.check(orch)
        except Exception:                                    # noqa: BLE001,S110
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=CONFIG.starting_cash)
    ap.add_argument("--port", type=int, default=CONFIG.port)
    ap.add_argument("--host", default=CONFIG.host)
    ap.add_argument("--tick", type=int, default=CONFIG.tick_seconds)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--live", action="store_true",
                    help="conecta con Kraken en modo VALIDACIÓN (no ejecuta nada)")
    ap.add_argument("--real", action="store_true",
                    help="ejecuta órdenes de verdad. Exige --live, credenciales y "
                         "LIVE_TRADING_CONFIRMED. Puedes perder dinero.")
    args = ap.parse_args()

    CONFIG.starting_cash = args.cash
    CONFIG.port = args.port
    CONFIG.host = args.host
    CONFIG.tick_seconds = args.tick

    orch = Orchestrator(CONFIG)

    if args.live:
        from bot.kraken import KrakenError
        from bot.live import LiveBroker
        try:
            lb = LiveBroker(validate=not args.real)
            lb.arm()
            orch.broker = lb
            CONFIG.starting_cash = lb.starting_cash or CONFIG.starting_cash
        except KrakenError as e:
            print(f"\n  No se pudo conectar con el exchange: {e}\n")
            return 2
    elif args.real:
        print("\n  --real necesita también --live.\n")
        return 2

    alerts = Alerts()
    orch.alerts = alerts
    threading.Thread(target=_watch, args=(orch, alerts), daemon=True).start()
    orch.start()

    start_research()
    httpd = serve(orch, args.host, args.port)
    url = f"http://{args.host}:{args.port}"
    print("=" * 62)
    print("  OCTOPUS BOT · sistema multi-agente de trading")
    print("=" * 62)
    modo = ("REAL · MUEVE DINERO" if (args.live and args.real)
            else "VALIDACIÓN · el exchange comprueba, no ejecuta" if args.live
            else "PAPEL · dinero simulado")
    print(f"  Modo            : {modo}")
    print(f"  Capital inicial : ${CONFIG.starting_cash:,.2f}"
          + ("" if args.live else " simulados"))
    print("  Agentes         : noticias, escaner, tecnico, correlacion,")
    print("                    aprendizaje, riesgo, ejecucion")
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
