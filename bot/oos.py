"""Validacion out-of-sample.

Todo lo medido hasta ahora tiene el mismo defecto: la combinacion de mejoras se
eligio mirando el mismo tramo con el que luego se midio. Eso infla el resultado
y no se sabe cuanto.

Aqui se parte el historico en dos. En el primer tramo (ENTRENAMIENTO) se repite
la eleccion desde cero. En el segundo (PRUEBA), que no se toca durante la
eleccion, se mide lo elegido. La diferencia entre ambos es el sobreajuste.

    python3 -m bot.oos
    python3 -m bot.oos --split 0.5 --real     # con comision y minimos reales
"""
from __future__ import annotations

import argparse

from .backtest import _series, run
from .config import CONFIG, Config

# Las mismas candidatas que se exploraron a mano al portar freqtrade.
CANDIDATES: list[tuple[str, set[str]]] = [
    ("nada",                 set()),
    ("adx",                  {"adx"}),
    ("prot",                 {"prot"}),
    ("trail",                {"trail"}),
    ("roi",                  {"roi"}),
    ("regime",               {"regime"}),
    ("adx+prot",             {"adx", "prot"}),
    ("adx+trail",            {"adx", "trail"}),
    ("prot+trail",           {"prot", "trail"}),
    ("adx+prot+trail",       {"adx", "prot", "trail"}),
    ("todas",                {"adx", "prot", "trail", "roi", "regime"}),
]


def score(st) -> float:
    """Criterio de eleccion: retorno por unidad de drawdown."""
    dd = abs(st["max_drawdown"])
    return st["total_return"] / dd if dd > 1e-9 else st["total_return"]


def evaluate(cfg, feats, lo, hi, tf, real):
    return run(cfg, features=feats, verbose=False, timeframe=tf,
               trade_from=lo, trade_to=hi, enforce_minimums=real)[0]


def main(cfg: Config, split: float = 0.6, tf: str = "1d", real: bool = False):
    warmup = 100
    n = min(len(c) for c in _series(warmup, tf).values()) - warmup
    cut = int(n * split)

    print("=" * 74)
    print(f"  VALIDACIÓN OUT-OF-SAMPLE · {n} barras diarias")
    print(f"  Entrenamiento: barras 0–{cut}   ·   Prueba: barras {cut}–{n} "
          f"(nunca se mira al elegir)")
    if real:
        print(f"  Condiciones reales: comisión {cfg.fee_rate*100:.2f} % por lado "
              f"+ mínimos de exchange")
    print("=" * 74)
    print(f"{'variante':<18}{'ENTREN.':>10}{'maxDD':>9}{'ret/DD':>8}"
          f"{'  │':>3}{'PRUEBA':>10}{'maxDD':>9}{'ret/DD':>8}")
    print("-" * 74)

    rows = []
    for name, f in CANDIDATES:
        tr = evaluate(cfg, f, 0, cut, tf, real)
        te = evaluate(cfg, f, cut, n, tf, real)
        rows.append((name, f, tr, te))
        print(f"{name:<18}{tr['total_return']*100:>9.2f}%{tr['max_drawdown']*100:>8.2f}%"
              f"{score(tr):>8.2f}{'  │':>3}"
              f"{te['total_return']*100:>9.2f}%{te['max_drawdown']*100:>8.2f}%"
              f"{score(te):>8.2f}")

    best = max(rows, key=lambda r: score(r[2]))          # elegida SOLO con entrenamiento
    base = next(r for r in rows if r[0] == "nada")
    used = next(r for r in rows if r[1] == set(cfg.features))

    print("-" * 74)
    print(f"  Elegida mirando solo el entrenamiento : {best[0]}")
    print(f"  La que lleva el repositorio ahora     : {used[0]}")
    print()
    print(f"  {best[0]} en entrenamiento : {best[2]['total_return']*100:+.2f} %")
    print(f"  {best[0]} en PRUEBA        : {best[3]['total_return']*100:+.2f} %"
          f"   ← el único número honesto")
    print(f"  sin mejoras, en PRUEBA    : {base[3]['total_return']*100:+.2f} %")
    print()
    caida = best[2]["total_return"] - best[3]["total_return"]
    print(f"  Caída entrenamiento → prueba: {caida*100:+.2f} puntos.")
    if best[1] != set(cfg.features):
        print(f"  AVISO: elegir a ciegas habría dado '{best[0]}', no "
              f"'{used[0]}'. La elección anterior usó datos de prueba.")
    if best[3]["total_return"] <= base[3]["total_return"]:
        print("  Fuera de muestra, las mejoras NO baten a no hacer nada.")
    print(f"  {best[3]['trades_closed']} operaciones en la prueba: muestra muy corta.")
    print("=" * 74)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", type=float, default=0.6)
    ap.add_argument("--tf", default="1d")
    ap.add_argument("--real", action="store_true",
                    help="comisión de exchange real y mínimos de orden")
    a = ap.parse_args()
    cfg = Config()
    if a.real:
        cfg.fee_rate, cfg.slippage_rate = 0.0026, 0.0010
    main(cfg, a.split, a.tf, a.real)
