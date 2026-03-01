from read_db import get_read_connection
from queries import (
    GetProductCard, GetProductDetail, ListProducts, SearchProducts,
    ProductCardDTO, ProductDetailDTO, ProductSummaryDTO,
)


class QueryHandler:
    def handle(self, query):
        match query:
            case GetProductCard():   return self._get_card(query)
            case GetProductDetail(): return self._get_detail(query)
            case ListProducts():     return self._list(query)
            case SearchProducts():   return self._search(query)
            case _: raise ValueError(f"Unknown query: {type(query)}")

    def _get_card(self, q: GetProductCard) -> ProductCardDTO | None:
        conn = get_read_connection()
        row = conn.execute(
            "SELECT id, name, price, stock FROM product_list_view WHERE id = ?",
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
        conn = get_read_connection()
        row = conn.execute(
            "SELECT * FROM product_detail_view WHERE id = ?",
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
            supplier_name=row["supplier_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _list(self, q: ListProducts) -> list[ProductSummaryDTO]:
        conn = get_read_connection()
        rows = conn.execute("SELECT * FROM product_list_view").fetchall()
        conn.close()
        return [
            ProductSummaryDTO(
                id=r["id"], name=r["name"], price=r["price"],
                stock=r["stock"], supplier_name=r["supplier_name"],
            )
            for r in rows
        ]

    def _search(self, q: SearchProducts) -> list[ProductSummaryDTO]:
        conn = get_read_connection()
        rows = conn.execute(
            "SELECT * FROM product_list_view WHERE name LIKE ?",
            (f"%{q.query}%",),
        ).fetchall()
        conn.close()
        return [
            ProductSummaryDTO(
                id=r["id"], name=r["name"], price=r["price"],
                stock=r["stock"], supplier_name=r["supplier_name"],
            )
            for r in rows
        ]
