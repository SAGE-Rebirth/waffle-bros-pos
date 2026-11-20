"""Hardening: PIN lockdown and throttling, Host check, body limit, headers and input limits.

Everything goes through HTTP except the pure helpers (``LoginThrottle``, ``host_allowed`` and the
Google Sheet cell escaping), which are tested with explicit values.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from waffle_pos import __main__ as entry
from waffle_pos.app import create_app
from waffle_pos.config import AppConfig
from waffle_pos.integrations import sheets
from waffle_pos.security import APP_CSP, DOCS_CSP, host_allowed
from waffle_pos.services import auth
from waffle_pos.services.auth import LoginThrottle

Json = dict[str, Any]
DEFAULT_PIN_403 = {"error": "Change the default PIN 1234 first (POST /api/admin/pin)"}
SCRIPT = "https://script.google.com/macros/s/"
TOO_LARGE = {"error": "The request is too large"}
PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)


@contextmanager
def shop(tmp_path: Path, **config: Any) -> Iterator[TestClient]:
    cfg = AppConfig(data_dir=tmp_path, start_sync_loop=False, frontend_dist=tmp_path / "no-dist", **config)
    with TestClient(create_app(cfg)) as client:
        yield client


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with shop(tmp_path) as c:
        yield c


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def default_token(c: TestClient) -> str:
    r = c.post("/api/admin/login", json={"pin": "1234"})
    assert r.status_code == 200, r.text
    token: str = r.json()["token"]
    return token


def owner(c: TestClient) -> dict[str, str]:
    """Admin headers after changing the default PIN to 2468."""
    r = c.post("/api/admin/pin", headers=bearer(default_token(c)), json={"new_pin": "2468"})
    assert r.status_code == 200, r.text
    return bearer(r.json()["token"])


def operations(c: TestClient) -> list[tuple[str, str]]:
    """Every (METHOD, path template) in the OpenAPI schema."""
    schema = cast(FastAPI, c.app).openapi()
    return [(m.upper(), path) for path, ops in schema["paths"].items() for m in ops]


def concrete(template: str) -> str:
    return re.sub(r"\{[^/]+\}", "1", template.replace("{key}", "gst").replace("{month}", "2026-11"))


# ---------------------------------------------------------------------------------------------
# The default PIN only lets you change the PIN
# ---------------------------------------------------------------------------------------------
def test_default_pin_token_can_only_change_the_pin(client: TestClient) -> None:
    token = default_token(client)
    guarded: list[tuple[str, str]] = []
    for method, template in operations(client):
        path = concrete(template)
        if client.request(method, path, json={}).status_code != 401:
            continue  # open to everyone (or the login itself)
        guarded.append((method, template))
        r = client.request(method, path, headers=bearer(token), json={})
        if (method, template) == ("POST", "/api/admin/pin"):
            assert r.status_code == 422  # signed in is enough; the empty body is what's wrong
        else:
            assert (r.status_code, r.json()) == (403, DEFAULT_PIN_403), f"{method} {path}"
    assert ("GET", "/api/backup") in guarded
    assert ("POST", "/api/orders/{order_id}/cancel") in guarded
    assert len(guarded) >= 18

    # Changing the PIN with that token works and unlocks everything.
    changed = client.post("/api/admin/pin", headers=bearer(token), json={"new_pin": "2468"})
    assert changed.status_code == 200
    assert client.get("/api/admin/modules", headers=bearer(changed.json()["token"])).status_code == 200


# ---------------------------------------------------------------------------------------------
# Sign-in throttling
# ---------------------------------------------------------------------------------------------
def test_throttle_locks_a_client_after_five_wrong_pins() -> None:
    t = LoginThrottle()
    for i in range(4):
        t.failed("tablet", now=1000 + i)
        assert t.wait_seconds("tablet", now=1000 + i) == 0
    t.failed("tablet", now=1004)  # 5th wrong PIN: 30 s lock
    assert t.wait_seconds("tablet", now=1004) == 30
    assert t.wait_seconds("tablet", now=1020) == 14
    assert t.wait_seconds("tablet", now=1034) == 0
    assert t.wait_seconds("counter", now=1004) == 0  # other devices are unaffected

    # Each further wrong PIN doubles the lock, up to 15 minutes.
    t.failed("tablet", now=1034)
    assert t.wait_seconds("tablet", now=1034) == 60
    t.failed("tablet", now=1100)
    assert t.wait_seconds("tablet", now=1100) == 120
    for k in range(10):
        t.failed("tablet", now=1200 + k)
    assert t.wait_seconds("tablet", now=1209) == 900

    # A correct PIN clears that client's record.
    t.succeeded("tablet")
    assert t.wait_seconds("tablet", now=1209) == 0


def test_throttle_locks_everyone_after_thirty_wrong_pins() -> None:
    t = LoginThrottle()
    for i in range(29):
        t.failed(f"10.0.0.{i}", now=5000 + i)  # one guess each, so no client is locked on its own
    assert t.wait_seconds("10.0.1.1", now=5029) == 0
    t.failed("10.0.0.99", now=5029)  # the 30th within 10 minutes
    assert t.wait_seconds("10.0.1.1", now=5030) == 570  # until the first guess leaves the window
    assert t.wait_seconds("10.0.1.1", now=5600) == 0


def test_throttle_forgets_old_clients() -> None:
    t = LoginThrottle()
    for i in range(1001):
        t.failed(f"c{i}", now=float(i))
    assert len(t._clients) <= 501  # bounded memory


def test_login_returns_429_with_retry_after(client: TestClient) -> None:
    # A correct PIN resets the count: 4 wrong, 1 right, 4 wrong is never locked.
    for pin in ["0000"] * 4 + ["1234"] + ["0000"] * 4:
        assert client.post("/api/admin/login", json={"pin": pin}).status_code in (200, 401)
    assert client.post("/api/admin/login", json={"pin": "0000"}).status_code == 401  # the 5th in a row
    locked = client.post("/api/admin/login", json={"pin": "1234"})  # even the right PIN waits now
    assert locked.status_code == 429
    message = locked.json()["error"]
    found = re.fullmatch(r"Too many wrong PINs\. Try again in (\d+) seconds\.", message)
    assert found, message
    assert 1 <= int(found[1]) <= 30

    # A restart (a fresh throttle) clears the lock.
    cast(FastAPI, client.app).state.login_throttle = LoginThrottle()
    assert client.post("/api/admin/login", json={"pin": "1234"}).status_code == 200


def test_429_carries_retry_after(client: TestClient) -> None:
    for _ in range(5):
        client.post("/api/admin/login", json={"pin": "0000"})
    locked = client.post("/api/admin/login", json={"pin": "0000"})
    assert locked.status_code == 429
    assert 1 <= int(locked.headers["Retry-After"]) <= 30


@pytest.mark.parametrize("pin", ["١٢٣٤", "\uff11\uff12\uff13\uff14", "12 34", "123", "1234567x", "é", "-123"])
def test_odd_pins_are_just_wrong(client: TestClient, pin: str) -> None:
    r = client.post("/api/admin/login", json={"pin": pin})
    assert (r.status_code, r.json()) == (401, {"error": "Wrong PIN"})


@pytest.mark.parametrize(
    "new_pin", ["١٢٣٤٥", "\uff11\uff12\uff13\uff14\uff15", "12 345", "123", "123456789", "+12345", ""]
)
def test_odd_new_pins_are_refused(client: TestClient, new_pin: str) -> None:
    bad = client.post("/api/admin/pin", headers=bearer(default_token(client)), json={"new_pin": new_pin})
    assert (bad.status_code, bad.json()) == (400, {"error": "PIN must be 4 to 8 digits"})
    assert client.get("/api/config").json()["default_pin"] is True


@pytest.mark.parametrize(
    "authorization",
    [
        "Bearer é.abc".encode(),
        "Bearer ١٢٣.abc".encode(),
        b"Bearer " + b"9" * 200 + b".abc",
        b"Bearer 99999999999.",
        b"Basic dXNlcjpwYXNz",
    ],
)
def test_odd_tokens_are_401_not_500(client: TestClient, authorization: bytes) -> None:
    r = client.get("/api/admin/modules", headers={"Authorization": authorization})
    assert (r.status_code, r.json()) == (401, {"error": "Admin PIN required"})


# ---------------------------------------------------------------------------------------------
# Host header (DNS rebinding)
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "host",
    ["testserver", "localhost", "localhost:4000", "shop-pc", "shop-pc.local:4000", "192.168.1.20:4000",
     "127.0.0.1", "[::1]:4000", "[fe80::1]"],
)  # fmt: skip
def test_allowed_hosts(client: TestClient, host: str) -> None:
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "host", ["evil.example.com", "evil.example.com:4000", "192.168.1.20.evil.com", "local.evil.com", ""]
)
def test_foreign_hosts_are_refused(client: TestClient, host: str) -> None:
    r = client.get("/api/health", headers={"Host": host})
    assert r.status_code == 400
    assert "WB_ALLOWED_HOSTS" in r.json()["error"]
    # Refused before any work is done: not even billing goes through.
    order = client.post("/api/orders", headers={"Host": host}, json={"items": [{"item_id": 1}]})
    assert order.status_code == 400
    assert client.get("/api/orders").json() == []


def test_extra_allowed_hosts(tmp_path: Path) -> None:
    with shop(tmp_path, allowed_hosts="pos.waffle-bros.in, other.example") as c:
        assert c.get("/api/health", headers={"Host": "POS.Waffle-Bros.in:4000"}).status_code == 200
        assert c.get("/api/health", headers={"Host": "other.example"}).status_code == 200
        assert c.get("/api/health", headers={"Host": "evil.example.com"}).status_code == 400


def test_host_allowed_helper() -> None:
    assert host_allowed("192.168.1.20:4000")
    assert host_allowed("[::1]:4000")
    assert host_allowed("::1")
    assert host_allowed("Shop-PC.LOCAL")
    assert host_allowed("pos.example.in", ["POS.example.in"])
    assert not host_allowed("")
    assert not host_allowed(":4000")
    assert not host_allowed("pos.example.in")
    assert not host_allowed("pos.example.in", [" ", ""])


# ---------------------------------------------------------------------------------------------
# Request size
# ---------------------------------------------------------------------------------------------
def test_body_over_one_megabyte_is_refused(client: TestClient) -> None:
    big = b'{"items": [{"item_id": 1}], "note": "' + b"x" * 1_000_000 + b'"}'
    r = client.post("/api/orders", content=big, headers={"Content-Type": "application/json"})
    assert (r.status_code, r.json()) == (413, TOO_LARGE)
    assert client.get("/api/orders").json() == []


def test_chunked_body_over_the_limit_is_refused(tmp_path: Path) -> None:
    with shop(tmp_path, max_body_bytes=200) as c:

        def chunks() -> Iterator[bytes]:  # no Content-Length: sent chunked
            yield b'{"items": [{"item_id": 1}], "note": "'
            for _ in range(10):
                yield b"x" * 50
            yield b'"}'

        r = c.post("/api/orders", content=chunks(), headers={"Content-Type": "application/json"})
        assert "content-length" not in r.request.headers
        assert r.status_code == 413
        assert c.get("/api/orders").json() == []

        # Small chunked bodies still work.
        def small() -> Iterator[bytes]:
            yield b'{"items": '
            yield b'[{"item_id": 1}]}'

        ok = c.post("/api/orders", content=small(), headers={"Content-Type": "application/json"})
        assert ok.status_code == 200, ok.text


def test_bad_content_length_is_refused(client: TestClient) -> None:
    r = client.post("/api/orders", content=b"{}", headers={"Content-Length": "2000000"})
    assert (r.status_code, r.json()) == (413, TOO_LARGE)


# ---------------------------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------------------------
def test_security_headers(client: TestClient) -> None:
    api = client.get("/api/menu")
    assert api.headers["x-content-type-options"] == "nosniff"
    assert api.headers["x-frame-options"] == "DENY"
    assert api.headers["referrer-policy"] == "no-referrer"
    assert api.headers["content-security-policy"] == APP_CSP
    assert "frame-ancestors 'none'" in APP_CSP
    assert api.headers["cache-control"] == "no-store"
    # Errors carry them too.
    assert client.get("/api/orders/999999").headers["x-frame-options"] == "DENY"

    page = client.get("/")
    assert page.headers["content-security-policy"] == APP_CSP
    assert "cache-control" not in page.headers  # only the API is no-store

    # Swagger UI loads its script from a CDN, so /docs gets its own policy.
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert docs.headers["content-security-policy"] == DOCS_CSP
    assert "https://cdn.jsdelivr.net" in DOCS_CSP
    assert "https://cdn.jsdelivr.net" not in APP_CSP


# ---------------------------------------------------------------------------------------------
# Input limits
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("number", ["Infinity", "-Infinity", "NaN", "1e308", "1e400"])
def test_non_finite_and_huge_amounts_are_rejected(client: TestClient, number: str) -> None:
    h = owner(client)
    json_h = {**h, "Content-Type": "application/json"}
    cases = [
        ("POST", "/api/orders", '{"items": [{"item_id": 1}], "discount": %s}', "discount: "),
        ("POST", "/api/expenses", '{"category": "rent", "amount": %s}', "amount: "),
        ("PUT", "/api/targets/2026-11", '{"amount": %s}', "amount: "),
        ("POST", "/api/items", '{"code": "X1", "name": "X", "category_id": 1, "price": %s}', "price: "),
        (
            "PUT",
            "/api/items/1",
            '{"code": "W01", "name": "X", "category_id": 1, "price": 1, "cost": %s}',
            "cost: ",
        ),
    ]
    for method, path, body, field in cases:
        r = client.request(method, path, content=(body % number).encode(), headers=json_h)
        assert r.status_code == 422, f"{method} {path} {number}: {r.status_code} {r.text}"
        assert r.json()["error"].startswith(field)
    # Nothing was saved.
    assert client.get("/api/orders").json() == []
    assert client.get("/api/expenses").json()["total"] == 0
    assert client.get("/api/menu").json()["items"][0]["price"] == 129


def test_limits_at_the_edge_are_accepted(client: TestClient) -> None:
    h = owner(client)
    item = {"code": "BIG", "name": "Wedding order", "category_id": 1, "price": 10_000_000, "cost": 10_000_000}
    big = client.post("/api/items", headers=h, json=item)
    assert big.status_code == 200, big.text
    r = client.post("/api/orders", json={"items": [{"item_id": 1}] * 100, "note": "n" * 300})
    assert r.status_code == 200, r.text
    assert r.json()["subtotal"] == 129 * 100
    assert client.put("/api/targets/2026-11", headers=h, json={"amount": 100_000_000}).status_code == 200
    assert (
        client.post("/api/expenses", headers=h, json={"category": "rent", "amount": 10_000_000}).status_code
        == 200
    )


@pytest.mark.parametrize(
    "image",
    [
        "https://evil.example.com/track.png",
        "http://192.168.1.5/x.png",
        "javascript:alert(1)",
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        "data:text/html;base64,PGgxPmhpPC9oMT4=",
        "data:image/png;base64,abc def",
        "/uploads/<script>.png",
        "/../../etc/passwd",
        "/assets/../api/backup",
        "/api/backup",
        "/assets//evil.png",
    ],
)
def test_external_or_unsafe_images_are_rejected(client: TestClient, image: str) -> None:
    h = owner(client)
    item = {"code": "IMG", "name": "Pic", "category_id": 1, "price": 10, "image": image}
    r = client.post("/api/items", headers=h, json=item)
    assert r.status_code == 422, r.text
    assert r.json()["error"].startswith("image: ")
    logo = client.put("/api/admin/modules/shop", headers=h, json={"settings": {"logo": image}})
    assert logo.status_code == 400, logo.text
    assert logo.json()["error"].startswith("logo: ")


def test_protocol_relative_image_urls_are_rejected(client: TestClient) -> None:
    h = owner(client)
    item = {"code": "IMG", "name": "Pic", "category_id": 1, "price": 10, "image": "//evil.example.com/t.png"}
    assert client.post("/api/items", headers=h, json=item).status_code == 422


def test_inline_and_local_images_are_accepted(client: TestClient) -> None:
    h = owner(client)
    for code, image in (("IMG1", PNG), ("IMG2", "/assets/nutella.webp"), ("IMG3", "")):
        item = {"code": code, "name": "Pic", "category_id": 1, "price": 10, "image": image}
        assert client.post("/api/items", headers=h, json=item).status_code == 200
    items = {i["code"]: i["image"] for i in client.get("/api/menu").json()["items"]}
    assert (items["IMG1"], items["IMG2"], items["IMG3"]) == (PNG, "/assets/nutella.webp", None)
    too_big = {"code": "IMG4", "name": "Pic", "category_id": 1, "price": 10, "image": PNG + "A" * 200_000}
    assert client.post("/api/items", headers=h, json=too_big).status_code == 422
    view = client.put("/api/admin/modules/shop", headers=h, json={"settings": {"logo": PNG}})
    assert view.status_code == 200
    assert client.get("/api/config").json()["modules"]["shop"]["settings"]["logo"] == PNG


@pytest.mark.parametrize("big_id", ["9223372036854775808", "99999999999999999999999"])
def test_ids_too_big_for_sqlite_are_404(client: TestClient, big_id: str) -> None:
    h = owner(client)
    item = {"code": "X1", "name": "X", "category_id": 1, "price": 1}
    for method, path, body in [
        ("GET", f"/api/orders/{big_id}", None),
        ("POST", f"/api/orders/{big_id}/cancel", None),
        ("PUT", f"/api/items/{big_id}", item),
        ("DELETE", f"/api/items/{big_id}", None),
        ("PUT", f"/api/categories/{big_id}", {"name": "X"}),
        ("DELETE", f"/api/categories/{big_id}", None),
        ("DELETE", f"/api/expenses/{big_id}", None),
    ]:
        r = client.request(method, path, headers=h, json=body)
        assert (r.status_code, r.json()) == (404, {"error": "Not found"}), f"{method} {path}"
    # A huge item id in an order is just an unknown item.
    order = client.post("/api/orders", json={"items": [{"item_id": int(big_id)}]})
    assert order.status_code in (400, 404, 422)
    assert order.status_code != 500


# ---------------------------------------------------------------------------------------------
# Google Sheet sync
# ---------------------------------------------------------------------------------------------
def test_formula_like_text_is_escaped_for_the_sheet() -> None:
    row: list[str | int | float] = [
        '=IMPORTDATA("https://evil.example.com")',
        "+91 98765 43210",
        "-SUM(A1:A9)",
        "@me",
        "-",
        "-5",
        "+12.5",
        "Ravi",
        "a=b",
        "\t=1+1",
        "\r=1+1",
        -3,
        12.5,
        0,
    ]
    tab = sheets._tab("Orders", "append", [row])
    assert tab["name"] == "Orders"
    assert tab["mode"] == "append"
    assert tab["header"] == sheets.TABS["Orders"]
    assert tab["rows"] == [
        [
            '\'=IMPORTDATA("https://evil.example.com")',
            "'+91 98765 43210",
            "'-SUM(A1:A9)",
            "'@me",
            "'-",
            "-5",  # numbers written as text stay as they are
            "+12.5",
            "Ravi",
            "a=b",
            "'\t=1+1",
            "'\r=1+1",
            -3,
            12.5,
            0,
        ]
    ]


def test_only_one_sync_at_a_time(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    h = owner(client)
    settings = {"web_app_url": "https://script.google.com/macros/s/AKfy-test/exec", "secret": "x" * 20}
    r = client.put(
        "/api/admin/modules/google_sheets", headers=h, json={"enabled": True, "settings": settings}
    )
    assert r.status_code == 200, r.text
    # Pretend the background loop is mid-sync: the manual sync returns at once, without any network call.
    monkeypatch.setattr(sheets, "_running", True)
    busy = client.post("/api/sync", headers=h)
    assert busy.status_code == 200
    assert busy.json() == {
        "ok": False,
        "skipped": False,
        "at": None,
        "message": "A sync is already running. Try again in a moment.",
    }


def test_chunked_body_over_the_limit_is_413(tmp_path: Path) -> None:
    with shop(tmp_path, max_body_bytes=200) as c:

        def chunks() -> Iterator[bytes]:
            yield b'{"items": [{"item_id": 1}], "note": "'
            yield b"x" * 500
            yield b'"}'

        r = c.post("/api/orders", content=chunks(), headers={"Content-Type": "application/json"})
        assert (r.status_code, r.json()) == (413, TOO_LARGE)


def test_middleware_errors_carry_security_headers(client: TestClient) -> None:
    r = client.get("/api/health", headers={"Host": "evil.example.com"})
    assert r.status_code == 400
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_server_trusts_forwarded_for_only_from_configured_proxies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behind nginx (the `web` service) the PIN lockout must see each tablet, not the proxy."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(entry, "create_app", lambda config: "app")
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append(kw))
    for cfg, expected in (
        (AppConfig(data_dir=tmp_path, start_sync_loop=False), "127.0.0.1"),
        (AppConfig(data_dir=tmp_path, start_sync_loop=False, forwarded_allow_ips="*"), "*"),
    ):
        monkeypatch.setattr(entry, "get_config", lambda cfg=cfg: cfg)
        entry.main()
        assert calls[-1]["proxy_headers"] is True
        assert calls[-1]["forwarded_allow_ips"] == expected


# ---------- Review of 2026-11-20: PIN at the counter, PIN change, settings limits ----------
def test_changing_the_pin_needs_the_current_pin(client: TestClient) -> None:
    """A token left signed in on a tablet must not be enough to take over the PIN."""
    h = owner(client)
    for body in ({"new_pin": "13579"}, {"new_pin": "13579", "current_pin": "9999"}):
        r = client.post("/api/admin/pin", headers=h, json=body)
        assert (r.status_code, r.json()) == (400, {"error": "Your current PIN is wrong"})
    assert client.post("/api/admin/login", json={"pin": "2468"}).status_code == 200  # unchanged
    r = client.post("/api/admin/pin", headers=h, json={"new_pin": "13579", "current_pin": "2468"})
    assert r.status_code == 200, r.text
    assert client.post("/api/admin/login", json={"pin": "13579"}).status_code == 200


def test_wrong_current_pins_count_towards_the_lockout(client: TestClient) -> None:
    h = owner(client)
    for _ in range(5):
        client.post("/api/admin/pin", headers=h, json={"new_pin": "13579", "current_pin": "0000"})
    r = client.post("/api/admin/pin", headers=h, json={"new_pin": "13579", "current_pin": "2468"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert client.post("/api/admin/login", json={"pin": "2468"}).status_code == 429


def test_first_pin_change_needs_no_current_pin(client: TestClient) -> None:
    r = client.post("/api/admin/pin", headers=bearer(default_token(client)), json={"new_pin": "2468"})
    assert r.status_code == 200, r.text


def test_counter_pin_tokens_last_two_minutes(client: TestClient) -> None:
    owner(client)
    once = client.post("/api/admin/login", json={"pin": "2468", "once": True}).json()
    full = client.post("/api/admin/login", json={"pin": "2468"}).json()
    now = time.time()
    assert now + 100 < once["expires_at"] <= now + 121
    assert full["expires_at"] > now + 11 * 3600  # the Admin page session is unchanged (12 h)
    assert client.get("/api/admin/modules", headers=bearer(once["token"])).status_code == 200
    factory = cast(FastAPI, client.app).state.session_factory
    with factory() as db:  # an expired once-token is refused
        assert auth.verify_token(db, once["token"], now=now + 200) is False
        assert auth.verify_token(db, full["token"], now=now + 200) is True


@pytest.mark.parametrize(
    ("key", "settings", "field"),
    [
        ("targets", {"default_target": 1e300}, "default_target"),
        ("targets", {"expense_categories": ["x" * 31]}, "expense_categories.0"),
        ("whatsapp", {"delivery_buildings": ["y" * 61]}, "delivery_buildings.0"),
        ("whatsapp", {"min_order": 1e308}, "min_order"),
        ("google_sheets", {"web_app_url": SCRIPT + "x@evil.com/exec"}, "web_app_url"),
        ("google_sheets", {"web_app_url": SCRIPT + "../../x"}, "web_app_url"),
    ],
)
def test_module_settings_have_limits(client: TestClient, key: str, settings: Json, field: str) -> None:
    r = client.put(f"/api/admin/modules/{key}", headers=owner(client), json={"settings": settings})
    assert r.status_code == 400, r.text
    assert r.json()["error"].startswith(f"{field}: ")
