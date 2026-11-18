"""Settings, Google Sheet sync, backup, and the phase 2 WhatsApp placeholder."""

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from starlette.background import BackgroundTask

from waffle_pos import __version__, clock
from waffle_pos.api.deps import DB, SessionFactory, bad_request, errors
from waffle_pos.integrations import sheets
from waffle_pos.schemas import SyncResult
from waffle_pos.services.settings import EDITABLE, get_settings, set_settings

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", summary="Health check")
def health(db: DB) -> dict[str, str]:
    """Liveness/readiness probe used by Docker: the app is up and the database answers."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


SETTINGS_DOC = """Settings are a flat object of strings:

- `shop_name`, `shop_address`, `shop_phone`, `gstin`: printed on bills.
- `gst_rate`: GST percent added to every new bill, e.g. `"5"` (`"0"` = no GST).
- `default_target`: monthly revenue target in rupees for months without their own target.
- `open_hour`, `close_hour`: shop hours (0-23), the range of the hourly chart.
- `sheets_enabled` (`"1"` on, `"0"` off), `sheets_spreadsheet_id`, `sheets_credentials_path`:
  Google Sheet sync.
- `sheets_last_sync`: read-only, shop-local time of the last successful sync (`YYYY-MM-DD HH:MM:SS`).
"""


@router.get("/settings", summary="Read shop settings", description=SETTINGS_DOC)
def read_settings(db: DB) -> dict[str, str]:
    return get_settings(db)


@router.put(
    "/settings",
    summary="Change shop settings",
    description='Send only the keys to change. Values are stored as text (`5` becomes `"5"`, '
    '`null` becomes `""`; send `"1"`/`"0"` for on/off, not `true`/`false`). Unknown keys and '
    "`sheets_last_sync` are ignored. Returns every setting after the change. A new `gst_rate` "
    "applies to bills created from now on.\n\n" + SETTINGS_DOC,
    responses=errors({422: "The body is not a JSON object."}),
)
def update_settings(
    body: Annotated[
        dict[str, Any],
        Body(openapi_examples={"gst": {"summary": "Charge 5% GST", "value": {"gst_rate": "5"}}}),
    ],
    db: DB,
) -> dict[str, str]:
    set_settings(db, {k: "" if v is None else str(v) for k, v in body.items() if k in EDITABLE})
    return get_settings(db)


@router.post("/sync", summary="Sync to the Google Sheet now")
async def sync(factory: SessionFactory) -> SyncResult:
    """Push bills and expenses not yet synced (up to 500 bills per run) to the Google Sheet and
    rewrite its Daily tab (last 90 days). The same sync runs in the background every few minutes.

    Always answers 200: check `ok`. `skipped: true` means sync is turned off in settings;
    `ok: false` without `skipped` means it is not configured or failed (`message` says why);
    `at` is the shop-local time of a successful sync.
    """
    try:
        return await sheets.sync_now(factory)
    except Exception as e:
        return SyncResult(ok=False, message=str(e))


@router.get(
    "/backup",
    summary="Download a database backup",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}, "description": "The SQLite file."}},
)
def backup(request: Request) -> FileResponse:
    """A consistent copy of the live database, made with SQLite's online backup API, downloaded as
    `waffle-bros-backup-YYYY-MM-DD.db`. Safe while the shop is billing. To restore, stop the POS
    and put the file in place of `waffle-bros.db` in the data folder (`WB_DATA_DIR`).
    """
    src_path: Path = request.app.state.config.db_path
    fd, tmp_name = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tmp = Path(tmp_name)
    with sqlite3.connect(src_path) as src, sqlite3.connect(tmp) as dst:
        src.backup(dst)
    return FileResponse(
        tmp,
        media_type="application/octet-stream",
        filename=f"waffle-bros-backup-{clock.today():%Y-%m-%d}.db",
        background=BackgroundTask(tmp.unlink, missing_ok=True),
    )


@router.post(
    "/integrations/whatsapp",
    status_code=501,
    summary="WhatsApp ordering webhook (planned)",
    responses=errors({501: "Always: WhatsApp ordering is planned for phase 2."}),
)
def whatsapp_webhook() -> None:
    """Phase 2: WhatsApp Business webhook. Orders will be created with source='whatsapp'."""
    raise bad_request("WhatsApp ordering is planned for phase 2", 501)
