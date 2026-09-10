# Atribución de terceros

Este repositorio está bajo **GPL-3.0** (ver `LICENSE`).

## freqtrade

`bot/protections.py` y `bot/exits.py` son reimplementaciones de mecanismos de
[freqtrade](https://github.com/freqtrade/freqtrade), copyright de los
contribuidores de freqtrade, distribuido bajo **GPL-3.0**. Licencia compatible
con la de este repositorio, que se mantiene GPL-3.0 por ello.

Mecanismos tomados, con su origen:

| Aquí | En freqtrade |
|---|---|
| `ProtectionManager` → cooldown | `freqtrade/plugins/protections/cooldown_period.py` (`CooldownPeriod`) |
| `ProtectionManager` → guardia de stops | `freqtrade/plugins/protections/stoploss_guard.py` (`StoplossGuard`) |
| `ProtectionManager` → activo en pérdidas | `freqtrade/plugins/protections/low_profit_pairs.py` (`LowProfitPairs`) |
| `ProtectionManager` → bloqueo por drawdown | `freqtrade/plugins/protections/max_drawdown_protection.py` |
| `exits.roi_target` | `IStrategy.min_roi_reached_entry` (`minimal_roi`) |
| `exits.trailing_stop` | `trailing_stop_positive` + `trailing_stop_positive_offset` |

No se ha copiado código literalmente: freqtrade se apoya en SQLAlchemy, pandas y
sus propios objetos `Trade`, que aquí no existen. Lo portado es la **lógica**,
reescrita sobre las estructuras de este proyecto y sin dependencias externas.

Dos adaptaciones deliberadas:

- La tabla `minimal_roi` de freqtrade usa porcentajes fijos, razonables en velas
  de 5–15 minutos. Aquí los objetivos son **múltiplos del ATR**, para que
  signifiquen lo mismo en SPY que en SOL y en velas horarias que diarias.
- El reloj sale de la marca temporal de la vela, no del reloj de pared, para que
  las protecciones funcionen igual en vivo que en backtest.

## freqtrade-strategies

`bot/external.py` reimplementa la **lógica** de tres estrategias de
[freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies)
(GPL-3.0, 5.464 ★, con commits del mismo día en que se portaron):

| Aquí | Allí |
|---|---|
| `Strategy001` | `user_data/strategies/Strategy001.py` |
| `Strategy002` | `user_data/strategies/Strategy002.py` |
| `SupertrendStrategy` | `user_data/strategies/Supertrend.py` |

No se ha copiado su código: dependen de pandas, numpy, TA-Lib y del framework de
freqtrade, nada de lo cual existe aquí. Se han portado sus condiciones de entrada
y salida, su tabla ROI y su stop, con indicadores propios en Python puro
(Heikin-Ashi, estocástico, SAR parabólico, Fisher RSI, Supertrend, martillo).

Están para **medirlas**, no para venderlas: el resultado sale en
`python3 -m bot.external`.

## Otras referencias

La arquitectura multi-agente (analistas → agregación → riesgo → ejecución) está
inspirada en [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).
No se ha tomado código de ese proyecto.
