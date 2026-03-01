# Data Model Changes Across CQRS Stages

This document explores how each stage of the CQRS progression handles three categories
of data model change:

- **A** — Adding a field to an existing product (e.g., `weight_kg`)
- **B** — Adding a new entity type alongside products (e.g., services)
- **C** — Subtyping products (e.g., physical vs. digital products with different fields)

---

## Stage 1 (CRUD)

**Scenario A — New field:**
`ALTER TABLE` + update the `Product` dataclass + update every method that touches the
table. Because `SELECT *` is everywhere and `Product` is used everywhere, the blast
radius is the entire codebase. Nothing tells you what you missed.

**Scenario B — New entity type:**
Add a `Service` dataclass and a `ServiceRepository`. Both repositories read and write
the same kind of mixed model. Immediately, `list_all()` becomes ambiguous — do you list
products, services, or both? You either duplicate logic or add conditional branching
into the repository.

**Scenario C — Product subtypes:**
Two options, both painful. Option 1: add a `product_type` discriminator column and
litter the `Product` class with `Optional` fields that only apply to one subtype.
Option 2: create `PhysicalProduct` and `DigitalProduct` classes that share no parent
type — now every caller has to handle both separately with no common interface.

**The core problem:** One model serves everything, so every change touches everything.

---

## Stage 2 (Basic CQRS)

**Scenario A — New field:**
The blast radius shrinks to only the things that actually care about `weight_kg`:
- Add it to `CreateProduct` command (the only write that sets it)
- Add it to `ProductDetailDTO` if admins need to see it (don't add it to `ProductCardDTO` — it's irrelevant there)
- Update `CommandHandler._create_product` and `QueryHandler._get_detail`

`ProductCardDTO`, `ProductSummaryDTO`, `UpdateStock`, `ChangePrice` are all untouched —
they never knew about `weight_kg` and still don't. This is the first time a schema
change has a contained blast radius.

**Scenario B — New entity type:**
Add `CreateService`, `UpdateServiceRate` commands and `ServiceDetailDTO`,
`ServiceSummaryDTO` DTOs. Route them in the handlers. The clean separation means product
logic and service logic never accidentally intermix — they're different command/query
namespaces. You can even have separate `ServiceCommandHandler` and `ServiceQueryHandler`
if they diverge.

**Scenario C — Product subtypes:**
Each subtype gets its own command: `CreatePhysicalProduct` (includes `weight_kg`,
`dimensions`) and `CreateDigitalProduct` (includes `download_url`, `license_type`).
The command handler routes them. DTOs can diverge per subtype —
`PhysicalProductDetailDTO` and `DigitalProductDetailDTO` — with no shared superclass
required. The type shapes the interface, not a discriminator field.

**The key insight:** Because each operation has its own named object, you only touch
the objects that are semantically affected. Unrelated operations are invisible to
the change.

---

## Stage 3 (Separate Read Models)

**Scenario A — New field:**
Now there are two places to update: the write schema and the read schema. Adding
`weight_kg`:
1. `ALTER TABLE products ADD COLUMN weight_kg REAL` in `write_db.py`
2. `ALTER TABLE product_detail_view ADD COLUMN weight_kg REAL` in `read_db.py` (if it needs to be visible)
3. Update the Projector to carry `weight_kg` through to the view table
4. Update `ProductDetailDTO`

The Projector is the coordination point. If `weight_kg` doesn't need to appear in the
UI, you update the write DB only — the read views are completely unaffected. This is
the first time a write-side schema change can be invisible to the read side.

**Scenario B — New entity type:**
Add a `services` table to `write_db.py` and a `service_list_view` to `read_db.py`. Add
projection methods to the Projector. The query handler reads from `service_list_view`
with no joins, same as products. The two entities can share or separate their view
tables depending on whether the UI needs to list them together.

**Scenario C — Product subtypes:**
The write DB can have a single `products` table with a `type` discriminator, or separate
`physical_products` and `digital_products` tables. The read DB can have separate flat
view tables per subtype (`physical_product_view`, `digital_product_view`) — each shaped
exactly for how that subtype is displayed. The Projector routes to the right view based
on the product type. Queries are still flat SELECTs with no conditional logic.

**New problem introduced:** Any schema change now requires a coordinated migration of
both databases plus the Projector. If you forget to update the Projector, the write DB
has `weight_kg` but the read view never receives it — silent staleness with no error.

---

## Stage 4 (Event Sourcing)

This is where the rules change fundamentally. The write side is no longer a mutable
table — it's a permanent log. This makes **forward changes easy and backward changes
nearly impossible**.

**Scenario A — New field:**

*Adding* `weight_kg` is safe:
- Add `weight_kg: Optional[float] = None` to `ProductCreated` (with a default for backward compatibility)
- Old events in the log don't have this field — the deserializer sets it to `None`
- Update the Projector to write `weight_kg` into the read view
- Call `rebuild_all()` — the read DB is repopulated; existing products get `weight_kg=None`, new products get the value

*Renaming* `weight_kg` to `weight_grams` is a serious problem:
- Old events use `weight_kg`. They are permanent. You cannot change them.
- Your deserializer must handle both field names forever:
  ```python
  # Must live in the codebase indefinitely
  weight = data.get("weight_grams") or data.get("weight_kg")
  ```
- This is called **upcasting** — transforming old event formats to new ones at read
  time. Production event-sourced systems build dedicated upcaster pipelines for this.

**Scenario B — New entity type:**
Services get their own event types (`ServiceCreated`, `ServiceRateChanged`), their own
aggregate (`Service`), and their own product registry rows. They share the event store
table but are distinct streams. The Projector gains new projection methods. Existing
product logic is entirely unaffected — you're adding new event types, not changing
existing ones. This is the cleanest possible extension path.

**Scenario C — Product subtypes:**
Each subtype gets its own creation event: `PhysicalProductCreated` (carries `weight_kg`,
`dimensions`) and `DigitalProductCreated` (carries `download_url`). The Aggregate's
`_apply` method handles each:
```python
case PhysicalProductCreated(): self._apply_physical_created(event)
case DigitalProductCreated():  self._apply_digital_created(event)
```
The event log naturally records which type each product is — not as a discriminator
column, but as the type of the creation event itself. Time-traveling to see what a
product looked like at any point in history works the same regardless of subtype.

**The massive read-side advantage:** You can change how data is *projected* without
touching the event log at all. Want to add a `low_stock_flag` boolean to the read view?
Update the Projector and call `rebuild_all()`. The event log is unchanged — the new
field is computed from existing `StockUpdated` events during replay. This kind of
retroactive read model enrichment is impossible in Stages 1–3 without a data migration.

---

## Stage 5 (Async Bus)

The write-side story is identical to Stage 4 — event sourcing rules apply. The bus adds
one new dimension to model changes.

**Scenario A — New field:**
Same as Stage 4 for the event store. The bus adds a deployment concern: if you deploy a
new `ProductCreated` event schema while old events are still queued on the bus, handlers
must be able to process both old and new formats simultaneously. Rolling deployments
require forward and backward compatibility for at least one version.

**Scenario B — New entity type:**
Add new event types → add new bus subscriptions. Zero changes to existing handlers.
This is the cleanest path for extension:
```python
bus.subscribe(ServiceCreated, service_projector.on_created)
bus.subscribe(ServiceCreated, audit_handler.on_event)
```
Existing `ProductCreated` subscriptions are completely unaffected.

**Scenario C — Product subtypes:**
Each subtype event type can have its own subscribers. `PhysicalProductCreated` and
`DigitalProductCreated` can share the `AuditLogHandler` (both call `on_event`) but have
separate projectors if their read views differ. The bus's type-keyed subscription map
(`dict[type, list[callable]]`) naturally handles this routing — no conditional branching
inside any handler.

---

## Summary: How Model Change Tolerance Evolves

| Change Type | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 |
|---|---|---|---|---|---|
| Add field to existing type | Touch everything | Touch only affected commands + DTOs | Touch write DB + Projector + read DB | Add with default; `rebuild_all()` updates read side | Same as 4; mind deployment ordering |
| Rename/remove field | ALTER TABLE + audit every usage | Update affected commands + DTOs only | Update both schemas + Projector | **Cannot change existing events ever** | Same as 4 |
| Add new entity type | New table + new repo, logic leaks | New commands + DTOs, fully isolated | New write table + new read view + Projector routes | New event types + new aggregate | New event types + new bus subscriptions |
| Add product subtype | Discriminator column + optional fields bloat | Separate commands + DTOs per subtype | Separate read views per subtype | Separate creation events per subtype | Separate event types + independent subscribers |
| Retroactively enrich read model | Full data migration | Full data migration | Full data migration | Update Projector + `rebuild_all()` | Same as 4 |

The pattern is clear: **additive changes get progressively cheaper** from Stage 1 to
Stage 5, because each stage reduces the blast radius of a change. But **breaking changes
get progressively more expensive** — Stage 4 makes renaming an event field a permanent
commitment, not a refactor. The discipline this imposes on event schema design is both
the cost and the point.
