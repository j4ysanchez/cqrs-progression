from event_store import EventStore
from events import ProductCreated, StockUpdated, PriceChanged, ProductViewed
from read_db import get_read_connection


class Projector:
    def project(self, event) -> None:
        match event:
            case ProductCreated():  self._on_created(event)
            case StockUpdated():    self._on_stock_updated(event)
            case PriceChanged():    self._on_price_changed(event)
            case ProductViewed():   self._on_viewed(event)

    def rebuild_all(self, event_store: EventStore) -> None:
        """Wipe the read DB and replay every event from scratch."""
        conn = get_read_connection()
        conn.execute("DELETE FROM product_detail_view")
        conn.execute("DELETE FROM product_list_view")
        conn.commit()
        conn.close()
        for event in event_store.load_all():
            self.project(event)

    def _on_created(self, e: ProductCreated) -> None:
        conn = get_read_connection()
        conn.execute(
            "INSERT OR REPLACE INTO product_detail_view VALUES (?,?,?,?,?,?,?,?,?)",
            (e.product_id, e.name, e.description, e.price, e.stock,
             0, e.supplier_name, e.occurred_at, e.occurred_at),
        )
        conn.execute(
            "INSERT OR REPLACE INTO product_list_view VALUES (?,?,?,?,?)",
            (e.product_id, e.name, e.price, e.stock, e.supplier_name),
        )
        conn.commit()
        conn.close()

    def _on_stock_updated(self, e: StockUpdated) -> None:
        conn = get_read_connection()
        conn.execute(
            "UPDATE product_detail_view SET stock=?, updated_at=? WHERE id=?",
            (e.new_stock, e.occurred_at, e.product_id),
        )
        conn.execute(
            "UPDATE product_list_view SET stock=? WHERE id=?",
            (e.new_stock, e.product_id),
        )
        conn.commit()
        conn.close()

    def _on_price_changed(self, e: PriceChanged) -> None:
        conn = get_read_connection()
        conn.execute(
            "UPDATE product_detail_view SET price=?, updated_at=? WHERE id=?",
            (e.new_price, e.occurred_at, e.product_id),
        )
        conn.execute(
            "UPDATE product_list_view SET price=? WHERE id=?",
            (e.new_price, e.product_id),
        )
        conn.commit()
        conn.close()

    def _on_viewed(self, e: ProductViewed) -> None:
        conn = get_read_connection()
        conn.execute(
            "UPDATE product_detail_view SET view_count = view_count + 1 WHERE id=?",
            (e.product_id,),
        )
        conn.commit()
        conn.close()
