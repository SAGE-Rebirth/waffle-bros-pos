"""Dashboard and day-end numbers, ported from the Node ``server/analytics.js``.

Every JSON key matches what the React pages (Dashboard, DayEnd) read, so keys stay camelCase.
Only paid orders count towards revenue; cancelled bills are reported separately on the day-end sheet.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, Integer, cast, func, select
from sqlalchemy.orm import Session

from waffle_pos import clock
from waffle_pos.db.models import Category, Expense, Item, Order, OrderItem, Target
from waffle_pos.modules.builtin import ShopSettings, TargetSettings
from waffle_pos.modules.registry import settings_of
from waffle_pos.services.targets import TargetInput, compute, money

PERIODS = ("today", "week", "month", "30d", "all")
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")  # date.weekday() order


def _at(d: date) -> datetime:
    """Midnight at the start of ``d`` (orders are stored as naive shop-local datetimes)."""
    return datetime(d.year, d.month, d.day)


def _paid_between(start: date | None, end: date | None) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [Order.status == "paid"]
    if start is not None:
        conds.append(Order.created_at >= _at(start))
    if end is not None:
        conds.append(Order.created_at < _at(end))
    return conds


def _revenue_between(session: Session, start: date, end: date) -> tuple[float, int]:
    row = session.execute(
        select(func.coalesce(func.sum(Order.total), 0.0), func.count(Order.id)).where(
            *_paid_between(start, end)
        )
    ).one()
    return float(row[0]), int(row[1])


def _day_of(col: Any) -> ColumnElement[str]:
    return func.strftime("%Y-%m-%d", col)


def _hour_of(col: Any) -> ColumnElement[int]:
    return cast(func.strftime("%H", col), Integer)


# ---------- Targets & expenses ----------
def get_target(session: Session, month: str) -> float:
    row = session.get(Target, month)
    if row is not None:
        return float(row.amount)
    return settings_of(session, "targets", TargetSettings).default_target


def _expense_dict(e: Expense) -> dict[str, Any]:
    return {
        "id": e.id,
        "date": e.date.isoformat(),
        "category": e.category,
        "amount": e.amount,
        "note": e.note,
        "recurring": bool(e.recurring),
    }


def month_expenses(session: Session, month: str) -> dict[str, Any]:
    start = clock.parse_month(month)
    end = clock.next_month_start(start)
    newest_first = (Expense.date.desc(), Expense.id.desc())
    one_off = list(
        session.scalars(
            select(Expense)
            .where(Expense.recurring.is_(False), Expense.date >= start, Expense.date < end)
            .order_by(*newest_first)
        )
    )
    # Recurring expenses (rent, salaries) count in every month from the month they were added.
    recurring = list(
        session.scalars(
            select(Expense).where(Expense.recurring.is_(True), Expense.date < end).order_by(*newest_first)
        )
    )
    by_cat: dict[str, float] = defaultdict(float)
    for e in [*recurring, *one_off]:
        by_cat[e.category] += e.amount
    recurring_total = sum(e.amount for e in recurring)
    one_off_total = sum(e.amount for e in one_off)
    return {
        "total": money(recurring_total + one_off_total),
        "recurringTotal": money(recurring_total),
        "oneOffTotal": money(one_off_total),
        "byCategory": sorted(
            ({"category": c, "amount": money(a)} for c, a in by_cat.items()),
            key=lambda r: -r["amount"],
        ),
        "recurring": [_expense_dict(e) for e in recurring],
        "oneOff": [_expense_dict(e) for e in one_off],
    }


def target_summary(session: Session, now: datetime) -> dict[str, Any]:
    today = now.date()
    tomorrow = today + timedelta(days=1)
    first_of_month = clock.month_start(today)
    month = clock.month_key(today)
    dim = clock.days_in_month(today)
    target = get_target(session, month)

    revenue_before, _ = _revenue_between(session, first_of_month, today)
    revenue_today, orders_today = _revenue_between(session, today, tomorrow)
    revenue_mtd, orders_mtd = _revenue_between(session, first_of_month, tomorrow)

    first_sale = session.scalar(
        select(func.min(_day_of(Order.created_at))).where(*_paid_between(first_of_month, None))
    )
    first_day = date.fromisoformat(first_sale) if first_sale else None
    trading_days = (today - first_day).days if first_day is not None and first_day < today else 0

    expenses = month_expenses(session, month)
    numbers = compute(
        TargetInput(
            target=target,
            days_in_month=dim,
            day_of_month=today.day,
            revenue_before_today=revenue_before,
            revenue_today=revenue_today,
            orders_mtd=orders_mtd,
            trading_days_before_today=trading_days,
            expenses_total=expenses["total"],
        )
    )
    return {
        "month": month,
        "target": target,
        "daysInMonth": dim,
        "dayOfMonth": today.day,
        "daysLeft": dim - today.day + 1,  # including today
        "revenue": money(revenue_mtd),
        "orders": orders_mtd,
        "todayRevenue": money(revenue_today),
        "todayOrders": orders_today,
        "expenses": {
            "total": expenses["total"],
            "recurringTotal": expenses["recurringTotal"],
            "oneOffTotal": expenses["oneOffTotal"],
            "byCategory": expenses["byCategory"],
        },
        **numbers,
    }


# ---------- Charts ----------
def _hour_label(h: int) -> str:
    return f"{(h + 11) % 12 + 1}{'am' if h < 12 else 'pm'}"


def _by_hour(session: Session, start: date, end: date) -> dict[int, tuple[float, int]]:
    hour = _hour_of(Order.created_at)
    rows = session.execute(
        select(hour, func.sum(Order.total), func.count(Order.id))
        .where(*_paid_between(start, end))
        .group_by(hour)
    ).all()
    return {int(h): (float(rev), int(n)) for h, rev, n in rows}


def _by_day(session: Session, start: date, end: date) -> dict[str, tuple[float, int]]:
    day = _day_of(Order.created_at)
    rows = session.execute(
        select(day, func.sum(Order.total), func.count(Order.id))
        .where(*_paid_between(start, end))
        .group_by(day)
    ).all()
    return {str(d): (float(rev), int(n)) for d, rev, n in rows}


def _hourly(session: Session, today: date) -> list[dict[str, Any]]:
    """Today, hour by hour, against the average of the previous 28 days."""
    tomorrow = today + timedelta(days=1)
    hist_from = today - timedelta(days=28)
    today_hours = _by_hour(session, today, tomorrow)
    avg_hours = _by_hour(session, hist_from, today)
    hist_days = (
        session.scalar(
            select(func.count(func.distinct(_day_of(Order.created_at)))).where(
                *_paid_between(hist_from, today)
            )
        )
        or 0
    )
    shop = settings_of(session, "shop", ShopSettings)
    open_h, close_h = shop.open_hour, shop.close_hour
    first = min([open_h, *today_hours])
    last = max([close_h, *today_hours])
    out: list[dict[str, Any]] = []
    for h in range(first, last + 1):
        t_rev, t_n = today_hours.get(h, (0.0, 0))
        a_rev, a_n = avg_hours.get(h, (0.0, 0))
        out.append(
            {
                "hour": h,
                "label": _hour_label(h),
                "today": money(t_rev),
                "todayOrders": t_n,
                "average": money(a_rev / hist_days) if hist_days else 0,
                "avgOrders": money(a_n / hist_days) if hist_days else 0,
            }
        )
    return out


def _daily(session: Session, today: date, target: float) -> list[dict[str, Any]]:
    """This month day by day, with the even-pace line and the running total."""
    start = clock.month_start(today)
    dim = clock.days_in_month(today)
    rows = _by_day(session, start, clock.next_month_start(today))
    out: list[dict[str, Any]] = []
    cum = 0.0
    for d in range(1, dim + 1):
        day = start.replace(day=d)
        key = day.isoformat()
        rev, n = rows.get(key, (0.0, 0))
        future = day > today
        if not future:
            cum += rev
        out.append(
            {
                "day": d,
                "date": key,
                "revenue": None if future else money(rev),
                "orders": None if future else n,
                "cumulative": None if future else money(cum),
                "pace": money(target / dim * d),
                "dailyTarget": money(target / dim),
            }
        )
    return out


def _weekly(session: Session, today: date) -> list[dict[str, Any]]:
    """The last 12 weeks, Monday to Sunday."""
    this_week = clock.start_of_week(today)
    out: list[dict[str, Any]] = []
    for i in range(11, -1, -1):
        ws = this_week - timedelta(days=7 * i)
        rev, n = _revenue_between(session, ws, ws + timedelta(days=7))
        out.append({"week": f"{ws.day} {ws:%b}", "start": ws.isoformat(), "revenue": money(rev), "orders": n})
    return out


def monthly_summary(session: Session, today: date) -> list[dict[str, Any]]:
    """The last 12 months with their targets and expenses."""
    out: list[dict[str, Any]] = []
    for i in range(11, -1, -1):
        idx = today.year * 12 + today.month - 1 - i
        ms = date(idx // 12, idx % 12 + 1, 1)
        key = clock.month_key(ms)
        rev, n = _revenue_between(session, ms, clock.next_month_start(ms))
        out.append(
            {
                "month": f"{ms:%b} {ms:%y}",
                "key": key,
                "revenue": money(rev),
                "orders": n,
                "target": get_target(session, key),
                "expenses": month_expenses(session, key)["total"],
            }
        )
    return out


def _splits(session: Session, today: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Category and payment-method split for this month."""
    start = clock.month_start(today)
    value = func.sum(OrderItem.qty * OrderItem.price)
    cat_rows = session.execute(
        select(OrderItem.category, value, func.sum(OrderItem.qty))
        .join(Order, Order.id == OrderItem.order_id)
        .where(*_paid_between(start, None))
        .group_by(OrderItem.category)
        .order_by(value.desc())
    ).all()
    total = func.sum(Order.total)
    pay_rows = session.execute(
        select(Order.payment_method, total, func.count(Order.id))
        .where(*_paid_between(start, None))
        .group_by(Order.payment_method)
        .order_by(total.desc())
    ).all()
    categories = [{"name": c, "value": money(v), "qty": int(q)} for c, v, q in cat_rows]
    payments = [{"name": m, "value": money(v), "orders": int(n)} for m, v, n in pay_rows]
    return categories, payments


def _weekday(session: Session, today: date) -> list[dict[str, Any]]:
    """Average revenue per weekday over the last 8 weeks (days with sales only), Monday first."""
    rows = _by_day(session, today - timedelta(days=56), today)
    totals = [0.0] * 7
    days = [0] * 7
    for d, (rev, _) in rows.items():
        wd = date.fromisoformat(d).weekday()
        totals[wd] += rev
        days[wd] += 1
    return [
        {"day": name, "average": money(totals[i] / days[i]) if days[i] else 0}
        for i, name in enumerate(_WEEKDAYS)
    ]


def charts(session: Session, now: datetime) -> dict[str, Any]:
    today = now.date()
    target = get_target(session, clock.month_key(today))
    category_split, payment_split = _splits(session, today)
    return {
        "hourly": _hourly(session, today),
        "daily": _daily(session, today, target),
        "weekly": _weekly(session, today),
        "monthly": monthly_summary(session, today),
        "categorySplit": category_split,
        "paymentSplit": payment_split,
        "weekday": _weekday(session, today),
    }


# ---------- Menu performance ----------
def _period_range(period: str, today: date) -> tuple[date | None, date]:
    tomorrow = today + timedelta(days=1)
    if period == "today":
        return today, tomorrow
    if period == "week":
        return today - timedelta(days=6), tomorrow
    if period == "month":
        return clock.month_start(today), tomorrow
    if period == "30d":
        return today - timedelta(days=29), tomorrow
    return None, tomorrow


def item_stats(session: Session, period: str, now: datetime) -> dict[str, Any]:
    start, end = _period_range(period, now.date())
    sales = (
        select(
            OrderItem.item_id.label("item_id"),
            func.sum(OrderItem.qty).label("qty"),
            func.count(func.distinct(OrderItem.order_id)).label("orders"),
            func.sum(OrderItem.qty * OrderItem.price).label("revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*_paid_between(start, end))
        .group_by(OrderItem.item_id)
        .subquery()
    )
    rows = session.execute(
        select(
            Item.id,
            Item.code,
            Item.name,
            Category.name,
            Item.price,
            Item.cost,
            Item.active,
            func.coalesce(sales.c.qty, 0),
            func.coalesce(sales.c.orders, 0),
            func.coalesce(sales.c.revenue, 0.0),
        )
        .join(Category, Category.id == Item.category_id)
        .outerjoin(sales, sales.c.item_id == Item.id)
        .order_by(Item.sort, Item.id)
    ).all()
    total_revenue = sum(float(r[9]) for r in rows)
    items: list[dict[str, Any]] = [
        {
            "id": iid,
            "code": code,
            "name": name,
            "category": category,
            "price": price,
            "cost": cost,
            "active": bool(active),
            "qty": int(qty),
            "orders": int(orders),
            "revenue": money(float(revenue)),
            "share": money(float(revenue) / total_revenue * 100) if total_revenue else 0,
            "margin": money((price - cost) / price * 100) if cost > 0 and price else None,
        }
        for iid, code, name, category, price, cost, active, qty, orders, revenue in rows
    ]
    items.sort(key=lambda r: (-r["revenue"], -r["qty"]))
    sold = [r for r in items if r["qty"] > 0]

    def by(key: str) -> list[dict[str, Any]]:
        return sorted(sold, key=lambda r: -r[key])

    return {
        "period": period,
        "from": start.isoformat() if start else "0000-00-00",
        "to": end.isoformat(),
        "items": items,
        "bestSeller": next(iter(by("revenue")), None),  # most money earned
        "mostPopular": next(iter(by("qty")), None),  # most units sold
        "customerFavourite": next(iter(by("orders")), None),  # in the most separate orders
        "topByRevenue": by("revenue")[:5],
        "topByQty": by("qty")[:5],
        "slowMovers": sorted((r for r in items if r["active"]), key=lambda r: (r["qty"], r["revenue"]))[:5],
    }


# ---------- Day end ----------
def day_end(session: Session, day: date) -> dict[str, Any]:
    nxt = day + timedelta(days=1)
    paid_today = _paid_between(day, nxt)
    revenue, orders = _revenue_between(session, day, nxt)

    line_revenue = func.sum(OrderItem.qty * OrderItem.price)
    item_rows = session.execute(
        select(
            OrderItem.name,
            OrderItem.category,
            func.sum(OrderItem.qty),
            line_revenue,
            func.count(func.distinct(OrderItem.order_id)),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(*paid_today)
        .group_by(OrderItem.name, OrderItem.category)
        .order_by(line_revenue.desc())
    ).all()

    sold_ids = (
        select(OrderItem.item_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(*paid_today, OrderItem.item_id.is_not(None))
    )
    not_sold = session.execute(
        select(Item.name, Category.name)
        .join(Category, Category.id == Item.category_id)
        .where(Item.active.is_(True), Item.id.not_in(sold_ids))
        .order_by(Category.sort, Item.sort, Item.id)
    ).all()

    pay_rows = session.execute(
        select(Order.payment_method, func.sum(Order.total), func.count(Order.id))
        .where(*paid_today)
        .group_by(Order.payment_method)
    ).all()

    start, end = clock.day_bounds(day)
    cancelled = session.execute(
        select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0.0)).where(
            Order.status == "cancelled", Order.created_at >= start, Order.created_at < end
        )
    ).one()

    return {
        "date": day.isoformat(),
        "revenue": money(revenue),
        "orders": orders,
        "aov": money(revenue / orders) if orders else 0,
        "items": [
            {"name": n, "category": c, "qty": int(q), "revenue": money(r), "orders": int(o)}
            for n, c, q, r, o in item_rows
        ],
        "notSold": [{"name": n, "category": c} for n, c in not_sold],
        "payments": [{"method": m, "amount": money(a), "orders": int(o)} for m, a, o in pay_rows],
        "cancelled": {"n": int(cancelled[0]), "amount": money(float(cancelled[1]))},
    }
