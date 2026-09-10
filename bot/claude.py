"""Conectar el bot con la API de Claude, con freno de mano.

Esto NO llama a nadie mientras no haya una clave en el entorno. Sin
ANTHROPIC_API_KEY el modulo se comporta como si Claude no existiera y el bot
sigue funcionando exactamente igual, porque los cinco agentes de calculo no
necesitan un modelo para nada.

Cuando SI hay clave, dos cosas mandan sobre todo lo demas:

  1. Un presupuesto en dolares. Cada llamada estima su coste antes y lo suma
     despues con el uso real que devuelve la API. Pasado el tope, se apaga
     solo. No hay modo "sin limite": el techo es obligatorio.

  2. Una cadencia minima. El sistema opera velas diarias; preguntar cada
     veinte segundos son 4.320 opiniones al dia sobre un grafico que cambia
     una vez, y 270 $/dia (ver `python3 -m bot.coste`).

Modelo por defecto: claude-opus-5.
"""
from __future__ import annotations

import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request

API = "https://api.anthropic.com/v1/messages"
VERSION = "2023-06-01"
MODELO = "claude-opus-5"

# Precios publicados, dolares por millon de tokens: entrada / salida.
PRECIOS = {
    "claude-opus-5":   (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


class SinClave(RuntimeError):
    pass


class Presupuesto:
    """Techo de gasto. Cuando se acaba, se acaba: no hay reintento."""

    def __init__(self, tope_usd: float):
        self.tope = float(tope_usd)
        self.gastado = 0.0
        self.llamadas = 0
        self._lock = threading.Lock()

    def queda(self):
        return max(0.0, self.tope - self.gastado)

    def apunta(self, modelo: str, entrada: int, salida: int):
        p_in, p_out = PRECIOS.get(modelo, PRECIOS[MODELO])
        coste = entrada * p_in / 1e6 + salida * p_out / 1e6
        with self._lock:
            self.gastado += coste
            self.llamadas += 1
        return coste

    def hay(self, estimado: float = 0.05):
        return self.queda() >= estimado

    def dict(self):
        return {"tope": round(self.tope, 2), "gastado": round(self.gastado, 4),
                "queda": round(self.queda(), 4), "llamadas": self.llamadas}


class Claude:
    """Cliente minimo sobre la API de mensajes. Solo stdlib, como el resto."""

    def __init__(self, clave: str | None = None, modelo: str = MODELO,
                 tope_usd: float = 1.0, cada_segundos: int = 3600):
        self.clave = clave if clave is not None else os.environ.get("ANTHROPIC_API_KEY", "")
        self.modelo = modelo
        self.presupuesto = Presupuesto(tope_usd)
        self.cada = max(cada_segundos, 300)      # nunca por debajo de 5 minutos
        self.ultima = 0.0
        self.ultimo_error = ""
        self.historial: list[dict] = []

    @property
    def disponible(self) -> bool:
        return bool(self.clave)

    def puede_preguntar(self) -> tuple[bool, str]:
        if not self.disponible:
            return False, "sin ANTHROPIC_API_KEY: el bot funciona igual, sin modelo"
        if not self.presupuesto.hay():
            return False, f"presupuesto agotado (${self.presupuesto.tope:.2f})"
        espera = self.cada - (time.time() - self.ultima)
        if espera > 0:
            return False, f"cadencia: faltan {espera/60:.0f} min"
        return True, ""

    def preguntar(self, sistema: str, mensaje: str, max_tokens: int = 900):
        """Una consulta. Devuelve (texto, uso) o lanza SinClave."""
        ok, motivo = self.puede_preguntar()
        if not ok:
            raise SinClave(motivo)

        cuerpo = json.dumps({
            "model": self.modelo,
            "max_tokens": max_tokens,
            "system": sistema,
            "messages": [{"role": "user", "content": mensaje}],
        }).encode()
        req = urllib.request.Request(API, data=cuerpo, method="POST", headers={
            "content-type": "application/json",
            "x-api-key": self.clave,
            "anthropic-version": VERSION,
        })
        self.ultima = time.time()
        try:
            with urllib.request.urlopen(req, timeout=120,
                                        context=ssl.create_default_context()) as r:
                d = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            self.ultimo_error = f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
            raise
        except Exception as e:                               # noqa: BLE001
            self.ultimo_error = f"{type(e).__name__}: {e}"
            raise

        uso = d.get("usage", {})
        ent = uso.get("input_tokens", 0) + uso.get("cache_read_input_tokens", 0)
        sal = uso.get("output_tokens", 0)
        coste = self.presupuesto.apunta(d.get("model", self.modelo), ent, sal)
        texto = "".join(b.get("text", "") for b in d.get("content", [])
                        if b.get("type") == "text")
        self.historial.append({"t": int(time.time()), "coste": round(coste, 5),
                               "entrada": ent, "salida": sal,
                               "resumen": texto[:180]})
        self.historial = self.historial[-25:]
        return texto, {"entrada": ent, "salida": sal, "coste": coste}

    def estado(self):
        ok, motivo = self.puede_preguntar()
        return {
            "disponible": self.disponible,
            "modelo": self.modelo,
            "puede": ok, "motivo": motivo,
            "cada_min": round(self.cada / 60),
            "presupuesto": self.presupuesto.dict(),
            "ultimo_error": self.ultimo_error,
            "historial": self.historial[-6:][::-1],
        }


if __name__ == "__main__":
    c = Claude()
    e = c.estado()
    print(json.dumps(e, indent=2, ensure_ascii=False))
    if not e["disponible"]:
        print("\nNo hay clave, y eso esta bien: el bot no la necesita para operar.")
        print("Para darle una, en TU maquina y en TU .env:")
        print("  ANTHROPIC_API_KEY=sk-ant-...")
        print("Nunca la pegues en un chat, ni aqui ni en ningun sitio.")
