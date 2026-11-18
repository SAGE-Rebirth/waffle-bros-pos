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
| **Billing** | Category menu (Waffle, Sandwich, Combo, Mini Waffle), item cards with photo, name, price and ID, live bill on the right with the order amount. Dine-in / takeaway / delivery, UPI / cash / card, discount, optional customer, Save or Save & Print (80 mm thermal bill). Today's progress is always visible in the top bar. |
| **Dashboard** | Target ring (month progress vs an even pace), today's goal bar, amount needed per day from tomorrow, projected month end, expenses, net profit. Sales charts (hourly vs an average day, daily with target line, running total vs target pace, weekly, monthly vs target). Best seller, most popular, customer favourite, every item's sales and margin. Expense entry (one-off or monthly). Plain-language insights. |
| **Day End** | Any day's sales, orders, average bill, cash/UPI/card split, items sold, items that didn't sell, every bill (with cancel). |
| **Settings** | Menu editor (add/edit items and photos, prices, ingredient cost for margins, hide items), shop details and GST, Google Sheet sync, backup download. |

## How the target maths works

The maths lives in `src/waffle_pos/services/targets.py` as pure functions with unit tests.


- **Today's goal** = (monthly target − sales before today) ÷ days left including today. It's fixed for the day, so the bar fills as you bill.
- **Needed per day from tomorrow** = what's still left after today's sales ÷ remaining days.
- **Projected month end** = sales so far + your average daily sales × days left. Averages count from your first sale of the month, so opening mid-month doesn't drag it down.
- **Expenses** = one-off expenses dated this month + every monthly expense (rent, salary) added in or before this month. **Break-even/day** = monthly expenses ÷ days in the month.
- **Best seller** = most revenue. **Most popular** = most units sold. **Customer favourite** = appears in the most separate bills.

## Running it

You need **[uv](https://docs.astral.sh/uv/)** (it installs the right Python by itself) and, to build the screens once, **Node.js 22**.

**Windows:** double-click `start-pos.bat`. The first run sets everything up, then the POS opens at http://localhost:4000.

**macOS / Linux:** `./start-pos.sh`

Or by hand:

```bash
uv sync                                  # creates .venv with Python 3.12 and all dependencies
(cd frontend && npm ci && npm run build) # build the screens once
uv run waffle-pos                        # http://localhost:4000 (also prints the Wi-Fi address for tablets)
```

API docs are at http://localhost:4000/docs.

Settings for the server process come from environment variables or a `.env` file: `WB_DATA_DIR`, `WB_PORT`, `WB_TIMEZONE` (default `Asia/Kolkata`), `WB_SYNC_INTERVAL_SECONDS`.

### Try it with sample data

```bash
uv run python -m waffle_pos.demo                 # ~6 weeks of made-up sales in data-demo/ (your real data/ is untouched)
WB_DATA_DIR=data-demo uv run waffle-pos          # Windows: set WB_DATA_DIR=data-demo && uv run waffle-pos
```

## Development

```bash
uv sync                       # dev tools included
uv run pre-commit install     # ruff, ruff-format, mypy and pytest before every commit
uv run ruff check && uv run ruff format --check
uv run mypy                   # strict
uv run pytest                 # with coverage
uv run uvicorn waffle_pos.app:create_app --factory --reload --port 4000   # API with auto-reload
cd frontend && npm run dev    # screens with hot reload on :5173, proxied to the API
```

Database changes: edit `src/waffle_pos/db/models.py`, then `uv run alembic revision --autogenerate -m "what changed"`. The app applies pending migrations on start-up.

CI (GitHub Actions) runs the same checks plus the front-end build on every pull request.

## Google Sheet sync

Every 5 minutes, when the computer is online, new bills, items sold and expenses are appended to a Google Sheet and a **Daily** summary tab is refreshed. Billing never waits for the internet; unsynced rows catch up later. Setup steps are in **Settings → Google Sheet** (a service account key plus sharing the sheet with it). **Sync now** on that screen runs it immediately.

Tabs created: `Orders`, `OrderItems`, `Expenses`, `Daily`.

## Backups

All data lives in `data/waffle-bros.db` (SQLite). **Settings → Backup** downloads a consistent copy, even while the shop is billing.

## Project layout

```
src/waffle_pos/
  app.py            FastAPI app factory (routes, error format, serves frontend/dist)
  __main__.py       `uv run waffle-pos`
  config.py         process settings (WB_* env vars)
  clock.py          shop-local time helpers
  schemas.py        Pydantic request/response models
  api/              thin routers: menu, orders, dashboard, finance, system
  services/         business logic: orders, menu, settings, targets (pure maths), analytics, insights
  db/               SQLAlchemy models, session, migrations runner, starter menu
  migrations/       Alembic
  integrations/     Google Sheets sync
  demo.py           demo data generator
tests/              pytest: API, target maths, analytics, Sheets sync (mocked)
frontend/           React + Vite screens
```

## Phase 2: WhatsApp ordering (planned)

Orders already carry `source` (`counter` / `whatsapp`), `order_type` (`delivery`) and `delivery_address` fields, and `POST /api/integrations/whatsapp` is reserved for the WhatsApp Business webhook. Online orders from the apartment residents will land on the same dashboard and count toward the target.
