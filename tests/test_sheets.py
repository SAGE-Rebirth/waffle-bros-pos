"""Google Sheet sync through the Apps Script web app, faked by httpx.MockTransport (no network)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from waffle_pos import clock
from waffle_pos.config import AppConfig
from waffle_pos.db.migrate import upgrade_to_head
from waffle_pos.db.models import Expense, Item, Order
from waffle_pos.db.seed import seed_if_empty
from waffle_pos.db.session import make_engine, make_session_factory, session_scope
from waffle_pos.integrations import sheets
from waffle_pos.modules import registry
from waffle_pos.modules.builtin import GoogleSheetsSettings
from waffle_pos.schemas import OrderCreate, OrderLineIn, SyncResult
from waffle_pos.services.orders import cancel_order, create_order

WEB_APP = "https://script.google.com/macros/s/AKfy-test_123/exec"
ECHO = "https://script.googleusercontent.com/macros/echo?user_content_key=abc"
SECRET = "a-long-shared-secret-123"  # noqa: S105 - test value


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@dataclass
class FakeWebApp:
    """Behaves like the deployed Apps Script: POST answers 302 to an echo URL serving the JSON
    result, and the tabs are kept in memory the way apps_script.gs writes them."""

    secret: str = SECRET
    status: int = 200
    raw_answer: str | None = None  # e.g. an HTML error page
    posts: list[dict[str, Any]] = field(default_factory=list)
    tabs: dict[str, list[list[Any]]] = field(default_factory=dict)  # header row + data rows
    _result: dict[str, Any] = field(default_factory=dict)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == WEB_APP:
            body = json.loads(request.content)
            self.posts.append(body)
            self._result = self._apply(body)
            return httpx.Response(302, headers={"Location": ECHO})
        if request.method == "GET" and url == ECHO:
            if self.status != 200:
                return httpx.Response(self.status, text="Google error page")
            if self.raw_answer is not None:
                return httpx.Response(200, text=self.raw_answer)
            return httpx.Response(200, json=self._result)
        return httpx.Response(404, text=f"unexpected {request.method} {url}")

    def _apply(self, body: dict[str, Any]) -> dict[str, Any]:
        if body.get("secret") != self.secret:
            return {"ok": False, "error": "Wrong secret: it must match the POS admin page"}
        for tab in body["tabs"]:
            sheet = self.tabs.setdefault(tab["name"], [tab["header"]])
            if tab["mode"] == "append":
                sheet.extend(tab["rows"])
            else:
                sheet[1:] = tab["rows"]
        return {"ok": True, "tabs": len(body["tabs"])}

    def rows(self, tab: str) -> list[list[Any]]:
        return self.tabs.get(tab, [[]])[1:]

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def _sync(factory: sessionmaker[Session], fake: FakeWebApp) -> SyncResult:
    async with fake.client() as client:
        return await sheets.sync_now(factory, client=client)


@pytest.fixture
def sheets_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(AppConfig(data_dir=tmp_path / "data", start_sync_loop=False))
    upgrade_to_head(engine)
    with Session(engine) as session:
        seed_if_empty(session)
        session.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def sheets_factory(sheets_engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(sheets_engine)


def _last_sync(session: Session) -> str:
    return registry.settings_of(session, "google_sheets", GoogleSheetsSettings).last_sync


@pytest.fixture
def sheets_enabled(sheets_factory: sessionmaker[Session]) -> sessionmaker[Session]:
    with session_scope(sheets_factory) as session:
        registry.set_enabled(session, "google_sheets", True)
        registry.save_settings(session, "google_sheets", {"web_app_url": WEB_APP, "secret": SECRET})
    return sheets_factory


def _add_sales(factory: sessionmaker[Session]) -> list[str]:
    today = clock.now().replace(hour=12, minute=0, second=0)
    with session_scope(factory) as session:
        ids = {i.code: i.id for i in session.scalars(select(Item))}
        o1 = create_order(
            session,
            OrderCreate(items=[OrderLineIn(item_id=ids["W03"], qty=2), OrderLineIn(item_id=ids["S01"])]),
            when=today,
        )
        o2 = create_order(
            session,
            OrderCreate(items=[OrderLineIn(item_id=ids["W01"])], payment_method="upi", customer_name="Asha"),
            when=today + timedelta(minutes=5),
        )
        o3 = create_order(session, OrderCreate(items=[OrderLineIn(item_id=ids["C05"])]), when=today)
        cancel_order(session, o3.id)
        session.add(Expense(date=date(2026, 1, 1), category="rent", amount=25000, recurring=True))
        session.add(Expense(date=date(2026, 1, 3), category="ingredients", amount=9000, note="Weekly stock"))
        return [o1.bill_no, o2.bill_no, o3.bill_no]


def test_disabled_is_skipped(sheets_factory: sessionmaker[Session]) -> None:
    fake = FakeWebApp()
    result = run(_sync(sheets_factory, fake))
    assert result.skipped and not result.ok
    assert fake.posts == []


def test_enabled_without_config_asks_for_it(sheets_factory: sessionmaker[Session]) -> None:
    with session_scope(sheets_factory) as session:
        registry.set_enabled(session, "google_sheets", True)
    fake = FakeWebApp()
    result = run(_sync(sheets_factory, fake))
    assert not result.ok and not result.skipped
    assert "web app URL and secret" in result.message
    assert fake.posts == []


def test_settings_reject_other_urls_and_short_secrets(sheets_factory: sessionmaker[Session]) -> None:
    with session_scope(sheets_factory) as session:
        with pytest.raises(ValueError, match="Apps Script web app URL"):
            registry.save_settings(session, "google_sheets", {"web_app_url": "http://169.254.169.254/x"})
        with pytest.raises(ValueError, match="16 characters"):
            registry.save_settings(session, "google_sheets", {"secret": "short"})


def test_sync_posts_every_tab_and_marks_synced(sheets_enabled: sessionmaker[Session]) -> None:
    bills = _add_sales(sheets_enabled)
    fake = FakeWebApp()
    result = run(_sync(sheets_enabled, fake))

    assert result.ok, result.message
    assert result.message == "Synced 3 orders and 2 expenses."
    assert result.at

    # One request carrying the secret and all six tabs, each with its header.
    assert len(fake.posts) == 1
    post = fake.posts[0]
    assert post["secret"] == SECRET
    assert [(t["name"], t["mode"]) for t in post["tabs"]] == [
        ("Orders", "append"),
        ("OrderItems", "append"),
        ("Expenses", "append"),
        ("Daily", "replace"),
        ("Items", "replace"),
        ("Monthly", "replace"),
    ]
    for tab in post["tabs"]:
        assert tab["header"] == sheets.TABS[tab["name"]]
        assert all(len(r) == len(tab["header"]) for r in tab["rows"]), tab["name"]

    orders = fake.rows("Orders")
    assert [r[0] for r in orders] == bills
    first = orders[0]
    assert first[3] == "Nutella Waffle x2, Veg Sandwich x1"
    assert first[7] == 189 * 2 + 59
    assert orders[1][8] == "upi" and orders[1][12] == "Asha"
    assert orders[2][11] == "cancelled"

    items = fake.rows("OrderItems")
    assert len(items) == 4
    assert items[0][3:] == ["Nutella Waffle", "Waffle", 189, 2, 378]

    assert fake.rows("Expenses") == [
        ["2026-01-01", "rent", 25000, "Monthly", ""],
        ["2026-01-03", "ingredients", 9000, "One-off", "Weekly stock"],
    ]

    # Daily: today only, paid bills only (the cancelled Family Feast is left out).
    today = f"{clock.today():%Y-%m-%d}"
    assert fake.rows("Daily") == [[today, 437 + 129, 2, 283, "Nutella Waffle"]]

    # Items: whole menu, best earners first, last 30 days of paid bills.
    item_rows = fake.rows("Items")
    assert len(item_rows) == 20
    assert item_rows[0][:3] == ["W03", "Nutella Waffle", "Waffle"]
    assert item_rows[0][6:9] == [2, 1, 378]

    # Monthly: 12 months ending with this one; expenses include the recurring rent.
    monthly = fake.rows("Monthly")
    assert len(monthly) == 12
    assert monthly[-1][0] == clock.month_key(clock.today())
    assert monthly[-1][2:5] == [437 + 129, 2, 283]
    assert monthly[-1][6] >= 25000

    with session_scope(sheets_enabled) as session:
        assert all(o.synced for o in session.scalars(select(Order)))
        assert all(e.synced for e in session.scalars(select(Expense)))
        assert _last_sync(session) == result.at

    # Second run: nothing new to append, summaries rewritten (not duplicated).
    again = run(_sync(sheets_enabled, fake))
    assert again.message == "Synced 0 orders and 0 expenses."
    assert len(fake.rows("Orders")) == 3
    assert len(fake.rows("Items")) == 20
    assert len(fake.rows("Monthly")) == 12


@pytest.mark.parametrize(
    ("fake", "match"),
    [
        (FakeWebApp(secret="something-else-entirely"), "Wrong secret"),  # noqa: S106
        (FakeWebApp(status=500), "answered 500"),
        (FakeWebApp(raw_answer="<html>Sign in</html>"), "didn't answer with JSON"),
        (FakeWebApp(raw_answer='{"ok": false}'), "unknown error"),
    ],
)
def test_web_app_errors_raise_and_leave_rows_unsynced(
    sheets_enabled: sessionmaker[Session], fake: FakeWebApp, match: str
) -> None:
    _add_sales(sheets_enabled)
    with pytest.raises(sheets.SheetsError, match=match):
        run(_sync(sheets_enabled, fake))
    with session_scope(sheets_enabled) as session:
        assert not any(o.synced for o in session.scalars(select(Order)))
        assert _last_sync(session) == ""


def test_unreachable_web_app(sheets_enabled: sessionmaker[Session]) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no internet", request=request)

    async def go() -> SyncResult:
        async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
            return await sheets.sync_now(sheets_enabled, client=client)

    with pytest.raises(sheets.SheetsError, match="Could not reach"):
        run(go())


def test_apps_script_source_is_shipped() -> None:
    src = sheets.apps_script_source()
    assert "function doPost(e)" in src
    assert "PASTE_THE_SECRET_FROM_THE_POS" in src
    # The guard must not contain the whole placeholder: a find-and-replace of it in the SECRET line
    # used to change the guard too, so the script always answered "Set SECRET".
    assert src.count("PASTE_THE_SECRET_FROM_THE_POS") == 2  # the setup comment and the SECRET line
    assert "SECRET === PLACEHOLDER" in src


def test_find_and_replace_of_the_placeholder_leaves_the_guard_working() -> None:
    secret = "0123456789abcdef0123456789abcdef"  # noqa: S105 - test value
    src = sheets.apps_script_source().replace("PASTE_THE_SECRET_FROM_THE_POS", secret)
    assert f"const SECRET = '{secret}';" in src
    assert "const PLACEHOLDER = 'PASTE_THE_' + 'SECRET_FROM_THE_POS';" in src


def test_saved_secret_is_filled_into_the_script() -> None:
    src = sheets.apps_script_source("ab'cd\\ef\u2028gh</script>12345")
    assert sheets.SECRET_LINE not in src
    line = next(x for x in src.splitlines() if x.startswith("const SECRET = "))
    assert line == 'const SECRET = "ab\'cd\\\\ef\\u2028gh</script>12345";'
    assert sheets.apps_script_source("") == sheets.apps_script_source()
    for tab in sheets.TABS:
        assert f"'{tab}'" in src  # every tab the POS sends is on the script's allow-list


class _StopLoop(BaseException):
    """Escapes sync_loop's ``except Exception`` so the test can end the endless loop."""


def test_sync_loop_logs_failures_and_keeps_going(
    sheets_enabled: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls = 0
    sleeps: list[float] = []

    async def flaky_sync(*_args: Any, **_kwargs: Any) -> SyncResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sheets.SheetsError("boom")
        if calls == 2:
            raise ValueError("unexpected")
        raise _StopLoop

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(sheets, "sync_now", flaky_sync)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(_StopLoop):
        run(sheets.sync_loop(sheets_enabled, interval_seconds=300))
    assert calls == 3
    assert sleeps == [10.0, 300, 300]
    assert "sync failed: boom" in caplog.text
    assert "sync failed unexpectedly" in caplog.text
