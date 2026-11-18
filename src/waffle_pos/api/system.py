"""Health, Google Sheet sync, backup, and the phase 2 WhatsApp placeholder.

Shop settings moved to feature modules: see ``api/admin.py`` (`GET /api/config`, `/api/admin/modules`).
"""

import os
import sqlite3
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy import text
from starlette.background import BackgroundTask

from waffle_pos import __version__, clock
from waffle_pos.api.deps import ADMIN_401, ADMIN_403, DB, AdminOnly, SessionFactory, bad_request, errors
from waffle_pos.integrations import sheets
from waffle_pos.schemas import SyncResult

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", summary="Health check")
def health(db: DB) -> dict[str, str]:
    """Liveness/readiness probe used by Docker: the app is up and the database answers."""
    db.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


@router.post(
    "/sync",
    summary="Sync to the Google Sheet now (Admin)",
    dependencies=[AdminOnly],
    responses=errors({401: ADMIN_401, 403: ADMIN_403}),
)
async def sync(factory: SessionFactory) -> SyncResult:
    """Push bills and expenses not yet synced (up to 500 bills per run) to the Google Sheet and
    rewrite its Daily, Items and Monthly summary tabs. The same sync runs in the background on the
    interval set in Admin → Modules → Google Sheet sync (5 minutes by default).

    Always answers 200: check `ok`. `skipped: true` means sync is switched off in the admin dashboard;
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
    dependencies=[AdminOnly],
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "The SQLite file."},
        **errors({401: ADMIN_401, 403: ADMIN_403}),
    },
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
