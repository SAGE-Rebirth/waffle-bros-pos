"""Admin PIN and short-lived admin tokens (stdlib only: scrypt + HMAC).

Until the owner sets a PIN, the default PIN ``1234`` works and the dashboard asks for a new one.
Tokens are ``<expiry>.<hmac>`` signed with a random per-install secret, so they survive restarts
and are invalidated when the PIN changes (the secret is rotated).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from waffle_pos.modules.builtin import AdminSettings
from waffle_pos.modules.registry import settings_of, store_internal

DEFAULT_PIN = "1234"
MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 8
MAX_TOKEN_LENGTH = 100
ONCE_SECONDS = 120  # a counter PIN prompt's token: enough for one action and its retry


class AuthError(PermissionError):
    pass


def _hash(pin: str, salt: str) -> str:
    return hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()


def _admin(session: Session) -> AdminSettings:
    return settings_of(session, "admin", AdminSettings)


def uses_default_pin(session: Session) -> bool:
    return not _admin(session).pin_hash


def _pin_shaped(pin: str) -> bool:
    return pin.isascii() and pin.isdigit() and MIN_PIN_LENGTH <= len(pin) <= MAX_PIN_LENGTH


def check_pin(session: Session, pin: str) -> bool:
    if not _pin_shaped(pin):  # rejects junk before spending scrypt time on it
        return False
    cfg = _admin(session)
    if not cfg.pin_hash:
        return hmac.compare_digest(pin, DEFAULT_PIN)
    return hmac.compare_digest(_hash(pin, cfg.pin_salt), cfg.pin_hash)


def set_pin(session: Session, new_pin: str) -> None:
    if not _pin_shaped(new_pin):
        raise AuthError(f"PIN must be {MIN_PIN_LENGTH} to {MAX_PIN_LENGTH} digits")
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


def issue_token(session: Session, now: float | None = None, seconds: int | None = None) -> tuple[str, int]:
    """A token valid for ``seconds`` (default: the admin session length, ``session_hours``)."""
    lifetime = _admin(session).session_hours * 3600 if seconds is None else seconds
    expires = int((now or time.time()) + lifetime)
    sig = hmac.new(_secret(session), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}", expires


def verify_token(session: Session, token: str, now: float | None = None) -> bool:
    if len(token) > MAX_TOKEN_LENGTH or not token.isascii():
        return False
    expires_s, _, sig = token.partition(".")
    if not expires_s.isdigit() or not sig:
        return False
    if int(expires_s) < (now or time.time()):
        return False
    expected = hmac.new(_secret(session), expires_s.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


# ---------- Sign-in throttling ----------
@dataclass
class _Failures:
    count: int = 0
    locked_until: float = 0.0


@dataclass
class LoginThrottle:
    """Slows down PIN guessing. A 4-digit PIN has only 10,000 values, so without this the whole
    space can be tried in minutes from any device on the shop Wi-Fi.

    Per client: ``free_tries`` wrong PINs, then a lock that doubles with every further wrong PIN
    (30 s, 60 s, ... up to 15 min). Across all clients: more than ``global_limit`` wrong PINs within
    ``global_window`` seconds locks sign-in for everyone for ``global_window`` seconds, so changing
    IP address doesn't help. A correct PIN clears that client's count. Kept in memory: a restart
    resets it, which is fine for a shop PC.
    """

    free_tries: int = 5
    base_lock: float = 30.0
    max_lock: float = 900.0
    global_limit: int = 30
    global_window: float = 600.0
    _clients: dict[str, _Failures] = field(default_factory=dict)
    _recent: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def wait_seconds(self, client: str, now: float | None = None) -> int:
        """Seconds this client must wait before trying again (0 = may try now)."""
        now = time.time() if now is None else now
        with self._lock:
            self._recent = [t for t in self._recent if t > now - self.global_window]
            waits = [0.0]
            if len(self._recent) >= self.global_limit:
                waits.append(self._recent[0] + self.global_window - now)
            failures = self._clients.get(client)
            if failures:
                waits.append(failures.locked_until - now)
            return max(0, int(max(waits) + 0.999))

    def failed(self, client: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._recent.append(now)
            failures = self._clients.setdefault(client, _Failures())
            failures.count += 1
            over = failures.count - self.free_tries
            if over >= 0:
                failures.locked_until = now + min(self.max_lock, self.base_lock * 2**over)
            if len(self._clients) > 1000:  # forget the oldest clients; keeps memory bounded
                for key in list(self._clients)[:500]:
                    del self._clients[key]

    def succeeded(self, client: str) -> None:
        with self._lock:
            self._clients.pop(client, None)
