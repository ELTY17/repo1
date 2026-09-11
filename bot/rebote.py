"""La idea del rebote: comprar cuando algo ha caido X% y vender cuando sube Y%.

Es la estrategia que mas se propone y la que mejor suena: "compro barato, vendo
caro". Aqui se mide con las mismas reglas de siempre, que son las que separan
una idea buena de una que solo lo parece:

  * Se elige la pareja (caida, subida) mirando SOLO el tramo de entrenamiento.
  * Se mide en el tramo que no se ha tocado.
  * Se compara contra comprar y no hacer nada, que es el rival de verdad.
  * Se pagan comision y deslizamiento en cada lado.

Y se mide ademas lo que esta idea esconde: cuantas compras se quedan colgadas
sin llegar nunca al objetivo, y cuanto llega a caer una posicion mientras se
espera. Una estrategia sin stop no pierde poco: pierde tarde.

    python3 -m bot.rebote            # barrido completo, tren y prueba
    python3 -m bot.rebote --detalle  # que pasa con la pareja elegida
"""
from __future__ import annotations

import sys

from . import research
from .config import CONFIG

COSTE = CONFIG.fee_rate + CONFIG.slippage_rate     # por lado


def simular(series: dict[str, list[dict]], caida: float, subida: float,
            ventana: int, capital: float = 100.0, stop: float = 0.0) -> dict:
    """Una pasada del rebote sobre todo el universo.

    Reglas, tal cual se propusieron:
      - Si el precio esta `caida` por debajo del maximo de las ultimas
        `ventana` velas y no hay posicion, se compra.
      - Si el precio sube `subida` sobre el precio de compra, se vende.
      - No hay stop. Es la idea original y hay que medirla como es.

    El capital se reparte en tantas partes como activos, asi que cada uno opera
    su trozo y no compiten por el dinero. Es lo mas favorable a la idea.
    """
    symbols = sorted(series)
    n = len(next(iter(series.values())))
    trozo = capital / len(symbols)

    efectivo = {s: trozo for s in symbols}
    unidades = {s: 0.0 for s in symbols}
    entrada = {s: 0.0 for s in symbols}
    peor = {s: 0.0 for s in symbols}          # peor caida estando dentro

    ops, ganadas, dias_dentro, colgadas, paradas = 0, 0, 0, 0, 0
    peor_flotante = 0.0

    for i in range(ventana, n):
        for s in symbols:
            velas = series[s]
            precio = velas[i]["c"]
            techo = max(v["h"] for v in velas[i - ventana:i])
            if unidades[s] == 0.0:
                if techo > 0 and precio <= techo * (1 - caida):
                    gasto = efectivo[s]
                    if gasto < 1e-9:
                        continue
                    unidades[s] = gasto * (1 - COSTE) / precio
                    entrada[s] = precio
                    efectivo[s] = 0.0
                    peor[s] = 0.0
                    ops += 1
            else:
                caida_viva = precio / entrada[s] - 1
                peor[s] = min(peor[s], caida_viva)
                peor_flotante = min(peor_flotante, caida_viva)
                dias_dentro += 1
                if precio >= entrada[s] * (1 + subida):
                    efectivo[s] = unidades[s] * precio * (1 - COSTE)
                    unidades[s] = 0.0
                    ganadas += 1
                elif stop and caida_viva <= -stop:
                    # la version con freno: se corta la perdida y se vuelve a
                    # empezar. La propuesta original no lo lleva
                    efectivo[s] = unidades[s] * precio * (1 - COSTE)
                    unidades[s] = 0.0
                    paradas += 1

    # lo que queda abierto al final vale lo que valga hoy: no se regala
    final = 0.0
    for s in symbols:
        final += efectivo[s] + unidades[s] * series[s][-1]["c"]
        if unidades[s] > 0:
            colgadas += 1

    # comprar y no hacer nada, repartido igual
    bh = 0.0
    for s in symbols:
        v = series[s]
        bh += trozo * (1 - COSTE) * v[-1]["c"] / v[ventana]["c"]

    # exposicion: que fraccion del tiempo-capital estuvo dentro del mercado.
    # Sin esto la comparacion es tramposa: en un mercado que cae, estar en
    # efectivo la mitad del tiempo "bate" a comprar y estarse sin tener
    # ninguna ventaja. Lo que hay que batir es la misma exposicion.
    expo = dias_dentro / max((n - ventana) * len(symbols), 1)
    return {
        "final": final,
        "ret": final / capital - 1,
        "bh": bh / capital - 1,
        "expo": expo,
        "bh_ajustado": (bh / capital - 1) * expo,
        "ops": ops,
        "ganadas": ganadas,
        "paradas": paradas,
        "colgadas": colgadas,
        "dias_dentro": dias_dentro,
        "peor_flotante": peor_flotante,
    }



def simular_azar(series, subida, ventana, semilla, capital=100.0):
    """El mismo juego pero entrando en un dia AL AZAR, no tras la caida.

    Es la prueba que de verdad importa. En un mercado que baja, comprar mas
    tarde bate a comprar el primer dia SIEMPRE, tenga o no razon la regla: el
    precio de entrada es mas bajo porque el mercado cayo, no porque la regla
    supiera nada. Si el rebote no bate a entrar al azar, lo que parecia
    ventaja era el calendario.
    """
    import random
    rnd = random.Random(semilla)
    symbols = sorted(series)
    n = len(next(iter(series.values())))
    trozo = capital / len(symbols)
    total = 0.0
    for s in symbols:
        velas = series[s]
        i0 = rnd.randrange(ventana, max(ventana + 1, n - 1))
        entrada = velas[i0]["c"]
        unidades = trozo * (1 - COSTE) / entrada
        efectivo = 0.0
        for i in range(i0 + 1, n):
            if unidades and velas[i]["c"] >= entrada * (1 + subida):
                efectivo = unidades * velas[i]["c"] * (1 - COSTE)
                unidades = 0.0
                break
        total += efectivo + unidades * velas[-1]["c"]
    return total / capital - 1


def partir(series: dict[str, list[dict]], corte: float = 0.6):
    """Dos tramos operables: con el primero se elige, con el segundo se mide."""
    n = len(next(iter(series.values())))
    k = int(n * corte)
    tren = {s: v[:k] for s, v in series.items()}
    prueba = {s: v[k:] for s, v in series.items()}
    return tren, prueba


CAIDAS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40]
SUBIDAS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.40]
VENTANAS = [20, 60, 120]


def barrido(series, ventana_min: int) -> list[tuple]:
    out = []
    for v in VENTANAS:
        if len(next(iter(series.values()))) <= v + 30:
            continue
        for c in CAIDAS:
            for s in SUBIDAS:
                r = simular(series, c, s, v)
                out.append((r["ret"], c, s, v, r))
    out.sort(key=lambda x: -x[0])
    return out


def main():
    datos = research.load()
    series, comun = research.aligned(datos)
    import datetime as dt
    print(f"{len(series)} activos · {len(comun)} dias comunes · "
          f"{dt.date.fromtimestamp(comun[0])} → {dt.date.fromtimestamp(comun[-1])}")
    print(f"coste por lado: {COSTE*100:.2f}%\n")

    tren, prueba = partir(series)
    print(f"tren: {len(next(iter(tren.values())))} dias · "
          f"prueba: {len(next(iter(prueba.values())))} dias\n")

    res_tren = barrido(tren, 0)
    print("— Las cinco mejores EN EL TRAMO DE ENTRENAMIENTO —")
    print(f"{'caida':>6} {'subida':>7} {'vent':>5} {'retorno':>9} {'ops':>5} "
          f"{'colgadas':>9}")
    for ret, c, s, v, r in res_tren[:5]:
        print(f"{c*100:5.0f}% {s*100:6.0f}% {v:5d} {ret*100:8.2f}% "
              f"{r['ops']:5d} {r['colgadas']:9d}")

    ret_t, c, s, v, rt = res_tren[0]
    print(f"\nElegida mirando solo el tren: caida {c*100:.0f}%, "
          f"subida {s*100:.0f}%, ventana {v} dias")

    rp = simular(prueba, c, s, v)
    print("\n— En el tramo que NO se ha tocado —")
    print(f"  rebote           {rp['ret']*100:+8.2f}%")
    print(f"  comprar y estarse{rp['bh']*100:+8.2f}%")
    print(f"  diferencia       {(rp['ret']-rp['bh'])*100:+8.2f} puntos")
    print(f"  operaciones      {rp['ops']:8d}   cerradas en verde {rp['ganadas']}")
    print(f"  colgadas al final{rp['colgadas']:8d}   (compradas y nunca vendidas)")
    print(f"  peor caida viva  {rp['peor_flotante']*100:+8.2f}%  "
          "(lo que llego a perder una posicion esperando)")
    print(f"  tiempo dentro    {rp['expo']*100:8.1f}%  del tiempo-capital")
    print(f"\n  Comparacion honesta: con esa MISMA exposicion, comprar y "
          f"estarse daria {rp['bh_ajustado']*100:+.2f}%.")
    print(f"  El rebote da {rp['ret']*100:+.2f}%  →  "
          f"{(rp['ret']-rp['bh_ajustado'])*100:+.2f} puntos.")

    # ¿y si la pareja elegida fue suerte? cuantas del barrido baten al indice
    print("\n— Cuantas de las 108 combinaciones baten a no hacer nada, fuera "
          "de muestra —")
    mejores = mejores_aj = 0
    total = 0
    for ret, cc, ss, vv, _ in res_tren:
        r = simular(prueba, cc, ss, vv)
        total += 1
        if r["ret"] > r["bh"]:
            mejores += 1
        if r["ret"] > r["bh_ajustado"]:
            mejores_aj += 1
    print(f"  {mejores} de {total}  ({mejores/total*100:.0f}%) baten a comprar "
          "y estarse.")
    print("  Pero eso es trampa: el mercado cayo, y estar en efectivo parte "
          "del tiempo\n  ya bate a estar dentro entero, sin ninguna ventaja.")
    print(f"  Contra la MISMA exposicion: {mejores_aj} de {total} "
          f"({mejores_aj/total*100:.0f}%).  El azar seria 50%.")

    print("\n— La prueba de verdad: ¿bate a entrar un dia AL AZAR? —")
    muestras = sorted(simular_azar(prueba, s, v, k) for k in range(300))
    peores = sum(1 for m in muestras if m < rp["ret"])
    print(f"  entrada al azar, 300 sorteos: mediana {muestras[150]*100:+.2f}%, "
          f"p10 {muestras[30]*100:+.2f}%, p90 {muestras[270]*100:+.2f}%")
    print(f"  el rebote ({rp['ret']*100:+.2f}%) queda en el percentil "
          f"{peores/len(muestras)*100:.0f} de esa nube.")
    print("  Percentil 50 = no aporta nada sobre entrar a ciegas.")

    if "--detalle" in sys.argv:
        print("\n— La propuesta original, tal cual: caida 20%, subida 20% —")
        for v in VENTANAS:
            r = simular(series, 0.20, 0.20, v)
            print(f"  ventana {v:3d} dias: {r['ret']*100:+7.2f}%  vs  "
                  f"{r['bh']*100:+7.2f}% de no hacer nada · {r['ops']} ops · "
                  f"{r['colgadas']} colgadas · dentro "
                  f"{r['expo']*100:.0f}% del tiempo · peor caida viva "
                  f"{r['peor_flotante']*100:+.1f}%")
        print("\n— La misma propuesta PERO con freno (stop) —")
        for st in (0.10, 0.15, 0.20, 0.30):
            r = simular(prueba, 0.20, 0.20, 20, stop=st)
            print(f"  stop -{st*100:.0f}%: {r['ret']*100:+7.2f}%  "
                  f"(sin freno {simular(prueba, 0.20, 0.20, 20)['ret']*100:+.2f}%) · "
                  f"{r['ops']} ops · {r['paradas']} cortadas · peor caida viva "
                  f"{r['peor_flotante']*100:+.1f}%")


if __name__ == "__main__":
    main()
