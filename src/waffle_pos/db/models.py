"""SQLAlchemy ORM models. Schema changes go through Alembic (``waffle_pos/migrations``)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    items: Mapped[list[Item]] = relationship(back_populates="category")


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True)  # short ID on the card, e.g. W01
    name: Mapped[str] = mapped_column(String(120))
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    price: Mapped[float] = mapped_column(Float)
    cost: Mapped[float] = mapped_column(Float, default=0)  # ingredient cost per unit, for margins
    image: Mapped[str | None] = mapped_column(Text, default=None)  # small data URL
    veg: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    category: Mapped[Category] = relationship(back_populates="items")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_no: Mapped[str] = mapped_column(String(24), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)  # shop-local, naive
    subtotal: Mapped[float] = mapped_column(Float)
    discount: Mapped[float] = mapped_column(Float, default=0)
    tax: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float)
    payment_method: Mapped[str] = mapped_column(String(10), default="cash")  # cash | upi | card
    order_type: Mapped[str] = mapped_column(String(10), default="dine-in")  # dine-in | takeaway | delivery
    source: Mapped[str] = mapped_column(String(12), default="counter")  # counter | whatsapp (phase 2)
    customer_name: Mapped[str | None] = mapped_column(String(80), default=None)
    customer_phone: Mapped[str | None] = mapped_column(String(20), default=None)
    delivery_address: Mapped[str | None] = mapped_column(String(200), default=None)  # phase 2: tower / flat
    status: Mapped[str] = mapped_column(String(12), default="paid")  # paid | cancelled
    note: Mapped[str | None] = mapped_column(Text, default=None)
    synced: Mapped[bool] = mapped_column(Boolean, default=False)

    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )


class OrderItem(Base):
    """A bill line. Name, category and price are copied so old bills never change when the menu does."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id"), default=None)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(30))  # rent, salary, ingredients, ...
    amount: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    recurring: Mapped[bool] = mapped_column(Boolean, default=False)  # counts in every month from `date`
    synced: Mapped[bool] = mapped_column(Boolean, default=False)


class Target(Base):
    __tablename__ = "targets"

    month: Mapped[str] = mapped_column(String(7), primary_key=True)  # 'YYYY-MM'
    amount: Mapped[float] = mapped_column(Float)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
