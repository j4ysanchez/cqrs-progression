import os
import sqlite3

_DB_PATH = os.path.join(os.path.dirname(__file__), "read.db")


def get_read_connection():
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_read_db():
    conn = get_read_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_detail_view (
            id            INTEGER PRIMARY KEY,
            name          TEXT NOT NULL,
            description   TEXT,
            price         REAL NOT NULL,
            stock         INTEGER NOT NULL,
            view_count    INTEGER NOT NULL,
            supplier_name TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_list_view (
            id            INTEGER PRIMARY KEY,
            name          TEXT NOT NULL,
            price         REAL NOT NULL,
            stock         INTEGER NOT NULL,
            supplier_name TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
