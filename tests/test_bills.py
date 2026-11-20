"""Bill history: filters, search and pages (services.orders.search_orders)."""

from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from waffle_pos.db.models import Item
from waffle_pos.schemas import OrderCreate, OrderLineIn, PaymentMethod
from waffle_pos.services.orders import BillFilter, cancel_order, create_order, search_orders


def _order(
    s: Session, when: datetime, code: str, pay: PaymentMethod = "cash", customer: str | None = None
) -> int:
    item_id = s.scalar(select(Item.id).where(Item.code == code))
    assert item_id is not None
    data = OrderCreate(items=[OrderLineIn(item_id=item_id)], payment_method=pay, customer_name=customer)
    return create_order(s, data, when=when).id


@pytest.fixture
def bills(db_session: Session) -> Session:
    s = db_session
    _order(s, datetime(2026, 11, 1, 12, 0), "W01")  # 129
    _order(s, datetime(2026, 11, 18, 11, 0), "W03", "upi", customer="Ravi")  # 189
    cancel_order(s, _order(s, datetime(2026, 11, 18, 12, 0), "W01", "card"))
    for minute in range(30):  # 30 bills on the 20th
        _order(s, datetime(2026, 11, 20, 13, minute), "W01")
    s.flush()
    return s


def test_newest_first_with_pages(bills: Session) -> None:
    first = search_orders(bills, BillFilter(), page=1, page_size=25)
    assert (first.total, first.paid, first.cancelled) == (33, 32, 1)
    assert len(first.orders) == 25
    assert first.orders[0].bill_no == "WB261120-030"
    last = search_orders(bills, BillFilter(), page=2, page_size=25)
    assert [o.bill_no for o in last.orders][-3:] == ["WB261118-002", "WB261118-001", "WB261101-001"]
    assert search_orders(bills, BillFilter(), page=3, page_size=25).orders == []


def test_date_range_is_inclusive(bills: Session) -> None:
    r = search_orders(bills, BillFilter(start=date(2026, 11, 1), end=date(2026, 11, 18)))
    assert r.total == 3
    assert r.paid_total == 129 + 189
    assert search_orders(bills, BillFilter(start=date(2026, 11, 19))).total == 30
    assert search_orders(bills, BillFilter(end=date(2026, 11, 1))).total == 1


def test_status_filter_keeps_both_counts(bills: Session) -> None:
    r = search_orders(bills, BillFilter(status="cancelled"))
    assert r.total == 1 and r.orders[0].status == "cancelled"
    assert (r.paid, r.cancelled) == (32, 1)  # the tab counts ignore the status filter
    assert search_orders(bills, BillFilter(status="paid")).total == 32


def test_search_by_bill_number_item_or_customer(bills: Session) -> None:
    assert [o.bill_no for o in search_orders(bills, BillFilter(q="261118-002")).orders] == ["WB261118-002"]
    assert search_orders(bills, BillFilter(q="wb261120")).total == 30
    assert search_orders(bills, BillFilter(q="nutella")).total == 1  # W03 is the Nutella waffle
    assert search_orders(bills, BillFilter(q="ravi")).total == 1
    assert search_orders(bills, BillFilter(q="%")).total == 0  # wildcards are literal
    assert search_orders(bills, BillFilter(q="_")).total == 0


def test_payment_filter(bills: Session) -> None:
    assert search_orders(bills, BillFilter(payment="upi")).total == 1
    assert search_orders(bills, BillFilter(payment="card", status="paid")).total == 0
