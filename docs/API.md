# Waffle Bros POS API

The React screens (Billing, Dashboard, Day End, Admin) use exactly this API, so anything the
cashier or owner can do on screen, a script or Claude can do with `curl`. This page is the
practical reference; the machine-readable schema is [`openapi.json`](openapi.json), generated from
the code with `uv run python -m waffle_pos.openapi`.

While the POS is running you can also browse and try every endpoint at:

- **Swagger UI:** <http://localhost:4000/docs>
- **ReDoc:** <http://localhost:4000/redoc>
- **Raw schema:** <http://localhost:4000/openapi.json>

Every example response below is real output from the demo data (`uv run python -m waffle_pos.demo`),
or from a fresh install for the admin endpoints, trimmed where marked with `...`. Examples that
change things need an admin token in `$T`: see [Admin & config](#admin--config).

## Contents

- [Conventions](#conventions)
- [Menu](#menu): `GET /api/menu`, `POST /api/categories`, `PUT /api/categories/{id}`, `DELETE /api/categories/{id}`, `POST /api/categories/reorder`, `POST /api/items`, `PUT /api/items/{id}`, `DELETE /api/items/{id}`, `POST /api/items/reorder`
- [Orders](#orders): `POST /api/orders`, `GET /api/orders`, `GET /api/orders/{id}`, `POST /api/orders/{id}/cancel`
- [Dashboard](#dashboard): `GET /api/dashboard`, `GET /api/items/stats`, `GET /api/day-end`
- [Finance](#finance): `PUT /api/targets/{month}`, `GET /api/expenses`, `POST /api/expenses`, `DELETE /api/expenses/{id}`
- [Admin & config](#admin--config): `GET /api/config`, `POST /api/admin/login`, `POST /api/admin/pin`, `GET /api/admin/modules`, `PUT /api/admin/modules/{key}`, `GET /api/admin/google-sheet/script`
- [System](#system): `GET /api/health`, `POST /api/sync`, `GET /api/backup`, `POST /api/integrations/whatsapp`
- [Recipes](#recipes)

## Conventions

| Topic | Rule |
| --- | --- |
| Base URL | `http://localhost:4000` on the shop computer, or `http://<its Wi-Fi IP>:4000` from a tablet. `WB_PORT` changes the port. The `Host` must be an IP address, a single-word name (`localhost`, `shop-pc`), a `*.local` name or listed in `WB_ALLOWED_HOSTS`; anything else gets 400 (protection against DNS rebinding). |
| Format | JSON in and out. Send `Content-Type: application/json` with every body. Bodies over 1,000,000 bytes (`WB_MAX_BODY_BYTES`) get 413. `Infinity` and `NaN` are refused. |
| Limits | Money fields (prices, costs, discounts, expenses) are at most ₹1,00,00,000 (₹1 crore), a monthly target at most ₹10,00,00,000. A bill has at most 100 lines; notes at most 300 characters; images must be `data:image/...` URLs or paths on this server, at most 200,000 characters. |
| Money | Rupees as JSON numbers (`199.0` is ₹199), rounded to 2 decimals. GST, when the GST module is on, is added on top of menu prices. |
| Times | Shop-local time (`WB_TIMEZONE`, default `Asia/Kolkata`), never UTC. Timestamps are `"YYYY-MM-DD HH:MM:SS"`, dates `"YYYY-MM-DD"`, months `"YYYY-MM"`. "Today" and "this month" are in shop time. |
| Revenue | Only **paid** bills count towards revenue, targets and item stats. Cancelled bills are kept but excluded. |
| Ids | Numeric `id`s are used in paths and bodies. A menu item's `code` (`W01`) and a bill's `bill_no` (`WB261118-001`) are for people. |
| Errors | JSON `{"error": "message"}`, a message you can show to the cashier as-is. |
| Auth | Billing, looking up bills and reading the reports are open to anyone on the shop network, so keep port 4000 off the internet. Everything else needs an admin token: menu changes, cancelling a bill, targets, adding or deleting expenses, Google Sheet sync, backups and the `/api/admin/*` endpoints. Sign in with the PIN (`POST /api/admin/login`) and send `Authorization: Bearer <token>`. Those endpoints are marked **Admin** below. While the PIN is still the default `1234`, an admin token only works for `POST /api/admin/pin` (others answer 403). See [Admin & config](#admin--config) and [SECURITY.md](SECURITY.md). |

Error status codes:

| Status | Meaning | Example body |
| --- | --- | --- |
| 400 | Request understood but refused | `{"error": "That item ID is already used"}` |
| 401 | Admin token missing, wrong or expired (or wrong PIN at sign-in) | `{"error": "Admin PIN required"}` |
| 403 | Signed in with the default PIN 1234, which can only change the PIN | `{"error": "Change the default PIN 1234 first (POST /api/admin/pin)"}` |
| 404 | No such order or item (also unknown `/api/...` paths, and ids too big to exist) | `{"error": "Not found"}` |
| 413 | Request body too large | `{"error": "The request is too large"}` |
| 422 | Validation failed, as `field: reason` | `{"error": "payment_method: Input should be 'cash', 'upi' or 'card'"}` |
| 429 | Too many wrong PINs; has a `Retry-After` header (seconds) | `{"error": "Too many wrong PINs. Try again in 30 seconds."}` |
| 501 | Not built yet | `{"error": "WhatsApp ordering is planned for phase 2"}` |

Each request is one database transaction: it is saved completely or not at all.

## Menu

Reading the menu is open (the billing screen needs it). **Every menu change needs the admin token**
(`Authorization: Bearer $T`, see [Admin & config](#admin--config)); without it the answer is 401
`Admin PIN required`, and with a default-PIN token 403.

### `GET /api/menu`: the full menu

All categories in display order and all items, including hidden ones (`active: false`). The
billing screen shows only active items.

```bash
curl http://localhost:4000/api/menu
```

```json
{
  "categories": [
    {"id": 1, "name": "Waffle", "sort": 0},
    {"id": 2, "name": "Sandwich", "sort": 1},
    {"id": 3, "name": "Combo", "sort": 2},
    {"id": 4, "name": "Mini Waffle", "sort": 3}
  ],
  "items": [
    {
      "id": 1, "code": "W01", "name": "Classic Maple Butter",
      "category_id": 1, "category": "Waffle",
      "price": 129.0, "cost": 40.0, "image": null,
      "veg": true, "active": true, "sort": 0
    },
    ...
  ]
}
```

### `POST /api/categories`: add a category (Admin)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string, 1-60 chars | yes | Must be unique (case-insensitive). Added at the end. |

```bash
curl -X POST http://localhost:4000/api/categories -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"name": "Shakes"}'
```

```json
{"id": 5}
```

Errors: 400 `That category already exists`.

### `PUT /api/categories/{category_id}`: rename a category (Admin)

Same body as create (`name`). Past bills keep the category name they were billed under.

```bash
curl -X PUT http://localhost:4000/api/categories/5 -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"name": "Milkshakes"}'
```

```json
{"ok": true}
```

Errors: 400 `That category already exists`, 404 `Category not found`.

### `DELETE /api/categories/{category_id}`: delete an empty category (Admin)

Only a category with no items can be deleted; hidden items count. Move or delete its items first.

```bash
curl -X DELETE http://localhost:4000/api/categories/5 -H "Authorization: Bearer $T"
```

```json
{"ok": true}
```

Errors: 400 `Move or remove this category's items first`, 404 `Category not found`.

### `POST /api/categories/reorder`: set the category order (Admin)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `ids` | array of integers, at least one | yes | Category `id`s in the new order. Any not listed keep their order after these. |

```bash
curl -X POST http://localhost:4000/api/categories/reorder -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"ids": [2, 1, 3, 4]}'
```

```json
{"ok": true}
```

Errors: 400 `Unknown id 99`, 422 for an empty list.

### `POST /api/items`: add a menu item (Admin)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `code` | string, 1-12 chars | yes | Short unique ID shown on the till, e.g. `SH01`. Upper-cased. |
| `name` | string, 1-120 chars | yes | |
| `category_id` | integer | yes | An existing category `id`. |
| `price` | number 0 to 1,00,00,000 | yes | Selling price in rupees, before GST. GST is not per item: it's the `gst` module. |
| `cost` | number 0 to 1,00,00,000 | no, `0` | Cost to make in rupees. Only used for margins; `0` = unknown. |
| `image` | string or null | no | A `data:image/(png\|jpeg\|webp\|gif);base64,...` URL (what the Admin page uploads) or a path on this server, at most 200,000 characters. External URLs are refused (422). |
| `veg` | boolean | no, `true` | |
| `active` | boolean | no, `true` | `false` hides it from billing. |

```bash
curl -X POST http://localhost:4000/api/items -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"code": "SH01", "name": "Oreo Shake", "category_id": 5, "price": 149, "cost": 45}'
```

```json
{"id": 19}
```

Errors: 400 `That item ID is already used` (duplicate `code`), 400 `Pick a valid category`, 422 for
missing or invalid fields.

### `PUT /api/items/{item_id}`: update a menu item (Admin)

Replaces **every** field, so send the whole item (same body as create). Read the current values
from `GET /api/menu` first. A new price applies to new bills only; past bills keep their price.

```bash
curl -X PUT http://localhost:4000/api/items/19 -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"code": "SH01", "name": "Oreo Shake", "category_id": 5, "price": 159, "cost": 45}'
```

```json
{"ok": true}
```

Errors: 404 `Item not found`, plus the 400/422 errors of create.

### `DELETE /api/items/{item_id}`: delete or hide an item (Admin)

An item that has never been billed is deleted. One that appears on past bills is **hidden**
instead (`active` becomes `false`) so old bills stay readable; the response says which happened.
An unknown id is not an error.

```bash
curl -X DELETE http://localhost:4000/api/items/18 -H "Authorization: Bearer $T"
```

```json
{"ok": true, "hidden": true}
```

### `POST /api/items/reorder`: set the item order (Admin)

Same body as the category reorder: `{"ids": [...]}` with item `id`s. Listed items are placed
first, in that order. Send one category's items to reorder that category on the billing screen.

```bash
curl -X POST http://localhost:4000/api/items/reorder -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"ids": [5, 4, 1, 2, 3]}'
```

```json
{"ok": true}
```

Errors: 400 `Unknown id 99`, 422 for an empty list.

## Orders

An order is a bill. Its shape, as returned by every endpoint in this section:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | integer | Use in paths. |
| `bill_no` | string | `WB<yymmdd>-<nnn>`, numbered from 001 each day. |
| `created_at` | string | Shop-local `YYYY-MM-DD HH:MM:SS`. |
| `subtotal` | number | Sum of `price x qty` over the lines. |
| `discount` | number | Rupees off, before GST. |
| `tax` | number | GST: `(subtotal - discount) x rate / 100`, using the `gst` module's `rate` when that module is on, else 0. |
| `total` | number | `subtotal - discount + tax`. What the customer pays. |
| `payment_method` | string | `cash`, `upi` or `card`. |
| `order_type` | string | `dine-in`, `takeaway` or `delivery`. |
| `source` | string | `counter` (or `whatsapp`, phase 2). |
| `customer_name`, `customer_phone`, `delivery_address`, `note` | string or null | |
| `status` | string | `paid` or `cancelled`. |
| `items` | array | Lines: `id`, `item_id` (null if the menu item was later deleted), `name`, `category`, `price`, `qty`. Name, category and price are copied at billing time. |

### `POST /api/orders`: bill an order

Creates a **paid** bill. Prices always come from the menu, never from the request.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `items` | array of `{item_id, qty}` | yes, 1 to 100 lines | `item_id` = menu item `id` of an **active** (not hidden) item; `qty` 1-999, default 1. |
| `discount` | number 0 to 1,00,00,000 | no, `0` | Rupees off before GST. Needs the `discounts` module on (it is by default), and can be at most `max_discount_pct` (default 20) % of the subtotal. |
| `payment_method` | `cash` / `upi` / `card` | no, `cash` | |
| `order_type` | `dine-in` / `takeaway` / `delivery` | no, `dine-in` | |
| `source` | `counter` / `whatsapp` | no, `counter` | |
| `customer_name` | string <= 80 | no | |
| `customer_phone` | string <= 20 | no | |
| `delivery_address` | string <= 200 | no | |
| `note` | string <= 300 | no | |

```bash
curl -X POST http://localhost:4000/api/orders -H 'Content-Type: application/json' \
  -d '{"items": [{"item_id": 5, "qty": 2}], "discount": 20,
       "payment_method": "upi", "order_type": "takeaway", "customer_name": "Ravi"}'
```

```json
{
  "id": 517,
  "bill_no": "WB261118-002",
  "created_at": "2026-11-18 15:20:17",
  "subtotal": 398.0,
  "discount": 20.0,
  "tax": 18.9,
  "total": 396.9,
  "payment_method": "upi",
  "order_type": "takeaway",
  "source": "counter",
  "customer_name": "Ravi",
  "customer_phone": null,
  "delivery_address": null,
  "status": "paid",
  "note": null,
  "items": [
    {"id": 794, "item_id": 5, "name": "Nutella", "category": "Waffle", "price": 199.0, "qty": 2}
  ]
}
```

The example was billed with the `gst` module on at 5%. With GST off (the default) `tax` is `0.0`.

Money is rounded to 2 decimals with halves going up (`services.targets.money`).

Errors: 400 `The order is empty`, 400 `Unknown item 999`, 400 `Nutella is hidden from the menu and
can't be billed`,
400 `Discounts are switched off in the admin dashboard` (a discount was sent while the `discounts`
module is off), 400 `Discount can be at most 20% of the bill (₹80)` (over the cap; the rupee
figure is the cap for this bill), 422 e.g. `payment_method: Input should be 'cash', 'upi' or 'card'`.

### `GET /api/orders?date=YYYY-MM-DD`: one day's bills

All bills created that shop-local day (default today), newest first, **including cancelled ones**.

```bash
curl 'http://localhost:4000/api/orders?date=2026-11-17'
```

Returns a JSON array of orders (shape above).

### `GET /api/orders/{order_id}`: one bill

```bash
curl http://localhost:4000/api/orders/1
```

```json
{
  "id": 1, "bill_no": "WB261001-001", "created_at": "2026-10-01 12:34:13",
  "subtotal": 129.0, "discount": 0.0, "tax": 0.0, "total": 129.0,
  "payment_method": "upi", "order_type": "takeaway", "source": "counter",
  "customer_name": null, "customer_phone": null, "delivery_address": null,
  "status": "paid", "note": null,
  "items": [{"id": 1, "item_id": 1, "name": "Classic Maple Butter", "category": "Waffle", "price": 129.0, "qty": 1}]
}
```

Errors: 404 `Not found`.

### `POST /api/orders/{order_id}/cancel`: cancel a bill (Admin)

Needs the admin token, so a paid bill can't be quietly cancelled at the counter (the Day End screen
asks for the PIN). Sets `status` to `cancelled` and returns the bill. It stays in the database (bills are history) but
stops counting towards revenue, targets and item stats; the day-end sheet lists it under
`cancelled`. The next Google Sheet sync appends the bill again with status `cancelled`. No body.

```bash
curl -X POST http://localhost:4000/api/orders/517/cancel -H "Authorization: Bearer $T"
```

```json
{"id": 517, "bill_no": "WB261118-002", ..., "total": 396.9, "status": "cancelled", ...}
```

Errors: 401, 403, 404 `Not found`.

## Dashboard

Read-only numbers, always computed for the shop-local **now**. Only paid bills count. Item and
category revenue is line value (`price x qty`), before bill discounts and GST; order revenue
(`revenue`, `todayRevenue`, payment split) is bill `total`, after discount and including GST.

### `GET /api/dashboard?period=month`: everything the Dashboard page shows

`period` (`today`, `week`, `month`, `30d`, `all`; default `month`) only affects the `items` part.

```bash
curl http://localhost:4000/api/dashboard
```

```json
{
  "target":   { ... },
  "charts":   { "hourly": [...], "daily": [...], "weekly": [...], "monthly": [...],
                "categorySplit": [...], "paymentSplit": [...], "weekday": [...] },
  "insights": [ ... ],
  "items":    { ... same as GET /api/items/stats?period=month ... }
}
```

#### `target`: this month's target summary

Real values on 18 Nov 2026 (target ₹1,00,000, one bill so far today):

```json
{
  "month": "2026-11",
  "target": 100000.0,
  "daysInMonth": 30,
  "dayOfMonth": 18,
  "daysLeft": 13,
  "revenue": 77471.0,
  "orders": 207,
  "todayRevenue": 447.0,
  "todayOrders": 1,
  "expenses": {
    "total": 78332.0,
    "recurringTotal": 52500.0,
    "oneOffTotal": 25832.0,
    "byCategory": [
      {"category": "rent", "amount": 25000.0},
      {"category": "salary", "amount": 24000.0},
      {"category": "ingredients", "amount": 21409.0},
      ...
    ]
  },
  "progressPct": 77.47,
  "expectedPct": 60.0,
  "remaining": 22529.0,
  "evenDailyTarget": 3333.33,
  "todayTarget": 1767.38,
  "todayPct": 25.29,
  "todayRemaining": 1320.38,
  "requiredDailyFromTomorrow": 1877.42,
  "avgDaily": 4530.82,
  "projected": 135924.71,
  "aov": 374.26,
  "ordersNeededToday": 4,
  "netProfit": -861.0,
  "breakEvenDaily": 2611.07,
  "breakEvenRemainingDaily": 66.23
}
```

Definitions. "Before today" means from the 1st of the month up to midnight today.
The maths lives in `src/waffle_pos/services/targets.py` (pure functions, unit tested).

| Key | Meaning | Formula |
| --- | --- | --- |
| `month` | Current month | `YYYY-MM` |
| `target` | This month's revenue target | `PUT /api/targets/{month}` value, else the `targets` module's `default_target` |
| `daysInMonth`, `dayOfMonth` | Calendar | |
| `daysLeft` | Days left, **including today** | `daysInMonth - dayOfMonth + 1` |
| `revenue`, `orders` | Month to date, including today | sum of paid bill `total`s, count |
| `todayRevenue`, `todayOrders` | Today only | |
| `expenses` | This month's expenses (see `GET /api/expenses`, without the lists) | |
| `progressPct` | % of target reached | `revenue / target x 100` |
| `expectedPct` | Where an even pace would put you by the end of today | `dayOfMonth / daysInMonth x 100` |
| `remaining` | Rupees still needed this month | `max(0, target - revenue)` |
| `evenDailyTarget` | Target spread evenly over the month | `target / daysInMonth` |
| `todayTarget` | Today's goal, fixed from the start of the day (doesn't move while billing) | `max(0, (target - revenueBeforeToday) / daysLeft)` |
| `todayPct` | % of today's goal done | `todayRevenue / todayTarget x 100` (100 if `todayTarget` is 0) |
| `todayRemaining` | Left to sell today | `max(0, todayTarget - todayRevenue)` |
| `requiredDailyFromTomorrow` | Needed per day after today to hit the target | `max(0, (target - revenue) / (daysLeft - 1))`; on the last day, `remaining` |
| `avgDaily` | Average per trading day so far | `revenueBeforeToday / tradingDays`, where `tradingDays` = completed days since this month's first paid sale (so a mid-month opening isn't diluted); if 0, `todayRevenue` |
| `projected` | Month-end estimate at the current pace | `revenueBeforeToday + avgDaily x daysLeft` |
| `aov` | Average bill value this month | `revenue / orders` (0 if no orders) |
| `ordersNeededToday` | Bills still needed today at the average bill | `ceil(todayRemaining / aov)`, `null` if `aov` is 0 |
| `netProfit` | Month to date | `revenue - expenses.total` |
| `breakEvenDaily` | Daily sales that cover this month's expenses | `expenses.total / daysInMonth` |
| `breakEvenRemainingDaily` | Daily sales needed for the rest of the month (incl. today) to cover expenses | `max(0, expenses.total - revenue) / daysLeft` |

Worked check with the numbers above: `revenueBeforeToday` = 77,471 - 447 = 77,024;
`todayTarget` = (1,00,000 - 77,024) / 13 = 1,767.38; trading days = 17 (1st to 17th), so
`avgDaily` = 77,024 / 17 = 4,530.82 and `projected` = 77,024 + 4,530.82 x 13 = 1,35,924.71.

#### `charts`

| Key | Rows | Row fields |
| --- | --- | --- |
| `hourly` | One per hour from opening hour to closing hour (widened if a sale fell outside) | `hour` (0-23), `label` (`"8pm"`), `today` (₹ this hour today), `todayOrders`, `average` (₹ in this hour over the previous 28 days / number of days that had sales), `avgOrders` (same, for bill count) |
| `daily` | Every day of this month | `day` (1-31), `date`, `revenue`, `orders`, `cumulative` (running total), all `null` for future days; `pace` (even-pace cumulative target: `target / daysInMonth x day`), `dailyTarget` (`target / daysInMonth`) |
| `weekly` | Last 12 weeks, Monday to Sunday, oldest first | `week` (`"31 Aug"`), `start` (Monday's date), `revenue`, `orders` |
| `monthly` | Last 12 months, oldest first | `month` (`"Nov 26"`), `key` (`"2026-11"`), `revenue`, `orders`, `target`, `expenses` (that month's total) |
| `categorySplit` | Categories sold this month, biggest first | `name`, `value` (₹ line value), `qty` |
| `paymentSplit` | Payment methods this month, biggest first | `name` (`upi`/`cash`/`card`), `value` (₹ bill totals), `orders` |
| `weekday` | Mon..Sun | `day` (`"Mon"`), `average` (₹ per trading day of that weekday over the last 8 weeks, before today; 0 if none) |

```json
{
  "hourly": [{"hour": 10, "label": "10am", "today": 0.0, "todayOrders": 0, "average": 127.5, "avgOrders": 0.29}, ...],
  "daily": [
    {"day": 1, "date": "2026-11-01", "revenue": 7492.0, "orders": 18, "cumulative": 7492.0, "pace": 3333.33, "dailyTarget": 3333.33},
    ...,
    {"day": 30, "date": "2026-11-30", "revenue": null, "orders": null, "cumulative": null, "pace": 100000.0, "dailyTarget": 3333.33}
  ],
  "weekly": [{"week": "31 Aug", "start": "2026-08-31", "revenue": 0.0, "orders": 0}, ...],
  "monthly": [{"month": "Dec 25", "key": "2025-12", "revenue": 0.0, "orders": 0, "target": 100000.0, "expenses": 0.0}, ...],
  "categorySplit": [{"name": "Waffle", "value": 46909.0, "qty": 261}, {"name": "Combo", "value": 18564.0, "qty": 56}, ...],
  "paymentSplit": [{"name": "upi", "value": 51831.0, "orders": 133}, {"name": "cash", "value": 20545.0, "orders": 61}, ...],
  "weekday": [{"day": "Mon", "average": 2316.14}, {"day": "Tue", "average": 2832.0}, ...]
}
```

#### `insights`: plain-English tips

A list of `{tone, title, text}` with `tone` = `good`, `warn` or `info`, in this order when they
apply: target pace (on track / behind), today's goal (or target reached), average bill, expenses
(add them / not covering / net so far) and the biggest cost, busiest and quietest hour, strongest
and weakest weekday, best seller, slow movers and thin-margin items (last 30 days). With no sales
this month there is a single "No sales yet this month" tip. Amounts in the text use Indian
formatting (`₹1,35,925`). Logic: `src/waffle_pos/services/insights.py`.

```json
[
  {"tone": "good", "title": "On track for the monthly target",
   "text": "At your current average of ₹4,531/day you'll finish around ₹1,35,925, ₹35,925 above the ₹1,00,000 target."},
  {"tone": "info", "title": "Today's goal",
   "text": "₹447 of ₹1,767 done. ₹1,320 to go, about 4 more orders at your average bill of ₹374."},
  {"tone": "warn", "title": "Not covering expenses yet",
   "text": "Expenses this month are ₹78,332 against ₹77,471 in sales. Break-even needs ₹66/day for the rest of the month."},
  {"tone": "info", "title": "Busiest hour: 8pm",
   "text": "Averages ₹818. Keep batter and toppings prepped before then. Quietest is 11am (₹66), a good slot for a happy-hour offer or mini-waffle deal."},
  ...
]
```

### `GET /api/items/stats?period=month`: menu item performance

`period`: `today`; `week` (last 7 days incl. today); `month` (1st of this month to now); `30d`
(last 30 days incl. today); `all`. Anything else is a 422.

| Key | Meaning |
| --- | --- |
| `period` | As requested |
| `from`, `to` | Date range; `to` is **exclusive** (tomorrow). `from` is `"0000-00-00"` for `all`. |
| `items` | Every menu item (sold or not, hidden ones included), sorted by revenue then qty |
| `bestSeller` | Item with the most revenue (`null` if nothing sold) |
| `mostPopular` | Item with the most units sold |
| `customerFavourite` | Item on the most separate bills |
| `topByRevenue`, `topByQty` | Top 5 sold items by each |
| `slowMovers` | 5 **active** items with the fewest units (then least revenue), unsold ones first |

Item fields: `id`, `code`, `name`, `category`, `price`, `cost`, `active`, `qty` (units),
`orders` (bills containing it), `revenue` (₹ `price x qty` at billed prices), `share` (% of all
item revenue in the period), `margin` (`(price - cost) / price x 100`, `null` when `cost` is 0).

```bash
curl 'http://localhost:4000/api/items/stats?period=month'
```

```json
{
  "period": "month",
  "from": "2026-11-01",
  "to": "2026-11-19",
  "items": [
    {"id": 5, "code": "W05", "name": "Nutella", "category": "Waffle", "price": 199.0, "cost": 70.0,
     "active": true, "qty": 46, "orders": 38, "revenue": 9154.0, "share": 11.77, "margin": 64.82},
    {"id": 4, "code": "W04", "name": "Triple Chocolate", "category": "Waffle", "price": 189.0, "cost": 62.0,
     "active": true, "qty": 46, "orders": 37, "revenue": 8694.0, "share": 11.18, "margin": 67.2},
    ...
  ],
  "bestSeller": {"id": 5, "code": "W05", "name": "Nutella", ...},
  "mostPopular": {"id": 5, "code": "W05", "name": "Nutella", ...},
  "customerFavourite": {"id": 5, "code": "W05", "name": "Nutella", ...},
  "topByRevenue": [...],
  "topByQty": [...],
  "slowMovers": [...]
}
```

### `GET /api/day-end?date=YYYY-MM-DD`: day-end closing sheet

The cash-up summary for one shop-local day (default today).

| Key | Meaning |
| --- | --- |
| `date` | The day |
| `revenue`, `orders` | Paid bills: sum of `total`, count |
| `aov` | `revenue / orders` (0 if none) |
| `items` | Items sold, by revenue: `name`, `category`, `qty`, `revenue` (line value), `orders` |
| `notSold` | Active menu items with no paid sale that day: `name`, `category` |
| `payments` | Per method: `method`, `amount` (₹ bill totals), `orders`. Use for cash-drawer reconciliation. |
| `cancelled` | Bills cancelled that day: `n`, `amount` (₹) |

```bash
curl 'http://localhost:4000/api/day-end?date=2026-11-17'
```

```json
{
  "date": "2026-11-17",
  "revenue": 4550.0,
  "orders": 10,
  "aov": 455.0,
  "items": [
    {"name": "Family Pack (4 Waffles)", "category": "Combo", "qty": 3, "revenue": 1647.0, "orders": 2},
    {"name": "Triple Chocolate", "category": "Waffle", "qty": 6, "revenue": 1134.0, "orders": 5},
    ...
  ],
  "notSold": [{"name": "Milk Chocolate", "category": "Waffle"}, ...],
  "payments": [
    {"method": "cash", "amount": 914.0, "orders": 4},
    {"method": "upi", "amount": 3636.0, "orders": 6}
  ],
  "cancelled": {"n": 0, "amount": 0.0}
}
```

## Finance

### `PUT /api/targets/{month}`: set a month's revenue target (Admin)

Needs the admin token (the Dashboard asks for the PIN).

`month` is `YYYY-MM`. Months without their own target use the `targets` module's
`default_target` (₹1,00,000 out of the box).

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `amount` | number > 0, at most 10,00,00,000 | yes | Rupees. |
| `makeDefault` | boolean | no, `false` | Also save it as `targets.default_target`, used for months without a target. |

```bash
curl -X PUT http://localhost:4000/api/targets/2026-12 -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"amount": 120000, "makeDefault": false}'
```

```json
{"ok": true}
```

Errors: 400 `Enter a valid month (YYYY-MM)`, 401, 403, 422 `amount: Input should be greater than 0`.

### `GET /api/expenses?month=YYYY-MM`: a month's expenses

Open (no token). Default month: the current one. **One-off** expenses count in the month of their `date`;
**recurring** ones (rent, salaries) count in every month from the month of their `date` on, until
deleted. `byCategory` is biggest first; lists are newest first.

```bash
curl 'http://localhost:4000/api/expenses?month=2026-11'
```

```json
{
  "total": 78332.0,
  "recurringTotal": 52500.0,
  "oneOffTotal": 25832.0,
  "byCategory": [{"category": "rent", "amount": 25000.0}, {"category": "salary", "amount": 24000.0}, ...],
  "recurring": [
    {"id": 3, "date": "2026-10-01", "category": "electricity", "amount": 3500.0, "note": "Approx. monthly bill", "recurring": true},
    ...
  ],
  "oneOff": [
    {"id": 13, "date": "2026-11-12", "category": "packaging", "amount": 1423.0, "note": "Boxes, forks, tissues", "recurring": false},
    ...
  ]
}
```

Errors: 400 `Enter a valid month (YYYY-MM)`.

### `POST /api/expenses`: add an expense (Admin)

Needs the admin token (the Dashboard asks for the PIN).

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `category` | string, 1-30 chars | yes | Free text, stored lower-case. The app offers the `targets` module's `expense_categories` (rent, salary, ingredients, electricity, packaging, marketing, maintenance, other by default). |
| `amount` | number > 0, at most 1,00,00,000 | yes | Rupees. |
| `date` | `YYYY-MM-DD` | no, today | |
| `note` | string <= 300 | no | |
| `recurring` | boolean | no, `false` | `true` for a monthly cost: counts every month from `date`. |

```bash
curl -X POST http://localhost:4000/api/expenses -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"category": "gas", "amount": 1850, "date": "2026-11-18", "note": "LPG cylinder"}'
```

```json
{"id": 15}
```

### `DELETE /api/expenses/{expense_id}`: delete an expense (Admin)

Permanent. A deleted recurring expense stops counting in every month, past ones included. An
unknown id is not an error. Rows already copied to the Google Sheet stay there.

```bash
curl -X DELETE http://localhost:4000/api/expenses/15 -H "Authorization: Bearer $T"
```

```json
{"ok": true}
```

## Admin & config

The owner's settings live in **feature modules**. Each module has an on/off switch and its own
settings, and the Admin page (`#admin`) draws its forms from what these endpoints return.

| Module (`key`) | What it does | Default | Settings |
| --- | --- | --- | --- |
| `shop` | Shop details | always on | `shop_name`, `shop_address`, `shop_phone`, `receipt_footer`, `logo`, `open_hour`, `close_hour` |
| `theme` | Colours used across the POS | always on | `primary`, `dark`, `accent`, `background` (`#RRGGBB`) |
| `billing` | Payment methods, order types, bill options | always on | `payment_methods`, `default_payment`, `order_types`, `customer_capture`, `print_on_save` |
| `targets` | Monthly target, insight thresholds, expense categories | always on | `default_target`, `slow_mover_pct`, `low_margin_pct`, `expense_categories` |
| `gst` | GST on bills, GSTIN on the bill | off | `rate` (0-28 %), `gstin` |
| `discounts` | Rupee discount on bills | on | `max_discount_pct` (default 20) |
| `google_sheets` | Copy bills, items and expenses to a Google Sheet through an Apps Script web app | off | `web_app_url` (`https://script.google.com/macros/s/.../exec`), `secret` (secret, 16+ characters), `interval_minutes`, `last_sync` (read-only) |
| `whatsapp` | Phase 2 delivery orders | off | `business_number`, `delivery_buildings` (up to 50), `min_order` |

`shop.logo` must be a `data:image/...` URL or a path on this server (at most 200,000 characters);
`targets.expense_categories` holds up to 30 entries. Numbers can't be `Infinity` or `NaN`.

The first four are **core** modules and can't be switched off. A hidden `admin` module holds the
PIN; it never appears in these responses. **Secret** settings (the Google Sheet `secret`) are left
out of the public `GET /api/config`. **Read-only** settings (`last_sync`) are written by the server
and ignored if you send them.

### How sign-in works

1. `POST /api/admin/login` with the PIN gives a token, valid for 12 hours (the admin module's
   `session_hours`).
2. Send it as `Authorization: Bearer <token>` to every endpoint marked **Admin**.
3. The PIN is **1234** until the owner changes it. While it is, `must_change_pin` and the public
   `default_pin` are `true`, and the token works **only** for `POST /api/admin/pin`. Every other
   Admin endpoint answers 403 `Change the default PIN 1234 first (POST /api/admin/pin)`. The
   Admin page shows only the change-PIN card.
4. Changing the PIN signs everyone out: all earlier tokens stop working and the response carries a
   fresh token for whoever changed it.
5. Wrong PINs are throttled: after 5 from one device, sign-in from it is locked for 30 seconds,
   doubling with each further wrong PIN up to 15 minutes. 30 wrong PINs from anywhere within 10
   minutes lock sign-in for everyone. A locked attempt gets 429 with `Retry-After`. The counts are
   kept in memory and reset when the POS restarts.

A missing, wrong or expired token gives 401 `{"error": "Admin PIN required"}`.

To keep a token in `$T` for the examples on this page (after the PIN has been changed; use yours):

```bash
T=$(curl -s -X POST http://localhost:4000/api/admin/login -H 'Content-Type: application/json' \
  -d '{"pin": "4821"}' | jq -r .token)
```

### `GET /api/config`: settings for the POS screens

Open (no token). Every module except `admin`, with its on/off state and its settings minus secret
ones. The screens load this at start-up for the shop name, theme colours, payment methods, order
types, the GST line, the discount cap and the bill footer.

```bash
curl http://localhost:4000/api/config
```

```json
{
  "version": "0.2.0",
  "modules": {
    "shop": {
      "enabled": true,
      "settings": {
        "shop_name": "Waffle Bros", "shop_address": "Bhopal", "shop_phone": "",
        "receipt_footer": "Thank you! Come back for more waffles", "logo": null,
        "open_hour": 10, "close_hour": 23
      }
    },
    "theme": {"enabled": true, "settings": {"primary": "#F6B92B", "dark": "#4A2C1A", "accent": "#B97A10", "background": "#FFFDF6"}},
    "billing": {
      "enabled": true,
      "settings": {
        "payment_methods": ["upi", "cash", "card"], "default_payment": "upi",
        "order_types": ["dine-in", "takeaway", "delivery"],
        "customer_capture": true, "print_on_save": false
      }
    },
    "targets": {
      "enabled": true,
      "settings": {
        "default_target": 100000, "slow_mover_pct": 5, "low_margin_pct": 55,
        "expense_categories": ["rent", "salary", "ingredients", "electricity", "packaging", "marketing", "maintenance", "other"]
      }
    },
    "gst": {"enabled": false, "settings": {"rate": 5, "gstin": ""}},
    "discounts": {"enabled": true, "settings": {"max_discount_pct": 20}},
    "google_sheets": {"enabled": false, "settings": {"web_app_url": "", "interval_minutes": 5, "last_sync": ""}},
    "whatsapp": {"enabled": false, "settings": {"business_number": "", "delivery_buildings": [], "min_order": 0}}
  },
  "default_pin": true
}
```

### `POST /api/admin/login`: sign in with the PIN

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `pin` | string, 1-8 chars | yes | `"1234"` until changed. Anything that isn't 4 to 8 digits is simply a wrong PIN. |

```bash
curl -X POST http://localhost:4000/api/admin/login -H 'Content-Type: application/json' \
  -d '{"pin": "1234"}'
```

```json
{
  "token": "1795038617.7690661fdf4c75b84f507a5ef9ea20911812457918fb6fea00a74aeb2dcb2a79",
  "expires_at": 1795038617,
  "must_change_pin": true
}
```

`expires_at` is a Unix timestamp (seconds). With `must_change_pin: true` the token can only be used
for `POST /api/admin/pin`.

Errors: 401 `Wrong PIN`, 429 `Too many wrong PINs. Try again in 30 seconds.` (with `Retry-After`).

### `POST /api/admin/pin`: change the PIN (Admin, default PIN allowed)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `new_pin` | string | yes | 4 to 8 digits, not `1234`. |

Needs a valid token, and is the only Admin endpoint that also accepts a token from the default PIN
1234. Signs out every other admin session. Use the token in the response from now on.

```bash
curl -X POST http://localhost:4000/api/admin/pin -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"new_pin": "4821"}'
```

```json
{
  "token": "1795038617.64fffa7c7463398ed9301bb758067310b7857f003177339cbbb7adfac83aed2f",
  "expires_at": 1795038617,
  "must_change_pin": false
}
```

Errors: 400 `PIN must be 4 to 8 digits`, 400 `Choose a PIN other than the default 1234`, 401.

### `GET /api/admin/modules`: modules with their settings forms (Admin)

A list in display order (core modules first). Each entry:

| Key | Meaning |
| --- | --- |
| `key`, `name`, `description`, `icon` | Identity and text for the Admin page |
| `core` | `true` = can't be switched off |
| `enabled` | On or off |
| `settings_schema` | JSON Schema of the settings, generated from the module's Pydantic model. The Admin page draws its form from it (`title`, `description`, `default`, limits, enums, `format: "color"` / `"image"`, `readOnly`). |
| `values` | Current settings, **including** secret ones such as the Google Sheet `secret` |
| `readonly_fields` | Settings the server writes; shown but not editable |

```bash
curl http://localhost:4000/api/admin/modules -H "Authorization: Bearer $T"
```

```json
[
  {"key": "shop", "name": "Shop details", ...},
  ...,
  {
    "key": "google_sheets",
    "name": "Google Sheet sync",
    "description": "Copy bills, items and expenses to a Google Sheet.",
    "icon": "📊",
    "core": false,
    "enabled": false,
    "settings_schema": {
      "properties": {
        "web_app_url": {"default": "", "description": "From the sheet's Apps Script: Deploy -> Web app. Looks like https://script.google.com/macros/s/.../exec", "maxLength": 300, "title": "Web app URL", "type": "string"},
        "secret": {"default": "", "description": "Any long random text (16+ characters). Paste the same text into SECRET in the script.", "maxLength": 200, "title": "Secret", "type": "string"},
        "interval_minutes": {"default": 5, "maximum": 1440, "minimum": 1, "title": "Sync every (minutes)", "type": "integer"},
        "last_sync": {"default": "", "readOnly": true, "title": "Last synced", "type": "string"}
      },
      "title": "GoogleSheetsSettings",
      "type": "object"
    },
    "values": {"web_app_url": "", "secret": "", "interval_minutes": 5, "last_sync": ""},
    "readonly_fields": ["last_sync"]
  },
  ...
]
```

### `PUT /api/admin/modules/{key}`: switch a module or change its settings (Admin)

Both fields are optional. Only the settings keys you send change; the rest keep their values.
Read-only settings are ignored. Returns the module in the same shape as one entry of
`GET /api/admin/modules`. Changes apply to new bills straight away.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `enabled` | boolean | no | Switch the module on or off. |
| `settings` | object | no | Settings to change, e.g. `{"rate": 5}`. Checked against the module's schema. |

```bash
curl -X PUT http://localhost:4000/api/admin/modules/gst -H "Authorization: Bearer $T" \
  -H 'Content-Type: application/json' -d '{"enabled": true, "settings": {"rate": 5}}'
```

```json
{
  "key": "gst",
  "name": "GST",
  "description": "Add GST to bills and print the GSTIN.",
  "icon": "🧮",
  "core": false,
  "enabled": true,
  "settings_schema": {
    "properties": {
      "rate": {"default": 5, "maximum": 28, "minimum": 0, "title": "GST rate (%)", "type": "number"},
      "gstin": {"default": "", "maxLength": 15, "title": "GSTIN (printed on bills)", "type": "string"}
    },
    "title": "GstSettings",
    "type": "object"
  },
  "values": {"rate": 5.0, "gstin": ""},
  "readonly_fields": []
}
```

Errors:

| Status | Body | When |
| --- | --- | --- |
| 404 | `Unknown module 'foo'` | No module with that key |
| 400 | `Change the PIN with POST /api/admin/pin` | `key` is `admin` |
| 400 | `'Shop details' is a core module and can't be switched off` | `enabled: false` on a core module |
| 400 | `rate: Input should be less than or equal to 28` | A setting failed validation (`field: reason`) |
| 401 | `Admin PIN required` | No valid token |
| 403 | `Change the default PIN 1234 first (POST /api/admin/pin)` | The PIN is still 1234 |

### `GET /api/admin/google-sheet/script`: the Apps Script for the Google Sheet (Admin)

Returns the Google Apps Script (`src/waffle_pos/integrations/apps_script.gs`) as `text/plain`. It is
what the Admin page's **Setup script** button shows. Paste it into the spreadsheet
(**Extensions → Apps Script**), set its `SECRET` to the module's `secret`, then **Deploy → New
deployment → Web app** (Execute as: Me, Who has access: Anyone), and put the `/exec` URL into the
module's `web_app_url`.

```bash
curl http://localhost:4000/api/admin/google-sheet/script -H "Authorization: Bearer $T" > apps_script.gs
```

Errors: 401, 403.

## System

### `GET /api/health`: health check

Used by Docker. Answers when the app is up and the database responds.

```bash
curl http://localhost:4000/api/health
```

```json
{"status": "ok", "version": "0.2.0"}
```

### `POST /api/sync`: sync to the Google Sheet now (Admin)

Needs the admin token, and the `google_sheets` module switched on and set up (see
[`PUT /api/admin/modules/{key}`](#put-apiadminmoduleskey-switch-a-module-or-change-its-settings-admin)
and [`GET /api/admin/google-sheet/script`](#get-apiadmingoogle-sheetscript-the-apps-script-for-the-google-sheet-admin)).
Each sync is one HTTPS POST of the new rows and the summaries, with the secret, to the Apps Script
web app, which writes six tabs, creating any that are missing:

| Tab | How it's written | What's in it |
| --- | --- | --- |
| `Orders` | New rows appended | One row per bill: bill no, date, time, items, subtotal, discount, tax, total, payment, order type, source, status, customer, phone. A cancelled bill is appended again with status `cancelled`. |
| `OrderItems` | New rows appended | One row per bill line: bill no, date, time, item, category, price, qty, line total. |
| `Expenses` | New rows appended | Date, category, amount, recurring (Monthly / One-off), note. |
| `Daily` | Rewritten every sync | Last 90 days: date, revenue, orders, average bill, top item. |
| `Items` | Rewritten every sync | Every menu item: code, name, category, price, cost, margin %, and over the last 30 days qty, bills, revenue and share %; plus whether it's on the menu. |
| `Monthly` | Rewritten every sync | Last 12 months: target, revenue, orders, average bill, % of target, expenses, net profit. |

Up to 500 bills are pushed per run, so a long backlog catches up over a few runs. Any other tab
in the spreadsheet (for example an `Overview` tab with your own KPI formulas and charts) is never
touched. Text that starts with `=`, `+`, `-` or `@` is sent with a leading apostrophe so it can never
run as a formula (the script escapes it again). The same sync also runs in the background every
`interval_minutes`. Only one sync runs at a time: a second one answers `A sync is already running.
Try again in a moment.` Apart from 401/403, it always answers 200, so check the body:

| Field | Meaning |
| --- | --- |
| `ok` | `true` if the sync succeeded |
| `skipped` | `true` if the `google_sheets` module is switched off |
| `message` | What happened, e.g. `Synced 12 orders and 1 expenses.` or why it failed |
| `at` | Shop-local time of a successful sync, else `null` |

```bash
curl -X POST http://localhost:4000/api/sync -H "Authorization: Bearer $T"
```

```json
{"ok": false, "message": "Google Sheet sync is switched off in the admin dashboard.", "skipped": true, "at": null}
```

Switched on but without a web app URL or secret:

```json
{"ok": false, "message": "Add the web app URL and secret in Admin → Modules → Google Sheet sync.", "skipped": false, "at": null}
```

Other `message`s: `Wrong secret: it must match the POS admin page` (the script's `SECRET` differs),
`The web app didn't answer with JSON...` (wrong URL, or access not set to Anyone), `Could not reach
the Google Sheet web app: ...` (offline; rows wait for the next run).

### `GET /api/backup`: download a database backup (Admin)

A consistent copy of the live SQLite database (safe while billing), sent as
`waffle-bros-backup-YYYY-MM-DD.db`. To restore: stop the POS and put the file in place of
`waffle-bros.db` in the data folder (`WB_DATA_DIR`, default `data/`).

```bash
curl -OJ http://localhost:4000/api/backup -H "Authorization: Bearer $T"
# saves waffle-bros-backup-2026-11-18.db
```

### `POST /api/integrations/whatsapp`: WhatsApp webhook (planned)

Reserved for phase 2 (WhatsApp ordering; orders will arrive with `source: "whatsapp"`). Always
answers 501 `{"error": "WhatsApp ordering is planned for phase 2"}` for now.

## Recipes

Copy-paste one-liners. Set `B=http://localhost:4000` first. `jq` is used to pick values out of the
output; anything marked **Admin** needs the admin token in `$T` (first two recipes).

```bash
# First time only: sign in with the default PIN and change it (until then the token can do nothing else)
T=$(curl -sX POST $B/api/admin/login -H 'Content-Type: application/json' -d '{"pin":"1234"}' | jq -r .token)
T=$(curl -sX POST $B/api/admin/pin -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"new_pin":"4821"}' | jq -r .token)

# Every other time: sign in with your PIN and keep the admin token in $T
T=$(curl -sX POST $B/api/admin/login -H 'Content-Type: application/json' -d '{"pin":"4821"}' | jq -r .token)

# Bill an order: 2 x item 5 and 1 x item 16, paid by UPI, takeaway
curl -sX POST $B/api/orders -H 'Content-Type: application/json' -d '{"items":[{"item_id":5,"qty":2},{"item_id":16,"qty":1}],"payment_method":"upi","order_type":"takeaway"}'

# Cancel bill id 517
curl -sX POST $B/api/orders/517/cancel -H "Authorization: Bearer $T"

# Today's revenue, bill count and target progress
curl -s $B/api/dashboard | jq '.target | {todayRevenue, todayOrders, todayTarget, revenue, target, progressPct}'

# Today's cash-up by payment method
curl -s $B/api/day-end | jq '.payments'

# Add a monthly (recurring) expense: rent from 1 Dec
curl -sX POST $B/api/expenses -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"category":"rent","amount":25000,"date":"2026-12-01","recurring":true,"note":"Shop rent"}'

# Add a one-off expense dated today
curl -sX POST $B/api/expenses -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"category":"ingredients","amount":3200,"note":"Nutella, cream"}'

# Set this month's target to ₹1,20,000 (and make it the default)
curl -sX PUT $B/api/targets/$(date +%Y-%m) -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"amount":120000,"makeDefault":true}'

# Add a category, then a menu item in it (use the id the first call returns)
curl -sX POST $B/api/categories -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"name":"Shakes"}'
curl -sX POST $B/api/items -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"code":"SH01","name":"Oreo Shake","category_id":5,"price":149,"cost":45}'

# Change one item's price (PUT replaces the whole item, so start from the current one)
curl -s $B/api/menu | jq '.items[] | select(.code=="W05") | {code,name,category_id,price:209,cost,image,veg,active}' | curl -sX PUT $B/api/items/5 -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d @-

# Hide an item from billing (or delete it if it was never sold)
curl -sX DELETE $B/api/items/19 -H "Authorization: Bearer $T"

# Put the Combo category (id 3) first on the billing screen
curl -sX POST $B/api/categories/reorder -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"ids":[3]}'

# Charge 5% GST on new bills (send {"enabled":false} to turn it off)
curl -sX PUT $B/api/admin/modules/gst -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"enabled":true,"settings":{"rate":5}}'

# Allow discounts of up to 10% of the bill
curl -sX PUT $B/api/admin/modules/discounts -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"enabled":true,"settings":{"max_discount_pct":10}}'

# Which modules are on?
curl -s $B/api/config | jq '.modules | map_values(.enabled)'

# Get the Apps Script to paste into the Google Sheet (set its SECRET, deploy as a web app)
curl -s $B/api/admin/google-sheet/script -H "Authorization: Bearer $T" > apps_script.gs

# Set up Google Sheet sync with the web app URL and the same secret, and switch it on
curl -sX PUT $B/api/admin/modules/google_sheets -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d '{"enabled":true,"settings":{"web_app_url":"https://script.google.com/macros/s/<deployment-id>/exec","secret":"<16+ random characters>"}}'

# Trigger a Google Sheet sync now
curl -sX POST $B/api/sync -H "Authorization: Bearer $T"

# Export a backup of the database into the current folder
curl -sOJ $B/api/backup -H "Authorization: Bearer $T"

# Best sellers over the last 30 days
curl -s "$B/api/items/stats?period=30d" | jq '.topByRevenue[] | {name, qty, revenue}'
```

## Keeping this page right

After changing an endpoint: add `summary=` and a docstring to the route, run
`uv run python -m waffle_pos.openapi` to regenerate `docs/openapi.json` (CI fails via
`tests/test_openapi.py` if you forget), and update the matching section here.
