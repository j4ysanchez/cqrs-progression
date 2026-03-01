from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProductCreated:
    product_id: int
    name: str
    price: float
    cost_price: float
    supplier_id: int
    supplier_name: str
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
