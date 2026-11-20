# Implementation guide

The hands-on guide to working on the Waffle Bros POS: where things are, how to run them, how each
piece works, and step-by-step recipes for common changes. For the design and the reasons behind it
see [ARCHITECTURE.md](ARCHITECTURE.md). For every endpoint see [API.md](API.md). The house rules
are in `CLAUDE.md`.

## Contents

1. [Repo layout](#repo-layout)
2. [Local setup](#local-setup)
3. [How each piece is implemented](#how-each-piece-is-implemented)
4. [Recipes](#recipes)
5. [Testing](#testing)
6. [Troubleshooting](#troubleshooting)

## Repo layout

```
waffle-bros-pos/
├── src/waffle_pos/
│   ├── __main__.py            `uv run waffle-pos`: prints the local and Wi-Fi URLs, starts uvicorn
│   ├── app.py                 create_app(): lifespan (migrate, seed, sync loop), routers, error format, serves frontend/dist
│   ├── config.py              AppConfig: WB_* env vars / .env (data_dir, host, port, timezone, frontend_dist, sync_interval_seconds, start_sync_loop)
│   ├── clock.py               now(), today(), month_key(), days_in_month(), day_bounds() in shop-local time
│   ├── schemas.py             Pydantic request/response models (the JSON contract with the React screens); In base, size and money caps
│   ├── security.py            middlewares: HostCheck (DNS rebinding), BodyLimit (413), SecurityHeaders (CSP etc.)
│   ├── openapi.py             writes docs/openapi.json (`--check` to verify it)
│   ├── demo.py                fills data-demo/ with about 6 weeks of made-up sales
│   ├── api/
│   │   ├── deps.py            DB session per request, AdminOnly / SignedIn, ADMIN_401 / ADMIN_403, errors(), bad_request()
│   │   ├── menu.py            GET /api/menu; admin-only category and item writes and reorders
│   │   ├── orders.py          bill, list by day, get, cancel
│   │   ├── dashboard.py       /api/dashboard, /api/items/stats, /api/day-end
│   │   ├── finance.py         PUT /api/targets/{month}, /api/expenses
│   │   ├── system.py          /api/health, /api/sync, /api/backup, WhatsApp placeholder
│   │   └── admin.py           /api/config, /api/admin/login (throttled), /pin, /modules, /google-sheet/script
│   ├── services/
│   │   ├── orders.py          create_order (server-side pricing, discount, GST), next_bill_no, cancel_order
│   │   ├── menu.py            get_menu, items and categories CRUD, hide-not-delete, _reorder
│   │   ├── targets.py         pure target maths: TargetInput → compute() → TargetNumbers; money(), js_round()
│   │   ├── analytics.py       target_summary, charts, item_stats, day_end, month_expenses, monthly_summary
│   │   ├── insights.py        plain-English tips from the analytics numbers
│   │   ├── auth.py            PIN (scrypt), HMAC tokens, secret rotation, LoginThrottle
│   │   └── fmt.py             inr() (₹1,00,000), group_indian(), num()
│   ├── modules/
│   │   ├── base.py            Module dataclass, ModuleSettings base model
│   │   ├── builtin.py         the shipped settings models and Module objects
│   │   └── registry.py        BUILTIN, is_enabled, settings_of, save_settings, store_internal, public_settings
│   ├── db/
│   │   ├── models.py          ORM: Category, Item, Order, OrderItem, Expense, Target, Setting
│   │   ├── session.py         make_engine (WAL, foreign keys), session_scope
│   │   ├── migrate.py         upgrade_to_head() at start-up
│   │   └── seed.py            starter menu on an empty database
│   ├── migrations/            Alembic env.py and versions/ (0001 schema, 0002 settings → modules)
│   └── integrations/
│       ├── sheets.py          Google Sheet sync: builds the rows, POSTs them to the Apps Script web app (sync_now, sync_loop)
│       └── apps_script.gs     the script the owner pastes into the Google Sheet (doPost writes the tabs)
├── frontend/
│   ├── vite.config.js         dev server :5173, proxies /api to WB_API_URL (default :4000); builds to dist/
│   ├── Dockerfile             the `web` image: deps → dev (Vite, for make dev) → build → nginx runtime
│   ├── nginx.conf             serves the screens, proxies /api, /docs, /openapi.json to api:4000
│   ├── security-headers.inc   the same CSP and headers the API sends, for the screens' files
│   └── src/
│       ├── main.jsx           mounts <App/> inside <ConfigProvider>
│       ├── App.jsx            top bar, hash routing (#billing #dashboard #dayend #admin), today chip
│       ├── config.jsx         loads GET /api/config, DEFAULT_MODULES, theme → CSS variables, useConfig()
│       ├── api.js             fetch wrapper, api / adminApi, admin token storage, adminDownload, inr()
│       ├── styles.css         all styles; colours come from CSS variables on :root
│       ├── components/Receipt.jsx   80 mm bill printed with window.print()
│       ├── components/PinPrompt.jsx PIN dialog for counter actions that need the admin PIN
│       └── pages/             Billing.jsx, Dashboard.jsx, DayEnd.jsx, Admin.jsx
├── tests/                     pytest: conftest.py, test_api, test_modules, test_analytics, test_targets, test_sheets, test_openapi
├── docs/                      API.md, openapi.json (generated), ARCHITECTURE.md, SECURITY.md, this file, screenshots
├── Makefile                   the seven everyday commands (`make`)
├── Dockerfile                 the `api` image (FastAPI only, no screens)
├── compose.yaml               `web` (nginx, port 4000) + `api` (internal), pos-data volume, read-only hardened containers
├── compose.dev.yaml           `make dev` override: uvicorn --reload, Vite hot reload, its own pos-dev-data volume
├── alembic.ini                Alembic CLI config (script_location = src/waffle_pos/migrations)
├── pyproject.toml, uv.lock    dependencies, ruff, mypy (strict), pytest and coverage settings
└── .github/workflows/ci.yml   backend checks, frontend build, both images built and smoke-tested through web
```

## Local setup

Running the POS needs only Docker. The checks (`make check`) and the commands below also need
[uv](https://docs.astral.sh/uv/) (it installs Python 3.12 by itself) and Node.js 22.

```bash
uv sync                          # .venv with Python 3.12, app and dev tools
uv run pre-commit install        # ruff, ruff-format, mypy and pytest before each commit
(cd frontend && npm ci)          # screen dependencies
```

### Make targets

`make` on its own (or `make help`) lists them. There are seven on purpose; anything else is one of
the plain commands below.

| Target | What it does |
| --- | --- |
| `make up` | `docker compose up -d --build --wait`: build and start `web` + `api`, POS on http://localhost:4000 |
| `make down` | stop both (data stays in the `pos-data` volume) |
| `make logs` | follow both services' logs |
| `make dev` | live-reload copy in Docker (project `waffle-bros-dev`, own `pos-dev-data` volume): screens with hot reload on http://localhost:5173, API with auto-reload on :8000 (`/docs`). Ctrl+C stops it |
| `make check` | ruff, ruff format, mypy, pytest, `openapi --check` and the screens build. Run it before pushing |
| `make backup` | copy the live database out of the `api` container into `backups/` with SQLite's backup API (safe while billing) |
| `make pin-reset` | stop `api`, forget the admin PIN so it goes back to 1234, start `api` again (see [Troubleshooting](#troubleshooting)) |

### The commands underneath

```bash
uv run ruff check --fix && uv run ruff format                              # auto-fix and format
uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest
uv run pre-commit run --all-files                                          # everything CI runs
uv run python -m waffle_pos.openapi                                        # regenerate docs/openapi.json
uv run uvicorn waffle_pos.app:create_app --factory --reload --port 4000   # API outside Docker, auto-reload
cd frontend && npm run dev                                                 # screens on :5173, /api → :4000
uv run python -m waffle_pos.demo && WB_DATA_DIR=data-demo uv run waffle-pos   # demo data, outside Docker
docker compose -p waffle-bros-dev -f compose.yaml -f compose.dev.yaml down -v   # wipe the dev data
```

Outside Docker, `uv run waffle-pos` still serves `frontend/dist` itself if it has been built, so
one process is enough for a quick look at the demo data.

Process settings come from environment variables or `.env`: `WB_DATA_DIR` (default `./data`),
`WB_PORT` (4000), `WB_HOST` (`0.0.0.0`), `WB_TIMEZONE` (`Asia/Kolkata`), `WB_FRONTEND_DIST`,
`WB_SYNC_INTERVAL_SECONDS` (unset = use the module's "Sync every" setting), `WB_ALLOWED_HOSTS`
(extra host names the POS may be opened by, comma-separated), `WB_MAX_BODY_BYTES` (default
1,000,000) and `WB_FORWARDED_ALLOW_IPS` (proxies whose `X-Forwarded-For` uvicorn believes; default
`127.0.0.1`, compose sets `*` because only `web` can reach `api`). In Docker they go under `api`
in `compose.yaml`.

The demo generator writes to `data-demo/` (or `WB_DEMO_DIR`). It wipes that folder first and
refuses to run against the real `data/` folder.

## How each piece is implemented

### Orders: pricing and bill numbers

`services/orders.create_order(session, data, when=None)`:

1. Rejects an empty order. Loads all requested items in one query (with their category).
2. Builds an `OrderItem` per line, copying `name`, `category.name` and `price` from the menu. The
   client's prices are never used, because `OrderLineIn` only has `item_id` and `qty` (1 to 999).
   A bill has at most 100 lines (`OrderCreate`). An unknown id raises `OrderError("Unknown item
   N")`, and a hidden item (`active=False`) raises "<name> is hidden from the menu and can't be
   billed".
3. `subtotal = Σ price × qty`.
4. Discount (rupees, before GST), only if `data.discount > 0`:
   - the `discounts` module must be on, otherwise "Discounts are switched off in the admin dashboard";
   - cap = `subtotal × max_discount_pct / 100` (default 20%), with a ₹0.005 tolerance. Over it:
     "Discount can be at most 20% of the bill (₹123)" (the cap via `fmt.inr()`);
   - the applied discount is `min(subtotal, discount)`.
5. GST: if the `gst` module is on, `tax = (subtotal − discount) × rate / 100` (default rate 5%),
   else 0.
6. `total = subtotal − discount + tax`. Amounts are rounded with `targets.money()` (2 dp, halves
   up).
7. `bill_no = next_bill_no(session, when)`: `WB<yymmdd>-<nnn>`, where `nnn` is the number of
   orders already created that shop-local day (cancelled ones included) plus 1, e.g.
   `WB261118-007`.
8. Adds and flushes. The request's session commits after the route returns.

Example: 2 × Nutella (₹199) + 1 × Lotus Biscoff (₹219) = ₹617 subtotal. With a ₹50 discount and
GST at 5%: tax = 567 × 5% = ₹28.35, total = ₹595.35.

`cancel_order` sets `status="cancelled"` and `synced=False`. Nothing is ever deleted. The cancel
endpoint is admin-only.

The Billing screen (`pages/Billing.jsx`) mirrors the same sums to show a live total, and clamps
the discount to the cap it gets from `/api/config`. The server's numbers are what get saved and
printed.

### Target maths

`services/targets.py` is pure. `analytics.target_summary(session, now)` gathers the inputs and calls
`compute(TargetInput(...))`.

Inputs (`TargetInput`): `target`, `days_in_month`, `day_of_month`, `revenue_before_today` (this
month up to midnight), `revenue_today`, `orders_mtd`, `trading_days_before_today` (whole days from
the first paid sale this month up to today), `expenses_total`. `days_left` counts **today
included**.

| Output key | Formula |
| --- | --- |
| `progressPct` | month-to-date revenue ÷ target × 100 |
| `expectedPct` | day of month ÷ days in month × 100 (even pace by the end of today) |
| `remaining` | max(0, target − MTD) |
| `evenDailyTarget` | target ÷ days in month |
| `todayTarget` | max(0, (target − revenue before today) ÷ days left). Fixed for the day, so billing doesn't move it |
| `todayPct`, `todayRemaining` | today's revenue against `todayTarget` |
| `requiredDailyFromTomorrow` | max(0, (target − MTD) ÷ (days left − 1)); on the last day, `remaining` |
| `avgDaily` | revenue before today ÷ trading days; on the first trading day, today's revenue |
| `projected` | revenue before today + `avgDaily` × days left |
| `aov` | MTD ÷ orders MTD |
| `ordersNeededToday` | ceil(`todayRemaining` ÷ `aov`), or `null` with no orders yet |
| `netProfit` | MTD − expenses counted this month |
| `breakEvenDaily` | expenses ÷ days in month |
| `breakEvenRemainingDaily` | max(0, expenses − MTD) ÷ days left |

Worked example (from `tests/test_targets.py`): target ₹1,00,000, a 30-day month, day 16, ₹30,000
before today, ₹1,000 so far today, first sale on day 1, 151 bills.

- days left = 15; `todayTarget` = (1,00,000 − 30,000) ÷ 15 = ₹4,666.67
- `requiredDailyFromTomorrow` = 69,000 ÷ 14 = ₹4,928.57
- `avgDaily` = 30,000 ÷ 15 = ₹2,000; `projected` = 30,000 + 2,000 × 15 = ₹60,000
- `progressPct` = 31, `expectedPct` = 53.33, `aov` = ₹205.30, `ordersNeededToday` = 18

`money(x)` rounds to 2 dp with halves going up (`floor((x + ε) × 100 + 0.5) / 100`), and
`js_round` copies JavaScript's `Math.round`. Both match the old Node code.

### Analytics and insights

`services/analytics.py` (all paid bills only, via `_paid_between`; dates are shop-local, and SQLite
`strftime` groups by day and hour):

- `get_target(month)`: the `targets` row, else the `targets` module's `default_target`.
- `month_expenses(month)`: one-off expenses dated in the month, plus every recurring expense dated
  before the month ends. Totals and a by-category list.
- `target_summary(now)`: the inputs above, plus `month`, `revenue`, `orders`, `todayRevenue`,
  `todayOrders` and the `expenses` breakdown.
- `charts(now)`: `hourly` (today against the average of the previous 28 days), `daily` (this month
  with an even-pace target line), `weekly` (12 weeks, Monday to Sunday), `monthly`
  (`monthly_summary`: 12 months with target and expenses), `categorySplit`, `paymentSplit`,
  `weekday` (8-week average per weekday, counting only days with sales).
- `item_stats(period, now)`: every menu item with `qty`, `orders` (separate bills), `revenue`,
  `share` and `margin` (`(price − cost) ÷ price`, `null` when cost is 0). Then `bestSeller` (most
  revenue), `mostPopular` (most units), `customerFavourite` (most bills), top 5 lists and
  `slowMovers` (5 active items selling least). Periods: `today`, `week`, `month`, `30d`, `all`.
- `day_end(day)`: revenue, orders, average bill, items sold (grouped by the copied name and
  category), active items that didn't sell, payment split, and cancelled count and amount.

`services/insights.insights(now)` returns `[{tone, title, text}]`, built by `_pace`, `_today`,
`_average_bill`, `_expenses`, `_hours`, `_weekdays` and `_menu`. With no sales this month it returns
a single "No sales yet" tip. `_menu` uses the `targets` module's `slow_mover_pct` and
`low_margin_pct`. Amounts are written with `fmt.inr()`, e.g. "₹4,667".

`GET /api/dashboard` returns `{target, charts, insights, items}` in one call.

### Menu and reorder

`services/menu.py`:

- `get_menu` orders categories by `(sort, id)` and items by `(category.sort, item.sort, code)`.
- `create_item` / `update_item` go through `_apply`, which checks the category exists and the
  `code` is unique (codes are upper-cased by `ItemIn`). Update replaces every field.
- `remove_item` deletes an item that has never been billed, else hides it (`active=False`) and the
  API answers `hidden: true`.
- `delete_category` refuses while the category has any items, hidden ones included.
- `reorder_categories(ids)` / `reorder_items(ids)` → `_reorder`: the listed ids take positions 0,
  1, 2, ... in the order given (duplicates ignored), and every other row keeps its relative order
  after them. An unknown id raises `MenuError`. The Admin page sends one category's items at a
  time.

### Migrations at start-up

- `db/migrate.upgrade_to_head(engine)` builds an Alembic `Config` pointing at
  `src/waffle_pos/migrations`, puts an open connection into `cfg.attributes["connection"]`, and runs
  `command.upgrade(cfg, "head")` inside `engine.begin()`. `migrations/env.py` uses that connection
  if it is there. Otherwise (the `alembic` CLI) it uses `alembic.ini`'s URL or `AppConfig().db_url`,
  which respects `WB_DATA_DIR`. `render_as_batch=True` is on, so SQLite `ALTER`s work.
- The app lifespan calls it before anything else, so pulling new code and restarting upgrades the
  shop's database.
- `0001_initial_schema`: all tables and indexes.
- `0002_module_settings`: a **data** migration. It reads the old flat `settings` keys
  (`shop_name`, `shop_address`, `shop_phone`, `open_hour`, `close_hour`, `gstin`, `gst_rate`,
  `default_target`, `sheets_spreadsheet_id`, `sheets_credentials_path`, `sheets_last_sync`),
  converts each to the right type, and writes them as `module:<key>` JSON rows. It switches `gst` on
  if the old rate was above 0, and copies `sheets_enabled` to `module:google_sheets:enabled`. Then it
  deletes the old keys. (The old sheet keys map to `spreadsheet_id` / `credentials_path`, fields the
  Apps Script version of `GoogleSheetsSettings` no longer has, so they are dropped when loaded.) `downgrade()` reverses it. `tests/test_modules.py::
  test_migration_moves_flat_settings_into_modules` covers both directions.

### Frontend config loading and theming

`frontend/src/config.jsx`:

- `DEFAULT_MODULES` mirrors the backend defaults so the screens work before (or without) the
  config call.
- `ConfigProvider` calls `GET /api/config` once on mount, then `merge()` lays the server's
  `enabled` and `settings` over the defaults per module. On failure it keeps what it had and sets
  `error`.
- `themeVars(theme)` maps the four theme colours to CSS variables: `primary` → `--yellow` (plus
  `--yellow-soft`, `--yellow-tint`, `--yellow-hover` and `--ring`, mixed toward white), `dark` →
  `--choc` (and `--choc-2`, mixed with the accent), `accent` → `--honey` (and `--honey-dark`),
  `background` → `--cream`. `applyTheme` sets them on `document.documentElement`, overriding the
  `:root` values in `styles.css`. Bad hex values fall back to the defaults.
- It also sets `document.title` to `<shop_name> POS`.
- `useConfig()` exposes `enabled(key)`, `settings(key)`, `reload()`, `default_pin`, `version`,
  `loaded`, `error`.

### Admin page and form generation

`frontend/src/pages/Admin.jsx`:

- `Admin` shows `PinScreen` until there is a session. With `must_change_pin` or
  `default_pin`, it shows **only** a banner with `ChangePin` (no tabs), because the server answers
  403 to every other admin call until the PIN is changed. It also signs out when the token expires
  (a timer on `expires_at`) or on the `wb:admin-signed-out` event.
- Tabs: `MenuTab` (categories with up/down reorder, rename, delete; items per category with edit,
  hide/delete and reorder; `ItemModal` makes photo thumbnails as JPEG data URLs), `ModulesTab`,
  `SecurityTab` (change PIN) and `BackupTab` (`adminDownload('/api/backup', ...)`).
- `ModulesTab` loads `GET /api/admin/modules` and renders a `ModuleCard` each. `ModuleCard` keeps a
  draft of the values, computes `changed` (skipping read-only fields, with `coerce` turning number
  inputs back into numbers), and sends `PUT /api/admin/modules/{key}` with `{settings: changed}` or
  `{enabled}`. After a successful save it calls `reload()` from `useConfig`. For `google_sheets` it
  adds **New secret** (fills the `secret` field with 36 random hex characters from
  `crypto.getRandomValues`), **Setup script** (shows the Apps Script from
  `GET /api/admin/google-sheet/script` with setup steps) and **Sync now** (saves first if needed,
  then `POST /api/sync` with the admin token), and shows `last_sync`.
- `SchemaField` picks a control with `kindOf` after `deref` resolves `$ref`, `allOf` and
  nullable `anyOf`. The mapping table is in [ARCHITECTURE.md](ARCHITECTURE.md#how-the-admin-form-is-generated).
  Read-only means either listed in `readonly_fields` or `readOnly` in the schema.

### api.js and the admin token

- `req(method, url, body, withAuth)` sends JSON, parses the reply, and on failure throws an `Error`
  whose message is the server's `error` (with `err.status` set).
- `api.*` calls carry no token. `adminApi.*` calls add `Authorization: Bearer <token>` from
  `adminSession`.
- `adminSession` stores `{token, expires_at, must_change_pin}` in `sessionStorage` under
  `wb-admin-session`, with an in-memory fallback when storage is blocked. `get()` returns `null`
  once `expires_at` has passed.
- A 401 on an `adminApi` call (or `adminDownload`) clears the session and dispatches
  `wb:admin-signed-out`.
- `pinApi.post/put/del(url, body, reason)` is for counter actions that need the PIN (Day End
  cancel, the Dashboard target and expenses). With no valid session it first calls
  `requirePin(reason)`. It then sends the call with the token, and on a 401 asks again and retries
  once. `requirePin` dispatches `wb:pin-needed`. `components/PinPrompt.jsx` (mounted once in
  `App.jsx`) listens for it, shows the PIN dialog, posts to `/api/admin/login`, stores the session
  with `adminSession.set`, and resolves the promise. **Cancel** rejects it with `e.cancelled = true`,
  and the pages then show nothing.
- `adminDownload(url, name)` fetches with the token and saves the blob, taking the file name from
  `Content-Disposition`. `adminText(url)` fetches a protected plain-text resource (the Apps Script).
- `inr(n, dp)` formats with `toLocaleString('en-IN')` (₹1,00,000). `inrShort` gives ₹1.2L / ₹4.5k.

## Recipes

### Add an endpoint

1. **Schema:** add request and response models to `src/waffle_pos/schemas.py`. Field names are what
   the screens will read.
2. **Logic:** add a function in `services/` that takes a `Session`. Raise a domain error (a
   `ValueError` subclass like `OrderError` or `MenuError`) for bad input. Use `clock.now()` and
   `targets.money()`.
3. **Route:** in the right `api/` module:

   ```python
   @router.get(
       "/expenses/summary",
       summary="This month's expenses by category",
       responses=errors({400: "...", 422: INVALID}),
   )
   def expense_summary(db: DB) -> ExpenseSummaryOut:
       """One paragraph for docs/openapi.json and Swagger. Say what is in rupees."""
       try:
           return finance_service.summary(db)
       except finance_service.FinanceError as e:
           raise bad_request(str(e)) from e
   ```

   For an admin-only route add `dependencies=[AdminOnly]` and `401: ADMIN_401, 403: ADMIN_403` to
   `errors(...)`. Request bodies subclass `schemas.In` (no Infinity/NaN). Give every string a
   `max_length` and every amount `le=MAX_MONEY`. If a counter screen calls it, use `pinApi`.
4. **Tests** in `tests/test_api.py`, using the `api_client` fixture (and `_admin(client)` for
   headers when it needs the PIN).
5. `uv run python -m waffle_pos.openapi`. `tests/test_openapi.py` fails until
   `docs/openapi.json` matches, and it checks every operation has a summary, description and tag.
6. Document it in `docs/API.md`, marked **(Admin)** if it needs the PIN.

### Add a module

1. Settings model in `modules/builtin.py` (or `modules/<key>.py` if it's big). Give every field a
   default and a `Field(title=..., description=...)`:

   ```python
   class LoyaltySettings(ModuleSettings):
       points_per_100: int = Field(1, ge=0, le=100, title="Points per ₹100 spent")
       reward_at: int = Field(50, ge=1, title="Points needed for a free waffle")
       card_colour: Color = Field("#F6B92B", title="Loyalty card colour")
   ```

2. The module:

   ```python
   LOYALTY = Module(
       "loyalty",
       "Loyalty points",
       "Points on every bill, free waffle at the end.",
       LoyaltySettings,
       default_enabled=False,
       icon="⭐",
       order=12,
   )
   ```

   Use `core=True` only if it can never be off. List `secret_fields` for anything that must not
   reach `GET /api/config`, and `internal_fields` for values only server code writes (use
   `registry.store_internal` for those).
3. Add it to `registry.BUILTIN`.
4. Read it in code only through the registry:

   ```python
   if registry.is_enabled(db, "loyalty"):
       cfg = registry.settings_of(db, "loyalty", LoyaltySettings)
   ```

5. The Admin form appears by itself. If a screen needs the values, read
   `useConfig().settings('loyalty')`, and add an entry to `DEFAULT_MODULES` in `config.jsx`.
6. Tests in `tests/test_modules.py` (and `tests/test_api.py` for endpoints). Add a row to the module
   table in `docs/API.md`. Agree the design with Abhinav before building it.

Renaming or removing a field is safe (unknown keys are dropped, bad values reset to defaults), but
don't change what an existing key means.

### Add a database column

1. Edit `src/waffle_pos/db/models.py`, e.g. `gst_rate: Mapped[float] = mapped_column(Float,
   default=0)` on `Order`. A new non-null column needs a `server_default` (or a data step) so
   existing rows get a value.
2. Make sure your local database is at head (start the app once, or `uv run alembic upgrade head`).
   Autogenerate compares against the database at `WB_DATA_DIR` (default `data/`).
3. `uv run alembic revision --autogenerate -m "orders gst rate"`. The file lands in
   `src/waffle_pos/migrations/versions/` as `<rev>_<slug>.py`.
4. Review it. Batch mode is on, so changes to existing tables come out as `with
   op.batch_alter_table(...)`. Add any data migration by hand (see `0002` for the pattern), and write
   `downgrade()`.
5. Update `schemas.py`, the services and tests. Restart: the app applies it. Never edit a migration
   that is already merged.

### Add a Google Sheet tab

Two files, because the sheet side only writes tabs it knows:

1. `src/waffle_pos/integrations/sheets.py`: add the tab and its header row to `TABS`.
2. Write a row builder that runs inside the short session in `sync_now`, like
   `_daily_rows(session, now)`. Return plain cells (`str | int | float`). Round rupees with
   `money()`.
3. Add it to the `tabs` list in `sync_now` with `_tab("Name", "replace", rows)` for a summary that is
   rewritten every run, or `_tab("Name", "append", rows)` for new rows only. An append-only tab
   needs a `synced` flag on its table (a new column, see above): collect the ids alongside the rows
   and `_mark_synced(...)` them **after** `_post` succeeds, like orders and expenses.
4. `src/waffle_pos/integrations/apps_script.gs`: add the name to `ALLOWED_TABS`. Otherwise the
   script answers `Unknown tab ...` and the whole sync fails.
   `tests/test_sheets.py::test_apps_script_source_is_shipped` fails if you forget.
5. The owner must paste the new script into the sheet and deploy a new version (**Deploy → Manage
   deployments → Edit → New version**, so the URL stays the same). Ship the POS and script change
   together and tell him. The header row is written only when a tab is empty, so changing an
   existing tab's columns also needs that tab's header fixed by hand.
6. Extend `FakeWebApp` checks in `tests/test_sheets.py` (it already applies `append` / `replace` per
   tab), and the tab table in `README.md`.

### Change the theme defaults

Three places hold the default colours. Keep them in step:

1. `modules/builtin.ThemeSettings`: the real defaults (`primary`, `dark`, `accent`, `background`).
2. `frontend/src/config.jsx` → `DEFAULT_MODULES.theme.settings`: used until `/api/config` answers.
3. `frontend/src/styles.css` → `:root` (`--yellow`, `--choc`, `--honey`, `--cream` and the mixed
   shades): the very first paint.

Then `make up` (or `cd frontend && npm run build`). A shop that has already saved the Look module keeps its stored colours, because
`save_settings` stores every field. The owner changes them in **Admin → Modules → Look**. To add a
new themable colour, add a `Color` field to `ThemeSettings`, map it in `themeVars()`, and use the
variable in `styles.css`.

## Testing

`uv run pytest` (`make check` runs it too) runs everything with coverage (`--cov=waffle_pos
--cov-report=term-missing:skip-covered`, set in `pyproject.toml`). Coverage leaves out
`migrations/`, `__main__.py` and `demo.py`. There is no minimum threshold, but new logic needs
tests.

| File | Covers |
| --- | --- |
| `tests/test_targets.py` | `targets.compute` edge cases (start of month, first day, behind/ahead, mid-month opening, target reached, last day, zero target, expenses above/below revenue), `money`, `js_round`, `fmt.inr` lakh grouping |
| `tests/test_analytics.py` | `get_target`, `month_expenses` and recurring expenses, `target_summary`, `item_stats` periods, hidden items vs slow movers, `charts`, hourly window, `day_end`, `insights` (no sales, behind, reached, with and without expenses) |
| `tests/test_api.py` | end to end through FastAPI: seeded menu, server-side pricing, GST and discount cap, readable errors, cancel, targets/expenses → dashboard, menu editing, sync skipped when off, backup is SQLite, WhatsApp 501, frontend not built / served, health |
| `tests/test_modules.py` | module defaults and core modules, settings merge and bad-data recovery, internal fields not writable, PIN flow, token expiry and tampering, admin endpoints need the PIN, module listing/update, modules changing billing, change PIN via API, categories, backup with token, the `0002` migration up and down |
| `tests/test_sheets.py` | sync off / not configured, settings rejecting other URLs and short secrets, one POST with every tab and rows marked synced, web app errors (wrong secret, HTTP 500, HTML page, `{"ok": false}`) leave rows unsynced, unreachable web app, the `.gs` file ships with the package and allows every tab in `TABS`, loop keeps going after failures |
| `tests/test_flow.py` | the whole shop through the HTTP API only: fresh install, owner setup, a trading day, day-end, validation errors, sync settings and script, backup contents, restart, front end built or not; its last test fails if any route in the OpenAPI schema was never answered successfully |
| `tests/test_security.py` | the security controls: default-PIN 403 on every admin route, sign-in throttle (unit and HTTP), odd PINs and tokens, Host check, body limit, security headers, NaN/Infinity amounts, input limits, image rules, huge ids, formula escaping and one-sync-at-a-time |
| `tests/test_openapi.py` | `docs/openapi.json` is up to date, every operation has a summary, description and tag, `--check` mode |

Fixtures:

- `tests/conftest.py`: `db_engine` creates a migrated SQLite database in `tmp_path` with
  `AppConfig(data_dir=tmp_path, start_sync_loop=False)`. `db_session` seeds the starter menu (18
  items, ids 1 to 18 in menu order) and rolls back afterwards.
- `tests/test_api.py` / `tests/test_modules.py`: `api_client` builds
  `create_app(AppConfig(data_dir=tmp_path, start_sync_loop=False, frontend_dist=tmp_path /
  "no-dist"))` inside a `TestClient`, so the lifespan runs migrations and seeding but no sync loop
  starts. `_admin(client)` logs in with `1234` and returns the bearer header.
- `tests/test_sheets.py`: `sheets_engine` / `sheets_factory` give a real migrated, seeded database
  with a session factory, as `sync_now` expects. `sheets_enabled` also switches the module on with a
  test web app URL and secret.

How the Sheets tests fake Google: `FakeWebApp.handler` is an `httpx.MockTransport` handler.
`sync_now(factory, client=fake.client())` gets an `AsyncClient` on that transport, so no request
leaves the process. The fake behaves like a deployed Apps Script: the `POST` to the web app URL
answers 302 to an echo URL, and the `GET` there returns the JSON result. It checks the secret and
keeps the tabs in memory, applying `append` and `replace` the way `apps_script.gs` does, so tests
assert on the resulting rows. Flags make it fail: `status` (an HTTP error), `raw_answer` (an HTML
page instead of JSON) or a different `secret`.

## Troubleshooting

**Port 4000 is already in use.** Another copy of the POS is probably running. Check with
`docker compose ps` or `lsof -i :4000`, and stop it (`make down`). Or publish another port: change
the left side of `ports: "4000:8080"` under `web` in `compose.yaml`. `make dev` uses 5173 and 8000
instead, so it can run next to `make up`.

**502 Bad Gateway from the POS.** `web` is up but can't reach `api`: it is still starting
(migrations run first) or has stopped. `docker compose ps` shows its health and `make logs` shows
why. `make up` waits for both to be healthy.

**"Front end not built yet."** You opened the backend directly outside Docker
(`uv run waffle-pos`) without `frontend/dist`. Run `cd frontend && npm ci && npm run build` and
restart it, or use `make up`, where `web` serves the screens.

**"This address isn't allowed. Open the POS by its IP address or add the name to
WB_ALLOWED_HOSTS."** (400) The `HostCheck` middleware only accepts IP addresses, single-word names
(`localhost`, `shop-pc`), `*.local` names and the names in `WB_ALLOWED_HOSTS`. If you open the POS by
a domain name (`pos.waffle-bros.in`), add it: `WB_ALLOWED_HOSTS=pos.waffle-bros.in`. In tests,
`TestClient`'s default host `testserver` is a single word, so it passes.

**403 "Change the default PIN 1234 first".** The PIN is still `1234`. Sign in and set a new one
(`POST /api/admin/pin`). Until then every other admin route refuses.

**429 "Too many wrong PINs. Try again in N seconds."** The sign-in throttle (5 wrong PINs per
device, then 30 s doubling to 15 minutes; or 30 wrong PINs from anywhere in 10 minutes). Wait for
`Retry-After`, or restart the POS, which clears it.

**413 "The request is too large".** The body is over `WB_MAX_BODY_BYTES` (1,000,000 bytes by
default). Usually a picture: the Admin page shrinks images, but the limit for an item image or logo
is 200,000 characters of data URL anyway.

**Migrations.** They run on every start-up. If one fails, start-up stops with the Alembic error
and the database is left as it was (it runs in one transaction). Useful commands (they use
`WB_DATA_DIR`):

```bash
uv run alembic current            # which revision the database is at
uv run alembic history            # all revisions
uv run alembic upgrade head       # apply by hand
```

"Can't locate revision" means the database was upgraded by newer code than you are running (for
example after switching back to an older branch). Go back to the newer code, or restore a backup
made with the older version. Never edit a merged migration to fix a shop database; add a new one.

**Forgot the admin PIN.** The PIN hash, salt and token secret are stored in the `module:admin`
row of the `settings` table. If that row is missing, `registry.load_settings` returns the defaults
(empty `pin_hash`), and `auth.check_pin` then accepts the default `1234`. So deleting the row resets
the PIN:

```bash
# In Docker: stops api, deletes the row, starts api again
make pin-reset

# Outside Docker (stop the server first; by hand the next request reads the change)
sqlite3 data/waffle-bros.db "DELETE FROM settings WHERE key = 'module:admin';"
```

Then sign in with **1234**. The Admin page shows only the change-PIN card, and every other admin
action answers 403 until you choose a new PIN. What else happens: a
new token secret is created at the next sign-in, so every old admin session is signed out, and
`session_hours` goes back to 12. Menu, bills, expenses and other modules are not touched. Take a
backup first if you can. (Checked against `services/auth.py` and `modules/registry.py`, and by
running it on a scratch database.)

**Google Sheet sync isn't running.** Press **Sync now** in **Admin → Modules → Google Sheet sync**.
The message says why. The usual ones:

- "Add the web app URL and secret": one of them is empty.
- "Wrong secret: it must match the POS admin page": `SECRET` in the script differs from the
  module's secret. Fix one and, if it was the script, deploy a new version.
- "Set SECRET in the Apps Script": the placeholder is still in the script.
- "The web app didn't answer with JSON": the URL isn't the `/exec` web app URL, or the deployment's
  access isn't **Anyone**.
- "Could not reach the Google Sheet web app": no internet. Rows wait and go on the next run.
- "Unknown tab ...": the POS is newer than the pasted script. Paste **Setup script** again and
  deploy a new version.

- "A sync is already running": the background run (or another click) hasn't finished. Try again
  in a moment.

The server log also has `[sheets]` warnings (`make logs` in Docker). If `WB_SYNC_INTERVAL_SECONDS`
is set, it overrides the "Sync every" setting (`compose.yaml` no longer sets it).
