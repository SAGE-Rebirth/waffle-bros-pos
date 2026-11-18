"""Move flat shop settings into per-module JSON settings.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

settings = sa.table("settings", sa.column("key", sa.String), sa.column("value", sa.Text))

# legacy key -> (module, field, converter)
MAP: dict[str, tuple[str, str, type]] = {
    "shop_name": ("shop", "shop_name", str),
    "shop_address": ("shop", "shop_address", str),
    "shop_phone": ("shop", "shop_phone", str),
    "open_hour": ("shop", "open_hour", int),
    "close_hour": ("shop", "close_hour", int),
    "gstin": ("gst", "gstin", str),
    "gst_rate": ("gst", "rate", float),
    "default_target": ("targets", "default_target", float),
    "sheets_spreadsheet_id": ("google_sheets", "spreadsheet_id", str),
    "sheets_credentials_path": ("google_sheets", "credentials_path", str),
    "sheets_last_sync": ("google_sheets", "last_sync", str),
}


def upgrade() -> None:
    bind = op.get_bind()
    rows = dict(bind.execute(sa.select(settings.c.key, settings.c.value)).tuples().all())
    modules: dict[str, dict[str, object]] = {}
    for key, (module, field, conv) in MAP.items():
        if key in rows and rows[key] not in (None, ""):
            try:
                modules.setdefault(module, {})[field] = conv(rows[key])
            except ValueError:
                continue
    enabled: dict[str, str] = {}
    if "gst_rate" in rows:
        try:
            enabled["gst"] = "1" if float(rows["gst_rate"] or 0) > 0 else "0"
        except ValueError:
            enabled["gst"] = "0"
    if "sheets_enabled" in rows:
        enabled["google_sheets"] = "1" if rows["sheets_enabled"] == "1" else "0"

    for module, values in modules.items():
        bind.execute(sa.insert(settings).values(key=f"module:{module}", value=json.dumps(values)))
    for module, flag in enabled.items():
        bind.execute(sa.insert(settings).values(key=f"module:{module}:enabled", value=flag))
    legacy = [*MAP, "sheets_enabled"]
    bind.execute(sa.delete(settings).where(settings.c.key.in_(legacy)))


def downgrade() -> None:
    bind = op.get_bind()
    for module in {m for m, _, _ in MAP.values()}:
        row = bind.execute(sa.select(settings.c.value).where(settings.c.key == f"module:{module}")).first()
        values = json.loads(row[0]) if row else {}
        for key, (mod, field, _) in MAP.items():
            if mod == module and field in values:
                bind.execute(sa.insert(settings).values(key=key, value=str(values[field])))
    sheets_on = bind.execute(
        sa.select(settings.c.value).where(settings.c.key == "module:google_sheets:enabled")
    ).first()
    if sheets_on:
        bind.execute(sa.insert(settings).values(key="sheets_enabled", value=sheets_on[0]))
    gst_on = bind.execute(sa.select(settings.c.value).where(settings.c.key == "module:gst:enabled")).first()
    if gst_on and gst_on[0] != "1":  # the old app had no on/off switch: GST off meant rate 0
        bind.execute(sa.update(settings).where(settings.c.key == "gst_rate").values(value="0"))
    bind.execute(sa.delete(settings).where(settings.c.key.like("module:%")))
