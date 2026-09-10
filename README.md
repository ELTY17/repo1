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

## El sexto agente: correlación

Los otros cinco miran cada activo por separado. Este mira lo que tienen en
común, que es lo que nadie estaba mirando. **No vota dirección**: es el único
que no opina de si algo va a subir, opina de si ya lo tienes.

El tope de posiciones por clase era un número fijo. Decía "no más de dos
criptos" porque midiendo salió que cuatro empeoraban, pero no sabía **por qué**:
no distinguía entre comprar BTC y ETH —la misma apuesta con dos nombres— y
comprar BTC y ATOM. Correlación de Pearson sobre los rendimientos diarios de los
últimos 60 días:

```
QQQ ~ SPY           0.89        NEAR ~ SPY    -0.10
BTC ~ XRP           0.88        SOL  ~ SPY    -0.10
BTC ~ ETH           0.87        ATOM ~ QQQ    -0.15
XLM ~ XRP           0.86        ATOM ~ SPY    -0.19

correlación media del universo: 0.48
24 de 171 pares por encima de 0.75 (14%)
```

El veto mira la correlación **máxima**, no la media: una media baja puede
esconder un par idéntico. Medido en cuatro ventanas fuera de muestra:

```
variante                    v1        v2        v3        v4     media
tope 2 (el parche)      -0.94%    -5.78%    +3.30%    +7.05%    +0.91%
tope 4, sin correlación -1.87%   -10.43%    -6.91%   +16.62%    -0.65%
tope 4 + correlación    -2.49%    -8.38%    -2.35%   +17.45%    +1.06%
```

Subir el tope sin medir correlación cuesta 1,56 puntos. **El agente los
recupera.** Lo que no hace es batir al parche por un margen demostrable
(+1,06% contra +0,91% en cuatro ventanas es ruido). Lo que sí hace es
convertir un número mágico en una medición que se explica sola.

## Vender en corto: probado y no aporta

*"Con todos los mercados que hay tiene que saber cuándo vender también."* Es
verdad que el sistema solo compraba. Ahora sabe abrir cortos —`bot/broker.py`
lleva `side` en la posición, `short()` y `funding()`— y el backtest los opera
con `allow_shorts`.

En la muestra entera parecía una mejora: **+1,67% con cortos contra +1,27%
sin ellos**, y menos drawdown. Fuera de muestra:

```
ventana            sin cortos   con cortos       dif   ops corto
barras 0-100           -0.94%       -3.45%    -2.51%          33
barras 100-200         -5.78%       -3.02%    +2.76%          74
barras 200-300         +3.30%       +3.63%    +0.33%          10
barras 300-400         +7.05%       +4.87%    -2.18%          20

ayuda en 2 de 4 ventanas · media -0.40%
```

Y no es el coste de financiación: quitando el rollover de Kraken (0,06%/día)
la diferencia se mueve entre 0,10 y 0,67 puntos, nada. **El corto no acierta**,
simplemente. Las mismas señales que no saben cuándo subir tampoco saben cuándo
baja.

Queda apagado por defecto (`allow_shorts: False`) y la maquinaria queda hecha,
medida y documentada. Si algún día aparecen señales con ventaja, el otro lado
del mercado ya está construido.

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

## Barrido sistemático: 495 reglas, 19 activos, 2 años

Hasta aquí probábamos estrategias de una en una. `bot/sweep.py` hace lo contrario:
recorre un espacio grande de reglas simples y bien conocidas sobre **19 criptos de
Kraken × 720 velas diarias** (2024-09-20 → 2026-09-09), el mejor muestreo que hemos
tenido en este repo.

El espacio: momentum a 5/10/20/30/60/90/120 días y reversión a 1/3/5/10, cartera
equiponderada de 1, 3 o 5 activos, rotación cada 1, 5 o 10 días, con y sin filtro de
tendencia (`cierre > SMA` de 20/50/100/200). **495 combinaciones.**

El método es lo único que importa: la historia se parte en dos mitades operables, se
elige la mejor **mirando solo la primera**, y la segunda no se toca hasta que la
elección ya está hecha. Comisiones de Kraken (0,26% por lado) en cada rotación,
mínimo de orden del exchange, y comprar-y-esperar todo el universo como listón.

```
entreno 2025-04-08 → 2025-12-23 | prueba 2025-12-24 → 2026-09-09

ENTRENO — comprar y esperar: +0.39%
mom120 top1 rot10 >sma100            +51.73%      9 ops
rev3 top1 rot10                      +47.45%     49
mom5 top3 rot5                       +45.70%    229

PRUEBA (nunca vista) — elegida a ciegas: mom120 top1 rot10 >sma100
  regla             -44.94%  (21 ops)
  comprar y esperar -14.94%
  diferencia        -29.99%

  las 20 mejores del entreno, promedio en prueba: -32.41%
  reglas que baten al listón en prueba: 122/495 (25%)
```

Tres cosas que leer aquí:

1. **La ganadora del entreno hizo +51,73% y luego perdió 30 puntos contra no hacer
   nada.** Ese salto es exactamente lo que significa sobreajuste: con 495 intentos,
   alguna sale espectacular por azar.
2. **No fue mala suerte de una regla.** Las 20 mejores del entreno promedian −32,41%
   fuera de muestra. El tipo de regla tampoco aguanta.
3. **Solo el 25% del espacio le gana al listón fuera de muestra.** Al azar sería el
   50%. Rotar cartera no es neutro: las comisiones y los latigazos se comen valor de
   forma sistemática frente a comprar y esperar.

Veredicto: **sin ventaja demostrable**, otra vez, ahora con 495 intentos y un
muestreo cuatro veces mayor. Reproducible con `python3 -m bot.sweep`.

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

## Las 100 estrategias y el conmutador por régimen

`bot/playbook.py` reúne **105 reglas** en ocho familias — las que la gente corre de
verdad, no inventos: cruces de EMA y SMA (incluida la cruz dorada), RSI por los dos
lados, MACD, Bollinger, Donchian (las Tortugas), Supertrend, estocástico, ADX/DI,
Heikin-Ashi, SAR parabólico, Keltner, momentum y combos como la triple pantalla.
Cada una es una función `(pre, i) -> bool`, así que todas se miden con el mismo
listón y las mismas comisiones.

`bot/regime.py` es la parte de "que sepa cambiar según lo que pase": clasifica cada
día en cuatro regímenes usando **solo datos pasados** (índice equiponderado contra su
SMA50; volatilidad de 20 días contra su mediana histórica) y asigna a cada régimen la
estrategia que mejor se portó **en el entrenamiento**. Cambiar de estrategia paga
comisión, como en la vida real.

```
alcista tranquilo  →  adx>25 +di>-di      +48.50%   (listón +14.23%)
alcista nervioso   →  roc5<-5% (rebote)    +3.76%   (listón  -8.51%)
bajista tranquilo  →  2 supertrend        +54.34%   (listón  -4.16%)
bajista nervioso   →  bb20 2.5 baja       +14.51%   (listón  -8.18%)

PRUEBA (nunca vista)
  conmutador por régimen   +8.55%
  mejor suelta (rsi7<25)  -38.21%
  comprar y esperar       -26.36%
```

Parece el hallazgo del año: +34,91 puntos sobre no hacer nada. **No lo es**, y
`python3 -m bot.regime --robust` es lo que lo demuestra:

```
VENTANAS SUCESIVAS   gana al listón en 1/3 · diferencia media +2.64%
CONTRA EL AZAR       400 asignaciones aleatorias: mediana -26.11%, p90 +32.69%
                     la nuestra: +8.55% → percentil 80
```

Traducido: el p90 del azar ya supera nuestro resultado, y en ventanas sucesivas gana
una de tres. La cifra buena venía de **tener cuatro estrategias cualesquiera** en un
tramo bajista, no de haberlas elegido por régimen. Un solo tramo bonito no es una
ventaja; es la forma más común de engañarse.

**Sin ventaja demostrable.** Otra vez.

## La versión de $10

```bash
python3 run.py --cash 10
```

Todo el sistema funciona igual con $10: los cinco agentes, el pulpo, las
decisiones, el dashboard. Lo que cambia es lo que el exchange te deja hacer.

```
BTC-USD   mínimo del exchange  $  3.86
ETH-USD   mínimo del exchange  $  2.44
SOL-USD   mínimo del exchange  $  5.99
SPY       mínimo del exchange  $758.80     ← una acción entera
QQQ       mínimo del exchange  $710.70     ← una acción entera
```

Con $10 las acciones desaparecen del universo (no llega ni para una sola) y en
cripto solo caben una o dos posiciones a la vez. Medido sobre el mismo tramo:

```
$   10   retorno  +5.18%   3 operaciones
$  100   retorno  -3.37%  22 operaciones
$ 1000   retorno  -3.37%  22 operaciones
```

Ese **+5,18% no es una buena noticia**: es lo que sale cuando los mínimos del
exchange bloquean 19 de las 22 operaciones y quedan tres. Tres operaciones no
distinguen una ventaja del azar. La cifra de $1.000 es idéntica a la de $100
porque ahí ya no hay mínimo que estorbe: **ese −3,37% es el resultado real del
sistema**, y el de $10 es ruido con suerte.

## Tu cuenta de $10

El panel está justo encima del pulpo, y el pulpo reacciona a lo que le pasa:
pone cara al ganar y al perder. Empieza en **$10** y **no tiene techo** — sube
hasta donde llegue, la escala del gráfico crece con ella.

Lo que corre no es una ristra de operaciones: es un **calendario**. Cada tic es
un día de mercado, y solo el **11% de los días hay operación**, que es la
cadencia real del sistema — 44 en 401 días, una cada nueve. Por eso hay semanas
enteras en las que la cuenta no se mueve, que es exactamente lo que se siente
operando de verdad. Velocidades **×1 · ×2 · ×5**, donde ×1 es un día de mercado
cada dos segundos: una hora mirando son unos siete años.

Se puede **ingresar en marcha** (+$10, +$20, +$50, +$100), y eso sube el listón
contra el que se mide el multiplicador, para que no mienta. Si la cuenta toca
**$1**, se acabó del todo: por debajo ningún exchange acepta la orden, y ahí no
valen ingresos ni segundas oportunidades — hay que vaciar y empezar otra. Se
guarda sola: si cierras la pestaña, sigue donde estaba.

Lo que la hace realista es de dónde salen las operaciones: **cada una es un
resultado real** de las 44 que el sistema hizo en el backtest, resampleadas
(bootstrap). Media +0,0446% por operación, 50% ganadoras, la mejor +3,98%, la
peor −2,15%. Por eso sube y baja como sube y baja el sistema de verdad.

Y por eso la respuesta a *"¿cuánto tarda en llegar a $100?"* deja de ser una
opinión:

```
llega a $100  95,9%      toca el stop de $1  4,1%
mediana: 6.647 operaciones  →  a una al día, 26 años
```

Casi siempre llega. **Tardando veintiséis años.** Esa es la ventaja real medida
de este sistema: existe, y es así de lenta. Multiplicar por diez en una tarde
solo se consigue apostando fuerte, y eso es la otra tabla:

```
ACIERTO NECESARIO para $10→$100 en 5 horas: 66,6%   (ganar 40 de 60)

acierto     llega a 100   acaba en 0
66,6% ←          63,0%        32,8%
55,0%            16,7%        81,4%
```

Con el acierto exacto que hace falta, una de cada tres sesiones acaba en cero.
Con un 55% —que ya sería un sistema bueno— mueren cuatro de cada cinco. La
palanca que multiplica es exactamente la misma que divide, y llega antes abajo.

`bot/turbo.py` tiene las dos cuentas (`camino()` y `required_winrate()`), y el
motor de la cuenta vive en el navegador para que la demo funcione sin servidor.

## ¿10 operaciones por segundo?

Un bot **puede**. Lo hacen a diario los de alta frecuencia. Pero antes de
acelerar conviene ver dónde está el cuello de botella, porque no es el que
parece. `bot/velocidad.py` mide los cuatro:

```
1. LA RED — ida y vuelta real a Kraken desde aquí
   mediana 277 ms → 3,6 peticiones/s en serie
   una operación son dos (abrir y cerrar) → 1,8 ops/s

2. EL CONTADOR DE KRAKEN — tope 15, baja 0,33/s
   ráfaga: 15 órdenes seguidas y te paras
   sostenido: una cada 3 segundos
   para 10 ops/s harían falta 61× ese límite

3. LA COMISIÓN — taker real de Kraken 0,26% + 0,05% de deslizamiento
   cada ida y vuelta cuesta 0,62% de lo movido
   10/s     864.000 ops/día →  535.680 $/día en comisiones
    1/s      86.400 ops/día →   53.568 $/día
    1/min     1.440 ops/día →      893 $/día
    1/día         1 op/día  →        1 $/día

4. LA SEÑAL — velas diarias
   el sistema hace 1 operación cada ~9 días de mercado
```

**Con $100 a 10 operaciones por segundo, la cuenta se evapora en 18 segundos.**
No por perder en el mercado: solo en comisiones.

Los tres primeros cuellos se pueden comprar —una cuenta institucional negocia
comisiones cerca de cero, un servidor en el mismo edificio que el exchange baja
la latencia a microsegundos, un límite de peticiones se sube pagando—. El
cuarto no: **el sistema opera velas diarias**. A 10 ops/s son 7.776.000
operaciones donde el sistema ve una. Las otras no son señales, son ruido caro.

Los de alta frecuencia no ganan por ir rápido. Ganan porque tienen una ventaja
que dura milisegundos *y además* van rápido. Con comisión de minorista y una
señal diaria, la velocidad no es una ventaja: **es el mecanismo por el que se
pierde el dinero.**

## ¿Y si los agentes fueran agentes de Claude?

Lo primero, que es lo que más se olvida: **este bot no gasta ni un token**. Los
cinco agentes son hilos de Python con indicadores calculados a mano. Puede
correr años en un portátil por el precio de la electricidad. No se apaga cuando
se acaba una sesión ni cuando se acaba una cuota.

`bot/coste.py` responde la otra pregunta: si cada agente fuese una llamada a la
API de Claude, ¿cuánto aguantaría? Se mide con los tamaños reales de lo que cada
agente tendría que leer y con los precios publicados de la API.

```
19 activos · 90 velas diarias cada uno

técnico      13.733 tokens   ← necesita la serie entera, es su trabajo
escáner       3.254
noticias      2.200
riesgo          608
ejecución       508
sistema       4.500 (cacheado)
TOTAL        24.803 tokens por ciclo
```

Con **10 agentes y $20**, cambiando solo cada cuánto se pregunta:

```
cadencia              ciclos/día    Opus 5   Sonnet 5    Haiku
cada 20 s (ahora)          4.320        0h         1h       2h
cada 5 min                   288        5h        13h      27h
cada hora                     24        3d         7d      13d
4 veces al día                 4       16d        40d      80d
una vez al día                 1       64d       160d     320d
```

Ahí está la respuesta realista, y no es la velocidad: **es la cadencia**. El
sistema opera velas **diarias**. Preguntarle a un modelo cada 20 segundos es
pagar 4.320 opiniones al día sobre un gráfico que cambia una vez. Con $20 y una
pregunta al día, diez agentes de Opus 5 aguantan **dos meses**; los mismos diez
agentes al ritmo de ahora se funden los $20 **antes de una hora**.

Y la comparación que zanja el asunto:

```
el sistema gana                       0,0027 $/día sobre $100
10 agentes cada 20 s                 269,99  $/día   (99.327× lo que gana)
10 agentes una vez al día              0,06  $/día        (23× lo que gana)
```

Incluso en la versión barata —Haiku, una pregunta al día— harían falta **$2.299
operando solo para pagar la factura del modelo**. Por debajo de eso el modelo
cuesta más que lo que el sistema gana, y con $10 o $100 no hay conversación
posible.

Reproducible con `python3 -m bot.coste --presupuesto 20 --agentes 10`.

## En el móvil

El dashboard no es el mosaico encogido. Por debajo de 760px el sistema se reparte en
cuatro pestañas con barra inferior al alcance del pulgar — **Pulpo, Capital, Mercado,
Pruebas** — y el capital sube a una cabecera fija que se ve desde cualquiera de ellas.
Son los mismos paneles, no una segunda versión: al ensanchar la ventana vuelve el
mosaico entero sin recargar, y la pestaña elegida se recuerda.

Detalles que importan en un teléfono: `viewport` y `doctype` de verdad (sin ellos
Chrome renderiza a 980px y entra en modo quirks), objetivos táctiles de 46px, respeto
al notch con `env(safe-area-inset-*)`, los raíles del pulpo bajan a dos columnas
debajo de él en vez de ahogarlo, y las tablas anchas ruedan ellas — la página nunca
se desplaza en horizontal. Comprobado a 390×844 y 1512×900.

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
- **`demo/turbo.html`** — **DIEZ A CIEN EN CINCO HORAS**: la sesión de $10 apalancada,
  entera en el navegador y sin servidor. La aritmética de bot/turbo.py en directo — la
  ecuación, una sesión que se lanza y se ve caer, y las diez mil sesiones simuladas al
  vuelo. Pensada para el móvil.

El dashboard con datos en vivo es el de `python3 run.py`.

### El Director

En el código, el Director es el **orquestador** (`bot/orchestrator.py`): combina los
tres votos direccionales con sus pesos, y solo abre posición si el agente de riesgo
lo aprueba. Los otros cinco agentes son hilos independientes con su propia cadencia.
