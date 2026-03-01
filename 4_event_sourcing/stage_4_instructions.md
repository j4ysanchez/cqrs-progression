# Stage 4: Event Sourcing — The Event Log as Source of Truth

## Goal

Replace the mutable write database with an append-only event log. Instead of storing
*current state* ("product 7 has stock=50"), you store *what happened* ("stock for
product 7 was set to 50 at 14:32"). Current state is always derived by replaying
events.

This stage explains why CQRS and Event Sourcing are almost always discussed together:
events are the natural, lossless bridge between the write side and the read side. The
Projector from Stage 3 now consumes events directly — no join against the write DB
needed, because the event itself carries everything the Projector needs to know.

---

## The Central Shift in Thinking

In Stages 1–3, you thought in terms of **current state**:
> "What does product 7 look like right now?"
> → `SELECT * FROM products WHERE id = 7`

In Stage 4, you think in terms of **history**:
> "What has happened to product 7?"
> → `SELECT * FROM events WHERE product_id = 7 ORDER BY id`
> → replay those events → current state emerges

The write database table changes from:
```
products (id, name, price, stock, ...)   ← stores latest values, mutated in place
```
to:
```
events (id, product_id, type, data, occurred_at)  ← append-only, never updated
```

---

## What Changes vs Stage 3

| Concern               | Stage 3                               | Stage 4                                 |
|-----------------------|---------------------------------------|-----------------------------------------|
| Write storage         | Mutable rows in `write.db`            | Append-only events in `event_store.db`  |
| Getting current state | `SELECT * FROM products WHERE id = ?` | Replay all events for that product      |
| Command handler       | Runs UPDATE/INSERT SQL                | Validates via aggregate, appends events |
| Projector input       | Commands (indirect)                   | Events (direct — no join needed)        |
| Audit trail           | Requires extra audit table            | Free — the event log IS the audit trail |
| Read side             | Same as Stage 3                       | Identical — no changes                  |

The read side (`read_db.py`, `query_handler.py`, DTOs) is **completely unchanged**.
This is intentional — it demonstrates that Event Sourcing is a write-side concern.

---

## File Structure

```
4_event_sourcing/
  event_store.py      ← append-only SQLite event log
  events.py           ← event dataclasses (the language of what happened)
  aggregate.py        ← Product rebuilt by replaying its events
  commands.py         ← same as Stage 3
  command_handler.py  ← validates commands, emits events
  read_db.py          ← copy from Stage 3, unchanged
  query_handler.py    ← copy from Stage 3, unchanged
  projector.py        ← rebuilt: now consumes events, not commands
  main.py
  instructions.md     ← this file
```

---

## Step 1 — events.py

**What:** Dataclasses that represent things that *have already happened*. Events are
facts. They are named in past tense. They are immutable once stored.

**How:**

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class ProductCreated:
    product_id: int
    name: str
    price: float
    cost_price: float
    supplier_id: int
    stock: int
    occurred_at: str
    description: Optional[str] = None

@dataclass(frozen=True)
class StockUpdated:
    product_id: int
    new_stock: int
    occurred_at: str

@dataclass(frozen=True)
class PriceChanged:
    product_id: int
    new_price: float
    occurred_at: str

@dataclass(frozen=True)
class ProductViewed:
    product_id: int
    occurred_at: str
```

Use `frozen=True` on each dataclass. Events are immutable facts — they cannot be
modified after creation, just as the past cannot be changed.

**Commands vs Events — the critical distinction:**

|           | Command                        | Event                         |
|-----------|--------------------------------|-------------------------------|
| Tense     | Imperative: `UpdateStock`      | Past: `StockUpdated`          |
| Can fail? | Yes — validation may reject it | No — it already happened      |
| Contains  | Intent (what to do)            | Fact (what happened)          |
| Timing    | Future                         | Past                          |

A command says "please do this." An event says "this occurred." The command handler
is the decision point — it accepts or rejects commands, and if accepted, records
the corresponding event.

**Why events carry `cost_price` and `supplier_id` in `ProductCreated`:** The event
log must be self-contained. If you replay `ProductCreated` six months from now, the
event must have everything needed to reconstruct state — even internal fields. Events
are not DTOs. They are a permanent historical record.

---

## Step 2 — event_store.py

**What:** An append-only SQLite database and the class that manages it. This is the
only write storage in Stage 4.

**How:**

Connect to `4_event_sourcing/event_store.db`. Create two tables:

```sql
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id   INTEGER NOT NULL,
    event_type   TEXT NOT NULL,
    data         TEXT NOT NULL,
    occurred_at  TEXT NOT NULL
)
```

```sql
CREATE TABLE IF NOT EXISTS product_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT
)
```

`product_registry` exists solely to generate product IDs. Inserting a row and reading
`lastrowid` gives you a unique, sequential product ID without coupling IDs to event IDs.

Write an `EventStore` class with these methods:

**`new_product_id() -> int`**
```python
cursor.execute("INSERT INTO product_registry DEFAULT VALUES")
conn.commit()
return cursor.lastrowid
```

**`append(event) -> None`**
1. Serialize the event to JSON: `json.dumps(dataclasses.asdict(event))`
2. Insert into `events` with the event's class name as `event_type`
3. Commit

```python
conn.execute(
    "INSERT INTO events (product_id, event_type, data, occurred_at) VALUES (?, ?, ?, ?)",
    (event.product_id, type(event).__name__, json.dumps(dataclasses.asdict(event)), event.occurred_at)
)
```

**`load(product_id: int) -> list`**
1. SELECT all events WHERE product_id = ? ORDER BY id ASC
2. Deserialize each row: use `event_type` to pick the right dataclass, then
   `DataClass(**json.loads(row["data"]))` to reconstruct it
3. Return the list of event objects

```python
EVENT_TYPES = {
    "ProductCreated": ProductCreated,
    "StockUpdated":   StockUpdated,
    "PriceChanged":   PriceChanged,
    "ProductViewed":  ProductViewed,
}
```

**`load_all() -> list`**
Same as `load()` but without the `WHERE product_id` filter — returns all events
across all products in insertion order. Used by the Projector's `rebuild_all()`.

**Why serialization matters:** The event store persists events as JSON strings. This
means the event log is readable, portable, and durable across code changes. You can
open `event_store.db` in any SQLite browser and read your entire system's history in
plain text.

**The append-only constraint:** Notice that `EventStore` has no `update()` or
`delete()` method. This is not an oversight. Events are permanent. If you made an
error, you append a corrective event (`StockCorrected`, `PriceReverted`) — you
never erase history. This is non-negotiable for correctness: if you could delete
events, your replayed state would differ from reality.

---

## Step 3 — aggregate.py

**What:** A `Product` class that reconstructs current state by replaying its events.
This is called an **Aggregate** — it's the write-side model of a product, and it
exists only in memory.

**How:**

```python
from dataclasses import dataclass, field
from typing import Optional

class Product:
    def __init__(self):
        self.id: Optional[int] = None
        self.name: Optional[str] = None
        self.description: Optional[str] = None
        self.price: float = 0.0
        self.cost_price: float = 0.0
        self.supplier_id: Optional[int] = None
        self.stock: int = 0
        self.view_count: int = 0
        self._version: int = 0   # number of events applied

    @classmethod
    def load(cls, events: list) -> "Product":
        product = cls()
        for event in events:
            product._apply(event)
        return product

    def _apply(self, event) -> None:
        match event:
            case ProductCreated(): self._apply_created(event)
            case StockUpdated():   self._apply_stock_updated(event)
            case PriceChanged():   self._apply_price_changed(event)
            case ProductViewed():  self._apply_viewed(event)
            case _: raise ValueError(f"Unknown event: {type(event)}")
        self._version += 1

    def _apply_created(self, e: ProductCreated) -> None:
        self.id = e.product_id
        self.name = e.name
        self.description = e.description
        self.price = e.price
        self.cost_price = e.cost_price
        self.supplier_id = e.supplier_id
        self.stock = e.stock

    def _apply_stock_updated(self, e: StockUpdated) -> None:
        self.stock = e.new_stock

    def _apply_price_changed(self, e: PriceChanged) -> None:
        self.price = e.new_price

    def _apply_viewed(self, e: ProductViewed) -> None:
        self.view_count += 1
```

**Why `_version` matters:** It tracks how many events have been applied. In
production systems, `_version` is used for **optimistic concurrency control**: when
you save events, you assert "I loaded version N, and no events have been added since."
If another process has added events in the meantime, the save fails and you retry.
You do not need to implement this now, but understanding that `_version` exists for
this purpose is important.

**What the Aggregate does NOT do:**
- It does not talk to a database
- It does not validate commands (that is the command handler's job)
- It does not produce read models (that is the projector's job)

The Aggregate is a pure in-memory state machine. Input: a stream of events. Output:
current state. It has no side effects.

---

## Step 4 — commands.py

Copy from Stage 3. No changes. Commands describe intent; they are independent of
whether the system uses event sourcing or direct SQL.

---

## Step 5 — command_handler.py

**What:** Validates commands by consulting the current aggregate state, then appends
events to the event store. Does not write to any state table.

**How:**

```python
from datetime import datetime, timezone

class CommandHandler:
    def __init__(self, event_store: EventStore):
        self.store = event_store

    def handle(self, command):
        match command:
            case CreateProduct():     return self._create_product(command)
            case UpdateStock():       return self._update_stock(command)
            case ChangePrice():       return self._change_price(command)
            case RecordProductView(): return self._record_view(command)
```

**`_now() -> str`** — private helper:
```python
return datetime.now(timezone.utc).isoformat()
```

**`_create_product(cmd: CreateProduct) -> int`**
```python
product_id = self.store.new_product_id()
event = ProductCreated(
    product_id=product_id,
    name=cmd.name,
    description=cmd.description,
    price=cmd.price,
    cost_price=cmd.cost_price,
    supplier_id=cmd.supplier_id,
    stock=cmd.stock,
    occurred_at=self._now()
)
self.store.append(event)
return product_id
```

No aggregate is loaded for creation — there is no prior state to validate against.
The event captures everything needed to later reconstruct the product.

**`_update_stock(cmd: UpdateStock) -> None`**
```python
# Load the aggregate to validate current state
events = self.store.load(cmd.product_id)
if not events:
    raise ValueError(f"Product {cmd.product_id} not found")
product = Product.load(events)

# Business rule validation against current state
if cmd.new_stock < 0:
    raise ValueError("Stock cannot be negative")

# Append the event — no SQL UPDATE anywhere
self.store.append(StockUpdated(
    product_id=cmd.product_id,
    new_stock=cmd.new_stock,
    occurred_at=self._now()
))
```

Notice the pattern: **load → validate → append**. This replaces Stage 3's
**load → validate → UPDATE**.

**`_change_price(cmd: ChangePrice) -> None`**
```python
events = self.store.load(cmd.product_id)
if not events:
    raise ValueError(f"Product {cmd.product_id} not found")
product = Product.load(events)

if cmd.new_price <= 0:
    raise ValueError("Price must be positive")

# You could also validate against current state, e.g.:
# if cmd.new_price > product.price * 2:
#     raise ValueError("Price increase of more than 100% requires approval")

self.store.append(PriceChanged(
    product_id=cmd.product_id,
    new_price=cmd.new_price,
    occurred_at=self._now()
))
```

**`_record_view(cmd: RecordProductView) -> None`**
```python
self.store.append(ProductViewed(
    product_id=cmd.product_id,
    occurred_at=self._now()
))
```

No aggregate loading needed — recording a view has no preconditions.

**Why validation against the aggregate matters:** In Stage 3, `_change_price` ran
`SELECT price FROM products WHERE id = ?` to get the current price for validation.
In Stage 4, you load the aggregate (replay events) to get the same information.
This feels more expensive — and it is, slightly. The benefit: the aggregate applies
*all* business rules consistently, everywhere, regardless of how state was reached.
You cannot get into an inconsistent state because the aggregate enforces invariants
on every transition.

---

## Step 6 — projector.py

**What:** Rebuilt from Stage 3 to consume **events** instead of commands. This is
the key architectural improvement: the Projector no longer needs to query the write
DB at all — everything it needs is in the event itself.

**How:**

The read DB setup and `QueryHandler` are identical to Stage 3. Copy `read_db.py`
and `query_handler.py` without changes.

```python
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
```

**`_on_created(e: ProductCreated) -> None`**

The Projector needs `supplier_name` but the event only has `supplier_id`. This is
a real design decision. Two options:

**Option A:** Store `supplier_name` in the `ProductCreated` event.

```python
@dataclass(frozen=True)
class ProductCreated:
    ...
    supplier_name: str   ← denormalized into the event at creation time
```

The command handler resolves the name before emitting the event. This means the
event is self-contained — replaying it never needs to query a supplier table.

**Option B:** Keep a separate supplier lookup in the Projector.

The Projector queries a supplier table to resolve the name during projection.

**Use Option A.** Events should be self-contained. Option B creates a dependency
between projection and a separate table that may change or be unavailable. If you
add `supplier_name` to `ProductCreated`, the event log is permanently accurate even
if the supplier is later deleted. This is the correct model for event sourcing.

Update `CreateProduct`, `ProductCreated`, and `CommandHandler._create_product` to
accept and carry `supplier_name`. The command handler receives the name and embeds
it in the event.

With Option A, `_on_created` becomes straightforward:
```python
def _on_created(self, e: ProductCreated) -> None:
    conn = get_read_connection()
    conn.execute(
        "INSERT OR REPLACE INTO product_detail_view VALUES (?,?,?,?,?,?,?,?,?)",
        (e.product_id, e.name, e.description, e.price, e.stock,
         0, e.supplier_name, e.occurred_at, e.occurred_at)
    )
    conn.execute(
        "INSERT OR REPLACE INTO product_list_view VALUES (?,?,?,?,?)",
        (e.product_id, e.name, e.price, e.stock, e.supplier_name)
    )
    conn.commit()
    conn.close()
```

**`_on_stock_updated(e: StockUpdated) -> None`**
```python
conn.execute("UPDATE product_detail_view SET stock=?, updated_at=? WHERE id=?",
             (e.new_stock, e.occurred_at, e.product_id))
conn.execute("UPDATE product_list_view SET stock=? WHERE id=?",
             (e.new_stock, e.product_id))
```

**`_on_price_changed(e: PriceChanged) -> None`**
```python
conn.execute("UPDATE product_detail_view SET price=?, updated_at=? WHERE id=?",
             (e.new_price, e.occurred_at, e.product_id))
conn.execute("UPDATE product_list_view SET price=? WHERE id=?",
             (e.new_price, e.product_id))
```

**`_on_viewed(e: ProductViewed) -> None`**
```python
conn.execute("UPDATE product_detail_view SET view_count = view_count + 1 WHERE id=?",
             (e.product_id,))
```

**Compare to Stage 3:** In Stage 3, `_on_stock_updated` had to JOIN against the
write DB to get `supplier_name` so it could do a full upsert. Now each event carries
exactly what the Projector needs. The Projector is a pure function of events — it
never reads from the write side.

---

## Step 7 — main.py

**What:** Same scenario as before, but now the three-step rhythm is
`command → event → project`.

**How:**

```python
from event_store import EventStore, init_event_store
from read_db import init_read_db
from events import *
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
        supplier_id=1, supplier_name="Acme Corp", stock=100
    ))
    # Project the last emitted event into the read model
    prj.project(store.load(widget_id)[-1])

    gadget_id = cmd.handle(CreateProduct(
        name="Gadget Plus", price=49.99, cost_price=22.50,
        supplier_id=1, supplier_name="Acme Corp", stock=0
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
```

---

## Step 8 — The Payoff: Things You Get For Free

### Free Audit Trail

```python
for event in store.load(product_id):
    print(event)
```

In Stage 1 you would need an `audit_log` table and explicit inserts. In Stage 4 the
event log *is* the audit trail. Every state change is recorded permanently with a
timestamp.

### Free Time Travel

To see what a product looked like at a specific point in time, replay events only
up to that timestamp:

```python
def load_at(self, product_id: int, before: str) -> list:
    # SELECT ... WHERE product_id = ? AND occurred_at <= ? ORDER BY id
```

Then `Product.load(events_at_time)` gives you the exact state at that moment. No
`updated_at` column needed.

### Free Read Model Rebuild

`prj.rebuild_all(store)` — wipe the read DB and replay every event. This means:
- You can fix a bug in the Projector and rebuild the read model correctly
- You can add a new read model (e.g., a `low_stock_alert_view`) and populate it
  immediately by replaying history
- You can migrate to a new read schema without migrating write data

Try it: add a `view_count_summary` table to `read_db.py` and add projection logic
for `ProductViewed`. Then call `rebuild_all()` — the new table is populated
retroactively from existing events.

---

## Step 9 — Observe the Trade-offs

### Trade-off 1: Loading an aggregate replays all events

After 10,000 stock updates, loading `Product.load(events)` replays 10,000 events.
This is the primary performance concern with event sourcing. The solution is
**snapshots**: periodically serialize the aggregate's current state and store it.
On load, you start from the latest snapshot and replay only events after it. This
is not implemented here, but understanding the problem prepares you for it.

### Trade-off 2: Schema evolution is harder

In Stage 3, changing a column name means running `ALTER TABLE`. In Stage 4, old
events in the log use the old field name. Your deserialization code must handle
both the old and new field names simultaneously — forever. Events are immutable,
so you cannot migrate them. Plan your event schemas carefully.

### Trade-off 3: Querying history requires the event store

"How many times has the price changed in the last 30 days?" In Stage 3 you would
need an audit table. In Stage 4 you query the event log:
```sql
SELECT COUNT(*) FROM events
WHERE event_type = 'PriceChanged'
AND occurred_at >= date('now', '-30 days')
```
This is a benefit, not a trade-off — but it means some queries go to the event store
rather than the read DB.

---

## What You Built

A complete event-sourced CQRS system. The write side has no mutable state — only an
append-only log. The read side is a projection of that log, identical to Stage 3.
The Projector is now a pure function of events, requiring no access to the write side.

The final architecture:

```
[Command] → CommandHandler → EventStore.append(event)
                                     ↓
                              Projector.project(event)
                                     ↓
                             Read DB (view tables)
                                     ↓
                            QueryHandler → DTO
```

**Move to Stage 5 when:** you have called `rebuild_all()` at least once,
deliberately introduced a bug in the Projector, observed the wrong read data, fixed
the Projector, and rebuilt to the correct state. That cycle — break, fix, replay —
is the lived experience that justifies the complexity of event sourcing.
