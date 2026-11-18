"""Fill a SEPARATE demo database (``data-demo/``) with ~6 weeks of made-up sales.

Lets you see the dashboard working without touching the real shop data in ``data/``.

    uv run python -m waffle_pos.demo                      # create demo data
    WB_DATA_DIR=data-demo uv run waffle-pos               # run the POS against it (macOS / Linux)
    set "WB_DATA_DIR=data-demo" && uv run waffle-pos      # same, Windows cmd

The random numbers come from the same seeded generator as the old Node demo, so every run
produces the same pattern of sales.
"""

from __future__ import annotations

import math
import os
import shutil
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from waffle_pos import clock
from waffle_pos.config import PROJECT_ROOT, AppConfig
from waffle_pos.db.migrate import upgrade_to_head
from waffle_pos.db.models import Expense, Item
from waffle_pos.db.seed import seed_if_empty
from waffle_pos.db.session import make_engine
from waffle_pos.schemas import OrderCreate, OrderLineIn, OrderType, PaymentMethod
from waffle_pos.services.orders import create_order

DEFAULT_DEMO_DIR = PROJECT_ROOT / "data-demo"
REAL_DATA_DIR = PROJECT_ROOT / "data"

# How often each item sells, relative to the others.
POPULARITY: dict[str, float] = {
    "W01": 6, "W02": 9, "W03": 7, "W04": 8, "W05": 12, "W06": 7, "W07": 4, "W08": 6, "W09": 1,
    "S01": 3, "S02": 5, "S03": 2, "C01": 6, "C02": 4, "C03": 2, "M01": 6, "M02": 5, "M03": 0.6,
}  # fmt: skip
# Quiet lunch, busy evenings.
HOUR_WEIGHTS: list[tuple[int, float]] = [
    (10, 1), (11, 2), (12, 3), (13, 3), (14, 2), (15, 2), (16, 4),
    (17, 6), (18, 8), (19, 10), (20, 10), (21, 8), (22, 5),
]  # fmt: skip
LINES_PER_BILL: list[tuple[int, float]] = [(1, 6), (2, 3), (3, 1)]
QTY_PER_LINE: list[tuple[int, float]] = [(1, 8), (2, 2)]
PAYMENT: list[tuple[PaymentMethod, float]] = [("upi", 7), ("cash", 3), ("card", 0.5)]
ORDER_TYPE: list[tuple[OrderType, float]] = [("dine-in", 5), ("takeaway", 5)]
WEEKDAY_ORDERS, FRIDAY_ORDERS, WEEKEND_ORDERS = 7, 10, 13
GROWTH_DAYS = 120  # sales grow by 1/120 per day, so the trend line slopes up


class Lcg:
    """The Node demo's linear congruential generator, reproduced exactly."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def __call__(self) -> float:
        self.seed = (self.seed * 1664525 + 1013904223) % 4294967296
        return self.seed / 4294967296

    def pick[T](self, weighted: Sequence[tuple[T, float]]) -> T:
        r = self() * sum(w for _, w in weighted)
        for value, weight in weighted:
            r -= weight
            if r <= 0:
                return value
        return weighted[0][0]


def js_round(x: float) -> int:
    """JavaScript's Math.round (half up), to keep the Node demo's numbers."""
    return math.floor(x + 0.5)


def demo_data_dir() -> Path:
    env = os.environ.get("WB_DATA_DIR")
    return Path(env).resolve() if env else DEFAULT_DEMO_DIR


def _orders_for_day(day: date) -> int:
    weekday = day.weekday()  # Monday = 0
    if weekday >= 5:
        return WEEKEND_ORDERS
    return FRIDAY_ORDERS if weekday == 4 else WEEKDAY_ORDERS


def generate_orders(session: Session, rand: Lcg, start: date, now: datetime) -> int:
    weighted_items = [
        (i.id, POPULARITY.get(i.code, 1)) for i in session.scalars(select(Item).order_by(Item.id))
    ]
    orders = 0
    day = start
    while day <= now.date():
        growth = 1 + (day - start).days / GROWTH_DAYS
        n = js_round(_orders_for_day(day) * (0.8 + rand() * 0.4) * growth)
        for _ in range(n):
            hour = rand.pick(HOUR_WEIGHTS)
            when = datetime(
                day.year, day.month, day.day, hour, math.floor(rand() * 60), math.floor(rand() * 60)
            )
            if when > now:
                continue
            lines = [
                OrderLineIn(item_id=rand.pick(weighted_items), qty=rand.pick(QTY_PER_LINE))
                for _ in range(rand.pick(LINES_PER_BILL))
            ]
            data = OrderCreate(
                items=lines,
                payment_method=rand.pick(PAYMENT),
                order_type=rand.pick(ORDER_TYPE),
                discount=20 if rand() < 0.05 else 0,
            )
            create_order(session, data, when=when)
            orders += 1
        day += timedelta(days=1)
    return orders


def generate_expenses(session: Session, rand: Lcg, start: date, today: date) -> None:
    session.add_all(
        [
            Expense(date=start, category="rent", amount=25000, note="Shop rent", recurring=True),
            Expense(date=start, category="salary", amount=24000, note="2 staff", recurring=True),
            Expense(
                date=start, category="electricity", amount=3500, note="Approx. monthly bill", recurring=True
            ),
        ]
    )
    week = start
    while week <= today:
        amount = js_round(9000 + rand() * 3000)
        session.add(Expense(date=week, category="ingredients", amount=amount, note="Weekly stock"))
        if rand() < 0.5:
            amount = js_round(1200 + rand() * 800)
            session.add(Expense(date=week, category="packaging", amount=amount, note="Boxes, forks, tissues"))
        week += timedelta(days=7)
    session.add(
        Expense(
            date=today.replace(day=2),
            category="marketing",
            amount=3000,
            note="Flyers in the apartment complex",
        )
    )
    session.flush()


def main() -> None:
    data_dir = demo_data_dir()
    if data_dir.resolve() == REAL_DATA_DIR.resolve():
        sys.exit(
            f"Refusing to wipe {data_dir}: that is the real shop data. Point WB_DATA_DIR somewhere else."
        )
    shutil.rmtree(data_dir, ignore_errors=True)

    engine = make_engine(AppConfig(data_dir=data_dir, start_sync_loop=False))
    try:
        upgrade_to_head(engine)
        now = clock.now()
        start = clock.month_start(clock.month_start(now.date()) - timedelta(days=1))  # 1st of last month
        rand = Lcg(42)
        with Session(engine) as session:
            seed_if_empty(session)
            orders = generate_orders(session, rand, start, now)
            generate_expenses(session, rand, start, now.date())
            session.commit()
    finally:
        engine.dispose()

    print(f"Demo data ready: {orders} orders since {start.isoformat()} in {data_dir}")
    print(f"Run the POS with this data:  WB_DATA_DIR={data_dir} uv run waffle-pos")
    print(f'  (Windows cmd:  set "WB_DATA_DIR={data_dir}" && uv run waffle-pos)')


if __name__ == "__main__":
    main()
