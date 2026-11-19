"""Feature modules, admin PIN and the admin API."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from waffle_pos.app import create_app
from waffle_pos.config import AppConfig
from waffle_pos.db.migrate import alembic_config
from waffle_pos.db.models import Setting
from waffle_pos.db.session import make_engine
from waffle_pos.modules import registry
from waffle_pos.modules.builtin import GstSettings, ShopSettings
from waffle_pos.services import auth


@pytest.fixture
def mod_client(tmp_path: Path) -> Iterator[TestClient]:
    config = AppConfig(data_dir=tmp_path, start_sync_loop=False, frontend_dist=tmp_path / "no-dist")
    with TestClient(create_app(config)) as client:
        yield client


def _login(client: TestClient, pin: str = "1234") -> dict[str, str]:
    r = client.post("/api/admin/login", json={"pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _admin(client: TestClient) -> dict[str, str]:
    """Admin headers on a fresh shop: the default PIN only allows changing it, so change it first."""
    r = client.post("/api/admin/pin", headers=_login(client), json={"new_pin": "2468"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------- registry ----------
def test_defaults_and_core_modules(db_session: Session) -> None:
    assert registry.is_enabled(db_session, "shop")
    assert not registry.is_enabled(db_session, "gst")
    assert registry.is_enabled(db_session, "discounts")
    assert registry.settings_of(db_session, "shop", ShopSettings).shop_name == "Waffle Bros"
    with pytest.raises(registry.ModuleError, match="core"):
        registry.set_enabled(db_session, "billing", False)
    with pytest.raises(registry.ModuleError, match="Unknown"):
        registry.get_module("nope")


def test_settings_merge_validate_and_survive_bad_data(db_session: Session) -> None:
    registry.save_settings(db_session, "gst", {"rate": 12})
    registry.save_settings(db_session, "gst", {"gstin": "23ABCDE1234F1Z5"})
    gst = registry.settings_of(db_session, "gst", GstSettings)
    assert (gst.rate, gst.gstin) == (12, "23ABCDE1234F1Z5")
    with pytest.raises(ValueError, match="rate"):
        registry.save_settings(db_session, "gst", {"rate": 99})

    # A hand-edited, partly broken row keeps its good fields.
    db_session.merge(Setting(key="module:shop", value='{"shop_name": "WB Arera", "open_hour": 99}'))
    shop = registry.settings_of(db_session, "shop", ShopSettings)
    assert shop.shop_name == "WB Arera"
    assert shop.open_hour == 10


def test_internal_fields_cannot_be_written_through_settings(db_session: Session) -> None:
    registry.save_settings(db_session, "admin", {"pin_hash": "deadbeef"})
    assert auth.uses_default_pin(db_session)
    assert "pin_hash" not in registry.public_settings(db_session, "admin")


# ---------- PIN and tokens ----------
def test_pin_flow(db_session: Session) -> None:
    assert auth.check_pin(db_session, "1234")
    with pytest.raises(auth.AuthError):
        auth.set_pin(db_session, "12")
    with pytest.raises(auth.AuthError):
        auth.set_pin(db_session, "1234")
    token, _ = auth.issue_token(db_session)
    assert auth.verify_token(db_session, token)
    auth.set_pin(db_session, "2468")
    assert not auth.check_pin(db_session, "1234")
    assert auth.check_pin(db_session, "2468")
    assert not auth.verify_token(db_session, token), "changing the PIN signs everyone out"


def test_tokens_expire_and_reject_tampering(db_session: Session) -> None:
    token, expires = auth.issue_token(db_session, now=1_000_000)
    assert auth.verify_token(db_session, token, now=1_000_100)
    assert not auth.verify_token(db_session, token, now=expires + 1)
    exp, sig = token.split(".")
    assert not auth.verify_token(db_session, f"{int(exp) + 999}.{sig}", now=1_000_100)
    assert not auth.verify_token(db_session, "garbage", now=1_000_100)


# ---------- admin API ----------
def test_admin_endpoints_need_the_pin(mod_client: TestClient) -> None:
    assert mod_client.get("/api/admin/modules").status_code == 401
    assert mod_client.post("/api/admin/login", json={"pin": "0000"}).status_code == 401
    bad = {"Authorization": "Bearer 1.abc"}
    assert mod_client.get("/api/admin/modules", headers=bad).status_code == 401
    item = {"code": "X1", "name": "X", "category_id": 1, "price": 10}
    assert mod_client.post("/api/items", json=item).status_code == 401
    assert mod_client.post("/api/categories", json={"name": "Shakes"}).status_code == 401
    assert mod_client.get("/api/backup").status_code == 401


def test_admin_module_listing_and_update(mod_client: TestClient) -> None:
    h = _admin(mod_client)
    mods = {m["key"]: m for m in mod_client.get("/api/admin/modules", headers=h).json()}
    assert "admin" not in mods
    assert mods["theme"]["settings_schema"]["properties"]["primary"]["format"] == "color"
    assert mods["google_sheets"]["readonly_fields"] == ["last_sync"]

    r = mod_client.put("/api/admin/modules/gst", headers=h, json={"enabled": True, "settings": {"rate": 5}})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    assert (
        mod_client.put("/api/admin/modules/gst", headers=h, json={"settings": {"rate": 50}}).status_code
        == 400
    )
    assert mod_client.put("/api/admin/modules/billing", headers=h, json={"enabled": False}).status_code == 400
    assert mod_client.put("/api/admin/modules/nope", headers=h, json={"enabled": True}).status_code == 404
    assert mod_client.put("/api/admin/modules/admin", headers=h, json={"settings": {}}).status_code == 400

    cfg = mod_client.get("/api/config").json()
    assert cfg["modules"]["gst"] == {"enabled": True, "settings": {"rate": 5.0, "gstin": ""}}
    assert "secret" not in cfg["modules"]["google_sheets"]["settings"]
    assert "admin" not in cfg["modules"]
    assert cfg["default_pin"] is False  # _admin() had to change it


def test_modules_change_billing(mod_client: TestClient) -> None:
    h = _admin(mod_client)
    item = {"items": [{"item_id": 1}]}  # Amul Dark Chocolate Waffle, 129
    assert mod_client.post("/api/orders", json=item).json()["tax"] == 0

    mod_client.put("/api/admin/modules/gst", headers=h, json={"enabled": True, "settings": {"rate": 5}})
    assert mod_client.post("/api/orders", json=item).json()["tax"] == pytest.approx(6.45)

    mod_client.put("/api/admin/modules/discounts", headers=h, json={"settings": {"max_discount_pct": 10}})
    r = mod_client.post("/api/orders", json={**item, "discount": 50})
    assert r.status_code == 400
    assert "at most 10%" in r.json()["error"]
    assert mod_client.post("/api/orders", json={**item, "discount": 12}).json()["discount"] == 12

    mod_client.put("/api/admin/modules/discounts", headers=h, json={"enabled": False})
    assert "switched off" in mod_client.post("/api/orders", json={**item, "discount": 5}).json()["error"]


def test_change_pin_via_api(mod_client: TestClient) -> None:
    h = _login(mod_client)
    assert mod_client.get("/api/admin/modules", headers=h).status_code == 403  # default PIN: change it first
    assert mod_client.post("/api/admin/pin", headers=h, json={"new_pin": "12"}).status_code == 400
    r = mod_client.post("/api/admin/pin", headers=h, json={"new_pin": "9753"})
    assert r.status_code == 200
    new_h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert mod_client.get("/api/admin/modules", headers=h).status_code == 401
    assert mod_client.get("/api/admin/modules", headers=new_h).status_code == 200
    assert mod_client.post("/api/admin/login", json={"pin": "1234"}).status_code == 401
    assert mod_client.get("/api/config").json()["default_pin"] is False


def test_category_management(mod_client: TestClient) -> None:
    h = _admin(mod_client)
    new = mod_client.post("/api/categories", headers=h, json={"name": "Shakes"}).json()["id"]
    assert (
        mod_client.put(f"/api/categories/{new}", headers=h, json={"name": "Thick Shakes"}).status_code == 200
    )
    assert mod_client.put(f"/api/categories/{new}", headers=h, json={"name": "Waffle"}).status_code == 400
    cats = mod_client.get("/api/menu").json()["categories"]
    ids = [c["id"] for c in cats]
    mod_client.post("/api/categories/reorder", headers=h, json={"ids": list(reversed(ids))})
    assert mod_client.get("/api/menu").json()["categories"][0]["name"] == "Thick Shakes"
    assert mod_client.delete(f"/api/categories/{ids[0]}", headers=h).status_code == 400  # has items
    assert mod_client.delete(f"/api/categories/{new}", headers=h).json()["ok"]

    waffles = [i["id"] for i in mod_client.get("/api/menu").json()["items"] if i["category"] == "Waffle"]
    mod_client.post("/api/items/reorder", headers=h, json={"ids": list(reversed(waffles))})
    after = [i["id"] for i in mod_client.get("/api/menu").json()["items"] if i["category"] == "Waffle"]
    assert after == list(reversed(waffles))


def test_backup_with_token(mod_client: TestClient) -> None:
    r = mod_client.get("/api/backup", headers=_admin(mod_client))
    assert r.content.startswith(b"SQLite format 3")


# ---------- data migration ----------
def test_migration_moves_flat_settings_into_modules(tmp_path: Path) -> None:
    engine = make_engine(AppConfig(data_dir=tmp_path, start_sync_loop=False))
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0001")
        conn.execute(
            sa.text("INSERT INTO settings (key, value) VALUES (:k, :v)"),
            [
                {"k": "shop_name", "v": "WB Kolar"},
                {"k": "gst_rate", "v": "5"},
                {"k": "default_target", "v": "150000"},
                {"k": "sheets_enabled", "v": "1"},
                {"k": "sheets_spreadsheet_id", "v": "abc"},
            ],
        )
        command.upgrade(cfg, "head")
    with Session(engine) as s:
        assert registry.settings_of(s, "shop", ShopSettings).shop_name == "WB Kolar"
        assert registry.is_enabled(s, "gst")
        assert registry.settings_of(s, "gst", GstSettings).rate == 5
        assert registry.is_enabled(s, "google_sheets")
        assert s.get(Setting, "shop_name") is None
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "0001")
        rows: dict[str, str] = dict(conn.execute(sa.text("SELECT key, value FROM settings")).tuples().all())
    assert rows["shop_name"] == "WB Kolar"
    assert rows["sheets_enabled"] == "1"
    engine.dispose()
