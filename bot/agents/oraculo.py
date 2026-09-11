"""El octavo agente: Claude, y solo cuando hace falta.

Los siete agentes de calculo no necesitan un modelo para nada: leen precios y
sacan numeros. Este es distinto — es un ULTIMO FILTRO delante de la orden, y
por eso tiene tres reglas que no se negocian:

  1. **Nunca inventa operaciones.** Solo puede confirmar o vetar un candidato
     que ya han elegido los otros siete. Un modelo de lenguaje que propone
     que comprar es un generador de excusas caras: no tiene precios en la
     cabeza, tiene texto.

  2. **Se le pregunta cuando hay algo que preguntar.** No cada veinte
     segundos. El sistema opera velas diarias y solo el 11% de los dias hay
     candidato: preguntar en cada tic son 4.320 opiniones al dia sobre un
     grafico que se mueve una vez. Ese era el gasto de 270 $/dia que midio
     `python3 -m bot.coste`, y no lo causaba el modelo sino la cadencia.

  3. **Si falla, el bot sigue.** Sin clave, sin presupuesto, sin red o con una
     respuesta que no se entiende, la respuesta es "sin opinion" y la decision
     vuelve a ser exactamente la de los siete agentes. Nunca bloquea por
     averia, solo por criterio.

Coste real con esta cadencia (precios publicados, 2026):

    ~370 tokens de entrada + ~60 de salida por consulta
    claude-opus-5   -> 0,0034 $ por consulta -> 0,020 $/dia con 6 consultas
    claude-haiku-4-5 -> 0,0007 $ por consulta -> 0,004 $/dia

O sea: el modelo caro, preguntando cuando toca, cuesta dos centimos al dia.
El problema nunca fue el modelo; era preguntarle 4.320 veces.

No se usa cache de prompt a proposito: el prefijo cacheable minimo son 512 -
4.096 tokens segun modelo y este sistema entero ocupa ~250. Marcarlo como
cacheado no cachearia nada y solo daria la sensacion de estar ahorrando.
"""
from __future__ import annotations

import json
import os
import time

from ..claude import MODELO, PRECIOS, Claude, SinClave
from .base import Agent

SISTEMA = (
    "Eres el ultimo filtro de un bot de trading de criptomonedas que opera en "
    "papel. Recibes un candidato que ya han aprobado siete agentes de calculo "
    "y el estado de la cartera. Tu unico trabajo es decir si esa compra "
    "concreta tiene sentido o si hay una razon para no hacerla ahora.\n"
    "No propongas otros activos. No des consejo financiero. No expliques que "
    "es el RSI.\n"
    "Veta solo con una razon concreta y visible en los numeros que te dan: "
    "senal contradictoria entre agentes, concentracion en lo mismo, volatilidad "
    "que no cuadra con el tamano, o una racha de perdidas que aconseje parar.\n"
    "Responde SOLO con este JSON, sin texto alrededor:\n"
    '{"ok": true|false, "confianza": 0.0-1.0, "motivo": "<12 palabras maximo>"}'
)


class OracleAgent(Agent):
    """Consejero. Ni calcula ni propone: confirma o veta, y casi nunca habla."""

    name = "oraculo"
    role = "ultimo filtro"
    emoji = "?"
    interval = 60                      # solo para refrescar su estado en pantalla

    def __init__(self, ctx):
        super().__init__(ctx)
        modelo = os.environ.get("ANTHROPIC_MODELO", MODELO)
        if modelo not in PRECIOS:
            modelo = MODELO
        self.claude = Claude(
            modelo=modelo,
            tope_usd=float(os.environ.get("CLAUDE_TOPE_USD", "0.50")),
            cada_segundos=int(os.environ.get("CLAUDE_CADA_SEG", "600")),
        )
        self.max_dia = int(os.environ.get("CLAUDE_MAX_DIA", "12"))
        self.consultas_hoy = 0
        self._dia = time.gmtime().tm_yday
        self.ultimo: dict = {}
        self.vetos = 0
        self.confirmaciones = 0

    # --- el estado que se ve en pantalla ---
    def step(self):
        self.output = {
            "claude": self.claude.estado(),
            "consultas_hoy": self.consultas_hoy,
            "max_dia": self.max_dia,
            "vetos": self.vetos,
            "confirmaciones": self.confirmaciones,
            "ultimo": self.ultimo,
        }

    # --- lo unico que hace de verdad ---
    def opina(self, sym: str, c: dict, precio: float, plan: dict,
              lectura: dict | None = None) -> dict:
        """Confirma o veta UN candidato. Nunca lanza: devuelve por que no pudo."""
        hoy = time.gmtime().tm_yday
        if hoy != self._dia:
            self._dia, self.consultas_hoy = hoy, 0

        if self.consultas_hoy >= self.max_dia:
            return self._sin_opinion(f"tope de {self.max_dia} consultas hoy")
        ok, motivo = self.claude.puede_preguntar()
        if not ok:
            return self._sin_opinion(motivo)

        lectura = lectura or {}
        pos = getattr(self.ctx.broker, "positions", {}) or {}
        # Todo el mensaje es una linea de numeros. Cuanto mas corto, mas barato
        # y menos sitio para que el modelo se invente contexto.
        mensaje = json.dumps({
            "activo": sym,
            "precio": round(precio, 6),
            "score": c.get("score"),
            "votos": c.get("votes"),
            "consenso": c.get("consensus"),
            "rsi": lectura.get("rsi"),
            "adx": lectura.get("adx"),
            "atr_pct": round((lectura.get("atr") or 0) / precio * 100, 2) if precio else None,
            "tamano_usd": round(plan.get("size_usd", 0), 2),
            "stop": plan.get("stop"),
            "abiertas": list(pos),
            "equity": round(self.ctx.broker.equity(self.ctx.prices()), 2),
        }, ensure_ascii=False, separators=(",", ":"))

        try:
            texto, uso = self.claude.preguntar(SISTEMA, mensaje, max_tokens=120)
        except SinClave as e:
            return self._sin_opinion(str(e))
        except Exception as e:                            # noqa: BLE001
            # una averia de red no puede impedir operar: eso seria un veto
            # disfrazado, y ademas uno que nadie decidio
            return self._sin_opinion(f"fallo al preguntar: {type(e).__name__}")

        self.consultas_hoy += 1
        veredicto = self._leer(texto)
        veredicto["coste"] = round(uso.get("coste", 0), 5)
        veredicto["modelo"] = self.claude.modelo
        self.ultimo = {"t": int(time.time()), "activo": sym, **veredicto}
        if veredicto["fuente"] == "claude":
            if veredicto["ok"]:
                self.confirmaciones += 1
            else:
                self.vetos += 1
            self.say(f"{sym}: {'confirma' if veredicto['ok'] else 'VETA'} · "
                     f"{veredicto['motivo']} · ${veredicto['coste']:.4f}")
        return veredicto

    # --- detalles ---
    @staticmethod
    def _sin_opinion(motivo: str) -> dict:
        """Sin opinion NO es un veto: la decision se queda como estaba."""
        return {"ok": True, "confianza": 0.0, "motivo": motivo, "fuente": "sin opinion"}

    def _leer(self, texto: str) -> dict:
        """Una respuesta que no se entiende vale lo mismo que no preguntar.

        Nada de rescatar a medias un JSON roto: si el modelo no ha contestado
        en el formato acordado, no se sabe lo que quiso decir, y actuar sobre
        una suposicion es peor que no actuar.
        """
        t = (texto or "").strip()
        if t.startswith("```"):
            t = t.strip("`")
            t = t.split("\n", 1)[-1] if "\n" in t else t
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            return self._sin_opinion("respuesta ilegible")
        try:
            d = json.loads(t[i:j + 1])
            return {"ok": bool(d["ok"]),
                    "confianza": max(0.0, min(1.0, float(d.get("confianza", 0.5)))),
                    "motivo": str(d.get("motivo", ""))[:90],
                    "fuente": "claude"}
        except Exception:                                 # noqa: BLE001
            return self._sin_opinion("respuesta ilegible")


if __name__ == "__main__":
    for m, (pin, pout) in PRECIOS.items():
        c = 370 * pin / 1e6 + 60 * pout / 1e6
        print(f"{m:18s} {c:.4f} $/consulta   {c*6:.4f} $/dia con 6 consultas")
