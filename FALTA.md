# Qué falta para operar con dinero real

El sistema **funciona** como está: corre, opera en papel con precios reales, se mide
a sí mismo y publica sus resultados. Lo que sigue es lo que faltaría para que moviera
dinero de verdad, en orden de importancia.

## 0. Lo que no se arregla programando

**Una estrategia con ventaja demostrable.** No la hay: la validación out-of-sample
(`python3 -m bot.oos`) muestra que las mejoras no baten a no hacer nada, y con comisión
y mínimos reales el sistema pierde. Todo lo que viene debajo es fontanería; sin esto,
la fontanería solo sirve para perder dinero más rápido y con mejor registro.

## 1. `LiveBroker` contra la API privada de Kraken

`bot/broker.py` tiene la interfaz y lanza `NotImplementedError` a propósito. Habría que:

- Firmar las peticiones privadas (HMAC-SHA512 sobre nonce + payload).
- `AddOrder` con `validate=true` primero, para probar sin ejecutar.
- Traducir cantidades y precios a los decimales que acepta cada par (`pair_decimals`,
  `lot_decimals` de `AssetPairs`), o el exchange rechaza la orden.

## 2. Máquina de estados de la orden

Lo que hoy es `buy()` devolviendo un fill instantáneo, en real es un proceso:
enviada → aceptada → parcialmente ejecutada → completa | rechazada | cancelada.

- **Ejecuciones parciales**: una orden puede llenarse a medias. La posición y el stop
  tienen que reflejar lo realmente ejecutado, no lo pedido.
- **Idempotencia**: si la respuesta se pierde por red, reintentar sin un identificador
  propio (`userref`) duplica la orden. Es de los errores que más dinero cuestan.
- **Reintentos y límites de tasa**: Kraken tiene un contador que penaliza; pasarse
  bloquea la cuenta temporalmente.

## 3. Persistencia y reconciliación

Hoy las posiciones viven en memoria: si el proceso se reinicia, el bot cree que no
tiene nada abierto mientras el exchange sí las tiene.

- Guardar estado en disco (SQLite basta).
- **Al arrancar, preguntar al exchange** cuál es el saldo y las posiciones reales, y
  creer eso antes que el estado local.

## 4. Stops en el exchange, no en el bot

Ahora el stop-loss lo vigila `ExecutionAgent` en un hilo. Si el bot se cae, la posición
queda **sin protección**. En real el stop tiene que estar puesto en el exchange
(`ordertype=stop-loss`) para que exista aunque el bot no.

Este es el punto que convierte "el sistema falla" en "el sistema falla y además pierdes
dinero mientras está caído".

## 5. Secretos

Claves en un `.env` fuera del repositorio, permisos mínimos en la API key (operar sí,
retirar **no**), y nunca en logs ni en mensajes de error.

## 6. Observabilidad

Alertas cuando algo se sale de lo previsto: una orden rechazada, el drawdown acercándose
al kill switch, el bot sin latir. Un bot que falla en silencio es peor que no tener bot.

## Orden sensato

1. Semanas de papel con datos en vivo (`python3 run.py`), que ya funciona y cuesta cero.
2. `LiveBroker` con `validate=true`: manda órdenes que el exchange comprueba pero no ejecuta.
3. Stops en el exchange + persistencia + reconciliación.
4. Cantidades mínimas, con dinero que dé igual perder.
5. Y solo si en algún momento aparece una ventaja real, medida fuera de muestra.
