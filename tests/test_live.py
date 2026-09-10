"""El broker en vivo, probado entero contra un Kraken de mentira.

No hace falta cuenta ni clave: se sustituye el cliente por uno que imita las
respuestas reales de la API, incluidas las ejecuciones parciales, que son lo que
de verdad rompe los bots.
"""
from __future__ import annotations

import os
import tempfile

from bot.live import LiveBroker
from bot.store import Store


class FakeKraken:
    """Imita a Kraken: acepta ordenes, las llena a plazos y guarda estado."""

    def __init__(self, balance=None, fill_steps=2):
        self.balance_data = balance or {"ZUSD": "100.0000"}
        self.orders: dict[str, dict] = {}
        self.open: dict[str, dict] = {}
        self.n = 0
        self.fill_steps = fill_steps
        self.sent: list[dict] = []
        self.canceled: list[str] = []
        self.has_credentials = True

    def asset_pairs(self, pairs):
        return {
            "XXBTZUSD": {"altname": "XBTUSD", "pair_decimals": 1, "lot_decimals": 8,
                         "ordermin": "0.00005", "costmin": "0.5"},
            "XETHZUSD": {"altname": "ETHUSD", "pair_decimals": 2, "lot_decimals": 8,
                         "ordermin": "0.001", "costmin": "0.5"},
            "SOLUSD":   {"altname": "SOLUSD", "pair_decimals": 2, "lot_decimals": 8,
                         "ordermin": "0.06", "costmin": "0.5"},
        }

    def balance(self):
        return dict(self.balance_data)

    def open_orders(self):
        return {"open": dict(self.open)}

    def add_order(self, **kw):
        self.sent.append(kw)
        self.n += 1
        txid = f"OTEST-{self.n}"
        if kw.get("validate") == "true":
            return {"descr": {"order": "validated"}}
        vol = float(kw["volume"])
        price = 78000.0 if "XBT" in kw["pair"] else 100.0
        self.orders[txid] = {"status": "open", "vol": vol, "vol_exec": 0.0,
                             "cost": 0.0, "fee": 0.0, "price": price,
                             "polls": 0, "type": kw["type"],
                             "ordertype": kw["ordertype"]}
        if kw["ordertype"] == "stop-loss":
            self.open[txid] = self.orders[txid]
        return {"txid": [txid]}

    def query_orders(self, txids):
        out = {}
        for t in txids:
            o = self.orders.get(t)
            if not o:
                continue
            o["polls"] += 1
            frac = min(o["polls"] / self.fill_steps, 1.0)
            o["vol_exec"] = round(o["vol"] * frac, 10)
            o["cost"] = o["vol_exec"] * o["price"]
            o["fee"] = o["cost"] * 0.0026
            o["status"] = "closed" if frac >= 1.0 else "open"
            out[t] = dict(o)
        return out

    def cancel_order(self, txid):
        self.canceled.append(txid)
        self.open.pop(txid, None)
        return {"count": 1}


def make(validate=False, **kw):
    path = tempfile.mktemp(suffix=".db")
    k = FakeKraken(**kw)
    b = LiveBroker(client=k, store=Store(path), validate=validate, log=lambda *a: None)
    b.arm()
    return b, k, path


def test_pair_metadata_and_rounding():
    b, k, p = make()
    assert b.meta["BTC-USD"]["lot_dec"] == 8
    # se redondea A LA BAJA: al alza podria pasarse del saldo
    assert b.round_volume("BTC-USD", 0.123456789) == 0.12345678
    assert b.round_price("BTC-USD", 78123.456) == 78123.5
    os.unlink(p)


def test_rejects_below_exchange_minimum():
    b, k, p = make()
    t = b.buy("SOL-USD", 0.01, 100.0, 92.0, 116.0, "prueba")
    assert t is None, "una orden por debajo del mínimo no debe salir"
    assert not k.sent, "ni siquiera debe llegar al exchange"
    os.unlink(p)


def test_partial_fill_is_what_counts():
    """La posición refleja lo ejecutado, no lo pedido."""
    b, k, p = make(fill_steps=3)
    t = b.buy("BTC-USD", 0.001, 78000.0, 76000.0, 82000.0, "prueba")
    assert t is not None
    pos = b.positions["BTC-USD"]
    assert abs(pos.qty - 0.001) < 1e-9, f"debería llenarse del todo, llenó {pos.qty}"
    assert t["fee"] > 0, "la comisión real tiene que contabilizarse"
    os.unlink(p)


def test_stop_lives_on_the_exchange():
    b, k, p = make()
    b.buy("BTC-USD", 0.001, 78000.0, 76000.0, 82000.0, "prueba")
    stops = [o for o in k.sent if o.get("ordertype") == "stop-loss"]
    assert len(stops) == 1, "tras comprar debe quedar un stop puesto en el exchange"
    assert stops[0]["type"] == "sell"
    assert b.positions["BTC-USD"].stop_txid in k.open
    os.unlink(p)


def test_moving_the_stop_replaces_it():
    b, k, p = make()
    b.buy("BTC-USD", 0.001, 78000.0, 76000.0, 82000.0, "prueba")
    old = b.positions["BTC-USD"].stop_txid
    b.move_stop("BTC-USD", 77500.0)
    assert old in k.canceled, "el stop viejo debe cancelarse antes de poner el nuevo"
    assert b.positions["BTC-USD"].stop_txid != old
    assert len([o for o in k.sent if o.get("ordertype") == "stop-loss"]) == 2
    os.unlink(p)


def test_selling_cancels_the_stop_first():
    b, k, p = make()
    b.buy("BTC-USD", 0.001, 78000.0, 76000.0, 82000.0, "prueba")
    stop = b.positions["BTC-USD"].stop_txid
    t = b.sell("BTC-USD", 79000.0, "objetivo")
    assert stop in k.canceled, "vender sin cancelar el stop deja una orden huérfana"
    assert t is not None and "BTC-USD" not in b.positions
    os.unlink(p)


def test_validate_mode_never_executes():
    b, k, p = make(validate=True)
    t = b.buy("BTC-USD", 0.001, 78000.0, 76000.0, 82000.0, "prueba")
    assert t and t.get("validated") is True
    assert all(o.get("validate") == "true" for o in k.sent)
    assert not b.positions, "en validación no se abre posición"
    os.unlink(p)


def test_each_order_carries_its_own_id():
    """Sin userref, un reintento tras un corte de red duplica la orden."""
    b, k, p = make()
    b.buy("BTC-USD", 0.001, 78000.0, 76000.0, 82000.0, "a")
    b.buy("ETH-USD", 0.01, 2500.0, 2400.0, 2700.0, "b")
    refs = [o["userref"] for o in k.sent]
    assert len(refs) == len(set(refs)), "cada orden necesita su propio userref"
    os.unlink(p)


def test_restart_believes_the_exchange():
    """Reinicio: si el exchange no tiene el activo, la posición local se cae."""
    b, k, p = make()
    b.buy("BTC-USD", 0.001, 78000.0, 76000.0, 82000.0, "prueba")
    assert "BTC-USD" in b.positions
    b.store.close()

    # el proceso muere y vuelve; el exchange SÍ tiene el bitcoin
    k2 = FakeKraken(balance={"ZUSD": "22.0", "XXBT": "0.001"})
    b2 = LiveBroker(client=k2, store=Store(p), validate=False, log=lambda *a: None)
    b2.arm()
    assert "BTC-USD" in b2.positions, "debe recuperar la posición del exchange"
    assert abs(b2.positions["BTC-USD"].qty - 0.001) < 1e-9
    assert abs(b2.positions["BTC-USD"].entry - 78000.0) < 1.0, "y su entrada del disco"
    b2.store.close()

    # ahora el exchange NO lo tiene: el estado local está obsoleto y se descarta
    k3 = FakeKraken(balance={"ZUSD": "100.0"})
    b3 = LiveBroker(client=k3, store=Store(p), validate=False, log=lambda *a: None)
    b3.arm()
    assert "BTC-USD" not in b3.positions, "el exchange manda sobre el estado local"
    b3.store.close(); os.unlink(p)


if __name__ == "__main__":
    import traceback
    os.environ["LIVE_TRADING_CONFIRMED"] = "yes-i-understand-the-risk"
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for t in tests:
        try:
            t(); print(f"  ✓ {t.__name__}"); ok += 1
        except Exception:
            print(f"  ✗ {t.__name__}"); traceback.print_exc()
    print(f"\n{ok}/{len(tests)} pruebas pasan")
