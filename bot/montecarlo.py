"""Cono de ruina: que le pasaria a la cuenta si el futuro se pareciese al pasado.

Coge las operaciones cerradas del backtest, las remuestrea con reemplazo
(bootstrap) y simula miles de futuros posibles aplicando las mismas reglas que
el sistema real, incluido el kill switch por drawdown. Responde a la unica
pregunta que importa: cuantas veces se va la cuenta a cero.

    python3 -m bot.montecarlo
    python3 -m bot.montecarlo --paths 20000 --trades 120
"""
from __future__ import annotations

import argparse
import random

from .backtest import run
from .config import CONFIG, Config


def trade_returns(broker, curve) -> list[float]:
    """Resultado de cada operacion como fraccion del capital que habia entonces."""
    out = []
    eq = broker.starting_cash
    marks = {p["t"]: p["equity"] for p in broker.equity_curve}
    for t in broker.trades:
        if t["side"] not in ("SELL", "COVER") or t["pnl"] is None:
            continue
        base = marks.get(t["t"], eq) or eq
        if base > 0:
            out.append(t["pnl"] / base)
        eq = base
    return out


def simulate(returns: list[float], paths: int = 10000, trades: int = 100,
             start: float = 100.0, dd_stop: float = 0.25,
             ruin_at: float = 0.5, seed: int = 7):
    """Devuelve estadisticas y una muestra de trayectorias para dibujar."""
    if not returns:
        raise SystemExit("no hay operaciones cerradas que remuestrear")
    rnd = random.Random(seed)
    finals, dds, ruined, halted = [], [], 0, 0
    sample, all_paths = [], []
    for p in range(paths):
        eq, peak, worst = start, start, 0.0
        path = [eq]
        stopped = False
        for _ in range(trades):
            if not stopped:
                eq *= 1 + returns[rnd.randrange(len(returns))]
                peak = max(peak, eq)
                worst = min(worst, eq / peak - 1)
                if worst <= -dd_stop:
                    stopped = True          # kill switch: deja de operar
                    halted += 1
            path.append(eq)
        finals.append(eq)
        dds.append(worst)
        if eq <= start * ruin_at:
            ruined += 1
        all_paths.append(path)
        if p < 40:
            sample.append([round(v, 2) for v in path])

    finals.sort(); dds.sort()
    def pct(xs, q): return xs[min(int(q * len(xs)), len(xs) - 1)]

    # bandas: percentiles del capital en cada paso, para dibujar el cono
    bands = {q: [] for q in (5, 25, 50, 75, 95)}
    for step in range(trades + 1):
        col = sorted(all_paths[i][step] for i in range(len(all_paths)))
        for q in bands:
            bands[q].append(round(col[min(int(q / 100 * len(col)), len(col) - 1)], 3))
    return {
        "paths": paths, "trades": trades, "start": start,
        "n_returns": len(returns),
        "p05": pct(finals, .05), "p25": pct(finals, .25), "p50": pct(finals, .50),
        "p75": pct(finals, .75), "p95": pct(finals, .95),
        "mean": sum(finals) / len(finals),
        "prob_profit": sum(1 for f in finals if f > start) / len(finals),
        "prob_ruin": ruined / paths,
        "prob_halt": halted / paths,
        "dd_median": pct(dds, .50), "dd_p95": pct(dds, .05),
        "sample": sample, "bands": bands,
    }


def report(s, ruin_at):
    print("=" * 60)
    print(f"  CONO DE RUINA · {s['paths']:,} futuros de {s['trades']} operaciones")
    print(f"  Remuestreando las {s['n_returns']} operaciones reales del backtest")
    print("=" * 60)
    b = s["start"]
    print(f"  Peor 5 %          : ${s['p05']:7.2f}  ({(s['p05']/b-1)*100:+7.1f} %)")
    print(f"  Cuartil bajo      : ${s['p25']:7.2f}  ({(s['p25']/b-1)*100:+7.1f} %)")
    print(f"  Mediana           : ${s['p50']:7.2f}  ({(s['p50']/b-1)*100:+7.1f} %)")
    print(f"  Cuartil alto      : ${s['p75']:7.2f}  ({(s['p75']/b-1)*100:+7.1f} %)")
    print(f"  Mejor 5 %         : ${s['p95']:7.2f}  ({(s['p95']/b-1)*100:+7.1f} %)")
    print("-" * 60)
    print(f"  Acaba en verde    : {s['prob_profit']*100:5.1f} %")
    print(f"  Pierde la mitad   : {s['prob_ruin']*100:5.1f} %   (ruina = por debajo de ${b*ruin_at:.0f})")
    print(f"  Salta el freno    : {s['prob_halt']*100:5.1f} %   (kill switch a -25 %)")
    print(f"  Drawdown mediano  : {s['dd_median']*100:5.1f} %")
    print(f"  Drawdown peor 5 % : {s['dd_p95']*100:5.1f} %")
    print("=" * 60)
    print("  Esto NO es una prediccion. Supone que el futuro reparte las mismas")
    print("  operaciones que el pasado, en otro orden. Si el mercado cambia de")
    print("  regimen, la distribucion cambia y este cono no vale nada.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=10000)
    ap.add_argument("--trades", type=int, default=100)
    ap.add_argument("--ruin-at", type=float, default=0.5)
    a = ap.parse_args()
    cfg = Config()
    stats, broker = run(cfg, verbose=False)
    rets = trade_returns(broker, broker.equity_curve)
    report(simulate(rets, a.paths, a.trades, cfg.starting_cash,
                    cfg.max_drawdown_stop, a.ruin_at), a.ruin_at)
