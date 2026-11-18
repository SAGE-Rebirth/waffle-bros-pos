"""Creating, listing and cancelling bills."""

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from waffle_pos import clock
from waffle_pos.db.models import Item, Order, OrderItem
from waffle_pos.schemas import OrderCreate
from waffle_pos.services.settings import get_float, get_settings


class OrderError(ValueError):
    """A bill that can't be saved (empty, unknown item)."""


def _money(x: float) -> float:
    return round(x + 0.0, 2)


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
        lines.append(
            OrderItem(
                item_id=item.id, name=item.name, category=item.category.name, price=item.price, qty=line.qty
            )
        )

    subtotal = sum(li.price * li.qty for li in lines)
    discount = min(subtotal, data.discount)
    gst_rate = get_float(get_settings(session), "gst_rate")
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


def cancel_order(session: Session, order_id: int) -> Order | None:
    order = get_order(session, order_id)
    if order is not None:
        order.status = "cancelled"
        order.synced = False
        session.flush()
    return order
