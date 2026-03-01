 import sys
import os

# Run from repo root: python 3_cqrs_read_models/main.py
sys.path.insert(0, os.path.dirname(__file__))

from write_db import init_write_db
from read_db import init_read_db
from commands import CreateSupplier, CreateProduct, UpdateStock, ChangePrice, RecordProductView
from queries import GetProductCard, GetProductDetail, ListProducts, SearchProducts
from command_handler import CommandHandler
from query_handler import QueryHandler
from projector import Projector


def main():
    init_write_db()
    init_read_db()

    cmd = CommandHandler()
    qry = QueryHandler()
    prj = Projector()

    # Create a supplier — write side now knows about suppliers
    supplier_id = cmd.handle(CreateSupplier(name="Acme Corp", email="orders@acme.com"))
    # No projection needed — no product view references this supplier yet

    # Create products (command → project → the read model is now in sync)
    widget_id = cmd.handle(CreateProduct(
        name="Widget Pro", price=29.99, cost_price=12.00,
        supplier_id=supplier_id, stock=100,
    ))
    prj.project(CreateProduct(
        name="Widget Pro", price=29.99, cost_price=12.00,
        supplier_id=supplier_id, stock=100,
    ), entity_id=widget_id)

    gadget_id = cmd.handle(CreateProduct(
        name="Gadget Plus", price=49.99, cost_price=22.50,
        supplier_id=supplier_id, stock=0,
    ))
    prj.project(CreateProduct(
        name="Gadget Plus", price=49.99, cost_price=22.50,
        supplier_id=supplier_id, stock=0,
    ), entity_id=gadget_id)

    # Query — supplier_name appears with no JOIN in the query handler
    print("=== Widget Pro Detail (supplier_name pre-joined, no cost_price) ===")
    print(qry.handle(GetProductDetail(widget_id)))

    # Product card — public-facing, no supplier shown
    print("\n=== Widget Pro Card (public, in_stock=True) ===")
    print(qry.handle(GetProductCard(widget_id)))

    # View tracking — command writes to write DB, projector updates read DB
    cmd.handle(RecordProductView(widget_id))
    prj.project(RecordProductView(widget_id))

    print("\n=== Widget Pro Detail after view (view_count=1) ===")
    print(qry.handle(GetProductDetail(widget_id)))

    # Stock update
    cmd.handle(UpdateStock(gadget_id, new_stock=50))
    prj.project(UpdateStock(gadget_id, new_stock=50))

    # Price change
    cmd.handle(ChangePrice(gadget_id, new_price=44.99))
    prj.project(ChangePrice(gadget_id, new_price=44.99))

    # Queries — hitting the read DB only, no joins
    print("\n=== Search 'gadget' (supplier_name in result) ===")
    print(qry.handle(SearchProducts("gadget")))

    print("\n=== All products ===")
    print(qry.handle(ListProducts()))


if __name__ == "__main__":
    main()
