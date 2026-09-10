"""Broker contra Kraken, con la misma interfaz que el de papel.

Los agentes no saben cual de los dos tienen debajo: `LiveBroker` expone
`buy`, `sell`, `positions`, `equity`, `mark` y `stats` igual que `PaperBroker`.

Lo que cambia es todo lo que en papel era instantaneo y aqui no lo es:

  * Una orden pasa por estados: enviada -> abierta -> parcial -> cerrada,
    o rechazada / cancelada. `poll()` la hace avanzar.
  * Se llena a medias con frecuencia. La posicion refleja lo EJECUTADO.
  * Cada orden lleva `userref` propio: si la respuesta se pierde por red, el
    reintento no crea una segunda orden.
  * El stop-loss se coloca EN EL EXCHANGE. Si este proceso se cae, la posicion
    sigue protegida. Era el fallo mas grave del diseno anterior.
  * Al arrancar no se cree su propio estado: le pregunta al exchange.

Seguridad: sale en modo `validate` (Kraken comprueba la orden y NO la ejecuta).
Para operar de verdad hacen falta dos cosas a la vez: `validate=False` y la
variable de entorno LIVE_TRADING_CONFIRMED=yes-i-understand-the-risk.
"""
from __future__ import annotations

import math
import threading
import time

from .broker import Position
from .kraken import KrakenClient, KrakenError
from .store import Store

# nuestro simbolo -> par de Kraken
PAIR = {"BTC-USD": "XBTUSD", "ETH-USD": "ETHUSD", "SOL-USD": "SOLUSD"}
# nuestro simbolo -> como se llama el saldo de ese activo en Balance.
# Kraken usa nombres propios: el bitcoin es XXBT, no BTC. Adivinarlo por el
# ticker no funciona y deja posiciones sin detectar.
ASSET = {"BTC-USD": "XXBT", "ETH-USD": "XETH", "SOL-USD": "SOL"}
QUOTE = "ZUSD"
CONFIRM = "yes-i-understand-the-risk"


class LiveBroker:
    def __init__(self, client: KrakenClient | None = None, store: Store | None = None,
                 validate: bool = True, log=print):
        self.k = client or KrakenClient()
        self.store = store or Store()
        self.validate = validate
        self.log = log
        self.lock = threading.RLock()
        self.positions: dict[str, Position] = {}
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.cash = 0.0
        self.fees_paid = 0.0
        self.starting_cash = 0.0
        self.peak_equity = 0.0
        self.meta: dict[str, dict] = {}
        self._armed = False

    # ---------- arranque ----------
    def arm(self):
        """Comprueba credenciales, carga metadatos del par y reconcilia."""
        import os
        if not self.validate:
            if os.environ.get("LIVE_TRADING_CONFIRMED") != CONFIRM:
                raise KrakenError(
                    "modo real sin confirmar: exporta "
                    f"LIVE_TRADING_CONFIRMED={CONFIRM} si de verdad quieres "
                    "que este proceso mueva dinero")
        self.load_pairs()
        self.reconcile()
        self._armed = True
        modo = "VALIDACIÓN (no ejecuta)" if self.validate else "REAL (mueve dinero)"
        self.log(f"[live] armado en modo {modo} · {len(self.positions)} posiciones")

    def load_pairs(self):
        """Decimales y mínimos de cada par. Sin esto el exchange rechaza.

        El emparejamiento va por `altname`, que es el nombre que Kraken publica
        justo para esto ("XBTUSD"). Deducirlo recortando la clave interna
        ("XXBTZUSD") es adivinar, y adivinar falla.
        """
        res = self.k.asset_pairs(list(PAIR.values()))
        by_alt = {}
        for name, v in res.items():
            by_alt[str(v.get("altname", name)).upper()] = (name, v)
            by_alt.setdefault(name.upper(), (name, v))
        missing = []
        for sym, code in PAIR.items():
            hit = by_alt.get(code.upper())
            if not hit:
                missing.append(sym)
                continue
            name, v = hit
            self.meta[sym] = {
                "name": name,
                "price_dec": int(v.get("pair_decimals", 2)),
                "lot_dec": int(v.get("lot_decimals", 8)),
                "ordermin": float(v.get("ordermin", 0) or 0),
                "costmin": float(v.get("costmin", 0) or 0),
            }
        if missing:
            raise KrakenError(f"el exchange no devolvió metadatos de: {', '.join(missing)}")

    # ---------- redondeos ----------
    def round_volume(self, symbol: str, qty: float) -> float:
        """A la baja: redondear al alza puede pasarse del saldo disponible."""
        d = self.meta.get(symbol, {}).get("lot_dec", 8)
        f = 10 ** d
        return math.floor(qty * f) / f

    def round_price(self, symbol: str, px: float) -> float:
        d = self.meta.get(symbol, {}).get("price_dec", 2)
        return round(px, d)

    def check_min(self, symbol: str, qty: float, price: float) -> tuple[bool, str]:
        m = self.meta.get(symbol)
        if not m:
            return False, f"par {symbol} sin metadatos"
        if qty < m["ordermin"]:
            return False, f"volumen {qty} < mínimo {m['ordermin']}"
        if qty * price < m["costmin"]:
            return False, f"importe ${qty*price:.2f} < mínimo ${m['costmin']:.2f}"
        return True, ""

    # ---------- reconciliacion ----------
    def reconcile(self):
        """Al arrancar, el exchange manda. El estado local solo complementa."""
        bal = self.k.balance()
        self.cash = float(bal.get(QUOTE, 0) or 0)
        if not self.starting_cash:
            self.starting_cash = self.store.get("starting_cash") or self.cash
            self.store.put("starting_cash", self.starting_cash)

        saved = {p["symbol"]: p for p in self.store.positions()}
        self.positions = {}
        for sym in PAIR:
            code = ASSET[sym]
            # el saldo puede venir como "XXBT" o como "XXBT.F" (earn/staking)
            held = sum(float(v or 0) for k, v in bal.items()
                       if k == code or k.startswith(code + "."))
            if held <= 0:
                if sym in saved:
                    self.log(f"[live] {sym}: el estado local decía posición pero el "
                             f"exchange no tiene saldo — se descarta")
                    self.store.drop_position(sym)
                continue
            s = saved.get(sym)
            if not s:
                self.log(f"[live] {sym}: hay {held} en el exchange sin registro local "
                         f"— se adopta sin stop; revísalo a mano")
            p = Position(sym, held, (s or {}).get("entry", 0.0) or 0.0,
                         (s or {}).get("stop", 0.0) or 0.0,
                         (s or {}).get("target"), (s or {}).get("opened_at", int(time.time())),
                         (s or {}).get("atr"))
            p.high_water = (s or {}).get("high_water", p.entry)
            p.stop_txid = (s or {}).get("stop_txid")
            self.positions[sym] = p

        alive = set(self.k.open_orders().get("open", {}).keys())
        for o in self.store.open_orders():
            if o["txid"] and o["txid"] not in alive:
                self.store.save_order({**o, "status": "gone"})
        self.log(f"[live] reconciliado · efectivo ${self.cash:.2f} · "
                 f"{len(self.positions)} posiciones · {len(alive)} órdenes abiertas")

    # ---------- ordenes ----------
    def _send(self, **kw):
        kw = {k: v for k, v in kw.items() if v is not None}
        if self.validate:
            kw["validate"] = "true"
        return self.k.add_order(**kw)

    def buy(self, symbol, qty, price, stop, target, reason="", ts=None, atr=None):
        with self.lock:
            if not self._armed:
                raise KrakenError("llama a arm() antes de operar")
            qty = self.round_volume(symbol, qty)
            ok, why = self.check_min(symbol, qty, price)
            if not ok:
                self.log(f"[live] {symbol} no se manda: {why}")
                return None

            ref = self.store.next_userref()
            self.store.save_order({"userref": ref, "symbol": symbol, "side": "buy",
                                   "qty": qty, "status": "sent", "reason": reason})
            try:
                res = self._send(pair=self.meta[symbol]["name"], type="buy",
                                 ordertype="market", volume=f"{qty}", userref=ref)
            except KrakenError as e:
                self.store.save_order({"userref": ref, "symbol": symbol, "side": "buy",
                                       "qty": qty, "status": "error", "reason": str(e)})
                self.log(f"[live] COMPRA {symbol} rechazada: {e}")
                return None

            txid = (res.get("txid") or [None])[0]
            self.store.save_order({"userref": ref, "txid": txid, "symbol": symbol,
                                   "side": "buy", "qty": qty, "status": "open",
                                   "reason": reason})
            if self.validate:
                self.log(f"[live] VALIDADA compra {symbol} {qty} — no ejecutada")
                return {"id": str(ref), "t": int(ts or time.time()), "side": "BUY",
                        "symbol": symbol, "qty": qty, "price": price, "fee": 0.0,
                        "pnl": None, "reason": reason, "validated": True}

            filled, avg, fee = self._await_fill(txid)
            if filled <= 0:
                self.log(f"[live] COMPRA {symbol} sin ejecutar")
                return None

            p = Position(symbol, filled, avg, stop, target, int(ts or time.time()), atr)
            p.entry_txid = txid
            self.positions[symbol] = p
            self.cash -= filled * avg + fee
            self.fees_paid += fee
            self.place_stop(symbol)
            t = {"id": str(ref), "t": int(ts or time.time()), "side": "BUY",
                 "symbol": symbol, "qty": filled, "price": avg, "fee": fee,
                 "pnl": None, "reason": reason, "txid": txid}
            self.trades.append(t); self.store.add_trade(t)
            self.store.save_position({**p.to_dict(avg), "stop_txid": p.stop_txid,
                                      "entry_txid": txid, "atr": atr})
            return t

    def place_stop(self, symbol: str):
        """El stop vive en el exchange: sobrevive a que este proceso muera."""
        p = self.positions.get(symbol)
        if not p or self.validate or not p.stop:
            return
        try:
            res = self._send(pair=self.meta[symbol]["name"], type="sell",
                             ordertype="stop-loss", volume=f"{p.qty}",
                             price=f"{self.round_price(symbol, p.stop)}",
                             userref=self.store.next_userref())
            p.stop_txid = (res.get("txid") or [None])[0]
            self.log(f"[live] stop de {symbol} colocado en el exchange a "
                     f"{p.stop:.2f} ({p.stop_txid})")
        except KrakenError as e:
            self.log(f"[live] AVISO: no se pudo colocar el stop de {symbol}: {e}. "
                     f"La posición está SIN PROTEGER.")

    def move_stop(self, symbol: str, new_stop: float):
        p = self.positions.get(symbol)
        if not p:
            return
        p.stop = new_stop
        if self.validate:
            return
        if p.stop_txid:
            try:
                self.k.cancel_order(p.stop_txid)
            except KrakenError as e:
                self.log(f"[live] no se pudo cancelar el stop viejo de {symbol}: {e}")
                return
        self.place_stop(symbol)

    def sell(self, symbol, price, reason="", ts=None):
        with self.lock:
            p = self.positions.get(symbol)
            if not p:
                return None
            if p.stop_txid and not self.validate:
                try:
                    self.k.cancel_order(p.stop_txid)
                except KrakenError:
                    pass
            ref = self.store.next_userref()
            try:
                res = self._send(pair=self.meta[symbol]["name"], type="sell",
                                 ordertype="market", volume=f"{p.qty}", userref=ref)
            except KrakenError as e:
                self.log(f"[live] VENTA {symbol} rechazada: {e}")
                return None
            txid = (res.get("txid") or [None])[0]
            if self.validate:
                self.log(f"[live] VALIDADA venta {symbol} {p.qty} — no ejecutada")
                return None
            filled, avg, fee = self._await_fill(txid)
            if filled <= 0:
                return None
            pnl = (avg - p.entry) * filled - fee
            self.cash += filled * avg - fee
            self.fees_paid += fee
            self.positions.pop(symbol, None)
            self.store.drop_position(symbol)
            t = {"id": str(ref), "t": int(ts or time.time()), "side": "SELL",
                 "symbol": symbol, "qty": filled, "price": avg, "fee": fee,
                 "pnl": pnl, "pnl_pct": pnl / (p.entry * filled) if p.entry else 0.0,
                 "reason": reason, "txid": txid}
            self.trades.append(t); self.store.add_trade(t)
            return t

    def _await_fill(self, txid: str, timeout: float = 45.0):
        """Espera a que la orden cierre. Devuelve (ejecutado, precio_medio, comision).

        Una orden puede quedarse a medias: se devuelve lo REALMENTE ejecutado,
        no lo pedido.
        """
        t0 = time.time()
        last = (0.0, 0.0, 0.0)
        while time.time() - t0 < timeout:
            try:
                info = self.k.query_orders([txid]).get(txid, {})
            except KrakenError:
                time.sleep(1.5); continue
            vol_exec = float(info.get("vol_exec", 0) or 0)
            cost = float(info.get("cost", 0) or 0)
            fee = float(info.get("fee", 0) or 0)
            avg = (cost / vol_exec) if vol_exec else 0.0
            last = (vol_exec, avg, fee)
            st = info.get("status")
            if st in ("closed", "canceled", "expired"):
                if st != "closed" and vol_exec > 0:
                    self.log(f"[live] {txid} {st} con ejecución parcial: {vol_exec}")
                return last
            time.sleep(1.5)
        self.log(f"[live] {txid} sigue abierta tras {timeout:.0f}s; "
                 f"se contabiliza lo ejecutado hasta ahora")
        return last

    # ---------- contabilidad ----------
    def equity(self, prices):
        with self.lock:
            return self.cash + sum(p.qty * prices.get(s, p.entry)
                                   for s, p in self.positions.items())

    def mark(self, prices):
        eq = self.equity(prices)
        with self.lock:
            self.peak_equity = max(self.peak_equity, eq)
            self.equity_curve.append({"t": int(time.time()), "equity": eq})
            if len(self.equity_curve) > 2000:
                self.equity_curve = self.equity_curve[-2000:]
        return eq

    def drawdown(self, prices):
        eq = self.equity(prices)
        return (eq / self.peak_equity - 1) if self.peak_equity > 0 else 0.0

    def stats(self, prices):
        from .broker import PaperBroker
        return PaperBroker.stats(self, prices)
