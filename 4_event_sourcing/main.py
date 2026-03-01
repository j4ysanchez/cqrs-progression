from event_store import EventStore, init_event_store
from read_db import init_read_db
from commands import CreateProduct, UpdateStock, ChangePrice, RecordProductView
from queries import GetProductDetail, GetProductCard, ListProducts, SearchProducts
from command_handler import CommandHandler
from query_handler import QueryHandler
from projector import Projector


def main():
    init_event_store()
    init_read_db()

    store = EventStore()
    cmd = CommandHandler(store)
    qry = QueryHandler()
    prj = Projector()

    # Create a product — the command handler emits a ProductCreated event
    widget_id = cmd.handle(CreateProduct(
        name="Widget Pro", price=29.99, cost_price=12.00,
        supplier_id=1, supplier_name="Acme Corp", stock=100,
    ))
    # Project the last emitted event into the read model
    prj.project(store.load(widget_id)[-1])

    gadget_id = cmd.handle(CreateProduct(
        name="Gadget Plus", price=49.99, cost_price=22.50,
        supplier_id=1, supplier_name="Acme Corp", stock=0,
    ))
    prj.project(store.load(gadget_id)[-1])

    # Query — read model is populated
    print(qry.handle(GetProductDetail(widget_id)))

    # Update stock
    cmd.handle(UpdateStock(gadget_id, new_stock=50))
    prj.project(store.load(gadget_id)[-1])

    # Change price
    cmd.handle(ChangePrice(gadget_id, new_price=44.99))
    prj.project(store.load(gadget_id)[-1])

    # === The Event Sourcing payoff: print the full audit trail ===
    print("\n--- Event Log for Gadget Plus ---")
    for event in store.load(gadget_id):
        print(f"  [{event.occurred_at}] {type(event).__name__}: {event}")

    # === Demonstrate rebuild ===
    print("\n--- Rebuilding read model from scratch ---")
    prj.rebuild_all(store)
    print(qry.handle(ListProducts()))


if __name__ == "__main__":
    main()
