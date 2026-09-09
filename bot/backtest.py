"""Backtest: replica la logica de los agentes sobre velas historicas reales.

Solo usa datos disponibles hasta cada barra (sin mirar al futuro). El agente de
noticias no es replicable historicamente, asi que su voto se pone a 0 y los
pesos de escaner y tecnico se renormalizan.

    python3 -m bot.backtest
"""
from __future__ import annotations

import argparse

from . import feeds
from .broker import PaperBroker
from .config import CONFIG, UNIVERSE
from .indicators import atr, clamp, ema, macd, pct_change, rsi, sma, stdev, zscore


def technical_score(candles):
    closes = [c["c"] for c in candles]
    price = closes[-1]
    parts = {}
    r = rsi(closes, 14)
    if r is not None:
        parts["rsi"] = 0.5 if r < 30 else (-0.8 if r > 75 else clamp((r - 50) / 25.0) * 0.6)
    ef, es = ema(closes, 12), ema(closes, 26)
    if ef and es:
        parts["trend"] = clamp((ef / es - 1) * 40)
    _, _, hist = macd(closes)
    if hist is not None:
        parts["macd"] = clamp((hist / price) * 300)
    mid, sd = sma(closes, 20), stdev(closes[-20:])
    if mid and sd > 0:
        parts["bollinger"] = clamp(-((price - mid) / (2 * sd)) * 0.5)
    return clamp(sum(parts.values()) / max(len(parts), 1))


def scanner_score(candles):
    closes = [c["c"] for c in candles]
    vols = [c["v"] for c in candles]
    m6 = pct_change(closes, 6) or 0.0
    m24 = pct_change(closes, 24) or 0.0
    m72 = pct_change(closes, 72) or 0.0
    vol_z = zscore(vols[-1], vols[-48:]) if len(vols) >= 48 else 0.0
    rv = stdev([closes[i] / closes[i - 1] - 1 for i in range(-48, 0)]) if len(closes) > 49 else 0.0
    momentum = (0.5 * m6 + 0.3 * m24 + 0.2 * m72) / (max(rv, 1e-4) * 8)
    return clamp(0.75 * clamp(momentum) + 0.25 * clamp(vol_z / 3.0))


def run(cfg=CONFIG, warmup=100, verbose=True):
    series = {}
    for inst in UNIVERSE:
        c = feeds.get_candles(inst)
        if len(c) > warmup + 20:
            series[inst.symbol] = c
    if not series:
        raise SystemExit("no hay datos historicos suficientes")

    n = min(len(c) for c in series.values())
    kinds = {i.symbol: i.kind for i in UNIVERSE}
    broker = PaperBroker(cfg.starting_cash, cfg.fee_rate, cfg.slippage_rate)

    # pesos sin noticias, renormalizados
    wt = cfg.weights["technical"] + cfg.weights["scanner"]
    w_tech = cfg.weights["technical"] / wt
    w_scan = cfg.weights["scanner"] / wt

    halted = False

    def tag(bar):
        """Anota la barra en la ultima operacion registrada."""
        if broker.trades:
            broker.trades[-1].setdefault("bar", bar - warmup)

    for k in range(warmup, n):
        window = {s: c[len(c) - n:][: k + 1] for s, c in series.items()}
        prices = {s: w[-1]["c"] for s, w in window.items()}

        # gestion de posiciones abiertas (stop / objetivo / break-even)
        for sym in list(broker.positions):
            pos = broker.positions[sym]
            bar = window[sym][-1]
            if bar["l"] <= pos.stop:
                broker.sell(sym, pos.stop, "stop-loss"); tag(k)
            elif bar["h"] >= pos.target:
                broker.sell(sym, pos.target, "take-profit"); tag(k)
            else:
                r = pos.entry - pos.stop
                if r > 0 and bar["c"] >= pos.entry + r and pos.stop < pos.entry:
                    pos.stop = pos.entry

        eq = broker.mark(prices)
        if not halted and broker.drawdown(prices) <= -cfg.max_drawdown_stop:
            halted = True
            for sym in list(broker.positions):
                broker.sell(sym, prices[sym], "kill switch"); tag(k)
        if halted:
            continue

        scores = {s: w_tech * technical_score(w) + w_scan * scanner_score(w)
                  for s, w in window.items()}

        for sym, sc in scores.items():
            if sym in broker.positions and sc <= cfg.exit_threshold:
                broker.sell(sym, prices[sym], f"senal debil ({sc:+.2f})"); tag(k)

        for sym, sc in sorted(scores.items(), key=lambda x: -x[1]):
            if sc < cfg.buy_threshold or sym in broker.positions:
                continue
            if len(broker.positions) >= cfg.max_positions:
                break
            if sum(1 for s in broker.positions if kinds[s] == kinds[sym]) >= 2:
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
                       price + stop_dist * cfg.take_profit_r, f"score {sc:+.2f}")
            tag(k)

    final_prices = {s: c[-1]["c"] for s, c in series.items()}
    for sym in list(broker.positions):
        broker.sell(sym, final_prices[sym], "fin del backtest")
    stats = broker.stats(final_prices)

    if verbose:
        bars = n - warmup
        print("=" * 58)
        print(f"  BACKTEST · {len(series)} instrumentos · {bars} barras horarias "
              f"(~{bars/24:.0f} dias)")
        print("=" * 58)
        print(f"  Capital inicial   : ${stats['starting_cash']:.2f}")
        print(f"  Capital final     : ${stats['equity']:.2f}")
        print(f"  Rentabilidad      : {stats['total_return']*100:+.2f}%")
        print(f"  Max drawdown      : {min_dd(broker)*100:.2f}%")
        print(f"  Operaciones       : {stats['trades_closed']} "
              f"({stats['wins']}G / {stats['losses']}P)")
        print(f"  Tasa de acierto   : {stats['win_rate']*100:.1f}%")
        pf = stats['profit_factor']
        print(f"  Profit factor     : {pf:.2f}" if pf else "  Profit factor     : n/a")
        print(f"  Comisiones pagadas: ${stats['fees_paid']:.2f}")
        print(f"  Kill switch       : {'ACTIVADO' if halted else 'no activado'}")
        print("=" * 58)
        if bars < 24 * 20:
            print("  AVISO: muestra corta. Estos numeros NO son evidencia de que")
            print("  la estrategia funcione. Sirven para ver que el sistema opera.")
    return stats, broker


def min_dd(broker):
    peak, worst = -1e18, 0.0
    for p in broker.equity_curve:
        peak = max(peak, p["equity"])
        worst = min(worst, p["equity"] / peak - 1)
    return worst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cash", type=float, default=CONFIG.starting_cash)
    a = ap.parse_args()
    CONFIG.starting_cash = a.cash
    run(CONFIG)
