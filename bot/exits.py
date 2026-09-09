"""Reglas de salida.

Portadas de freqtrade (GPL-3.0):
  * `minimal_roi`  — tabla de objetivos que decae con la duracion de la operacion.
    Se coge la entrada de mayor duracion que sea <= duracion actual y se sale si
    el beneficio la supera. Equivale a `min_roi_reached_entry`.
  * `trailing_stop_positive` con `trailing_stop_positive_offset` — cuando el
    beneficio supera el offset, el stop persigue al precio a una distancia fija.
    El stop nunca baja (`adjust_stop_loss`).
"""
from __future__ import annotations

# Barras abierta -> objetivo, en MULTIPLOS DEL ATR del activo.
#
# freqtrade usa porcentajes fijos porque su caso tipico son velas de 5-15 min.
# Aqui un porcentaje fijo no vale: un 5% es un objetivo absurdo en SPY y ridiculo
# en SOL, y ademas cambia de significado entre velas horarias y diarias. Anclarlo
# al ATR hace que la tabla signifique lo mismo en cualquier activo y temporalidad.
#
# El primer escalon (4.0 x ATR) es exactamente el objetivo 2R de siempre, porque
# el stop esta a 2 x ATR. A partir de ahi el listón baja con el tiempo.
ROI_STEPS: dict[int, float] = {
    0: 4.0,     # recien abierta: hace falta el objetivo completo, 2R
    6: 2.5,
    18: 1.2,
    40: 0.0,    # tan vieja que se cierra en cuanto no pierda
}

TRAILING_OFFSET_ATR = 2.0   # a partir de +2 x ATR el stop empieza a perseguir
TRAILING_DIST_ATR = 1.5     # y se queda 1,5 x ATR por debajo del maximo


def roi_target(bars_open: float, atr_pct: float) -> float | None:
    """Beneficio minimo exigido, como fraccion del precio de entrada."""
    if not atr_pct or atr_pct <= 0:
        return None
    steps = [b for b in ROI_STEPS if b <= bars_open]
    if not steps:
        return None
    return ROI_STEPS[max(steps)] * atr_pct


def roi_reached(profit_ratio: float, bars_open: float, atr_pct: float) -> bool:
    t = roi_target(bars_open, atr_pct)
    return t is not None and profit_ratio > t


def trailing_stop(entry: float, high_water: float, current_stop: float,
                  atr_abs: float | None) -> float:
    """Nuevo stop tras marcar un maximo. Solo puede subir, nunca bajar."""
    if entry <= 0 or not atr_abs or atr_abs <= 0:
        return current_stop
    if high_water - entry <= TRAILING_OFFSET_ATR * atr_abs:
        return current_stop
    return max(current_stop, high_water - TRAILING_DIST_ATR * atr_abs)
