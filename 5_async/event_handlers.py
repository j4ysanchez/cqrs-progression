from events import ProductCreated, StockUpdated, PriceChanged, ProductViewed
from projector import Projector


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


class AuditLogHandler:
    def on_event(self, event) -> None:
        print(f"  [AUDIT] {event.occurred_at} | {type(event).__name__} | "
              f"product_id={event.product_id}")


class LowStockAlertHandler:
    THRESHOLD = 10

    def on_stock_updated(self, event: StockUpdated) -> None:
        if event.new_stock < self.THRESHOLD:
            print(f"  [ALERT] Low stock on product {event.product_id}: "
                  f"{event.new_stock} units remaining")
