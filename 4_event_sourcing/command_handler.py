from datetime import datetime, timezone

from aggregate import Product
from commands import CreateProduct, UpdateStock, ChangePrice, RecordProductView
from event_store import EventStore
from events import ProductCreated, StockUpdated, PriceChanged, ProductViewed


class CommandHandler:
    def __init__(self, event_store: EventStore):
        self.store = event_store

    def handle(self, command):
        match command:
            case CreateProduct():     return self._create_product(command)
            case UpdateStock():       return self._update_stock(command)
            case ChangePrice():       return self._change_price(command)
            case RecordProductView(): return self._record_view(command)
            case _: raise ValueError(f"Unknown command: {type(command)}")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _create_product(self, cmd: CreateProduct) -> int:
        product_id = self.store.new_product_id()
        event = ProductCreated(
            product_id=product_id,
            name=cmd.name,
            description=cmd.description,
            price=cmd.price,
            cost_price=cmd.cost_price,
            supplier_id=cmd.supplier_id,
            supplier_name=cmd.supplier_name,
            stock=cmd.stock,
            occurred_at=self._now(),
        )
        self.store.append(event)
        return product_id

    def _update_stock(self, cmd: UpdateStock) -> None:
        events = self.store.load(cmd.product_id)
        if not events:
            raise ValueError(f"Product {cmd.product_id} not found")
        Product.load(events)

        if cmd.new_stock < 0:
            raise ValueError("Stock cannot be negative")

        self.store.append(StockUpdated(
            product_id=cmd.product_id,
            new_stock=cmd.new_stock,
            occurred_at=self._now(),
        ))

    def _change_price(self, cmd: ChangePrice) -> None:
        events = self.store.load(cmd.product_id)
        if not events:
            raise ValueError(f"Product {cmd.product_id} not found")
        Product.load(events)

        if cmd.new_price <= 0:
            raise ValueError("Price must be positive")

        self.store.append(PriceChanged(
            product_id=cmd.product_id,
            new_price=cmd.new_price,
            occurred_at=self._now(),
        ))

    def _record_view(self, cmd: RecordProductView) -> None:
        self.store.append(ProductViewed(
            product_id=cmd.product_id,
            occurred_at=self._now(),
        ))
