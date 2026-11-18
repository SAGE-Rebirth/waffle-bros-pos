"""Module registry and storage.

Each module's settings are stored as one JSON row in the ``settings`` table under
``module:<key>``, and its on/off state under ``module:<key>:enabled``.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from waffle_pos.db.models import Setting
from waffle_pos.modules import builtin
from waffle_pos.modules.base import Module, ModuleSettings

BUILTIN: tuple[Module, ...] = (
    builtin.SHOP,
    builtin.THEME,
    builtin.BILLING,
    builtin.TARGETS,
    builtin.GST,
    builtin.DISCOUNTS,
    builtin.GOOGLE_SHEETS,
    builtin.WHATSAPP,
    builtin.ADMIN,
)
REGISTRY: dict[str, Module] = {m.key: m for m in BUILTIN}


class ModuleError(ValueError):
    pass


def all_modules() -> list[Module]:
    return sorted(REGISTRY.values(), key=lambda m: (m.order, m.key))


def get_module(key: str) -> Module:
    try:
        return REGISTRY[key]
    except KeyError as e:
        raise ModuleError(f"Unknown module '{key}'") from e


def _key(module: str) -> str:
    return f"module:{module}"


def is_enabled(session: Session, key: str) -> bool:
    module = get_module(key)
    if module.core:
        return True
    row = session.get(Setting, f"{_key(key)}:enabled")
    return module.default_enabled if row is None else row.value == "1"


def set_enabled(session: Session, key: str, enabled: bool) -> None:
    module = get_module(key)
    if module.core and not enabled:
        raise ModuleError(f"'{module.name}' is a core module and can't be switched off")
    _put(session, f"{_key(key)}:enabled", "1" if enabled else "0")


def load_settings(session: Session, key: str) -> ModuleSettings:
    """The module's settings, falling back to defaults for anything missing or invalid."""
    module = get_module(key)
    row = session.get(Setting, _key(key))
    data: dict[str, Any] = {}
    if row is not None and row.value:
        try:
            data = json.loads(row.value)
        except json.JSONDecodeError:
            data = {}
    try:
        return module.settings.model_validate(data)
    except ValidationError:
        # Keep every valid field; reset only the broken ones.
        defaults = module.settings()
        good = {}
        for name, value in data.items():
            try:
                module.settings.model_validate({**defaults.model_dump(), name: value})
                good[name] = value
            except ValidationError:
                continue
        return module.settings.model_validate(good)


def settings_of[S: ModuleSettings](session: Session, key: str, model: type[S]) -> S:
    """Typed access for code: ``settings_of(db, "gst", GstSettings).rate``."""
    value = load_settings(session, key)
    if not isinstance(value, model):  # pragma: no cover - programming error
        raise TypeError(f"module {key} settings are {type(value).__name__}, not {model.__name__}")
    return value


def save_settings(
    session: Session, key: str, values: dict[str, Any], *, replace: bool = False
) -> ModuleSettings:
    """Validate and store settings. By default merges into the current values (a PATCH)."""
    module = get_module(key)
    current = {} if replace else load_settings(session, key).model_dump()
    # Internal fields (PIN hash, last sync time) can't be written through this path.
    incoming = {k: v for k, v in values.items() if k not in module.internal_fields}
    validated = module.settings.model_validate({**current, **incoming})
    _put(session, _key(key), validated.model_dump_json())
    return validated


def store_internal(session: Session, key: str, values: dict[str, Any]) -> None:
    """Write fields (including secret ones) from trusted server code, e.g. the PIN hash."""
    module = get_module(key)
    validated = module.settings.model_validate({**load_settings(session, key).model_dump(), **values})
    _put(session, _key(key), validated.model_dump_json())


def public_settings(session: Session, key: str) -> dict[str, Any]:
    """Settings safe to send to the POS screens (secrets removed)."""
    module = get_module(key)
    return load_settings(session, key).model_dump(exclude=set(module.secret_fields))


def _put(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.flush()
