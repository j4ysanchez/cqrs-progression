from datetime import datetime

from database import get_connection
from commands import CreateProduct, UpdateStock, ChangePrice, RecordProductView
from queries import (
    GetProductCard, GetProductDetail, ListProducts, SearchProducts,
    ProductCardDTO, ProductDetailDTO, ProductSummaryDTO,
)


class CommandHandler:
    def handle(self, command):
        match command:
            case CreateProduct():       return self._create_product(command)
            case UpdateStock():         return self._update_stock(command)
            case ChangePrice():         return self._change_price(command)
            case RecordProductView():   return self._record_view(command)
            case _: raise ValueError(f"Unknown command: {type(command)}")

    def _create_product(self, cmd: CreateProduct) -> int:
        now = datetime.utcnow().isoformat()
        conn = get_connection()
        cursor = conn.execute(
            """
            INSERT INTO products (name, description, price, cost_price, supplier_id,
                                  stock, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cmd.name, cmd.description, cmd.price, cmd.cost_price,
             cmd.supplier_id, cmd.stock, now, now),
        )
        conn.commit()
        product_id = cursor.lastrowid
        conn.close()
        return product_id

    def _update_stock(self, cmd: UpdateStock) -> None:
        if cmd.new_stock < 0:
            raise ValueError("stock cannot be negative")
        now = datetime.utcnow().isoformat()
        conn = get_connection()
        conn.execute(
            "UPDATE products SET stock = ?, updated_at = ? WHERE id = ?",
            (cmd.new_stock, now, cmd.product_id),
        )
        conn.commit()
        conn.close()

    def _change_price(self, cmd: ChangePrice) -> None:
        if cmd.new_price <= 0:
            raise ValueError("price must be positive")
        now = datetime.utcnow().isoformat()
        conn = get_connection()
        conn.execute(
            "UPDATE products SET price = ?, updated_at = ? WHERE id = ?",
            (cmd.new_price, now, cmd.product_id),
        )
        conn.commit()
        conn.close()

    def _record_view(self, cmd: RecordProductView) -> None:
        conn = get_connection()
        conn.execute(
            "UPDATE products SET view_count = view_count + 1 WHERE id = ?",
            (cmd.product_id,),
        )
        conn.commit()
        conn.close()


class QueryHandler:
    def handle(self, query):
        match query:
            case GetProductCard():   return self._get_card(query)
            case GetProductDetail(): return self._get_detail(query)
            case ListProducts():     return self._list(query)
            case SearchProducts():   return self._search(query)
            case _: raise ValueError(f"Unknown query: {type(query)}")

    def _get_card(self, q: GetProductCard) -> ProductCardDTO | None:
        conn = get_connection()
        row = conn.execute(
            "SELECT id, name, price, stock FROM products WHERE id = ?",
            (q.product_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return ProductCardDTO(
            id=row["id"],
            name=row["name"],
            price=row["price"],
            in_stock=row["stock"] > 0,
        )

    def _get_detail(self, q: GetProductDetail) -> ProductDetailDTO | None:
        conn = get_connection()
        row = conn.execute(
            """
            SELECT id, name, description, price, stock, view_count, created_at, updated_at
            FROM products WHERE id = ?
            """,
            (q.product_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return ProductDetailDTO(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            price=row["price"],
            stock=row["stock"],
            view_count=row["view_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _list(self, q: ListProducts) -> list[ProductSummaryDTO]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, name, price, stock FROM products"
        ).fetchall()
        conn.close()
        return [
            ProductSummaryDTO(id=r["id"], name=r["name"], price=r["price"], stock=r["stock"])
            for r in rows
        ]

    def _search(self, q: SearchProducts) -> list[ProductSummaryDTO]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, name, price, stock FROM products WHERE name LIKE ?",
            (f"%{q.query}%",),
        ).fetchall()
        conn.close()
        return [
            ProductSummaryDTO(id=r["id"], name=r["name"], price=r["price"], stock=r["stock"])
            for r in rows
        ]
