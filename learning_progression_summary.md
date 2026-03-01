# CQRS Progression: Stage-by-Stage Summary

---

## Stage 1 → Stage 2: Basic CQRS (Code Boundary Only)

**The core shift:** One `ProductRepository` with mixed read/write methods → explicit `CommandHandler` and `QueryHandler` with typed DTOs.

**What changed:**
- Write operations became named command objects (`CreateProduct`, `UpdateStock`) — values that can be logged, serialized, and queued
- Read operations returned typed DTOs (`ProductCardDTO`, `ProductDetailDTO`) instead of raw `Product` or `dict`
- View tracking moved from a hidden side-effect inside `get_by_id()` to an explicit `RecordProductView` command

**Problems solved:**
| Problem | How |
|---|---|
| Leaking `cost_price`/`supplier_id` | DTOs physically don't have those fields — the type system enforces the boundary |
| Reads that secretly write | `QueryHandler` contains zero SQL writes; view tracking is a separate command |
| One model for all use cases | Each use case gets its own DTO shape |
| No record of intent | `UpdateStock(product_id=7, new_stock=50)` is a durable, inspectable value |

**Trade-off introduced:** More code. Commands, queries, and DTOs all need to be defined separately.

**Problem NOT solved:** Read and write performance share the same table, indexes, and schema. Adding a write-only column pollutes read queries.

### Key Learning Moments

> **CQRS is a code boundary, not an infrastructure change.**
>
> The single most important insight of Stage 2: you don't need two databases, a message
> bus, or event sourcing to get most of the benefit. The same SQLite file serves both
> sides. What changes is the *design boundary in code* — one handler for reads, one
> for writes, and never the twain shall meet. This is learnable and applicable immediately
> in any codebase.

> **A DTO enforces a boundary the type system can see.**
>
> In Stage 1, `get_by_id()` returned a `Product` containing `cost_price`. The solution
> was documentation: "remember not to expose this field." That convention breaks under
> pressure. `ProductCardDTO` doesn't have a `cost_price` field — it is structurally
> impossible to return it. This is the difference between a convention and a constraint.
> The compiler (or in Python, the reader of the class definition) is your safety net.

> **Commands are values, not method calls.**
>
> `update_stock(product_id, new_stock)` disappears the moment it executes — there is no
> record it ever happened. `UpdateStock(product_id=7, new_stock=50)` is a value. You
> can log it before handling it, serialize it to a queue, inspect it in a debugger, and
> reason about it independently of the system that processes it. This shift from "call a
> method" to "create an object that represents intent" unlocks every capability that comes
> in later stages.

> **A read that secretly writes is a hidden architectural lie.**
>
> Stage 1's `get_by_id()` incremented `view_count` inside a read operation. This seems
> harmless until you try to: add a read replica (the replica is read-only, so the write
> fails), cache the result (the cache returns stale view counts), or run the query in a
> read-only transaction (it errors). By making `RecordProductView` an explicit command,
> the read path becomes pure — it has zero side effects. You can cache it, replicate it,
> or skip it without consequence.

---

## Stage 2 → Stage 3: Separate Read Models

**The core shift:** One shared database → two databases (`write.db` + `read.db`), bridged by a **Projector**.

**What changed:**
- Write DB is now normalized (`products` + `suppliers` with a real FK)
- Read DB is denormalized flat views (`product_detail_view`, `product_list_view`) with `supplier_name` pre-joined
- A new `Projector` component runs after every command: reads from write DB (with JOIN), upserts into read DB
- The JOIN happens once at write time, never at read time

**Problems solved:**
| Problem | How |
|---|---|
| Read performance coupled to write schema | Two independent schemas — add a write column, reads don't see it |
| Repeated JOIN cost | Projector resolves joins once; queries are flat SELECTs |
| `supplier_name` unavailable in UI | Pre-joined into read views at projection time |

**Trade-offs introduced:**
- **Eventual consistency** — between `prj.project()` call and the write, the read model is stale
- **Projection complexity** — if a supplier name changes, every product row in the read DB must be updated (write fan-out)
- **Two databases to keep in sync** — a crashed projection leaves write DB correct but read DB stale; you need a recovery strategy

### Key Learning Moments

> **The Projector pays the JOIN cost once so every read pays nothing.**
>
> In Stage 2, to show `supplier_name` on a product detail page, you would run a JOIN
> every time a user loads that page. Under load, that JOIN runs thousands of times per
> second. In Stage 3, the Projector runs that JOIN exactly once — when the product is
> created or the supplier name changes — and stores the result flat in the read table.
> Every subsequent read is a simple `SELECT` with no join. The work is done at write
> time, not read time. This is the core idea behind materialized views, Redis caches,
> and every denormalized read model in production systems.

> **Denormalization is a deliberate choice, not a mistake.**
>
> Database courses teach you to normalize data — one fact, one place. That's correct
> for write integrity. But `supplier_name` appears in both `product_detail_view` and
> `product_list_view`. It's duplicated intentionally. The trade-off is explicit: reads
> are instant because the data is pre-shaped for the UI; writes fan out because any
> change to a supplier name must update every product row that references it. This is
> not sloppy design — it is a conscious trade between read performance and write complexity.

> **Comment out `prj.project()` to feel eventual consistency.**
>
> The instructions ask you to deliberately skip a projection call and then query. The
> read model returns stale data. This isn't a bug — it is the system behaving correctly
> under its own rules. The gap between "write committed" and "read model updated" is
> the definition of eventual consistency. Experiencing this gap concretely, rather than
> reading about it abstractly, is what makes the Stage 3 trade-off real.

> **Recovery from projection failure is an operational concern you didn't have before.**
>
> In Stage 2, if something fails, you roll back the transaction. In Stage 3, the write
> DB commits successfully — then the Projector crashes. The write DB is correct; the
> read DB is stale. Rolling back the write DB would be wrong. You now need a recovery
> strategy: retry the projection, rebuild the read DB from scratch, or track which
> commands have been projected. This operational complexity is the real cost of two
> databases, and Stage 4's event log is the answer to it.

---

## Stage 3 → Stage 4: Event Sourcing

**The core shift:** Mutable write DB (`UPDATE products SET stock=50`) → append-only event log (`StockUpdated` record). Current state is derived by replaying events.

**What changed:**
- Write storage is now `event_store.db` with an `events` table — no UPDATE or DELETE ever runs
- A new `Product` **Aggregate** rebuilds current state in memory by replaying its events
- Command handler pattern changes: **load → validate → append** (was: load → validate → UPDATE)
- Projector now consumes **events** directly — no JOIN against write DB needed, because the event carries everything
- `ProductCreated` embeds `supplier_name` so events are self-contained and replayable forever

**Problems solved:**
| Problem | How |
|---|---|
| No audit trail | The event log *is* the audit trail — every change is permanent with a timestamp |
| Read model can go stale permanently | `rebuild_all()` wipes and replays the entire event log — read model is always recoverable |
| Projector needed write DB JOIN | Events are self-contained; Projector is a pure function of events |
| "What did product look like last Tuesday?" | Replay events only up to that timestamp |

**Read side:** Completely unchanged from Stage 3 — demonstrating that event sourcing is a write-side concern.

**Trade-offs introduced:**
- **Replay cost** — after 10,000 `StockUpdated` events, loading the aggregate replays all 10,000. Mitigated in production by snapshots (serialize state periodically, replay only events after the snapshot)
- **Schema evolution is hard** — old events use old field names forever. You can't `ALTER TABLE` the event log. Deserialization must handle both old and new formats simultaneously
- **Slightly more expensive reads on write side** — `_update_stock` now replays events to get current state instead of running a SELECT

### Key Learning Moments

> **Commands and events are not the same thing — tense matters.**
>
> A command (`UpdateStock`) is a request: it can be rejected. An event (`StockUpdated`)
> is a fact: it already happened and cannot be undone. This distinction sounds
> philosophical until you try to build with it. Commands live in the present — "please
> do this." Events live in the past — "this occurred." The command handler is the
> decision point: it accepts or rejects commands, and when it accepts one, it records
> the corresponding event. Events are immutable by definition (`frozen=True`). You
> cannot modify the past.

> **Events must be self-contained — forever.**
>
> `ProductCreated` stores `supplier_name` directly in the event, even though the write
> model has a normalized `suppliers` table with a foreign key. This feels like
> denormalization, and it is — but it's non-negotiable. If you store only `supplier_id`
> in the event and later delete that supplier, replaying the event six months from now
> produces wrong data because the lookup fails. The event log must be a complete,
> independent historical record. Every fact the Projector needs must be embedded in the
> event at creation time, not looked up at replay time.

> **The Aggregate is a pure in-memory state machine — it has no side effects.**
>
> `Product.load(events)` takes a list of events and returns current state. It does not
> talk to a database, it does not validate commands, it does not produce read models.
> It is a pure function: given the same events, it always produces the same state. This
> purity is what makes the aggregate testable in isolation and correct under replay.
> The pattern — apply each event in order, update internal state — is called event
> application, and it replaces `SELECT * FROM products WHERE id = ?` as the way to
> ask "what does this product look like right now?"

> **`rebuild_all()` makes the read model disposable.**
>
> In Stage 3, if the Projector had a bug, you had a problem: the read DB was corrupt
> and you had no reliable way to reconstruct it. In Stage 4, the event log is the source
> of truth. Fix the Projector bug, call `rebuild_all()`, and the read DB is rebuilt
> correctly from scratch. This is the deepest practical payoff of event sourcing: the
> read model is not precious data — it is a derived artifact that can always be
> regenerated from the permanent event history. This makes schema migrations, bug fixes,
> and new read model types all tractable.

> **The audit trail is not an extra feature — it is the architecture.**
>
> In Stage 1, to answer "who changed the price and when?", you would need to add an
> `audit_log` table and remember to insert into it on every price change. In Stage 4,
> you query the event log: `SELECT * FROM events WHERE event_type = 'PriceChanged'`.
> The audit trail costs nothing extra because the event log is already how the system
> stores all state changes. Auditability is a consequence of the architecture, not a
> feature bolted on afterwards.

---

## Stage 4 → Stage 5: Async Message Bus

**The core shift:** Explicit `prj.project(event)` call after every command → command handler publishes to a bus and returns immediately; subscribers react independently on a background thread.

**What changed:**
- A `MessageBus` wraps a `queue.Queue` and a background `threading.Thread`
- Command handler fires `bus.publish(event)` after appending — "fire and forget"
- Fan-out: one `StockUpdated` event now triggers `ProjectorHandler`, `AuditLogHandler`, and `LowStockAlertHandler` independently
- Adding a new reaction requires zero changes to the command handler — just `bus.subscribe(EventType, handler)`

**Problems solved:**
| Problem | How |
|---|---|
| Projector tightly coupled to write side | Command handler publishes; subscribers are fully decoupled |
| Adding new reactions requires touching command handler | New subscriber class + two lines in `main.py` — that's it |
| Sequential, blocking projection | Background thread; command handler returns before projection completes |

**Trade-offs introduced:**
- **True eventual consistency** — the read model can be arbitrarily behind the write model; `flush()` exists only for demos/tests
- **The atomicity gap** — if the process crashes between `store.append(event)` and `bus.publish(event)`, the event is durable but was never published. Production solution: the **Outbox Pattern**
- **Observability complexity** — a single request touches command handler, event store, bus, background thread, and read DB. Requires correlation IDs to trace
- **Idempotency requirement** — at-least-once delivery means handlers may run the same event twice; they must produce the same result both times (`INSERT OR REPLACE` handles this here)
- **Ordering** — events for two different products can interleave on the bus

### Key Learning Moments

> **Publisher ignorance is the goal.**
>
> In Stage 4, `main.py` called `prj.project(event)` explicitly after every command —
> the caller wired the write side to the read side by hand. The command handler itself
> was clean, but the *application flow* was not: every caller had to know to trigger
> the projection. In Stage 5, the command handler calls `bus.publish(event)` and returns.
> It does not know the Projector exists. It does not know the AuditLogHandler exists.
> It does not know anyone is listening. Adding a fifth subscriber requires zero changes
> to the command handler — this is the Open/Closed Principle applied at the architectural
> level: open for extension (new subscribers), closed for modification (command handler
> untouched).

> **Fan-out: one event, many independent reactions.**
>
> When `UpdateStock` runs, a single `StockUpdated` event is published. Three handlers
> fire independently: the Projector updates the read DB, the AuditLogHandler logs the
> change, and the LowStockAlertHandler checks the threshold and prints an alert. None
> of these handlers know about each other. The command handler knows about none of them.
> In Stage 1, adding alert logic meant editing `update_stock()` — coupling business
> policy to the write operation permanently. Now each reaction is a self-contained class.
> This is the pattern behind every webhook system, every event-driven pipeline, and every
> real-time analytics system you have ever used.

> **`flush()` is a test tool, not a production pattern.**
>
> `bus.flush()` blocks until every queued event has been processed. It exists so `main.py`
> can demonstrate consistent results. In production you never call it — you design the
> system to handle staleness gracefully. A UI shows a spinner. A response says "your
> change is processing." A downstream consumer retries. The lesson is that eventual
> consistency is not a problem to solve with `sleep()` or `flush()` — it is a property
> to design around. `flush()` makes the gap visible precisely so you understand you
> cannot rely on it.

> **The atomicity gap is the gap between toy systems and production systems.**
>
> Between `store.append(event)` and `bus.publish(event)`, there are two lines of code.
> If the process crashes between them, the event is durably stored in the event log but
> was never published. The read model will be permanently stale until someone notices.
> The production solution is the **Outbox Pattern**: write the event to the event store
> AND a `pending_events` table in the same database transaction, then have a background
> process poll `pending_events` and publish to the bus, deleting each row after success.
> This makes "write to store + publish" effectively atomic. The event store already
> gives you the data to recover — the question is whether you have the tooling to
> detect and replay the gap. That gap is what separates this stage from Kafka.

> **Idempotency is not optional once you have at-least-once delivery.**
>
> A real message bus delivers each event *at least once* — meaning it may deliver the
> same event twice on retry. If your handler is not idempotent, a duplicate delivery
> corrupts state. `INSERT OR REPLACE` in SQLite makes the Projector idempotent:
> projecting the same `StockUpdated` event twice produces the same read row both times.
> For any handler you write in a real system, the first question is always: "what
> happens if this runs twice?" If the answer is "bad things," the handler is broken
> before it ships.

---

## Full Progression Table

| Stage | Storage Model | Consistency | New Concept | Key Trade-off |
|---|---|---|---|---|
| **1 CRUD** | One mutable table | Immediate | — | One model leaks internals; reads can write; no audit |
| **2 Basic CQRS** | One mutable table | Immediate | Commands + DTOs | More code; read/write schema still coupled |
| **3 Read Models** | Two DBs (normalized write, denormalized read) | Eventual | Projector | Write fan-out; two DBs to keep in sync |
| **4 Event Sourcing** | Append-only event log + read DB | Eventual | Aggregate + Events | Replay cost; schema evolution locked |
| **5 Async Bus** | Append-only event log + read DB | Truly eventual | Message Bus | Atomicity gap; idempotency; observability |

---

## Which Stage Does Your System Actually Need?

The honest answer: **most systems need Stage 2**. Each step up adds operational weight that only pays off at scale or with specific requirements:

- **Stage 2** if you need clean boundaries and testability
- **Stage 3** if read and write performance must scale independently, or you need a denormalized view (e.g., `supplier_name` without JOIN)
- **Stage 4** if you need a permanent audit trail, time-travel queries, or the ability to rebuild read models from scratch after bugs
- **Stage 5** if you need multiple independent reactions to the same event, or the projection latency is acceptable to callers and you want true write-side decoupling
