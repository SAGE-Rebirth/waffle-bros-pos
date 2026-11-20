# Waffle Bros POS: notes for Claude

A locally hosted point-of-sale and revenue-target dashboard for one waffle shop in Bhopal (Waffle Bros). The owner, Abhinav, works in Python and Rust and wants architecture changes agreed with him before they're built.

## Shape of the system

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 on SQLite, Alembic. Package `src/waffle_pos/`.
  - `api/`: thin routers only: parse input, call a service, return a schema. No business logic here. `admin.py` has `GET /api/config` and the `/api/admin/*` endpoints (login is throttled). `deps.py` has `require_admin` (`AdminOnly`: signed in **and** the PIN is no longer the default 1234, else 403). It guards menu writes, cancelling a bill, targets, adding/deleting expenses, `POST /api/sync`, `GET /api/backup` and the admin module endpoints. `require_signed_in` (`SignedIn`) guards only `POST /api/admin/pin`, so a default-PIN token can change the PIN and nothing else.
  - `services/`: business logic. `targets.py` is pure maths (no DB) and must stay that way. `analytics.py` runs queries, `insights.py` turns numbers into tips, `orders.py` and `menu.py` handle writes, and `auth.py` handles the admin PIN (scrypt hash; default `1234` until changed; 4-8 digits), signed tokens (changing the PIN rotates the secret, which signs everyone out) and `LoginThrottle` (5 wrong PINs per device, then a 30 s lock doubling to 15 min, 429 + `Retry-After`; 30 wrong in 10 min locks everyone; in memory). There is no `settings.py` any more: settings live in modules.
  - `modules/`: switchable features. `base.py` defines `Module` and `ModuleSettings`, `builtin.py` the shipped modules (core: `shop`, `theme`, `billing`, `targets`, and the hidden `admin`; optional: `gst` off, `discounts` on, `google_sheets` off, `whatsapp` off), `registry.py` the list (`BUILTIN`) and storage: settings as JSON in the `settings` table row `module:<key>`, the on/off flag in `module:<key>:enabled`.
  - `db/models.py`: ORM models. `migrations/`: Alembic, applied automatically on start-up.
  - `integrations/sheets.py`: Google Sheet sync. It POSTs new rows and summaries, with a shared secret, to an Apps Script web app (`integrations/apps_script.gs`, pasted into the sheet by the owner; served by `GET /api/admin/google-sheet/script`). Runs as a background asyncio loop, one sync at a time; formula-like text is escaped with a leading apostrophe.
  - `security.py`: middlewares `HostCheck` (DNS-rebinding defence: IPs, single-word names, `*.local`, `WB_ALLOWED_HOSTS`), `BodyLimit` (413 over `WB_MAX_BODY_BYTES`, default 1,000,000) and `SecurityHeaders` (CSP, `X-Frame-Options: DENY`, `nosniff`, `no-store` on `/api`).
  - `schemas.py`: Pydantic models. **JSON field names are a contract with the React screens**; don't rename them without updating `frontend/src`. Request bodies subclass `In` (`allow_inf_nan=False`); amounts are capped at `MAX_MONEY` (₹1 crore), notes at `MAX_NOTE` (300), images at `MAX_IMAGE` (200,000 chars; `data:image/...` or a same-server path only).
  - `clock.py`: all times are shop-local naive datetimes (`WB_TIMEZONE`, default Asia/Kolkata). Always use `clock.now()` / `clock.today()`, never `datetime.now()`.
- **Frontend:** React + Vite + Recharts in `frontend/`. In Docker the `web` service (nginx, `frontend/Dockerfile` + `frontend/nginx.conf`) serves the built screens and proxies `/api`, `/docs`, `/openapi.json` to `api`; outside Docker FastAPI serves `frontend/dist` if it exists. Pages: `Billing`, `Dashboard` (with a sales calendar from `GET /api/calendar`; a day links to `#dayend?date=YYYY-MM-DD`; cards can be moved, resized and hidden in **Customise** mode via `components/DashGrid.jsx` + dnd-kit, layout saved per device in `localStorage` by `layout.js`), `DayEnd`, `Admin` (at `#admin`: PIN pad; with the default PIN only the change-PIN card; then tabs Menu / Modules / Security / Backup). Counter actions that need the PIN (Day End cancel, Dashboard target and expenses) use `pinApi` from `api.js`, which opens `components/PinPrompt.jsx` and retries. Dates and the top-bar clock use the shop clock (`shopNow()`/`today()` in `api.js`, synced from the dashboard's `now`), not the tablet's. The POS screens read `GET /api/config` (`frontend/src/config.jsx`) for theme colours, shop name, payment methods, order types, the GST line, the discount cap and the bill footer.
- **Docker:** two compose services. `api` (root `Dockerfile`, FastAPI only, not published, `pos-data` volume at `/data`) and `web` (nginx, published `4000:8080`). nginx passes `Host` through and overwrites `X-Forwarded-For`; uvicorn trusts it from `WB_FORWARDED_ALLOW_IPS` (compose: `*`) so the PIN throttle is per tablet. `compose.dev.yaml` (`make dev`, project `waffle-bros-dev`) adds uvicorn `--reload` on mounted `src/` (:8000) and the Vite dev server (:5173) with its own `pos-dev-data` volume. Docker is the only supported deployment.
- **Data:** one SQLite file, `data/waffle-bros.db` (or `/data` in the `api` container). Settings the owner edits live in the `settings` table as module rows (see `modules/`); process config is `WB_*` env vars (`config.py`).
- **Docs:** `docs/API.md` (API reference, written for humans and Claude), `docs/openapi.json` (generated), `docs/ARCHITECTURE.md` (design), `docs/IMPLEMENTATION.md` (hands-on guide and recipes), `docs/SECURITY.md` (threat model, controls, review findings). Swagger UI runs at `/docs`.

## Commands

The Makefile has exactly seven targets, on purpose (the owner asked for a small one): `make up`, `down`, `logs`, `dev`, `check`, `backup`, `pin-reset`. Don't add more without asking; use the plain commands. Underneath:

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
cd frontend && npm test                   # frontend unit tests (node --test, no extra packages)
docker compose up -d --build --wait       # make up: web on :4000 + api, data in the pos-data volume
```

## Making changes

- **New/changed endpoint:** add a schema in `schemas.py`, logic in `services/`, a route in `api/` with `summary=` and a docstring, tests in `tests/test_api.py`, then regenerate `docs/openapi.json` and update `docs/API.md`.
- **Database change:** edit `db/models.py`, then `uv run alembic revision --autogenerate -m "..."`, review the generated file in `migrations/versions/`, and commit it. Never edit an already-merged migration. Use batch mode (it's on) for SQLite ALTERs.
- **Money:** rupees as floats, rounded with `services.targets.money()` (2 dp, half-up). Bills are always priced on the server from the menu; never trust prices from the client.
- **Bills are history:** `order_items` copies name/category/price. Items that have been sold are hidden (`active=False`), not deleted.
- **Shop owner UI text:** plain English, Indian rupee formatting (`₹1,00,000`), via `services.fmt.inr()` on the backend.
- **Quality gates:** ruff, `mypy --strict`, pytest and `npm test` (frontend) must pass, and new logic needs tests. Run `uv run pre-commit run --all-files` before pushing.
- **Admin-only endpoints:** add `dependencies=[AdminOnly]` and `ADMIN_401` plus `ADMIN_403` in `responses=errors(...)`, and mark it **(Admin)** in `docs/API.md`. If a counter screen calls it, use `pinApi` there. Billing, looking up bills and reading reports stay open so the counter works without a PIN; anything that changes money figures (cancel, targets, expenses) needs it. See `docs/SECURITY.md`.
- **Input limits:** every new string field gets a `max_length`, every amount `le=MAX_MONEY`, every list a `max_length`; request bodies subclass `schemas.In`.
- **Workflow:** branch, then PR to `main`. CI (`.github/workflows/ci.yml`) runs the backend checks, the frontend build, and builds both images and smoke-tests them through `web`.

## Adding a module

1. Write a settings model (subclass `ModuleSettings`) in `modules/builtin.py`, or in its own `modules/<key>.py` for anything bigger. Give every field a default and `Field(title=..., description=...)`: the Admin page draws the form straight from the Pydantic JSON Schema, so no frontend change is needed. Limits (`ge`, `le`, `max_length`), `Literal` enums and lists all show up in the form. Use `json_schema_extra={"format": "color"}` (or the `Color` type) for a colour picker and `{"format": "image"}` for an image upload.
2. Create `Module(key, name, description, SettingsModel, ...)`: set `core=True` if it can't be switched off, `default_enabled`, `icon` and `order`. List `secret_fields` (left out of the public `GET /api/config`, e.g. `google_sheets.secret`) and `internal_fields` (written only by server code via `registry.store_internal`, shown read-only, e.g. `google_sheets.last_sync`).
3. Add it to `registry.BUILTIN`.
4. In code, read it with `registry.is_enabled(db, "<key>")` and `registry.settings_of(db, "<key>", SettingsModel)`, never by reading `settings` rows directly. Stored values are validated on load and bad ones fall back to defaults, so renaming or removing a field is safe, but don't change a key's meaning.
5. Add tests in `tests/test_modules.py` (and `tests/test_api.py` for endpoints), and update the module table in `docs/API.md`. If it adds endpoints, follow "New/changed endpoint" above.

## Planned

- More modules as needed (the module system and admin dashboard exist; agree new features' design with the owner first).
- Phase 2: WhatsApp ordering for the apartment residents (`POST /api/integrations/whatsapp` is reserved; orders already have `source`, `order_type`, `delivery_address`).
