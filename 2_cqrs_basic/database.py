import os
import sqlite3

_DB_PATH = os.path.join(os.path.dirname(__file__), "inventory.db")


def get_connection():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT,
            price       REAL NOT NULL,
            cost_price  REAL NOT NULL,
            supplier_id INTEGER NOT NULL,
            stock       INTEGER NOT NULL DEFAULT 0,
            view_count  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
