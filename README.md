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
python3 -m bot.backtest         # backtest: 2 años de velas diarias reales
python3 -m bot.backtest --compare    # antes vs ahora
python3 -m bot.backtest --ablation   # qué aporta cada mejora por separado
python3 -m bot.montecarlo            # cono de ruina: 10.000 futuros posibles
```

## Los cinco agentes

Cada uno corre en su propio hilo, con su propia cadencia.

| Agente | Qué hace | Cadencia |
|---|---|---|
| **`news`** | Lee titulares reales (Cointelegraph, WSJ Markets, Google News) y puntúa el sentimiento con un léxico financiero, por instrumento. | 180 s |
| **`scanner`** | Recorre el universo y lo rankea por fuerza relativa: momentum a 6h/24h/72h normalizado por volatilidad, más volumen anormal (z-score). | 60 s |
| **`technical`** | RSI(14), cruce EMA 12/26, histograma MACD, bandas de Bollinger, ATR(14) para el stop y **ADX(14)** para medir si hay tendencia o es lateral. | 30 s |
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
- **Stop** a 2×ATR de la entrada. **Objetivo** a 2R.
- **Trailing stop**: pasado +2×ATR de beneficio, el stop persigue al precio a 1,5×ATR y nunca baja.
- Máximo **3 posiciones** simultáneas, **35%** del equity en un solo activo, **2** por clase de activo.
- **Protecciones de cartera** (portadas de freqtrade, ver `NOTICE.md`):
  enfriamiento de 3 h tras operar un activo, parada global tras 3 stops en 24 h,
  bloqueo de un activo que acumula pérdidas, y bloqueo global por drawdown de la ventana.
- **Kill switch**: si el drawdown desde el pico llega a **-25%**, cierra todo y deja de abrir.
- Comisión 0,10% por lado y slippage 0,05% aplicados en cada ejecución.

## Qué mejora cada cosa (medido, no supuesto)

`python3 -m bot.backtest --ablation` mide cada añadido por separado sobre 402 velas
diarias reales (~1,1 años, 5 activos):

| Variante | Retorno | Máx. drawdown | Ops. | Acierto | Profit factor |
|---|---|---|---|---|---|
| nada | +3,35 % | −11,59 % | 34 | 35 % | 1,16 |
| solo ADX | +7,55 % | −12,45 % | 35 | 34 % | 1,32 |
| solo protecciones | +1,01 % | −10,67 % | 30 | 30 % | 1,08 |
| solo trailing | +1,78 % | −10,43 % | 36 | 50 % | 1,11 |
| solo escalera ROI | +1,42 % | −12,54 % | 40 | 48 % | 1,09 |
| solo filtro de régimen | +3,35 % | −11,59 % | 34 | 35 % | 1,16 |
| **`adx` + `prot` + `trail`** | **+6,93 %** | **−10,89 %** | 36 | 56 % | **1,36** |

Dos cosas se quedaron **fuera** tras medirlas:

- La **escalera ROI** de freqtrade cerraba a los ganadores demasiado pronto: subía el
  acierto al 48 % pero hundía el profit factor. Está implementada y se puede activar
  (`features`), pero por defecto no.
- El **filtro de régimen** (no comprar bajo la EMA50) no cambió ni una sola operación:
  para llegar al umbral de compra ya hace falta un momentum que implica estar por encima.

Advertencia honesta: elegir la mejor combinación sobre la misma muestra con la que se
mide es, en parte, sobreajustar a esa muestra. 36 operaciones en un año no demuestran
que esto funcione.

## Universo

Se **opera** en cinco: `BTC-USD`, `ETH-USD`, `SOL-USD` (Kraken) · `SPY` = S&P 500,
`QQQ` = Nasdaq 100 (Yahoo Finance).

Se **vigilan** 22: `feeds.wide_universe()` trae en una sola llamada 18 pares de Kraken
más SPY, QQQ, DIA e IWM. Mirar más mercado del que se opera sale casi gratis y dice en
qué estado está el conjunto.

## Cono de ruina

`python3 -m bot.montecarlo` coge las operaciones cerradas del backtest, las remuestrea
con reemplazo 10.000 veces y simula futuros de 100 operaciones aplicando el mismo
kill switch. Con la distribución medida: mediana **+22,9 %**, acaba en verde el
**88 %** de las veces, el freno salta en el **1,8 %** y la cuenta **nunca** pierde la
mitad.

Dicho lo cual, hay un sesgo que conviene tener presente: esas operaciones salen de un
solo tramo de mercado que resultó favorable. Un bootstrap solo puede repartir lo que ya
ocurrió — no sabe inventar el crash que no estaba en la muestra.

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

## Referencias y licencia

Este repositorio es **GPL-3.0**. Las protecciones de cartera y las reglas de salida
están portadas de [freqtrade](https://github.com/freqtrade/freqtrade) (GPL-3.0,
54.202 ★, el bot de trading más estrellado de GitHub); la arquitectura multi-agente
está inspirada en [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).
El detalle de qué viene de dónde está en **[`NOTICE.md`](NOTICE.md)**.

## Demos estáticas

Ambas se abren con doble clic, sin servidor:

- **`demo/taller.html`** — **PULPO DESK**, el puesto de mando. Velas diarias reales del
  activo en juego, el anillo con los cinco agentes y el cerebro, el horno con el resultado
  de cada operación cerrada, el cono de ruina, un cartograma de 22 instrumentos vigilados,
  el registro de órdenes y la cinta de lo que se dicen entre ellos. Todo reproduce la
  sesión medida de 402 barras.

  Los cinco agentes son bichos con ojos y el cerebro es el pulpo. La metáfora no es
  decorativa: dos tercios de las neuronas de un pulpo están en los brazos, que perciben
  y actúan por su cuenta y solo mandan un resumen al cerebro. Es literalmente esta
  arquitectura — cinco hilos independientes y un orquestador que solo recibe votos.
- **`demo/mesa.html`** — el mismo backtest en formato panel de instrumentos.

El dashboard con datos en vivo es el de `python3 run.py`.

### El Director

En el código, el Director es el **orquestador** (`bot/orchestrator.py`): combina los
tres votos direccionales con sus pesos, y solo abre posición si el agente de riesgo
lo aprueba. Los otros cinco agentes son hilos independientes con su propia cadencia.
