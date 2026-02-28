# Stage 1: Naive CRUD — Feel the Pain

## Goal

Build a working product inventory system using the simplest possible approach: one model,
one repository, one database. No patterns, no abstractions beyond the basics.

By the end of this stage you will have a functional system — and a list of concrete
problems that grow from it. Those problems are exactly what CQRS is designed to solve.

---

## The Domain

You are building the backend for a small product inventory system. It needs to:

- Create products with a name, description, price, stock quantity, cost price, and supplier ID
- Update stock when inventory changes
- Change product prices
- Display a **product card** (public-facing summary: name, price, stock status)
- Display a **product detail view** (full info for an admin)
- List all products with basic info
- Search products by name
- Track how many times a product has been viewed

---

## File Structure

Create the following files inside `1_crud/`:

```
1_crud/
  database.py
  models.py
  repository.py
  main.py
  instructions.md   ← this file
```

---

## Step 1 — database.py

**What:** A module that creates and returns a SQLite connection.

**How:**

Use Python's built-in `sqlite3` module. Write a function `get_connection()` that:
1. Connects to a local file `inventory.db` (use `sqlite3.connect("1_crud/inventory.db")`)
2. Sets `row_factory = sqlite3.Row` so rows behave like dicts
3. Returns the connection

Write a second function `init_db()` that:
1. Gets a connection
2. Executes a `CREATE TABLE IF NOT EXISTS products` statement with these columns:
   - `id` INTEGER PRIMARY KEY AUTOINCREMENT
   - `name` TEXT NOT NULL
   - `description` TEXT
   - `price` REAL NOT NULL
   - `cost_price` REAL NOT NULL       ← internal, should never be public
   - `supplier_id` INTEGER NOT NULL   ← internal reference
   - `stock` INTEGER NOT NULL DEFAULT 0
   - `view_count` INTEGER NOT NULL DEFAULT 0
   - `created_at` TEXT NOT NULL
   - `updated_at` TEXT NOT NULL
3. Commits and closes the connection

**Why this column set matters:** Notice that `cost_price` and `supplier_id` are internal
business data that should never be exposed to end users. But they live in the same table
as everything else. This will become a problem when you write queries.

---

## Step 2 — models.py

**What:** A plain Python dataclass representing a product.

**How:**

Use `@dataclass` from the standard library. Create a `Product` dataclass with all the
fields from the database table. Use `field(default=None)` for `id`, `view_count`,
`created_at`, and `updated_at` since they are auto-managed.

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Product:
    name: str
    price: float
    cost_price: float
    supplier_id: int
    stock: int
    description: Optional[str] = None
    id: Optional[int] = None
    view_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
```

**Why a single model:** In CRUD, there is one representation of a product used
everywhere — creation, updates, reads, internal logic. This feels convenient now.
You will see why it is a problem in a moment.

---

## Step 3 — repository.py

**What:** A `ProductRepository` class that handles all reads AND writes for products.

This is the heart of Stage 1. Everything — creating, updating, reading, searching —
goes through one class.

**How:**

Import `get_connection` from `database.py` and `Product` from `models.py`.

Implement the following methods:

---

### 3a. `create(product: Product) -> Product`

1. Get a connection
2. Insert all product fields. For `created_at` and `updated_at`, use
   `datetime.utcnow().isoformat()`
3. Commit, then fetch the inserted row using `cursor.lastrowid`
4. Return a new `Product` built from the fetched row

---

### 3b. `update_stock(product_id: int, new_stock: int) -> None`

1. Get a connection
2. Run an `UPDATE` that sets `stock = ?` and `updated_at = now` where `id = ?`
3. Commit

**Note what is happening:** even though you only want to change one field, you still
touch the same row that holds cost_price, supplier_id, and every other piece of data.
In a concurrent system, this creates contention.

---

### 3c. `change_price(product_id: int, new_price: float) -> None`

Same pattern as `update_stock` but updating `price`.

---

### 3d. `get_by_id(product_id: int) -> Optional[Product]`

1. Get a connection
2. Run `SELECT * FROM products WHERE id = ?`
3. Increment `view_count` with a second `UPDATE` statement (tracking views requires
   a write even for a read operation — notice this awkwardness)
4. Return a `Product` built from the row, or `None` if not found

**Why this is painful:** To show a product to a customer, you're returning the full
`Product` object — including `cost_price` and `supplier_id`. The caller must know to
ignore those fields. There is nothing in the type system enforcing this.

---

### 3e. `get_product_card(product_id: int) -> Optional[dict]`

A "product card" is the public-facing summary. For now, manually extract only the
safe fields and return a dict:

```python
return {
    "id": row["id"],
    "name": row["name"],
    "price": row["price"],
    "in_stock": row["stock"] > 0,
}
```

**Why a dict and not a class?** You don't have a `ProductCard` model because there's
only one model: `Product`. You resort to returning a raw dict to avoid exposing
internal fields. This is a code smell.

---

### 3f. `list_all() -> list[Product]`

Run `SELECT * FROM products` and return a list of `Product` objects.

**The problem:** You fetch every column — including cost_price and supplier_id — for
every product, even when listing just names and prices on a dashboard. As the table
grows (more columns, more rows), this becomes wasteful.

---

### 3g. `search(query: str) -> list[Product]`

Run `SELECT * FROM products WHERE name LIKE ?` with `f"%{query}%"`.

Notice: you again return full `Product` objects even though a search result only needs
name, id, and price.

---

## Step 4 — main.py

**What:** A script that exercises the full system and prints output so you can see it working.

**How:**

Write a `main()` function that runs this scenario:

```
1. Call init_db() to set up the database
2. Create two products:
     - Widget Pro: price=29.99, cost_price=12.00, supplier_id=1, stock=100
     - Gadget Plus: price=49.99, cost_price=22.50, supplier_id=2, stock=0
3. Print both product cards (should show in_stock: True / False)
4. Print the full detail of Widget Pro (notice cost_price and supplier_id are exposed)
5. Update Widget Pro's stock to 50
6. Change Gadget Plus's price to 44.99
7. Search for "gadget" and print results
8. List all products and print their names and prices
```

Use `pprint` from the standard library to print dicts and objects clearly.

Run it with: `python 1_crud/main.py`

---

## Step 5 — Observe the Problems

Once the system is working, read through the code and note these specific issues.
Write them as comments in `main.py` or just keep them in mind as you move to Stage 2.

### Problem 1: Leaking Internal Data

`get_by_id()` returns a `Product` with `cost_price` and `supplier_id`. Any code that
calls this method must manually ignore those fields. There is no type-safe way to
say "give me a product without internal fields."

### Problem 2: Reads That Require Writes

`get_by_id()` increments `view_count`. A read operation is secretly a write. This
means you cannot safely run read replicas or cache results without extra logic.

### Problem 3: One Model Serves Too Many Masters

The `Product` class is used for:
- Creating a product (needs cost_price)
- Updating stock (needs only stock + id)
- Displaying a card (needs only name, price, stock)
- Admin detail view (needs everything)

Every caller gets everything and must know which fields apply to their use case.

### Problem 4: No Separation of Intent

`update_stock` and `change_price` are just method calls. There is no record of
*why* the stock changed or *who* changed the price. Auditing is impossible without
adding more columns to the same model.

### Problem 5: Read Performance Couples to Write Schema

If you add a column for write purposes (e.g., `reorder_threshold`), all read queries
start returning it too. Optimizing reads means changing the same table that handles
writes, which can break write performance.

---

## What You Built

A fully working inventory system that is simple, readable, and immediately problematic
at scale. This is the starting point. Every problem listed above has a direct solution
in CQRS.

**Move to Stage 2 when:** you can run `main.py` end-to-end and articulate at least
three of the five problems above in your own words.
