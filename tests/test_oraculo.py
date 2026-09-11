"""El octavo agente, probado sin clave y sin red.

Lo que importa de este agente no es lo que dice Claude: es que el bot siga
funcionando igual cuando Claude no esta, y que una respuesta rara no se
convierta nunca en una decision.
"""
from __future__ import annotations

import json

from bot.agents.oraculo import OracleAgent


class CtxFalso:
    """Lo minimo que el agente le pide al orquestador."""

    class Broker:
        positions: dict = {}

        def equity(self, _prices):
            return 100.0

    def __init__(self):
        self.broker = self.Broker()

    def prices(self):
        return {}

    def feed_event(self, _e):
        pass

    def debug(self, _m):
        pass


C = {"score": 0.42, "votes": {"news": 0.1, "scanner": 0.3, "technical": 0.5},
     "consensus": 1.0}
PLAN = {"size_usd": 19.4, "stop": 98.2}


def test_sin_clave_no_bloquea():
    """Sin ANTHROPIC_API_KEY el veredicto es 'adelante, sin opinion'."""
    ag = OracleAgent(CtxFalso())
    ag.claude.clave = ""
    v = ag.opina("BTC-USD", C, 100.0, PLAN)
    assert v["ok"] is True
    assert v["fuente"] == "sin opinion"
    assert ag.consultas_hoy == 0          # ni siquiera lo intenta


def test_fallo_de_red_no_es_un_veto():
    ag = OracleAgent(CtxFalso())
    ag.claude.clave = "sk-ant-de-mentira"
    ag.claude.cada = 0
    def revienta(*a, **k):
        raise ConnectionError("sin red")
    ag.claude.preguntar = revienta
    v = ag.opina("BTC-USD", C, 100.0, PLAN)
    assert v["ok"] is True, "una averia no puede vetar: seria un veto que nadie decidio"
    assert v["fuente"] == "sin opinion"


def test_lee_el_veto():
    ag = OracleAgent(CtxFalso())
    ag.claude.clave = "sk-ant-de-mentira"
    ag.claude.cada = 0
    ag.claude.preguntar = lambda s, m, **k: (
        '{"ok": false, "confianza": 0.8, "motivo": "ya hay dos de lo mismo"}',
        {"coste": 0.003})
    v = ag.opina("BTC-USD", C, 100.0, PLAN)
    assert v["ok"] is False
    assert v["fuente"] == "claude"
    assert ag.vetos == 1


def test_json_en_bloque_de_codigo():
    """Los modelos envuelven en ``` a veces. Eso si se rescata."""
    ag = OracleAgent(CtxFalso())
    ag.claude.clave = "x"; ag.claude.cada = 0
    ag.claude.preguntar = lambda s, m, **k: (
        '```json\n{"ok": true, "confianza": 0.6, "motivo": "vale"}\n```', {"coste": 0})
    assert ag.opina("BTC-USD", C, 100.0, PLAN)["fuente"] == "claude"


def test_respuesta_ilegible_no_decide():
    ag = OracleAgent(CtxFalso())
    ag.claude.clave = "x"; ag.claude.cada = 0
    ag.claude.preguntar = lambda s, m, **k: ("pues mira, yo compraria", {"coste": 0})
    v = ag.opina("BTC-USD", C, 100.0, PLAN)
    assert v["ok"] is True and v["fuente"] == "sin opinion"


def test_tope_diario():
    ag = OracleAgent(CtxFalso())
    ag.claude.clave = "x"; ag.claude.cada = 0
    ag.max_dia = 2
    ag.claude.preguntar = lambda s, m, **k: (
        '{"ok": true, "confianza": 1, "motivo": "ok"}', {"coste": 0.003})
    for _ in range(5):
        ag.opina("BTC-USD", C, 100.0, PLAN)
    assert ag.consultas_hoy == 2, "el tope diario es un tope, no una sugerencia"


def test_el_mensaje_es_corto():
    """Si el mensaje engorda, engorda la factura. Se vigila aqui."""
    ag = OracleAgent(CtxFalso())
    ag.claude.clave = "x"; ag.claude.cada = 0
    visto = {}
    def espia(sistema, mensaje, **k):
        visto["m"] = mensaje
        return '{"ok": true, "confianza": 1, "motivo": "ok"}', {"coste": 0}
    ag.claude.preguntar = espia
    ag.opina("BTC-USD", C, 100.0, PLAN)
    assert len(visto["m"]) < 400, f"mensaje de {len(visto['m'])} caracteres"
    json.loads(visto["m"])                # y sigue siendo JSON valido


def test_nunca_propone_operaciones():
    """El sistema le prohibe elegir activo: solo juzga el que le dan."""
    from bot.agents.oraculo import SISTEMA
    assert "No propongas otros activos" in SISTEMA


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ✓ {nombre}")
            except AssertionError as e:
                fallos += 1
                print(f"  ✗ {nombre}: {e}")
    total = sum(1 for n in globals() if n.startswith("test_"))
    print(f"\n{total - fallos}/{total} pruebas pasan")
