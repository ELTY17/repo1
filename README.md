# Sala de Agentes — sistema multi-agente de trading (modo papel)

Cinco agentes autónomos que analizan cripto, el S&P 500 y el Nasdaq, votan, y
operan una cartera simulada. Con **dashboard visual en local**.

> **Esto opera con dinero simulado.** Los precios son reales; el dinero no.
> No hay ninguna ruta de código capaz de mover fondos reales: `LiveBroker`
> lanza `NotImplementedError` a propósito.

## Arrancar

Sin dependencias. Solo Python 3.10+.

```bash
python3 run.py                  # arranca el sistema + el dashboard del pulpo EN VIVO
python3 run.py --live           # conecta con Kraken en modo VALIDACIÓN (no ejecuta)
python3 -m tests.test_signature # la firma, contra el vector de Kraken
python3 -m tests.test_live      # el broker en vivo, contra un Kraken de mentira
python3 run.py --cash 250       # otro capital
python3 run.py --port 9000      # otro puerto
python3 -m bot.backtest         # backtest: 2 años de velas diarias reales
python3 -m bot.backtest --compare    # antes vs ahora
python3 -m bot.backtest --ablation   # qué aporta cada mejora por separado
python3 -m bot.montecarlo            # cono de ruina: 10.000 futuros posibles
python3 -m bot.backtest --fees       # cuánto aguanta según lo que cobre el exchange
python3 -m bot.oos                   # validación out-of-sample (el número honesto)
python3 -m bot.oos --real            # ...con comisión y mínimos reales
python3 -m bot.external              # contra estrategias reales y comprar y esperar
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

## Contra estrategias que la gente corre hoy

`python3 -m bot.external` porta la lógica de tres estrategias de
[freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies) —repositorio
con commits del mismo día— y las mide con las mismas reglas que todo lo demás:
comisión real del 0,26 %, mínimos de exchange y **comprar y esperar como vara de medir**,
que es la comparación que casi nadie se pone.

381 barras diarias, 5 activos, $100:

| Estrategia | Origen | Retorno | Máx. DD | Ops. | Acierto | PF |
|---|---|---|---|---|---|---|
| **Comprar y esperar** | la vara de medir | **−8,97 %** | — | 5 | 40 % | — |
| **Strategy001** | freqtrade-strategies | **−2,45 %** | −6,26 % | 10 | 90 % | 0,54 |
| Strategy002 | freqtrade-strategies | 0,00 % | 0,00 % | **0** | — | — |
| Supertrend | freqtrade-strategies | **−43,54 %** | −49,16 % | 90 | 21 % | 0,23 |
| La nuestra | este repo | −10,83 % | −32,28 % | 13 | 31 % | 0,62 |

Lo que sale de ahí:

- **Ninguna gana dinero.** El mercado cayó un 9 % en ese tramo y ninguna lo convirtió
  en beneficio.
- **Solo Strategy001 bate a comprar y esperar** (−2,45 % contra −8,97 %). Acierta el
  90 % de las veces pero su profit factor es 0,54: gana muchas veces poco y pierde
  pocas veces mucho. Su mérito aquí es perder menos, no ganar.
- **Supertrend se desploma** con sus valores por defecto: −43,5 % en 90 operaciones.
  Y hay un motivo concreto — sus tres supertrends vienen con los mismos parámetros
  (m=4, p=14), así que la triple confirmación que promete es en realidad una sola.
  Está escrita para hiperoptimizarla, y sin optimizar no vale.
- **Strategy002 no abrió ni una operación**: sus cuatro condiciones a la vez
  (RSI<30, estocástico<20, bajo la banda de Bollinger y martillo) no coinciden nunca
  en velas diarias.
- **La nuestra queda por debajo de comprar y esperar.**

Y un dato que lo tiñe todo: **494 órdenes rechazadas** por no llegar al mínimo del
exchange con $100 de capital.

Aviso honesto: Strategy001 y Strategy002 están escritas para velas de **5 minutos**.
No hay datos de 5 min suficientes para un backtest serio (Kraken da 720 velas: dos
días y medio), así que corren en otra temporalidad. Eso mide su lógica, no la
estrategia tal y como la corre su autor.

## Validación out-of-sample: no hay ventaja

`python3 -m bot.oos` parte las 400 barras en dos. En las primeras 240 repite la
elección de mejoras desde cero; en las últimas 160 —que no se miran al elegir— mide
lo elegido. Es la única forma de saber cuánto de lo medido era sobreajuste.

| Variante | Entrenamiento (0–240) | Prueba (240–400) |
|---|---|---|
| nada | −5,23 % | **+8,45 %** |
| adx | −5,30 % | +12,86 % |
| prot+trail | −2,27 % | +4,21 % |
| adx+prot+trail *(la del repo)* | −3,33 % | +9,93 % |

Tres cosas, y las tres son malas:

1. **Todas las variantes pierden en el primer tramo y ganan en el segundo.** El signo
   del resultado lo decide el tramo de mercado, no la estrategia. Eso no es una
   ventaja: es seguir al mercado con pasos extra.
2. **Elegir a ciegas no habría dado la combinación que lleva el repositorio.** Con solo
   el entrenamiento a la vista salía `prot+trail`, no `adx+prot+trail`. La elección
   anterior usó datos de prueba: era sobreajuste, y ahora está medido.
3. **Fuera de muestra las mejoras no baten a no hacer nada:** `prot+trail` da +4,21 %
   contra +8,45 % de la versión sin nada. Lo que parecía mejorar, empeora.

Con comisión real y mínimos de exchange (`--real`), el entrenamiento pierde entre
7,7 % y 9,5 % **en todas las variantes**, y la prueba da +3,39 % en 11 operaciones.

**Conclusión: este sistema no tiene ventaja demostrable sobre el mercado.** Funciona
como pieza de ingeniería —los agentes, el riesgo, las protecciones y las medidas hacen
lo que dicen— pero no como forma de ganar dinero.

## El mínimo del exchange decide todavía más

Kraken rechaza cualquier orden por debajo de su mínimo, y una acción de SPY cuesta
más que toda la cuenta. `bot/limits.py` consulta esos mínimos y el agente de riesgo
ya los comprueba antes de mandar nada. Con ellos activados el resultado cambia por
completo:

| Capital | Comisión | ¿Mínimos? | Retorno | Final | Ops. | Órdenes rechazadas |
|---|---|---|---|---|---|---|
| $100 | 0,10 % | no | +6,84 % | $106,84 | 36 | 0 |
| $100 | 0,10 % | **sí** | **−2,85 %** | $97,15 | 22 | 107 |
| $100 | 0,26 % | **sí** | **−4,11 %** | $95,89 | 22 | 107 |
| $19 | 0,26 % | **sí** | **−1,18 %** | $18,78 | 15 | 154 |

**Con dinero real y capital pequeño, esta estrategia pierde.** Todos los resultados
positivos de este repositorio asumían órdenes que un exchange habría rechazado.

Dos causas concretas:

- **SPY y QQQ son inoperables** por debajo de ~$2.200 de capital: el tamaño máximo
  por posición es el 35 % de la cuenta y una sola acción cuesta $762 / $716. Dos de
  los cinco instrumentos del universo están muertos, y con ellos la mitad no-cripto
  de la diversificación.
- El tamaño que dicta la regla del 2 % de riesgo **cae por debajo del mínimo de
  Kraken** en los activos más volátiles. Para colocar la orden habría que subir el
  tamaño, es decir, romper la propia regla de riesgo.

Comprobar esto es lo primero que hay que hacer antes de conectar nada:

```bash
python3 -m bot.backtest --fees        # sensibilidad a la comisión
python3 -c "from bot import limits, feeds; from bot.config import UNIVERSE; \
  [print(i.symbol, limits.min_notional(i, feeds.get_candles(i,timeframe='1d')[-1]['c'])) \
   for i in UNIVERSE]"
```

## La comisión decide

Todo lo anterior usa 0,10 % por lado, que es la tarifa de una cuenta con mucho
volumen. Una cuenta nueva paga bastante más, y eso cambia el resultado por completo:

| Comisión por lado | Retorno | Comisiones pagadas | Profit factor |
|---|---|---|---|
| 0,10 % — el que usábamos | +6,84 % | $2,14 | 1,35 |
| 0,16 % — Kraken Pro, volumen alto | +6,18 % | $3,39 | 1,35 |
| **0,26 % — Kraken taker, cuenta nueva** | **+3,27 %** | **$5,43** | 1,26 |
| 0,40 % — Kraken Instant Buy | −0,84 % | $8,20 | 1,14 |
| 0,60 % — Coinbase Advanced | −6,02 % | $12,00 | 1,00 |
| 1,49 % — Coinbase básico | −23,78 % | $17,60 | 0,39 |

**El punto en el que esto deja de compensar está entre 0,26 % y 0,40 % por lado.**
Ese margen es todo lo que separa una estrategia rentable de una que regala dinero al
exchange. Comprueba la tarifa que te aplican a ti antes de dar por bueno cualquier
número de este repositorio.

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
bot/kraken.py          cliente de la API de Kraken (firma HMAC verificada)
bot/live.py            broker real: parciales, idempotencia, stops en el exchange
bot/store.py           estado en SQLite: sobrevive a reinicios
bot/limits.py          mínimos de orden del exchange
bot/alerts.py          avisos cuando algo se sale de lo previsto
bot/oos.py             validación out-of-sample
bot/montecarlo.py      cono de ruina
bot/web/index.html     dashboard
tests/                 pruebas que corren sin credenciales
```

## Qué NO es esto

**No gana dinero.** No es una opinión prudente, está medido de tres formas
independientes y las tres coinciden:

- Con comisión real y mínimos de exchange, $100 dan **−4,11 %**.
- Fuera de muestra, las mejoras **no baten a no hacer nada**.
- El signo del resultado depende del tramo de mercado que mires, no de la estrategia.

Lo que sí hace bien es **no arruinarse rápido**: riesgo fijo, stops obligatorios,
protecciones de cartera y un interruptor de apagado. Y lo que hace mejor que nada es
**medirse a sí mismo con honestidad**, que es lo que permitió descubrir todo lo anterior.

Si algún día alguien conecta esto a dinero real, es su decisión y su riesgo. Con lo
que hay medido aquí, la recomendación es que no lo haga.

## Referencias y licencia

Este repositorio es **GPL-3.0**. Las protecciones de cartera y las reglas de salida
están portadas de [freqtrade](https://github.com/freqtrade/freqtrade) (GPL-3.0,
54.202 ★, el bot de trading más estrellado de GitHub); la arquitectura multi-agente
está inspirada en [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).
El detalle de qué viene de dónde está en **[`NOTICE.md`](NOTICE.md)**.

## El dashboard en vivo

`python3 run.py` levanta el sistema y sirve **el pulpo conectado a lo que está pasando
ahora mismo** en http://127.0.0.1:8787 — no una grabación. Cada dos segundos lee
`/api/state` y dibuja: el capital real, los votos que los agentes acaban de calcular,
sus contadores de ciclos, la conversación que están teniendo, las velas del activo en
juego y los 22 instrumentos vigilados. Cuando un agente termina un ciclo, su brazo
manda un impulso; cuando se cierra una operación, el pulpo cambia la cara.

El servidor expone además:

| Endpoint | Qué da |
|---|---|
| `/api/state` | todo el estado vivo: agentes, votos, posiciones, operaciones, eventos |
| `/api/candles?symbol=` | velas diarias reales del instrumento |
| `/api/wide` | los 22 instrumentos vigilados |
| `/api/research` | backtest, ablación y Monte Carlo, calculados al arrancar en segundo plano |

## Demos estáticas

Reproducen una sesión grabada del backtest. Se abren con doble clic, sin servidor:

- **`demo/taller.html`** — **PULPO DESK** en formato horizontal: una fila de columnas
  a pantalla completa que se recorre de izquierda a derecha con flechas o rueda. Velas diarias reales del
  activo en juego, el anillo con los cinco agentes y el cerebro, el horno con el resultado
  de cada operación cerrada, el cono de ruina, un cartograma de 22 instrumentos vigilados,
  el registro de órdenes y la cinta de lo que se dicen entre ellos. Todo reproduce la
  sesión medida de 402 barras.

  Los cinco agentes son bichos con ojos y el cerebro es el pulpo. La metáfora no es
  decorativa: dos tercios de las neuronas de un pulpo están en los brazos, que perciben
  y actúan por su cuenta y solo mandan un resumen al cerebro. Es literalmente esta
  arquitectura — cinco hilos independientes y un orquestador que solo recibe votos.
- **`demo/mosaico.html`** — el mismo sistema en **cuadrícula**: todo visible de una
  sola mirada, sin scroll ninguno, con el pulpo ocupando la fila de abajo. Pensado
  para pantalla de ordenador; comprobado a 1920×1080, 1512×982 y 1366×768. En
  vertical o por debajo de 1150px se apila.
- **`demo/cuadrilla.html`** — **LA CUADRILLA**, la misma sesión con los seis agentes
  como personajes trabajando codo con codo en una sola consola, en paleta roja. Cada uno
  con su cacharro delante y su piloto en el frontal; los votos viajan por la barra de luz
  hasta el Director. Mismos paneles de datos que el puesto de mando.
- **`demo/mesa.html`** — el mismo backtest en formato panel de instrumentos.

El dashboard con datos en vivo es el de `python3 run.py`.

### El Director

En el código, el Director es el **orquestador** (`bot/orchestrator.py`): combina los
tres votos direccionales con sus pesos, y solo abre posición si el agente de riesgo
lo aprueba. Los otros cinco agentes son hilos independientes con su propia cadencia.
