from datetime import date

from fastapi import APIRouter

from waffle_pos import clock
from waffle_pos.api.deps import DB, bad_request
from waffle_pos.schemas import OrderCreate, OrderOut
from waffle_pos.services import orders

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("")
def create_order(body: OrderCreate, db: DB) -> OrderOut:
    try:
        order = orders.create_order(db, body)
    except orders.OrderError as e:
        raise bad_request(str(e)) from e
    return OrderOut.model_validate(order)


@router.get("")
def list_orders(db: DB, date: date | None = None) -> list[OrderOut]:
    return [OrderOut.model_validate(o) for o in orders.list_orders(db, date or clock.today())]


@router.get("/{order_id}")
def get_order(order_id: int, db: DB) -> OrderOut:
    order = orders.get_order(db, order_id)
    if order is None:
        raise bad_request("Not found", 404)
    return OrderOut.model_validate(order)


@router.post("/{order_id}/cancel")
def cancel_order(order_id: int, db: DB) -> OrderOut:
    order = orders.cancel_order(db, order_id)
    if order is None:
        raise bad_request("Not found", 404)
    return OrderOut.model_validate(order)
