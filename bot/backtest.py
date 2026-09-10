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

from . import correlacion, feeds, signals
from .broker import PaperBroker
from .config import CONFIG, UNIVERSE, Config

_BY_SYMBOL = {i.symbol: i for i in UNIVERSE}
from .exits import roi_reached, roi_target, trailing_stop
from .indicators import atr
from .limits import min_notional
from .protections import ProtectionManager


def _series(warmup, timeframe="1d"):
    """Velas cerradas de cada instrumento.

    La ultima vela que devuelve el exchange es la del periodo en curso y todavia
    se esta moviendo: incluirla hace que el mismo backtest de un numero distinto
    cada vez que se ejecuta. Se descarta.
    """
    import time as _t
    period = {"1h": 3600, "1d": 86400}[timeframe]
    now = _t.time()
    out = {}
    for inst in UNIVERSE:
        c = feeds.get_candles(inst, timeframe=timeframe)
        if c and now - c[-1]["t"] < period:
            c = c[:-1]                      # fuera la vela sin cerrar
        if len(c) > warmup + 20:
            out[inst.symbol] = c
    if not out:
        raise SystemExit("no hay datos historicos suficientes")
    return out


BAR_SECONDS = {"1h": 3600, "1d": 86400}


def run(cfg: Config = CONFIG, warmup: int = 100, features=None,
        verbose: bool = True, timeframe: str = "1d", enforce_minimums: bool = False,
        trade_from: int = 0, trade_to: int | None = None, record: bool = False):
    """`trade_from`/`trade_to` limitan las barras en las que se OPERA.

    Los indicadores siguen usando todo el histórico anterior a cada barra —eso no
    es mirar al futuro—, pero no se abre ni se mantiene nada fuera de la ventana.
    Es lo que permite entrenar en un tramo y medir en otro sin contaminarlos.
    """
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
    rejected = 0
    # Con `record` el backtest deja constancia de cada decision —comprar, vender,
    # esperar y por que— para poder reproducir la sesion en las demos. No cambia
    # nada de lo que hace: solo lo apunta.
    broker.rounds = []

    def anota(bar, sym, kind, reason, price, pnl=None, sc=None, det=None):
        if not record:
            return
        d = det or {}
        broker.rounds.append({
            "bar": bar - warmup, "symbol": sym, "kind": kind,
            "tech": round((sc or {}).get("tech", 0.0), 3),
            "scan": round((sc or {}).get("scan", 0.0), 3),
            "comp": round((sc or {}).get("comp", 0.0), 3),
            "adx": round(d["adx"], 1) if d.get("adx") is not None else None,
            "rsi": d.get("rsi"), "price": round(price, 4),
            "pnl": round(pnl, 4) if pnl is not None else None,
            "reason": reason, "equity": round(broker.equity(prices), 2)})

    def tag(bar):
        if broker.trades:
            broker.trades[-1].setdefault("bar", bar - warmup)

    trade_to = n - warmup if trade_to is None else trade_to
    for k in range(warmup, n):
        bar_i = k - warmup
        window = {s: c[len(c) - n:][: k + 1] for s, c in series.items()}
        prices = {s: w[-1]["c"] for s, w in window.items()}
        now = window[next(iter(window))][-1]["t"]

        # Mantener un corto cuesta rollover cada barra. Se cobra antes de nada.
        if cfg.allow_shorts:
            broker.funding(prices, cfg.short_funding_daily * (bar_seconds / 86400))

        # --- gestion de posiciones abiertas ---
        for sym in list(broker.positions):
            pos = broker.positions[sym]
            bar = window[sym][-1]
            corto = pos.side < 0
            # En un corto el "mejor precio visto" es el mínimo, no el máximo.
            pos.high_water = min(pos.high_water, bar["l"]) if corto \
                else max(pos.high_water, bar["h"])
            bars = pos.bars_open(now, bar_seconds)

            # El stop de un corto está ARRIBA y el objetivo ABAJO: todo en espejo.
            toca_stop = bar["h"] >= pos.stop if corto else bar["l"] <= pos.stop
            toca_obj = bar["l"] <= pos.target if corto else bar["h"] >= pos.target
            mejor = (pos.entry / bar["l"] - 1) if corto else (bar["h"] / pos.entry - 1)

            if toca_stop:
                t = broker.sell(sym, pos.stop, "stop-loss", ts=now); tag(k)
            elif "roi" in feats and roi_reached(mejor, bars, pos.atr_pct):
                tgt = roi_target(bars, pos.atr_pct)
                px = pos.entry * (1 - tgt) if corto else pos.entry * (1 + tgt)
                t = broker.sell(sym, px, f"objetivo {tgt*100:.1f}%", ts=now); tag(k)
            elif toca_obj:
                t = broker.sell(sym, pos.target, "take-profit", ts=now); tag(k)
            else:
                if "trail" in feats:
                    if corto:
                        # Se reutiliza el trailing de siempre reflejando el precio
                        # sobre la entrada: así la lógica es una sola y no puede
                        # divergir entre los dos lados.
                        esp = lambda x: 2 * pos.entry - x                  # noqa: E731
                        ns = esp(trailing_stop(pos.entry, esp(pos.high_water),
                                               esp(pos.stop), pos.atr))
                        if ns < pos.stop:
                            pos.stop = ns
                    else:
                        ns = trailing_stop(pos.entry, pos.high_water, pos.stop, pos.atr)
                        if ns > pos.stop:
                            pos.stop = ns
                else:
                    r = abs(pos.entry - pos.stop)
                    if r > 0 and pos.side * (bar["c"] - pos.entry) >= r \
                            and pos.side * (pos.entry - pos.stop) > 0:
                        pos.stop = pos.entry
                continue
            if t:
                anota(k, sym, "MECH", t["reason"], t.get("price", prices[sym]),
                      t.get("pnl"))
            if prot and t:
                prot.register_close(sym, t["pnl"], t.get("pnl_pct", 0.0),
                                    t["reason"], now, broker.equity(prices))

        if bar_i >= trade_to:
            for sym in list(broker.positions):
                broker.sell(sym, prices[sym], "fin de la ventana", ts=now); tag(k)
            broker.mark(prices)
            continue

        eq = broker.mark(prices)
        if not halted and broker.drawdown(prices) <= -cfg.max_drawdown_stop:
            halted = True
            for sym in list(broker.positions):
                broker.sell(sym, prices[sym], "kill switch", ts=now); tag(k)
        if halted:
            continue

        scores = {}
        partes = {}
        detalles = {}
        for s, w in window.items():
            t_sc, t_det = signals.technical_score(w, features=feats)
            s_sc, s_det = signals.scanner_score(w, features=feats)
            scores[s] = w_tech * t_sc + w_scan * s_sc
            partes[s] = {"tech": t_sc, "scan": s_sc, "comp": scores[s]}
            detalles[s] = {"rsi": t_det.get("rsi"), "adx": t_det.get("adx")}

        for sym, sc in scores.items():
            if sym in broker.positions and sc <= cfg.exit_threshold:
                t = broker.sell(sym, prices[sym], f"senal debil ({sc:+.2f})", ts=now)
                tag(k)
                if t:
                    anota(k, sym, "SELL", t["reason"], prices[sym], t.get("pnl"),
                          {"comp": sc}, detalles.get(sym))
                if prot and t:
                    prot.register_close(sym, t["pnl"], t.get("pnl_pct", 0.0),
                                        t["reason"], now, broker.equity(prices))

        if bar_i < trade_from:
            continue

        compradas = 0
        veto = None                       # por que no se compro, para la demo
        for sym, sc in sorted(scores.items(), key=lambda x: -x[1]):
            if sc < cfg.buy_threshold:
                veto = veto or f"score {sc:+.2f} < umbral {cfg.buy_threshold:+.2f}"
                continue
            if sym in broker.positions:
                continue
            if len(broker.positions) >= cfg.max_positions:
                veto = f"ya hay {cfg.max_positions} posiciones abiertas"
                break
            if "corr" in feats:
                # El agente de correlación sustituye al tope fijo: en vez de
                # contar posiciones de la misma clase, mira si el candidato se
                # mueve como algo que ya se tiene.
                ok, motivo = correlacion.permite(
                    window[sym], {s2: window[s2] for s2 in broker.positions})
                if not ok:
                    veto = veto or motivo
                    continue
            elif sum(1 for s in broker.positions
                     if kinds[s] == kinds[sym]) >= cfg.max_per_kind:
                veto = veto or (f"tope de {cfg.max_per_kind} posiciones "
                                f"por clase de activo")
                continue
            if prot:
                ok, motivo = prot.check(sym, now)
                if not ok:
                    blocked_entries += 1
                    veto = veto or f"proteccion activa: {motivo}"
                    continue
            a = atr(window[sym], 14)
            price = prices[sym]
            stop_dist = max((a * cfg.stop_atr_mult) if a else price * 0.03, price * 0.005)
            qty = (eq * cfg.risk_per_trade) / stop_dist
            max_notional = min(eq * cfg.max_position_weight, broker.cash * 0.98)
            if qty * price > max_notional:
                qty = max_notional / price
            if qty * price < 1.0:
                veto = veto or "tamano por debajo de $1"
                continue
            if enforce_minimums:
                need = min_notional(_BY_SYMBOL[sym], price)
                if qty * price < need:
                    rejected += 1
                    veto = veto or (f"minimo del exchange ${need:.2f} > "
                                    f"${qty * price:.2f} que toca poner")
                    continue
            broker.buy(sym, qty, price, price - stop_dist,
                       price + stop_dist * cfg.take_profit_r, f"score {sc:+.2f}",
                       ts=now, atr=a)
            tag(k)
            compradas += 1
            anota(k, sym, "BUY", f"score {sc:+.2f}", price, None,
                  partes[sym], detalles[sym])

        # --- cortos: el otro lado del mercado -------------------------------
        if cfg.allow_shorts:
            for sym, sc in sorted(scores.items(), key=lambda x: x[1]):
                if sc > cfg.short_threshold or sym in broker.positions:
                    continue
                if len(broker.positions) >= cfg.max_positions:
                    break
                if sum(1 for s2 in broker.positions
                       if kinds[s2] == kinds[sym]) >= cfg.max_per_kind:
                    continue
                if kinds[sym] != "crypto":
                    continue            # en acciones al contado no se vende corto
                if prot:
                    ok, motivo = prot.check(sym, now)
                    if not ok:
                        blocked_entries += 1
                        continue
                a = atr(window[sym], 14)
                price = prices[sym]
                stop_dist = max((a * cfg.stop_atr_mult) if a else price * 0.03,
                                price * 0.005)
                qty = (eq * cfg.risk_per_trade) / stop_dist
                max_notional = min(eq * cfg.max_position_weight, broker.cash * 0.98)
                if qty * price > max_notional:
                    qty = max_notional / price
                if qty * price < 1.0:
                    continue
                if enforce_minimums and qty * price < min_notional(_BY_SYMBOL[sym], price):
                    rejected += 1
                    continue
                if broker.short(sym, qty, price, price + stop_dist,
                                price - stop_dist * cfg.take_profit_r,
                                f"score {sc:+.2f}", ts=now, atr=a):
                    tag(k)
                    compradas += 1
                    anota(k, sym, "SHORT", f"score {sc:+.2f}", price, None,
                          partes[sym], detalles[sym])

        # Esperar es la decision que el sistema toma la mayor parte del tiempo;
        # se apunta una vez por barra, sobre el mejor candidato del momento.
        if record and not compradas and scores:
            mejor = max(scores, key=scores.get)
            anota(k, mejor, "WAIT", veto or "sin candidato nuevo",
                  prices[mejor], None, partes[mejor], detalles[mejor])

    final = {s: c[-1]["c"] for s, c in series.items()}
    last_t = series[next(iter(series))][-1]["t"]
    for sym in list(broker.positions):
        broker.sell(sym, final[sym], "fin del backtest", ts=last_t)
    stats = broker.stats(final)
    stats["max_drawdown"] = max_dd(broker)
    stats["blocked_entries"] = blocked_entries
    stats["rejected_min"] = rejected
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


FEE_TIERS = [
    ("0,10 % — el que usábamos", 0.0010, 0.0005),
    ("0,16 % — Kraken Pro, volumen alto", 0.0016, 0.0007),
    ("0,26 % — Kraken taker, cuenta nueva", 0.0026, 0.0010),
    ("0,40 % — Kraken Instant Buy", 0.0040, 0.0015),
    ("0,60 % — Coinbase Advanced", 0.0060, 0.0020),
    ("1,49 % — Coinbase básico", 0.0149, 0.0025),
]


def fees(cfg, timeframe="1d"):
    """Cuanto aguanta la estrategia segun lo que cobre el exchange.

    Es la medida que decide si esto tiene sentido con dinero real: el backtest
    por defecto usa 0,10 % por lado, que es la tarifa de una cuenta con mucho
    volumen. Una cuenta nueva paga bastante mas.
    """
    print(f"{'comisión por lado':>36}{'retorno':>10}{'ops':>5}{'comisiones':>12}{'PF':>7}")
    print("-" * 70)
    for name, fee, slip in FEE_TIERS:
        c = Config(**{**cfg.to_dict(), "fee_rate": fee, "slippage_rate": slip})
        st, _ = run(c, verbose=False, timeframe=timeframe)
        pf = f"{st['profit_factor']:.2f}" if st["profit_factor"] else "n/a"
        print(f"{name:>36}{st['total_return']*100:>9.2f}%{st['trades_closed']:>5}"
              f"{'$'+format(st['fees_paid'],'.2f'):>12}{pf:>7}")
    print("-" * 70)
    print("  El punto en el que deja de compensar está entre 0,26 % y 0,40 %.")
    print("  Una cuenta nueva de Kraken paga 0,26 % de taker; Instant Buy, más.")
    print("  Comprueba la tarifa que te aplican a ti antes de dar por bueno nada.")


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
    ap.add_argument("--fees", action="store_true",
                    help="sensibilidad a la comisión del exchange")
    a = ap.parse_args()
    CONFIG.starting_cash = a.cash
    if a.fees:
        fees(CONFIG, a.tf)
    elif a.ablation:
        ablation(CONFIG, a.tf)
    elif a.compare:
        compare(CONFIG, a.tf)
    else:
        run(CONFIG, features=set() if a.dumb else None, timeframe=a.tf)
