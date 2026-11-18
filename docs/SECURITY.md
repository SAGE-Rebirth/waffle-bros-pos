# Security

How the Waffle Bros POS protects the shop's money and data, what it deliberately leaves open, and
what the owner should do. This is for Abhinav and for future Claude sessions. The design behind it is
in [ARCHITECTURE.md](ARCHITECTURE.md#auth). Every endpoint's access level is in [API.md](API.md).

## Contents

1. [Threat model](#threat-model)
2. [Open vs PIN-protected](#open-vs-pin-protected)
3. [Controls](#controls)
4. [Google Sheet bridge](#google-sheet-bridge)
5. [Operational advice](#operational-advice)
6. [Review findings](#review-findings)

## Threat model

- **Where it runs.** The POS runs on one shop PC. It listens on port 4000 on every network
  interface, so tablets and phones on the shop Wi-Fi can use it. Data is one SQLite file on that PC
  (or in the Docker volume `pos-data`).
- **Who can reach it.** Anyone on the same Wi-Fi: the owner and staff, but also **customers**, if
  they share the Wi-Fi. A customer's phone, or a malicious web page opened on a shop tablet, must not
  be able to change prices, cancel paid bills, fake expenses, read settings or download the database.
- **What we protect.**
  - **Money:** prices, discounts, GST, cancelled bills (cash skimming), targets and expenses (the
    profit figures).
  - **Data:** customer names and phone numbers on bills, and the full database backup.
  - **Availability:** billing must keep working, even offline, and bad input must not break the
    dashboard.
  - **The owner's Google Sheet:** nothing typed at the counter should run as a formula there.
- **Out of scope.** Someone with physical access to the shop PC (they can copy the database file),
  a compromised Google account, and anything on the internet: the POS is **not** meant to be
  reachable from outside the shop network.
- **Trusted on the LAN.** There is no HTTPS. The PIN and admin token travel in clear text on the shop
  Wi-Fi. That is acceptable only on a network the shop controls, which is why customers belong on a
  separate guest Wi-Fi (see [Operational advice](#operational-advice)).

## Open vs PIN-protected

The counter must keep billing without anyone typing a PIN. Everything else that changes money or
exposes data needs the owner's PIN.

| Open (no PIN) | Why |
| --- | --- |
| `GET /api/menu` | The billing screen needs it. |
| `POST /api/orders`, `GET /api/orders`, `GET /api/orders/{id}` | Billing and reprinting at the counter. Prices always come from the server's menu, so a client can't set its own. |
| `GET /api/dashboard`, `GET /api/items/stats`, `GET /api/day-end`, `GET /api/expenses` | Reading the numbers is part of running the shop. |
| `GET /api/config` | The screens load the theme and billing options from it. Secret settings are left out. |
| `POST /api/admin/login` | Throttled (see below). |
| `GET /api/health` | Docker's health check. |
| `POST /api/integrations/whatsapp` | Always answers 501 (planned for phase 2). |
| `/docs`, `/redoc`, `/openapi.json` | Accepted: a read-only description of the API. It is useful for scripts and Claude, and the open endpoints are open anyway. |

| PIN-protected (Admin) | Why |
| --- | --- |
| Category and item writes and reorders | Prices and the menu. |
| `POST /api/orders/{id}/cancel` | A paid bill can't be quietly cancelled after the cash is in the drawer. |
| `PUT /api/targets/{month}`, `POST /api/expenses`, `DELETE /api/expenses/{id}` | These drive the profit and target figures. `makeDefault` also writes a module setting. |
| `POST /api/sync` | Each call triggers outbound traffic and could duplicate rows. Only the Admin page uses it. |
| `GET /api/backup` | The whole database: customer phones, the PIN hash and the token secret. |
| `GET /api/admin/modules`, `PUT /api/admin/modules/{key}`, `GET /api/admin/google-sheet/script` | Settings, including the Sheet secret. |
| `POST /api/admin/pin` | Needs a signed-in token. This is the only route a default-PIN token can use. |

The counter screens ask for the PIN when they need it. Cancelling a bill on Day End, and changing
the target or adding or deleting an expense on the Dashboard, open a PIN prompt
(`frontend/src/components/PinPrompt.jsx`). Once it is entered, the call is retried with the new
token (`pinApi` / `requirePin` in `frontend/src/api.js`). The token is then kept for the session,
like an Admin sign-in.

## Controls

### PIN and tokens (`services/auth.py`, `api/deps.py`)

- **PIN storage:** scrypt (`n=2**14, r=8, p=1`) with a random 16-byte salt. A PIN is 4 to 8 ASCII
  digits and can't be `1234`. Anything else is rejected before scrypt runs.
- **Tokens:** `<expiry>.<HMAC-SHA256(token_secret, expiry)>`, valid for `session_hours` (default
  12). They are checked with `hmac.compare_digest`. Tokens over 100 characters or with non-ASCII
  characters are refused up front, so bad input gives a 401, never a 500.
- **Changing the PIN signs everyone out.** `set_pin` rotates `token_secret`, so every earlier token
  stops working. This is also the only way to revoke tokens (there is no per-token logout).
- **Default PIN lockdown.** `1234` is the same on every install, so a token from the default PIN can
  only call `POST /api/admin/pin` (`require_signed_in`). Every other admin route (`require_admin`)
  answers **403** `Change the default PIN 1234 first (POST /api/admin/pin)` until the PIN is
  changed. The Admin page shows only the change-PIN card until then.
- **Errors:** 401 `Admin PIN required` when the token is missing, wrong or expired.

### Sign-in throttle (`services/auth.LoginThrottle`)

A 4-digit PIN has only 10,000 values, so guessing must be slow:

- **Per device (client IP):** 5 wrong PINs are free. After that, sign-in from that device is locked
  for 30 seconds, doubling with every further wrong PIN (60 s, 120 s, ...) up to 15 minutes. The
  answer is **429** `Too many wrong PINs. Try again in N seconds.` with a `Retry-After` header. A
  correct PIN clears that device's count.
- **Everyone:** 30 wrong PINs from anywhere within 10 minutes locks sign-in for everyone until the
  oldest of them is 10 minutes old, so changing IP address doesn't help.
- It is kept **in memory**: a restart resets it. Memory is bounded (the oldest devices are forgotten
  beyond 1,000).

At these rates, trying all 10,000 four-digit PINs takes days instead of minutes. A 6-digit PIN
makes it far longer still.

### Input limits (`schemas.py`, `modules/builtin.py`)

- Request bodies inherit from `schemas.In`, which sets `allow_inf_nan=False`, so `Infinity` and
  `NaN` are refused. Module settings do the same (`ModuleSettings`).
- **Money:** prices, costs, discounts and expenses are at most `MAX_MONEY` = ₹1,00,00,000 (₹1
  crore). A monthly target is at most ₹10,00,00,000 (₹10 crore). One huge expense can therefore no
  longer break the dashboard.
- **Bills:** at most 100 lines (qty 1 to 999 each). Notes on bills and expenses are at most 300
  characters. Hidden items can't be billed.
- **Images:** an item `image` or the shop `logo` must be a `data:image/(png|jpeg|webp|gif);base64,...`
  URL or a path on this server, and at most 200,000 characters. External URLs are refused, so the
  screens never load anything from the internet (no tracking, works offline).
- **Lists:** up to 30 expense categories, 50 delivery buildings, and 1,000 ids in a reorder.
- **Request body:** over `WB_MAX_BODY_BYTES` (default 1,000,000 bytes) gives **413** `The request is
  too large`, checked against `Content-Length` and while the body streams in.
- **Ids:** an id too big for SQLite raises `OverflowError`, which is answered as 404 `Not found`.

### Middlewares (`security.py`, added in `app.create_app`)

- **`HostCheck`: DNS rebinding.** A web page from the internet could otherwise point its own domain
  name at the POS's LAN address and use it from a shop browser as if it were the same site. The
  `Host` header must be an IP address, a single-word name (`localhost`, `shop-pc`), a `*.local` name,
  or one of `WB_ALLOWED_HOSTS` (comma-separated, e.g. `pos.waffle-bros.in`). Anything else gets
  **400** `This address isn't allowed...`.
- **`BodyLimit`:** the 413 described above.
- **`SecurityHeaders`:** on every response, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY` (no clickjacking of the PIN pad), `Referrer-Policy: no-referrer`,
  `Permissions-Policy` (no camera, microphone or location) and a `Content-Security-Policy`. The
  screens get `default-src 'self'`, images from `self`, `data:` and `blob:`, scripts only from
  `self`, inline styles allowed, and `frame-ancestors 'none'`. `/docs` and `/redoc` get a looser
  policy that allows the Swagger UI files from `cdn.jsdelivr.net`. `/api/*` responses also carry
  `Cache-Control: no-store`.
- **Other guards:**
  - Unknown `/api/*` paths answer a JSON 404, even with the screens built, instead of falling
    through to the app page.
  - Static files are served only from inside `frontend/dist`.
  - There is no CORS middleware, so other sites can't send JSON requests to the API.
  - All SQL goes through SQLAlchemy expressions.
  - React escapes every text field (there is no `innerHTML`).
  - Errors are `{"error": "..."}` without tracebacks.

### Docker (`compose.yaml`, `Dockerfile`)

- Runs as the non-root user `pos`, with `read_only: true` (only `/tmp` is a tmpfs, for backups in
  progress), `cap_drop: [ALL]` and `no-new-privileges:true`.
- Data is in the named volume `pos-data`. The image contains no secrets.
- Port `4000:4000` is published on all interfaces so tablets can connect. Docker's port rules bypass
  the host firewall (ufw, Windows Firewall), so don't rely on the firewall to hide it. To keep the
  POS on the PC only, use `"127.0.0.1:4000:4000"`.

## Google Sheet bridge

The sync sends data **out** to an Apps Script web app inside the owner's Google Sheet
(`integrations/sheets.py`, `integrations/apps_script.gs`).

- **Shared secret.** The module's `secret` (at least 16 characters; **New secret** in Admin makes
  36 random hex characters) is sent in the POST body, never in the URL. The script refuses requests
  until its own `SECRET` is set (not the placeholder, at least 16 characters), and compares secrets
  in constant time. The secret is a secret field: it never appears in `GET /api/config`.
- **"Anyone" access.** The web app is deployed with *Who has access: Anyone* so the POS needs no
  Google sign-in. Anyone who has the URL can call it, but without the secret it only answers
  `Wrong secret`. The script runs as the owner but touches only the active spreadsheet.
- **Allow-listed tabs.** The script writes only `Orders`, `OrderItems`, `Expenses`, `Daily`, `Items`
  and `Monthly`, with at most 5,000 rows per tab per request, under a script lock. Other tabs are
  never touched.
- **Formula escaping, twice.** Text that starts with `=`, `+`, `-` or `@` (and isn't a number) gets a
  leading apostrophe, so a customer name like `=IMPORTDATA("https://...")` stays plain text. The POS
  does this before sending (`sheets._cell`), and the script does it again (`clean_`), so an old copy
  of either side is still safe.
- **URL check.** The POS only posts to `https://script.google.com/macros/s/<id>/exec`.
- **Admin-only, one at a time.** `POST /api/sync` needs the PIN. If a sync is already running (the
  background loop or a second click), another one answers "A sync is already running", so rows aren't
  sent twice.
- **If the secret leaks:** press **New secret** in Admin, put the same value into `SECRET` in the
  script, and deploy a new version.

## Operational advice

For the owner, in order of importance:

1. **Change the PIN on day one.** The admin dashboard stays locked until you do. Use 6 to 8 digits,
   not a birthday or `0000`.
2. **Never port-forward 4000** on the router, and don't put the POS on the internet. It is built for
   the shop network only.
3. **Give customers a separate guest Wi-Fi.** Most routers have a "Guest network" switch that keeps
   guests away from the shop's devices. Put the shop PC and tablets on the main network.
4. **Keep backups private.** A backup (**Admin → Backup**, `make backup`) is the whole database. It
   includes customer phone numbers, the PIN hash and the token secret. Someone holding it can try PINs
   offline, or sign admin tokens directly. Store backups like cash. If one is lost, change the PIN at
   once: that also replaces the token secret.
5. **Sign out on shared tablets.** Sign-in lasts 12 hours on that device (the token is forgotten
   when the browser closes). Changing the PIN signs out every device.
6. **Forgot the PIN?** On the shop PC, stop the POS and run `make pin-reset`. That deletes the
   `module:admin` row, so the PIN is `1234` again and every session is signed out. Then sign in and
   choose a new PIN. In Docker:

   ```bash
   docker compose exec pos python -c "import sqlite3; c = sqlite3.connect('/data/waffle-bros.db'); c.execute(\"DELETE FROM settings WHERE key = 'module:admin'\"); c.commit()"
   ```

   Only someone with access to the PC (or the Docker host) can do this, which is the point.
7. **Open the POS by IP address or the PC's name.** If you give it a domain name, add it to
   `WB_ALLOWED_HOSTS`, or the Host check will refuse it.

## Review findings

From the security review of 2026-11-18 (`/tmp/claude-0/security-review.md`, not in the repo).

| ID | Severity | Finding | Status |
| --- | --- | --- | --- |
| F1 | High | No rate limit on PIN sign-in; a 4-digit PIN could be brute-forced in minutes, and scrypt floods could exhaust CPU and RAM | **Fixed:** `LoginThrottle` (5 tries, then 30 s doubling to 15 min, per device; 30 in 10 min for everyone; 429 + `Retry-After`). Malformed PINs are rejected before scrypt. The minimum length stays 4 digits; the throttle is kept in memory and resets on restart. |
| F2 | High | Default PIN `1234` gave full admin, and only the UI pushed for a change | **Fixed:** a default-PIN token can only call `POST /api/admin/pin`; everything else is 403. `GET /api/config` still reports `default_pin`, which only says that admin is locked. |
| F3 | Medium | Anyone on the Wi-Fi could cancel paid bills, add or delete expenses and set targets (including the default target) | **Fixed:** all four are admin-only; the screens prompt for the PIN. Cancels and deletes still leave no audit trail (who and when). |
| F4 | Medium | One `1e308` or `Infinity` expense or target broke the dashboard with 500s | **Fixed:** `allow_inf_nan=False` and caps (₹1 crore money, ₹10 crore target). |
| F5 | Medium | Formula injection into the Google Sheet | **Fixed:** the POS escapes `= + - @` before sending, and the Apps Script escapes again. |
| F6 | Medium | DNS rebinding: any `Host` accepted | **Fixed:** `HostCheck` middleware and `WB_ALLOWED_HOSTS`. |
| F7 | Medium | No size limits (notes, bill lines, images, logo in `/api/config`, list settings, body size) | **Fixed:** 300-character notes, 100 lines, 200,000-character images, list caps, 1 MB body limit (413). |
| F8 | Low | `POST /api/sync` open; concurrent syncs duplicated rows | **Fixed:** admin-only and one sync at a time. |
| F9 | Low | Service-account `credentials_path` file oracle and SSRF via `token_uri` | **Fixed:** that code was removed; the Apps Script URL must be `https://script.google.com/macros/s/.../exec`. |
| F10 | Low | 500s on a non-ASCII PIN or token, a 5,000-digit token, or ids ≥ 2^63 | **Fixed:** PIN and token shape checks; `OverflowError` → 404; money caps. |
| F11 | Low | No security headers; admin page could be framed | **Fixed:** `SecurityHeaders` (CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `no-store` on `/api`). |
| F12 | Low | Tokens can't be revoked one at a time; no server-side logout | **Accepted:** changing the PIN signs everyone out; sessions last 12 hours by default. |
| F13 | Info | `/docs`, `/redoc`, `/openapi.json` open on the LAN; Swagger UI loads from a CDN | **Accepted:** read-only schema, useful for Claude and scripts. The CDN is limited by the `/docs` CSP. |
| F14 | Info | Admin could set an external image or logo URL (tracking, breaks offline) | **Fixed:** only `data:image/...` or same-server paths. |
| F15 | Info | Docker: port on all interfaces (bypasses ufw); no read-only / cap-drop; images pinned by tag | **Port binding accepted** (documented: never port-forward, `127.0.0.1:4000:4000` to keep it local). **Hardening fixed:** `read_only`, `cap_drop: [ALL]`, `no-new-privileges`. **Open:** base images are pinned by tag, not digest. |
| F16 | Info | CI actions pinned to major tags, not SHAs; npm audit highs in dev-only build deps | **Accepted:** CI has read-only permissions and no secrets; the npm issues are in vite's build tooling and nothing from them ships in `dist`. Upgrade vite when a fix is out. |
| F17 | Info | Backups hold the PIN hash and token secret | **Accepted:** documented above (keep backups private; change the PIN if one is lost). |
| F18 | Low | The 429 from sign-in lost its `Retry-After` header (the error handler dropped headers) | **Fixed:** the handler passes `exc.headers` through. |
| F19 | Low | An oversized chunked body got 400 instead of 413 | **Fixed:** `BodyLimit` reads the body up to the limit first and answers 413. |
| F20 | Low | Protocol-relative image URLs (`//host/x.png`) passed as same-server paths | **Fixed:** a leading `//` is refused. |
| F21 | Info | Errors from `HostCheck`/`BodyLimit` went out without the security headers | **Fixed:** `SecurityHeaders` is now the outermost middleware. |
