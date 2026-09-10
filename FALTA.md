# Qué falta para operar con dinero real

**Actualizado.** Los puntos 1–6 ya están construidos y probados. Lo que queda es
el punto 0 y la clave, que no depende del código.

## Estado

| | Estado |
|---|---|
| **0. Una estrategia con ventaja demostrable** | ❌ **no la hay** — `python3 -m bot.oos` |
| 1. Cliente de la API privada de Kraken | ✅ `bot/kraken.py` · firma verificada |
| 2. Máquina de estados de la orden | ✅ `bot/live.py` · parciales, idempotencia |
| 3. Persistencia y reconciliación | ✅ `bot/store.py` · SQLite, sobrevive reinicios |
| 4. Stops puestos en el exchange | ✅ `bot/live.py::place_stop` |
| 5. Secretos | ✅ `.env` fuera del repo, `.env.example` |
| 6. Alertas | ✅ `bot/alerts.py` |
| **La clave de API** | 🔑 **la tienes que poner tú, en tu máquina** |

## Cómo se probó sin tener cuenta

- **La firma** (`tests/test_signature.py`) se comprueba contra el vector de ejemplo
  que publica Kraken. O sale exactamente esa firma o el exchange rechaza todo; no
  admite un "parece que va".
- **El resto** (`tests/test_live.py`) contra un Kraken de mentira que imita la API,
  incluidas las **ejecuciones parciales**, que son lo que de verdad rompe los bots.
  9 pruebas: redondeos, mínimos, parciales, stop en el exchange, mover el stop,
  cancelarlo al vender, modo validación, `userref` único y reinicio.
- **Los metadatos de los pares** se leen del Kraken real: `AssetPairs` es público.

## Las tres barreras que hay que cruzar a la vez para mover dinero

1. `--live --real` en la línea de comandos.
2. `KRAKEN_API_KEY` y `KRAKEN_API_SECRET` en el entorno.
3. `LIVE_TRADING_CONFIRMED=yes-i-understand-the-risk`.

Falta cualquiera de las tres y el sistema entra en **modo validación**: manda la
orden con `validate=true`, Kraken la comprueba de arriba abajo y **no la ejecuta**.

## Lo que YO no voy a hacer

No voy a manejar tu clave de API. Tú la creas, tú la pones en tu `.env`, en tu
máquina. Que un proceso que no controlas tenga credenciales que mueven tu dinero
es mala idea aunque me lo pidas — y no cambia porque sean 19 dólares.

Cuando la crees, **quítale el permiso de retirada** (`Withdraw Funds`). Con eso,
en el peor caso alguien puede hacer operaciones tontas, pero no puede sacar el
dinero de tu cuenta.

## Y el punto 0 sigue ahí

Toda esta fontanería está bien hecha y probada. No convierte una estrategia sin
ventaja en una que gane: solo hace que pierda de forma ordenada, protegida y con
buen registro. La validación out-of-sample dice que las mejoras no baten a no hacer
nada, y con comisión y mínimos reales el sistema pierde.

Mi recomendación no ha cambiado: `python3 run.py --live` unas semanas. Manda las
órdenes al exchange de verdad, Kraken las valida de verdad, y no se ejecuta nada.
Ahí se ve si la fontanería aguanta sin arriesgar un euro.
