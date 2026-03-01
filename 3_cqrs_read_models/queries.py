from dataclasses import dataclass


# --- Result DTOs ---

@dataclass
class ProductCardDTO:
    """Public-facing summary. Safe to expose to any user."""
    id: int
    name: str
    price: float
    in_stock: bool


@dataclass
class ProductDetailDTO:
    """Admin view. All operational fields — supplier_name pre-joined from read model."""
    id: int
    name: str
    description: str | None
    price: float
    stock: int
    view_count: int
    supplier_name: str
    created_at: str
    updated_at: str


@dataclass
class ProductSummaryDTO:
    """Used in lists and search results."""
    id: int
    name: str
    price: float
    stock: int
    supplier_name: str


# --- Query objects ---

@dataclass
class GetProductCard:
    product_id: int


@dataclass
class GetProductDetail:
    product_id: int


@dataclass
class ListProducts:
    pass


@dataclass
class SearchProducts:
    query: str
