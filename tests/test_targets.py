"""Pure target maths (no database) and the rupee formatter."""

from dataclasses import replace

import pytest

from waffle_pos.services.fmt import group_indian, inr, num
from waffle_pos.services.targets import TargetInput, compute, js_round, money

BASE = TargetInput(
    target=100_000,
    days_in_month=30,
    day_of_month=16,
    revenue_before_today=30_000,
    revenue_today=1_000,
    orders_mtd=151,
    trading_days_before_today=15,
    expenses_total=0,
)


def test_start_of_month_with_no_sales() -> None:
    t = compute(
        replace(
            BASE,
            day_of_month=1,
            revenue_before_today=0,
            revenue_today=0,
            orders_mtd=0,
            trading_days_before_today=0,
        )
    )
    assert t["progressPct"] == 0
    assert t["expectedPct"] == 3.33
    assert t["remaining"] == 100_000
    assert t["evenDailyTarget"] == 3333.33
    assert t["todayTarget"] == 3333.33  # target spread over all 30 days, today included
    assert t["todayPct"] == 0
    assert t["todayRemaining"] == 3333.33
    assert t["requiredDailyFromTomorrow"] == 3448.28  # 100000 / 29
    assert t["avgDaily"] == 0
    assert t["projected"] == 0
    assert t["aov"] == 0
    assert t["ordersNeededToday"] is None  # no average bill yet
    assert t["netProfit"] == 0
    assert t["breakEvenDaily"] == 0
    assert t["breakEvenRemainingDaily"] == 0


def test_first_day_avg_uses_today_until_a_day_is_complete() -> None:
    t = compute(
        replace(BASE, day_of_month=1, revenue_before_today=0, trading_days_before_today=0, orders_mtd=5)
    )
    assert t["avgDaily"] == 1000
    assert t["projected"] == 30_000  # 1000/day x 30 days left including today


def test_mid_month_behind() -> None:
    t = compute(BASE)
    # Day 16 of 30: 15 days left including today, so today needs (100000 - 30000) / 15.
    assert t["remaining"] == 69_000
    assert t["progressPct"] == 31
    assert t["expectedPct"] == 53.33
    assert t["todayTarget"] == 4666.67
    assert t["todayPct"] == 21.43
    assert t["todayRemaining"] == 3666.67
    assert t["requiredDailyFromTomorrow"] == 4928.57  # 69000 / 14
    assert t["avgDaily"] == 2000
    assert t["projected"] == 60_000  # 30000 + 2000 x 15
    assert t["aov"] == 205.3
    assert t["ordersNeededToday"] == 18  # ceil(3666.67 / 205.30)


def test_today_target_is_fixed_for_the_day() -> None:
    """Billing more today must not move today's target (it's set from revenue before today)."""
    early = compute(replace(BASE, revenue_today=0))
    late = compute(replace(BASE, revenue_today=4000))
    assert early["todayTarget"] == late["todayTarget"] == 4666.67
    assert late["todayRemaining"] == 666.67
    assert late["requiredDailyFromTomorrow"] < early["requiredDailyFromTomorrow"]


def test_mid_month_ahead() -> None:
    t = compute(replace(BASE, revenue_before_today=60_000, revenue_today=5_000, orders_mtd=300))
    assert t["projected"] == 120_000  # 60000 + 4000 x 15
    assert t["todayTarget"] == 2666.67
    assert t["todayPct"] == 187.5
    assert t["todayRemaining"] == 0
    assert t["ordersNeededToday"] == 0
    assert t["requiredDailyFromTomorrow"] == 2500  # 35000 / 14
    assert t["progressPct"] == 65


def test_mid_month_opening_averages_over_trading_days_only() -> None:
    t = compute(replace(BASE, trading_days_before_today=5))
    assert t["avgDaily"] == 6000
    assert t["projected"] == 120_000


def test_target_already_reached() -> None:
    t = compute(replace(BASE, revenue_before_today=100_000, revenue_today=2_000, orders_mtd=500))
    assert t["remaining"] == 0
    assert t["progressPct"] == 102
    assert t["todayTarget"] == 0
    assert t["todayPct"] == 100  # nothing needed today counts as done
    assert t["todayRemaining"] == 0
    assert t["requiredDailyFromTomorrow"] == 0
    assert t["ordersNeededToday"] == 0


def test_last_day_of_month() -> None:
    t = compute(
        replace(
            BASE,
            days_in_month=31,
            day_of_month=31,
            revenue_before_today=90_000,
            revenue_today=4_000,
            orders_mtd=470,
            trading_days_before_today=30,
        )
    )
    assert t["expectedPct"] == 100
    assert t["remaining"] == 6000
    assert t["todayTarget"] == 10_000
    assert t["todayRemaining"] == 6000
    assert t["requiredDailyFromTomorrow"] == 6000  # no tomorrow: falls back to what's remaining
    assert t["projected"] == 93_000


def test_zero_orders_and_zero_target() -> None:
    t = compute(replace(BASE, target=0, revenue_before_today=0, revenue_today=0, orders_mtd=0))
    assert t["progressPct"] == 0
    assert t["todayTarget"] == 0
    assert t["todayPct"] == 100
    assert t["aov"] == 0
    assert t["ordersNeededToday"] is None


def test_expenses_more_than_revenue() -> None:
    t = compute(replace(BASE, expenses_total=50_000))
    assert t["netProfit"] == -19_000
    assert t["breakEvenDaily"] == 1666.67
    assert t["breakEvenRemainingDaily"] == 1266.67  # 19000 / 15 days left


def test_expenses_covered() -> None:
    t = compute(replace(BASE, expenses_total=20_000))
    assert t["netProfit"] == 11_000
    assert t["breakEvenRemainingDaily"] == 0


def test_days_left_includes_today() -> None:
    assert BASE.days_left == 15
    assert BASE.revenue_mtd == 31_000


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1.005, 1.01), (2.675, 2.68), (1.234, 1.23), (-0.0, 0.0), (0.1 + 0.2, 0.3), (-1.005, -1.0)],
)
def test_money_rounds_halves_up_like_node(value: float, expected: float) -> None:
    assert money(value) == expected


def test_js_round() -> None:
    assert js_round(2.5) == 3
    assert js_round(-2.5) == -2
    assert js_round(2.49) == 2


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "₹0"),
        (999, "₹999"),
        (1000, "₹1,000"),
        (99_999.6, "₹1,00,000"),
        (100_000, "₹1,00,000"),
        (1_234_567, "₹12,34,567"),
        (12_345_678, "₹1,23,45,678"),
        (-1500, "\u2212₹1,500"),
    ],
)
def test_inr_uses_lakh_grouping(amount: float, expected: str) -> None:
    assert inr(amount) == expected


def test_group_indian_and_num() -> None:
    assert group_indian(123456) == "1,23,456"
    assert num(12.0) == "12"
    assert num(47.48) == "47.48"
