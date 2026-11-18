"""Analytics, day-end and insights on a migrated, seeded temp SQLite database."""

from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from waffle_pos.db.models import Expense, Item, Target
from waffle_pos.schemas import OrderCreate, OrderLineIn, PaymentMethod
from waffle_pos.services.analytics import (
    charts,
    day_end,
    get_target,
    item_stats,
    month_expenses,
    target_summary,
)
from waffle_pos.services.insights import insights
from waffle_pos.services.orders import cancel_order, create_order
from waffle_pos.services.settings import set_settings
from waffle_pos.services.targets import TargetInput, compute

NOW = datetime(2026, 11, 18, 15, 30)  # a Wednesday


def _id(session: Session, code: str) -> int:
    item_id = session.scalar(select(Item.id).where(Item.code == code))
    assert item_id is not None
    return item_id


def _order(session: Session, when: datetime, lines: dict[str, int], payment: PaymentMethod = "cash") -> int:
    data = OrderCreate(
        items=[OrderLineIn(item_id=_id(session, code), qty=qty) for code, qty in lines.items()],
        payment_method=payment,
    )
    return create_order(session, data, when=when).id


@pytest.fixture
def shop(db_session: Session) -> Session:
    """A few weeks of trading around 18 Nov 2026, plus expenses and a November target."""
    s = db_session
    _order(s, datetime(2026, 10, 20, 12, 5), {"W02": 1})  # last month (Tue): 149
    _order(s, datetime(2026, 11, 10, 12, 0), {"W01": 2})  # Tue: 258 cash
    _order(s, datetime(2026, 11, 10, 18, 15), {"W05": 1}, "upi")  # 199
    _order(s, datetime(2026, 11, 17, 13, 45), {"C01": 1}, "upi")  # Tue: 229
    _order(s, datetime(2026, 11, 18, 11, 10), {"W01": 1})  # today: 129
    cancelled = _order(s, datetime(2026, 11, 18, 12, 0), {"W08": 1}, "card")  # today: 219, cancelled
    cancel_order(s, cancelled)
    s.add_all(
        [
            Expense(date=date(2026, 9, 1), category="rent", amount=20_000, recurring=True),
            Expense(date=date(2026, 11, 5), category="ingredients", amount=3_000, note="flour, cream"),
            Expense(date=date(2026, 10, 15), category="ingredients", amount=500),
            Expense(date=date(2026, 12, 1), category="salary", amount=15_000, recurring=True),
            Target(month="2026-11", amount=50_000),
        ]
    )
    s.flush()
    return s


# ---------- targets & expenses ----------
def test_get_target_prefers_month_row_then_default(shop: Session) -> None:
    assert get_target(shop, "2026-11") == 50_000
    assert get_target(shop, "2026-10") == 100_000  # settings default_target
    set_settings(shop, {"default_target": "75000"})
    assert get_target(shop, "2026-10") == 75_000


def test_month_expenses(shop: Session) -> None:
    nov = month_expenses(shop, "2026-11")
    assert nov["total"] == 23_000
    assert nov["recurringTotal"] == 20_000
    assert nov["oneOffTotal"] == 3_000
    assert nov["byCategory"] == [
        {"category": "rent", "amount": 20_000},
        {"category": "ingredients", "amount": 3_000},
    ]
    assert nov["oneOff"] == [
        {
            "id": nov["oneOff"][0]["id"],
            "date": "2026-11-05",
            "category": "ingredients",
            "amount": 3_000,
            "note": "flour, cream",
            "recurring": False,
        }
    ]
    assert [e["category"] for e in nov["recurring"]] == ["rent"]
    assert nov["recurring"][0]["recurring"] is True


def test_recurring_expenses_count_in_later_months_only(shop: Session) -> None:
    assert month_expenses(shop, "2026-08")["total"] == 0
    assert month_expenses(shop, "2026-09")["total"] == 20_000
    assert month_expenses(shop, "2026-10")["total"] == 20_500
    jan = month_expenses(shop, "2027-01")
    assert jan["total"] == 35_000  # rent + salary (added in December), no one-offs
    assert jan["oneOffTotal"] == 0
    assert [e["category"] for e in jan["recurring"]] == ["salary", "rent"]  # newest first


def test_target_summary(shop: Session) -> None:
    t = target_summary(shop, NOW)
    assert t["month"] == "2026-11"
    assert t["target"] == 50_000
    assert (t["daysInMonth"], t["dayOfMonth"], t["daysLeft"]) == (30, 18, 13)
    # Paid only: the cancelled 219 and last month's 149 are excluded.
    assert t["revenue"] == 815
    assert t["orders"] == 4
    assert t["todayRevenue"] == 129
    assert t["todayOrders"] == 1
    assert t["expenses"] == {
        "total": 23_000,
        "recurringTotal": 20_000,
        "oneOffTotal": 3_000,
        "byCategory": [{"category": "rent", "amount": 20_000}, {"category": "ingredients", "amount": 3_000}],
    }
    # Trading days run from the first sale (10 Nov), not from the 1st: 686 / 8 days.
    assert t["avgDaily"] == 85.75
    assert t["projected"] == 1800.75  # 686 + 85.75 x 13
    assert t["netProfit"] == -22_185
    expected = compute(
        TargetInput(
            target=50_000,
            days_in_month=30,
            day_of_month=18,
            revenue_before_today=686,
            revenue_today=129,
            orders_mtd=4,
            trading_days_before_today=8,
            expenses_total=23_000,
        )
    )
    assert {k: t[k] for k in expected} == expected


def test_target_summary_empty_month(db_session: Session) -> None:
    t = target_summary(db_session, NOW)
    assert t["revenue"] == 0
    assert t["orders"] == 0
    assert t["avgDaily"] == 0
    assert t["ordersNeededToday"] is None
    assert t["target"] == 100_000


# ---------- menu performance ----------
def test_item_stats_month(shop: Session) -> None:
    st = item_stats(shop, "month", NOW)
    assert (st["period"], st["from"], st["to"]) == ("month", "2026-11-01", "2026-11-19")
    assert len(st["items"]) == 18
    by_code = {i["code"]: i for i in st["items"]}
    w01 = by_code["W01"]
    assert (w01["qty"], w01["orders"], w01["revenue"]) == (3, 2, 387)
    assert w01["share"] == 47.48  # 387 / 815
    assert w01["margin"] == 68.99  # (129 - 40) / 129
    assert w01["category"] == "Waffle"
    assert w01["active"] is True
    assert by_code["W08"]["qty"] == 0  # its only bill was cancelled
    assert st["items"][0]["code"] == "W01"  # sorted by revenue
    assert [i["code"] for i in st["topByRevenue"]] == ["W01", "C01", "W05"]
    assert st["bestSeller"]["code"] == "W01"
    assert st["mostPopular"]["code"] == "W01"
    assert st["customerFavourite"]["code"] == "W01"
    assert len(st["slowMovers"]) == 5
    assert all(s["qty"] == 0 for s in st["slowMovers"])


def test_item_stats_periods(shop: Session) -> None:
    today = item_stats(shop, "today", NOW)
    assert (today["from"], today["to"]) == ("2026-11-18", "2026-11-19")
    assert [(i["code"], i["qty"]) for i in today["topByQty"]] == [("W01", 1)]

    week = item_stats(shop, "week", NOW)  # rolling 7 days: 12-18 Nov
    assert week["from"] == "2026-11-12"
    assert {i["code"] for i in week["topByQty"]} == {"W01", "C01"}

    all_time = item_stats(shop, "all", NOW)
    assert all_time["from"] == "0000-00-00"
    assert {i["code"] for i in all_time["topByQty"]} == {"W01", "W02", "W05", "C01"}

    thirty = item_stats(shop, "30d", NOW)
    assert thirty["from"] == "2026-10-20"
    assert "W02" in {i["code"] for i in thirty["topByQty"]}


def test_item_stats_with_no_sales(db_session: Session) -> None:
    st = item_stats(db_session, "month", NOW)
    assert st["bestSeller"] is None
    assert st["mostPopular"] is None
    assert st["customerFavourite"] is None
    assert st["topByRevenue"] == []
    assert all(i["share"] == 0 for i in st["items"])


def test_inactive_items_are_not_slow_movers(shop: Session) -> None:
    item = shop.get(Item, _id(shop, "M01"))
    assert item is not None
    item.active = False
    shop.flush()
    st = item_stats(shop, "month", NOW)
    assert "M01" not in {s["code"] for s in st["slowMovers"]}
    assert next(i for i in st["items"] if i["code"] == "M01")["active"] is False


# ---------- charts ----------
def test_charts(shop: Session) -> None:
    c = charts(shop, NOW)
    assert set(c) == {"hourly", "daily", "weekly", "monthly", "categorySplit", "paymentSplit", "weekday"}

    hourly = {h["hour"]: h for h in c["hourly"]}
    assert min(hourly) == 10
    assert max(hourly) == 23
    assert hourly[11] == {
        "hour": 11,
        "label": "11am",
        "today": 129,
        "todayOrders": 1,
        "average": 0,
        "avgOrders": 0,
    }
    # 28-day history before today has 2 trading days (10 and 17 Nov); 20 Oct is outside it.
    assert hourly[12]["average"] == 129
    assert hourly[12]["label"] == "12pm"
    assert hourly[12]["today"] == 0  # the 12:00 bill today was cancelled
    assert hourly[13]["average"] == 114.5
    assert hourly[18]["avgOrders"] == 0.5

    daily = c["daily"]
    assert len(daily) == 30
    assert daily[9] == {
        "day": 10,
        "date": "2026-11-10",
        "revenue": 457,
        "orders": 2,
        "cumulative": 457,
        "pace": 16_666.67,
        "dailyTarget": 1666.67,
    }
    assert daily[17]["cumulative"] == 815
    assert daily[18]["revenue"] is None
    assert daily[18]["cumulative"] is None
    assert daily[29]["pace"] == 50_000

    weekly = c["weekly"]
    assert len(weekly) == 12
    assert weekly[-1] == {"week": "16 Nov", "start": "2026-11-16", "revenue": 229 + 129, "orders": 2}
    assert weekly[-2] == {"week": "9 Nov", "start": "2026-11-09", "revenue": 258 + 199, "orders": 2}
    assert weekly[0]["start"] == "2026-08-31"

    monthly = c["monthly"]
    assert len(monthly) == 12
    assert monthly[0]["key"] == "2025-12"
    assert monthly[-1] == {
        "month": "Nov 26",
        "key": "2026-11",
        "revenue": 815,
        "orders": 4,
        "target": 50_000,
        "expenses": 23_000,
    }
    assert monthly[-2]["revenue"] == 149
    assert monthly[-2]["expenses"] == 20_500

    assert c["categorySplit"] == [
        {"name": "Waffle", "value": 586, "qty": 4},
        {"name": "Combo", "value": 229, "qty": 1},
    ]
    assert c["paymentSplit"] == [
        {"name": "upi", "value": 428, "orders": 2},
        {"name": "cash", "value": 387, "orders": 2},
    ]

    assert [w["day"] for w in c["weekday"]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday = {w["day"]: w["average"] for w in c["weekday"]}
    assert weekday["Tue"] == round((457 + 229 + 149) / 3, 2)
    assert weekday["Wed"] == 0  # today is not part of the history


def test_hourly_extends_past_opening_hours(shop: Session) -> None:
    _order(shop, datetime(2026, 11, 18, 8, 30), {"M01": 1})
    c = charts(shop, NOW)
    assert c["hourly"][0]["hour"] == 8
    assert c["hourly"][0]["label"] == "8am"
    assert c["hourly"][0]["today"] == 99


# ---------- day end ----------
def test_day_end(shop: Session) -> None:
    d = day_end(shop, date(2026, 11, 18))
    assert d["date"] == "2026-11-18"
    assert (d["revenue"], d["orders"], d["aov"]) == (129, 1, 129)
    assert d["items"] == [
        {"name": "Classic Maple Butter", "category": "Waffle", "qty": 1, "revenue": 129, "orders": 1}
    ]
    assert d["payments"] == [{"method": "cash", "amount": 129, "orders": 1}]
    assert d["cancelled"] == {"n": 1, "amount": 219}
    not_sold = {n["name"] for n in d["notSold"]}
    assert len(not_sold) == 17
    assert "Lotus Biscoff" in not_sold  # cancelled bills don't count as sold
    assert "Classic Maple Butter" not in not_sold


def test_day_end_busy_and_empty_days(shop: Session) -> None:
    d = day_end(shop, date(2026, 11, 10))
    assert (d["revenue"], d["orders"], d["aov"]) == (457, 2, 228.5)
    assert [i["name"] for i in d["items"]] == ["Classic Maple Butter", "Nutella"]
    assert {p["method"] for p in d["payments"]} == {"cash", "upi"}
    assert d["cancelled"] == {"n": 0, "amount": 0}

    empty = day_end(shop, date(2026, 11, 11))
    assert (empty["revenue"], empty["orders"], empty["aov"]) == (0, 0, 0)
    assert empty["items"] == []
    assert len(empty["notSold"]) == 18


# ---------- insights ----------
def test_insights_no_sales(db_session: Session) -> None:
    out = insights(db_session, NOW)
    assert out == [
        {
            "tone": "info",
            "title": "No sales yet this month",
            "text": "Your target is ₹1,00,000. That is ₹3,333 a day at an even pace. "
            "Bill your first order to start tracking.",
        }
    ]


def test_insights_behind_target(shop: Session) -> None:
    out = insights(shop, NOW)
    titles = [i["title"] for i in out]
    assert titles[0] == "Behind the monthly target"
    assert out[0]["tone"] == "warn"
    assert "₹48,199 short" in out[0]["text"]  # 50000 - 1800.75
    assert titles[1] == "Today's goal"
    assert "more orders at your average bill of ₹204" in out[1]["text"]
    assert "Average bill ₹204" in titles
    assert "Not covering expenses yet" in titles
    assert "Biggest cost: Rent" in titles
    biggest = next(i for i in out if i["title"] == "Biggest cost: Rent")
    assert biggest["text"] == "₹20,000 this month, 87% of all expenses."
    assert "Best seller: Classic Maple Butter" in titles
    assert any(i["title"] == "Slow movers" for i in out)
    assert all(i["tone"] in {"good", "warn", "info"} for i in out)


def test_insights_target_reached(shop: Session) -> None:
    target = shop.get(Target, "2026-11")
    assert target is not None
    target.amount = 500
    shop.flush()
    out = insights(shop, NOW)
    titles = [i["title"] for i in out]
    assert titles[:2] == ["On track for the monthly target", "Monthly target reached"]
    reached = out[1]["text"]
    assert reached.startswith("₹815 so far against ₹500.")
    assert "around ₹0." in reached  # projected 1800.75 rounds to the nearest 5000


def test_insights_without_expenses_and_with_profit(db_session: Session) -> None:
    s = db_session
    for day in (10, 11, 12, 13, 16, 17):
        for hour in (11, 15, 19):
            _order(s, datetime(2026, 11, day, hour, 0), {"C03": 2})
    out = insights(s, NOW)
    titles = [i["title"] for i in out]
    assert "Add your expenses" in titles
    assert "Busiest hour: 11am" in titles  # equal averages: the first hour wins, like the Node sort
    assert any(t.endswith("is your strongest day") for t in titles)

    s.add(Expense(date=date(2026, 11, 1), category="rent", amount=5_000, recurring=True))
    s.flush()
    out = insights(s, NOW)
    net = next(i for i in out if i["title"].startswith("Net so far"))
    assert net["tone"] == "good"
    assert net["title"] == "Net so far ₹14,764"  # 18 x 1098 - 5000
    assert net["text"].startswith("Expenses are 25% of sales")
