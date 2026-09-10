"""Calculo de senales, compartido por los agentes en vivo y por el backtest.

Antes cada uno tenia su copia y podian separarse sin que nadie se enterara;
ahora hay una sola implementacion y el backtest mide lo que de verdad corre.

`smart=True` anade dos cosas sobre la version original:
  * filtro de regimen: sin compras cuando el precio esta por debajo de la EMA50.
  * filtro de fuerza (ADX): la conviccion se recorta en mercado lateral.
"""
from __future__ import annotations

from .indicators import (adx, atr, clamp, ema, macd, pct_change, rsi, sma,
                         stdev, zscore)

REGIME_EMA = 50
ADX_CHOP = 18.0
ADX_STRONG = 25.0


ALL_FEATURES = {"regime", "adx", "prot", "roi", "trail", "corr"}


def _feat(features):
    if features is None:
        from .config import CONFIG
        return set(CONFIG.features)
    if features is True:
        return ALL_FEATURES
    if features is False:
        return set()
    return set(features)


def technical_score(candles, features=None) -> tuple[float, dict]:
    f = _feat(features)
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

    score = clamp(sum(parts.values()) / max(len(parts), 1))
    detail = {"parts": {k: round(v, 3) for k, v in parts.items()},
              "rsi": round(r, 1) if r is not None else None,
              "raw_score": round(score, 3), "atr": atr(candles, 14)}

    # --- filtro de regimen: no se compra por debajo de la media larga ---
    regime_ema = ema(closes, REGIME_EMA) if "regime" in f else None
    detail["ema50"] = regime_ema
    if regime_ema:
        below = price < regime_ema
        detail["regime"] = "bajista" if below else "alcista"
        if below and score > 0:
            score = 0.0
            detail["vetoed_by"] = f"precio bajo la EMA{REGIME_EMA}"
    else:
        detail["regime"] = "sin datos"

    # --- filtro de fuerza: en lateral la senal vale menos ---
    a, pdi, ndi = adx(candles, 14) if "adx" in f else (None, None, None)
    detail["adx"] = round(a, 1) if a is not None else None
    if a is not None:
        if a < ADX_CHOP:
            score *= 0.45
            detail["adx_note"] = "lateral: convicción recortada"
        elif a > ADX_STRONG:
            score = clamp(score * 1.15)
            detail["adx_note"] = "tendencia fuerte"

    score = clamp(score)
    detail["score"] = round(score, 3)
    return score, detail


def scanner_score(candles, features=None) -> tuple[float, dict]:
    closes = [c["c"] for c in candles]
    vols = [c["v"] for c in candles]
    m6 = pct_change(closes, 6) or 0.0
    m24 = pct_change(closes, 24) or 0.0
    m72 = pct_change(closes, 72) or 0.0
    vol_z = zscore(vols[-1], vols[-48:]) if len(vols) >= 48 else 0.0
    rv = (stdev([closes[i] / closes[i - 1] - 1 for i in range(-48, 0)])
          if len(closes) > 49 else 0.0)
    momentum = (0.5 * m6 + 0.3 * m24 + 0.2 * m72) / (max(rv, 1e-4) * 8)
    score = clamp(0.75 * clamp(momentum) + 0.25 * clamp(vol_z / 3.0))
    detail = {"m6": m6, "m24": m24, "m72": m72, "vol_z": round(vol_z, 2),
              "realized_vol": rv, "score": round(score, 3)}
    return score, detail
