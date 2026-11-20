"""The whole shop, end to end, through the HTTP API only.

These tests walk through the POS the way the shop uses it: a fresh install, the owner setting it up,
a day of billing, the day-end cash-up, sync and backup, and a restart. Every request goes through
``TestClient``; nothing here touches the services or the database directly (except opening the
downloaded backup with ``sqlite3``), so they check the contract the React screens rely on.

A response hook records which API route answered each request. The last test checks that every
route in the OpenAPI schema was answered successfully at least once by this file, so a new endpoint
can't slip in untested.

Bills can't be back-dated over HTTP, so expectations use ``waffle_pos.clock.today()``.
"""

from __future__ import annotations

import math
import re
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from waffle_pos import clock
from waffle_pos.app import create_app
from waffle_pos.config import AppConfig
from waffle_pos.services.targets import money

Json = dict[str, Any]

# (METHOD, route template) of every API route that has answered successfully in this file.
HITS: set[tuple[str, str]] = set()
# Test functions of this module that have run (the coverage check only applies to a full run).
RAN: set[str] = set()

MODULE_KEYS = ["shop", "theme", "billing", "targets", "gst", "discounts", "google_sheets", "whatsapp"]


# ---------------------------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------------------------
def api_operations(app: FastAPI) -> dict[tuple[str, str], Json]:
    """Every (METHOD, path template) in the OpenAPI schema, with its operation object."""
    schema = app.openapi()
    return {(m.upper(), path): op for path, ops in schema["paths"].items() for m, op in ops.items()}


def _recorder(app: FastAPI) -> Callable[[httpx.Response], None]:
    """An httpx response hook that records which API route answered, when it answered successfully."""
    ops = api_operations(app)
    # Literal paths before templated ones, so /api/items/reorder never counts as /api/items/{item_id}.
    patterns = sorted(
        (
            (method, path, re.compile("^" + re.sub(r"\\\{[^/]+?\\\}", "[^/]+", re.escape(path)) + "$"))
            for method, path in ops
        ),
        key=lambda p: p[1].count("{"),
    )

    def hook(response: httpx.Response) -> None:
        method, url_path = response.request.method, response.request.url.path
        for op_method, path, regex in patterns:
            if op_method == method and regex.match(url_path):
                declared = {int(code) for code in ops[(method, path)]["responses"] if code.isdigit()}
                # Success is a 2xx, or the declared status of a route with no 2xx (the WhatsApp stub's 501).
                no_2xx = not any(200 <= code < 300 for code in declared)
                if response.status_code < 300 or (no_2xx and response.status_code in declared):
                    HITS.add((method, path))
                return

    return hook


@contextmanager
def shop(data_dir: Path, frontend_dist: Path | None = None) -> Iterator[TestClient]:
    """Start the POS on ``data_dir`` (no sync loop, no network) and yield a recording client."""
    config = AppConfig(
        data_dir=data_dir,
        start_sync_loop=False,
        frontend_dist=frontend_dist if frontend_dist is not None else data_dir / "no-dist",
    )
    app = create_app(config)
    with TestClient(app) as client:
        client.event_hooks = {"request": [], "response": [_recorder(app)]}
        yield client


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with shop(tmp_path) as c:
        yield c


@pytest.fixture(autouse=True)
def _track_run(request: pytest.FixtureRequest) -> None:
    RAN.add(request.node.originalname)


def ok(r: httpx.Response, status: int = 200) -> Any:
    """Assert the status (showing the body when it's wrong) and return the JSON body."""
    assert r.status_code == status, f"{r.request.method} {r.request.url}: {r.status_code} {r.text}"
    return r.json()


OWNER_PIN = "2468"


def login(c: TestClient, pin: str = OWNER_PIN) -> dict[str, str]:
    body = ok(c.post("/api/admin/login", json={"pin": pin}))
    return {"Authorization": f"Bearer {body['token']}"}


def admin(c: TestClient) -> dict[str, str]:
    """Admin headers. With the default PIN still set (a fresh shop), first change it to OWNER_PIN:
    a default-PIN token may only change the PIN; every other admin route answers 403."""
    if not config(c)["default_pin"]:
        return login(c)
    changed = ok(c.post("/api/admin/pin", headers=login(c, "1234"), json={"new_pin": OWNER_PIN}))
    return {"Authorization": f"Bearer {changed['token']}"}


def menu_items(c: TestClient) -> dict[str, Json]:
    """Menu items by code."""
    return {i["code"]: i for i in ok(c.get("/api/menu"))["items"]}


def set_module(c: TestClient, h: dict[str, str], key: str, **body: Any) -> Json:
    view: Json = ok(c.put(f"/api/admin/modules/{key}", headers=h, json=body))
    return view


def config(c: TestClient) -> Json:
    cfg: Json = ok(c.get("/api/config"))
    return cfg


def expected_bill(lines: list[tuple[float, int]], discount: float = 0.0, gst: float = 0.0) -> Json:
    """What a bill should come to: (price, qty) lines, rupee discount before GST, GST rate in %.

    Money is rounded half-up to 2 dp (``services.targets.money``), as CLAUDE.md requires.
    """
    subtotal = sum(price * qty for price, qty in lines)
    tax = money((subtotal - discount) * gst / 100)
    return {
        "subtotal": money(subtotal),
        "discount": money(discount),
        "tax": tax,
        "total": money(subtotal - discount + tax),
    }


def assert_bill(order: Json, expected: Json) -> None:
    for key, value in expected.items():
        assert order[key] == pytest.approx(value, abs=1e-9), f"{key}: {order[key]} != {value}"


def today_s() -> str:
    return f"{clock.today():%Y-%m-%d}"


# ---------------------------------------------------------------------------------------------
# 1. Fresh install
# ---------------------------------------------------------------------------------------------
def test_fresh_install(client: TestClient) -> None:
    # The app is up and the database answers.
    health = ok(client.get("/api/health"))
    assert health["status"] == "ok"

    # Out-of-the-box config: default PIN, GST off, discounts on (20% cap), the shop's defaults.
    cfg = config(client)
    assert health["version"] == cfg["version"]
    assert cfg["default_pin"] is True
    assert list(cfg["modules"]) == MODULE_KEYS  # display order; the hidden admin module never shows
    mods = cfg["modules"]
    assert mods["gst"]["enabled"] is False
    assert mods["discounts"] == {"enabled": True, "settings": {"max_discount_pct": 20}}
    assert mods["google_sheets"]["enabled"] is False
    assert mods["whatsapp"]["enabled"] is False
    assert all(mods[k]["enabled"] for k in ("shop", "theme", "billing", "targets"))
    assert mods["shop"]["settings"]["shop_name"] == "Waffle Bros"
    assert mods["billing"]["settings"]["payment_methods"] == ["upi", "cash", "card"]
    assert mods["targets"]["settings"]["default_target"] == 100000

    # The starter menu is seeded: 5 categories, 20 active items, in menu order.
    menu = ok(client.get("/api/menu"))
    assert [c["name"] for c in menu["categories"]] == ["Waffle", "Mini Waffle", "Bowl", "Snacks", "Combo"]
    assert [c["sort"] for c in menu["categories"]] == [0, 1, 2, 3, 4]
    assert len(menu["items"]) == 20
    assert all(i["active"] for i in menu["items"])
    assert menu["items"][0]["code"] == "W01"
    assert {i["category"] for i in menu["items"]} == {"Waffle", "Mini Waffle", "Bowl", "Snacks", "Combo"}

    # No bills yet: empty day, empty dashboard with the single "no sales yet" tip.
    assert ok(client.get("/api/orders")) == []
    day = ok(client.get("/api/day-end"))
    assert (day["revenue"], day["orders"], day["payments"]) == (0, 0, [])
    assert len(day["notSold"]) == 20
    dash = ok(client.get("/api/dashboard"))
    assert [i["title"] for i in dash["insights"]] == ["No sales yet this month"]
    assert dash["items"]["bestSeller"] is None


def test_every_admin_route_needs_a_token(client: TestClient) -> None:
    """Admin routes answer 401 without a token; everything else in the API works without one."""
    guarded: set[tuple[str, str]] = set()
    for method, template in api_operations(cast(FastAPI, client.app)):
        path = re.sub(r"\{[^/]+\}", "1", template.replace("{key}", "gst"))
        r = client.request(method, path, json={})
        if r.status_code == 401 and r.json() == {"error": "Admin PIN required"}:
            guarded.add((method, template))
            # A forged or malformed token is no better than none.
            for headers in ({"Authorization": "Bearer 9999999999.forged"}, {"Authorization": "1234"}):
                assert client.request(method, path, headers=headers, json={}).status_code == 401
    assert guarded >= {
        ("POST", "/api/categories"),
        ("PUT", "/api/categories/{category_id}"),
        ("DELETE", "/api/categories/{category_id}"),
        ("POST", "/api/categories/reorder"),
        ("POST", "/api/items"),
        ("PUT", "/api/items/{item_id}"),
        ("DELETE", "/api/items/{item_id}"),
        ("POST", "/api/items/reorder"),
        ("GET", "/api/backup"),
        ("POST", "/api/admin/pin"),
        ("GET", "/api/admin/modules"),
        ("PUT", "/api/admin/modules/{key}"),
        ("GET", "/api/admin/google-sheet/script"),
        ("POST", "/api/orders/{order_id}/cancel"),
        ("PUT", "/api/targets/{month}"),
        ("POST", "/api/expenses"),
        ("DELETE", "/api/expenses/{expense_id}"),
        ("POST", "/api/sync"),
    }
    # Billing, reading and reporting stay open so the counter works without a PIN.
    open_routes = {
        ("GET", "/api/menu"),
        ("GET", "/api/config"),
        ("POST", "/api/admin/login"),
        ("POST", "/api/orders"),
        ("GET", "/api/orders"),
        ("GET", "/api/orders/{order_id}"),
        ("GET", "/api/dashboard"),
        ("GET", "/api/items/stats"),
        ("GET", "/api/day-end"),
        ("GET", "/api/expenses"),
        ("GET", "/api/health"),
    }
    assert not guarded & open_routes

    # Nothing was changed by those attempts.
    assert len(ok(client.get("/api/menu"))["items"]) == 20
    assert config(client)["modules"]["gst"]["enabled"] is False


# ---------------------------------------------------------------------------------------------
# 2. The owner sets the shop up
# ---------------------------------------------------------------------------------------------
def test_owner_setup(client: TestClient) -> None:
    # --- PIN: sign in with the default, then change it ---
    first = ok(client.post("/api/admin/login", json={"pin": "1234"}))
    assert first["must_change_pin"] is True
    assert first["token"].startswith(f"{first['expires_at']}.")
    old = {"Authorization": f"Bearer {first['token']}"}
    # The default PIN is the same on every install, so its token can only change the PIN.
    locked = client.get("/api/admin/modules", headers=old)
    assert (locked.status_code, locked.json()) == (
        403,
        {"error": "Change the default PIN 1234 first (POST /api/admin/pin)"},
    )

    changed = ok(client.post("/api/admin/pin", headers=old, json={"new_pin": "4821"}))
    assert changed["must_change_pin"] is False
    h = {"Authorization": f"Bearer {changed['token']}"}
    assert client.get("/api/admin/modules", headers=old).status_code == 401  # everyone signed out
    assert ok(client.get("/api/admin/modules", headers=h))
    assert client.post("/api/admin/login", json={"pin": "1234"}).status_code == 401
    assert ok(client.post("/api/admin/login", json={"pin": "4821"}))["must_change_pin"] is False
    assert config(client)["default_pin"] is False

    # --- Module list as the Admin page sees it ---
    modules = ok(client.get("/api/admin/modules", headers=h))
    assert [m["key"] for m in modules] == MODULE_KEYS
    assert {m["key"] for m in modules if m["core"]} == {"shop", "theme", "billing", "targets"}
    for m in modules:
        assert set(m) == {
            "key",
            "name",
            "description",
            "icon",
            "core",
            "enabled",
            "settings_schema",
            "values",
            "readonly_fields",
        }
        assert set(m["values"]) <= set(m["settings_schema"]["properties"])

    # --- Shop, theme and billing settings flow through to /api/config ---
    shop_view = set_module(
        client, h, "shop", settings={"shop_name": "Waffle Bros Arera", "receipt_footer": "Visit again!"}
    )
    assert shop_view["values"]["shop_name"] == "Waffle Bros Arera"
    assert shop_view["values"]["shop_address"] == "Bhopal"  # untouched keys keep their values
    set_module(client, h, "theme", settings={"primary": "#7B3F00"})
    bad_colour = client.put("/api/admin/modules/theme", headers=h, json={"settings": {"primary": "brown"}})
    assert bad_colour.status_code == 400
    assert bad_colour.json()["error"].startswith("primary:")
    set_module(
        client,
        h,
        "billing",
        settings={
            "payment_methods": ["upi", "cash"],
            "default_payment": "cash",
            "order_types": ["takeaway", "dine-in", "takeaway"],  # duplicates are dropped
        },
    )
    bad_method = client.put(
        "/api/admin/modules/billing", headers=h, json={"settings": {"payment_methods": ["bitcoin"]}}
    )
    assert bad_method.status_code == 400

    cfg = config(client)["modules"]
    assert cfg["shop"]["settings"]["shop_name"] == "Waffle Bros Arera"
    assert cfg["shop"]["settings"]["receipt_footer"] == "Visit again!"
    assert cfg["theme"]["settings"]["primary"] == "#7B3F00"
    assert cfg["theme"]["settings"]["dark"] == "#4A2C1A"
    assert cfg["billing"]["settings"]["payment_methods"] == ["upi", "cash"]
    assert cfg["billing"]["settings"]["default_payment"] == "cash"
    assert cfg["billing"]["settings"]["order_types"] == ["takeaway", "dine-in"]

    # --- GST on at 5%, discount cap 10% ---
    gst = set_module(client, h, "gst", enabled=True, settings={"rate": 5, "gstin": "23ABCDE1234F1Z5"})
    assert gst["enabled"] is True
    assert gst["values"] == {"rate": 5.0, "gstin": "23ABCDE1234F1Z5"}
    assert client.put("/api/admin/modules/gst", headers=h, json={"settings": {"rate": 30}}).status_code == 400
    set_module(client, h, "discounts", settings={"max_discount_pct": 10})
    cfg = config(client)["modules"]
    assert cfg["gst"] == {"enabled": True, "settings": {"rate": 5.0, "gstin": "23ABCDE1234F1Z5"}}
    assert cfg["discounts"]["settings"]["max_discount_pct"] == 10

    # --- Menu: a new category with two items ---
    shakes = ok(client.post("/api/categories", headers=h, json={"name": "Shakes"}))["id"]
    dup = client.post("/api/categories", headers=h, json={"name": "  shakes "})
    assert (dup.status_code, dup.json()) == (400, {"error": "That category already exists"})
    ok(client.put(f"/api/categories/{shakes}", headers=h, json={"name": "Thick Shakes"}))
    assert client.put(f"/api/categories/{shakes}", headers=h, json={"name": "waffle"}).status_code == 400

    oreo_body = {"code": "sh01", "name": " Oreo Shake ", "category_id": shakes, "price": 149, "cost": 45}
    oreo = ok(client.post("/api/items", headers=h, json=oreo_body))["id"]
    coffee_body = {"code": "SH02", "name": "Cold Coffee Shake", "category_id": shakes, "price": 129}
    coffee = ok(client.post("/api/items", headers=h, json=coffee_body))["id"]
    dup_item = client.post("/api/items", headers=h, json={**coffee_body, "name": "Other"})
    assert dup_item.json() == {"error": "That item ID is already used"}
    no_cat = client.post("/api/items", headers=h, json={**coffee_body, "code": "SH09", "category_id": 9999})
    assert no_cat.json() == {"error": "Pick a valid category"}

    items = menu_items(client)
    assert items["SH01"]["name"] == "Oreo Shake"  # code upper-cased, name trimmed
    assert items["SH01"]["category"] == "Thick Shakes"
    assert items["SH02"]["cost"] == 0
    assert items["SH02"]["veg"] is True

    # Price change (PUT replaces the whole item).
    ok(client.put(f"/api/items/{oreo}", headers=h, json={**oreo_body, "price": 159}))
    assert menu_items(client)["SH01"]["price"] == 159

    # --- Reorder: shakes first on the billing screen, cold coffee before oreo ---
    ok(client.post("/api/categories/reorder", headers=h, json={"ids": [shakes]}))
    cats = ok(client.get("/api/menu"))["categories"]
    assert [c["name"] for c in cats] == ["Thick Shakes", "Waffle", "Mini Waffle", "Bowl", "Snacks", "Combo"]
    ok(client.post("/api/items/reorder", headers=h, json={"ids": [coffee, oreo]}))
    assert [i["code"] for i in ok(client.get("/api/menu"))["items"][:3]] == ["SH02", "SH01", "W01"]

    # --- Remove items: unsold ones are deleted, sold ones hidden ---
    assert ok(client.delete(f"/api/items/{coffee}", headers=h)) == {"ok": True, "hidden": False}
    assert "SH02" not in menu_items(client)
    sold = ok(client.post("/api/orders", json={"items": [{"item_id": oreo}]}))
    assert sold["items"][0]["name"] == "Oreo Shake"
    assert ok(client.delete(f"/api/items/{oreo}", headers=h)) == {"ok": True, "hidden": True}
    assert menu_items(client)["SH01"]["active"] is False
    assert ok(client.delete("/api/items/999999", headers=h)) == {"ok": True, "hidden": False}
    # Bring it back with active: true.
    ok(client.put(f"/api/items/{oreo}", headers=h, json={**oreo_body, "price": 159, "active": True}))
    assert menu_items(client)["SH01"]["active"] is True

    # --- Categories: only empty ones can be deleted ---
    blocked = client.delete(f"/api/categories/{shakes}", headers=h)
    assert blocked.json() == {"error": "Move or remove this category's items first"}
    seasonal = ok(client.post("/api/categories", headers=h, json={"name": "Seasonal"}))["id"]
    assert ok(client.delete(f"/api/categories/{seasonal}", headers=h)) == {"ok": True}
    assert client.delete(f"/api/categories/{seasonal}", headers=h).status_code == 404

    # --- Monthly target, made the default; next month's own target doesn't change the default ---
    month = clock.month_key(clock.today())
    next_month = clock.month_key(clock.next_month_start(clock.today()))
    assert client.put(f"/api/targets/{month}", json={"amount": 60000}).status_code == 401  # admin only
    assert ok(
        client.put(f"/api/targets/{month}", headers=h, json={"amount": 60000, "makeDefault": True})
    ) == {"ok": True}
    ok(client.put(f"/api/targets/{next_month}", headers=h, json={"amount": 80000}))
    assert config(client)["modules"]["targets"]["settings"]["default_target"] == 60000
    assert ok(client.get("/api/dashboard"))["target"]["target"] == 60000

    # --- Expenses: recurring rent from the 1st, a one-off today, last month's one-off doesn't count ---
    first_of_month = clock.month_start(clock.today())
    last_month_day = first_of_month - timedelta(days=1)
    rent = ok(
        client.post(
            "/api/expenses",
            headers=h,
            json={"category": " Rent ", "amount": 25000, "recurring": True, "date": f"{first_of_month}"},
        )
    )["id"]
    assert client.post("/api/expenses", json={"category": "x", "amount": 1}).status_code == 401
    ok(
        client.post(
            "/api/expenses", headers=h, json={"category": "ingredients", "amount": 4200, "note": "Nutella"}
        )
    )
    ok(
        client.post(
            "/api/expenses",
            headers=h,
            json={"category": "packaging", "amount": 900, "date": f"{last_month_day}"},
        )
    )
    exp = ok(client.get(f"/api/expenses?month={month}"))
    assert (exp["total"], exp["recurringTotal"], exp["oneOffTotal"]) == (29200, 25000, 4200)
    assert exp["byCategory"] == [
        {"category": "rent", "amount": 25000},
        {"category": "ingredients", "amount": 4200},
    ]
    assert exp["recurring"][0] == {
        "id": rent,
        "date": f"{first_of_month}",
        "category": "rent",
        "amount": 25000,
        "note": None,
        "recurring": True,
    }
    assert exp["oneOff"][0]["note"] == "Nutella"
    assert exp["oneOff"][0]["date"] == today_s()
    assert ok(client.get("/api/expenses")) == exp  # default month is this one
    # The recurring rent also counts next month; last month only has its one-off.
    assert ok(client.get(f"/api/expenses?month={next_month}"))["total"] == 25000
    assert ok(client.get(f"/api/expenses?month={clock.month_key(last_month_day)}"))["total"] == 900


# ---------------------------------------------------------------------------------------------
# 3. A trading day
# ---------------------------------------------------------------------------------------------
def test_trading_day(client: TestClient) -> None:
    h = admin(client)
    set_module(client, h, "gst", enabled=True, settings={"rate": 5})  # discount cap stays at 20%
    menu = menu_items(client)
    nutella, duo, classic = menu["W03"], menu["C02"], menu["W01"]
    overload, bites = menu["C03"], menu["M01"]
    day = f"WB{clock.today():%y%m%d}"

    def bill(body: Json) -> Json:
        order: Json = ok(client.post("/api/orders", json=body))
        return order

    # A: two Nutellas and a combo, UPI takeaway, ₹50 off (cap is 20% of 607 = 121.40).
    a = bill(
        {
            "items": [{"item_id": nutella["id"], "qty": 2}, {"item_id": duo["id"]}],
            "payment_method": "upi",
            "order_type": "takeaway",
            "discount": 50,
            "customer_name": "Ravi",
        }
    )
    assert_bill(a, expected_bill([(189, 2), (229, 1)], discount=50, gst=5))
    assert a["bill_no"] == f"{day}-001"
    assert [(i["name"], i["category"], i["price"], i["qty"]) for i in a["items"]] == [
        ("Nutella Waffle", "Waffle", 189, 2),
        ("Waffle Duo", "Combo", 229, 1),
    ]
    assert (a["status"], a["source"], a["customer_name"], a["customer_phone"]) == (
        "paid",
        "counter",
        "Ravi",
        None,
    )
    assert a["created_at"][:10] == today_s()

    # B: one Classic, cash, dine-in (the defaults are cash and dine-in).
    b = bill({"items": [{"item_id": classic["id"]}]})
    assert_bill(b, expected_bill([(129, 1)], gst=5))  # 129 + 6.45
    assert (b["payment_method"], b["order_type"], b["bill_no"]) == ("cash", "dine-in", f"{day}-002")

    # Over the 20% cap: refused, with the cap in the message, and no bill number used up.
    over = client.post("/api/orders", json={"items": [{"item_id": classic["id"]}], "discount": 26})
    assert over.status_code == 400
    assert over.json()["error"].startswith("Discount can be at most 20% of the bill")

    # C: Chocolate Overload delivery by card, discount exactly at the cap (20% of 259 = 51.80).
    c = bill(
        {
            "items": [{"item_id": overload["id"]}],
            "payment_method": "card",
            "order_type": "delivery",
            "discount": 51.8,
            "customer_phone": "9876543210",
            "delivery_address": "Tower B, Flat 402",
            "note": "Ring twice",
        }
    )
    assert_bill(c, expected_bill([(259, 1)], discount=51.8, gst=5))
    assert (c["delivery_address"], c["note"], c["bill_no"]) == (
        "Tower B, Flat 402",
        "Ring twice",
        f"{day}-003",
    )

    # D: the client tries to set its own prices and totals; the server ignores them.
    d = bill(
        {
            "items": [{"item_id": bites["id"], "qty": 4, "price": 1, "name": "Free bites"}],
            "subtotal": 1,
            "tax": 0,
            "total": 1,
            "status": "cancelled",
            "bill_no": "HACKED",
        }
    )
    assert_bill(d, expected_bill([(89, 4)], gst=5))
    assert (d["items"][0]["price"], d["items"][0]["name"]) == (89, bites["name"])
    assert (d["status"], d["bill_no"]) == ("paid", f"{day}-004")

    # An unknown item is refused.
    unknown = client.post("/api/orders", json={"items": [{"item_id": classic["id"]}, {"item_id": 999999}]})
    assert (unknown.status_code, unknown.json()) == (400, {"error": "Unknown item 999999"})

    # E: a Nutella that gets cancelled.
    e = bill({"items": [{"item_id": nutella["id"]}], "payment_method": "upi"})
    assert e["bill_no"] == f"{day}-005"

    # F: Nutella + Classic, UPI takeaway.
    f = bill(
        {
            "items": [{"item_id": nutella["id"]}, {"item_id": classic["id"]}],
            "payment_method": "upi",
            "order_type": "takeaway",
        }
    )
    assert_bill(f, expected_bill([(189, 1), (129, 1)], gst=5))
    assert f["bill_no"] == f"{day}-006"

    # With the discounts module off, any discount is refused; without one billing still works.
    set_module(client, h, "discounts", enabled=False)
    off = client.post("/api/orders", json={"items": [{"item_id": classic["id"]}], "discount": 5})
    assert (off.status_code, off.json()) == (
        400,
        {"error": "Discounts are switched off in the admin dashboard"},
    )
    set_module(client, h, "discounts", enabled=True)

    # Cancel E (twice is harmless); unknown ids are 404.
    assert client.post(f"/api/orders/{e['id']}/cancel").status_code == 401  # needs the owner
    cancelled = ok(client.post(f"/api/orders/{e['id']}/cancel", headers=h))
    assert cancelled["status"] == "cancelled"
    assert {k: v for k, v in cancelled.items() if k != "status"} == {
        k: v for k, v in e.items() if k != "status"
    }
    assert ok(client.post(f"/api/orders/{e['id']}/cancel", headers=h))["status"] == "cancelled"
    assert client.post("/api/orders/999999/cancel", headers=h).json() == {"error": "Not found"}

    paid = [a, b, c, d, f]
    revenue = money(sum(o["total"] for o in paid))

    # --- Bills listed for the day: newest first, cancelled included ---
    listed = ok(client.get(f"/api/orders?date={today_s()}"))
    assert [o["bill_no"] for o in listed] == [f"{day}-{n:03d}" for n in (6, 5, 4, 3, 2, 1)]
    assert [o["status"] for o in listed] == ["paid", "cancelled", "paid", "paid", "paid", "paid"]
    assert ok(client.get("/api/orders")) == listed
    assert ok(client.get(f"/api/orders?date={clock.today() - timedelta(days=1)}")) == []
    assert ok(client.get(f"/api/orders/{a['id']}")) == a
    assert client.get("/api/orders/999999").status_code == 404

    # --- Expenses for the month ---
    ok(client.post("/api/expenses", headers=h, json={"category": "rent", "amount": 20000, "recurring": True}))
    gas = ok(client.post("/api/expenses", headers=h, json={"category": "gas", "amount": 1850}))["id"]
    ok(client.post("/api/expenses", headers=h, json={"category": "ingredients", "amount": 3000.5}))
    assert client.delete(f"/api/expenses/{gas}").status_code == 401
    ok(client.delete(f"/api/expenses/{gas}", headers=h))
    assert ok(client.delete(f"/api/expenses/{gas}", headers=h)) == {"ok": True}  # unknown id: not an error
    expenses = ok(client.get("/api/expenses"))
    assert (expenses["total"], expenses["recurringTotal"], expenses["oneOffTotal"]) == (
        23000.5,
        20000,
        3000.5,
    )
    assert [x["category"] for x in expenses["oneOff"]] == ["ingredients"]
    expenses_total = 23000.5

    # --- Day-end cash-up ---
    end = ok(client.get(f"/api/day-end?date={today_s()}"))
    assert ok(client.get("/api/day-end")) == end
    assert end["date"] == today_s()
    assert end["revenue"] == pytest.approx(revenue)
    assert end["orders"] == 5
    assert end["aov"] == pytest.approx(money(revenue / 5))
    payments = {p["method"]: (p["amount"], p["orders"]) for p in end["payments"]}
    assert payments == {
        "upi": (pytest.approx(money(a["total"] + f["total"])), 2),
        "cash": (pytest.approx(money(b["total"] + d["total"])), 2),
        "card": (pytest.approx(c["total"]), 1),
    }
    assert end["cancelled"] == {"n": 1, "amount": pytest.approx(e["total"])}
    sold = {i["name"]: (i["qty"], i["revenue"], i["orders"]) for i in end["items"]}
    assert sold == {
        "Nutella Waffle": (3, 567, 2),  # the cancelled Nutella doesn't count
        "Chocolate Overload": (1, 259, 1),
        "Amul Dark Chocolate Mini Waffle": (4, 356, 1),
        "Amul Dark Chocolate Waffle": (2, 258, 2),
        "Waffle Duo": (1, 229, 1),
    }
    assert [i["revenue"] for i in end["items"]] == sorted((i["revenue"] for i in end["items"]), reverse=True)
    assert len(end["notSold"]) == 20 - 5
    assert "Nutella Waffle" not in {i["name"] for i in end["notSold"]}
    # Yesterday is empty.
    assert ok(client.get(f"/api/day-end?date={clock.today() - timedelta(days=1)}"))["orders"] == 0

    # --- Dashboard: target progress (fresh shop: nothing before today) ---
    dash = ok(client.get("/api/dashboard"))
    assert set(dash) == {"now", "today", "target", "charts", "insights", "items"}
    t = dash["target"]
    today = clock.today()
    dim = clock.days_in_month(today)
    days_left = dim - today.day + 1
    target = 100000.0
    needed_today = target / days_left
    today_remaining = max(0.0, needed_today - revenue)
    aov = revenue / 5
    expect = {
        "month": clock.month_key(today),
        "target": target,
        "daysInMonth": dim,
        "dayOfMonth": today.day,
        "daysLeft": days_left,
        "revenue": revenue,
        "orders": 5,
        "todayRevenue": revenue,
        "todayOrders": 5,
        "progressPct": money(revenue / target * 100),
        "expectedPct": money(today.day / dim * 100),
        "remaining": money(target - revenue),
        "evenDailyTarget": money(target / dim),
        "todayTarget": money(needed_today),
        "todayPct": money(revenue / needed_today * 100),
        "todayRemaining": money(today_remaining),
        "requiredDailyFromTomorrow": money((target - revenue) / (days_left - 1)) if days_left > 1 else None,
        "avgDaily": revenue,  # no completed trading days yet, so today's revenue
        "projected": money(revenue * days_left),
        "aov": money(aov),
        "ordersNeededToday": math.ceil(today_remaining / aov),
        "netProfit": money(revenue - expenses_total),
        "breakEvenDaily": money(expenses_total / dim),
        "breakEvenRemainingDaily": money(max(0.0, expenses_total - revenue) / days_left),
    }
    if days_left == 1:
        expect["requiredDailyFromTomorrow"] = money(target - revenue)
    for key, value in expect.items():
        assert t[key] == (value if isinstance(value, str) else pytest.approx(value)), key
    assert t["expenses"]["total"] == expenses_total
    assert t["expenses"]["byCategory"][0] == {"category": "rent", "amount": 20000}

    # --- Charts ---
    charts = dash["charts"]
    assert set(charts) == {"hourly", "daily", "weekly", "monthly", "categorySplit", "paymentSplit", "weekday"}
    assert sum(r["today"] for r in charts["hourly"]) == pytest.approx(revenue)
    assert sum(r["todayOrders"] for r in charts["hourly"]) == 5
    assert [r["hour"] for r in charts["hourly"]] == list(
        range(charts["hourly"][0]["hour"], charts["hourly"][-1]["hour"] + 1)
    )
    assert len(charts["daily"]) == dim
    today_row = charts["daily"][today.day - 1]
    assert (today_row["date"], today_row["orders"]) == (today_s(), 5)
    assert today_row["revenue"] == today_row["cumulative"] == pytest.approx(revenue)
    assert charts["daily"][-1]["pace"] == pytest.approx(target)
    assert all(r["revenue"] is None for r in charts["daily"][today.day :])
    assert len(charts["weekly"]) == 12
    assert charts["weekly"][-1]["start"] == f"{clock.start_of_week(today)}"
    assert (charts["weekly"][-1]["revenue"], charts["weekly"][-1]["orders"]) == (pytest.approx(revenue), 5)
    assert len(charts["monthly"]) == 12
    this_month = charts["monthly"][-1]
    assert this_month["key"] == clock.month_key(today)
    assert (this_month["revenue"], this_month["orders"]) == (pytest.approx(revenue), 5)
    assert (this_month["target"], this_month["expenses"]) == (target, expenses_total)
    assert charts["categorySplit"] == [
        {"name": "Waffle", "value": 567 + 258, "qty": 5},
        {"name": "Combo", "value": 229 + 259, "qty": 2},
        {"name": "Mini Waffle", "value": 356, "qty": 4},
    ]
    split = {p["name"]: (p["value"], p["orders"]) for p in charts["paymentSplit"]}
    assert split == {method: (amount, n) for method, (amount, n) in payments.items()}
    split_values = [r["value"] for r in charts["paymentSplit"]]
    assert split_values == sorted(split_values, reverse=True)  # biggest first
    assert [r["day"] for r in charts["weekday"]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert all(r["average"] == 0 for r in charts["weekday"])  # nothing before today

    # --- Insights ---
    insights = dash["insights"]
    assert insights
    assert all(
        set(i) == {"tone", "title", "text"} and i["tone"] in {"good", "warn", "info"} for i in insights
    )
    assert "No sales yet this month" not in {i["title"] for i in insights}
    assert any("Nutella" in i["title"] + i["text"] for i in insights)

    # --- Item stats: the same numbers for every period on a one-day-old shop ---
    line_total = 567 + 259 + 356 + 258 + 229
    tomorrow = f"{today + timedelta(days=1)}"
    starts = {
        "today": today_s(),
        "week": f"{today - timedelta(days=6)}",
        "month": f"{clock.month_start(today)}",
        "30d": f"{today - timedelta(days=29)}",
        "all": "0000-00-00",
    }
    for period, start in starts.items():
        stats = ok(client.get(f"/api/items/stats?period={period}"))
        assert (stats["period"], stats["from"], stats["to"]) == (period, start, tomorrow)
        assert len(stats["items"]) == 20
        assert stats["bestSeller"]["name"] == "Nutella Waffle"  # most revenue: 567
        assert stats["mostPopular"]["name"] == "Amul Dark Chocolate Mini Waffle"  # most units: 4
        assert stats["customerFavourite"]["name"] == "Nutella Waffle"  # 2 bills, ties W01 on more revenue
        n = stats["bestSeller"]
        assert (n["qty"], n["orders"], n["revenue"]) == (3, 2, 567)
        assert n["share"] == pytest.approx(money(567 / line_total * 100))
        assert n["margin"] == pytest.approx(money((189 - 67) / 189 * 100))
        assert [i["name"] for i in stats["topByRevenue"]] == [
            "Nutella Waffle",
            "Amul Dark Chocolate Mini Waffle",
            "Chocolate Overload",
            "Amul Dark Chocolate Waffle",
            "Waffle Duo",
        ]
        assert [i["qty"] for i in stats["topByQty"]] == [4, 3, 2, 1, 1]
        assert len(stats["slowMovers"]) == 5
        assert all(i["qty"] == 0 and i["active"] for i in stats["slowMovers"])
        assert sum(i["share"] for i in stats["items"]) == pytest.approx(100, abs=0.05)
    assert dash["items"] == ok(client.get("/api/items/stats?period=month"))
    assert ok(client.get("/api/dashboard?period=today"))["items"]["period"] == "today"


def test_gst_is_rounded_half_up(client: TestClient) -> None:
    h = admin(client)
    set_module(client, h, "gst", enabled=True, settings={"rate": 5})
    item = {"code": "SH01", "name": "Choco Shot", "category_id": 1, "price": 129.5}
    item_id = ok(client.post("/api/items", headers=h, json=item))["id"]
    order = ok(client.post("/api/orders", json={"items": [{"item_id": item_id}]}))
    # 129.50 x 5% = 6.475, which rounds half-up to 6.48.
    assert order["tax"] == 6.48
    assert order["total"] == 135.98


def test_discount_cap_message_uses_indian_rupees(client: TestClient) -> None:
    family = menu_items(client)["C05"]["id"]  # 569 x 999 = 5,68,431; 20% cap = 1,13,686.20
    r = client.post("/api/orders", json={"items": [{"item_id": family, "qty": 999}], "discount": 200000})
    assert r.status_code == 400
    assert r.json()["error"] == "Discount can be at most 20% of the bill (₹1,13,686)"


def test_huge_but_valid_order(client: TestClient) -> None:
    family = menu_items(client)["C05"]["id"]
    order = ok(
        client.post("/api/orders", json={"items": [{"item_id": family, "qty": 999}], "discount": 113686})
    )
    assert_bill(order, expected_bill([(569, 999)], discount=113686))
    # The same item on two lines stays as two lines.
    twice = ok(
        client.post("/api/orders", json={"items": [{"item_id": family}, {"item_id": family, "qty": 2}]})
    )
    assert [i["qty"] for i in twice["items"]] == [1, 2]
    assert twice["subtotal"] == 569 * 3


def test_hidden_items_cannot_be_billed(client: TestClient) -> None:
    h = admin(client)
    nutella = menu_items(client)["W03"]["id"]
    ok(client.post("/api/orders", json={"items": [{"item_id": nutella}]}))
    assert ok(client.delete(f"/api/items/{nutella}", headers=h))["hidden"] is True
    r = client.post("/api/orders", json={"items": [{"item_id": nutella}]})
    assert (r.status_code, r.json()) == (
        400,
        {"error": "Nutella Waffle is hidden from the menu and can't be billed"},
    )
    # Bringing it back makes it billable again.
    item = {
        k: v for k, v in menu_items(client)["W03"].items() if k in ("code", "name", "category_id", "price")
    }
    ok(client.put(f"/api/items/{nutella}", headers=h, json={**item, "active": True}))
    assert ok(client.post("/api/orders", json={"items": [{"item_id": nutella}]}))["total"] == 189


# ---------------------------------------------------------------------------------------------
# 4. Edge cases and validation
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "case",
    [
        # Months and dates
        ("GET", "/api/expenses?month=2026-13", None, 400, "Enter a valid month (YYYY-MM)"),
        ("GET", "/api/expenses?month=26-11", None, 400, "Enter a valid month (YYYY-MM)"),
        ("GET", "/api/expenses?month=2026-1", None, 400, "Enter a valid month (YYYY-MM)"),
        ("GET", "/api/orders?date=2026-02-30", None, 422, "date: "),
        ("GET", "/api/orders?date=yesterday", None, 422, "date: "),
        ("GET", "/api/day-end?date=18-11-2026", None, 422, "date: "),
        ("GET", "/api/dashboard?period=year", None, 422, "period: "),
        ("GET", "/api/items/stats?period=1y", None, 422, "period: "),
        # Orders
        ("POST", "/api/orders", {"items": []}, 400, "The order is empty"),
        ("POST", "/api/orders", {}, 422, "items: Field required"),
        ("POST", "/api/orders", {"items": "W05"}, 422, "items: "),
        ("POST", "/api/orders", {"items": [{"item_id": 1, "qty": 0}]}, 422, "items.0.qty: "),
        ("POST", "/api/orders", {"items": [{"item_id": 1, "qty": -2}]}, 422, "items.0.qty: "),
        (
            "POST",
            "/api/orders",
            {"items": [{"item_id": 1, "qty": 1000}]},
            422,
            "items.0.qty: Input should be less than or equal to 999",
        ),
        ("POST", "/api/orders", {"items": [{"item_id": 1, "qty": 1.5}]}, 422, "items.0.qty: "),
        ("POST", "/api/orders", {"items": [{"item_id": "abc"}]}, 422, "items.0.item_id: "),
        ("POST", "/api/orders", {"items": [{"qty": 1}]}, 422, "items.0.item_id: Field required"),
        ("POST", "/api/orders", {"items": [{"item_id": 1}], "discount": -10}, 422, "discount: "),
        ("POST", "/api/orders", {"items": [{"item_id": 1}], "discount": "lots"}, 422, "discount: "),
        (
            "POST",
            "/api/orders",
            {"items": [{"item_id": 1}], "payment_method": "bitcoin"},
            422,
            "payment_method: ",
        ),
        ("POST", "/api/orders", {"items": [{"item_id": 1}], "order_type": "drive-thru"}, 422, "order_type: "),
        ("POST", "/api/orders", {"items": [{"item_id": 1}], "source": "zomato"}, 422, "source: "),
        (
            "POST",
            "/api/orders",
            {"items": [{"item_id": 1}], "customer_name": "x" * 81},
            422,
            "customer_name: ",
        ),
        ("GET", "/api/orders/abc", None, 422, "order_id: "),
        ("GET", "/api/orders/9223372036854775808", None, 404, "Not found"),  # too big for SQLite
        # Size limits
        ("POST", "/api/orders", {"items": [{"item_id": 1}], "discount": 10_000_001}, 422, "discount: "),
        ("POST", "/api/orders", {"items": [{"item_id": 1}] * 101}, 422, "items: "),
        ("POST", "/api/orders", {"items": [{"item_id": 1}], "note": "x" * 301}, 422, "note: "),
        ("GET", "/api/orders/999999", None, 404, "Not found"),
        # Expenses
        # Sign-in
        ("POST", "/api/admin/login", {"pin": "0000"}, 401, "Wrong PIN"),
        ("POST", "/api/admin/login", {"pin": ""}, 422, "pin: "),
        ("POST", "/api/admin/login", {"pin": "123456789"}, 422, "pin: "),
        ("POST", "/api/admin/login", {}, 422, "pin: Field required"),
        # Unknown routes and methods still answer JSON errors
        ("GET", "/api/nope", None, 404, "Not Found"),
        ("DELETE", "/api/menu", None, 405, "Method Not Allowed"),
        ("GET", "/api/integrations/whatsapp", None, 405, "Method Not Allowed"),
    ],
)
def test_public_validation(client: TestClient, case: tuple[str, str, Json | None, int, str]) -> None:
    method, path, body, status, error = case
    r = client.request(method, path, json=body)
    assert r.status_code == status, r.text
    message = r.json()["error"]
    assert message.startswith(error) if error.endswith(": ") else message == error
    # Nothing was saved by the failed request.
    assert ok(client.get("/api/orders")) == []
    assert ok(client.get("/api/expenses"))["total"] == 0


def test_body_that_is_not_json(client: TestClient) -> None:
    r = client.post("/api/orders", content=b"items=1", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert r.json()["error"]


@pytest.mark.parametrize(
    "case",
    [
        # Targets, cancelling and expenses (owner only)
        ("PUT", "/api/targets/November", {"amount": 1}, 400, "Enter a valid month (YYYY-MM)"),
        ("PUT", "/api/targets/2026-00", {"amount": 1}, 400, "Enter a valid month (YYYY-MM)"),
        ("PUT", "/api/targets/2026-11", {"amount": 0}, 422, "amount: Input should be greater than 0"),
        ("PUT", "/api/targets/2026-11", {"amount": -5}, 422, "amount: Input should be greater than 0"),
        ("PUT", "/api/targets/2026-11", {}, 422, "amount: Field required"),
        ("PUT", "/api/targets/2026-11", {"amount": "lots"}, 422, "amount: "),
        ("POST", "/api/orders/999999/cancel", None, 404, "Not found"),
        ("POST", "/api/expenses", {"category": "", "amount": 10}, 422, "category: "),
        ("POST", "/api/expenses", {"category": "x" * 31, "amount": 10}, 422, "category: "),
        ("POST", "/api/expenses", {"category": "rent", "amount": 0}, 422, "amount: "),
        ("POST", "/api/expenses", {"category": "rent"}, 422, "amount: Field required"),
        ("POST", "/api/expenses", {"category": "rent", "amount": 1, "date": "2026-13-01"}, 422, "date: "),
        ("DELETE", "/api/expenses/abc", None, 422, "expense_id: "),
        ("PUT", "/api/targets/2026-11", {"amount": 100_000_001}, 422, "amount: "),
        ("POST", "/api/expenses", {"category": "rent", "amount": 10_000_001}, 422, "amount: "),
        ("POST", "/api/expenses", {"category": "rent", "amount": 1, "note": "x" * 301}, 422, "note: "),
        ("POST", "/api/orders/9223372036854775808/cancel", None, 404, "Not found"),
        # Modules
        ("PUT", "/api/admin/modules/nope", {"enabled": True}, 404, "Unknown module 'nope'"),
        ("PUT", "/api/admin/modules/admin", {"settings": {}}, 400, "Change the PIN with POST /api/admin/pin"),
        (
            "PUT",
            "/api/admin/modules/admin",
            {"enabled": False},
            400,
            "Change the PIN with POST /api/admin/pin",
        ),
        (
            "PUT",
            "/api/admin/modules/billing",
            {"enabled": False},
            400,
            "'Billing' is a core module and can't be switched off",
        ),
        (
            "PUT",
            "/api/admin/modules/shop",
            {"enabled": False},
            400,
            "'Shop details' is a core module and can't be switched off",
        ),
        (
            "PUT",
            "/api/admin/modules/theme",
            {"enabled": False},
            400,
            "'Look' is a core module and can't be switched off",
        ),
        (
            "PUT",
            "/api/admin/modules/targets",
            {"enabled": False},
            400,
            "'Targets & insights' is a core module and can't be switched off",
        ),
        (
            "PUT",
            "/api/admin/modules/gst",
            {"settings": {"rate": 50}},
            400,
            "rate: Input should be less than or equal to 28",
        ),
        (
            "PUT",
            "/api/admin/modules/discounts",
            {"settings": {"max_discount_pct": -1}},
            400,
            "max_discount_pct: ",
        ),
        ("PUT", "/api/admin/modules/shop", {"settings": {"open_hour": 24}}, 400, "open_hour: "),
        ("PUT", "/api/admin/modules/gst", {"settings": "rate=5"}, 422, "settings: "),
        (
            "PUT",
            "/api/admin/modules/shop",
            {"settings": {"logo": "https://evil.example.com/l.png"}},
            400,
            "logo: ",
        ),
        (
            "PUT",
            "/api/admin/modules/targets",
            {"settings": {"expense_categories": [f"c{i}" for i in range(31)]}},
            400,
            "expense_categories: ",
        ),
        (
            "PUT",
            "/api/admin/modules/whatsapp",
            {"settings": {"delivery_buildings": [f"T{i}" for i in range(51)]}},
            400,
            "delivery_buildings: ",
        ),
        ("PUT", "/api/admin/modules/gst", {"enabled": "maybe"}, 422, "enabled: "),
        # PIN
        ("POST", "/api/admin/pin", {"new_pin": "12"}, 400, "PIN must be 4 to 8 digits"),
        ("POST", "/api/admin/pin", {"new_pin": "abcd"}, 400, "PIN must be 4 to 8 digits"),
        ("POST", "/api/admin/pin", {"new_pin": "123456789"}, 400, "PIN must be 4 to 8 digits"),
        ("POST", "/api/admin/pin", {"new_pin": "1234"}, 400, "Choose a PIN other than the default 1234"),
        ("POST", "/api/admin/pin", {}, 422, "new_pin: Field required"),
        # Menu
        ("POST", "/api/categories", {"name": "   "}, 422, "name: Category name is required"),
        ("POST", "/api/categories", {"name": "x" * 61}, 422, "name: "),
        ("PUT", "/api/categories/999999", {"name": "Shakes"}, 404, "Category not found"),
        ("DELETE", "/api/categories/999999", None, 404, "Category not found"),
        ("DELETE", "/api/categories/1", None, 400, "Move or remove this category's items first"),
        ("POST", "/api/categories/reorder", {"ids": []}, 422, "ids: "),
        ("POST", "/api/items/reorder", {"ids": list(range(1, 1002))}, 422, "ids: "),
        (
            "POST",
            "/api/items",
            {"code": "X1", "name": "X", "category_id": 1, "price": 10_000_001},
            422,
            "price: ",
        ),
        (
            "POST",
            "/api/items",
            {"code": "X1", "name": "X", "category_id": 1, "price": 1, "cost": 10_000_001},
            422,
            "cost: ",
        ),
        (
            "POST",
            "/api/items",
            {
                "code": "X1",
                "name": "X",
                "category_id": 1,
                "price": 1,
                "image": "https://evil.example.com/x.png",
            },
            422,
            "image: ",
        ),
        ("POST", "/api/categories/reorder", {"ids": [1, 99999]}, 400, "Unknown id 99999"),
        ("POST", "/api/items/reorder", {"ids": [99999]}, 400, "Unknown id 99999"),
        ("POST", "/api/items", {"code": "X1", "name": "X", "category_id": 1, "price": -1}, 422, "price: "),
        ("POST", "/api/items", {"code": "X1", "category_id": 1, "price": 1}, 422, "name: Field required"),
        (
            "POST",
            "/api/items",
            {"code": "W01", "name": "X", "category_id": 1, "price": 1},
            400,
            "That item ID is already used",
        ),
        (
            "PUT",
            "/api/items/999999",
            {"code": "X1", "name": "X", "category_id": 1, "price": 1},
            404,
            "Item not found",
        ),
        (
            "PUT",
            "/api/items/abc",
            {"code": "X1", "name": "X", "category_id": 1, "price": 1},
            422,
            "item_id: ",
        ),
        (
            "PUT",
            "/api/items/2",
            {"code": "W01", "name": "X", "category_id": 1, "price": 1},
            400,
            "That item ID is already used",
        ),
    ],
)
def test_admin_validation(client: TestClient, case: tuple[str, str, Json | None, int, str]) -> None:
    method, path, body, status, error = case
    h = admin(client)
    before_menu = ok(client.get("/api/menu"))
    before_cfg = config(client)
    before_expenses = ok(client.get("/api/expenses"))
    r = client.request(method, path, headers=h, json=body)
    assert r.status_code == status, r.text
    message = r.json()["error"]
    assert message.startswith(error) if error.endswith(": ") else message == error
    # The failed request changed nothing, and the token still works (no accidental PIN change).
    assert ok(client.get("/api/menu")) == before_menu
    assert config(client) == before_cfg
    assert ok(client.get("/api/expenses")) == before_expenses
    assert ok(client.get("/api/admin/modules", headers=h))


# ---------------------------------------------------------------------------------------------
# 5. Google Sheet sync and backup
# ---------------------------------------------------------------------------------------------
def test_sync_settings_and_script(client: TestClient) -> None:
    # Only the owner can trigger a sync. Off by default: the sync is skipped.
    assert client.post("/api/sync").status_code == 401
    h = admin(client)
    off = ok(client.post("/api/sync", headers=h))
    assert off == {
        "ok": False,
        "skipped": True,
        "at": None,
        "message": "Google Sheet sync is switched off in the admin dashboard.",
    }

    # On but not configured: not skipped, and it says what to fill in. No network call is made.
    view = set_module(client, h, "google_sheets", enabled=True)
    assert view["readonly_fields"] == ["last_sync"]
    on = ok(client.post("/api/sync", headers=h))
    assert (on["ok"], on["skipped"], on["at"]) == (False, False, None)
    assert on["message"] == "Add the web app URL and secret in Admin → Modules → Google Sheet sync."

    # Settings are validated: only an Apps Script web app URL, and a secret of 16+ characters.
    bad_url = client.put(
        "/api/admin/modules/google_sheets",
        headers=h,
        json={"settings": {"web_app_url": "https://evil.example.com/exec"}},
    )
    assert bad_url.status_code == 400
    assert bad_url.json()["error"].startswith("web_app_url:")
    short = client.put("/api/admin/modules/google_sheets", headers=h, json={"settings": {"secret": "short"}})
    assert short.status_code == 400
    assert short.json()["error"].startswith("secret:")

    # A URL alone is still "not configured" (so no network call either).
    url = "https://script.google.com/macros/s/AKfyc-example/exec"
    set_module(client, h, "google_sheets", settings={"web_app_url": url, "last_sync": "2000-01-01 00:00:00"})
    assert ok(client.post("/api/sync", headers=h))["message"].startswith("Add the web app URL and secret")
    # With the secret set, switch sync off again before anything could reach Google.
    shared = "a-long-shared-text-for-the-script"
    view = set_module(client, h, "google_sheets", enabled=False, settings={"secret": shared})
    assert view["values"]["web_app_url"] == url
    assert view["values"]["secret"] == shared  # the admin form shows it
    assert view["values"]["last_sync"] == ""  # read-only: ignored when sent
    public = config(client)["modules"]["google_sheets"]["settings"]
    assert "secret" not in public  # the POS screens never see it
    assert public["web_app_url"] == url
    assert ok(client.post("/api/sync", headers=h))["skipped"] is True

    # The Apps Script to paste into the sheet: admin only, plain text.
    assert client.get("/api/admin/google-sheet/script").status_code == 401
    script = client.get("/api/admin/google-sheet/script", headers=h)
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/plain")
    assert "function doPost" in script.text


def test_backup_contains_the_orders(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/api/backup").status_code == 401
    h = admin(client)
    set_module(client, h, "gst", enabled=True)
    w03 = menu_items(client)["W03"]["id"]
    kept = ok(
        client.post("/api/orders", json={"items": [{"item_id": w03, "qty": 2}], "payment_method": "upi"})
    )
    gone = ok(client.post("/api/orders", json={"items": [{"item_id": w03}]}))
    ok(client.post(f"/api/orders/{gone['id']}/cancel", headers=h))
    ok(client.post("/api/expenses", headers=h, json={"category": "rent", "amount": 25000, "recurring": True}))

    r = client.get("/api/backup", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert f'filename="waffle-bros-backup-{today_s()}.db"' in r.headers["content-disposition"]
    assert r.content.startswith(b"SQLite format 3\x00")

    copy = tmp_path / "restore" / "backup.db"
    copy.parent.mkdir()
    copy.write_bytes(r.content)
    with sqlite3.connect(copy) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        rows = db.execute("SELECT bill_no, total, status FROM orders ORDER BY id").fetchall()
        assert rows == [
            (kept["bill_no"], kept["total"], "paid"),
            (gone["bill_no"], gone["total"], "cancelled"),
        ]
        lines = db.execute("SELECT name, price, qty FROM order_items ORDER BY id").fetchall()
        assert lines == [("Nutella Waffle", 189.0, 2), ("Nutella Waffle", 189.0, 1)]
        assert db.execute("SELECT count(*) FROM items").fetchone() == (20,)
        assert db.execute("SELECT amount, recurring FROM expenses").fetchall() == [(25000.0, 1)]
        settings = dict(db.execute("SELECT key, value FROM settings").fetchall())
        assert settings["module:gst:enabled"] == "1"
    copy.unlink()  # the temporary copy the server made is cleaned up by the server itself


# ---------------------------------------------------------------------------------------------
# 6. Everything survives a restart
# ---------------------------------------------------------------------------------------------
def test_data_survives_restart(tmp_path: Path) -> None:
    with shop(tmp_path) as c:
        h = login(c, "1234")
        new_token = ok(c.post("/api/admin/pin", headers=h, json={"new_pin": "97531"}))["token"]
        h = {"Authorization": f"Bearer {new_token}"}
        set_module(c, h, "gst", enabled=True, settings={"rate": 12})
        set_module(c, h, "discounts", enabled=False)
        set_module(c, h, "shop", settings={"shop_name": "WB Kolar"})
        shakes = ok(c.post("/api/categories", headers=h, json={"name": "Shakes"}))["id"]
        ok(
            c.post(
                "/api/items",
                headers=h,
                json={"code": "SH01", "name": "Oreo", "category_id": shakes, "price": 150},
            )
        )
        month = clock.month_key(clock.today())
        ok(c.put(f"/api/targets/{month}", headers=h, json={"amount": 75000}))
        ok(
            c.post(
                "/api/expenses", headers=h, json={"category": "salary", "amount": 12000, "recurring": True}
            )
        )
        sh01 = menu_items(c)["SH01"]["id"]
        first = ok(c.post("/api/orders", json={"items": [{"item_id": sh01}]}))
        second = ok(c.post("/api/orders", json={"items": [{"item_id": sh01, "qty": 2}]}))
        ok(c.post(f"/api/orders/{second['id']}/cancel", headers=h))
        assert_bill(first, expected_bill([(150, 1)], gst=12))
        before = {
            "orders": ok(c.get("/api/orders")),
            "menu": ok(c.get("/api/menu")),
            "config": config(c),
            "expenses": ok(c.get("/api/expenses")),
        }

    # A new process on the same data folder.
    with shop(tmp_path) as c:
        assert ok(c.get("/api/orders")) == before["orders"]
        assert ok(c.get("/api/menu")) == before["menu"]
        assert config(c) == before["config"]
        assert ok(c.get("/api/expenses")) == before["expenses"]
        cfg = config(c)
        assert cfg["default_pin"] is False
        assert cfg["modules"]["gst"] == {"enabled": True, "settings": {"rate": 12.0, "gstin": ""}}
        assert cfg["modules"]["discounts"]["enabled"] is False
        assert cfg["modules"]["shop"]["settings"]["shop_name"] == "WB Kolar"
        assert ok(c.get("/api/dashboard"))["target"]["target"] == 75000

        # The PIN and the signed-in session survive; the default PIN doesn't come back.
        assert ok(c.get("/api/admin/modules", headers=h))
        assert c.post("/api/admin/login", json={"pin": "1234"}).status_code == 401
        assert ok(c.post("/api/admin/login", json={"pin": "97531"}))["must_change_pin"] is False

        # The menu isn't re-seeded and bill numbers carry on from the cancelled one.
        assert len(menu_items(c)) == 21
        third = ok(c.post("/api/orders", json={"items": [{"item_id": menu_items(c)["SH01"]["id"]}]}))
        assert third["bill_no"] == f"WB{clock.today():%y%m%d}-003"
        assert ok(c.get("/api/day-end"))["cancelled"]["n"] == 1


# ---------------------------------------------------------------------------------------------
# 7. WhatsApp placeholder and the front end
# ---------------------------------------------------------------------------------------------
def test_whatsapp_placeholder(client: TestClient) -> None:
    bodies: list[Json | None] = [None, {"entry": [{"changes": []}]}]
    for body in bodies:
        r = client.post("/api/integrations/whatsapp", json=body)
        assert r.status_code == 501
        assert r.json() == {"error": "WhatsApp ordering is planned for phase 2"}
    assert ok(client.get("/api/orders")) == []


def test_front_end_not_built(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Front end not built yet" in r.text
    # Without a build there is no SPA fallback, so other paths are plain 404s.
    assert client.get("/dashboard").json() == {"error": "Not Found"}
    # The API docs are always there.
    assert client.get("/docs").status_code == 200
    assert "/api/orders" in ok(client.get("/openapi.json"))["paths"]


def _built_front_end(root: Path) -> Path:
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    (root / "secret.txt").write_text("not for you")
    return dist


def test_front_end_built(tmp_path: Path) -> None:
    dist = _built_front_end(tmp_path)
    with shop(tmp_path / "data", frontend_dist=dist) as c:
        assert c.get("/").text == "<div id=root></div>"
        assert c.get("/dashboard").text == "<div id=root></div>"  # client-side route
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/favicon.svg").text == "<svg/>"
        assert "not for you" not in c.get("/../secret.txt").text
        assert "not for you" not in c.get("/%2e%2e/secret.txt").text
        # The API still answers JSON next to the SPA.
        assert len(ok(c.get("/api/menu"))["items"]) == 20
        assert ok(c.post("/api/orders", json={"items": [{"item_id": 1}]}))["total"] == 129


def test_unknown_api_path_is_a_json_404_with_built_front_end(tmp_path: Path) -> None:
    dist = _built_front_end(tmp_path)
    with shop(tmp_path / "data", frontend_dist=dist) as c:
        r = c.get("/api/does-not-exist")
        assert r.status_code == 404
        assert r.json() == {"error": "Not Found"}


# ---------------------------------------------------------------------------------------------
# Route coverage: keep this test last
# ---------------------------------------------------------------------------------------------
def test_every_api_route_is_exercised(tmp_path: Path) -> None:
    """Every method + path in the OpenAPI schema was answered successfully by a test above."""
    this_module = {name for name in globals() if name.startswith("test_")}
    others = this_module - {"test_every_api_route_is_exercised"}
    if not others <= RAN:
        pytest.skip(f"route coverage needs the whole file; not run: {sorted(others - RAN)}")

    schema = create_app(AppConfig(data_dir=tmp_path, start_sync_loop=False)).openapi()
    documented = {(method.upper(), path) for path, ops in schema["paths"].items() for method in ops}
    assert documented, "no routes in the OpenAPI schema"
    missing = sorted(documented - HITS)
    assert not missing, f"API routes never exercised successfully in tests/test_flow.py: {missing}"
