from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Product:
    name: str
    price: float
    cost_price: float
    supplier_id: int
    stock: int
    description: Optional[str] = None
    id: Optional[int] = None
    view_count: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
