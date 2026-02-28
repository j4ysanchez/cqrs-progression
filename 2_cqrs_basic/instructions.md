# Stage 2: Basic CQRS — Split the Interface, Keep the Database

## Goal

Apply the Command Query Responsibility Segregation pattern to the same inventory
domain from Stage 1 — without changing the database at all.

The key insight of this stage: **CQRS is first and foremost a design boundary, not
an infrastructure change.** You do not need two databases, a message bus, or event
sourcing to get most of the benefit. Separating commands from queries in code is
enough to eliminate four of the five problems you identified in Stage 1.

By the end you will have: explicit command objects that express intent, typed read
models (DTOs) that expose only what each caller needs, and two focused handlers that
keep write logic and read logic from ever touching each other.

---

## What Changes vs Stage 1

| Concern | Stage 1 | Stage 2 |
|---|---|---|
| Write operations | Methods on a repository | Named command objects → command handler |
| Read operations | Same repository methods | Named query objects → query handler |
| Return types | Raw `Product` or `dict` | Typed DTO per use case |
| Tracking views | Hidden write inside a read | Explicit `RecordProductView` command |
| Business intent | Implicit (method call) | Explicit (command object with a name) |

The database schema does not change. Same table, same columns.

---

## File Structure

```
2_cqrs_basic/
  database.py      ← identical to Stage 1, copy it
  commands.py      ← write side: command dataclasses
  queries.py       ← read side: query dataclasses + result DTOs
  handlers.py      ← CommandHandler and QueryHandler
  main.py
  instructions.md  ← this file
```

---

## Step 1 — database.py

Copy `1_crud/database.py` exactly. No changes needed.

**Why:** The point of this stage is to prove that the CQRS boundary is a code
boundary, not an infrastructure boundary. The same database serves both sides.

---

## Step 2 — commands.py

**What:** Dataclasses that represent *intent to change state*. Each command captures
exactly the data needed for one operation — nothing more, nothing less.

**How:**

Define these five command dataclasses:

```python
@dataclass
class CreateProduct:
    name: str
    price: float
    cost_price: float
    supplier_id: int
    stock: int
    description: str | None = None

@dataclass
class UpdateStock:
    product_id: int
    new_stock: int

@dataclass
class ChangePrice:
    product_id: int
    new_price: float

@dataclass
class RecordProductView:
    product_id: int
```

**Why this shape matters:**

Each command contains *only* what is needed for that operation. Compare this to
Stage 1 where `update_stock(product_id, new_stock)` was a method call with no
persistent record of the intent:

- `UpdateStock(product_id=7, new_stock=50)` is a value. You can log it, validate it,
  queue it, serialize it, and inspect it. A method call disappears the moment it runs.

- `RecordProductView` now exists as an explicit command. In Stage 1, view tracking
  was a silent write buried inside `get_by_id()`. Now it is a deliberate action the
  caller must choose to take. The read path is finally pure.

- `CreateProduct` contains `cost_price` and `supplier_id` because creation needs
  them. No other command does. Each command carries exactly its own data.

**Naming convention:** Commands are named in the imperative: `CreateProduct`,
`UpdateStock`, `ChangePrice`. They describe *what the caller wants to happen*,
not *what the system does internally*.

---

## Step 3 — queries.py

**What:** Two things in one file — query objects (what you ask for) and result DTOs
(what you get back). The DTOs are the most important part of this stage.

**How:**

First define the result DTOs — plain dataclasses with only the fields each use case
needs:

```python
@dataclass
class ProductCardDTO:
    """Public-facing summary. Safe to expose to any user."""
    id: int
    name: str
    price: float
    in_stock: bool

@dataclass
class ProductDetailDTO:
    """Admin view. All operational fields, still NO cost_price or supplier_id."""
    id: int
    name: str
    description: str | None
    price: float
    stock: int
    view_count: int
    created_at: str
    updated_at: str

@dataclass
class ProductSummaryDTO:
    """Used in lists and search results."""
    id: int
    name: str
    price: float
    stock: int
```

Then define the query objects:

```python
@dataclass
class GetProductCard:
    product_id: int

@dataclass
class GetProductDetail:
    product_id: int

@dataclass
class ListProducts:
    pass   # no parameters needed

@dataclass
class SearchProducts:
    query: str
```

**Why DTOs are the core of this stage:**

In Stage 1, `get_by_id()` returned a `Product` with `cost_price` and `supplier_id`
in it. The caller had to know to ignore those fields. There was no enforcement.

Now look at `ProductCardDTO` — it is physically impossible to leak `cost_price`
because the field does not exist on the type. The type system enforces the boundary.
No documentation required. No runtime checks. The wrong data simply cannot be
returned.

Notice also that `ProductDetailDTO` (the admin view) also omits `cost_price` and
`supplier_id`. Those are write-side concerns that live in `CreateProduct`. The read
side never needs to expose them — even to admins, who have a separate UI for
supplier management.

**Why separate query objects:**

`GetProductCard` and `GetProductDetail` both take a `product_id`. Why not just one
`GetProduct(product_id, mode="card"|"detail")`? Because a query object describes
intent, and "get a card" and "get a detail view" are different intents that may
diverge in the future (different caching rules, different data sources, different
access control). Keeping them separate preserves that flexibility at zero cost now.

---

## Step 4 — handlers.py

**What:** Two classes — `CommandHandler` and `QueryHandler` — each responsible for
one side of the system.

**How:**

### CommandHandler

```python
class CommandHandler:
    def handle(self, command):
        match command:
            case CreateProduct():   return self._create_product(command)
            case UpdateStock():     return self._update_stock(command)
            case ChangePrice():     return self._change_price(command)
            case RecordProductView(): return self._record_view(command)
            case _: raise ValueError(f"Unknown command: {type(command)}")
```

Implement each private method:

**`_create_product(cmd: CreateProduct)`**
1. Get a connection
2. INSERT into products with all fields from the command
3. Set `created_at` and `updated_at` to `datetime.utcnow().isoformat()`
4. Commit and return the new product's id

Note: return only the id, not a full object. Commands succeed or raise — they
do not return read models. If the caller needs to display the product after creating
it, they issue a query.

**`_update_stock(cmd: UpdateStock)`**
1. Validate: `new_stock >= 0`, raise `ValueError` if not
2. UPDATE products SET stock, updated_at WHERE id
3. Commit

**`_change_price(cmd: ChangePrice)`**
1. Validate: `new_price > 0`, raise `ValueError` if not
2. UPDATE products SET price, updated_at WHERE id
3. Commit

**`_record_view(cmd: RecordProductView)`**
1. UPDATE products SET view_count = view_count + 1 WHERE id
2. Commit

**Why validation lives in the command handler:**

Business rules (stock can't be negative, price must be positive) live here — on the
write side — because only writes change state. There is no point validating a read.
This is the Single Responsibility Principle applied at the architectural level.

---

### QueryHandler

```python
class QueryHandler:
    def handle(self, query):
        match query:
            case GetProductCard():    return self._get_card(query)
            case GetProductDetail():  return self._get_detail(query)
            case ListProducts():      return self._list(query)
            case SearchProducts():    return self._search(query)
            case _: raise ValueError(f"Unknown query: {type(query)}")
```

Implement each private method:

**`_get_card(q: GetProductCard) -> ProductCardDTO | None`**
1. SELECT id, name, price, stock FROM products WHERE id = ?
2. Only select the columns you need — not `SELECT *`
3. Return `ProductCardDTO(id=..., name=..., price=..., in_stock=row["stock"] > 0)`
   or `None` if not found

**Why only selected columns:** The query handler asks the database for exactly what
it needs. In Stage 1, every query ran `SELECT *` and discarded most columns.
Here, the query is as narrow as the DTO.

**`_get_detail(q: GetProductDetail) -> ProductDetailDTO | None`**
1. SELECT id, name, description, price, stock, view_count, created_at, updated_at
   FROM products WHERE id = ?
2. Notice: `cost_price` and `supplier_id` are deliberately not selected
3. Return `ProductDetailDTO(...)` or `None`

**`_list(q: ListProducts) -> list[ProductSummaryDTO]`**
1. SELECT id, name, price, stock FROM products
2. Return a list of `ProductSummaryDTO`

**`_search(q: SearchProducts) -> list[ProductSummaryDTO]`**
1. SELECT id, name, price, stock FROM products WHERE name LIKE ?
2. Return a list of `ProductSummaryDTO`

**Key property of the query handler:** It contains zero writes. No commits, no
updates. It is a pure projection from the database to DTOs. You could point it at
a read replica safely.

---

## Step 5 — main.py

**What:** Run the same scenario as Stage 1, but using commands and queries.

**How:**

```python
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
    print(qry.handle(GetProductCard(widget_id)))

    # View tracking is now explicit — the caller decides when to record a view
    cmd.handle(RecordProductView(widget_id))

    # Get full detail — still no cost_price, even in the admin view
    print(qry.handle(GetProductDetail(widget_id)))

    # Update operations
    cmd.handle(UpdateStock(gadget_id, new_stock=50))
    cmd.handle(ChangePrice(gadget_id, new_price=44.99))

    # Search and list
    print(qry.handle(SearchProducts("gadget")))
    print(qry.handle(ListProducts()))
```

Run it with: `python 2_cqrs_basic/main.py`

---

## Step 6 — Compare to Stage 1

Go back to `1_crud/main.py` and read it alongside `2_cqrs_basic/main.py`. For each
problem from Stage 1, verify it is solved here:

### Problem 1 solved: No leaking internal data
`ProductCardDTO` and `ProductDetailDTO` do not have `cost_price` or `supplier_id`.
It is not a convention you must remember — those fields literally do not exist on
the return type.

### Problem 2 solved: Reads no longer write
`QueryHandler._get_card()` contains no SQL writes. View tracking is now
`RecordProductView` — an explicit command the caller issues separately.
The read path is pure. You could cache it, replicate it, or skip it safely.

### Problem 3 solved: Each caller gets exactly what they need
`GetProductCard` → `ProductCardDTO` (4 fields)
`GetProductDetail` → `ProductDetailDTO` (8 fields, no internal data)
`ListProducts` → `list[ProductSummaryDTO]` (4 fields, flat)
Each use case has its own shape.

### Problem 4 solved: Intent is now explicit and durable
`UpdateStock(product_id=7, new_stock=50)` is a value. You can log it before handling
it. You can serialize it. You can see in your logs *exactly* what was requested and
when, without adding audit columns to your database.

### Problem 5: Still not solved
The database is the same. If you add a write-only column, it appears in `SELECT *`
queries (though you are no longer using `SELECT *`). Read and write performance still
share the same table, indexes, and connection pool. This is the problem Stage 3 solves
by introducing a separate read model.

---

## What You Built

A CQRS system over a single database. The pattern is now enforced in code:
- You cannot accidentally return `cost_price` in a card view
- You cannot accidentally write inside a query
- Every state change has a named, inspectable object representing it
- Business rules are enforced in one place: the command handler

**Move to Stage 3 when:** you can answer — "where would I add a new business rule
for price changes?" and "where would I add a new field to the product card?" without
hesitation, and the answers are different files.
