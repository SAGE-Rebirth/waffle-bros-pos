"""FastAPI dependencies."""

from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session, sessionmaker

from waffle_pos.schemas import ErrorOut


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


def bad_request(message: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def errors(described: dict[int, str]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses=`` for the ``{"error": "..."}`` bodies a route can return, keyed by status."""
    return {code: {"model": ErrorOut, "description": text} for code, text in described.items()}


INVALID = "Validation failed: a field is missing, the wrong type or out of range (`field: reason`)."
