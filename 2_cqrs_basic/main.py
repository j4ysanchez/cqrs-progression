import sys
import os

# Run from repo root: python 2_cqrs_basic/main.py
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db
from commands import CreateProduct, UpdateStock, ChangePrice, RecordProductView
from queries import GetProductCard, GetProductDetail, ListProducts, SearchProducts
from handlers import CommandHandler, QueryHandler


def main():
    init_db()
    cmd = CommandHandler()
    qry = QueryHandler()

    # Create products — command returns only the id
    widget_id = cmd.handle(CreateProduct(
        name="Widget Pro", price=29.99, cost_price=12.00,
        supplier_id=1, stock=100
    ))
    gadget_id = cmd.handle(CreateProduct(
        name="Gadget Plus", price=49.99, cost_price=22.50,
        supplier_id=2, stock=0
    ))

    # Read with a card query — notice no cost_price in the result
    print("=== Product Card (no cost_price) ===")
    print(qry.handle(GetProductCard(widget_id)))

    # View tracking is now explicit — the caller decides when to record a view
    cmd.handle(RecordProductView(widget_id))

    # Get full detail — still no cost_price, even in the admin view
    print("\n=== Widget Pro Detail (view_count=1, still no cost_price) ===")
    print(qry.handle(GetProductDetail(widget_id)))

    # Update operations
    cmd.handle(UpdateStock(gadget_id, new_stock=50))
    cmd.handle(ChangePrice(gadget_id, new_price=44.99))

    # Search and list
    print("\n=== Search 'gadget' ===")
    print(qry.handle(SearchProducts("gadget")))

    print("\n=== All products ===")
    print(qry.handle(ListProducts()))


if __name__ == "__main__":
    main()
