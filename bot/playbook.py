"""Las 100 reglas que de verdad corre la gente, en un solo sitio.

No hay nada exótico aquí y es a propósito: cruces de medias, RSI, MACD,
Bollinger, Donchian, Supertrend, estocástico, ADX, Heikin-Ashi, SAR, Keltner
y momentum. Son las que aparecen una y otra vez en TradingView, en freqtrade
y en cualquier foro de trading. Si alguna tiene ventaja, la queremos ver; si
ninguna la tiene, eso también es un resultado y hay que poder demostrarlo.

Cada estrategia es una función `(pre, i) -> bool`: ¿debería estar dentro hoy?
Sin más estado. Así se pueden comparar 100 con el mismo listón y las mismas
comisiones, que es lo único que hace la comparación honesta.

    python3 -m bot.playbook          # lista el catálogo
"""
from __future__ import annotations

# ---------------------------------------------------------------- series base

def _ema(v, n):
    k, out, e = 2 / (n + 1), [], None
    for x in v:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def _sma(v, n):
    out, s = [], 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n:
            s -= v[i - n]
        out.append(s / min(i + 1, n))
    return out


def _rsi(v, n=14):
    out, ag, al = [50.0], None, None
    for i in range(1, len(v)):
        d = v[i] - v[i - 1]
        up, dn = max(d, 0.0), max(-d, 0.0)
        if ag is None:
            ag, al = up, dn
        else:
            ag = (ag * (n - 1) + up) / n
            al = (al * (n - 1) + dn) / n
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out


def _stdev(v, n):
    out = []
    for i in range(len(v)):
        w = v[max(0, i - n + 1):i + 1]
        m = sum(w) / len(w)
        out.append((sum((x - m) ** 2 for x in w) / len(w)) ** 0.5)
    return out


def _tr(c):
    out = [c[0]["h"] - c[0]["l"]]
    for i in range(1, len(c)):
        p = c[i - 1]["c"]
        out.append(max(c[i]["h"] - c[i]["l"], abs(c[i]["h"] - p), abs(c[i]["l"] - p)))
    return out


def _wilder(v, n):
    out, e = [], None
    for x in v:
        e = x if e is None else (e * (n - 1) + x) / n
        out.append(e)
    return out


def _dmi(c, n=14):
    """ADX y las dos direccionales, en versión serie."""
    plus, minus = [0.0], [0.0]
    for i in range(1, len(c)):
        up = c[i]["h"] - c[i - 1]["h"]
        dn = c[i - 1]["l"] - c[i]["l"]
        plus.append(up if up > dn and up > 0 else 0.0)
        minus.append(dn if dn > up and dn > 0 else 0.0)
    atr = _wilder(_tr(c), n)
    pdi = [100 * p / a if a else 0.0 for p, a in zip(_wilder(plus, n), atr)]
    mdi = [100 * m / a if a else 0.0 for m, a in zip(_wilder(minus, n), atr)]
    dx = [100 * abs(p - m) / (p + m) if (p + m) else 0.0 for p, m in zip(pdi, mdi)]
    return _wilder(dx, n), pdi, mdi, atr


def _stoch(c, k=14, d=3):
    ks = []
    for i in range(len(c)):
        w = c[max(0, i - k + 1):i + 1]
        hi = max(x["h"] for x in w)
        lo = min(x["l"] for x in w)
        ks.append(50.0 if hi == lo else 100 * (c[i]["c"] - lo) / (hi - lo))
    return ks, _sma(ks, d)


def _donchian(c, n):
    hi, lo = [], []
    for i in range(len(c)):
        w = c[max(0, i - n + 1):i + 1]
        hi.append(max(x["h"] for x in w))
        lo.append(min(x["l"] for x in w))
    return hi, lo


def _supertrend(c, mult, per):
    atr = _wilder(_tr(c), per)
    dirs, up, dn = [1], None, None
    for i in range(len(c)):
        mid = (c[i]["h"] + c[i]["l"]) / 2
        u, d = mid + mult * atr[i], mid - mult * atr[i]
        if i == 0:
            up, dn = u, d
            continue
        up = min(u, up) if c[i - 1]["c"] <= up else u
        dn = max(d, dn) if c[i - 1]["c"] >= dn else d
        prev = dirs[-1]
        cur = 1 if c[i]["c"] > up else (-1 if c[i]["c"] < dn else prev)
        dirs.append(cur)
    return dirs


def _heikin(c):
    ha_c, ha_o = [], []
    for i, x in enumerate(c):
        hc = (x["o"] + x["h"] + x["l"] + x["c"]) / 4
        ho = (x["o"] + x["c"]) / 2 if i == 0 else (ha_o[-1] + ha_c[-1]) / 2
        ha_c.append(hc)
        ha_o.append(ho)
    return ha_c, ha_o


def _psar(c, step=0.02, cap=0.2):
    out, bull = [c[0]["l"]], True
    af, ep, sar = step, c[0]["h"], c[0]["l"]
    for i in range(1, len(c)):
        sar = sar + af * (ep - sar)
        if bull:
            if c[i]["l"] < sar:
                bull, sar, ep, af = False, ep, c[i]["l"], step
            elif c[i]["h"] > ep:
                ep, af = c[i]["h"], min(af + step, cap)
        else:
            if c[i]["h"] > sar:
                bull, sar, ep, af = True, ep, c[i]["h"], step
            elif c[i]["l"] < ep:
                ep, af = c[i]["l"], min(af + step, cap)
        out.append(sar)
    return out


def _roc(v, n):
    return [0.0 if i < n or v[i - n] <= 0 else v[i] / v[i - n] - 1.0
            for i in range(len(v))]


EMAS = (5, 8, 9, 10, 12, 13, 20, 21, 26, 50, 55, 100, 200)
SMAS = (10, 20, 30, 50, 100, 200)
RSIS = (2, 7, 14, 21)
ROCS = (5, 10, 20, 60, 90)


def prepare(c: list[dict]) -> dict:
    """Todos los indicadores de un activo, calculados una sola vez."""
    cl = [x["c"] for x in c]
    p = {"c": cl, "n": len(cl), "candles": c}
    p["ema"] = {n: _ema(cl, n) for n in EMAS}
    p["sma"] = {n: _sma(cl, n) for n in SMAS}
    p["rsi"] = {n: _rsi(cl, n) for n in RSIS}
    p["roc"] = {n: _roc(cl, n) for n in ROCS}
    for tag, (f, s, g) in {"macd": (12, 26, 9), "macdf": (5, 35, 5)}.items():
        line = [a - b for a, b in zip(_ema(cl, f), _ema(cl, s))]
        p[tag] = (line, _ema(line, g))
    for tag, (n, k) in {"bb20": (20, 2.0), "bb20w": (20, 2.5), "bb50": (50, 2.0)}.items():
        mid, sd = _sma(cl, n), _stdev(cl, n)
        p[tag] = (mid, [m + k * s for m, s in zip(mid, sd)],
                  [m - k * s for m, s in zip(mid, sd)])
    p["don"] = {n: _donchian(c, n) for n in (10, 20, 30, 55)}
    adx, pdi, mdi, atr = _dmi(c, 14)
    p["adx"], p["pdi"], p["mdi"], p["atr"] = adx, pdi, mdi, atr
    p["stoch"] = _stoch(c, 14, 3)
    p["stochs"] = _stoch(c, 21, 5)
    p["st"] = {t: _supertrend(c, *t) for t in ((3, 10), (4, 14), (2, 7), (1.5, 7))}
    p["ha"] = _heikin(c)
    p["sar"] = _psar(c)
    kmid = _ema(cl, 20)
    p["kelt"] = (kmid, [m + 2 * a for m, a in zip(kmid, atr)],
                 [m - 2 * a for m, a in zip(kmid, atr)])
    p["atrp"] = [a / x if x else 0.0 for a, x in zip(atr, cl)]
    return p


# ------------------------------------------------------------------ catálogo

def _catalog():
    """(nombre, familia, fn) para las 100. Se construyen, no se copian a mano."""
    out = []

    def add(name, fam, fn):
        out.append((name, fam, fn))

    # 1. Cruces de EMA — el pan de cada día (12)
    for f, s in [(5, 20), (8, 21), (9, 26), (10, 50), (12, 26), (13, 55),
                 (20, 50), (20, 100), (21, 55), (50, 100), (50, 200), (12, 50)]:
        add(f"ema{f}>{s}", "cruce",
            lambda p, i, f=f, s=s: p["ema"][f][i] > p["ema"][s][i])

    # 2. Cruces de SMA, incluida la cruz dorada (8)
    for f, s in [(10, 30), (10, 50), (20, 50), (20, 100), (30, 100),
                 (50, 100), (50, 200), (10, 20)]:
        add(f"sma{f}>{s}", "cruce",
            lambda p, i, f=f, s=s: p["sma"][f][i] > p["sma"][s][i])

    # 3. RSI: sobreventa (compra la caída) y fuerza (compra la subida) (10)
    for n, th in [(2, 10), (2, 20), (7, 25), (7, 30), (14, 30), (14, 35), (21, 35)]:
        add(f"rsi{n}<{th}", "reversión",
            lambda p, i, n=n, th=th: p["rsi"][n][i] < th)
    for n, th in [(14, 50), (14, 55), (21, 50)]:
        add(f"rsi{n}>{th}", "momento",
            lambda p, i, n=n, th=th: p["rsi"][n][i] > th)

    # 4. MACD (8)
    add("macd>señal", "momento", lambda p, i: p["macd"][0][i] > p["macd"][1][i])
    add("macd>0", "momento", lambda p, i: p["macd"][0][i] > 0)
    add("macd>señal>0", "momento",
        lambda p, i: p["macd"][0][i] > p["macd"][1][i] > 0)
    add("macd hist↑", "momento",
        lambda p, i: i > 0 and (p["macd"][0][i] - p["macd"][1][i])
        > (p["macd"][0][i - 1] - p["macd"][1][i - 1]))
    add("macd rápido>señal", "momento",
        lambda p, i: p["macdf"][0][i] > p["macdf"][1][i])
    add("macd rápido>0", "momento", lambda p, i: p["macdf"][0][i] > 0)
    add("macd + ema50", "combo",
        lambda p, i: p["macd"][0][i] > p["macd"][1][i] and p["c"][i] > p["ema"][50][i])
    add("macd + rsi14>50", "combo",
        lambda p, i: p["macd"][0][i] > p["macd"][1][i] and p["rsi"][14][i] > 50)

    # 5. Bollinger, por los dos lados (8)
    add("bb20 toca baja", "reversión", lambda p, i: p["c"][i] < p["bb20"][2][i])
    add("bb20 2.5 baja", "reversión", lambda p, i: p["c"][i] < p["bb20w"][2][i])
    add("bb50 baja", "reversión", lambda p, i: p["c"][i] < p["bb50"][2][i])
    add("bb20 rompe alta", "ruptura", lambda p, i: p["c"][i] > p["bb20"][1][i])
    add("bb50 rompe alta", "ruptura", lambda p, i: p["c"][i] > p["bb50"][1][i])
    add("bb20 sobre media", "momento", lambda p, i: p["c"][i] > p["bb20"][0][i])
    add("bb baja + rsi14<40", "combo",
        lambda p, i: p["c"][i] < p["bb20"][2][i] and p["rsi"][14][i] < 40)
    add("bb alta + ema50", "combo",
        lambda p, i: p["c"][i] > p["bb20"][1][i] and p["c"][i] > p["ema"][50][i])

    # 6. Donchian — el sistema de las Tortugas (8)
    for n in (10, 20, 30, 55):
        add(f"donchian{n} máx", "ruptura",
            lambda p, i, n=n: i > 0 and p["c"][i] >= p["don"][n][0][i - 1])
        add(f"donchian{n} medio", "ruptura",
            lambda p, i, n=n: p["c"][i] > (p["don"][n][0][i] + p["don"][n][1][i]) / 2)

    # 7. Supertrend (6)
    for t in ((3, 10), (4, 14), (2, 7), (1.5, 7)):
        add(f"supertrend{t[0]}/{t[1]}", "tendencia",
            lambda p, i, t=t: p["st"][t][i] > 0)
    add("supertrend + ema50", "combo",
        lambda p, i: p["st"][(3, 10)][i] > 0 and p["c"][i] > p["ema"][50][i])
    add("2 supertrend", "combo",
        lambda p, i: p["st"][(3, 10)][i] > 0 and p["st"][(2, 7)][i] > 0)

    # 8. Estocástico (6)
    add("stoch<20", "reversión", lambda p, i: p["stoch"][0][i] < 20)
    add("stoch<30", "reversión", lambda p, i: p["stoch"][0][i] < 30)
    add("stoch k>d", "momento", lambda p, i: p["stoch"][0][i] > p["stoch"][1][i])
    add("stoch lento k>d", "momento",
        lambda p, i: p["stochs"][0][i] > p["stochs"][1][i])
    add("stoch>50", "momento", lambda p, i: p["stoch"][0][i] > 50)
    add("stoch<20 + ema200", "combo",
        lambda p, i: p["stoch"][0][i] < 20 and p["c"][i] > p["ema"][200][i])

    # 9. ADX y direccionales (6)
    add("adx>25", "tendencia", lambda p, i: p["adx"][i] > 25)
    add("adx>20 +di>-di", "tendencia",
        lambda p, i: p["adx"][i] > 20 and p["pdi"][i] > p["mdi"][i])
    add("adx>25 +di>-di", "tendencia",
        lambda p, i: p["adx"][i] > 25 and p["pdi"][i] > p["mdi"][i])
    add("+di>-di", "tendencia", lambda p, i: p["pdi"][i] > p["mdi"][i])
    add("adx<20 (rango)", "reversión", lambda p, i: p["adx"][i] < 20)
    add("adx>25 + ema20", "combo",
        lambda p, i: p["adx"][i] > 25 and p["c"][i] > p["ema"][20][i])

    # 10. Momento puro (8)
    for n in ROCS:
        add(f"roc{n}>0", "momento", lambda p, i, n=n: p["roc"][n][i] > 0)
    add("roc20>5%", "momento", lambda p, i: p["roc"][20][i] > 0.05)
    add("roc90>0 + roc20>0", "momento",
        lambda p, i: p["roc"][90][i] > 0 and p["roc"][20][i] > 0)
    add("roc5<-5% (rebote)", "reversión", lambda p, i: p["roc"][5][i] < -0.05)

    # 11. Heikin-Ashi (4)
    add("ha verde", "tendencia", lambda p, i: p["ha"][0][i] > p["ha"][1][i])
    add("ha 2 verdes", "tendencia",
        lambda p, i: i > 0 and p["ha"][0][i] > p["ha"][1][i]
        and p["ha"][0][i - 1] > p["ha"][1][i - 1])
    add("ha + ema50", "combo",
        lambda p, i: p["ha"][0][i] > p["ha"][1][i] and p["c"][i] > p["ema"][50][i])
    add("ha + adx>20", "combo",
        lambda p, i: p["ha"][0][i] > p["ha"][1][i] and p["adx"][i] > 20)

    # 12. SAR parabólico (3)
    add("sar debajo", "tendencia", lambda p, i: p["c"][i] > p["sar"][i])
    add("sar + ema50", "combo",
        lambda p, i: p["c"][i] > p["sar"][i] and p["c"][i] > p["ema"][50][i])
    add("sar + macd", "combo",
        lambda p, i: p["c"][i] > p["sar"][i] and p["macd"][0][i] > p["macd"][1][i])

    # 13. Keltner (4)
    add("kelt rompe alta", "ruptura", lambda p, i: p["c"][i] > p["kelt"][1][i])
    add("kelt toca baja", "reversión", lambda p, i: p["c"][i] < p["kelt"][2][i])
    add("kelt sobre media", "momento", lambda p, i: p["c"][i] > p["kelt"][0][i])
    add("squeeze bb<kelt", "ruptura",
        lambda p, i: p["bb20"][1][i] < p["kelt"][1][i] and p["c"][i] > p["ema"][20][i])

    # 14. Precio contra media, a secas (6)
    for n in (20, 50, 100, 200):
        add(f"precio>sma{n}", "tendencia",
            lambda p, i, n=n: p["c"][i] > p["sma"][n][i])
    add("precio>ema200 + rsi14>50", "combo",
        lambda p, i: p["c"][i] > p["ema"][200][i] and p["rsi"][14][i] > 50)
    add("precio<sma200 (contrario)", "reversión",
        lambda p, i: p["c"][i] < p["sma"][200][i])

    # 15. Volatilidad como filtro (4)
    add("atr% bajo", "filtro", lambda p, i: 0 < p["atrp"][i] < 0.03)
    add("atr% bajo + ema50", "combo",
        lambda p, i: 0 < p["atrp"][i] < 0.03 and p["c"][i] > p["ema"][50][i])
    add("atr% alto", "filtro", lambda p, i: p["atrp"][i] > 0.05)
    add("atr% alto + momento", "combo",
        lambda p, i: p["atrp"][i] > 0.05 and p["roc"][20][i] > 0)

    # 16. Los tres clásicos combinados (4)
    add("triple pantalla", "combo",
        lambda p, i: p["c"][i] > p["ema"][200][i] and p["macd"][0][i] > p["macd"][1][i]
        and p["stoch"][0][i] < 50)
    add("tortuga filtrada", "combo",
        lambda p, i: i > 0 and p["c"][i] >= p["don"][20][0][i - 1] and p["adx"][i] > 20)
    add("rsi2 + ema200", "combo",
        lambda p, i: p["rsi"][2][i] < 15 and p["c"][i] > p["ema"][200][i])
    add("comprar y esperar", "listón", lambda p, i: True)
    return out


CATALOG = _catalog()
NAMES = [n for n, _, _ in CATALOG]
FAMILIES = sorted({f for _, f, _ in CATALOG})

if __name__ == "__main__":
    print(f"{len(CATALOG)} estrategias en {len(FAMILIES)} familias\n")
    for fam in FAMILIES:
        rules = [n for n, f, _ in CATALOG if f == fam]
        print(f"{fam:<12}({len(rules):>2})  " + ", ".join(rules))
