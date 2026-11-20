"""Creating, listing and cancelling bills."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import ColumnElement, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from waffle_pos import clock
from waffle_pos.db.models import Item, Order, OrderItem
from waffle_pos.modules.builtin import DiscountSettings, GstSettings
from waffle_pos.modules.registry import is_enabled, settings_of
from waffle_pos.schemas import OrderCreate
from waffle_pos.services.fmt import inr
from waffle_pos.services.targets import money


class OrderError(ValueError):
    """A bill that can't be saved (empty, unknown item)."""


def _money(x: float) -> float:
    return money(x)


def next_bill_no(session: Session, when: datetime) -> str:
    start, end = clock.day_bounds(when.date())
    count = session.scalar(
        select(func.count()).select_from(Order).where(Order.created_at >= start, Order.created_at < end)
    )
    return f"WB{when:%y%m%d}-{(count or 0) + 1:03d}"


def create_order(session: Session, data: OrderCreate, when: datetime | None = None) -> Order:
    """Price the bill from the menu (never trust prices from the client) and save it."""
    if not data.items:
        raise OrderError("The order is empty")
    when = when or clock.now()

    ids = {line.item_id for line in data.items}
    items = {
        i.id: i
        for i in session.scalars(select(Item).options(selectinload(Item.category)).where(Item.id.in_(ids)))
    }
    lines: list[OrderItem] = []
    for line in data.items:
        item = items.get(line.item_id)
        if item is None:
            raise OrderError(f"Unknown item {line.item_id}")
        if not item.active:
            raise OrderError(f"{item.name} is hidden from the menu and can't be billed")
        lines.append(
            OrderItem(
                item_id=item.id, name=item.name, category=item.category.name, price=item.price, qty=line.qty
            )
        )

    subtotal = sum(li.price * li.qty for li in lines)
    discount = 0.0
    if data.discount > 0:
        if not is_enabled(session, "discounts"):
            raise OrderError("Discounts are switched off in the admin dashboard")
        max_pct = settings_of(session, "discounts", DiscountSettings).max_discount_pct
        cap = subtotal * max_pct / 100
        if data.discount > cap + 0.005:
            raise OrderError(f"Discount can be at most {max_pct:g}% of the bill ({inr(cap)})")
        discount = min(subtotal, data.discount)
    gst_rate = settings_of(session, "gst", GstSettings).rate if is_enabled(session, "gst") else 0.0
    tax = _money((subtotal - discount) * gst_rate / 100)
    order = Order(
        bill_no=next_bill_no(session, when),
        created_at=when,
        subtotal=_money(subtotal),
        discount=_money(discount),
        tax=tax,
        total=_money(subtotal - discount + tax),
        payment_method=data.payment_method,
        order_type=data.order_type,
        source=data.source,
        customer_name=data.customer_name or None,
        customer_phone=data.customer_phone or None,
        delivery_address=data.delivery_address or None,
        note=data.note or None,
        items=lines,
    )
    session.add(order)
    session.flush()
    return order


def get_order(session: Session, order_id: int) -> Order | None:
    return session.scalar(select(Order).options(selectinload(Order.items)).where(Order.id == order_id))


def list_orders(session: Session, day: date) -> list[Order]:
    start, end = clock.day_bounds(day)
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.created_at >= start, Order.created_at < end)
        .order_by(Order.id.desc())
    )
    return list(session.scalars(stmt))


@dataclass(frozen=True)
class BillFilter:
    """What the Bills page asks for. Dates are shop-local and inclusive; None means open-ended."""

    start: date | None = None
    end: date | None = None
    q: str = ""
    status: str = "all"  # all | paid | cancelled
    payment: str | None = None  # cash | upi | card


@dataclass(frozen=True)
class BillPage:
    orders: list[Order]
    total: int  # bills matching every filter, across all pages
    paid: int  # bills matching the filters except status, by status
    cancelled: int
    paid_total: float  # rupees in the paid ones


def _like(text: str) -> str:
    """A LIKE pattern matching `text` anywhere, with % and _ taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _conditions(f: BillFilter) -> list[ColumnElement[bool]]:
    """WHERE parts for every filter except status (the page shows per-status counts)."""
    where: list[ColumnElement[bool]] = []
    if f.start is not None:
        where.append(Order.created_at >= clock.day_bounds(f.start)[0])
    if f.end is not None:
        where.append(Order.created_at < clock.day_bounds(f.end)[0] + timedelta(days=1))
    if f.payment:
        where.append(Order.payment_method == f.payment)
    q = f.q.strip()
    if q:
        pat = _like(q.lower())
        line_match = (
            select(OrderItem.id)
            .where(OrderItem.order_id == Order.id, func.lower(OrderItem.name).like(pat, escape="\\"))
            .exists()
        )
        where.append(
            or_(
                func.lower(Order.bill_no).like(pat, escape="\\"),
                func.lower(func.coalesce(Order.customer_name, "")).like(pat, escape="\\"),
                func.coalesce(Order.customer_phone, "").like(pat, escape="\\"),
                line_match,
            )
        )
    return where


def search_orders(session: Session, f: BillFilter, page: int = 1, page_size: int = 25) -> BillPage:
    """One page of bills, newest first, plus counts for the whole filtered range."""
    where = _conditions(f)
    paid, cancelled, paid_total = session.execute(
        select(
            func.count(case((Order.status == "paid", 1))),
            func.count(case((Order.status == "cancelled", 1))),
            func.coalesce(func.sum(case((Order.status == "paid", Order.total))), 0.0),
        ).where(*where)
    ).one()
    if f.status in ("paid", "cancelled"):
        where.append(Order.status == f.status)
    total = {"paid": paid, "cancelled": cancelled}.get(f.status, paid + cancelled)
    stmt = (
        select(Order)
        .options(selectinload(Order.items))
        .where(*where)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return BillPage(
        orders=list(session.scalars(stmt)),
        total=int(total),
        paid=int(paid),
        cancelled=int(cancelled),
        paid_total=money(float(paid_total)),
    )


def cancel_order(session: Session, order_id: int) -> Order | None:
    order = get_order(session, order_id)
    if order is not None:
        order.status = "cancelled"
        order.synced = False
        session.flush()
    return order
