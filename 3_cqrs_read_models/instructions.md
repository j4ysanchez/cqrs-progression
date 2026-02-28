# Stage 3: Separate Read Models — Optimize Each Side Independently

## Goal

Introduce a dedicated read database with pre-built, denormalized views. The write
database stays normalized for integrity. A new component — the **Projector** — keeps
the read database in sync after every command.

This stage solves the last remaining problem from Stage 1: read performance is
coupled to the write schema. It also introduces the first real trade-off in CQRS:
**eventual consistency**.

---

## What Changes vs Stage 2

| Concern | Stage 2 | Stage 3 |
|---|---|---|
| Database | One shared SQLite file | Two SQLite files: write + read |
| Write schema | One products table | Normalized: products + suppliers |
| Read schema | Same products table | Denormalized flat views |
| Query joins | Done at query time | Done once at write time (by the Projector) |
| Supplier name in UI | Not shown (only supplier_id) | Pre-joined into read model |
| Consistency | Immediate | Eventual (read model updated after write) |

---

## The Domain Change

The write side gains a `suppliers` table. Products now have a real foreign key
to a supplier. The read side exposes `supplier_name` directly in the detail view —
no join needed at query time.

This is the concrete motivation for read models: the write model stores a reference
(`supplier_id`), but the UI wants a name (`supplier_name`). In Stage 2 you would
need a JOIN every time you read a product. In Stage 3, the Projector resolves that
join once when data changes and stores the result in the read table.

---

## File Structure

```
3_cqrs_read_models/
  write_db.py          ← write-side DB: products + suppliers (normalized)
  read_db.py           ← read-side DB: flat denormalized view tables
  commands.py          ← same as Stage 2 + CreateSupplier
  queries.py           ← same DTOs, now include supplier_name
  command_handler.py   ← writes to write DB only
  query_handler.py     ← reads from read DB only
  projector.py         ← the bridge: reads write DB, updates read DB
  main.py
  instructions.md      ← this file
```

Note: `handlers.py` is now split into two files. With two databases involved, keeping
them in one file obscures which side each handler belongs to.

---

## Step 1 — write_db.py

**What:** Initialize the write-side SQLite database. This is the source of truth.

**How:**

Connect to `3_cqrs_read_models/write.db`. Create two tables:

**`suppliers` table:**
```sql
CREATE TABLE IF NOT EXISTS suppliers (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT NOT NULL,
    email   TEXT NOT NULL
)
```

**`products` table:**
```sql
CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    price       REAL NOT NULL,
    cost_price  REAL NOT NULL,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    stock       INTEGER NOT NULL DEFAULT 0,
    view_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
```

Write `get_write_connection()` and `init_write_db()` functions following the same
pattern as Stage 1.

**Why normalized:** The write side stores data the way a relational database is
designed to — one fact in one place. `supplier_id` is a foreign key. The supplier's
name lives in the `suppliers` table, not duplicated in every product row. If a
supplier changes their name, you update one row and it's correct everywhere.

---

## Step 2 — read_db.py

**What:** Initialize the read-side SQLite database. This is optimized for queries.

**How:**

Connect to `3_cqrs_read_models/read.db`. Create two tables:

**`product_detail_view` table:**
```sql
CREATE TABLE IF NOT EXISTS product_detail_view (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT,
    price         REAL NOT NULL,
    stock         INTEGER NOT NULL,
    view_count    INTEGER NOT NULL,
    supplier_name TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
)
```

**`product_list_view` table:**
```sql
CREATE TABLE IF NOT EXISTS product_list_view (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    price         REAL NOT NULL,
    stock         INTEGER NOT NULL,
    supplier_name TEXT NOT NULL
)
```

Write `get_read_connection()` and `init_read_db()` functions.

**Why denormalized:** The read side stores data the way a UI wants to consume it.
`supplier_name` is copied directly into both view tables. Queries are pure lookups —
no joins, no subqueries. The trade-off is duplication: if a supplier name changes,
the Projector must update every product row in the read DB. This is acceptable
because supplier name changes are rare, but product detail views are fetched
constantly.

**Notice what is absent:** `cost_price` and `supplier_id` are not in either read
table. They are write-side concerns only. They are structurally impossible to leak
now — not just by convention.

---

## Step 3 — commands.py

Copy from Stage 2 and add one new command:

```python
@dataclass
class CreateSupplier:
    name: str
    email: str
```

All other commands (`CreateProduct`, `UpdateStock`, `ChangePrice`,
`RecordProductView`) remain identical to Stage 2.

---

## Step 4 — queries.py

**What:** Update the DTOs to include `supplier_name` and add a new card query.

**How:**

Update `ProductDetailDTO`:
```python
@dataclass
class ProductDetailDTO:
    id: int
    name: str
    description: str | None
    price: float
    stock: int
    view_count: int
    supplier_name: str      ← new: resolved from the read model
    created_at: str
    updated_at: str
```

Update `ProductSummaryDTO`:
```python
@dataclass
class ProductSummaryDTO:
    id: int
    name: str
    price: float
    stock: int
    supplier_name: str      ← new
```

`ProductCardDTO` stays the same — the card is public-facing and doesn't show the
supplier.

Query objects (`GetProductCard`, `GetProductDetail`, `ListProducts`,
`SearchProducts`) are identical to Stage 2.

**Why the DTOs change here and not in the query handler:** The DTO defines what the
caller receives. Updating the DTO signals to every caller that `supplier_name` is
now available without changing any method signatures. The query handler just fills it.

---

## Step 5 — command_handler.py

**What:** Handles all commands, writing only to the write DB. Does not touch the
read DB.

**How:**

```python
class CommandHandler:
    def handle(self, command) -> int | None:
        match command:
            case CreateSupplier():    return self._create_supplier(command)
            case CreateProduct():     return self._create_product(command)
            case UpdateStock():       return self._update_stock(command)
            case ChangePrice():       return self._change_price(command)
            case RecordProductView(): return self._record_view(command)
```

**`_create_supplier(cmd: CreateSupplier) -> int`**
1. INSERT into `suppliers` (name, email)
2. Return the new supplier's id

**`_create_product(cmd: CreateProduct) -> int`**
1. Validate: `supplier_id` exists in `suppliers` table — raise `ValueError` if not
2. INSERT into `products` with all fields
3. Return the new product's id

**`_update_stock(cmd: UpdateStock)`**
Same as Stage 2: validate `new_stock >= 0`, UPDATE, commit.

**`_change_price(cmd: ChangePrice)`**
Same as Stage 2: validate `new_price > 0`, UPDATE, commit.

**`_record_view(cmd: RecordProductView)`**
Same as Stage 2: increment `view_count` in write DB.

**What this handler does NOT do:** It never touches `read.db`. It never calls the
Projector. The command handler's job ends at the write commit. Keeping the Projector
call outside the command handler makes the eventual consistency explicit in the
application flow — you can see the gap.

---

## Step 6 — query_handler.py

**What:** Handles all queries, reading only from the read DB. Does not touch write DB.

**How:**

```python
class QueryHandler:
    def handle(self, query):
        match query:
            case GetProductCard():   return self._get_card(query)
            case GetProductDetail(): return self._get_detail(query)
            case ListProducts():     return self._list(query)
            case SearchProducts():   return self._search(query)
```

**`_get_card(q: GetProductCard) -> ProductCardDTO | None`**
1. SELECT id, name, price, stock FROM `product_list_view` WHERE id = ?
2. Return `ProductCardDTO(in_stock=row["stock"] > 0, ...)`

**`_get_detail(q: GetProductDetail) -> ProductDetailDTO | None`**
1. SELECT * FROM `product_detail_view` WHERE id = ?
2. Return `ProductDetailDTO(...)` — `supplier_name` is already in the row, no JOIN needed

**`_list(q: ListProducts) -> list[ProductSummaryDTO]`**
1. SELECT * FROM `product_list_view`
2. Return list of `ProductSummaryDTO`

**`_search(q: SearchProducts) -> list[ProductSummaryDTO]`**
1. SELECT * FROM `product_list_view` WHERE name LIKE ?
2. Return list of `ProductSummaryDTO`

**The payoff:** Every query is a flat SELECT with no joins. The query handler has no
knowledge of suppliers, foreign keys, or normalization. It treats the read DB as a
simple key-value store optimized for its specific access patterns.

---

## Step 7 — projector.py

**What:** The bridge between the write DB and the read DB. After a command changes
the write DB, the Projector reads the updated data (with joins) from the write DB
and writes the result to the read DB.

This is the most important new concept in Stage 3.

**How:**

```python
class Projector:
    def project(self, command) -> None:
        match command:
            case CreateSupplier():    self._on_supplier_created(command)
            case CreateProduct():     self._on_product_created(command)
            case UpdateStock():       self._on_stock_updated(command)
            case ChangePrice():       self._on_price_changed(command)
            case RecordProductView(): self._on_view_recorded(command)
```

All projection methods share a common pattern:

1. Read the current state from the **write DB** (with the JOIN to get supplier_name)
2. Upsert (`INSERT OR REPLACE`) into the **read DB** view tables

Define a private helper `_fetch_product_with_supplier(product_id) -> dict | None`
that runs this query against the write DB:

```sql
SELECT
    p.id, p.name, p.description, p.price, p.stock,
    p.view_count, p.created_at, p.updated_at,
    s.name AS supplier_name
FROM products p
JOIN suppliers s ON s.id = p.supplier_id
WHERE p.id = ?
```

This is the only JOIN in the entire system — and it runs on writes, not reads.

---

**`_on_product_created(cmd: CreateProduct)`**

1. Call `_fetch_product_with_supplier(cmd.product_id)` — wait, the command doesn't
   carry the new id. You have two options:
   - Change `CommandHandler._create_product` to also return the row for the projector
   - Store the last inserted id and pass it through the application flow

   Use the second approach: `main.py` captures the returned id from the command
   handler and passes it to the projector as a keyword arg. Update the projector
   method signature: `_on_product_created(self, product_id: int)`.

   Actually, the cleanest design for this stage: give `project()` an optional
   `entity_id` parameter that is passed through to specific handlers that need it:
   ```python
   def project(self, command, entity_id: int | None = None) -> None:
   ```

2. Fetch the product+supplier row from write DB
3. `INSERT OR REPLACE INTO product_detail_view VALUES (...)`
4. `INSERT OR REPLACE INTO product_list_view VALUES (...)`

**`_on_stock_updated(cmd: UpdateStock)`**
1. Fetch the product+supplier row using `cmd.product_id`
2. `INSERT OR REPLACE` both view tables

**`_on_price_changed(cmd: ChangePrice)`**
Same pattern: fetch, upsert.

**`_on_view_recorded(cmd: RecordProductView)`**
Only update `view_count` in `product_detail_view`:
```sql
UPDATE product_detail_view SET view_count = view_count + 1 WHERE id = ?
```
No need to touch `product_list_view` — it doesn't show view counts.

**`_on_supplier_created(cmd: CreateSupplier)`**
Nothing to project yet — supplier data will flow into view tables when products
referencing this supplier are created or updated. If you want a supplier list view,
you could add a `supplier_list_view` table, but that's outside this stage's scope.

---

## Step 8 — main.py

**What:** Same business scenario as Stages 1 and 2. Now the flow has three steps:
issue command → project → query.

**How:**

```python
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

    # Create a supplier first — write side now knows about suppliers
    supplier_id = cmd.handle(CreateSupplier(name="Acme Corp", email="orders@acme.com"))
    # No projection needed — no product view references this supplier yet

    # Create products
    widget_id = cmd.handle(CreateProduct(
        name="Widget Pro", price=29.99, cost_price=12.00,
        supplier_id=supplier_id, stock=100
    ))
    prj.project(CreateProduct(...), entity_id=widget_id)  # projection step is explicit

    gadget_id = cmd.handle(CreateProduct(
        name="Gadget Plus", price=49.99, cost_price=22.50,
        supplier_id=supplier_id, stock=0
    ))
    prj.project(CreateProduct(...), entity_id=gadget_id)

    # Query — supplier_name now appears in the result with no JOIN in the query
    print(qry.handle(GetProductDetail(widget_id)))

    # View tracking
    cmd.handle(RecordProductView(widget_id))
    prj.project(RecordProductView(widget_id))

    # Stock update
    cmd.handle(UpdateStock(gadget_id, new_stock=50))
    prj.project(UpdateStock(gadget_id, new_stock=50))

    # Price change
    cmd.handle(ChangePrice(gadget_id, new_price=44.99))
    prj.project(ChangePrice(gadget_id, new_price=44.99))

    # Queries — hitting the read DB only
    print(qry.handle(SearchProducts("gadget")))
    print(qry.handle(ListProducts()))
```

**Why the projection calls are explicit in main.py:** You want to see the three-step
rhythm — command, project, query — as three distinct actions. This makes the eventual
consistency gap visible. In production systems this projection call becomes an async
message handler (Stage 5), but for now you control it manually.

---

## Step 9 — Observe the Trade-offs

### Problem 5 solved: Read performance is now independent

Add a new column to the write schema — say, `reorder_threshold`. It does not appear
in either read view table. Queries are completely unaffected. Add an index to the
read DB optimized for name searches — it does not touch the write DB at all. The two
sides can now evolve independently.

### New trade-off 1: Eventual consistency

Comment out the `prj.project(...)` call after `UpdateStock`. Then run a query. The
read model returns the old stock value. The write DB has the correct value. This gap
— however brief — is the definition of eventual consistency.

Ask yourself: for your domain, is this acceptable? For stock counts on a product
listing page, probably yes. For a bank balance, no. CQRS is not always the right tool.

### New trade-off 2: Projection complexity

When a supplier name changes, you must update every product row in the read DB that
references that supplier. Add a `_on_supplier_name_changed` method that does:
```sql
UPDATE product_detail_view SET supplier_name = ? WHERE supplier_name = ?
UPDATE product_list_view SET supplier_name = ? WHERE supplier_name = ?
```
This is the cost of denormalization: writes fan out. In Stage 2, changing a supplier
name touched one row. Now it touches N rows in the read DB.

### New trade-off 3: Two databases to keep in sync

What happens if the projection fails halfway? The write DB is updated but the read DB
is stale. You need a strategy: retry the projection, rebuild the read DB from scratch,
or accept the staleness. These questions have answers — but they are real operational
concerns that Stage 2 did not have.

---

## What You Built

A fully separated CQRS system: a normalized write database for integrity, a
denormalized read database for performance, and a Projector that bridges them.

The read path is now completely isolated. The query handler does not know the write
DB exists. The write path is protected — no read query can cause a write lock
contention on the products table.

**Move to Stage 4 when:** you can deliberately make the read model stale (by skipping
a projection), observe the inconsistency, and explain what would need to happen in
a real system to recover from it. That thinking is the prerequisite for Event Sourcing.
