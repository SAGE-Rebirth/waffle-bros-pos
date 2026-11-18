"""Google Sheets sync, with Google faked by httpx.MockTransport (no network)."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
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

TOKEN_URI = "https://oauth2.example.test/token"  # noqa: S105 - fake endpoint
SHEET_ID = "sheet-123"


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


async def _sync(factory: sessionmaker[Session], fake: FakeGoogle) -> SyncResult:
    async with fake.client() as client:
        return await sheets.sync_now(factory, client=client)


@dataclass
class FakeGoogle:
    """Records requests and answers like the token endpoint and Sheets API would."""

    existing_tabs: set[str] = field(default_factory=set)
    auth_status: int = 200
    sheets_status: int = 200
    token_requests: int = 0
    appended: dict[str, list[list[Any]]] = field(default_factory=dict)
    written: dict[str, list[list[Any]]] = field(default_factory=dict)
    added_tabs: list[str] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)
    assertions: list[str] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:  # noqa: PLR0911 - one branch per endpoint
        url = str(request.url)
        if url.startswith(TOKEN_URI):
            self.token_requests += 1
            form = dict(httpx.QueryParams(request.content.decode()))
            assert form["grant_type"] == sheets.JWT_BEARER_GRANT
            self.assertions.append(form["assertion"])
            if self.auth_status != 200:
                return httpx.Response(self.auth_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})

        assert request.headers["Authorization"] == "Bearer tok-1"
        if self.sheets_status != 200:
            return httpx.Response(self.sheets_status, json={"error": {"message": "nope"}})
        prefix = f"{sheets.SHEETS_API}/{SHEET_ID}"
        assert request.url.path.startswith(httpx.URL(prefix).path)
        path = request.url.path[len(httpx.URL(prefix).path) :]
        body: Any = json.loads(request.content) if request.content else None

        if request.method == "GET" and path == "":
            tabs = self.existing_tabs | set(self.added_tabs)
            return httpx.Response(200, json={"sheets": [{"properties": {"title": t}} for t in sorted(tabs)]})
        if request.method == "POST" and path == ":batchUpdate":
            self.added_tabs += [r["addSheet"]["properties"]["title"] for r in body["requests"]]
            return httpx.Response(200, json={})
        if request.method == "POST" and path.endswith(":append"):
            tab = path.removeprefix("/values/").split("!")[0]
            self.appended.setdefault(tab, []).extend(body["values"])
            return httpx.Response(200, json={})
        if request.method == "POST" and path.endswith(":clear"):
            self.cleared.append(path)
            return httpx.Response(200, json={})
        if request.method == "PUT":
            self.written[path.removeprefix("/values/")] = body["values"]
            return httpx.Response(200, json={})
        return httpx.Response(404, text=f"unexpected {request.method} {path}")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


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


@pytest.fixture(autouse=True)
def sheets_clear_token_cache() -> Iterator[None]:
    sheets.clear_token_cache()
    yield
    sheets.clear_token_cache()


@pytest.fixture(scope="module")
def sheets_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def sheets_key_file(tmp_path: Path, sheets_private_key: rsa.RSAPrivateKey) -> Path:
    key = sheets_private_key
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    path = tmp_path / "google-key.json"
    path.write_text(
        json.dumps(
            {
                "type": "service_account",
                "client_email": "pos@waffle.iam.gserviceaccount.com",
                "private_key_id": "kid-1",
                "private_key": pem,
                "token_uri": TOKEN_URI,
            }
        )
    )
    return path


def _last_sync(session: Session) -> str:
    return registry.settings_of(session, "google_sheets", GoogleSheetsSettings).last_sync


@pytest.fixture
def sheets_enabled(sheets_factory: sessionmaker[Session], sheets_key_file: Path) -> sessionmaker[Session]:
    with session_scope(sheets_factory) as session:
        registry.set_enabled(session, "google_sheets", True)
        registry.save_settings(
            session,
            "google_sheets",
            {"spreadsheet_id": SHEET_ID, "credentials_path": str(sheets_key_file)},
        )
    return sheets_factory


def _add_sales(factory: sessionmaker[Session]) -> list[str]:
    today = clock.now().replace(hour=12, minute=0, second=0)
    with session_scope(factory) as session:
        ids = {i.code: i.id for i in session.scalars(select(Item))}
        o1 = create_order(
            session,
            OrderCreate(items=[OrderLineIn(item_id=ids["W05"], qty=2), OrderLineIn(item_id=ids["S01"])]),
            when=today,
        )
        o2 = create_order(
            session,
            OrderCreate(items=[OrderLineIn(item_id=ids["W01"])], payment_method="upi", customer_name="Asha"),
            when=today + timedelta(minutes=5),
        )
        o3 = create_order(session, OrderCreate(items=[OrderLineIn(item_id=ids["C03"])]), when=today)
        cancel_order(session, o3.id)
        session.add(Expense(date=date(2026, 1, 1), category="rent", amount=25000, recurring=True))
        session.add(Expense(date=date(2026, 1, 3), category="ingredients", amount=9000, note="Weekly stock"))
        return [o1.bill_no, o2.bill_no, o3.bill_no]


def test_disabled_is_skipped(sheets_factory: sessionmaker[Session]) -> None:
    fake = FakeGoogle()
    result = run(_sync(sheets_factory, fake))
    assert result.skipped and not result.ok
    assert fake.token_requests == 0


def test_enabled_without_config_asks_for_it(sheets_factory: sessionmaker[Session]) -> None:
    with session_scope(sheets_factory) as session:
        registry.set_enabled(session, "google_sheets", True)
    result = run(_sync(sheets_factory, FakeGoogle()))
    assert not result.ok and not result.skipped
    assert "spreadsheet ID" in result.message


def test_sync_appends_rows_and_marks_synced(sheets_enabled: sessionmaker[Session]) -> None:
    bills = _add_sales(sheets_enabled)
    fake = FakeGoogle(existing_tabs={"Orders"})
    result = run(_sync(sheets_enabled, fake))

    assert result.ok, result.message
    assert result.message == "Synced 3 orders and 2 expenses."
    assert result.at

    # Missing tabs created, with headers; the existing one left alone.
    assert fake.added_tabs == ["OrderItems", "Expenses", "Daily", "Items", "Monthly"]
    assert fake.written["OrderItems!A1"] == [sheets.TABS["OrderItems"]]
    assert "Orders!A1" not in fake.written

    orders = fake.appended["Orders"]
    assert [r[0] for r in orders] == bills
    first = orders[0]
    assert first[3] == "Nutella x2, Veg Grilled Waffle Sandwich x1"
    assert first[7] == 199 * 2 + 139
    assert orders[1][8] == "upi" and orders[1][12] == "Asha"
    assert orders[2][11] == "cancelled"
    assert len(first) == len(sheets.TABS["Orders"])

    items = fake.appended["OrderItems"]
    assert len(items) == 4
    assert items[0][3:] == ["Nutella", "Waffle", 199, 2, 398]

    assert fake.appended["Expenses"] == [
        ["2026-01-01", "rent", 25000, "Monthly", ""],
        ["2026-01-03", "ingredients", 9000, "One-off", "Weekly stock"],
    ]

    # Daily: today only, paid bills only (the cancelled family pack is left out).
    today = f"{clock.today():%Y-%m-%d}"
    assert fake.cleared == [
        "/values/Daily!A3:E2000:clear",
        "/values/Items!A20:K2000:clear",
        "/values/Monthly!A14:H2000:clear",
    ]
    assert fake.written["Daily!A2"] == [[today, 537 + 129, 2, 333, "Nutella"]]

    # Items: whole menu, best earners first, last 30 days of paid bills.
    item_rows = fake.written["Items!A2"]
    assert len(item_rows) == 18
    assert item_rows[0][:3] == ["W05", "Nutella", "Waffle"]
    assert item_rows[0][6:9] == [2, 1, 398]
    assert all(len(r) == len(sheets.TABS["Items"]) for r in item_rows)

    # Monthly: 12 months ending with this one; expenses include the recurring rent.
    monthly = fake.written["Monthly!A2"]
    assert len(monthly) == 12
    assert monthly[-1][0] == clock.month_key(clock.today())
    assert monthly[-1][2:5] == [537 + 129, 2, 333]
    assert monthly[-1][6] >= 25000

    with session_scope(sheets_enabled) as session:
        assert all(o.synced for o in session.scalars(select(Order)))
        assert all(e.synced for e in session.scalars(select(Expense)))
        assert _last_sync(session) == result.at

    # Second run: nothing new to append, token reused from the cache.
    fake.appended.clear()
    again = run(_sync(sheets_enabled, fake))
    assert again.message == "Synced 0 orders and 0 expenses."
    assert fake.appended == {}
    assert fake.token_requests == 1


def _b64json(part: str) -> Any:
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def test_jwt_is_signed_for_the_service_account(
    sheets_enabled: sessionmaker[Session], sheets_private_key: rsa.RSAPrivateKey
) -> None:
    fake = FakeGoogle(existing_tabs=set(sheets.TABS))
    run(_sync(sheets_enabled, fake))
    header_b64, claims_b64, signature_b64 = fake.assertions[0].split(".")
    header, claims = _b64json(header_b64), _b64json(claims_b64)
    assert header["alg"] == "RS256" and header["kid"] == "kid-1"
    assert claims["iss"] == "pos@waffle.iam.gserviceaccount.com"
    assert claims["aud"] == TOKEN_URI
    assert claims["scope"] == sheets.SCOPE
    assert claims["exp"] - claims["iat"] == 3600
    # Raises InvalidSignature if the JWT wasn't signed with the service account's key.
    sheets_private_key.public_key().verify(
        base64.urlsafe_b64decode(signature_b64 + "=" * (-len(signature_b64) % 4)),
        f"{header_b64}.{claims_b64}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_expired_token_is_refreshed(sheets_enabled: sessionmaker[Session]) -> None:
    fake = FakeGoogle(existing_tabs=set(sheets.TABS))
    run(_sync(sheets_enabled, fake))
    for token in sheets._token_cache.values():
        token.expires_at = 0
    run(_sync(sheets_enabled, fake))
    assert fake.token_requests == 2


@pytest.mark.parametrize(
    ("setup", "match"),
    [
        (lambda f: setattr(f, "auth_status", 400), "Google auth failed: 400"),
        (lambda f: setattr(f, "sheets_status", 403), "Sheets API GET : 403"),
    ],
)
def test_google_errors_raise_and_leave_rows_unsynced(
    sheets_enabled: sessionmaker[Session], setup: Callable[[FakeGoogle], None], match: str
) -> None:
    _add_sales(sheets_enabled)
    fake = FakeGoogle()
    setup(fake)
    with pytest.raises(sheets.SheetsError, match=match):
        run(_sync(sheets_enabled, fake))
    with session_scope(sheets_enabled) as session:
        assert not any(o.synced for o in session.scalars(select(Order)))
        assert _last_sync(session) == ""


def test_missing_credentials_file(sheets_enabled: sessionmaker[Session], tmp_path: Path) -> None:
    with session_scope(sheets_enabled) as session:
        registry.save_settings(session, "google_sheets", {"credentials_path": str(tmp_path / "nope.json")})
    with pytest.raises(sheets.SheetsError, match="Credentials file not found"):
        run(_sync(sheets_enabled, FakeGoogle()))


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
