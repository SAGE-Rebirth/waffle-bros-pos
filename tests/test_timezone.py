"""Every report buckets bills by the shop's own day and hour (Asia/Kolkata), never by UTC.

The Docker container's clock runs on UTC, so these tests freeze the *UTC* instant and check that a
bill lands on the IST day, hour and weekday on every screen: today's total, the hourly and daily
charts, the weekday averages, the month calendar and the day-end sheet.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, tzinfo

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from waffle_pos import clock
from waffle_pos.db.models import Item, Order
from waffle_pos.schemas import OrderCreate, OrderLineIn
from waffle_pos.services.analytics import calendar, charts, day_end, item_stats, target_summary
from waffle_pos.services.orders import cancel_order, create_order

Freeze = Callable[[datetime], None]


@pytest.fixture
def freeze(monkeypatch: pytest.MonkeyPatch) -> Iterator[Freeze]:
    """Pin ``clock.now()`` to a UTC instant, converted through the real time-zone code."""

    def _freeze(utc: datetime) -> None:
        class Frozen(datetime):
            @classmethod
            def now(cls, tz: tzinfo | None = None) -> "Frozen":
                moment = utc.replace(tzinfo=UTC)
                local = moment.astimezone(tz) if tz is not None else moment
                return cls(*local.timetuple()[:6], tzinfo=local.tzinfo)

        monkeypatch.setattr(clock, "datetime", Frozen)

    yield _freeze


def _bill(session: Session, code: str = "W01", qty: int = 1) -> Order:
    item_id = session.scalar(select(Item.id).where(Item.code == code))
    assert item_id is not None
    return create_order(session, OrderCreate(items=[OrderLineIn(item_id=item_id, qty=qty)]))


def test_clock_is_shop_local_not_utc(freeze: Freeze) -> None:
    freeze(datetime(2026, 11, 19, 18, 45))  # 18:45 UTC = 00:15 IST the next day
    assert clock.now() == datetime(2026, 11, 20, 0, 15)
    assert clock.today() == date(2026, 11, 20)


def test_bill_after_ist_midnight_counts_for_the_ist_day(db_session: Session, freeze: Freeze) -> None:
    # 00:30 IST on Friday 20 Nov is still Thursday 19 Nov in UTC.
    freeze(datetime(2026, 11, 19, 19, 0))
    bill = _bill(db_session)  # Amul Dark Chocolate Waffle, 129
    assert bill.created_at == datetime(2026, 11, 20, 0, 30)
    assert bill.bill_no.startswith("WB261120")

    now = clock.now()
    t = target_summary(db_session, now)
    assert (t["todayRevenue"], t["todayOrders"]) == (129, 1)

    c = charts(db_session, now)
    hourly = {h["hour"]: h for h in c["hourly"]}
    assert hourly[0]["today"] == 129  # the 12am bar, not 7pm
    assert hourly[0]["label"] == "12am"
    assert c["daily"][19]["date"] == "2026-11-20"
    assert c["daily"][19]["revenue"] == 129
    assert c["daily"][18]["revenue"] == 0

    assert day_end(db_session, date(2026, 11, 20))["revenue"] == 129
    assert day_end(db_session, date(2026, 11, 19))["revenue"] == 0
    assert item_stats(db_session, "today", now)["bestSeller"]["code"] == "W01"

    cal = calendar(db_session, "2026-11", now.date())
    assert cal["today"] == "2026-11-20"
    assert cal["days"][19]["revenue"] == 129
    assert cal["days"][18]["revenue"] == 0


def test_late_evening_bill_stays_on_its_ist_day(db_session: Session, freeze: Freeze) -> None:
    # 23:50 IST on Thursday 19 Nov is 18:20 UTC: still Thursday either way, and the 11pm bar.
    freeze(datetime(2026, 11, 19, 18, 20))
    _bill(db_session, "B01", 2)  # Amul Dark Chocolate Bowl, 2 x 129
    freeze(datetime(2026, 11, 20, 6, 30))  # next day, 12:00 IST
    now = clock.now()

    assert day_end(db_session, date(2026, 11, 19))["revenue"] == 258
    t = target_summary(db_session, now)
    assert (t["todayRevenue"], t["revenue"]) == (0, 258)

    c = charts(db_session, now)
    weekday = {w["day"]: w["average"] for w in c["weekday"]}
    assert weekday["Thu"] == 258
    assert weekday["Fri"] == 0
    assert c["daily"][18]["revenue"] == 258
    hist = {h["hour"]: h for h in c["hourly"]}
    assert hist[23]["average"] == 258  # one trading day in the last 4 weeks


def test_cancelled_bill_is_not_sales(db_session: Session, freeze: Freeze) -> None:
    freeze(datetime(2026, 11, 20, 6, 33))  # 12:03 IST
    cancel_order(db_session, _bill(db_session).id)
    now = clock.now()
    assert target_summary(db_session, now)["todayRevenue"] == 0
    d = day_end(db_session, now.date())
    assert (d["revenue"], d["cancelled"]) == (0, {"n": 1, "amount": 129})
    cal = calendar(db_session, "2026-11", now.date())
    assert cal["days"][19] | {} == {
        "date": "2026-11-20",
        "day": 20,
        "weekday": 4,  # Friday
        "revenue": 0,
        "orders": 0,
        "cancelled": 1,
        "future": False,
        "today": True,
    }
