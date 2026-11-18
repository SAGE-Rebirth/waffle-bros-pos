"""Settings, Google Sheet sync, backup, and the phase 2 WhatsApp placeholder."""

import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from waffle_pos import clock
from waffle_pos.api.deps import DB, SessionFactory, bad_request
from waffle_pos.integrations import sheets
from waffle_pos.schemas import SyncResult
from waffle_pos.services.settings import EDITABLE, get_settings, set_settings

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/settings")
def read_settings(db: DB) -> dict[str, str]:
    return get_settings(db)


@router.put("/settings")
def update_settings(body: dict[str, Any], db: DB) -> dict[str, str]:
    set_settings(db, {k: "" if v is None else str(v) for k, v in body.items() if k in EDITABLE})
    return get_settings(db)


@router.post("/sync")
async def sync(factory: SessionFactory) -> SyncResult:
    try:
        return await sheets.sync_now(factory)
    except Exception as e:
        return SyncResult(ok=False, message=str(e))


@router.get("/backup")
def backup(request: Request) -> FileResponse:
    """A consistent copy of the live database, made with SQLite's online backup API."""
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


@router.post("/integrations/whatsapp", status_code=501)
def whatsapp_webhook() -> None:
    """Phase 2: WhatsApp Business webhook. Orders will be created with source='whatsapp'."""
    raise bad_request("WhatsApp ordering is planned for phase 2", 501)
