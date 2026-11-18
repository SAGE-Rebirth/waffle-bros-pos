"""Read-only analytics endpoints. Response shapes are documented in services/analytics.py."""

from datetime import date
from typing import Any

from fastapi import APIRouter

from waffle_pos import clock
from waffle_pos.api.deps import DB
from waffle_pos.schemas import Period
from waffle_pos.services import analytics, insights

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard(db: DB, period: Period = "month") -> dict[str, Any]:
    now = clock.now()
    return {
        "target": analytics.target_summary(db, now),
        "charts": analytics.charts(db, now),
        "insights": insights.insights(db, now),
        "items": analytics.item_stats(db, period, now),
    }


@router.get("/items/stats")
def item_stats(db: DB, period: Period = "month") -> dict[str, Any]:
    return analytics.item_stats(db, period, clock.now())


@router.get("/day-end")
def day_end(db: DB, date: date | None = None) -> dict[str, Any]:
    return analytics.day_end(db, date or clock.today())
