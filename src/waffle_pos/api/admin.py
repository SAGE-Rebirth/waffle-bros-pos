"""Admin dashboard API: PIN sign-in, feature modules and their settings, public POS config."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from waffle_pos import __version__
from waffle_pos.api.deps import ADMIN_401, ADMIN_403, DB, AdminOnly, SignedIn, bad_request, errors
from waffle_pos.integrations import sheets
from waffle_pos.modules import registry
from waffle_pos.modules.base import Module
from waffle_pos.modules.builtin import GoogleSheetsSettings
from waffle_pos.services import auth

router = APIRouter(prefix="/api", tags=["admin"])


class LoginIn(BaseModel):
    pin: str = Field(min_length=1, max_length=8)
    once: bool = Field(
        default=False,
        description="True for a token that lasts only "
        f"{auth.ONCE_SECONDS // 60} minutes: the counter's PIN prompt uses one per action, so the "
        "PIN typed at the counter is not left signed in on the tablet.",
    )


class LoginOut(BaseModel):
    token: str
    expires_at: int
    must_change_pin: bool


class PinIn(BaseModel):
    new_pin: str
    current_pin: str = Field(
        default="",
        max_length=8,
        description="The PIN in use now. Required once the default PIN has been changed, so a "
        "token left signed in on a tablet can't be used to lock the owner out.",
    )


class ModuleView(BaseModel):
    key: str
    name: str
    description: str
    icon: str
    core: bool
    enabled: bool
    settings_schema: dict[str, Any]
    values: dict[str, Any]
    readonly_fields: list[str]


class ModuleUpdate(BaseModel):
    enabled: bool | None = None
    settings: dict[str, Any] | None = None


def _hidden(module: Module) -> set[str]:
    props = module.settings.model_json_schema().get("properties", {})
    return {name for name, spec in props.items() if spec.get("hidden")}


def module_view(db: DB, module: Module) -> ModuleView:
    hidden = _hidden(module)
    schema = module.settings.model_json_schema()
    schema["properties"] = {k: v for k, v in schema.get("properties", {}).items() if k not in hidden}
    return ModuleView(
        key=module.key,
        name=module.name,
        description=module.description,
        icon=module.icon,
        core=module.core,
        enabled=registry.is_enabled(db, module.key),
        settings_schema=schema,
        values=registry.load_settings(db, module.key).model_dump(exclude=hidden),
        readonly_fields=sorted(module.internal_fields - hidden),
    )


@router.get("/config", summary="POS configuration for the screens")
def public_config(db: DB) -> dict[str, Any]:
    """Every module's on/off state and its non-secret settings. The POS screens load this at start-up."""
    return {
        "version": __version__,
        "modules": {
            m.key: {
                "enabled": registry.is_enabled(db, m.key),
                "settings": registry.public_settings(db, m.key),
            }
            for m in registry.all_modules()
            if m.key != "admin"
        },
        "default_pin": auth.uses_default_pin(db),
    }


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def _check_throttle(request: Request) -> auth.LoginThrottle:
    throttle: auth.LoginThrottle = request.app.state.login_throttle
    if wait := throttle.wait_seconds(_client(request)):
        raise bad_request(
            f"Too many wrong PINs. Try again in {wait} seconds.", 429, headers={"Retry-After": str(wait)}
        )
    return throttle


@router.post("/admin/login", summary="Sign in to the admin dashboard with the PIN")
def login(body: LoginIn, db: DB, request: Request) -> LoginOut:
    """Returns a bearer token for the admin endpoints. The default PIN is 1234 until changed, and
    with it the token can only change the PIN. After 5 wrong PINs from one device, sign-in from it
    is locked for 30 s, doubling with every further wrong PIN (429 with `Retry-After`); 30 wrong
    PINs from anywhere within 10 minutes lock sign-in for everyone for a while.

    With `once: true` the token lasts only a few minutes (the counter's PIN prompt asks for one per
    action); otherwise it lasts the admin session length (12 hours)."""
    throttle = _check_throttle(request)
    if not auth.check_pin(db, body.pin):
        throttle.failed(_client(request))
        raise bad_request("Wrong PIN", 401)
    throttle.succeeded(_client(request))
    token, expires = auth.issue_token(db, seconds=auth.ONCE_SECONDS if body.once else None)
    return LoginOut(token=token, expires_at=expires, must_change_pin=auth.uses_default_pin(db))


@router.post(
    "/admin/pin",
    summary="Change the admin PIN",
    dependencies=[SignedIn],
    responses=errors(
        {
            400: "The new PIN isn't 4-8 digits or is 1234, or `current_pin` is wrong.",
            401: ADMIN_401,
            429: "Too many wrong PINs (`Retry-After` says how many seconds to wait).",
        }
    ),
)
def change_pin(body: PinIn, db: DB, request: Request) -> LoginOut:
    """Sets a new 4-8 digit PIN. Once the default PIN has been changed, `current_pin` must be the
    PIN in use now; a wrong one counts as a wrong PIN for the sign-in lockout. Other signed-in admin
    sessions are signed out; a fresh token is returned."""
    if not auth.uses_default_pin(db):
        throttle = _check_throttle(request)
        if not auth.check_pin(db, body.current_pin):
            throttle.failed(_client(request))
            raise bad_request("Your current PIN is wrong")
        throttle.succeeded(_client(request))
    try:
        auth.set_pin(db, body.new_pin)
    except auth.AuthError as e:
        raise bad_request(str(e)) from e
    token, expires = auth.issue_token(db)
    return LoginOut(token=token, expires_at=expires, must_change_pin=False)


@router.get("/admin/modules", summary="List feature modules with settings forms", dependencies=[AdminOnly])
def list_modules(db: DB) -> list[ModuleView]:
    """Each module with its JSON Schema (used to draw the form), current values and on/off state."""
    return [module_view(db, m) for m in registry.all_modules() if m.key != "admin"]


@router.put(
    "/admin/modules/{key}", summary="Switch a module on/off or change its settings", dependencies=[AdminOnly]
)
def update_module(key: str, body: ModuleUpdate, db: DB) -> ModuleView:
    """Partial update: only the settings keys you send change. Core modules can't be switched off."""
    try:
        module = registry.get_module(key)
        if key == "admin":
            raise registry.ModuleError("Change the PIN with POST /api/admin/pin")
        if body.settings is not None:
            registry.save_settings(db, key, body.settings)
        if body.enabled is not None:
            registry.set_enabled(db, key, body.enabled)
    except registry.ModuleError as e:
        raise bad_request(str(e), 404 if "Unknown" in str(e) else 400) from e
    except ValueError as e:  # pydantic.ValidationError
        raise bad_request(_first_error(e)) from e
    return module_view(db, module)


@router.get(
    "/admin/google-sheet/script",
    summary="The Apps Script to paste into the Google Sheet",
    dependencies=[AdminOnly],
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/plain": {}}}, **errors({401: ADMIN_401, 403: ADMIN_403})},
)
def google_sheet_script(db: DB) -> str:
    """The Google Apps Script that receives the POS sync, with `SECRET` already set to the module's
    saved secret (left as the placeholder if none is saved yet). Paste it into the spreadsheet
    (Extensions → Apps Script) and deploy it as a web app; the setup steps are in the comment at the top."""
    secret = registry.settings_of(db, "google_sheets", GoogleSheetsSettings).secret
    return sheets.apps_script_source(secret)


def _first_error(e: ValueError) -> str:
    errors = getattr(e, "errors", None)
    if callable(errors):
        first = errors()[0]
        field = ".".join(str(p) for p in first.get("loc", ()))
        return f"{field}: {first.get('msg', 'invalid')}"
    return str(e)
