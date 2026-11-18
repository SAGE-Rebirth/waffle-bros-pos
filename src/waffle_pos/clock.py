"""Shop-local time.

Every timestamp is stored as a naive datetime in the shop's time zone (Asia/Kolkata by default),
so "today", "this hour" and "this month" mean what the owner expects, whatever the computer's own
clock zone is.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from waffle_pos.config import get_config


def now() -> datetime:
    return datetime.now(ZoneInfo(get_config().timezone)).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_start(d: date) -> date:
    return d.replace(day=1)


def next_month_start(d: date) -> date:
    return date(d.year + (d.month == 12), d.month % 12 + 1, 1)


def days_in_month(d: date) -> int:
    return (next_month_start(d) - month_start(d)).days


def parse_month(key: str) -> date:
    year, month = key.split("-")
    return date(int(year), int(month), 1)


def start_of_week(d: date) -> date:
    """Monday of the week containing ``d``."""
    return d - timedelta(days=d.weekday())


def day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=1)
