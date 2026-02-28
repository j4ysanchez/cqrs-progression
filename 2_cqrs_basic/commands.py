from dataclasses import dataclass


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
