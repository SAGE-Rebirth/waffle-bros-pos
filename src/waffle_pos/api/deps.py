"""FastAPI dependencies."""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from waffle_pos.schemas import ErrorOut
from waffle_pos.services import auth


def get_session_factory(request: Request) -> sessionmaker[Session]:
    factory: sessionmaker[Session] = request.app.state.session_factory
    return factory


def get_session(request: Request) -> Iterator[Session]:
    """One transaction per request: committed on success, rolled back on error."""
    session = get_session_factory(request)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DB = Annotated[Session, Depends(get_session)]
SessionFactory = Annotated[sessionmaker[Session], Depends(get_session_factory)]


def bad_request(message: str, status: int = 400, headers: dict[str, str] | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail=message, headers=headers)


def errors(described: dict[int, str]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses=`` for the ``{"error": "..."}`` bodies a route can return, keyed by status."""
    return {code: {"model": ErrorOut, "description": text} for code, text in described.items()}


INVALID = "Validation failed: a field is missing, the wrong type or out of range (`field: reason`)."


def require_signed_in(db: DB, authorization: Annotated[str | None, Header()] = None) -> None:
    """Dependency: the request carries a valid ``Authorization: Bearer <token>`` from
    ``POST /api/admin/login``. Only used by ``POST /api/admin/pin``; everything else uses
    :func:`require_admin`."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token or not auth.verify_token(db, token):
        raise bad_request("Admin PIN required", 401)


def require_admin(db: DB, authorization: Annotated[str | None, Header()] = None) -> None:
    """Dependency: signed in, and the default PIN has been changed. The default 1234 is the same on
    every install, so until it's changed it only lets you set a new PIN."""
    require_signed_in(db, authorization)
    if auth.uses_default_pin(db):
        raise bad_request("Change the default PIN 1234 first (POST /api/admin/pin)", 403)


SignedIn = Depends(require_signed_in)
AdminOnly = Depends(require_admin)
ADMIN_401 = "Admin PIN required: send `Authorization: Bearer <token>` from `POST /api/admin/login`."
ADMIN_403 = "The default PIN 1234 is still set: change it with `POST /api/admin/pin` first."
