"""Cambiar de estrategia según lo que esté haciendo el mercado.

La idea que pide el sentido común: una regla de ruptura funciona cuando hay
tendencia y se come el capital a base de latigazos cuando el mercado va de
lado. Así que en vez de casarse con una, se mira el régimen del mercado y se
usa la que mejor se porta en ese régimen.

El régimen se calcula SOLO con datos pasados (índice equiponderado contra su
propia media de 50 días, y volatilidad de 20 días contra su mediana histórica),
así que no hay futuro filtrado. Y la asignación régimo→estrategia se elige
mirando únicamente el tramo de entrenamiento. El tramo de prueba se usa una
sola vez, al final, para reportar.

    python3 -m bot.regime
    python3 -m bot.regime --top 15
"""
from __future__ import annotations

import argparse
import datetime as dt
import random

from bot import playbook, research

FEE = 0.0026
MIN_NOTIONAL = 5.0
MAX_POS = 10
START = 100.0

REGIMES = ["alcista tranquilo", "alcista nervioso",
           "bajista tranquilo", "bajista nervioso"]


# ------------------------------------------------------------------ régimen

def classify(series, names, n):
    """Régimen de cada día, con información disponible ese mismo día."""
    idx = []
    for i in range(n):
        idx.append(sum(series[a][i]["c"] / series[a][0]["c"] for a in names) / len(names))
    sma50 = playbook._sma(idx, 50)
    rets = [0.0] + [idx[i] / idx[i - 1] - 1 for i in range(1, n)]
    vol = playbook._stdev(rets, 20)
    out = []
    for i in range(n):
        past = sorted(vol[max(0, i - 252):i + 1])
        med = past[len(past) // 2]
        up = idx[i] > sma50[i]
        calm = vol[i] <= med
        out.append(("alcista " if up else "bajista ") + ("tranquilo" if calm else "nervioso"))
    return out, idx


# ------------------------------------------------------- carteras por regla

def weights(series, names, n, warm):
    """Para cada estrategia, el peso de cada activo cada día."""
    pre = {a: playbook.prepare(series[a]) for a in names}
    out = []
    for _, _, fn in playbook.CATALOG:
        days = []
        for i in range(n):
            if i < warm:
                days.append({})
                continue
            on = [a for a in names if fn(pre[a], i)]
            if len(on) > MAX_POS:
                # sin criterio de desempate honesto, nos quedamos con los
                # primeros por orden alfabético: no elegimos con el futuro
                on = on[:MAX_POS]
            days.append({a: 1.0 / len(on) for a in on} if on else {})
        out.append(days)
    return out


def walk(series, names, wts, pick, lo, hi):
    """Recorre los días aplicando pick(i) -> índice de estrategia. Comisiones incluidas."""
    eq, prev, switches = START, {}, 0
    for i in range(lo, hi - 1):
        w = wts[pick(i)][i]
        if eq / max(len(w), 1) < MIN_NOTIONAL and w:
            keep = max(int(eq // MIN_NOTIONAL), 1)
            w = {a: 1.0 / min(len(w), keep) for a in list(w)[:keep]}
        turn = sum(abs(w.get(a, 0) - prev.get(a, 0)) for a in set(w) | set(prev))
        eq *= 1 - turn * FEE
        if turn:
            switches += 1
        r = sum(q * (series[a][i + 1]["c"] / series[a][i]["c"] - 1) for a, q in w.items())
        eq *= 1 + r
        prev = w
    eq *= 1 - sum(prev.values()) * FEE
    return eq / START - 1.0, switches


def by_regime(series, names, wts, regs, lo, hi):
    """Rendimiento de cada estrategia dentro de cada régimen, por separado."""
    acc = {r: [1.0] * len(wts) for r in REGIMES}
    for i in range(lo, hi - 1):
        reg = regs[i]
        for s, days in enumerate(wts):
            w = days[i]
            turn = sum(abs(w.get(a, 0) - days[i - 1].get(a, 0))
                       for a in set(w) | set(days[i - 1])) if i > lo else sum(w.values())
            r = sum(q * (series[a][i + 1]["c"] / series[a][i]["c"] - 1)
                    for a, q in w.items())
            acc[reg][s] *= (1 - turn * FEE) * (1 + r)
    return acc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--robust", action="store_true",
                    help="varias ventanas + comparación contra asignación al azar")
    a = ap.parse_args()

    series, common = research.aligned(research.load())
    names = sorted(series)
    n = len(common)
    warm = 200
    split = warm + (n - warm) // 2
    regs, _ = classify(series, names, n)

    print(f"{len(names)} activos · {n} días · "
          f"{dt.date.fromtimestamp(common[0])} → {dt.date.fromtimestamp(common[-1])}")
    print(f"entreno {dt.date.fromtimestamp(common[warm])} → "
          f"{dt.date.fromtimestamp(common[split - 1])} | "
          f"prueba {dt.date.fromtimestamp(common[split])} → "
          f"{dt.date.fromtimestamp(common[-1])}")
    print(f"{len(playbook.CATALOG)} estrategias\n")
    for r in REGIMES:
        print(f"  {r:<18} {sum(1 for x in regs[warm:] if x == r):>4} días")

    wts = weights(series, names, n, warm)
    bh = playbook.NAMES.index("comprar y esperar")

    # --- fase 1: todo se decide mirando solo el entrenamiento ---------------
    tr = [(walk(series, names, wts, lambda i, s=s: s, warm, split)[0], s)
          for s in range(len(wts))]
    tr.sort(reverse=True)
    print(f"\nENTRENO — mejores sueltas (listón comprar y esperar: "
          f"{dict((s, r) for r, s in tr)[bh]:+.2%})")
    for r, s in tr[:a.top]:
        print(f"  {playbook.NAMES[s]:<28}{r:>+10.2%}")

    acc = by_regime(series, names, wts, regs, warm, split)
    table = {}
    for r in REGIMES:
        best = max(range(len(wts)), key=lambda s: acc[r][s])
        table[r] = best
        print(f"\n  {r:<18} mejor: {playbook.NAMES[best]:<24}"
              f"{acc[r][best] - 1:>+9.2%}  (listón {acc[r][bh] - 1:+.2%})")

    # --- fase 2: el tramo intacto, una sola vez -----------------------------
    best_single = tr[0][1]
    out = {
        "conmutador por régimen": walk(series, names, wts,
                                       lambda i: table[regs[i]], split, n),
        f"mejor suelta ({playbook.NAMES[best_single]})":
            walk(series, names, wts, lambda i: best_single, split, n),
        "comprar y esperar": walk(series, names, wts, lambda i: bh, split, n),
    }
    print("\nPRUEBA (nunca vista)")
    for k, (r, sw) in out.items():
        print(f"  {k:<38}{r:>+9.2%}")
    liston = out["comprar y esperar"][0]
    conm = out["conmutador por régimen"][0]
    print(f"\n  conmutador vs listón: {conm - liston:+.2%}")

    if not a.robust:
        print("\n  un solo tramo no demuestra nada: python3 -m bot.regime --robust")
        return
    robust(series, names, wts, regs, n, warm, bh)


def fit(series, names, wts, regs, lo, hi):
    """Asignación régimen→estrategia mirando SOLO [lo, hi)."""
    acc = by_regime(series, names, wts, regs, lo, hi)
    return {r: max(range(len(wts)), key=lambda s: acc[r][s]) for r in REGIMES}


def robust(series, names, wts, regs, n, warm, bh):
    """Lo único que separa un hallazgo de una casualidad: repetirlo."""
    print("\n" + "=" * 62)
    print("VENTANAS SUCESIVAS — entrenar en un tramo, medir en el siguiente")
    print(f"{'entreno':<26}{'prueba':<26}{'conm':>8}{'listón':>9}")
    diffs = []
    folds, span = 4, (n - warm) // 5
    for k in range(folds):
        lo, mid, hi = warm + k * span, warm + (k + 2) * span, warm + (k + 3) * span
        hi = min(hi, n)
        if hi - mid < 20:
            break
        table = fit(series, names, wts, regs, lo, mid)
        c = walk(series, names, wts, lambda i: table[regs[i]], mid, hi)[0]
        b = walk(series, names, wts, lambda i: bh, mid, hi)[0]
        diffs.append(c - b)
        print(f"{k + 1}. día {lo}-{mid:<17}día {mid}-{hi:<17}{c:>+8.1%}{b:>+9.1%}")
    won = sum(1 for d in diffs if d > 0)
    print(f"\n  gana al listón en {won}/{len(diffs)} ventanas · "
          f"diferencia media {sum(diffs) / len(diffs):+.2%}")

    print("\n" + "=" * 62)
    print("CONTRA EL AZAR — 400 asignaciones régimen→estrategia aleatorias")
    split = warm + (n - warm) // 2
    table = fit(series, names, wts, regs, warm, split)
    real = walk(series, names, wts, lambda i: table[regs[i]], split, n)[0]
    rng = random.Random(7)
    sample = []
    for _ in range(400):
        rt = {r: rng.randrange(len(wts)) for r in REGIMES}
        sample.append(walk(series, names, wts, lambda i: rt[regs[i]], split, n)[0])
    sample.sort()
    pct = sum(1 for x in sample if x < real) / len(sample)
    med = sample[len(sample) // 2]
    print(f"  al azar: mediana {med:+.2%} · p10 {sample[40]:+.2%} · p90 {sample[360]:+.2%}")
    print(f"  nuestra asignación: {real:+.2%} → percentil {pct:.0%}")
    print("\n  Si el percentil no es alto, elegir por régimen no aportó nada:")
    print("  el número bueno vendría de tener 4 estrategias cualesquiera.")

    solid = won >= max(len(diffs) - 1, 1) and pct >= 0.9
    print(f"\n  VEREDICTO: {'aguanta el escrutinio' if solid else 'no aguanta — es ruido'}")


if __name__ == "__main__":
    main()
