"""End-to-end API tests on a temporary database (no network, no sync loop)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from waffle_pos import clock
from waffle_pos.app import create_app
from waffle_pos.config import AppConfig


@pytest.fixture
def api_client(tmp_path: Path) -> Iterator[TestClient]:
    config = AppConfig(data_dir=tmp_path, start_sync_loop=False, frontend_dist=tmp_path / "no-dist")
    with TestClient(create_app(config)) as client:
        yield client


def _admin(client: TestClient) -> dict[str, str]:
    """Admin headers: sign in with the default PIN and change it (the default only allows that)."""
    token = client.post("/api/admin/login", json={"pin": "1234"}).json()["token"]
    r = client.post("/api/admin/pin", headers={"Authorization": f"Bearer {token}"}, json={"new_pin": "2468"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _item_id(client: TestClient, code: str) -> int:
    items = client.get("/api/menu").json()["items"]
    return int(next(i["id"] for i in items if i["code"] == code))


def test_menu_is_seeded(api_client: TestClient) -> None:
    menu = api_client.get("/api/menu").json()
    assert [c["name"] for c in menu["categories"]] == ["Waffle", "Mini Waffle", "Bowl", "Snacks", "Combo"]
    assert len(menu["items"]) == 20
    nutella = next(i for i in menu["items"] if i["code"] == "W03")
    assert nutella["category"] == "Waffle"
    assert nutella["price"] == 189
    assert nutella["active"] is True


def test_order_is_priced_on_the_server(api_client: TestClient) -> None:
    w03, c02 = _item_id(api_client, "W03"), _item_id(api_client, "C02")
    r = api_client.post(
        "/api/orders",
        json={
            "items": [{"item_id": w03, "qty": 2}, {"item_id": c02, "qty": 1}],
            "payment_method": "upi",
            "discount": 30,
        },
    )
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["subtotal"] == 2 * 189 + 229
    assert order["discount"] == 30
    assert order["total"] == 2 * 189 + 229 - 30
    assert order["bill_no"] == f"WB{clock.today():%y%m%d}-001"
    assert len(order["created_at"]) == 19 and order["created_at"][10] == " "
    assert [(i["name"], i["qty"]) for i in order["items"]] == [("Nutella Waffle", 2), ("Waffle Duo", 1)]

    second = api_client.post("/api/orders", json={"items": [{"item_id": w03}]}).json()
    assert second["bill_no"].endswith("-002")


def test_gst_and_discount_cap(api_client: TestClient) -> None:
    h = _admin(api_client)
    api_client.put("/api/admin/modules/gst", headers=h, json={"enabled": True, "settings": {"rate": 5}})
    w01 = _item_id(api_client, "W01")  # 129
    r = api_client.post("/api/orders", json={"items": [{"item_id": w01}], "discount": 9999})
    assert r.status_code == 400
    assert "at most 20%" in r.json()["error"]
    order = api_client.post("/api/orders", json={"items": [{"item_id": w01}]}).json()
    assert order["tax"] == pytest.approx(6.45)
    assert order["total"] == pytest.approx(135.45)


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"items": []}, "empty"),
        ({"items": [{"item_id": 99999}]}, "Unknown item"),
        ({"items": [{"item_id": 1, "qty": 0}]}, "qty"),
        ({"items": [{"item_id": 1}], "payment_method": "bitcoin"}, "payment_method"),
    ],
)
def test_bad_orders_return_readable_errors(
    api_client: TestClient, body: dict[str, object], fragment: str
) -> None:
    r = api_client.post("/api/orders", json=body)
    assert r.status_code in (400, 422)
    assert fragment in r.json()["error"]


def test_cancel_removes_order_from_sales(api_client: TestClient) -> None:
    w03 = _item_id(api_client, "W03")
    order = api_client.post("/api/orders", json={"items": [{"item_id": w03}]}).json()
    assert api_client.get("/api/dashboard").json()["target"]["todayRevenue"] == 189
    assert api_client.post(f"/api/orders/{order['id']}/cancel").status_code == 401
    cancelled = api_client.post(f"/api/orders/{order['id']}/cancel", headers=_admin(api_client)).json()
    assert cancelled["status"] == "cancelled"
    assert api_client.get("/api/dashboard").json()["target"]["todayRevenue"] == 0
    listed = api_client.get(f"/api/orders?date={clock.today():%Y-%m-%d}").json()
    assert [o["status"] for o in listed] == ["cancelled"]
    assert api_client.get("/api/orders/999").status_code == 404


def test_targets_and_expenses_feed_the_dashboard(api_client: TestClient) -> None:
    h = _admin(api_client)
    month = clock.month_key(clock.today())
    target_body = {"amount": 150000, "makeDefault": True}
    assert api_client.put(f"/api/targets/{month}", headers=h, json=target_body).json()["ok"]
    assert api_client.put("/api/targets/2026-13", headers=h, json={"amount": 1}).status_code == 400
    targets = api_client.get("/api/config").json()["modules"]["targets"]["settings"]
    assert targets["default_target"] == 150000

    rent = api_client.post(
        "/api/expenses", headers=h, json={"category": "Rent", "amount": 25000, "recurring": True}
    ).json()
    api_client.post("/api/expenses", headers=h, json={"category": "ingredients", "amount": 5000})
    expenses = api_client.get(f"/api/expenses?month={month}").json()
    assert expenses["total"] == 30000
    assert expenses["recurringTotal"] == 25000
    assert expenses["recurring"][0]["category"] == "rent"

    target = api_client.get("/api/dashboard").json()["target"]
    assert target["target"] == 150000
    assert target["expenses"]["total"] == 30000
    assert target["netProfit"] == -30000

    api_client.delete(f"/api/expenses/{rent['id']}", headers=h)
    assert api_client.get("/api/expenses").json()["total"] == 5000


def test_dashboard_shapes(api_client: TestClient) -> None:
    w03 = _item_id(api_client, "W03")
    api_client.post("/api/orders", json={"items": [{"item_id": w03, "qty": 3}]})
    d = api_client.get("/api/dashboard?period=today").json()
    assert set(d) == {"now", "today", "target", "charts", "insights", "items"}
    assert set(d["charts"]) >= {
        "hourly",
        "daily",
        "weekly",
        "monthly",
        "categorySplit",
        "paymentSplit",
        "weekday",
    }
    assert d["items"]["bestSeller"]["name"] == "Nutella Waffle"
    assert d["items"]["mostPopular"]["qty"] == 3
    assert all({"tone", "title", "text"} <= set(i) for i in d["insights"])
    assert api_client.get("/api/items/stats?period=week").json()["period"] == "week"
    assert api_client.get("/api/items/stats?period=year").status_code == 422
    day = api_client.get("/api/day-end").json()
    assert day["orders"] == 1
    assert day["revenue"] == 567
    assert d["today"] == day["date"]
    cal = api_client.get("/api/calendar").json()
    assert cal["today"] == day["date"]
    assert cal["month"] == day["date"][:7]
    assert cal["revenue"] == 567
    assert next(x for x in cal["days"] if x["today"])["revenue"] == 567
    assert api_client.get("/api/calendar?month=2026-01").json()["revenue"] == 0
    for bad in ("2026-13", "2026-1", "nope"):
        assert api_client.get(f"/api/calendar?month={bad}").status_code == 422
    assert api_client.get("/api/config").json()["timezone"] == "Asia/Kolkata"


def test_menu_editing(api_client: TestClient) -> None:
    h = _admin(api_client)
    cat = api_client.post("/api/categories", headers=h, json={"name": "Shakes"}).json()["id"]
    assert api_client.post("/api/categories", headers=h, json={"name": "shakes"}).status_code == 400
    item = {"code": "sh1", "name": "Oreo Shake", "category_id": cat, "price": 149, "cost": 50}
    new_id = api_client.post("/api/items", headers=h, json=item).json()["id"]
    menu = api_client.get("/api/menu").json()
    created = next(i for i in menu["items"] if i["id"] == new_id)
    assert created["code"] == "SH1"
    assert created["category"] == "Shakes"

    assert (
        api_client.post("/api/items", headers=h, json=item).json()["error"] == "That item ID is already used"
    )
    assert api_client.put(f"/api/items/{new_id}", headers=h, json={**item, "price": 159}).json()["ok"]
    assert api_client.put("/api/items/9999", headers=h, json=item).status_code == 404

    # Unsold items are deleted; sold items are hidden so old bills stay intact.
    assert api_client.delete(f"/api/items/{new_id}", headers=h).json()["hidden"] is False
    w03 = _item_id(api_client, "W03")
    api_client.post("/api/orders", json={"items": [{"item_id": w03}]})
    assert api_client.delete(f"/api/items/{w03}", headers=h).json()["hidden"] is True
    nutella = next(i for i in api_client.get("/api/menu").json()["items"] if i["id"] == w03)
    assert nutella["active"] is False


def test_old_settings_endpoint_is_gone(api_client: TestClient) -> None:
    assert api_client.put("/api/settings", json={"shop_name": "x"}).status_code in (404, 405)


def test_sync_is_skipped_until_enabled(api_client: TestClient) -> None:
    assert api_client.post("/api/sync").status_code == 401
    r = api_client.post("/api/sync", headers=_admin(api_client)).json()
    assert r["ok"] is False
    assert r["skipped"] is True


def test_backup_is_a_sqlite_file(api_client: TestClient) -> None:
    r = api_client.get("/api/backup", headers=_admin(api_client))
    assert r.status_code == 200
    assert r.content.startswith(b"SQLite format 3")
    assert "attachment" in r.headers["content-disposition"]


def test_whatsapp_placeholder(api_client: TestClient) -> None:
    r = api_client.post("/api/integrations/whatsapp")
    assert r.status_code == 501
    assert "phase 2" in r.json()["error"]


def test_frontend_not_built_message(api_client: TestClient) -> None:
    assert "not built" in api_client.get("/").text


def test_serves_built_frontend(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    config = AppConfig(data_dir=tmp_path / "data", start_sync_loop=False, frontend_dist=dist)
    with TestClient(create_app(config)) as client:
        assert client.get("/").text == "<div id=root></div>"
        assert client.get("/dashboard").text == "<div id=root></div>"  # SPA fallback
        assert client.get("/assets/app.js").text == "console.log(1)"
        assert client.get("/favicon.svg").text == "<svg/>"
        assert client.get("/../pyproject.toml").text == "<div id=root></div>"
        assert client.get("/api/menu").status_code == 200


def test_health(api_client: TestClient) -> None:
    assert api_client.get("/api/health").json()["status"] == "ok"
