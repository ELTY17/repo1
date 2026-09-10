"""Estado en disco.

Hasta ahora las posiciones vivian solo en memoria: si el proceso se reiniciaba,
el bot creia que no tenia nada abierto mientras el exchange si las tenia. Aqui se
guardan en SQLite, que basta y no anade dependencias.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
  symbol TEXT PRIMARY KEY, qty REAL, entry REAL, stop REAL, target REAL,
  atr REAL, high_water REAL, opened_at INTEGER,
  stop_txid TEXT, entry_txid TEXT
);
CREATE TABLE IF NOT EXISTS orders (
  userref INTEGER PRIMARY KEY, txid TEXT, symbol TEXT, side TEXT,
  qty REAL, filled REAL, price REAL, status TEXT, reason TEXT,
  created_at INTEGER, updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT, t INTEGER, side TEXT, symbol TEXT,
  qty REAL, price REAL, fee REAL, pnl REAL, reason TEXT, txid TEXT
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


class Store:
    def __init__(self, path: str = "state.db"):
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self):
        with self._lock:
            self._db.close()

    # --- meta ---
    def get(self, k, default=None):
        with self._lock:
            r = self._db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else default

    def put(self, k, v):
        with self._lock:
            self._db.execute("INSERT INTO meta(k,v) VALUES(?,?) "
                             "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                             (k, json.dumps(v)))
            self._db.commit()

    def next_userref(self) -> int:
        """Identificador propio de la orden: sin el, un reintento duplica."""
        with self._lock:
            n = int(self.get("userref", 1000000)) + 1
            self.put("userref", n)
            return n

    # --- posiciones ---
    def save_position(self, p: dict):
        with self._lock:
            self._db.execute(
                "INSERT INTO positions(symbol,qty,entry,stop,target,atr,high_water,"
                "opened_at,stop_txid,entry_txid) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(symbol) DO UPDATE SET qty=excluded.qty,entry=excluded.entry,"
                "stop=excluded.stop,target=excluded.target,atr=excluded.atr,"
                "high_water=excluded.high_water,stop_txid=excluded.stop_txid",
                (p["symbol"], p["qty"], p["entry"], p["stop"], p.get("target"),
                 p.get("atr"), p.get("high_water", p["entry"]),
                 p.get("opened_at", int(time.time())),
                 p.get("stop_txid"), p.get("entry_txid")))
            self._db.commit()

    def drop_position(self, symbol: str):
        with self._lock:
            self._db.execute("DELETE FROM positions WHERE symbol=?", (symbol,))
            self._db.commit()

    def positions(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM positions")]

    # --- ordenes ---
    def save_order(self, o: dict):
        now = int(time.time())
        with self._lock:
            self._db.execute(
                "INSERT INTO orders(userref,txid,symbol,side,qty,filled,price,status,"
                "reason,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(userref) DO UPDATE SET txid=excluded.txid,"
                "filled=excluded.filled,price=excluded.price,status=excluded.status,"
                "updated_at=excluded.updated_at",
                (o["userref"], o.get("txid"), o["symbol"], o["side"], o["qty"],
                 o.get("filled", 0.0), o.get("price"), o.get("status", "sent"),
                 o.get("reason", ""), o.get("created_at", now), now))
            self._db.commit()

    def open_orders(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT * FROM orders WHERE status IN ('sent','open','partial')")]

    def order_by_ref(self, userref: int) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM orders WHERE userref=?",
                                 (userref,)).fetchone()
        return dict(r) if r else None

    # --- operaciones ---
    def add_trade(self, t: dict):
        with self._lock:
            self._db.execute(
                "INSERT INTO trades(t,side,symbol,qty,price,fee,pnl,reason,txid) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (t.get("t", int(time.time())), t["side"], t["symbol"], t["qty"],
                 t["price"], t.get("fee", 0.0), t.get("pnl"), t.get("reason", ""),
                 t.get("txid")))
            self._db.commit()

    def trades(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))][::-1]
