"""Read-only analytics endpoints. Response shapes are documented in services/analytics.py and docs/API.md."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query

from waffle_pos import clock
from waffle_pos.api.deps import DB, INVALID, errors
from waffle_pos.schemas import Period
from waffle_pos.services import analytics, insights

router = APIRouter(prefix="/api", tags=["dashboard"])

PeriodQuery = Annotated[
    Period,
    Query(
        description="Window for the item stats: `today`, `week` (last 7 days incl. today), "
        "`month` (this calendar month to date), `30d` (last 30 days incl. today) or `all`."
    ),
]

_ITEM_STATS_KEYS = (
    "`period`, `from`, `to` (shop-local dates; `to` is exclusive, `from` is `0000-00-00` for `all`), "
    "`items` (every menu item with `qty`, `orders`, `revenue`, `share` % of item revenue and `margin` % "
    "or null), `bestSeller` (most revenue), `mostPopular` (most units), `customerFavourite` (in the most "
    "bills), `topByRevenue`, `topByQty` (top 5 each) and `slowMovers` (5 active items selling least)."
)


@router.get(
    "/dashboard",
    summary="Everything the Dashboard page shows",
    responses=errors({422: INVALID}),
)
def dashboard(db: DB, period: PeriodQuery = "month") -> dict[str, Any]:
    """One call for the whole Dashboard, computed for the shop-local *now*. Only paid bills count;
    all money is rupees rounded to 2 dp. Keys (full field list and formulas in docs/API.md):

    - `now`, `today`: the shop-local time and date the numbers were computed for.
    - `target`: this month's target summary: `month`, `target`, `revenue`, `orders`,
      `todayRevenue`, `progressPct`, `expectedPct`, `remaining`, `todayTarget`,
      `requiredDailyFromTomorrow`, `avgDaily`, `projected`, `aov`, `netProfit`, break-even figures
      and an `expenses` breakdown.
    - `charts`: arrays `hourly` (today vs 28-day average), `daily` (this month, with even-pace line),
      `weekly` (12 weeks), `monthly` (12 months with target and expenses), `categorySplit`,
      `paymentSplit` and `weekday` (8-week average per weekday).
    - `insights`: plain-English tips, each `{tone: good|warn|info, title, text}`.
    - `items`: the same object as `GET /api/items/stats` for `period`.
    """
    now = clock.now()
    return {
        "now": now.isoformat(),
        "today": now.date().isoformat(),
        "target": analytics.target_summary(db, now),
        "charts": analytics.charts(db, now),
        "insights": insights.insights(db, now),
        "items": analytics.item_stats(db, period, now),
    }


@router.get(
    "/items/stats",
    summary="Menu item performance",
    description="How each menu item sold over a period (paid bills only, rupees). Keys: "
    + _ITEM_STATS_KEYS
    + " See docs/API.md.",
    responses=errors({422: INVALID}),
)
def item_stats(db: DB, period: PeriodQuery = "month") -> dict[str, Any]:
    return analytics.item_stats(db, period, clock.now())


@router.get("/calendar", summary="Sales calendar for one month", responses=errors({422: INVALID}))
def calendar(
    db: DB,
    month: Annotated[
        str | None,
        Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="`YYYY-MM`. Defaults to this month."),
    ] = None,
) -> dict[str, Any]:
    """Paid sales for every shop-local day of a month, for the Day End calendar. Keys: `month`,
    `today` (shop-local date), `target` and `dailyTarget` (even pace for that month), `revenue` and
    `orders` (month totals, paid bills), `tradingDays` (days with a paid bill), `bestDay` (date or
    null) and `days`: one entry per day with `date`, `day`, `weekday`, `revenue`, `orders`,
    `cancelled` (bills cancelled that day), `today` and `future` (figures are null for future days).
    """
    today = clock.today()
    return analytics.calendar(db, month or clock.month_key(today), today)


@router.get("/day-end", summary="Day-end closing sheet", responses=errors({422: INVALID}))
def day_end(
    db: DB,
    date: Annotated[
        date | None, Query(description="Shop-local day, `YYYY-MM-DD`. Defaults to today.")
    ] = None,
) -> dict[str, Any]:
    """The cash-up summary for one day (see docs/API.md). Keys: `date`, `revenue` and `orders` (paid
    bills), `aov` (revenue / orders), `items` (sold items by revenue: `name`, `category`, `qty`,
    `revenue`, `orders`), `notSold` (active items with no sale: `name`, `category`), `payments`
    (`method`, `amount`, `orders` per payment method) and `cancelled` (`n` bills, `amount` rupees).
    """
    return analytics.day_end(db, date or clock.today())
