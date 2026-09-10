"""¿Cuántas operaciones por segundo se pueden hacer de verdad?

La pregunta parece de velocidad y no lo es. Hay cuatro cuellos de botella y
solo uno tiene que ver con lo rápido que piense nadie:

  1. La red: cuánto tarda una petición a Kraken en ir y volver. Se mide aquí.
  2. El contador de Kraken: cuántas peticiones acepta antes de bloquearte.
  3. La comisión: lo que cuesta cada ida y vuelta, que no baja por ir rápido.
  4. La señal: el sistema opera velas DIARIAS. No hay 10 decisiones por
     segundo que tomar porque el dato no cambia 10 veces por segundo.

El tercero es el que decide, y no se arregla con más agentes ni con más CPU.

    python3 -m bot.velocidad
"""
from __future__ import annotations

import argparse
import statistics
import time
import urllib.request

from .config import Config

PUBLICO = "https://api.kraken.com/0/public/Time"

# Contador de Kraken para cuentas normales, tal como lo implementa bot/kraken.py:
# tope 15, baja 0.33/s. Una orden cuesta 1; consultar órdenes cuesta 2.
TOPE, DECAY, COSTE_ORDEN = 15.0, 0.33, 1.0


def latencia(n: int = 12) -> list[float]:
    """Ida y vuelta real a Kraken, en milisegundos."""
    ms = []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            urllib.request.urlopen(PUBLICO, timeout=10).read()
        except Exception:                                    # noqa: BLE001
            continue
        ms.append((time.perf_counter() - t0) * 1000)
        time.sleep(0.25)
    return ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ops", type=float, default=10.0,
                    help="operaciones por segundo que se quieren hacer")
    ap.add_argument("--capital", type=float, default=100.0)
    a = ap.parse_args()
    cfg = Config()

    print("1. LA RED — ida y vuelta real a Kraken desde aquí")
    ms = latencia()
    if ms:
        print(f"   mediana {statistics.median(ms):.0f} ms · "
              f"mejor {min(ms):.0f} · peor {max(ms):.0f} ms")
        techo = 1000 / statistics.median(ms)
        print(f"   techo por latencia: {techo:.1f} peticiones/s en serie")
        print(f"   (una operación son 2: abrir y cerrar → {techo/2:.1f} ops/s)")
    else:
        print("   sin red; se salta la medición")

    print(f"\n2. EL CONTADOR DE KRAKEN — tope {TOPE:.0f}, baja {DECAY}/s")
    sost = DECAY / COSTE_ORDEN
    print(f"   ráfaga: {TOPE/COSTE_ORDEN:.0f} órdenes seguidas y te paras")
    print(f"   sostenido: {sost:.2f} órdenes/s = una cada {1/sost:.1f} s")
    print(f"   para {a.ops:.0f} ops/s harían falta {a.ops*2/sost:.0f}× ese límite")

    # El config lleva 0,10% porque es lo que se simula; Kraken cobra 0,26% de
    # taker a un minorista. Para esta cuenta manda la tarifa de verdad.
    TAKER = 0.0026
    print(f"\n3. LA COMISIÓN — taker real de Kraken {TAKER*100:.2f}% por lado "
          f"+ {cfg.slippage_rate*100:.2f}% de deslizamiento")
    ida_vuelta = 2 * (TAKER + cfg.slippage_rate)
    print(f"   cada ida y vuelta cuesta {ida_vuelta*100:.2f}% de lo movido")
    for ops in (a.ops, 1.0, 1/60, 1/86400):
        al_dia = ops * 86400
        etiq = (f"{ops:.0f}/s" if ops >= 1 else
                ("1/min" if abs(ops - 1/60) < 1e-9 else "1/día"))
        # moviendo la cuenta entera cada vez, que es el caso más favorable al
        # argumento de "voy rápido": menos rotación sería aún peor por operación
        coste = a.capital * ida_vuelta * al_dia
        print(f"   {etiq:<7}{al_dia:>12,.0f} ops/día → {coste:>16,.0f} $/día en comisiones")
    print(f"   La cuenta son ${a.capital:.0f}. A {a.ops:.0f} ops/s se evapora en "
          f"{1/(ida_vuelta * a.ops * 60):.1f} minutos.")

    print("\n4. LA SEÑAL — velas diarias")
    print(f"   el sistema hace 1 operación cada ~9 días de mercado")
    print(f"   a {a.ops:.0f} ops/s eso es {a.ops*86400*9:,.0f} operaciones donde")
    print("   el sistema ve una. Las otras no son señales: son ruido caro.")

    print("\n" + "=" * 62)
    print("Un bot PUEDE ir a 10 operaciones por segundo. Lo hacen a diario los")
    print("de alta frecuencia — pero con comisiones negociadas cerca de cero,")
    print("servidores en el mismo edificio que el exchange y una ventaja que")
    print("dura milisegundos. Con comisión de minorista, la velocidad no es")
    print("una ventaja: es el mecanismo por el que se pierde el dinero.")


if __name__ == "__main__":
    main()
