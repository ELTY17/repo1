"""Estrategias de terceros, portadas para medirlas con nuestro banco de pruebas.

Vienen de `freqtrade/freqtrade-strategies` (GPL-3.0, 5.464 estrellas, con commits
de hoy mismo): son estrategias que la gente esta corriendo ahora. Aqui se
reimplementa su LOGICA con nuestros indicadores; no se copia su codigo, que
depende de pandas, numpy y TA-Lib.

Se comparan todas con las mismas reglas de ejecucion —comision real, minimos del
exchange, stops y tabla ROI— y contra comprar y esperar, que es la vara de medir
que casi nadie se pone.

    python3 -m bot.external
    python3 -m bot.external --tf 1h --fee 0.0026
"""
from __future__ import annotations

import argparse

from . import feeds, signals
from .broker import PaperBroker
from .config import UNIVERSE, Config
from .indicators import atr, ema, rsi, sma, stdev
from .limits import min_notional

BAR_MIN = {"1h": 60, "1d": 1440}


# ---------------------------------------------------------------- indicadores
def heikin_ashi(c):
    """Velas Heikin-Ashi. Suavizan el ruido; Strategy001 decide con ellas."""
    out = []
    for i, x in enumerate(c):
        close = (x["o"] + x["h"] + x["l"] + x["c"]) / 4
        op = (c[0]["o"] + c[0]["c"]) / 2 if i == 0 else (out[-1]["o"] + out[-1]["c"]) / 2
        out.append({"o": op, "c": close,
                    "h": max(x["h"], op, close), "l": min(x["l"], op, close)})
    return out


def stoch_slowk(c, k=14, d=3):
    """%K lento del estocastico."""
    if len(c) < k + d:
        return None
    fast = []
    for i in range(k - 1, len(c)):
        w = c[i - k + 1:i + 1]
        hi = max(x["h"] for x in w); lo = min(x["l"] for x in w)
        fast.append(100 * (c[i]["c"] - lo) / (hi - lo) if hi > lo else 50.0)
    return sum(fast[-d:]) / d


def fisher_rsi(closes, n=14):
    """RSI normalizado a [-1, 1] con la transformada de Fisher."""
    import math
    r = rsi(closes, n)
    if r is None:
        return None
    x = max(min(0.1 * (r - 50), 0.999), -0.999)
    return (math.exp(2 * x) - 1) / (math.exp(2 * x) + 1)


def is_hammer(x):
    """Martillo: cuerpo pequeno arriba y sombra inferior larga."""
    body = abs(x["c"] - x["o"]); rng = x["h"] - x["l"]
    if rng <= 0 or body > rng * 0.35:
        return False
    lower = min(x["o"], x["c"]) - x["l"]
    upper = x["h"] - max(x["o"], x["c"])
    return lower > body * 2 and upper < body


def psar(c, step=0.02, cap=0.2):
    """SAR parabolico."""
    if len(c) < 5:
        return None
    up = c[1]["c"] > c[0]["c"]
    sar = c[0]["l"] if up else c[0]["h"]
    ep = c[0]["h"] if up else c[0]["l"]
    af = step
    for x in c[1:]:
        sar = sar + af * (ep - sar)
        if up:
            if x["l"] < sar:
                up, sar, ep, af = False, ep, x["l"], step
            elif x["h"] > ep:
                ep, af = x["h"], min(af + step, cap)
        else:
            if x["h"] > sar:
                up, sar, ep, af = True, ep, x["h"], step
            elif x["l"] < ep:
                ep, af = x["l"], min(af + step, cap)
    return sar


def supertrend_dir(c, m=4, p=14):
    """Direccion del Supertrend: 'up' o 'down'."""
    if len(c) < p + 2:
        return None
    st = fub = flb = None
    prev_close = None
    for i in range(p, len(c)):
        w = c[:i + 1]
        a = atr(w[-(p + 1):], p)
        if a is None:
            continue
        hl2 = (w[-1]["h"] + w[-1]["l"]) / 2
        bub, blb = hl2 + m * a, hl2 - m * a
        if fub is None:
            fub, flb, st = bub, blb, bub
        else:
            fub = bub if (bub < fub or prev_close > fub) else fub
            flb = blb if (blb > flb or prev_close < flb) else flb
            cl = w[-1]["c"]
            if st == fub_prev:
                st = flb if cl > fub else fub
            else:
                st = fub if cl < flb else flb
        fub_prev = fub
        prev_close = w[-1]["c"]
    return "up" if c[-1]["c"] > st else "down"


# ---------------------------------------------------------------- estrategias
class Strategy:
    name = "?"; roi = {0: 0.05}; stoploss = -0.10; origin = ""

    def entry(self, c) -> bool: return False
    def exit(self, c) -> bool: return False


class Strategy001(Strategy):
    """freqtrade-strategies/Strategy001 — cruce de EMA con velas Heikin-Ashi."""
    name = "Strategy001"; origin = "freqtrade-strategies"
    roi = {0: 0.05, 20: 0.04, 30: 0.03, 60: 0.01}; stoploss = -0.10

    def entry(self, c):
        cl = [x["c"] for x in c]
        e20, e50 = ema(cl, 20), ema(cl, 50)
        e20p, e50p = ema(cl[:-1], 20), ema(cl[:-1], 50)
        if None in (e20, e50, e20p, e50p):
            return False
        ha = heikin_ashi(c)[-1]
        return (e20p <= e50p and e20 > e50) and ha["c"] > e20 and ha["o"] < ha["c"]

    def exit(self, c):
        cl = [x["c"] for x in c]
        e50, e100 = ema(cl, 50), ema(cl, 100)
        e50p, e100p = ema(cl[:-1], 50), ema(cl[:-1], 100)
        e20 = ema(cl, 20)
        if None in (e50, e100, e50p, e100p, e20):
            return False
        ha = heikin_ashi(c)[-1]
        return (e50p <= e100p and e50 > e100) and ha["c"] < e20 and ha["o"] > ha["c"]


class Strategy002(Strategy):
    """freqtrade-strategies/Strategy002 — reversion: RSI + estocastico + Bollinger + martillo."""
    name = "Strategy002"; origin = "freqtrade-strategies"
    roi = {0: 0.05, 20: 0.04, 30: 0.03, 60: 0.01}; stoploss = -0.10

    def entry(self, c):
        cl = [x["c"] for x in c]
        r, k = rsi(cl, 14), stoch_slowk(c)
        mid, sd = sma(cl, 20), stdev(cl[-20:]) if len(cl) >= 20 else None
        if None in (r, k, mid) or not sd:
            return False
        return r < 30 and k < 20 and (mid - 2 * sd) > cl[-1] and is_hammer(c[-1])

    def exit(self, c):
        cl = [x["c"] for x in c]
        s, f = psar(c), fisher_rsi(cl)
        return s is not None and f is not None and s > cl[-1] and f > 0.3


class SupertrendStrategy(Strategy):
    """freqtrade-strategies/Supertrend — tres supertrends que deben coincidir.

    Con los valores por defecto los tres llevan los mismos parametros (m=4,
    p=14), asi que en la practica es UNO. Esta pensada para hiperoptimizar.
    """
    name = "Supertrend"; origin = "freqtrade-strategies"
    roi = {0: 0.087, 372: 0.058, 861: 0.029, 2221: 0.0}; stoploss = -0.265

    def entry(self, c): return supertrend_dir(c, 4, 14) == "up"
    def exit(self, c):  return supertrend_dir(c, 4, 14) == "down"


class Nuestra(Strategy):
    """La de este repositorio, con sus features por defecto."""
    name = "La nuestra"; origin = "este repo"
    roi = {}; stoploss = -0.10

    def entry(self, c):
        cfg = Config()
        wt = cfg.weights["technical"] + cfg.weights["scanner"]
        t, _ = signals.technical_score(c)
        s, _ = signals.scanner_score(c)
        return (cfg.weights["technical"] / wt * t
                + cfg.weights["scanner"] / wt * s) >= cfg.buy_threshold

    def exit(self, c):
        cfg = Config()
        wt = cfg.weights["technical"] + cfg.weights["scanner"]
        t, _ = signals.technical_score(c)
        s, _ = signals.scanner_score(c)
        return (cfg.weights["technical"] / wt * t
                + cfg.weights["scanner"] / wt * s) <= cfg.exit_threshold


# ---------------------------------------------------------------- evaluacion
def roi_hit(roi, minutes, profit):
    if not roi:
        return False
    got = [m for m in roi if m <= minutes]
    return bool(got) and profit > roi[max(got)]


def evaluate(strat: Strategy, series, n, warmup, tf, cash, fee, slip,
             max_open=3, enforce_min=True):
    bmin = BAR_MIN[tf]
    broker = PaperBroker(cash, fee, slip)
    by_sym = {i.symbol: i for i in UNIVERSE}
    opened = {}
    rejected = 0

    for k in range(warmup, n):
        win = {s: c[len(c) - n:][: k + 1] for s, c in series.items()}
        prices = {s: w[-1]["c"] for s, w in win.items()}
        now = win[next(iter(win))][-1]["t"]

        for sym in list(broker.positions):
            p = broker.positions[sym]
            bar = win[sym][-1]
            mins = (now - p.opened_at) / 60.0
            if bar["l"] <= p.stop:
                broker.sell(sym, p.stop, "stop", ts=now); continue
            prof_hi = bar["h"] / p.entry - 1
            if roi_hit(strat.roi, mins, prof_hi):
                tgt = strat.roi[max(m for m in strat.roi if m <= mins)]
                broker.sell(sym, p.entry * (1 + tgt), "roi", ts=now); continue
            if strat.exit(win[sym]):
                broker.sell(sym, bar["c"], "señal", ts=now)

        eq = broker.mark(prices)
        if len(broker.positions) >= max_open:
            continue
        for sym, w in win.items():
            if sym in broker.positions or len(broker.positions) >= max_open:
                continue
            if not strat.entry(w):
                continue
            px = prices[sym]
            stake = min(eq / max_open, broker.cash * 0.98)
            qty = stake / px
            if enforce_min and qty * px < min_notional(by_sym[sym], px):
                rejected += 1; continue
            if qty * px < 1:
                continue
            broker.buy(sym, qty, px, px * (1 + strat.stoploss), None, strat.name, ts=now)

    last = {s: c[-1]["c"] for s, c in series.items()}
    for sym in list(broker.positions):
        broker.sell(sym, last[sym], "fin")
    st = broker.stats(last)
    peak, worst = -1e18, 0.0
    for p in broker.equity_curve:
        peak = max(peak, p["equity"]); worst = min(worst, p["equity"] / peak - 1)
    st["max_drawdown"] = worst
    st["rejected"] = rejected
    return st


def buy_and_hold(series, n, warmup, cash):
    """Comprar el primer dia a partes iguales y no tocar nada. La vara de medir."""
    syms = list(series)
    per = cash / len(syms)
    tot = 0.0
    for s in syms:
        w = series[s][len(series[s]) - n:]
        tot += per * (w[-1]["c"] / w[warmup]["c"])
    return {"total_return": tot / cash - 1, "equity": tot, "trades_closed": len(syms),
            "win_rate": sum(1 for s in syms
                            if series[s][-1]["c"] > series[s][len(series[s]) - n:][warmup]["c"]) / len(syms),
            "profit_factor": None, "max_drawdown": float("nan"), "rejected": 0,
            "fees_paid": 0.0}


def main(tf="1d", fee=0.0026, slip=0.0010, cash=100.0, warmup=120, enforce=True):
    from .backtest import _series
    series = _series(warmup, tf)
    n = min(len(c) for c in series.values())
    bars = n - warmup
    dias = bars if tf == "1d" else bars / 24

    print("=" * 78)
    print(f"  ESTRATEGIAS QUE LA GENTE CORRE, MEDIDAS AQUÍ")
    print(f"  {len(series)} activos · {bars} barras de {tf} (~{dias:.0f} días) · "
          f"comisión {fee*100:.2f} % por lado" + (" · mínimos del exchange" if enforce else ""))
    print("=" * 78)
    print(f"{'estrategia':<19}{'origen':<22}{'retorno':>9}{'maxDD':>9}{'ops':>5}"
          f"{'acierto':>9}{'PF':>7}")
    print("-" * 78)

    bh = buy_and_hold(series, n, warmup, cash)
    rows = [("Comprar y esperar", "la vara de medir", bh)]
    for S in (Strategy001(), Strategy002(), SupertrendStrategy(), Nuestra()):
        st = evaluate(S, series, n, warmup, tf, cash, fee, slip, enforce_min=enforce)
        rows.append((S.name, S.origin, st))

    for name, origin, st in rows:
        pf = f"{st['profit_factor']:.2f}" if st.get("profit_factor") else "—"
        dd = "n/a" if st["max_drawdown"] != st["max_drawdown"] else f"{st['max_drawdown']*100:.2f}%"
        print(f"{name:<19}{origin:<22}{st['total_return']*100:>8.2f}%{dd:>9}"
              f"{st['trades_closed']:>5}{st['win_rate']*100:>8.0f}%{pf:>7}")
    print("-" * 78)
    rej = sum(r[2].get("rejected", 0) for r in rows)
    if rej:
        print(f"  {rej} órdenes rechazadas por no llegar al mínimo del exchange.")
    print("  Strategy001 y Strategy002 están escritas para velas de 5 minutos; aquí")
    print("  corren en otra temporalidad porque no hay datos de 5 min suficientes.")
    print("  Eso prueba su LÓGICA, no la estrategia tal y como la corre su autor.")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="1d", choices=["1h", "1d"])
    ap.add_argument("--fee", type=float, default=0.0026)
    ap.add_argument("--cash", type=float, default=100.0)
    ap.add_argument("--no-min", action="store_true")
    a = ap.parse_args()
    main(a.tf, a.fee, cash=a.cash, enforce=not a.no_min)
