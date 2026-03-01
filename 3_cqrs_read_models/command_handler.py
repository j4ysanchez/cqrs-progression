from datetime import datetime

from write_db import get_write_connection
from commands import CreateSupplier, CreateProduct, UpdateStock, ChangePrice, RecordProductView


class CommandHandler:
    def handle(self, command) -> int | None:
        match command:
            case CreateSupplier():    return self._create_supplier(command)
            case CreateProduct():     return self._create_product(command)
            case UpdateStock():       return self._update_stock(command)
            case ChangePrice():       return self._change_price(command)
            case RecordProductView(): return self._record_view(command)
            case _: raise ValueError(f"Unknown command: {type(command)}")

    def _create_supplier(self, cmd: CreateSupplier) -> int:
        conn = get_write_connection()
        cursor = conn.execute(
            "INSERT INTO suppliers (name, email) VALUES (?, ?)",
            (cmd.name, cmd.email),
        )
        conn.commit()
        supplier_id = cursor.lastrowid
        conn.close()
        return supplier_id

    def _create_product(self, cmd: CreateProduct) -> int:
        conn = get_write_connection()
        row = conn.execute(
            "SELECT id FROM suppliers WHERE id = ?", (cmd.supplier_id,)
        ).fetchone()
        if row is None:
            conn.close()
            raise ValueError(f"Supplier {cmd.supplier_id} does not exist")

        now = datetime.utcnow().isoformat()
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
        conn = get_write_connection()
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
        conn = get_write_connection()
        conn.execute(
            "UPDATE products SET price = ?, updated_at = ? WHERE id = ?",
            (cmd.new_price, now, cmd.product_id),
        )
        conn.commit()
        conn.close()

    def _record_view(self, cmd: RecordProductView) -> None:
        conn = get_write_connection()
        conn.execute(
            "UPDATE products SET view_count = view_count + 1 WHERE id = ?",
            (cmd.product_id,),
        )
        conn.commit()
        conn.close()
