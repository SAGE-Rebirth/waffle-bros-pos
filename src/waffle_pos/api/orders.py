"""Bills: create, list, look up and cancel. Money is in rupees; times are shop-local."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Path, Query

from waffle_pos import clock
from waffle_pos.api.deps import ADMIN_401, ADMIN_403, DB, INVALID, AdminOnly, bad_request, errors
from waffle_pos.schemas import (
    MAX_PAGE_SIZE,
    BillsPageOut,
    BillStatus,
    OrderCreate,
    OrderOut,
    PaymentMethod,
)
from waffle_pos.services import orders

router = APIRouter(prefix="/api/orders", tags=["orders"])
# The bill history lives at /api/bills so it can't clash with /api/orders/{order_id}.
bills_router = APIRouter(prefix="/api/bills", tags=["orders"])

OrderId = Annotated[int, Path(description="The order's numeric `id` (not its `bill_no`).")]


@router.post(
    "",
    summary="Bill an order",
    responses=errors(
        {400: "The order is empty, an `item_id` is unknown, or the discount is not allowed.", 422: INVALID}
    ),
)
def create_order(body: OrderCreate, db: DB) -> OrderOut:
    """Create a paid bill and return it with its `bill_no` (`WB<yymmdd>-<nnn>`, numbered per day).

    Prices come from the menu, never from the request. Totals, in rupees:
    `subtotal` = sum of price x qty; `discount` = rupees off before GST (rejected with 400 when
    discounts are not allowed or exceed the allowed cap); `tax` = (subtotal - discount) x GST rate
    / 100 (0 when GST is off); `total` = subtotal - discount + tax. `created_at` is the shop-local
    time now (`YYYY-MM-DD HH:MM:SS`). The bill is queued for the next Google Sheet sync.
    """
    try:
        order = orders.create_order(db, body)
    except orders.OrderError as e:
        raise bad_request(str(e)) from e
    return OrderOut.model_validate(order)


@router.get("", summary="List one day's bills", responses=errors({422: INVALID}))
def list_orders(
    db: DB,
    date: Annotated[
        date | None, Query(description="Shop-local day, `YYYY-MM-DD`. Defaults to today.")
    ] = None,
) -> list[OrderOut]:
    """Every bill created on that day, newest first, including cancelled ones (`status: cancelled`)."""
    return [OrderOut.model_validate(o) for o in orders.list_orders(db, date or clock.today())]


@router.get(
    "/{order_id}", summary="Get one bill", responses=errors({404: "No order with that id.", 422: INVALID})
)
def get_order(order_id: OrderId, db: DB) -> OrderOut:
    """One bill with its line items, for reprinting or checking."""
    order = orders.get_order(db, order_id)
    if order is None:
        raise bad_request("Not found", 404)
    return OrderOut.model_validate(order)


@router.post(
    "/{order_id}/cancel",
    summary="Cancel a bill (Admin)",
    dependencies=[AdminOnly],
    responses=errors({401: ADMIN_401, 403: ADMIN_403, 404: "No order with that id.", 422: INVALID}),
)
def cancel_order(order_id: OrderId, db: DB) -> OrderOut:
    """Needs the admin PIN, so a paid bill can't be quietly cancelled at the counter.
    Mark a bill `cancelled` and return it. The bill is kept (bills are history) but no longer
    counts towards revenue, targets or item stats; the day-end sheet lists it under `cancelled`.
    The next Google Sheet sync appends the bill again with status `cancelled` (the earlier row is
    left as it was). Cancelling twice is harmless.
    """
    order = orders.cancel_order(db, order_id)
    if order is None:
        raise bad_request("Not found", 404)
    return OrderOut.model_validate(order)


@bills_router.get(
    "",
    summary="Browse past bills, a page at a time",
    responses=errors({400: "`from` is after `to`.", 422: INVALID}),
)
def list_bills(
    *,
    db: DB,
    from_: Annotated[
        date | None,
        Query(alias="from", description="First shop-local day, `YYYY-MM-DD` (inclusive). Omit for no limit."),
    ] = None,
    to: Annotated[
        date | None,
        Query(description="Last shop-local day, `YYYY-MM-DD` (inclusive). Omit for no limit."),
    ] = None,
    q: Annotated[
        str,
        Query(
            max_length=40,
            description="Search text: part of a bill number (`014`, `WB261120`), an item name, "
            "or a customer's name or phone. Case-insensitive.",
        ),
    ] = "",
    status: Annotated[BillStatus, Query(description="`all`, `paid` or `cancelled`.")] = "all",
    payment: Annotated[PaymentMethod | None, Query(description="Only this payment method.")] = None,
    page: Annotated[int, Query(ge=1, le=100_000, description="Page number, from 1.")] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Bills per page.")] = 25,
) -> BillsPageOut:
    """Bills on any day, newest first, including cancelled ones, with filters and pages.

    `total` and `pages` count every bill that matches; `paid`, `cancelled` and `paid_total` ignore
    the `status` filter so a screen can show counts on its All / Paid / Cancelled tabs. A page past
    the last one comes back with no `items`.
    """
    if from_ is not None and to is not None and from_ > to:
        raise bad_request("`from` must be on or before `to`")
    f = orders.BillFilter(start=from_, end=to, q=q, status=status, payment=payment)
    result = orders.search_orders(db, f, page=page, page_size=page_size)
    return BillsPageOut(
        items=[OrderOut.model_validate(o) for o in result.orders],
        page=page,
        page_size=page_size,
        pages=max(1, -(-result.total // page_size)),
        total=result.total,
        paid=result.paid,
        cancelled=result.cancelled,
        paid_total=result.paid_total,
    )
