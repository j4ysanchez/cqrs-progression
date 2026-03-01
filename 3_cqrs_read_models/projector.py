from write_db import get_write_connection
from read_db import get_read_connection
from commands import CreateSupplier, CreateProduct, UpdateStock, ChangePrice, RecordProductView


class Projector:
    def project(self, command, entity_id: int | None = None) -> None:
        match command:
            case CreateSupplier():    self._on_supplier_created(command)
            case CreateProduct():     self._on_product_created(entity_id)
            case UpdateStock():       self._on_stock_updated(command)
            case ChangePrice():       self._on_price_changed(command)
            case RecordProductView(): self._on_view_recorded(command)

    def _fetch_product_with_supplier(self, product_id: int) -> dict | None:
        conn = get_write_connection()
        row = conn.execute(
            """
            SELECT
                p.id, p.name, p.description, p.price, p.stock,
                p.view_count, p.created_at, p.updated_at,
                s.name AS supplier_name
            FROM products p
            JOIN suppliers s ON s.id = p.supplier_id
            WHERE p.id = ?
            """,
            (product_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def _upsert_views(self, product: dict) -> None:
        conn = get_read_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO product_detail_view
                (id, name, description, price, stock, view_count,
                 supplier_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                product["id"], product["name"], product["description"],
                product["price"], product["stock"], product["view_count"],
                product["supplier_name"], product["created_at"], product["updated_at"],
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO product_list_view
                (id, name, price, stock, supplier_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                product["id"], product["name"], product["price"],
                product["stock"], product["supplier_name"],
            ),
        )
        conn.commit()
        conn.close()

    def _on_supplier_created(self, cmd: CreateSupplier) -> None:
        # Nothing to project yet — no product view references this supplier yet
        pass

    def _on_product_created(self, product_id: int) -> None:
        product = self._fetch_product_with_supplier(product_id)
        if product:
            self._upsert_views(product)

    def _on_stock_updated(self, cmd: UpdateStock) -> None:
        product = self._fetch_product_with_supplier(cmd.product_id)
        if product:
            self._upsert_views(product)

    def _on_price_changed(self, cmd: ChangePrice) -> None:
        product = self._fetch_product_with_supplier(cmd.product_id)
        if product:
            self._upsert_views(product)

    def _on_view_recorded(self, cmd: RecordProductView) -> None:
        # Only update view_count in detail view — list view doesn't show it
        conn = get_read_connection()
        conn.execute(
            "UPDATE product_detail_view SET view_count = view_count + 1 WHERE id = ?",
            (cmd.product_id,),
        )
        conn.commit()
        conn.close()
