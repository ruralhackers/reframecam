# ReFrame

A community repeat-photography project, built by [Rural Hackers](https://ruralhackers.com)

Visitors take a photo from a fixed, 3D-printed phone holder, and upload to [ReFrame](https://reframecam.org) or a self-hosted version forked from this repo. Over time those photos build into a
timelapse of a landscape slowly changing.

## Stack

- **FastAPI** + **Jinja2** — server-rendered, one template per page.
- **Vanilla JS, plain CSS.** No bundler, no framework.
- **Self-hosted fonts** (Anton, Be Vietnam Pro, Permanent Marker, JetBrains
  Mono — Latin subset, woff2) and a self-hosted **Leaflet** for the
  `/locations` map.
- **SQLite** + the local filesystem, behind a storage abstraction.
- **Pillow** + **pillow-heif** + **OpenCV** for the upload pipeline.

Dependencies are pinned in `pyproject.toml`. The project uses
[`uv`](https://docs.astral.sh/uv/) for environment management.

## Quick start

Requires **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/).

1. Copy `.env.example` to `.env`, no need to fill in any variables yet for a quickstart.
2. Run the following commands in the terminal:

```bash
uv sync
uv run python -m app.db init      # create the SQLite schema
uv run python -m app.seed         # load locations + stations from data/stations.toml
uv run uvicorn app.main:app --reload --host 0.0.0.0
```

3. Open `http://localhost:8000/` to see the user-facing frontend.

**Note**:

- `python -m app.seed` is idempotent — re-run it after editing `data/stations.toml`.
- `.env` at the repo root is
  auto-loaded by `app/config.py` (via `python-dotenv`); shell env vars still
  override it.

The app binds `0.0.0.0` so a phone on the same Wi-Fi can reach it via the
laptop's LAN IP — the realistic way to test the QR upload flow on a device:

1. Get the laptop's IP
2. Then run on the phone `http://<ip>:8000/`

To run the whole thing behind Caddy (automatic HTTPS) instead, jump to
[Deployment](#deployment).

## Configuration

Two layers.

**`data/site.toml`** — the fork's branding + i18n manifest: site name, footer
attribution, and enabled languages. Checked in for the Anceu build, edited per
fork, loaded once at startup (restart to pick up changes). It holds **no
secrets** and **no operational settings** — those are environment variables (below).

| Section         | Key             | Purpose                                                                                                                                                 |
| --------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[site]`        | `name`          | Project name — header wordmark and page titles.                                                                                                         |
| `[site.footer]` | `attribution_*` | Footer attribution line, per language.                                                                                                                  |
| `[languages]`   | `enabled`       | Offered languages; **the first is the default** (bare `/` redirects to it). Drop `"es"` for an English-only fork — the language toggle then disappears. |

**Environment variables** — deployment-specific and secret-bearing. All are
read once at process boot; restart to apply changes.

| Var                         | Default       | Notes                                                                                   |
| --------------------------- | ------------- | --------------------------------------------------------------------------------------- |
| `DATA_ROOT`                 | `<repo>/data` | Where SQLite, photos, and `site.toml` live.                                             |
| `STORAGE_BACKEND`           | `local`       | Storage abstraction key. Only `local` ships today.                                      |
| `ADMIN_SLUG`                | _(unset)_     | Non-guessable URL segment for the admin page. Empty → admin 404s.                       |
| `ADMIN_PASSWORD`            | _(unset)_     | Single shared admin password. Empty → admin 404s.                                       |
| `MIN_RESOLUTION_LONG_EDGE`  | `800`         | Reject uploads whose long edge is below this many pixels.                               |
| `BLUR_LAPLACIAN_THRESHOLD`  | `100`         | Reject uploads whose Laplacian variance is below this.                                  |
| `FEATURE_MATCH_MIN_MATCHES` | `8`           | Minimum ORB matches against the active reference set.                                   |
| `BORDERLINE_LOG_PATH`       | _(stdout)_    | Path to the borderline-match log file.                                                  |
| `SUBMISSIONS_ENABLED`       | `false`       | Toggles the `/host` community submission form. `false` → `/host` 404s and its nav link + homepage setup section are hidden. |
| `NEARBY_RADIUS_KM`          | `50`          | Radius for the "Nearby stations" section on each station page.                          |
| `RATE_LIMIT_ENABLED`        | `true`        | Per-IP rate limiting on admin auth, uploads, and the `/host` form. Set `false` if a smarter limiter sits at the proxy/WAF layer (and for multi-worker deployments — the in-process limiter isn't shared across workers). |
| `SMTP_HOST`                 | _(unset)_     | Outgoing mail host. Powers **both** the `/host` submission form and the admin-toggled per-upload notification email. Unset → both silently no-op (the `/host` form still works, it just emails nothing). |
| `SMTP_PORT`                 | `587`         | SMTP port.                                                                              |
| `SMTP_USERNAME`             | _(unset)_     | SMTP auth username. If empty, no login is attempted.                                    |
| `SMTP_USE_TLS`              | `true`        | STARTTLS on the connection (`true`/`false`).                                            |
| `SMTP_FROM_ADDRESS`         | _(unset)_     | `From` header; falls back to `SMTP_USERNAME` if unset.                                  |
| `SMTP_RECIPIENT`            | _(unset)_     | Where submission + upload-notification emails are sent. Required (with `SMTP_HOST`) for any mail to fire. |
| `SMTP_PASSWORD`             | _(unset)_     | SMTP auth password.                                                                     |

Every var falls back to the default shown when unset or empty, so a copied
`.env.example` boots as-is. That file ships `SUBMISSIONS_ENABLED=true` (the form
on, for the default build); the code default when the var is absent is `false`.
One more var, `DOMAIN`, appears in `.env.example` but not above: it's read only
by `docker-compose.yml` / Caddy, not the app — see [Docker](#docker).

## Forking / re-theming

ReFrame is built so another community can rebrand by editing config, assets,
and a small amount of copy — the layout and component code stay untouched. Most
of a rebrand is swapping static files; the rest is a handful of clearly-marked
edits in `app/`. The touchpoints:

**Config + assets (static files):**

1. **`data/site.toml`** — project name, footer attribution, and enabled
   languages (see the table above).
2. **`static/css/tokens.css`** — the colour and spacing tokens (edit the values
   at the top of the file). **Note:** a brand colour lives in _three_ places
   that must be kept in sync by hand — `tokens.css`, the critical above-the-fold
   subset inlined in `templates/base.html`, and the hardcoded
   `<meta name="theme-color" content="#163528">` tag near the top of
   `templates/base.html` (it sets the mobile browser-chrome colour and is not
   derived from the token). Miss one and the first paint or browser chrome
   flashes the old value.
3. **`static/branding/`** — favicon set (`favicon.svg`, `favicon-32.png`,
   `apple-touch-icon.png`, `favicon.ico`) and the default share image
   (`og-default.jpg`). Replace these files in place.
4. **`templates/partials/logo.html`** — the inlined SVG logo used in the nav
   and hero. It inherits colour via `currentColor`, so a re-brand is a single
   file swap. `static/img/logo.svg` is the canonical on-disk copy.
5. **`static/img/`** — homepage hero video and imagery (`hero-video.mp4`,
   `hero-poster.jpg`, `shared-roots.jpg`, `project.jpg`,
   `community-background.jpg`). Swap those for your own, keeping the filenames
   (or edit the paths in `templates/landing.html`).

**Copy + config in `app/` (Python — small, but you do edit these):**

6. **`app/strings.py`** — the site's narrative copy and brand references. The
   default build hardcodes Anceu/Galicia/Rural Hackers throughout the homepage
   (e.g. the `"EST. GALICIA 2024"` hero badge, the about/intro paragraphs, the
   `"— T.S. Eliot"` quote attribution, and the location headings). These are not
   in `site.toml` — a fork edits them here. (Per-_station_ story copy and place
   names live in `data/stations.toml`, not here — see
   [Stations: seed vs. admin](#stations-seed-vs-admin).)
7. **`HOMEPAGE_FEATURED_SLUGS` in `app/views.py`** — the homepage's featured
   location cards are an editorial list of station slugs
   (`casa-do-pobo`, `ies-ponte-caldelas`, …). A fresh fork's stations won't
   match the default slugs, so **set these to your own or the homepage locations
   section renders empty.**

What is _not_ meant to be re-themed: the layout structure, the type pairing,
the component primitives, and the bold-caps-over-photo gesture. A fork can rip
those out — the code is MIT — but it is then on its own.

## Stations: seed vs. admin

`data/stations.toml` is a bootstrap / fork convenience — a quick way to
populate a fresh database with locations and stations. Each `[[stations]]`
entry carries a slug, its location, bilingual name + story, optional
coordinates, and a status (`draft` / `active` / `archived`). Once a deployment
is live, locations and stations are managed entirely through the **admin UI**
(create, edit, photo upload, archive); the TOML is just the starting point.

**Through the admin UI**, a station can't be flipped to `active` until it has at
least one photo: `admin_station_update` clamps an under-prepared station back to
`draft`, and removing a station's last photo demotes it to draft too. The admin
uploads that first ("seed") photo through the admin photo form — it runs the full
validator but skips the feature-match step, so it bootstraps a station that has
no reference photos yet. Until a seed photo is in place the validator fail-closes:
community uploads return `doesnt_match`.

The **seed loader does not apply that gate** — it writes whatever `status` each
`[[stations]]` entry declares straight to the database. The default
`data/stations.toml` ships all three stations as `active`, so a fresh
`python -m app.seed` yields active stations that have no photos yet. They appear
in listings and on the homepage, but as **image-less cards** (there are no
per-station placeholder image files), and each links to a station page showing
the built-in cold-start empty state — until a seed photo is uploaded. A fork that
prefers the admin-UI model can instead seed its stations as `draft` and activate
them from the admin once a seed photo is in place.

## Admin

A Spanish-only management surface lives at `/admin/{ADMIN_SLUG}/`. Both
`ADMIN_SLUG` and `ADMIN_PASSWORD` must be set for the route to exist; if
either is empty, every admin route returns 404.

The **slug** is a non-guessable URL segment that doubles as a secret — a wrong
slug returns 404 rather than an auth prompt, so the page can't be found by
guessing. Generate a random one and add it to `.env`:

```bash
python -c 'import secrets; print("ADMIN_SLUG=" + secrets.token_hex(8))' >> .env
```

The **password** is checked on every admin visit. Use a strong value — a long
passphrase you'll remember, or a random one from a password manager — and add it
to `.env`:

```
ADMIN_PASSWORD=...
```

Then visit `http://localhost:8000/admin/{slug}/` — it's HTTP Basic auth; the
username is ignored (single shared password).

The admin **Ajustes** (Settings) page carries a runtime toggle for **per-upload
notification emails**: when on, each accepted community upload sends the operator
a moderation email (photo thumbnail + station + capture date) to `SMTP_RECIPIENT`.
It's off by default and needs the `SMTP_*` vars configured to actually send.

## Tests

```bash
uv run pytest
```

## Project layout

```
app/                 FastAPI app
  main.py              routes, template setup, lifespan, error handlers, access log
  config.py            env-var Settings + site.toml SiteConfig
  strings.py           UI strings + t() helper
  db.py                SQLite schema + connection helper (CLI: python -m app.db init)
  seed.py              location + station seed loader (CLI: python -m app.seed)
  storage.py           photo storage (local backend) — viewer + thumb derivatives
  photos.py            photo query helpers
  validation.py        upload pipeline: HEIC, EXIF, OpenCV checks, derivatives
  views.py             view-model builders + per-page meta / OG context
  email.py             SMTP send for the community submission form
  countries.py         ISO country codes + admin-dropdown helpers
  settings_store.py    persistent key/value settings (admin-toggleable)
templates/           Jinja templates
  base.html            chrome shell (critical CSS, meta / OG / favicon) all pages extend
                       page templates: landing, station, locations, host,
                       error, partials/, admin/
static/css/          tokens.css (design tokens) + app.css
static/branding/     favicon set + default OG image — a fork's swap point
static/vendor/       self-hosted third-party assets (Leaflet)
static/js/           vanilla JS (nav, home, reveal, viewer, upload, host, locations-map, admin)
static/fonts/        self-hosted woff2 fonts
static/img/          hero video + homepage imagery — fork swap assets
data/                runtime data
  site.toml            branding / languages (committed; no secrets or operational settings)
  stations.toml        editable location + station seed copy (committed)
  photos/<slug>/       uploaded photos: viewer/ + thumb/ derivatives (git-ignored)
  reframe.db           SQLite database (git-ignored)
tests/               pytest suite + fixtures
Dockerfile           uv-based image running uvicorn
docker-compose.yml   app + Caddy
Caddyfile            reverse proxy with automatic HTTPS
CLAUDE.md            working reference (repo overview + conventions)
```

---

## Deployment

The operational runbook for the deploying party. Deployment is via the bundled
Docker + Caddy stack: `docker compose up --build -d` builds the app image and
runs it behind Caddy, which terminates TLS and renews certificates
automatically. You need shell access to the host and a domain pointed at it.
(For local development without Docker, see [Quick start](#quick-start).)

### Prerequisites

- **Docker** and **Docker Compose** on the host.
- A **domain** pointed at the host — Caddy obtains a real Let's Encrypt
  certificate for it. Optional for a local run (defaults to `localhost` with a
  self-signed cert). The app binds plain HTTP inside the compose network and
  trusts Caddy for TLS and `X-Forwarded-*` headers.
- **Ports 80 and 443 reachable from the internet** and **DNS already resolving
  to the host** — both are preconditions for Caddy's certificate issuance, not
  optional niceties: the ACME challenge runs over port 80 against the resolved
  domain. Open 80/443 wherever your host filters traffic — a cloud provider's
  network firewall (if one is attached) *and* a host firewall (`ufw` or similar)
  if one is enabled.
- Disk space for the `reframe-data` named volume (DB + photos + config). The
  on-disk footprint is small — well under 1 GB for the Anceu build.

### Docker

The repo ships a `Dockerfile` (uv-based, runs uvicorn), a `docker-compose.yml`
(the app plus **Caddy**, which terminates TLS and renews certificates
automatically), a `Caddyfile`, and `docker-entrypoint.sh`.

Copy `.env.example` to `.env` next to `docker-compose.yml` (keep `.env` off
version control — it holds secrets):

```bash
cp .env.example .env
```

Every var is documented inline and ships a sensible default, so a copied file
boots as-is. For a real deploy, fill in:

- `DOMAIN` — your real domain (Caddy gets a Let's Encrypt cert for it); leave
  blank for a local run (defaults to `localhost` with a self-signed cert).
- `ADMIN_SLUG` / `ADMIN_PASSWORD` — the admin UI 404s until both are set (see
  [Admin](#admin)).
- `SUBMISSIONS_ENABLED` — already `true` in the example; the `/host` form toggle.
- `SMTP_HOST` / `SMTP_RECIPIENT` / `SMTP_PASSWORD` (and the other `SMTP_*`) —
  only if you want outgoing email: the `/host` submission form and/or the
  admin-toggled per-upload notification (see [Admin](#admin)).

Under Docker, the `DATA_ROOT` and `STORAGE_BACKEND` lines in `.env` are ignored:
compose mounts the `reframe-data` volume at `/data` and sets `DATA_ROOT` itself.

Then:

```bash
docker compose up --build -d
```

Caddy serves `:80` / `:443`; the app is internal to the compose network. With a
real `DOMAIN` pointed at the host, Caddy obtains a Let's Encrypt certificate on
first boot. With the default `localhost` it serves a self-signed certificate —
enough to smoke-test on a laptop.

**Data and first run.** `DATA_ROOT` is a named volume, `reframe-data`, mounted
at `/data`. On first boot `docker-entrypoint.sh` seeds the empty volume from the
image's committed defaults (`site.toml`, `stations.toml`), applies the schema,
and runs the seed loader — all idempotent, so it re-runs harmlessly on every
restart. To edit config after first boot, write into the volume (inspect its
host path with `docker volume inspect reframe-data`, or
`docker compose run --rm --entrypoint sh app` and edit `/data/site.toml` etc.), then
`docker compose restart app`.

**Backups.** Back up the `reframe-data` volume — it holds the DB, photos, and
config. The `caddy-data` volume holds issued certificates; losing it just means
Caddy re-issues them.

### Going live: post-compose checklist

`docker compose up` builds and starts the stack, but a handful of steps no
command performs stand between that and a site visitors can actually use. After
the containers are up:

1. **Confirm TLS issued.** `docker compose logs caddy` and look for a successful
   certificate obtain (no ACME errors), then load `https://<your-domain>/` from
   *outside* the host and confirm a real (not self-signed) certificate. A failure
   here is almost always DNS not yet resolving to the host or port 80 blocked —
   see [Prerequisites](#prerequisites).
2. **Confirm the admin works** at `https://<your-domain>/admin/{ADMIN_SLUG}/`
   (HTTP Basic; the username is ignored, the password is the gate — see
   [Admin](#admin)).
3. **Apply any fork/branding edits _before_ building.** For a rebrand, the copy
   and assets live *in the image*, not just config — `app/strings.py`,
   `HOMEPAGE_FEATURED_SLUGS` in `app/views.py`, the tokens, and `static/` assets
   (see [Forking / re-theming](#forking--re-theming)). The two config files
   (`site.toml`, `stations.toml`) are seeded into the volume on first boot; to
   change them *afterwards* you edit them in the volume and
   `docker compose restart app` (see **Data and first run** above).
4. **Upload a seed photo per station.** The seeded stations are `active` but
   photo-less, so they render as image-less cards *and community uploads fail
   closed* (`doesnt_match`) until each station has its first photo, uploaded
   through the admin photo form (see [Stations: seed vs. admin](#stations-seed-vs-admin)).
   This is what makes the site genuinely usable.
5. **Generate and print the QR signage** using the real domain (see
   [QR signage](#qr-signage)). Slugs bake into the printed codes and are
   read-only after creation, so lock them in before printing.
6. **Put backups on a schedule.** Everything that matters is in the
   `reframe-data` volume (see **Backups** above). A cron'd dump to offsite
   storage, e.g.:

   ```bash
   docker run --rm -v reframe-data:/data -v "$PWD":/backup alpine \
     tar czf "/backup/reframe-$(date +%F).tar.gz" /data
   ```

   and/or your provider's volume/server snapshots.
7. **Ensure the stack survives reboots.** The services use
   `restart: unless-stopped`, which only helps if Docker itself starts on boot:
   `sudo systemctl enable docker`.

**Ongoing.** Redeploy after a code or config change with
`git pull && docker compose up --build -d`. Watch the stack with
`docker compose logs -f` (see [Logs to watch](#logs-to-watch)).

### Where files live on disk

Relative to `DATA_ROOT`:

```
site.toml                      Per-deployment config (branding, languages; no secrets).
stations.toml                  Editable seed config.
reframe.db                     SQLite database (KB → low MB).
photos/<slug>/viewer/*.jpg     1200px-long-edge derivatives (~150 KB).
photos/<slug>/thumb/*.jpg      400px-long-edge derivatives (~30 KB).
```

Two derivatives are written per accepted photo — viewer + thumbnail, ~180 KB
total. The client-compressed original is never persisted to disk. Backing up
`DATA_ROOT` backs up everything.

### Threshold tuning (after launch)

The validator ships with first-guess defaults — `MIN_RESOLUTION_LONG_EDGE` 800,
`BLUR_LAPLACIAN_THRESHOLD` 100, `FEATURE_MATCH_MIN_MATCHES` 8. Plan to retune
the feature-match threshold in the first month or two from real uploads. Set
`BORDERLINE_LOG_PATH` and every accepted upload whose match count lands just
above the threshold writes a line you can review:

```
BORDERLINE photo_id=42 station=casa-do-pobo match_count=13 threshold=8
```

If that band is densely populated, raise `FEATURE_MATCH_MIN_MATCHES`; if it's
empty, the threshold may be too low. Restart the app after changing any
threshold env var.

### Logs to watch

| Logger                | Why you'd look                                                            |
| --------------------- | ------------------------------------------------------------------------- |
| `reframe.access`      | Apache-combined access log — basic post-launch usage.                     |
| `reframe.upload`      | One line per upload (token, station, bytes, decision); WARNING on reject. |
| `reframe.cleanup`     | The 30-day soft-delete cleanup — one line per file removed at boot.       |
| `reframe.errors`      | Unhandled exceptions; the themed 500 page is also rendered.               |
| `reframe.submissions` | Submission-form email failures.                                           |
| `reframe.uploads_notifications` | Per-upload notification email — one line per send/skip/failure (when the admin toggle is on). |

Everything not file-redirected goes to stderr — wherever your supervisor (or
`docker compose logs`) captures it.

### QR signage

Each station's sign carries two QR codes:

1. **About this place** → the station page root, e.g.
   `https://<host>/en/anceu/casa-do-pobo` (the leading segment is the visitor's
   language; slugs are language-agnostic).
2. **Upload a photo** → the same page with the upload anchor — `#subir` in
   Spanish, `#upload` in English.

Station URLs are `/{lang}/{location-slug}/{station-slug}`. The slug bakes into
the printed QR, so **late slug changes are expensive** — they invalidate every
printed sign. Confirm slugs before printing. Each target page still carries the
language toggle in its footer, so a visitor can switch.

### Worth knowing

- **EXIF is stripped** from stored photos after the capture date is read — GPS
  and other metadata don't persist in the public files. (`tests/test_security.py`
  guards this end-to-end against the served derivative.)
- **Uploaded photos are public.** Every accepted upload is served at `/photos/…`
  and joins the station's public timelapse — there's no private/pending state.
  People can appear incidentally in shots; the only removal path is the admin
  **Quitar** takedown (above). Make that route, and a contact address for
  removal requests, easy to reach for whoever operates the deployment.
- **Soft-deleted photos keep their files for 30 days** before the boot-time
  cleanup hard-deletes them. There's no un-delete UI; reversal within the window
  is a single SQL update:
  `UPDATE photo SET removed_at = NULL, removal_reason = NULL WHERE id = ?;`
- **Admin takedown affects the validator's reference set** — a removed photo no
  longer contributes to the sliding-window references for future uploads.
- **Idempotency tokens** prevent duplicate uploads of the same submission.

## Licence

MIT — see [`LICENSE`](./LICENSE).
