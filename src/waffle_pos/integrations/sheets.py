"""Google Sheet sync through a Google Apps Script web app.

The owner pastes ``integrations/apps_script.gs`` into the spreadsheet (Extensions -> Apps Script),
sets the same secret there as in Admin -> Modules -> Google Sheet sync, and deploys it as a web app.
Each sync POSTs one JSON payload to that web app: new orders, order items and expenses to append,
and the Daily, Items and Monthly summary tabs to rewrite. Other tabs (such as an Overview tab with
charts) are never touched. No Google Cloud project or service-account key is needed.

Every HTTP call goes through httpx. Database work happens in short synchronous sections (SQLite is
local and fast), never across a network call. Rows are marked synced only after the script
confirms it wrote them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from importlib import resources
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload, sessionmaker

from waffle_pos import clock
from waffle_pos.db.models import Expense, Order
from waffle_pos.db.session import session_scope
from waffle_pos.modules.builtin import WEB_APP_URL_RE, GoogleSheetsSettings
from waffle_pos.modules.registry import is_enabled, settings_of, store_internal
from waffle_pos.schemas import SyncResult
from waffle_pos.services import analytics
from waffle_pos.services.targets import money

logger = logging.getLogger(__name__)

ORDER_BATCH = 500  # rows per run, so one huge backlog can't time out a sync
DAILY_DAYS = 90
HTTP_TIMEOUT = 60.0  # Apps Script can take a few seconds to start

TABS: dict[str, list[str]] = {
    "Orders": [
        "Bill No",
        "Date",
        "Time",
        "Items",
        "Subtotal",
        "Discount",
        "Tax",
        "Total",
        "Payment",
        "Order Type",
        "Source",
        "Status",
        "Customer",
        "Phone",
    ],
    "OrderItems": ["Bill No", "Date", "Time", "Item", "Category", "Price", "Qty", "Line Total"],
    "Expenses": ["Date", "Category", "Amount", "Recurring", "Note"],
    "Daily": ["Date", "Revenue", "Orders", "Avg Bill", "Top Item"],
    "Items": [
        "Code",
        "Item",
        "Category",
        "Price",
        "Cost",
        "Margin %",
        "Qty (30 days)",
        "Bills (30 days)",
        "Revenue (30 days)",
        "Share %",
        "On Menu",
    ],
    "Monthly": [
        "Month",
        "Target",
        "Revenue",
        "Orders",
        "Avg Bill",
        "% of Target",
        "Expenses",
        "Net Profit",
    ],
}
"""Tabs the sync writes. Orders, OrderItems and Expenses only ever get new rows appended;
Daily, Items and Monthly are summaries rewritten in full on every sync."""

Cell = str | int | float
Row = list[Cell]


class SheetsError(RuntimeError):
    """Sync failed: the web app could not be reached, refused the secret, or reported an error."""


SECRET_LINE = "const SECRET = 'PASTE_THE_SECRET_FROM_THE_POS';"  # noqa: S105 - a placeholder


def apps_script_source(secret: str = "") -> str:
    """The Apps Script the owner pastes into the spreadsheet (also shown in docs/README). With a
    ``secret``, it is filled in, so the owner doesn't have to edit the script by hand."""
    src = resources.files("waffle_pos.integrations").joinpath("apps_script.gs").read_text("utf-8")
    if secret:
        # json.dumps gives a safe JavaScript string literal (quotes, backslashes, U+2028 escaped).
        src = src.replace(SECRET_LINE, f"const SECRET = {json.dumps(secret)};", 1)
    return src


def _round_half_up(x: float) -> int:
    """Match JavaScript's Math.round, which the old sheet used (Python's round() is banker's)."""
    return math.floor(x + 0.5)


# Leading tab / carriage return can also start a formula once pasted (OWASP CSV injection list).
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: Cell) -> Cell:
    """Text typed at the counter (customer name, note) must never run as a formula in the sheet,
    e.g. ``=IMPORTDATA(...)``. A leading apostrophe makes Sheets keep it as plain text."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        try:
            float(value)
        except ValueError:
            return "'" + value
    return value


def _tab(name: str, mode: str, rows: list[Row]) -> dict[str, Any]:
    return {"name": name, "mode": mode, "header": TABS[name], "rows": [[_cell(c) for c in r] for r in rows]}


async def _post(client: httpx.AsyncClient, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the web app. Apps Script answers with a redirect to the JSON result, which httpx
    follows as a GET; an error page or a non-JSON answer means the script isn't deployed right."""
    try:
        res = await client.post(url, json=payload, follow_redirects=True)
    except httpx.HTTPError as e:
        raise SheetsError(f"Could not reach the Google Sheet web app: {e}") from e
    if res.is_error:
        raise SheetsError(f"Google Sheet web app answered {res.status_code}. Check the web app URL.")
    try:
        body = res.json()
    except ValueError as e:
        raise SheetsError(
            "The web app didn't answer with JSON. Check that it is deployed with access "
            "'Anyone' and that the URL ends in /exec."
        ) from e
    if not isinstance(body, dict) or body.get("ok") is not True:
        error = body.get("error") if isinstance(body, dict) else None
        raise SheetsError(f"The Google Sheet script reported: {error or 'an unknown error'}")
    return body


# ---------- Rows (sync DB sections) ----------
def _order_rows(session: Session) -> tuple[list[int], list[Row], list[Row]]:
    orders = session.scalars(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.synced.is_(False))
        .order_by(Order.id)
        .limit(ORDER_BATCH)
    ).all()
    order_rows: list[Row] = []
    item_rows: list[Row] = []
    for o in orders:
        d, t = f"{o.created_at:%Y-%m-%d}", f"{o.created_at:%H:%M:%S}"
        order_rows.append([
            o.bill_no, d, t, ", ".join(f"{i.name} x{i.qty}" for i in o.items),
            o.subtotal, o.discount, o.tax, o.total, o.payment_method, o.order_type, o.source, o.status,
            o.customer_name or "", o.customer_phone or "",
        ])  # fmt: skip
        item_rows.extend(
            [o.bill_no, d, t, i.name, i.category, i.price, i.qty, i.price * i.qty] for i in o.items
        )
    return [o.id for o in orders], order_rows, item_rows


def _expense_rows(session: Session) -> tuple[list[int], list[Row]]:
    expenses = session.scalars(select(Expense).where(Expense.synced.is_(False)).order_by(Expense.id)).all()
    rows: list[Row] = [
        [e.date.isoformat(), e.category, e.amount, "Monthly" if e.recurring else "One-off", e.note or ""]
        for e in expenses
    ]
    return [e.id for e in expenses], rows


def _daily_rows(session: Session, now: datetime) -> list[Row]:
    """Last 90 days of paid sales, one row per day with its best-selling item."""
    since = datetime.combine(now.date() - timedelta(days=DAILY_DAYS - 1), datetime.min.time())
    orders = session.scalars(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.status == "paid", Order.created_at >= since)
        .order_by(Order.created_at)
    ).all()
    revenue: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    qty: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for o in orders:
        day = f"{o.created_at:%Y-%m-%d}"
        revenue[day] += o.total
        count[day] += 1
        for i in o.items:
            qty[day][i.name] += i.qty
    rows: list[Row] = []
    for day in sorted(revenue):
        top = min(qty[day].items(), key=lambda kv: (-kv[1], kv[0]))[0] if qty[day] else ""
        rows.append(
            [day, _round_half_up(revenue[day]), count[day], _round_half_up(revenue[day] / count[day]), top]
        )
    return rows


def _item_rows(session: Session, now: datetime) -> list[Row]:
    """Every menu item with its last-30-days sales, best earners first."""
    stats = analytics.item_stats(session, "30d", now)
    return [
        [
            i["code"], i["name"], i["category"], i["price"], i["cost"],
            "" if i["margin"] is None else i["margin"],
            i["qty"], i["orders"], i["revenue"], i["share"], "Yes" if i["active"] else "Hidden",
        ]
        for i in stats["items"]
    ]  # fmt: skip


def _monthly_rows(session: Session, now: datetime) -> list[Row]:
    """The last 12 months: target, revenue, expenses and profit."""
    rows: list[Row] = []
    for m in analytics.monthly_summary(session, now.date()):
        revenue, target, orders = m["revenue"], m["target"], m["orders"]
        rows.append([
            m["key"], target, revenue, orders,
            money(revenue / orders) if orders else 0,
            money(revenue / target * 100) if target else 0,
            m["expenses"], money(revenue - m["expenses"]),
        ])  # fmt: skip
    return rows


def _mark_synced(
    session_factory: sessionmaker[Session], model: type[Order] | type[Expense], ids: list[int]
) -> None:
    if ids:
        with session_scope(session_factory) as session:
            session.execute(update(model).where(model.id.in_(ids)).values(synced=True))


# ---------- Public API ----------
async def sync_now(
    session_factory: sessionmaker[Session], *, client: httpx.AsyncClient | None = None
) -> SyncResult:
    """Push unsynced orders and expenses, and fresh summaries, to the Google Sheet web app.

    Returns a skipped result when sync is off and ``ok=False`` when it isn't configured yet.
    Raises :class:`SheetsError` when the web app can't be reached or reports an error; rows are
    only marked synced after the script has confirmed it wrote them.
    """
    with session_scope(session_factory) as session:
        enabled = is_enabled(session, "google_sheets")
        cfg = settings_of(session, "google_sheets", GoogleSheetsSettings)
    if not enabled:
        return SyncResult(
            ok=False, skipped=True, message="Google Sheet sync is switched off in the admin dashboard."
        )
    url, secret = cfg.web_app_url.strip(), cfg.secret.strip()
    if not url or not secret:
        return SyncResult(
            ok=False, message="Add the web app URL and secret in Admin → Modules → Google Sheet sync."
        )
    if not WEB_APP_URL_RE.match(url):
        return SyncResult(
            ok=False,
            message="The web app URL should look like https://script.google.com/macros/s/.../exec",
        )

    global _running  # noqa: PLW0603 - one sync at a time in this process
    if _running:
        return SyncResult(ok=False, message="A sync is already running. Try again in a moment.")
    _running = True
    try:
        return await _sync(session_factory, client, url, secret)
    finally:
        _running = False


_running = False


async def _sync(
    session_factory: sessionmaker[Session], client: httpx.AsyncClient | None, url: str, secret: str
) -> SyncResult:
    now = clock.now()
    with session_scope(session_factory) as session:
        order_ids, order_rows, item_rows = _order_rows(session)
        expense_ids, expense_rows = _expense_rows(session)
        tabs = [
            _tab("Orders", "append", order_rows),
            _tab("OrderItems", "append", item_rows),
            _tab("Expenses", "append", expense_rows),
            _tab("Daily", "replace", _daily_rows(session, now)),
            _tab("Items", "replace", _item_rows(session, now)),
            _tab("Monthly", "replace", _monthly_rows(session, now)),
        ]

    own_client = client is None
    http = client or httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    try:
        await _post(http, url, {"secret": secret, "tabs": tabs})
    finally:
        if own_client:
            await http.aclose()
    _mark_synced(session_factory, Order, order_ids)
    _mark_synced(session_factory, Expense, expense_ids)

    at = f"{clock.now():%Y-%m-%d %H:%M:%S}"
    with session_scope(session_factory) as session:
        store_internal(session, "google_sheets", {"last_sync": at})
    return SyncResult(
        ok=True, message=f"Synced {len(order_ids)} orders and {len(expense_ids)} expenses.", at=at
    )


async def sync_loop(
    session_factory: sessionmaker[Session],
    interval_seconds: int | None = None,
    *,
    initial_delay: float = 10.0,
) -> None:
    """Sync in the background forever. Failures are logged and retried next round, never raised.

    The interval comes from the module's settings (``interval_minutes``) unless ``interval_seconds``
    is given, so changing it in the admin dashboard takes effect after the current wait.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        await asyncio.sleep(initial_delay)
        while True:
            try:
                result = await sync_now(session_factory, client=client)
                if not result.ok and not result.skipped:
                    logger.warning("[sheets] %s", result.message)
                else:
                    logger.debug("[sheets] %s", result.message)
            except SheetsError as e:
                logger.warning("[sheets] sync failed: %s", e)
            except Exception:
                logger.exception("[sheets] sync failed unexpectedly")
            await asyncio.sleep(max(interval_seconds or _interval_from_settings(session_factory), 1))


def _interval_from_settings(session_factory: sessionmaker[Session]) -> int:
    try:
        with session_scope(session_factory) as session:
            return settings_of(session, "google_sheets", GoogleSheetsSettings).interval_minutes * 60
    except Exception:  # pragma: no cover - never let the loop die over settings
        return 300
