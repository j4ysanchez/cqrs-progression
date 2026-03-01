from typing import Optional

from events import ProductCreated, StockUpdated, PriceChanged, ProductViewed


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
        self._version: int = 0

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
