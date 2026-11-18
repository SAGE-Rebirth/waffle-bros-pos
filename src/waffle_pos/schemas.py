"""Pydantic request/response models. Field names match the JSON the React front end uses."""

import datetime as dt
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


# ---------- Menu ----------
class CategoryOut(ORM):
    id: int
    name: str
    sort: int


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Category name is required")
        return v


class ItemIn(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    name: str = Field(min_length=1, max_length=120)
    category_id: int
    price: float = Field(ge=0)
    cost: float = Field(default=0, ge=0)
    image: str | None = None
    veg: bool = True
    active: bool = True

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return v.strip()


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


class IdOut(BaseModel):
    id: int


class OkOut(BaseModel):
    ok: bool = True


class DeleteItemOut(OkOut):
    hidden: bool


# ---------- Orders ----------
class OrderLineIn(BaseModel):
    item_id: int
    qty: int = Field(default=1, ge=1, le=999)


class OrderCreate(BaseModel):
    items: list[OrderLineIn]
    discount: float = Field(default=0, ge=0)
    payment_method: PaymentMethod = "cash"
    order_type: OrderType = "dine-in"
    source: OrderSource = "counter"
    customer_name: str | None = Field(default=None, max_length=80)
    customer_phone: str | None = Field(default=None, max_length=20)
    delivery_address: str | None = Field(default=None, max_length=200)
    note: str | None = None


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
class TargetIn(BaseModel):
    amount: float = Field(gt=0)
    makeDefault: bool = False  # noqa: N815 - matches the front end's JSON


class ExpenseIn(BaseModel):
    category: str = Field(min_length=1, max_length=30)
    amount: float = Field(gt=0)
    date: dt.date | None = None
    note: str | None = None
    recurring: bool = False

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
