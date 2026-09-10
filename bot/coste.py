"""¿Cuánto duraría este bot si los agentes fueran agentes de Claude?

Ahora mismo no gasta nada: los cinco agentes son hilos de Python con
indicadores calculados a mano. Puede correr años en un portátil por el precio
de la electricidad. Esa es la respuesta corta y conviene no perderla de vista.

La pregunta interesante es la otra: si cada agente fuese una llamada a la API
de Claude —que es lo que la gente imagina cuando dice "agentes"—, ¿cuánto
aguantaría con un presupuesto dado? Aquí se calcula con los tamaños reales de
lo que cada agente tendría que leer, y con los precios publicados de la API.

    python3 -m bot.coste
    python3 -m bot.coste --presupuesto 20 --cadencia 20
"""
from __future__ import annotations

import argparse
import json

from . import feeds
from .config import UNIVERSE, Config

# Precios de la API de Claude, en dólares por millón de tokens.
# Entrada / salida / lectura de caché (la caché cuesta ~0,1x la entrada).
MODELOS = {
    "Opus 5":    (5.00, 25.00, 0.50),
    "Sonnet 5":  (2.00, 10.00, 0.20),
    "Haiku 4.5": (1.00,  5.00, 0.10),
}

# Un token son ~3,6 caracteres en JSON numérico denso como este. La cifra
# exacta la daría messages.count_tokens, que necesita clave; esto es una
# estimación conservadora y se dice que lo es.
CHARS_POR_TOKEN = 3.6

# Lo que cada agente escribiría de vuelta: un voto y su razón, no un ensayo.
SALIDA_TOKENS = {"noticias": 350, "escaner": 500, "tecnico": 600,
                 "riesgo": 400, "ejecucion": 250}

# Instrucciones fijas de cada agente. Se cachean: no cambian entre ciclos.
SISTEMA_TOKENS = 900


def _tokens(texto: str) -> int:
    return int(len(texto) / CHARS_POR_TOKEN)


def payloads(velas=90):
    """Lo que de verdad tendría que leer cada agente, medido en el dato real."""
    datos = {}
    for inst in UNIVERSE:
        try:
            c = feeds.get_candles(inst, timeframe="1d")[-velas:]
        except Exception:                                    # noqa: BLE001
            continue
        datos[inst.symbol] = [[round(x["o"], 4), round(x["h"], 4),
                               round(x["l"], 4), round(x["c"], 4)] for x in c]
    if not datos:
        raise SystemExit("sin datos de mercado; ¿hay red?")

    crudo = json.dumps(datos, separators=(",", ":"))
    resumen = json.dumps({s: v[-1] for s, v in datos.items()}, separators=(",", ":"))
    return {
        # El técnico necesita la serie entera: es su trabajo.
        "tecnico": _tokens(crudo),
        # El escáner compara fuerza relativa: le basta el cierre de cada día.
        "escaner": _tokens(json.dumps(
            {s: [x[3] for x in v] for s, v in datos.items()}, separators=(",", ":"))),
        # Noticias lee titulares, no precios.
        "noticias": 2200,
        # Riesgo y ejecución miran la cartera y el último precio.
        "riesgo": _tokens(resumen) + 400,
        "ejecucion": _tokens(resumen) + 300,
    }, len(datos), velas


def coste_ciclo(entradas, precio, cacheado=True):
    """Dólares de un ciclo completo: los cinco agentes hablan una vez."""
    p_in, p_out, p_cache = precio
    total = 0.0
    for agente, tok_in in entradas.items():
        sis = SISTEMA_TOKENS * (p_cache if cacheado else p_in) / 1e6
        ent = tok_in * p_in / 1e6
        sal = SALIDA_TOKENS[agente] * p_out / 1e6
        total += sis + ent + sal
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--presupuesto", type=float, default=10.0)
    ap.add_argument("--cadencia", type=int, default=Config().tick_seconds,
                    help="segundos entre ciclos de decisión")
    ap.add_argument("--agentes", type=int, default=5)
    a = ap.parse_args()

    entradas, n_act, velas = payloads()
    tok_ciclo = sum(entradas.values()) + SISTEMA_TOKENS * 5
    ciclos_hora = 3600 / a.cadencia

    print(f"Universo: {n_act} activos · {velas} velas diarias cada uno")
    print(f"Cadencia real del sistema: un ciclo cada {a.cadencia}s "
          f"→ {ciclos_hora:.0f} ciclos/hora\n")
    print("Lo que leería cada agente por ciclo (tokens estimados):")
    for k, v in sorted(entradas.items(), key=lambda x: -x[1]):
        print(f"  {k:<10}{v:>9,}")
    print(f"  {'sistema':<10}{SISTEMA_TOKENS * 5:>9,}  (cacheado)")
    print(f"  {'TOTAL':<10}{tok_ciclo:>9,} tokens por ciclo\n")

    print(f"{'modelo':<11}{'$/ciclo':>10}{'$/hora':>10}{'$/día':>11}"
          f"{'$/mes':>12}{'dura $' + str(int(a.presupuesto)):>12}")
    for nombre, precio in MODELOS.items():
        c = coste_ciclo(entradas, precio)
        hora = c * ciclos_hora
        dia, mes = hora * 24, hora * 24 * 30
        horas = a.presupuesto / hora
        dur = (f"{horas * 60:.0f} min" if horas < 1 else
               f"{horas:.1f} h" if horas < 48 else f"{horas / 24:.1f} días")
        print(f"{nombre:<11}{c:>10.4f}{hora:>10.2f}{dia:>11.2f}{mes:>12.0f}{dur:>12}")

    # ── la parte que de verdad decide: cada cuánto se pregunta ──────────────
    # El sistema opera velas DIARIAS. Preguntarle a un modelo cada 20 segundos
    # es pagar por 4.320 opiniones al día sobre un gráfico que cambia una vez.
    print(f"\n{'─' * 62}\nMisma cuenta, cambiando solo cada cuánto se pregunta")
    print(f"(con {a.agentes} agentes, y el presupuesto de ${a.presupuesto:.0f}):\n")
    print(f"{'cadencia':<22}{'ciclos/día':>12}{'Opus 5':>12}{'Sonnet 5':>12}{'Haiku':>10}")
    escala = a.agentes / 5
    for etiqueta, seg in [("cada 20 s (ahora)", 20), ("cada 5 min", 300),
                          ("cada hora", 3600), ("4 veces al día", 21600),
                          ("una vez al día", 86400)]:
        cd = 86400 / seg
        fila = f"{etiqueta:<22}{cd:>12,.0f}"
        for nombre, precio in MODELOS.items():
            dia = coste_ciclo(entradas, precio) * cd * escala
            dur = a.presupuesto / dia
            fila += (f"{dur * 24:>11.0f}h" if dur < 2 else
                     f"{dur:>11.0f}d" if dur < 400 else f"{dur / 365:>11.1f}a")
        print(fila)
    print("\nLa columna es cuánto aguanta el presupuesto. Una vela diaria cambia")
    print("una vez al día: preguntar más veces no da más información, solo más")
    print("factura. Ahí está la respuesta realista.")

    # El otro lado de la balanza: lo que el sistema gana, medido.
    # +1,09% sobre $100 en 401 días de mercado.
    gana_dia = 100 * 0.0109 / 401
    print(f"\nAl otro lado: el sistema gana {gana_dia:.4f} $/día sobre $100")
    print("(su resultado medido, +1,09% en 401 días de mercado).")
    barato = min(MODELOS.items(), key=lambda x: coste_ciclo(entradas, x[1]))
    unitario = coste_ciclo(entradas, barato[1]) * (a.agentes / 5)
    for etiqueta, cd in [(f"a la cadencia de ahora ({a.cadencia}s)", 86400 / a.cadencia),
                         ("preguntando una vez al día", 1)]:
        d = unitario * cd
        print(f"  {etiqueta:<34}{d:>10.2f} $/día  "
              f"({d / gana_dia:,.0f}× lo que gana)")
    print(f"\nCon {barato[0]} una vez al día hacen falta unos "
          f"${unitario / (0.0109 / 401):,.0f} operando solo para pagar la factura.")
    print("Por debajo de eso, el modelo cuesta más que lo que el sistema gana.")


if __name__ == "__main__":
    main()
