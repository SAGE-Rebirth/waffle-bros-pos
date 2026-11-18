"""Pure monthly-target maths (no database), so the numbers on the Dashboard are easy to test.

Ported from the original ``targetSummary()`` in the Node server. Money is rounded to 2 dp the way
the Node code did (``Math.round((n + EPSILON) * 100) / 100``: halves round up).
"""

import math
import sys
from dataclasses import dataclass
from typing import TypedDict

_EPS = sys.float_info.epsilon


def js_round(x: float) -> int:
    """JavaScript ``Math.round``: halves go towards +infinity (Python's ``round`` goes to even)."""
    return math.floor(x + 0.5)


def money(x: float) -> float:
    """Round to 2 dp like the Node ``round()`` helper; ``+ 0.0`` turns ``-0.0`` into ``0.0``."""
    return math.floor((x + _EPS) * 100 + 0.5) / 100 + 0.0


@dataclass(frozen=True)
class TargetInput:
    target: float
    days_in_month: int
    day_of_month: int  # 1-based, today
    revenue_before_today: float  # this month, up to the start of today
    revenue_today: float
    orders_mtd: int  # including today
    trading_days_before_today: int  # completed days since the first sale this month
    expenses_total: float  # everything counted against this month (recurring + one-off)

    @property
    def revenue_mtd(self) -> float:
        return self.revenue_before_today + self.revenue_today

    @property
    def days_left(self) -> int:
        """Days left in the month, including today."""
        return self.days_in_month - self.day_of_month + 1


# camelCase keys, exactly as the front end reads them.
class TargetNumbers(TypedDict):
    progressPct: float
    expectedPct: float
    remaining: float
    evenDailyTarget: float
    todayTarget: float
    todayPct: float
    todayRemaining: float
    requiredDailyFromTomorrow: float
    avgDaily: float
    projected: float
    aov: float
    ordersNeededToday: int | None
    netProfit: float
    breakEvenDaily: float
    breakEvenRemainingDaily: float


def compute(t: TargetInput) -> TargetNumbers:
    dim = t.days_in_month
    days_left = t.days_left
    mtd = t.revenue_mtd

    remaining = max(0.0, t.target - mtd)
    # What today needs to bring in, fixed from the start of the day so it doesn't drift while billing.
    needed_today = max(0.0, (t.target - t.revenue_before_today) / days_left)
    required_after_today = max(0.0, (t.target - mtd) / (days_left - 1)) if days_left > 1 else remaining
    # Average over trading days (from the first sale), so a mid-month opening isn't diluted by empty days.
    avg_daily = (
        t.revenue_before_today / t.trading_days_before_today
        if t.trading_days_before_today > 0
        else t.revenue_today
    )
    projected = t.revenue_before_today + avg_daily * days_left
    aov = mtd / t.orders_mtd if t.orders_mtd else 0.0
    today_remaining = max(0.0, needed_today - t.revenue_today)

    return {
        "progressPct": money(mtd / t.target * 100) if t.target else 0.0,
        "expectedPct": money(t.day_of_month / dim * 100),  # where an even pace puts you by end of today
        "remaining": money(remaining),
        "evenDailyTarget": money(t.target / dim),
        "todayTarget": money(needed_today),
        "todayPct": money(t.revenue_today / needed_today * 100) if needed_today else 100.0,
        "todayRemaining": money(today_remaining),
        "requiredDailyFromTomorrow": money(required_after_today),
        "avgDaily": money(avg_daily),
        "projected": money(projected),
        "aov": money(aov),
        "ordersNeededToday": math.ceil(today_remaining / aov) if aov else None,
        "netProfit": money(mtd - t.expenses_total),
        "breakEvenDaily": money(t.expenses_total / dim),
        # Revenue needed per day for the rest of the month to cover all logged expenses.
        "breakEvenRemainingDaily": money(max(0.0, t.expenses_total - mtd) / days_left),
    }
