"""Pydantic request/response models. Field names match the JSON the React front end uses."""

import datetime as dt
import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

# Bills show times as 'YYYY-MM-DD HH:MM:SS' (the front end splits on the space).
LocalDateTime = Annotated[
    datetime, PlainSerializer(lambda d: d.strftime("%Y-%m-%d %H:%M:%S"), return_type=str)
]

PaymentMethod = Literal["cash", "upi", "card"]
OrderType = Literal["dine-in", "takeaway", "delivery"]
OrderSource = Literal["counter", "whatsapp"]
Period = Literal["today", "week", "month", "30d", "all"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    """Base for request bodies: no Infinity/NaN, which would break every total that includes them."""

    model_config = ConfigDict(allow_inf_nan=False)


MAX_MONEY = 10_000_000  # ₹1 crore: far above any real bill, expense or price at one shop
MAX_IMAGE = 200_000  # characters of a data: URL (the admin page shrinks images to ~30 KB)
MAX_NOTE = 300


def _image(v: str | None) -> str | None:
    """Images are stored inline as data: URLs, or as paths on this server. External URLs are
    refused so the screens never load anything from the internet (no tracking, works offline)."""
    if v is None or v == "":
        return None
    if re.fullmatch(r"data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+", v) or re.fullmatch(
        r"/(?!/)[A-Za-z0-9._/-]*", v
    ):
        return v
    raise ValueError("must be an uploaded image (data:image/...) or a path on this server")


class ErrorOut(BaseModel):
    """Every failed request answers with this body (400, 404, 422, 501)."""

    error: str = Field(description="A message that is safe to show to the cashier as-is.")


# ---------- Menu ----------
class CategoryOut(ORM):
    id: int
    name: str
    sort: int


class CategoryIn(In):
    name: str = Field(min_length=1, max_length=60, description="Category name, e.g. `Shakes`.")

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Category name is required")
        return v


class ItemIn(In):
    code: str = Field(
        min_length=1, max_length=12, description="Short unique item ID shown on the till, e.g. `W01`."
    )
    name: str = Field(min_length=1, max_length=120)
    category_id: int = Field(description="`id` of an existing category (see `GET /api/menu`).")
    price: float = Field(ge=0, le=MAX_MONEY, description="Selling price in rupees, before GST.")
    cost: float = Field(
        default=0, ge=0, le=MAX_MONEY, description="Cost to make, in rupees (for margins; 0 = unknown)."
    )
    image: str | None = Field(
        default=None,
        max_length=MAX_IMAGE,
        description="Optional picture: a `data:image/...;base64,` URL (what the admin page uploads) "
        "or a path on this server. External URLs are refused.",
    )
    veg: bool = True
    active: bool = Field(default=True, description="False hides the item from the billing screen.")

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip()

    @field_validator("image")
    @classmethod
    def _img(cls, v: str | None) -> str | None:
        return _image(v)


class ItemOut(ORM):
    id: int
    code: str
    name: str
    category_id: int
    category: str
    price: float
    cost: float
    image: str | None
    veg: bool
    active: bool
    sort: int


class MenuOut(BaseModel):
    categories: list[CategoryOut]
    items: list[ItemOut]


class ReorderIn(In):
    ids: list[int] = Field(min_length=1, max_length=1000, description="Ids in the new display order.")


class IdOut(BaseModel):
    id: int


class OkOut(BaseModel):
    ok: bool = True


class DeleteItemOut(OkOut):
    hidden: bool


# ---------- Orders ----------
class OrderLineIn(In):
    item_id: int = Field(description="Menu item `id`.")
    qty: int = Field(default=1, ge=1, le=999)


class OrderCreate(In):
    items: list[OrderLineIn] = Field(
        max_length=100, description="At least one line (at most 100); prices come from the menu."
    )
    discount: float = Field(default=0, ge=0, le=MAX_MONEY, description="Rupees off the subtotal, before GST.")
    payment_method: PaymentMethod = "cash"
    order_type: OrderType = "dine-in"
    source: OrderSource = "counter"
    customer_name: str | None = Field(default=None, max_length=80)
    customer_phone: str | None = Field(default=None, max_length=20)
    delivery_address: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=MAX_NOTE)


class OrderItemOut(ORM):
    id: int
    item_id: int | None
    name: str
    category: str
    price: float
    qty: int


class OrderOut(ORM):
    id: int
    bill_no: str
    created_at: LocalDateTime
    subtotal: float
    discount: float
    tax: float
    total: float
    payment_method: str
    order_type: str
    source: str
    customer_name: str | None
    customer_phone: str | None
    delivery_address: str | None
    status: str
    note: str | None
    items: list[OrderItemOut]


# ---------- Targets & expenses ----------
class TargetIn(In):
    amount: float = Field(gt=0, le=MAX_MONEY * 10, description="Revenue target for the month, in rupees.")
    makeDefault: bool = Field(  # noqa: N815 - matches the front end's JSON
        default=False, description="Also use this amount for months without their own target."
    )


class ExpenseIn(In):
    category: str = Field(min_length=1, max_length=30, description="e.g. `rent`; stored lower-case.")
    amount: float = Field(gt=0, le=MAX_MONEY, description="Rupees.")
    date: dt.date | None = Field(default=None, description="`YYYY-MM-DD`; defaults to today.")
    note: str | None = Field(default=None, max_length=MAX_NOTE)
    recurring: bool = Field(default=False, description="True for a monthly cost (counts every month).")

    @field_validator("category")
    @classmethod
    def _cat(cls, v: str) -> str:
        return v.strip().lower()


class ExpenseOut(ORM):
    id: int
    date: dt.date
    category: str
    amount: float
    note: str | None
    recurring: bool


class CategoryAmount(BaseModel):
    category: str
    amount: float


class MonthExpensesOut(BaseModel):
    total: float
    recurringTotal: float  # noqa: N815
    oneOffTotal: float  # noqa: N815
    byCategory: list[CategoryAmount]  # noqa: N815
    recurring: list[ExpenseOut]
    oneOff: list[ExpenseOut]  # noqa: N815


# ---------- Sync ----------
class SyncResult(BaseModel):
    ok: bool
    message: str
    skipped: bool = False
    at: str | None = None
