"""Shop settings the owner edits in the app, stored as key/value rows."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from waffle_pos.db.models import Setting

DEFAULTS: dict[str, str] = {
    "shop_name": "Waffle Bros",
    "shop_address": "Bhopal",
    "shop_phone": "",
    "gstin": "",
    "gst_rate": "0",  # percent; 5% is typical for restaurants once GST-registered
    "default_target": "100000",
    "open_hour": "10",
    "close_hour": "23",
    "sheets_enabled": "0",
    "sheets_spreadsheet_id": "",
    "sheets_credentials_path": "",
    "sheets_last_sync": "",
}

EDITABLE: frozenset[str] = frozenset(DEFAULTS) - {"sheets_last_sync"}


def get_settings(session: Session) -> dict[str, str]:
    stored = {s.key: s.value for s in session.scalars(select(Setting))}
    return {**DEFAULTS, **stored}


def set_settings(session: Session, values: dict[str, str]) -> None:
    for key, value in values.items():
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
    session.flush()


def get_float(settings: dict[str, str], key: str) -> float:
    try:
        return float(settings.get(key) or DEFAULTS.get(key) or 0)
    except ValueError:
        return float(DEFAULTS.get(key) or 0)
