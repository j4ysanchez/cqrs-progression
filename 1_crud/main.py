import sys
import os
from pprint import pprint

# Run from repo root: python 1_crud/main.py
sys.path.insert(0, os.path.dirname(__file__))

from database import init_db
from models import Product
from repository import ProductRepository


def main():
    # 1. Set up the database
    init_db()

    repo = ProductRepository()

    # 2. Create two products
    widget = repo.create(Product(
        name="Widget Pro",
        description="A professional-grade widget",
        price=29.99,
        cost_price=12.00,
        supplier_id=1,
        stock=100,
    ))
    gadget = repo.create(Product(
        name="Gadget Plus",
        description="An enhanced gadget",
        price=49.99,
        cost_price=22.50,
        supplier_id=2,
        stock=0,
    ))

    # 3. Print product cards (public-facing — in_stock: True / False)
    print("=== Product Cards ===")
    pprint(repo.get_product_card(widget.id))
    pprint(repo.get_product_card(gadget.id))

    # 4. Print full detail of Widget Pro
    #    PROBLEM 1: cost_price and supplier_id are exposed to the caller
    print("\n=== Widget Pro — Full Detail (notice cost_price & supplier_id leak) ===")
    pprint(repo.get_by_id(widget.id))

    # 5. Update Widget Pro's stock
    repo.update_stock(widget.id, 50)
    print("\n=== Widget Pro stock updated to 50 ===")

    # 6. Change Gadget Plus's price
    repo.change_price(gadget.id, 44.99)
    print("=== Gadget Plus price changed to 44.99 ===")

    # 7. Search for "gadget"
    print("\n=== Search results for 'gadget' ===")
    for p in repo.search("gadget"):
        print(f"  [{p.id}] {p.name} — ${p.price}")

    # 8. List all products
    print("\n=== All products ===")
    for p in repo.list_all():
        print(f"  [{p.id}] {p.name} — ${p.price}")


if __name__ == "__main__":
    main()
