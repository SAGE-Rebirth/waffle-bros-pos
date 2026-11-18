"""Google Sheets sync.

Pushes new orders, order items and expenses as rows, and rewrites a "Daily" summary tab, so the
numbers can be reviewed outside the shop.

Setup (once): create a Google Cloud service account, download its JSON key, share the spreadsheet
with the service account's email as Editor, then fill in Settings -> Google Sheet in the POS.

The service-account JWT is signed with google-auth; every HTTP call goes through httpx. Database
work happens in short synchronous sections (SQLite is local and fast), never across a network call.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from google.auth import crypt
from google.auth import jwt as google_jwt
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload, sessionmaker

from waffle_pos import clock
from waffle_pos.db.models import Expense, Order
from waffle_pos.db.session import session_scope
from waffle_pos.schemas import SyncResult
from waffle_pos.services.settings import get_settings, set_settings

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - a public endpoint, not a secret
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
ORDER_BATCH = 500  # rows per run, so one huge backlog can't time out a sync
DAILY_DAYS = 90
TOKEN_REFRESH_MARGIN = 60.0  # seconds before expiry to fetch a fresh token
HTTP_TIMEOUT = 30.0

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
}

Cell = str | int | float
Row = list[Cell]


class SheetsError(RuntimeError):
    """Sync failed: bad credentials file, Google refused the login, or a Sheets API call failed."""


@dataclass
class _Token:
    value: str
    expires_at: float  # time.time() seconds


_token_cache: dict[tuple[str, str], _Token] = {}


def clear_token_cache() -> None:
    _token_cache.clear()


def _round_half_up(x: float) -> int:
    """Match JavaScript's Math.round, which the old sheet used (Python's round() is banker's)."""
    return math.floor(x + 0.5)


def _load_credentials(path: str) -> dict[str, Any]:
    try:
        info = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise SheetsError(f"Credentials file not found: {path}") from e
    except (OSError, ValueError) as e:
        raise SheetsError(f"Could not read credentials file {path}: {e}") from e
    if not isinstance(info, dict) or not info.get("client_email") or not info.get("private_key"):
        raise SheetsError(f"{path} is not a service-account key (needs client_email and private_key)")
    return info


async def _access_token(client: httpx.AsyncClient, credentials_path: str) -> str:
    info = _load_credentials(credentials_path)
    token_uri = str(info.get("token_uri") or DEFAULT_TOKEN_URI)
    cache_key = (str(info["client_email"]), token_uri)
    cached = _token_cache.get(cache_key)
    if cached and cached.expires_at > time.time() + TOKEN_REFRESH_MARGIN:
        return cached.value

    try:
        signer = crypt.RSASigner.from_service_account_info(info)  # type: ignore[no-untyped-call]
    except (ValueError, KeyError) as e:
        raise SheetsError(f"The private key in {credentials_path} is not valid: {e}") from e
    issued = int(time.time())
    claims = {
        "iss": info["client_email"],
        "scope": SCOPE,
        "aud": token_uri,
        "iat": issued,
        "exp": issued + 3600,
    }
    jwt_bytes: bytes = google_jwt.encode(signer, claims)  # type: ignore[no-untyped-call]
    assertion = jwt_bytes.decode("ascii")

    try:
        res = await client.post(token_uri, data={"grant_type": JWT_BEARER_GRANT, "assertion": assertion})
    except httpx.HTTPError as e:
        raise SheetsError(f"Could not reach Google to sign in: {e}") from e
    if res.is_error:
        raise SheetsError(f"Google auth failed: {res.status_code} {res.text}")
    body = res.json()
    token = _Token(
        value=str(body["access_token"]), expires_at=time.time() + float(body.get("expires_in", 3600))
    )
    _token_cache[cache_key] = token
    return token.value


class _SheetsApi:
    def __init__(self, client: httpx.AsyncClient, token: str, spreadsheet_id: str) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}
        self.base = f"{SHEETS_API}/{spreadsheet_id}"

    async def call(
        self, method: str, path: str, *, params: dict[str, str] | None = None, body: Any = None
    ) -> Any:
        try:
            res = await self.client.request(
                method, self.base + path, params=params, json=body, headers=self.headers
            )
        except httpx.HTTPError as e:
            raise SheetsError(f"Could not reach Google Sheets: {e}") from e
        if res.is_error:
            raise SheetsError(f"Sheets API {method} {path}: {res.status_code} {res.text}")
        return res.json() if res.content else {}

    async def ensure_tabs(self) -> None:
        meta = await self.call("GET", "", params={"fields": "sheets.properties.title"})
        have = {s["properties"]["title"] for s in meta.get("sheets", [])}
        missing = [t for t in TABS if t not in have]
        if not missing:
            return
        await self.call(
            "POST",
            ":batchUpdate",
            body={"requests": [{"addSheet": {"properties": {"title": t}}} for t in missing]},
        )
        for tab in missing:
            await self.call(
                "PUT", f"/values/{tab}!A1", params={"valueInputOption": "RAW"}, body={"values": [TABS[tab]]}
            )

    async def append(self, tab: str, rows: list[Row]) -> None:
        if rows:
            await self.call(
                "POST",
                f"/values/{tab}!A1:append",
                params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
                body={"values": rows},
            )

    async def replace_daily(self, rows: list[Row]) -> None:
        await self.call("POST", "/values/Daily!A2:E1000:clear", body={})
        if rows:
            await self.call(
                "PUT", "/values/Daily!A2", params={"valueInputOption": "USER_ENTERED"}, body={"values": rows}
            )


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
    """Push unsynced orders and expenses to the configured Google Sheet.

    Returns a skipped result when sync is off and ``ok=False`` when it isn't configured yet.
    Raises :class:`SheetsError` when the credentials, Google sign-in or a Sheets call fail; rows
    are only marked synced after Google has accepted them.
    """
    with session_scope(session_factory) as session:
        settings = get_settings(session)
    if settings.get("sheets_enabled") != "1":
        return SyncResult(ok=False, skipped=True, message="Google Sheet sync is turned off in Settings.")
    spreadsheet_id = settings.get("sheets_spreadsheet_id", "").strip()
    credentials_path = settings.get("sheets_credentials_path", "").strip()
    if not spreadsheet_id or not credentials_path:
        return SyncResult(ok=False, message="Add the spreadsheet ID and credentials file path in Settings.")

    own_client = client is None
    http = client or httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    try:
        api = _SheetsApi(http, await _access_token(http, credentials_path), spreadsheet_id)
        await api.ensure_tabs()

        with session_scope(session_factory) as session:
            order_ids, order_rows, item_rows = _order_rows(session)
        await api.append("Orders", order_rows)
        await api.append("OrderItems", item_rows)
        _mark_synced(session_factory, Order, order_ids)

        with session_scope(session_factory) as session:
            expense_ids, expense_rows = _expense_rows(session)
        await api.append("Expenses", expense_rows)
        _mark_synced(session_factory, Expense, expense_ids)

        now = clock.now()
        with session_scope(session_factory) as session:
            daily = _daily_rows(session, now)
        await api.replace_daily(daily)
    finally:
        if own_client:
            await http.aclose()

    at = f"{clock.now():%Y-%m-%d %H:%M:%S}"
    with session_scope(session_factory) as session:
        set_settings(session, {"sheets_last_sync": at})
    return SyncResult(
        ok=True, message=f"Synced {len(order_ids)} orders and {len(expense_ids)} expenses.", at=at
    )


async def sync_loop(
    session_factory: sessionmaker[Session], interval_seconds: int, *, initial_delay: float = 10.0
) -> None:
    """Sync in the background forever. Failures are logged and retried next round, never raised."""
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
            await asyncio.sleep(max(interval_seconds, 1))
