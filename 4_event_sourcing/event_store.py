import dataclasses
import json
import os
import sqlite3

from events import ProductCreated, StockUpdated, PriceChanged, ProductViewed

_DB_PATH = os.path.join(os.path.dirname(__file__), "event_store.db")

EVENT_TYPES = {
    "ProductCreated": ProductCreated,
    "StockUpdated":   StockUpdated,
    "PriceChanged":   PriceChanged,
    "ProductViewed":  ProductViewed,
}


def init_event_store():
    conn = sqlite3.connect(_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id   INTEGER NOT NULL,
            event_type   TEXT NOT NULL,
            data         TEXT NOT NULL,
            occurred_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    """)
    conn.commit()
    conn.close()


class EventStore:
    def _connect(self):
        conn = sqlite3.connect(_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def new_product_id(self) -> int:
        conn = self._connect()
        cursor = conn.execute("INSERT INTO product_registry DEFAULT VALUES")
        conn.commit()
        product_id = cursor.lastrowid
        conn.close()
        return product_id

    def append(self, event) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO events (product_id, event_type, data, occurred_at) VALUES (?, ?, ?, ?)",
            (
                event.product_id,
                type(event).__name__,
                json.dumps(dataclasses.asdict(event)),
                event.occurred_at,
            ),
        )
        conn.commit()
        conn.close()

    def load(self, product_id: int) -> list:
        conn = self._connect()
        rows = conn.execute(
            "SELECT event_type, data FROM events WHERE product_id = ? ORDER BY id ASC",
            (product_id,),
        ).fetchall()
        conn.close()
        return [EVENT_TYPES[r["event_type"]](**json.loads(r["data"])) for r in rows]

    def load_all(self) -> list:
        conn = self._connect()
        rows = conn.execute(
            "SELECT event_type, data FROM events ORDER BY id ASC"
        ).fetchall()
        conn.close()
        return [EVENT_TYPES[r["event_type"]](**json.loads(r["data"])) for r in rows]
