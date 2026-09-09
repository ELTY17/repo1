"""Backtest sobre velas historicas reales.

Usa exactamente los mismos modulos que el sistema en vivo (`bot.signals`,
`bot.exits`, `bot.protections`), asi que mide lo que de verdad corre.
El reloj sale de la marca temporal de la vela, no del reloj de pared.

    python3 -m bot.backtest             # version actual
    python3 -m bot.backtest --dumb      # version anterior, para comparar
    python3 -m bot.backtest --compare   # las dos, una al lado de la otra
"""
from __future__ import annotations

import argparse

from . import feeds, signals
from .broker import PaperBroker
from .config import CONFIG, UNIVERSE, Config
from .exits import roi_reached, roi_target, trailing_stop
from .indicators import atr
from .protections import ProtectionManager


def _series(warmup, timeframe="1d"):
    out = {}
    for inst in UNIVERSE:
        c = feeds.get_candles(inst, timeframe=timeframe)
        if len(c) > warmup + 20:
            out[inst.symbol] = c
    if not out:
        raise SystemExit("no hay datos historicos suficientes")
    return out


BAR_SECONDS = {"1h": 3600, "1d": 86400}


def run(cfg: Config = CONFIG, warmup: int = 100, features=None,
        verbose: bool = True, timeframe: str = "1d"):
    feats = signals._feat(features)
    smart = bool(feats)
    series = _series(warmup, timeframe)
    bar_seconds = BAR_SECONDS[timeframe]
    n = min(len(c) for c in series.values())
    kinds = {i.symbol: i.kind for i in UNIVERSE}
    broker = PaperBroker(cfg.starting_cash, cfg.fee_rate, cfg.slippage_rate)
    prot = ProtectionManager() if "prot" in feats else None

    wt = cfg.weights["technical"] + cfg.weights["scanner"]
    w_tech, w_scan = cfg.weights["technical"] / wt, cfg.weights["scanner"] / wt

    halted = False
    blocked_entries = 0

    def tag(bar):
        if broker.trades:
            broker.trades[-1].setdefault("bar", bar - warmup)

    for k in range(warmup, n):
        window = {s: c[len(c) - n:][: k + 1] for s, c in series.items()}
        prices = {s: w[-1]["c"] for s, w in window.items()}
        now = window[next(iter(window))][-1]["t"]

        # --- gestion de posiciones abiertas ---
        for sym in list(broker.positions):
            pos = broker.positions[sym]
            bar = window[sym][-1]
            pos.high_water = max(pos.high_water, bar["h"])
            bars = pos.bars_open(now, bar_seconds)

            if bar["l"] <= pos.stop:
                t = broker.sell(sym, pos.stop, "stop-loss", ts=now); tag(k)
            elif "roi" in feats and roi_reached(bar["h"] / pos.entry - 1, bars, pos.atr_pct):
                tgt = roi_target(bars, pos.atr_pct)
                px = pos.entry * (1 + tgt)
                t = broker.sell(sym, px, f"objetivo {tgt*100:.1f}%", ts=now); tag(k)
            elif bar["h"] >= pos.target:
                t = broker.sell(sym, pos.target, "take-profit", ts=now); tag(k)
            else:
                if "trail" in feats:
                    ns = trailing_stop(pos.entry, pos.high_water, pos.stop, pos.atr)
                    if ns > pos.stop:
                        pos.stop = ns
                else:
                    r = pos.entry - pos.stop
                    if r > 0 and bar["c"] >= pos.entry + r and pos.stop < pos.entry:
                        pos.stop = pos.entry
                continue
            if prot and t:
                prot.register_close(sym, t["pnl"], t.get("pnl_pct", 0.0),
                                    t["reason"], now, broker.equity(prices))

        eq = broker.mark(prices)
        if not halted and broker.drawdown(prices) <= -cfg.max_drawdown_stop:
            halted = True
            for sym in list(broker.positions):
                broker.sell(sym, prices[sym], "kill switch", ts=now); tag(k)
        if halted:
            continue

        scores = {}
        for s, w in window.items():
            t_sc, _ = signals.technical_score(w, features=feats)
            s_sc, _ = signals.scanner_score(w, features=feats)
            scores[s] = w_tech * t_sc + w_scan * s_sc

        for sym, sc in scores.items():
            if sym in broker.positions and sc <= cfg.exit_threshold:
                t = broker.sell(sym, prices[sym], f"senal debil ({sc:+.2f})", ts=now)
                tag(k)
                if prot and t:
                    prot.register_close(sym, t["pnl"], t.get("pnl_pct", 0.0),
                                        t["reason"], now, broker.equity(prices))

        for sym, sc in sorted(scores.items(), key=lambda x: -x[1]):
            if sc < cfg.buy_threshold or sym in broker.positions:
                continue
            if len(broker.positions) >= cfg.max_positions:
                break
            if sum(1 for s in broker.positions if kinds[s] == kinds[sym]) >= 2:
                continue
            if prot:
                ok, _ = prot.check(sym, now)
                if not ok:
                    blocked_entries += 1
                    continue
            a = atr(window[sym], 14)
            price = prices[sym]
            stop_dist = max((a * cfg.stop_atr_mult) if a else price * 0.03, price * 0.005)
            qty = (eq * cfg.risk_per_trade) / stop_dist
            max_notional = min(eq * cfg.max_position_weight, broker.cash * 0.98)
            if qty * price > max_notional:
                qty = max_notional / price
            if qty * price < 1.0:
                continue
            broker.buy(sym, qty, price, price - stop_dist,
                       price + stop_dist * cfg.take_profit_r, f"score {sc:+.2f}",
                       ts=now, atr=a)
            tag(k)

    final = {s: c[-1]["c"] for s, c in series.items()}
    last_t = series[next(iter(series))][-1]["t"]
    for sym in list(broker.positions):
        broker.sell(sym, final[sym], "fin del backtest", ts=last_t)
    stats = broker.stats(final)
    stats["max_drawdown"] = max_dd(broker)
    stats["blocked_entries"] = blocked_entries
    stats["bars"] = n - warmup
    stats["timeframe"] = timeframe
    stats["halted"] = halted

    if verbose:
        report(stats, ("ACTUAL: " + ", ".join(sorted(feats))) if feats else "BASE (sin extras)")
    return stats, broker


def max_dd(broker):
    peak, worst = -1e18, 0.0
    for p in broker.equity_curve:
        peak = max(peak, p["equity"])
        worst = min(worst, p["equity"] / peak - 1)
    return worst


def report(s, title):
    print("=" * 58)
    unit = "diarias" if s.get("timeframe") == "1d" else "horarias"
    days = s['bars'] if s.get("timeframe") == "1d" else s['bars'] / 24
    print(f"  {title} · {s['bars']} barras {unit} (~{days/365:.1f} años)"
          if s.get("timeframe") == "1d" else
          f"  {title} · {s['bars']} barras {unit} (~{days:.0f} días)")
    print("=" * 58)
    print(f"  Capital final     : ${s['equity']:.2f}  ({s['total_return']*100:+.2f} %)")
    print(f"  Max drawdown      : {s['max_drawdown']*100:.2f} %")
    print(f"  Operaciones       : {s['trades_closed']} "
          f"({s['wins']}G / {s['losses']}P · {s['win_rate']*100:.0f} % acierto)")
    pf = s['profit_factor']
    print(f"  Profit factor     : {pf:.2f}" if pf else "  Profit factor     : n/a")
    print(f"  Comisiones        : ${s['fees_paid']:.2f}")
    if s.get("blocked_entries"):
        print(f"  Entradas frenadas : {s['blocked_entries']} por las protecciones")
    print("=" * 58)


def compare(cfg, timeframe="1d"):
    old, _ = run(cfg, features=set(), verbose=False, timeframe=timeframe)
    new, _ = run(cfg, features=None, verbose=False, timeframe=timeframe)
    rows = [
        ("Capital final",   f"${old['equity']:.2f}",              f"${new['equity']:.2f}"),
        ("Rentabilidad",    f"{old['total_return']*100:+.2f} %",  f"{new['total_return']*100:+.2f} %"),
        ("Max drawdown",    f"{old['max_drawdown']*100:.2f} %",   f"{new['max_drawdown']*100:.2f} %"),
        ("Operaciones",     f"{old['trades_closed']}",            f"{new['trades_closed']}"),
        ("Acierto",         f"{old['win_rate']*100:.0f} %",       f"{new['win_rate']*100:.0f} %"),
        ("Profit factor",   f"{old['profit_factor']:.2f}" if old['profit_factor'] else "n/a",
                            f"{new['profit_factor']:.2f}" if new['profit_factor'] else "n/a"),
        ("Comisiones",      f"${old['fees_paid']:.2f}",           f"${new['fees_paid']:.2f}"),
    ]
    w = max(len(r[0]) for r in rows)
    print("=" * (w + 30))
    print(f"  {'':<{w}}   {'ANTERIOR':>11}   {'ACTUAL':>11}")
    print("=" * (w + 30))
    for name, a, b in rows:
        print(f"  {name:<{w}}   {a:>11}   {b:>11}")
    print("=" * (w + 30))
    print(f"  Entradas frenadas por las protecciones: {new['blocked_entries']}")
    d = new["bars"] if timeframe == "1d" else new["bars"] / 24
    print(f"  Muestra: {new['bars']} barras {'diarias' if timeframe=='1d' else 'horarias'} "
          f"(~{d/365:.1f} años).")
    return old, new


def ablation(cfg, timeframe="1d"):
    """Mide cada mejora aislada. Sin esto es imposible saber cual aporta."""
    tests = [("BASE (nada)", set())]
    tests += [(f"solo {f}", {f}) for f in sorted(signals.ALL_FEATURES)]
    tests += [("activas por defecto", set(cfg.features))]
    print(f"{'variante':<22}{'retorno':>9}{'maxDD':>9}{'ret/DD':>8}{'ops':>5}{'PF':>7}")
    print("-" * 60)
    for name, f in tests:
        s, _ = run(cfg, features=f, verbose=False, timeframe=timeframe)
        r, dd = s["total_return"], abs(s["max_drawdown"])
        pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] else "n/a"
        print(f"{name:<22}{r*100:>8.2f}%{s['max_drawdown']*100:>8.2f}%"
              f"{(r/dd if dd else 0):>8.2f}{s['trades_closed']:>5}{pf:>7}")
    print("-" * 60)
    print("  Una sola muestra de ~1,1 años sobre 5 activos. Elegir la mejor")
    print("  combinación aquí es, en parte, sobreajustar a estos datos.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=CONFIG.starting_cash)
    ap.add_argument("--dumb", action="store_true", help="lógica anterior")
    ap.add_argument("--compare", action="store_true", help="compara ambas")
    ap.add_argument("--tf", default="1d", choices=["1h", "1d"], help="temporalidad")
    ap.add_argument("--ablation", action="store_true",
                    help="mide cada mejora por separado")
    a = ap.parse_args()
    CONFIG.starting_cash = a.cash
    if a.ablation:
        ablation(CONFIG, a.tf)
    elif a.compare:
        compare(CONFIG, a.tf)
    else:
        run(CONFIG, features=set() if a.dumb else None, timeframe=a.tf)
