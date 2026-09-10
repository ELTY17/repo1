"""Cliente de la API de Kraken: publica y privada.

La parte privada va firmada con HMAC-SHA512 segun el esquema que publica Kraken:

    sha  = SHA256(nonce + cuerpo_urlencoded)
    mac  = HMAC-SHA512(base64decode(secreto), ruta_utf8 + sha)
    firma = base64(mac)

El secreto nunca se escribe en un log ni aparece en un mensaje de error: se lee
de las variables de entorno y se queda dentro de este modulo.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.kraken.com"
UA = "multi-agent-trader/1.0"


class KrakenError(RuntimeError):
    """Error devuelto por la API. Nunca lleva credenciales dentro."""


def sign(path: str, data: dict, secret_b64: str) -> str:
    """Cabecera API-Sign para una peticion privada."""
    post = urllib.parse.urlencode(data)
    sha = hashlib.sha256((str(data["nonce"]) + post).encode()).digest()
    mac = hmac.new(base64.b64decode(secret_b64), path.encode() + sha, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


class RateLimiter:
    """Contador de Kraken: cada llamada suma y el contador baja con el tiempo.

    Pasarse bloquea la cuenta un rato, asi que se espera antes de llegar.
    """

    def __init__(self, max_counter: float = 15.0, decay_per_s: float = 0.33):
        self.max = max_counter
        self.decay = decay_per_s
        self.counter = 0.0
        self.last = time.time()
        self._lock = threading.Lock()

    def take(self, cost: float = 1.0):
        with self._lock:
            now = time.time()
            self.counter = max(0.0, self.counter - (now - self.last) * self.decay)
            self.last = now
            if self.counter + cost > self.max:
                wait = (self.counter + cost - self.max) / self.decay
                time.sleep(min(wait, 30))
                self.counter = max(0.0, self.counter - wait * self.decay)
            self.counter += cost


class KrakenClient:
    def __init__(self, key: str | None = None, secret: str | None = None,
                 timeout: int = 20):
        self._key = key if key is not None else os.environ.get("KRAKEN_API_KEY", "")
        self._secret = secret if secret is not None else os.environ.get("KRAKEN_API_SECRET", "")
        self.timeout = timeout
        self.limiter = RateLimiter()
        self._nonce_lock = threading.Lock()
        self._last_nonce = 0

    # --- utilidades ---
    @property
    def has_credentials(self) -> bool:
        return bool(self._key and self._secret)

    def _nonce(self) -> int:
        with self._nonce_lock:
            n = max(int(time.time() * 1000), self._last_nonce + 1)
            self._last_nonce = n
            return n

    def _request(self, path: str, data: dict | None, headers: dict, cost: float):
        self.limiter.take(cost)
        body = urllib.parse.urlencode(data or {}).encode()
        req = urllib.request.Request(API + path, data=body if data else None,
                                     headers={"User-Agent": UA, **headers})
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as r:
                payload = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:                  # noqa: PERF203
            raise KrakenError(f"HTTP {e.code} en {path}") from None
        except Exception as e:                               # noqa: BLE001
            raise KrakenError(f"{type(e).__name__} en {path}") from None
        if payload.get("error"):
            raise KrakenError(f"{path}: {'; '.join(payload['error'])}")
        return payload.get("result", {})

    # --- publico ---
    def public(self, method: str, **params):
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        return self._request(f"/0/public/{method}{q}", None, {}, 1.0)

    # --- privado ---
    def private(self, method: str, cost: float = 1.0, **params):
        if not self.has_credentials:
            raise KrakenError(
                "faltan credenciales: define KRAKEN_API_KEY y KRAKEN_API_SECRET")
        path = f"/0/private/{method}"
        data = {"nonce": self._nonce(), **{k: v for k, v in params.items() if v is not None}}
        headers = {"API-Key": self._key,
                   "API-Sign": sign(path, data, self._secret),
                   "Content-Type": "application/x-www-form-urlencoded"}
        return self._request(path, data, headers, cost)

    # --- envoltorios ---
    def asset_pairs(self, pairs: list[str]) -> dict:
        return self.public("AssetPairs", pair=",".join(pairs))

    def balance(self) -> dict:
        return self.private("Balance", cost=2.0)

    def open_orders(self) -> dict:
        return self.private("OpenOrders", cost=1.0)

    def closed_orders(self) -> dict:
        return self.private("ClosedOrders", cost=2.0)

    def query_orders(self, txids: list[str]) -> dict:
        return self.private("QueryOrders", cost=1.0, txid=",".join(txids))

    def add_order(self, **kw):
        return self.private("AddOrder", cost=0.0, **kw)

    def cancel_order(self, txid: str):
        return self.private("CancelOrder", cost=0.0, txid=txid)
