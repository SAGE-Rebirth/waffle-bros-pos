"""FastAPI application factory."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from waffle_pos import __version__
from waffle_pos.api import admin, dashboard, finance, menu, orders, system
from waffle_pos.config import AppConfig, get_config
from waffle_pos.db.migrate import upgrade_to_head
from waffle_pos.db.seed import seed_if_empty
from waffle_pos.db.session import make_engine, make_session_factory, session_scope
from waffle_pos.integrations import sheets
from waffle_pos.security import BodyLimit, HostCheck, SecurityHeaders
from waffle_pos.services.auth import LoginThrottle


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or get_config()
    engine = make_engine(config)
    factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        upgrade_to_head(engine)
        with session_scope(factory) as s:
            seed_if_empty(s)
        task = (
            asyncio.create_task(sheets.sync_loop(factory, config.sync_interval_seconds))
            if config.start_sync_loop
            else None
        )
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        engine.dispose()

    app = FastAPI(
        title="Waffle Bros POS",
        version=__version__,
        lifespan=lifespan,
        description=(
            "Point-of-sale and revenue-target API for the Waffle Bros shop in Bhopal. "
            "The React screens use exactly this API, so a script can do anything the cashier can.\n\n"
            "- **Base URL:** `http://localhost:4000` (or the shop computer's address on the Wi-Fi).\n"
            "- **Money:** rupees, as JSON numbers (`199.0` is Rs 199).\n"
            "- **Times:** shop-local (Asia/Kolkata by default); timestamps are `YYYY-MM-DD HH:MM:SS`, "
            "dates `YYYY-MM-DD`, months `YYYY-MM`.\n"
            '- **Errors:** JSON `{"error": "..."}` with status 400 (bad request), 404 (not found), '
            "422 (validation, `field: reason`) or 501 (not built yet).\n"
            "- **Auth:** reading and billing are open on the shop network. Menu changes, module settings "
            "and backups need the admin PIN: `POST /api/admin/login` returns a token to send as "
            "`Authorization: Bearer <token>`.\n\n"
            "Practical guide with real examples: `docs/API.md` in the repository."
        ),
        openapi_tags=[
            {"name": "menu", "description": "Categories and items: what can be billed, at what price."},
            {"name": "orders", "description": "Bills: create, list by day, look up and cancel."},
            {
                "name": "dashboard",
                "description": "Read-only numbers: target progress, charts, tips, day-end.",
            },
            {"name": "finance", "description": "Monthly revenue targets and expenses."},
            {"name": "system", "description": "Health, Google Sheet sync, backup, webhooks."},
            {
                "name": "admin",
                "description": "PIN sign-in, feature modules and their settings, and the POS config.",
            },
        ],
    )
    app.state.config = config
    app.state.session_factory = factory
    app.state.login_throttle = LoginThrottle()
    # The last one added runs first: headers wrap everything (errors too), then foreign Host
    # names are refused, then oversized bodies.
    app.add_middleware(BodyLimit, max_bytes=config.max_body_bytes)
    app.add_middleware(HostCheck, extra_hosts=config.allowed_host_list)
    app.add_middleware(SecurityHeaders)

    # The front end reads {"error": "..."} from failed requests.
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"error": exc.detail},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(OverflowError)
    async def _overflow(_: Request, __: OverflowError) -> JSONResponse:
        # e.g. /api/orders/99999999999999999999: too big for SQLite, so it can't exist.
        return JSONResponse({"error": "Not found"}, status_code=404)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        field = ".".join(str(p) for p in first.get("loc", ())[1:])
        msg = str(first.get("msg", "Invalid request")).removeprefix("Value error, ")
        return JSONResponse({"error": f"{field}: {msg}" if field else msg}, status_code=422)

    for module in (menu, orders, dashboard, finance, system, admin):
        app.include_router(module.router)

    dist = config.frontend_dist
    if (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise StarletteHTTPException(404, "Not Found")  # unknown API paths stay JSON 404s
            file = (dist / path).resolve()
            if path and file.is_file() and file.is_relative_to(dist.resolve()):
                return FileResponse(file)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def not_built() -> HTMLResponse:
            return HTMLResponse(
                "Front end not built yet. Run <code>npm ci && npm run build</code> in <code>frontend/</code>."
            )

    return app
