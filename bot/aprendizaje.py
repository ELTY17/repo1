"""Qué ha aprendido el bot, y cuánto le falta para aprender lo demás.

"Aprender" aquí no es "le funcionó dos veces". Cada regla del catálogo se
evalúa contra lo que hizo el mercado al día siguiente, se acumulan sus
resultados, y solo se da por APRENDIDA cuando su ventaja se distingue del cero
con margen: media positiva y t de Student por encima de 2, con muestra
suficiente. Lo demás está APRENDIENDO, y se puede decir exactamente cuánto le
falta.

Esa cuenta —cuántas observaciones más hacen falta— es lo que llena la barra.
No es decorativa: sale de la varianza observada y del tamaño del efecto
observado, así que una regla con ventaja grande y estable llena la barra
deprisa y una regla mediocre no la llena nunca.

    python3 -m bot.aprendizaje            # estado actual
    python3 -m bot.aprendizaje --historia # aprende de todo el histórico
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time

ARCHIVO = os.path.join(os.path.dirname(__file__), "..", ".aprendizaje.json")

T_APRENDIDO = 2.0        # ~97,5% de confianza en una cola
N_MINIMO = 60            # por debajo de esto no se cierra ningún juicio
FEE = 0.0026             # cada señal implica entrar y salir


class Registro:
    """Media, varianza y evidencia de una regla, en forma acumulable."""

    def __init__(self, n=0, suma=0.0, suma2=0.0, aciertos=0, visto=0.0):
        self.n, self.suma, self.suma2 = n, suma, suma2
        self.aciertos, self.visto = aciertos, visto

    def añade(self, r: float):
        self.n += 1
        self.suma += r
        self.suma2 += r * r
        if r > 0:
            self.aciertos += 1
        self.visto = time.time()

    @property
    def media(self):
        return self.suma / self.n if self.n else 0.0

    @property
    def desv(self):
        if self.n < 2:
            return 0.0
        v = (self.suma2 - self.n * self.media ** 2) / (self.n - 1)
        return math.sqrt(max(v, 0.0))

    @property
    def t(self):
        """Cuántos errores estándar separa la media del cero."""
        if self.n < 2 or self.desv <= 0:
            return 0.0
        return self.media / (self.desv / math.sqrt(self.n))

    @property
    def n_necesario(self):
        """Observaciones que harían falta para que este efecto sea concluyente.

        Despejando n de t = media / (desv/raíz(n)): n = (T·desv/media)². Si la
        media es negativa o cero, no hay n que valga: la regla no tiene nada
        que demostrar por ese lado.
        """
        if self.media <= 0 or self.desv <= 0:
            return None
        return max(N_MINIMO, int((T_APRENDIDO * self.desv / self.media) ** 2) + 1)

    @property
    def estado(self):
        if self.n >= N_MINIMO and self.t >= T_APRENDIDO:
            return "aprendido"
        if self.n >= N_MINIMO and self.t <= -T_APRENDIDO:
            return "descartado"
        return "aprendiendo"

    @property
    def progreso(self):
        """0..1 — cuánto lleva del camino hasta poder decidir."""
        if self.estado != "aprendiendo":
            return 1.0
        nn = self.n_necesario
        if nn is None:                       # media negativa: mide contra el mínimo
            return min(1.0, self.n / N_MINIMO)
        return min(1.0, self.n / nn)

    def dict(self):
        return {"n": self.n, "suma": round(self.suma, 8),
                "suma2": round(self.suma2, 10), "aciertos": self.aciertos,
                "visto": self.visto}


class Memoria:
    """Todo lo que el bot lleva aprendido, guardado en disco."""

    def __init__(self, ruta: str = ARCHIVO):
        self.ruta = ruta
        self.reglas: dict[str, Registro] = {}
        self.cargar()

    def cargar(self):
        try:
            with open(self.ruta) as f:
                d = json.load(f)
            self.reglas = {k: Registro(**v) for k, v in d.get("reglas", {}).items()}
        except Exception:                                    # noqa: BLE001,S110
            pass

    def guardar(self):
        with open(self.ruta, "w") as f:
            json.dump({"t": time.time(),
                       "reglas": {k: v.dict() for k, v in self.reglas.items()}}, f)

    def observa(self, regla: str, retorno: float):
        self.reglas.setdefault(regla, Registro()).añade(retorno)

    def resumen(self, top: int = 12):
        filas = []
        for nombre, r in self.reglas.items():
            filas.append({
                "regla": nombre, "n": r.n, "media": round(r.media, 6),
                "t": round(r.t, 2), "estado": r.estado,
                "progreso": round(r.progreso, 3),
                "faltan": (max(0, (r.n_necesario or N_MINIMO) - r.n)
                           if r.estado == "aprendiendo" else 0),
                "acierto": round(r.aciertos / r.n, 3) if r.n else None,
            })
        filas.sort(key=lambda x: (-{"aprendido": 2, "aprendiendo": 1,
                                    "descartado": 0}[x["estado"]], -x["t"]))
        return {
            "reglas": filas[:top],
            "total": len(filas),
            "aprendidas": sum(1 for f in filas if f["estado"] == "aprendido"),
            "descartadas": sum(1 for f in filas if f["estado"] == "descartado"),
            "observaciones": sum(f["n"] for f in filas),
            # el avance global es el de las que aún están en juicio
            "progreso": (sum(f["progreso"] for f in filas if f["estado"] == "aprendiendo")
                         / max(1, sum(1 for f in filas if f["estado"] == "aprendiendo"))),
        }


def estudiar(memoria: Memoria, series: dict, desde: int = 0, hasta: int | None = None):
    """Pasa el catálogo por el histórico y apunta lo que le pasó a cada regla.

    Para cada día y cada activo: si la regla decía "dentro", se apunta el
    rendimiento del día siguiente menos la comisión de entrar y salir. Nadie
    elige nada aquí; solo se cuenta lo que pasó.
    """
    from . import playbook
    pre = {s: playbook.prepare(v) for s, v in series.items()}
    n = min(len(v) for v in series.values())
    hasta = n - 1 if hasta is None else min(hasta, n - 1)
    for nombre, _, fn in playbook.CATALOG:
        if nombre == "comprar y esperar":
            continue
        for s, p in pre.items():
            c = series[s]
            for i in range(max(desde, 200), hasta):
                if fn(p, i):
                    r = c[i + 1]["c"] / c[i]["c"] - 1 - 2 * FEE
                    memoria.observa(nombre, r)
    return memoria


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--historia", action="store_true",
                    help="recorrer el histórico entero y acumular evidencia")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--top", type=int, default=14)
    a = ap.parse_args()

    m = Memoria()
    if a.reset:
        m.reglas = {}
    if a.historia:
        from . import research
        series, _ = research.aligned(research.load())
        print(f"estudiando {len(series)} activos…")
        estudiar(m, series)
        m.guardar()

    r = m.resumen(a.top)
    print(f"\n{r['total']} reglas · {r['observaciones']:,} observaciones")
    print(f"APRENDIDAS {r['aprendidas']}  ·  DESCARTADAS {r['descartadas']}  ·  "
          f"en juicio {r['total'] - r['aprendidas'] - r['descartadas']}")
    print(f"avance medio de las que siguen en juicio: {r['progreso']:.0%}\n")
    print(f"{'regla':<26}{'estado':<13}{'n':>8}{'media':>10}{'t':>7}{'faltan':>9}")
    for f in r["reglas"]:
        media = f"{f['media']*100:+.3f}%"
        faltan = f"{f['faltan']:,}" if f["faltan"] else "—"
        print(f"{f['regla']:<26}{f['estado']:<13}{f['n']:>8,}{media:>10}"
              f"{f['t']:>7.2f}{faltan:>9}")


if __name__ == "__main__":
    main()
