"""Indicadores tecnicos en Python puro (sin numpy/pandas)."""
from __future__ import annotations


def sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def ema_series(values, n):
    if len(values) < n:
        return []
    k = 2.0 / (n + 1)
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema(values, n):
    s = ema_series(values, n)
    return s[-1] if s else None


def rsi(values, n=14):
    if len(values) < n + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - (100.0 / (1.0 + rs))


def macd(values, fast=12, slow=26, signal=9):
    """Devuelve (macd, signal, histograma) o (None, None, None)."""
    if len(values) < slow + signal:
        return None, None, None
    ef, es = ema_series(values, fast), ema_series(values, slow)
    # alinear por la cola
    n = min(len(ef), len(es))
    line = [ef[-n + i] - es[-n + i] for i in range(n)]
    sig = ema_series(line, signal)
    if not sig:
        return None, None, None
    return line[-1], sig[-1], line[-1] - sig[-1]


def atr(candles, n=14):
    """Average True Range sobre lista de dicts con h/l/c."""
    if len(candles) < n + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h, l = candles[i]["h"], candles[i]["l"]
        pc = candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    a = sum(trs[:n]) / n
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def stdev(values):
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return (sum((v - m) ** 2 for v in values) / (n - 1)) ** 0.5


def pct_change(values, n):
    if len(values) <= n or values[-n - 1] == 0:
        return None
    return (values[-1] / values[-n - 1]) - 1.0


def zscore(value, sample):
    s = stdev(sample)
    if s == 0:
        return 0.0
    return (value - sum(sample) / len(sample)) / s


def clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def adx(candles, n=14):
    """ADX de Wilder. Devuelve (adx, +DI, -DI) o (None, None, None).

    Mide la FUERZA de la tendencia, no su direccion: por debajo de ~20 el
    mercado esta lateral y las senales de tendencia valen poco.
    """
    if len(candles) < 2 * n + 1:
        return None, None, None
    pdm, ndm, trs = [], [], []
    for i in range(1, len(candles)):
        up = candles[i]["h"] - candles[i - 1]["h"]
        dn = candles[i - 1]["l"] - candles[i]["l"]
        pdm.append(up if (up > dn and up > 0) else 0.0)
        ndm.append(dn if (dn > up and dn > 0) else 0.0)
        h, l, pc = candles[i]["h"], candles[i]["l"], candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    def wilder(vals):
        s = sum(vals[:n])
        out = [s]
        for v in vals[n:]:
            s = s - s / n + v
            out.append(s)
        return out

    tr_s, pdm_s, ndm_s = wilder(trs), wilder(pdm), wilder(ndm)
    dxs = []
    for i in range(len(tr_s)):
        if tr_s[i] == 0:
            continue
        pdi = 100 * pdm_s[i] / tr_s[i]
        ndi = 100 * ndm_s[i] / tr_s[i]
        if pdi + ndi == 0:
            continue
        dxs.append((100 * abs(pdi - ndi) / (pdi + ndi), pdi, ndi))
    if len(dxs) < n:
        return None, None, None
    a = sum(d[0] for d in dxs[:n]) / n
    for d in dxs[n:]:
        a = (a * (n - 1) + d[0]) / n
    return a, dxs[-1][1], dxs[-1][2]
