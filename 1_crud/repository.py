from datetime import datetime
from typing import Optional

from database import get_connection
from models import Product


class ProductRepository:

    def create(self, product: Product) -> Product:
        conn = get_connection()
        now = datetime.utcnow().isoformat()
        cursor = conn.execute(
            """
            INSERT INTO products (name, description, price, cost_price, supplier_id, stock, view_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (product.name, product.description, product.price, product.cost_price,
             product.supplier_id, product.stock, now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM products WHERE id = ?", (cursor.lastrowid,)).fetchone()
        conn.close()
        return self._row_to_product(row)

    def update_stock(self, product_id: int, new_stock: int) -> None:
        conn = get_connection()
        conn.execute(
            "UPDATE products SET stock = ?, updated_at = ? WHERE id = ?",
            (new_stock, datetime.utcnow().isoformat(), product_id),
        )
        conn.commit()
        conn.close()

    def change_price(self, product_id: int, new_price: float) -> None:
        conn = get_connection()
        conn.execute(
            "UPDATE products SET price = ?, updated_at = ? WHERE id = ?",
            (new_price, datetime.utcnow().isoformat(), product_id),
        )
        conn.commit()
        conn.close()

    def get_by_id(self, product_id: int) -> Optional[Product]:
        conn = get_connection()
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            conn.close()
            return None
        # A read operation secretly performs a write — this is awkward
        conn.execute(
            "UPDATE products SET view_count = view_count + 1 WHERE id = ?",
            (product_id,),
        )
        conn.commit()
        conn.close()
        return self._row_to_product(row)

    def get_product_card(self, product_id: int) -> Optional[dict]:
        conn = get_connection()
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        conn.close()
        if row is None:
            return None
        # Manually strip internal fields — nothing in the type system enforces this
        return {
            "id": row["id"],
            "name": row["name"],
            "price": row["price"],
            "in_stock": row["stock"] > 0,
        }

    def list_all(self) -> list[Product]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM products").fetchall()
        conn.close()
        return [self._row_to_product(r) for r in rows]

    def search(self, query: str) -> list[Product]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM products WHERE name LIKE ?", (f"%{query}%",)
        ).fetchall()
        conn.close()
        return [self._row_to_product(r) for r in rows]

    # ------------------------------------------------------------------ helpers

    def _row_to_product(self, row) -> Product:
        return Product(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            price=row["price"],
            cost_price=row["cost_price"],
            supplier_id=row["supplier_id"],
            stock=row["stock"],
            view_count=row["view_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
