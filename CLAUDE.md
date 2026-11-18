# Waffle Bros POS: notes for Claude

A locally hosted point-of-sale and revenue-target dashboard for one waffle shop in Bhopal (Waffle Bros). The owner, Abhinav, works in Python and Rust and wants architecture changes agreed with him before they're built.

## Shape of the system

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 on SQLite, Alembic. Package `src/waffle_pos/`.
  - `api/`: thin routers only: parse input, call a service, return a schema. No business logic here.
  - `services/`: business logic. `targets.py` is pure maths (no DB) and must stay that way. `analytics.py` runs queries, `insights.py` turns numbers into tips, and `orders.py`, `menu.py` and `settings.py` handle writes.
  - `db/models.py`: ORM models. `migrations/`: Alembic, applied automatically on start-up.
  - `integrations/sheets.py`: Google Sheets sync (service-account JWT + httpx). Runs as a background asyncio loop.
  - `schemas.py`: Pydantic models. **JSON field names are a contract with the React screens**; don't rename them without updating `frontend/src`.
  - `clock.py`: all times are shop-local naive datetimes (`WB_TIMEZONE`, default Asia/Kolkata). Always use `clock.now()` / `clock.today()`, never `datetime.now()`.
- **Frontend:** React + Vite + Recharts in `frontend/`. FastAPI serves the built `frontend/dist`. Pages: `Billing`, `Dashboard`, `DayEnd`, `Settings`.
- **Data:** one SQLite file, `data/waffle-bros.db` (or `/data` in Docker). Settings the owner edits live in the `settings` table; process config is `WB_*` env vars (`config.py`).
- **API reference:** `docs/API.md` (written for humans and Claude) and `docs/openapi.json` (generated). Swagger UI runs at `/docs`.

## Commands

```bash
uv sync                                   # .venv with dev tools
uv run ruff check && uv run ruff format --check
uv run mypy                               # strict
uv run pytest                             # with coverage
uv run pre-commit run --all-files         # everything CI runs
uv run python -m waffle_pos.openapi       # regenerate docs/openapi.json after API changes
uv run python -m waffle_pos.demo          # demo data in data-demo/
WB_DATA_DIR=data-demo uv run waffle-pos   # run on demo data, http://localhost:4000
cd frontend && npm ci && npm run build    # build screens (npm run dev for hot reload on :5173)
docker compose up -d --build              # production-style run, data in the pos-data volume
```

## Making changes

- **New/changed endpoint:** add a schema in `schemas.py`, logic in `services/`, a route in `api/` with `summary=` and a docstring, tests in `tests/test_api.py`, then regenerate `docs/openapi.json` and update `docs/API.md`.
- **Database change:** edit `db/models.py`, then `uv run alembic revision --autogenerate -m "..."`, review the generated file in `migrations/versions/`, and commit it. Never edit an already-merged migration. Use batch mode (it's on) for SQLite ALTERs.
- **Money:** rupees as floats, rounded with `services.targets.money()` (2 dp, half-up). Bills are always priced on the server from the menu; never trust prices from the client.
- **Bills are history:** `order_items` copies name/category/price. Items that have been sold are hidden (`active=False`), not deleted.
- **Shop owner UI text:** plain English, Indian rupee formatting (`₹1,00,000`), via `services.fmt.inr()` on the backend.
- **Quality gates:** ruff, `mypy --strict` and pytest must pass, and new logic needs tests. Run `uv run pre-commit run --all-files` before pushing.
- **Workflow:** branch, then PR to `main`. CI (`.github/workflows/ci.yml`) runs the backend checks, the frontend build and the Docker build.

## Planned

- Admin dashboard with PIN, and a module system for features (GST, discounts, Sheets, WhatsApp). Agree the design with the owner before building.
- Phase 2: WhatsApp ordering for the apartment residents (`POST /api/integrations/whatsapp` is reserved; orders already have `source`, `order_type`, `delivery_address`).
