# Sala de Agentes — sistema multi-agente de trading (modo papel)

Cinco agentes autónomos que analizan cripto, el S&P 500 y el Nasdaq, votan, y
operan una cartera simulada. Con **dashboard visual en local**.

> **Esto opera con dinero simulado.** Los precios son reales; el dinero no.
> No hay ninguna ruta de código capaz de mover fondos reales: `LiveBroker`
> lanza `NotImplementedError` a propósito.

## Arrancar

Sin dependencias. Solo Python 3.10+.

```bash
python3 run.py                  # $100 simulados, dashboard en http://127.0.0.1:8787
python3 run.py --cash 250       # otro capital
python3 run.py --port 9000      # otro puerto
python3 -m bot.backtest         # backtest sobre histórico real
```

## Los cinco agentes

Cada uno corre en su propio hilo, con su propia cadencia.

| Agente | Qué hace | Cadencia |
|---|---|---|
| **`news`** | Lee titulares reales (Cointelegraph, WSJ Markets, Google News) y puntúa el sentimiento con un léxico financiero, por instrumento. | 180 s |
| **`scanner`** | Recorre el universo y lo rankea por fuerza relativa: momentum a 6h/24h/72h normalizado por volatilidad, más volumen anormal (z-score). | 60 s |
| **`technical`** | RSI(14), cruce EMA 12/26, histograma MACD, posición en las bandas de Bollinger y ATR(14) para calcular el stop. | 30 s |
| **`risk`** | **Poder de veto.** Dimensiona cada posición, coloca el stop y vigila la cuenta. Puede apagar el sistema entero. | 15 s |
| **`execution`** | Manda las órdenes al bróker y vigila las abiertas: stop-loss, take-profit y subida del stop a break-even en +1R. | 10 s |

El **orquestador** combina los tres votos direccionales
(`técnico 0.45 · escáner 0.30 · noticias 0.25`) en un score compuesto por activo.
Si supera `+0.35`, pide permiso al agente de riesgo; solo si lo aprueba se manda la orden.

```
news ──┐
scan ──┼──► score compuesto ──► agente de riesgo (veto) ──► ejecución ──► bróker papel
tech ──┘
```

## Reglas de riesgo (las importantes)

- **2%** del equity arriesgado por operación — el tamaño sale de la distancia al stop, no al revés.
- **Stop** a 2×ATR de la entrada. **Objetivo** a 2R. En +1R el stop sube a break-even.
- Máximo **3 posiciones** simultáneas, **35%** del equity en un solo activo, **2** por clase de activo.
- **Kill switch**: si el drawdown desde el pico llega a **-25%**, cierra todo y deja de abrir.
- Comisión 0,10% por lado y slippage 0,05% aplicados en cada ejecución.

## Universo

`BTC-USD`, `ETH-USD`, `SOL-USD` (Kraken) · `SPY` = S&P 500, `QQQ` = Nasdaq 100 (Yahoo Finance).

Si una fuente falla, el sistema mantiene la última vela buena y marca el instrumento
como *degradado* en el dashboard, en vez de operar a ciegas.

## Estructura

```
run.py                 arranque + dashboard
bot/config.py          capital, riesgo, umbrales, pesos de voto
bot/feeds.py           datos de mercado reales (+ fallback)
bot/indicators.py      RSI, EMA, MACD, ATR, Bollinger (Python puro)
bot/broker.py          bróker en papel · LiveBroker bloqueado
bot/orchestrator.py    agrega votos y decide
bot/backtest.py        replay de la misma lógica sobre histórico
bot/agents/            los cinco agentes
bot/web/index.html     dashboard
```

## Qué NO es esto

No es una máquina de ganar dinero. Un backtest de 13 días con 7 operaciones no
demuestra nada, y esta lógica es de reglas simples sobre indicadores públicos:
no tiene ninguna ventaja estructural frente al mercado. Lo que sí hace bien es
**no arruinarse rápido**: riesgo fijo, stops obligatorios y un interruptor de apagado.

Si algún día alguien conecta esto a dinero real, es su decisión y su riesgo.

## Referencias

Arquitectura inspirada en [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
(framework multi-agente LLM para trading) y en la gestión de riesgo de
[freqtrade](https://github.com/freqtrade/freqtrade).

## Demo estática

`demo/mesa.html` reproduce visualmente la sesión de backtest (las 14 órdenes
reales, la curva de capital real) sin necesidad de servidor: se abre con doble clic.
El dashboard en vivo con datos actualizados es el de `python3 run.py`.
