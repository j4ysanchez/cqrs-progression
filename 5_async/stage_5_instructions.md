# Stage 5: Async Projection — The Message Bus

## Goal

Decouple the write side from the read side completely. In Stage 4, after every
command, `main.py` explicitly called `prj.project(event)` — the write and read
updates happened in sequence, on the same thread, the caller waited for both.

In Stage 5, the command handler publishes events to a **message bus**. Subscribers
listen to the bus and react independently. The command handler does not know who
the subscribers are. It does not wait for them. It writes to the event store, fires
the event onto the bus, and returns.

This is the pattern behind Kafka, RabbitMQ, SNS/SQS, and every major event-driven
system. You will build a minimal in-process version that has the same semantics.

---

## The Central Shift in Thinking

In Stage 4 you thought in terms of **sequence**:
```
handle command → append event → project event → query
```

In Stage 5 you think in terms of **topology**:
```
handle command → append event → publish to bus
                                       ↓         ↓         ↓
                               projector   audit log   alert handler
                               (async)     (async)     (async)
```

The command handler is upstream. Handlers are downstream. Upstream does not know
downstream exists. Adding a new handler requires zero changes to the command handler.

---

## What Changes vs Stage 4

| Concern                         | Stage 4                        | Stage 5                      |
|---------------------------------|--------------------------------|------------------------------|
| Projection trigger              | Explicit call in `main.py`     | Bus subscription             |
| Command handler return          | After projection completes     | After event is published     |
| Multiple reactions to one event | Manual, sequential             | Fan-out via subscriptions    |
| Consistency model               | Synchronous (forced by caller) | Eventual (background thread) |
| New handler wiring              | Touch `main.py` + caller       | Subscribe in `main.py` only  |

The event store, aggregate, commands, events, read DB, and query handler are
**unchanged**. Copy them from Stage 4.

---

## File Structure

```
5_async/
  bus.py               ← in-process message bus (queue + background thread)
  events.py            ← copy from Stage 4
  commands.py          ← copy from Stage 4
  aggregate.py         ← copy from Stage 4
  event_store.py       ← copy from Stage 4
  command_handler.py   ← updated: publishes to bus after appending
  event_handlers.py    ← subscriber classes: projector, audit log, alert handler
  read_db.py           ← copy from Stage 4
  query_handler.py     ← copy from Stage 4
  main.py
  instructions.md      ← this file
```

---

## Step 1 — bus.py

**What:** An in-process message bus. Publishers put events on a queue. A background
thread pulls events off the queue and dispatches them to all registered subscribers.

**How:**

```python
import queue
import threading
from collections import defaultdict

class MessageBus:
    def __init__(self):
        self._queue = queue.Queue()
        # defaultdict(list) returns an empty list if a missing key is accessed
        self._subscribers: dict[type, list[callable]] = defaultdict(list)
        self._thread: threading.Thread | None = None
        self._running = False

    def subscribe(self, event_type: type, handler: callable) -> None:
        """Register a handler to be called when event_type is published."""
        self._subscribers[event_type].append(handler)

    def publish(self, event) -> None:
        """Put an event on the queue. Returns immediately."""
        self._queue.put(event)

    def start(self) -> None:
        """Start the background processing thread."""
        self._running = True
        self._thread = threading.Thread(target=self._process, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the thread to stop and wait for it to finish."""
        self._running = False
        self._queue.put(None)   # sentinel value to unblock the thread
        self._thread.join()

    def flush(self) -> None:
        """Block until all currently queued events have been processed.
        Use this in tests and demos before querying the read model."""
        self._queue.join()

    def _process(self) -> None:
        while self._running:
            event = self._queue.get(block=True)
            if event is None:
                self._queue.task_done()
                break
            for handler in self._subscribers[type(event)]:
                try:
                    handler(event)
                except Exception as e:
                    # In production: dead-letter queue, retry logic, alerting.
                    # Here: log and continue — one bad handler does not stop others.
                    print(f"[BUS ERROR] Handler {handler.__name__} failed: {e}")
            self._queue.task_done()
```

**Why `Queue` and not a simple list:** `queue.Queue` is thread-safe. The main thread
calls `publish()` (writes to the queue) while the background thread calls `_process()`
(reads from the queue). Without a thread-safe structure, you would have race conditions.

**Why `flush()`:** `Queue.join()` blocks until every item that was `put()` has been
matched with a `task_done()` call. This is not something you would do in production —
you would design your system to be eventually consistent and not wait. But in `main.py`
you need it to query reliably. It also lets you deliberately show what happens when
you *don't* call it.

**Why `daemon=True`:** If the main thread exits without calling `stop()`, daemon
threads are killed automatically. This prevents the background thread from keeping
the process alive after `main()` returns.

**The error handling policy in `_process`:** A handler that throws must not stop the
bus. The other handlers for that event still need to run, and future events still need
to be processed. Log the error and continue. In production, failed events go to a
**dead-letter queue** for inspection and replay. The event store means you can always
replay.

---

## Step 2 — event_handlers.py

**What:** Three subscriber classes, each reacting to events independently. This is
where you see fan-out: one `StockUpdated` event triggers multiple handlers.

**How:**

Import `Projector` from your Stage 4 projector code (or copy and adapt it).

### Handler 1: ProjectorHandler

Wraps the Stage 4 `Projector` and exposes individual methods per event type so they
can be registered as bus subscribers.

```python
class ProjectorHandler:
    def __init__(self):
        self._projector = Projector()

    def on_product_created(self, event: ProductCreated) -> None:
        self._projector.project(event)

    def on_stock_updated(self, event: StockUpdated) -> None:
        self._projector.project(event)

    def on_price_changed(self, event: PriceChanged) -> None:
        self._projector.project(event)

    def on_product_viewed(self, event: ProductViewed) -> None:
        self._projector.project(event)
```

### Handler 2: AuditLogHandler

A second subscriber for the same events. Demonstrates that the projector does not
need to change at all for this to work.

```python
class AuditLogHandler:
    def on_event(self, event) -> None:
        print(f"  [AUDIT] {event.occurred_at} | {type(event).__name__} | "
              f"product_id={event.product_id}")
```

Note: `on_event` is registered for each event type individually. It has the same
signature for all of them.

### Handler 3: LowStockAlertHandler

Business logic triggered by domain events — this is a **policy**: when stock drops
below a threshold, take an action. In a real system this would send an email or
create a restock task. Here it prints an alert.

```python
class LowStockAlertHandler:
    THRESHOLD = 10

    def on_stock_updated(self, event: StockUpdated) -> None:
        if event.new_stock < self.THRESHOLD:
            print(f"  [ALERT] Low stock on product {event.product_id}: "
                  f"{event.new_stock} units remaining")
```

**Why this handler matters for the architecture lesson:** In Stage 1 through 4, if
you wanted to trigger an alert when stock drops low, you would add logic inside
`_update_stock` in the command handler — coupling business policy to the write
operation. Now the command handler knows nothing about alerts. The `LowStockAlertHandler`
subscribes to `StockUpdated` independently. You can add, remove, or change alert
logic without touching the command handler.

This is the **Open/Closed Principle** applied architecturally: the command handler
is closed for modification but open for extension via new subscribers.

---

## Step 3 — command_handler.py

**What:** The same command handler from Stage 4, with one addition: after appending
each event to the event store, publish it to the bus.

**How:**

Add `bus: MessageBus` as a constructor parameter.

```python
class CommandHandler:
    def __init__(self, event_store: EventStore, bus: MessageBus):
        self.store = event_store
        self.bus = bus
```

Update each handler method to publish after appending:

```python
def _create_product(self, cmd: CreateProduct) -> int:
    product_id = self.store.new_product_id()
    event = ProductCreated(product_id=product_id, ...)
    self.store.append(event)
    self.bus.publish(event)   # ← fire and forget
    return product_id

def _update_stock(self, cmd: UpdateStock) -> None:
    events = self.store.load(cmd.product_id)
    product = Product.load(events)
    if cmd.new_stock < 0:
        raise ValueError("Stock cannot be negative")
    event = StockUpdated(product_id=cmd.product_id, new_stock=cmd.new_stock,
                         occurred_at=self._now())
    self.store.append(event)
    self.bus.publish(event)   # ← fire and forget
```

Apply the same pattern to `_change_price` and `_record_view`.

**What "fire and forget" means here:** `bus.publish(event)` puts the event on the
queue and returns immediately. The command handler does not know and does not care
whether the projector has processed the event yet. The write side's job is done.

**The atomicity problem to know about:** There is a gap between `store.append(event)`
and `bus.publish(event)`. If the process crashes between those two lines, the event
is durably stored but was never published to the bus. The read model will be stale
until you either:

1. Restart and replay unprojected events from the event store
2. Implement the **Outbox Pattern**: write the event to the event store AND a
   `pending_events` table in the same database transaction. A background process
   polls `pending_events` and publishes them to the bus, deleting each row after
   successful publish. This makes the "write to store + publish" effectively atomic.

You do not need to implement the Outbox Pattern here, but this is the gap between
a toy system and a production one. The event store already gives you the data to
recover — the question is whether you have the tooling to detect and replay gaps.

---

## Step 4 — read_db.py and query_handler.py

Copy from Stage 4 without changes.

---

## Step 5 — main.py

**What:** Wire everything together. Demonstrate fan-out, and deliberately expose the
eventual consistency gap before showing the correct flush-then-query pattern.

**How:**

```python
from bus import MessageBus
from event_store import EventStore, init_event_store
from read_db import init_read_db
from commands import CreateProduct, UpdateStock, ChangePrice, RecordProductView
from queries import GetProductDetail, ListProducts, SearchProducts
from command_handler import CommandHandler
from query_handler import QueryHandler
from event_handlers import ProjectorHandler, AuditLogHandler, LowStockAlertHandler
import time

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

    bus.subscribe(StockUpdated,   low_stock_handler.on_stock_updated)

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

    bus.flush()   # wait for all published events to be fully processed

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
```

---

## Step 6 — Observe the Full Architecture

### The eventual consistency gap is visible and controllable

Remove `bus.flush()` after creating the products and run the script. The query
returns `None` or stale data because the background thread hasn't projected yet.
Add `time.sleep(0.01)` instead of `flush()` and run again — it may or may not work
depending on thread scheduling. This non-determinism is exactly why production systems
design around eventual consistency rather than trying to time it.

`flush()` is a test/demo tool. In production, you either:
- Design the UI to show stale data gracefully (a spinner, a cache timestamp)
- Use a read-your-writes pattern (query the event store directly after a write
  for the issuing user's next request, then switch to the read model)
- Accept staleness as a feature ("prices update within 30 seconds")

### Fan-out with zero coupling

The `StockUpdated` event triggers three independent reactions:
1. `ProjectorHandler` updates the read DB
2. `AuditLogHandler` logs the event
3. `LowStockAlertHandler` fires an alert if below threshold

None of these know about each other. The command handler knows about none of them.
To add a fourth reaction — say, a `ReorderHandler` that creates a purchase order when
stock drops below 5 — you write one new class and add two lines to `main.py`:

```python
bus.subscribe(StockUpdated, reorder_handler.on_stock_updated)
```

Zero changes to `CommandHandler`, `ProjectorHandler`, `AuditLogHandler`, or
`LowStockAlertHandler`.

### The bus is an abstraction boundary

Your `MessageBus` uses `queue.Queue` and `threading.Thread`. A production message
bus uses Kafka, RabbitMQ, AWS SQS, or Google Pub/Sub. The interface is identical:

```
bus.subscribe(EventType, handler)   →  consumer group on a topic
bus.publish(event)                  →  producer.send(topic, message)
```

The semantics your code has learned — publisher ignorance, fan-out, eventual
consistency, dead-letter handling — are the same semantics those systems implement.
The only difference is that crossing a network boundary makes the consistency gap
larger and the failure modes more varied.

---

## Step 7 — The Completed Architecture

Looking back across all five stages, here is the full picture:

```
┌─────────────────────────────────────────────────────────┐
│                      WRITE SIDE                          │
│                                                          │
│   Command ──► CommandHandler ──► EventStore (durable)    │
│                                        │                 │
│                                   MessageBus             │
└─────────────────────────────────────────────────────────┘
                                         │
              ┌──────────────────────────┼──────────────────┐
              ▼                          ▼                   ▼
    ProjectorHandler            AuditLogHandler    LowStockAlertHandler
              │
              ▼
┌─────────────────────────────────────────────────────────┐
│                       READ SIDE                          │
│                                                          │
│   Read DB (denormalized views) ──► QueryHandler ──► DTO  │
└─────────────────────────────────────────────────────────┘
```

Each layer solves a problem introduced by the previous stages:

| Stage | Problem Solved | Trade-off Introduced |
|---|---|---|
| 1 → 2 | Reads and writes share one model | Commands/queries are more code |
| 2 → 3 | Read queries join the write schema | Eventual consistency, projector complexity |
| 3 → 4 | No audit trail; can't rebuild read models | Replay cost, schema evolution complexity |
| 4 → 5 | Projector is tightly coupled to commands | True eventual consistency, operational complexity |

**No trade-off column for Stage 5 is a lie.** The real trade-offs at Stage 5:

- **Observability:** A request touches the command handler, the event store, the bus,
  a background thread, and the read DB. Tracing a single operation requires
  correlation IDs across all of them.
- **Ordering:** The bus processes events in order per-product only if you enforce it.
  Two products' events can interleave. If your projector has cross-product logic,
  ordering matters.
- **Exactly-once delivery:** The bus delivers each event at least once (on retry).
  Your handlers must be **idempotent** — running the same event twice must produce
  the same result. `INSERT OR REPLACE` in SQLite handles this for you here.
- **Local vs distributed:** Crossing the network (real Kafka/RabbitMQ) adds latency,
  partition tolerance concerns, and consumer group rebalancing. Everything you built
  here scales directly to those systems — the concepts transfer completely.

---

## What You Built Across All Five Stages

Starting from a 60-line CRUD file, you have arrived at a system where:

- **Writes** are validated commands that produce immutable events stored permanently
- **Reads** are pre-computed projections of those events, optimized per use case
- **New reactions** to events (emails, alerts, analytics) require no changes to existing code
- **The read model can be rebuilt** at any time by replaying the event log
- **Every state change is auditable** — who changed what, when, and from what value
- **Scaling** is achieved by pointing the query handler at a read replica and the
  projector at a Kafka consumer — the interfaces stay the same

**The final question to sit with:** not every system needs Stage 5. A startup's
inventory system probably needs Stage 2. A financial trading platform probably needs
Stage 5. The value of having worked through all five stages is that you can identify
*which stage fits your domain* — and you know the exact cost of each step up.
