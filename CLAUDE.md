# Waffle Bros POS: notes for Claude

A locally hosted point-of-sale and revenue-target dashboard for one waffle shop in Bhopal (Waffle Bros). The owner, Abhinav, works in Python and Rust and wants architecture changes agreed with him before they're built.

## Shape of the system

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 on SQLite, Alembic. Package `src/waffle_pos/`.
  - `api/`: thin routers only: parse input, call a service, return a schema. No business logic here. `admin.py` has `GET /api/config` and the `/api/admin/*` endpoints; `deps.py` has `require_admin` (`AdminOnly`), which guards menu writes, `GET /api/backup` and the admin module endpoints.
  - `services/`: business logic. `targets.py` is pure maths (no DB) and must stay that way. `analytics.py` runs queries, `insights.py` turns numbers into tips, `orders.py` and `menu.py` handle writes, and `auth.py` handles the admin PIN (scrypt hash; default `1234` until changed; 4-8 digits) and signed tokens (changing the PIN rotates the secret, which signs everyone out). There is no `settings.py` any more: settings live in modules.
  - `modules/`: switchable features. `base.py` defines `Module` and `ModuleSettings`, `builtin.py` the shipped modules (core: `shop`, `theme`, `billing`, `targets`, and the hidden `admin`; optional: `gst` off, `discounts` on, `google_sheets` off, `whatsapp` off), `registry.py` the list (`BUILTIN`) and storage: settings as JSON in the `settings` table row `module:<key>`, the on/off flag in `module:<key>:enabled`.
  - `db/models.py`: ORM models. `migrations/`: Alembic, applied automatically on start-up.
  - `integrations/sheets.py`: Google Sheets sync (service-account JWT + httpx). Runs as a background asyncio loop.
  - `schemas.py`: Pydantic models. **JSON field names are a contract with the React screens**; don't rename them without updating `frontend/src`.
  - `clock.py`: all times are shop-local naive datetimes (`WB_TIMEZONE`, default Asia/Kolkata). Always use `clock.now()` / `clock.today()`, never `datetime.now()`.
- **Frontend:** React + Vite + Recharts in `frontend/`. FastAPI serves the built `frontend/dist`. Pages: `Billing`, `Dashboard`, `DayEnd`, `Admin` (at `#admin`: PIN pad, then tabs Menu / Modules / Security / Backup). The POS screens read `GET /api/config` (`frontend/src/config.jsx`) for theme colours, shop name, payment methods, order types, the GST line, the discount cap and the bill footer.
- **Data:** one SQLite file, `data/waffle-bros.db` (or `/data` in Docker). Settings the owner edits live in the `settings` table as module rows (see `modules/`); process config is `WB_*` env vars (`config.py`).
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
- **Admin-only endpoints:** add `dependencies=[AdminOnly]` and `ADMIN_401` in `responses=errors(...)`, and mark it **(Admin)** in `docs/API.md`. Billing, reading and reports stay open so the counter works without a PIN.
- **Workflow:** branch, then PR to `main`. CI (`.github/workflows/ci.yml`) runs the backend checks, the frontend build and the Docker build.

## Adding a module

1. Write a settings model (subclass `ModuleSettings`) in `modules/builtin.py`, or in its own `modules/<key>.py` for anything bigger. Give every field a default and `Field(title=..., description=...)`: the Admin page draws the form straight from the Pydantic JSON Schema, so no frontend change is needed. Limits (`ge`, `le`, `max_length`), `Literal` enums and lists all show up in the form. Use `json_schema_extra={"format": "color"}` (or the `Color` type) for a colour picker and `{"format": "image"}` for an image upload.
2. Create `Module(key, name, description, SettingsModel, ...)`: set `core=True` if it can't be switched off, `default_enabled`, `icon` and `order`. List `secret_fields` (left out of the public `GET /api/config`, e.g. `google_sheets.credentials_path`) and `internal_fields` (written only by server code via `registry.store_internal`, shown read-only, e.g. `google_sheets.last_sync`).
3. Add it to `registry.BUILTIN`.
4. In code, read it with `registry.is_enabled(db, "<key>")` and `registry.settings_of(db, "<key>", SettingsModel)`, never by reading `settings` rows directly. Stored values are validated on load and bad ones fall back to defaults, so renaming or removing a field is safe, but don't change a key's meaning.
5. Add tests in `tests/test_modules.py` (and `tests/test_api.py` for endpoints), and update the module table in `docs/API.md`. If it adds endpoints, follow "New/changed endpoint" above.

## Planned

- More modules as needed (the module system and admin dashboard exist; agree new features' design with the owner first).
- Phase 2: WhatsApp ordering for the apartment residents (`POST /api/integrations/whatsapp` is reserved; orders already have `source`, `order_type`, `delivery_address`).
