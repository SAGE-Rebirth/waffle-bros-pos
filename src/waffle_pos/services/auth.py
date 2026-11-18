"""Admin PIN and short-lived admin tokens (stdlib only: scrypt + HMAC).

Until the owner sets a PIN, the default PIN ``1234`` works and the dashboard asks for a new one.
Tokens are ``<expiry>.<hmac>`` signed with a random per-install secret, so they survive restarts
and are invalidated when the PIN changes (the secret is rotated).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from sqlalchemy.orm import Session

from waffle_pos.modules.builtin import AdminSettings
from waffle_pos.modules.registry import settings_of, store_internal

DEFAULT_PIN = "1234"
MIN_PIN_LENGTH = 4


class AuthError(PermissionError):
    pass


def _hash(pin: str, salt: str) -> str:
    return hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()


def _admin(session: Session) -> AdminSettings:
    return settings_of(session, "admin", AdminSettings)


def uses_default_pin(session: Session) -> bool:
    return not _admin(session).pin_hash


def check_pin(session: Session, pin: str) -> bool:
    cfg = _admin(session)
    if not cfg.pin_hash:
        return hmac.compare_digest(pin, DEFAULT_PIN)
    return hmac.compare_digest(_hash(pin, cfg.pin_salt), cfg.pin_hash)


def set_pin(session: Session, new_pin: str) -> None:
    if not (new_pin.isdigit() and MIN_PIN_LENGTH <= len(new_pin) <= 8):
        raise AuthError(f"PIN must be {MIN_PIN_LENGTH} to 8 digits")
    if new_pin == DEFAULT_PIN:
        raise AuthError("Choose a PIN other than the default 1234")
    salt = secrets.token_hex(16)
    # Rotating the secret signs everyone out of the admin dashboard.
    store_internal(
        session,
        "admin",
        {"pin_hash": _hash(new_pin, salt), "pin_salt": salt, "token_secret": secrets.token_hex(32)},
    )


def _secret(session: Session) -> bytes:
    cfg = _admin(session)
    if not cfg.token_secret:
        store_internal(session, "admin", {"token_secret": secrets.token_hex(32)})
        cfg = _admin(session)
    return bytes.fromhex(cfg.token_secret)


def issue_token(session: Session, now: float | None = None) -> tuple[str, int]:
    expires = int((now or time.time()) + _admin(session).session_hours * 3600)
    sig = hmac.new(_secret(session), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}", expires


def verify_token(session: Session, token: str, now: float | None = None) -> bool:
    expires_s, _, sig = token.partition(".")
    if not expires_s.isdigit() or not sig:
        return False
    if int(expires_s) < (now or time.time()):
        return False
    expected = hmac.new(_secret(session), expires_s.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)
