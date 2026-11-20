"""Read-only analytics endpoints. Response shapes are documented in services/analytics.py and docs/API.md."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query

from waffle_pos import clock
from waffle_pos.api.deps import DB, INVALID, bad_request, errors
from waffle_pos.api.finance import BAD_MONTH, MONTH_RE
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
    "`bills` (paid bills in the period), `revenue` (item revenue in the period), "
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

    - `target`: this month's target summary: `month`, `target`, `revenue`, `orders`,
      `todayRevenue`, `progressPct`, `expectedPct`, `remaining`, `todayTarget`,
      `requiredDailyFromTomorrow`, `avgDaily`, `projected`, `aov`, `netProfit`, break-even figures
      and an `expenses` breakdown.
    - `charts`: arrays `hourly` (today vs 28-day average), `daily` (this month, with even-pace line),
      `weekly` (up to 12 weeks, each with `label` like `16-22 Nov` and `current`), `monthly` (up to
      12 months with target, expenses, `label` like `Nov 2026` and `current`), `categorySplit`,
      `paymentSplit` and `weekday` (8-week average per weekday).
    - `insights`: plain-English tips, each `{tone: good|warn|info, title, text}`.
    - `items`: the same object as `GET /api/items/stats` for `period`.
    - `now`: the shop-local time the numbers were worked out for (`YYYY-MM-DDTHH:MM:SS`), so the
      screens show the shop's clock even if a tablet's own clock or time zone is off.
    """
    now = clock.now()
    return {
        "now": now.isoformat(),
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


@router.get(
    "/calendar",
    summary="A month of daily sales, for the calendar",
    responses=errors({400: BAD_MONTH, 422: INVALID}),
)
def calendar(
    db: DB,
    month: Annotated[
        str | None, Query(description="The month, `YYYY-MM`. Defaults to the current month.")
    ] = None,
) -> dict[str, Any]:
    """Every day of one month with its paid sales, for the Dashboard calendar (see docs/API.md).
    Keys: `month`, `today`, `target` and `dailyTarget` (target / days in month), `revenue`,
    `orders`, `tradingDays` (days with a sale), `avgDaily` (per trading day), `bestDay` (date or
    null), `firstSale` (date of the shop's first paid bill or null) and `days`: one entry per day
    with `date`, `day`, `weekday` (0 = Monday), `revenue`, `orders`, `cancelled` (all null for days
    after today), `future` and `today`.
    """
    if month is not None and not MONTH_RE.match(month):
        raise bad_request("Enter a valid month (YYYY-MM)")
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
