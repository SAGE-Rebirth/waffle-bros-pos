# 🧇 Waffle Bros POS

A point-of-sale and revenue-target dashboard for **Waffle Bros, Bhopal**. It runs on the shop computer, needs no internet for billing, and can be opened from a tablet or phone on the shop Wi-Fi.

What makes it different from a regular POS: you set a **monthly revenue target** (say ₹1,00,000) and the app tells you, every day, how close you are, what today's goal is, and what to do to get there, with your running expenses taken into account.

## Screens

![Billing](docs/1-billing.png)
![Dashboard](docs/2-dashboard-target.png)
![Items and expenses](docs/3-dashboard-items-expenses.png)

_Screenshots use the sample data from `uv run python -m waffle_pos.demo`._

| Screen | What it does |
| --- | --- |
| **Billing** | Category menu (Waffle, Mini Waffle, Bowl, Snacks, Combo), item cards with photo, name, price and ID, live bill on the right with the order amount. Dine-in / takeaway / delivery, UPI / cash / card, discount, optional customer, Save or Save & Print (80 mm thermal bill). Today's progress is always visible in the top bar. |
| **Dashboard** | Target ring (month progress vs an even pace), today's goal bar, amount needed per day from tomorrow, projected month end, expenses, net profit. Sales charts (hourly vs an average day, daily with target line, running total vs target pace, weekly, monthly vs target). Best seller, most popular, customer favourite, every item's sales and margin. Expense entry (one-off or monthly). Plain-language insights. |
| **Day End** | Any day's sales, orders, average bill, cash/UPI/card split, items sold, items that didn't sell, every bill (with cancel, which asks for the admin PIN). |
| **Admin** | Behind a PIN (open it from the top bar, or go to `#admin`). **Menu**: add, edit, rename, reorder and hide categories and items, photos, prices, ingredient cost for margins. **Modules**: switch features on or off and change their settings (shop details, colours, billing options, targets, GST, discounts, Google Sheet sync). **Security**: change the PIN. **Backup**: download the database. |

## Admin dashboard

Menu changes, settings, backups, cancelling a bill, the monthly target, expenses and the Google Sheet sync are behind an admin PIN. Staff at the counter can bill and look at the dashboard and day-end, but they can't change prices or quietly cancel a paid bill. When the counter screens need the PIN (Cancel on Day End, the target or expenses on the Dashboard), a PIN box pops up.

- The PIN is **1234** on a new install. Sign in with it and the Admin page shows only one thing: choose your own PIN (4 to 8 digits). Nothing else works until you do, because 1234 is the same in every copy of the POS. Do this on the first day.
- After 5 wrong PINs on a device, that device has to wait 30 seconds, then longer with every further wrong PIN (up to 15 minutes).
- Changing the PIN signs everyone out of the admin dashboard, on every device.
- Sign-in lasts 12 hours on that device.
- Forgot the PIN? On the shop computer, run `make pin-reset`. It goes back to 1234 and asks for a new one.
- More about keeping the POS safe (guest Wi-Fi for customers, never port-forwarding 4000, storing backups): [docs/SECURITY.md](docs/SECURITY.md).
- Features are **modules** you switch on or off under **Admin → Modules**: GST (off until you switch it on), discounts (on, at most 20% of a bill by default), Google Sheet sync (off), and WhatsApp orders (phase 2). Shop details, colours, billing options and targets are always on.

## How the target maths works

The maths lives in `src/waffle_pos/services/targets.py` as pure functions with unit tests.


- **Today's goal** = (monthly target − sales before today) ÷ days left including today. It's fixed for the day, so the bar fills as you bill.
- **Needed per day from tomorrow** = what's still left after today's sales ÷ remaining days.
- **Projected month end** = sales so far + your average daily sales × days left. Averages count from your first sale of the month, so opening mid-month doesn't drag it down.
- **Expenses** = one-off expenses dated this month + every monthly expense (rent, salary) added in or before this month. **Break-even/day** = monthly expenses ÷ days in the month.
- **Best seller** = most revenue. **Most popular** = most units sold. **Customer favourite** = appears in the most separate bills.

## Running it

The POS runs in Docker as two services:

| Service | What it is | Port |
| --- | --- | --- |
| `web` | nginx serving the screens. It forwards `/api` and `/docs` to `api`. | **4000** on the computer (and tablets on the Wi-Fi) |
| `api` | The FastAPI backend, with the SQLite database in the `pos-data` volume. | Inside Docker only; only `web` can reach it |

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) on the shop computer, then from this folder run `make` to see the commands:

| Command | What it does |
| --- | --- |
| `make up` | Build and start the POS on http://localhost:4000. Run it again after every `git pull`. |
| `make down` | Stop the POS. Your data stays. |
| `make logs` | Follow what both services are doing. |
| `make dev` | A live-reload copy for working on the code (see [Development](#development)). |
| `make check` | Everything CI checks: lint, types, tests, OpenAPI drift and the screens build. |
| `make backup` | Save a copy of the live database into `backups/`, safe while billing. |
| `make pin-reset` | Forget the admin PIN, so it goes back to 1234. |

The POS is at http://localhost:4000 (and on tablets via the computer's Wi-Fi address), with the API docs at http://localhost:4000/docs. It restarts by itself after a reboot.

- **Data** lives in the Docker volume `pos-data` (`/data/waffle-bros.db` inside `api`) and survives rebuilds and updates. Download a copy any time from **Admin → Backup**, or run `make backup`.
- **Google Sheet sync** needs no files: it is set up entirely in **Admin → Modules → Google Sheet sync** (see [Google Sheet sync](#google-sheet-sync)).
- **Time zone:** `WB_TIMEZONE` under `api` in `compose.yaml` (default Asia/Kolkata).
- **Hardened containers:** both run as non-root users with a read-only file system, no extra Linux capabilities and no privilege escalation.
- **Never port-forward 4000** on the router. Docker opens the port past the computer's firewall, so tablets on the Wi-Fi can reach it; to keep it on this computer only, change the `web` port line in `compose.yaml` to `"127.0.0.1:4000:8080"`.

Settings for the backend come from environment variables (under `api` in `compose.yaml`) or a `.env` file: `WB_DATA_DIR`, `WB_PORT`, `WB_TIMEZONE` (default `Asia/Kolkata`), `WB_SYNC_INTERVAL_SECONDS` (overrides the "Sync every" setting), `WB_ALLOWED_HOSTS` (extra host names the POS may be opened by, e.g. `pos.waffle-bros.in`; IP addresses, plain computer names and `*.local` names always work), `WB_MAX_BODY_BYTES` (largest request, default 1,000,000) and `WB_FORWARDED_ALLOW_IPS` (proxies whose `X-Forwarded-For` is believed; compose sets `*` because only `web` can reach `api`).

## Development

See `CLAUDE.md` for conventions, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design, [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) for the hands-on guide, [docs/SECURITY.md](docs/SECURITY.md) for security, and [docs/API.md](docs/API.md) for the full API reference (also live at http://localhost:4000/docs).

`make dev` runs both services with live reload, using only Docker:

- Screens with hot reload on http://localhost:5173 (the Vite dev server, forwarding `/api` to `api`).
- The API with auto-reload on http://localhost:8000 (Swagger at http://localhost:8000/docs), running your `src/` directly.
- It's a separate Docker project (`waffle-bros-dev`) with its own `pos-dev-data` volume, so it never touches the shop's data and can run next to `make up`. Ctrl+C stops it.

`make check` needs [uv](https://docs.astral.sh/uv/) and Node.js 22 on your computer. The commands underneath, for when you need just one:

```bash
uv sync                       # .venv with Python 3.12 and the dev tools
uv run pre-commit install     # ruff, ruff-format, mypy and pytest before every commit
uv run ruff check && uv run ruff format --check
uv run ruff check --fix && uv run ruff format   # auto-fix and format
uv run mypy                   # strict
uv run pytest                 # with coverage
uv run python -m waffle_pos.openapi            # regenerate docs/openapi.json after API changes
uv run python -m waffle_pos.demo               # ~6 weeks of made-up sales in data-demo/ (real data is never touched)
WB_DATA_DIR=data-demo uv run waffle-pos        # run the backend on the demo data, http://localhost:4000
cd frontend && npm ci && npm run build         # build the screens (the backend serves frontend/dist if it exists)
```

Database changes: edit `src/waffle_pos/db/models.py`, then `uv run alembic revision --autogenerate -m "what changed"`. The app applies pending migrations on start-up.

CI (GitHub Actions) runs the same checks plus the front-end build on every pull request.

## Google Sheet sync

When it's switched on, the POS copies your bills, items sold and expenses to a Google Sheet every few minutes while the computer is online, so you can look at the numbers from anywhere. Billing never waits for the internet; anything not yet copied catches up later.

It works through a small Google Apps Script that lives inside your sheet. You don't need a Google Cloud project or any key file.

### Setting it up (once)

1. Create a Google Sheet (or use an existing one).
2. In the POS, open **Admin → Modules → Google Sheet sync**. Press **New secret**: it fills in a long random secret. Press **Save**.
3. Press **Setup script** and copy the script it shows.
4. In the Google Sheet, open **Extensions → Apps Script**. Delete what's there and paste the script. Replace `PASTE_THE_SECRET_FROM_THE_POS` with the secret from step 2 (the same text in both places), and save.
5. In Apps Script, choose **Deploy → New deployment**, type **Web app**. Set **Execute as: Me** and **Who has access: Anyone**, then **Deploy**, and allow the permissions Google asks for. "Anyone" only means the POS doesn't need to sign in to Google; every request must carry the secret.
6. Copy the **web app URL** (it ends in `/exec`) into **Web app URL** in the POS, save, switch the module on, and press **Sync now**.

If something is wrong, Sync now says what. For example, a wrong secret, a URL that isn't the `/exec` one, or access not set to Anyone. If you change the secret later, put the same value in the script and deploy a new version (**Deploy → Manage deployments → Edit → New version**, which keeps the same URL). Anything typed at the counter that starts with `=`, `+`, `-` or `@` is written as plain text, never as a formula.

### What it writes

| Tab | How | What's in it |
| --- | --- | --- |
| `Orders` | New rows added | One row per bill. A cancelled bill is added again with status `cancelled`. |
| `OrderItems` | New rows added | One row per item on each bill. |
| `Expenses` | New rows added | Every expense you enter. |
| `Daily` | Rewritten each sync | Last 90 days: revenue, orders, average bill, top item. |
| `Items` | Rewritten each sync | Every menu item with its last 30 days: units, bills, revenue, share of sales and margin. |
| `Monthly` | Rewritten each sync | Last 12 months: target, revenue, orders, average bill, % of target, expenses, net profit. |

The POS creates any of these tabs that are missing and never touches other tabs, so you can add your own, such as an **Overview** tab with KPI formulas and charts built on the tabs above.

## Backups

All data lives in `waffle-bros.db` (SQLite) in the `pos-data` Docker volume. **Admin → Backup** downloads a consistent copy, even while the shop is billing; `make backup` saves one into `backups/` on the shop computer. Keep backups private: they hold customer phone numbers and the admin PIN's hash.

## Project layout

```
src/waffle_pos/
  app.py            FastAPI app factory (routes, middlewares, error format; serves frontend/dist when run outside Docker)
  security.py       Host check, request size limit, security headers
  __main__.py       `uv run waffle-pos`
  config.py         process settings (WB_* env vars)
  clock.py          shop-local time helpers
  schemas.py        Pydantic request/response models
  api/              thin routers: menu, orders, dashboard, finance, system, admin
  modules/          switchable features (shop, theme, billing, targets, GST, discounts, Sheets, WhatsApp) and their settings
  services/         business logic: orders, menu, auth (admin PIN), targets (pure maths), analytics, insights
  db/               SQLAlchemy models, session, migrations runner, starter menu
  migrations/       Alembic
  integrations/     Google Sheet sync and the Apps Script to paste into the sheet
  demo.py           demo data generator
tests/              pytest: API, target maths, analytics, Sheets sync (mocked)
frontend/           React + Vite screens, and their image (Dockerfile, nginx.conf)
docs/               API, architecture, implementation guide, security
Makefile            the seven everyday commands (`make`)
Dockerfile          the api image
compose.yaml        the web + api services; compose.dev.yaml adds live reload for `make dev`
```

## Phase 2: WhatsApp ordering (planned)

Orders already carry `source` (`counter` / `whatsapp`), `order_type` (`delivery`) and `delivery_address` fields, and `POST /api/integrations/whatsapp` is reserved for the WhatsApp Business webhook. Online orders from the apartment residents will land on the same dashboard and count toward the target.
