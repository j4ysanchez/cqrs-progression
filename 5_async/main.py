from bus import MessageBus
from command_handler import CommandHandler
from commands import CreateProduct, UpdateStock, ChangePrice, RecordProductView
from event_handlers import AuditLogHandler, LowStockAlertHandler, ProjectorHandler
from event_store import EventStore, init_event_store
from events import ProductCreated, StockUpdated, PriceChanged, ProductViewed
from queries import GetProductDetail, ListProducts
from query_handler import QueryHandler
from read_db import init_read_db


def main():
    init_event_store()
    init_read_db()

    # --- Wire up the bus ---
    bus = MessageBus()
    projector_handler = ProjectorHandler()
    audit_handler     = AuditLogHandler()
    low_stock_handler = LowStockAlertHandler()

    bus.subscribe(ProductCreated, projector_handler.on_product_created)
    bus.subscribe(StockUpdated,   projector_handler.on_stock_updated)
    bus.subscribe(PriceChanged,   projector_handler.on_price_changed)
    bus.subscribe(ProductViewed,  projector_handler.on_product_viewed)

    bus.subscribe(ProductCreated, audit_handler.on_event)
    bus.subscribe(StockUpdated,   audit_handler.on_event)
    bus.subscribe(PriceChanged,   audit_handler.on_event)

    bus.subscribe(StockUpdated, low_stock_handler.on_stock_updated)

    bus.start()

    store = EventStore()
    cmd   = CommandHandler(store, bus)
    qry   = QueryHandler()

    # --- Create products ---
    print("=== Creating products ===")
    widget_id = cmd.handle(CreateProduct(
        name="Widget Pro", price=29.99, cost_price=12.00,
        supplier_id=1, supplier_name="Acme Corp", stock=100
    ))
    gadget_id = cmd.handle(CreateProduct(
        name="Gadget Plus", price=49.99, cost_price=22.50,
        supplier_id=1, supplier_name="Acme Corp", stock=15
    ))

    # --- Demonstrate eventual consistency ---
    print("\n=== Query WITHOUT flush (may be stale) ===")
    result = qry.handle(GetProductDetail(widget_id))
    # result may be None or show old data — the background thread may not have
    # finished projecting yet
    print(f"  Widget Pro detail: {result}")

    print(f"Flushing now...")
    bus.flush()  # wait for all published events to be fully processed

    print("\n=== Query AFTER flush (consistent) ===")
    result = qry.handle(GetProductDetail(widget_id))
    print(f"  Widget Pro detail: {result}")

    # --- Fan-out: one event, multiple handlers fire ---
    print("\n=== Updating stock to 8 (below alert threshold) ===")
    cmd.handle(UpdateStock(gadget_id, new_stock=8))
    bus.flush()
    # You should see BOTH the audit log line AND the low-stock alert

    # --- Price change ---
    cmd.handle(ChangePrice(gadget_id, new_price=44.99))
    bus.flush()

    # --- View tracking ---
    cmd.handle(RecordProductView(widget_id))
    cmd.handle(RecordProductView(widget_id))
    bus.flush()

    # --- Final state ---
    print("\n=== Final product list ===")
    for product in qry.handle(ListProducts()):
        print(f"  {product}")

    bus.stop()


if __name__ == "__main__":
    main()
