# CLAUDE.md

Working reference for ReFrame: a brief repo overview, the conventions to follow, an accurate file layout, and the current state of the build.

## Repo overview

ReFrame is a community repeat-photography project for Rural Hackers (Anceu, Galicia). Each station has a 3D-printed phone holder; visitors scan a QR, upload a photo, and a per-station timelapse builds over time. The build is open-source and themable for forks: stations are dynamic (managed through an admin UI), there is a marketing landing page plus `/locations` and a community submission ("host a location") form, and the whole thing ships with a Docker + Caddy deployment story. The **"abundant brooks"** homepage is a full-screen video hero with About + Quote + Locations + Setup sections, a fixed wavy-bottomed nav, and a deep-green design system (Anton / Be Vietnam Pro / Permanent Marker / JetBrains Mono). The standalone `/about` page was retired — its content lives in the homepage About section.

**Stack** — FastAPI + Jinja2; vanilla JS, plain CSS; self-hosted fonts; SQLite + local filesystem behind a storage abstraction (B2 / Cloudflare swap-in via env var). Pillow / pillow-heif / OpenCV power the upload pipeline. No bundler, no JS framework, no analytics, no third-party CDN at first paint. The `/locations` map self-hosts Leaflet; OpenStreetMap tiles are the one accepted runtime third-party dependency, and only on that page. The homepage hero video (`static/img/hero-video.mp4`, ~1.6 MB) is bundled — it's lazy-loaded behind a poster, a deliberate deviation from the §8.1 page-weight budget.


**Conventions**

- **Design tokens, never raw values.** All colour, type, spacing, motion live in `static/css/tokens.css` — the single canonical token set, which a fork edits directly to rebrand. Stylesheets reference `var(--token)`. The critical above-the-fold subset is mirrored as an inlined block in `templates/base.html`; these two sources must be kept in sync by hand — no build step derives one from the other (`tests/test_tokens_sync.py` guards it).
- **All UI strings via `t(key, lang)`.** Strings live in `app/strings.py` as a flat dict-of-dicts, key convention `surface.element.variant` (spec §9.9). `t()` falls back en→es→key. Adding a third UI language is a config change, not a refactor. (Admin templates are the exception — Spanish is inlined directly, a deliberate scope call for an internal single-language tool.)
- **Bilingual URLs.** Every page lives at `/{lang}/...`. Enabled languages and the default come from `data/site.toml` (`[languages] enabled`; first entry is the default — English by default, Spanish optional); root redirects per `Accept-Language`. Stations live at `/{lang}/{location-slug}/{station-slug}` (no path word). Standalone pages use localised segments: `/locations` ↔ `/lugares`, `/host` ↔ `/acoger` (see `LOCATIONS_SEGMENT` / `HOST_SEGMENT` in `app/views.py`). Slugs are language-agnostic and read-only after creation.
- **British English in narrative copy and comments; American English in code identifiers.**
- **Branding / theming for forks.** A fork rebrands via `data/site.toml` (name, taglines, languages, links, SMTP), the colour / spacing tokens in `static/css/tokens.css` (and the mirrored block in `templates/base.html`), `static/branding/` (favicon set + default OG image), and `static/img/` (hero video / about / community imagery). The brand mark is `templates/partials/logo.html` (inlined SVG, coloured per-surface via `currentColor`). The homepage featured cards are an editorial list — `HOMEPAGE_FEATURED_SLUGS` in `app/views.py`. Layout, type pairing, and component primitives are not meant to be re-themed.

**Layout**

```
app/__init__.py                 (empty)
app/main.py                     FastAPI entry — routes (landing, station, locations, host, upload, admin), mounts, lifespan, robots.txt + sitemap.xml, themed 404/500, access-log + same-origin (CSRF) + per-IP rate-limit middleware, 30-day cleanup
app/config.py                   env-var Settings (validation thresholds, ADMIN_*, SUBMISSIONS_ENABLED, NEARBY_RADIUS_KM, RATE_LIMIT_ENABLED, SMTP_* incl. SmtpConfig) + SiteConfig (name/footer/languages) loaded from data/site.toml
app/strings.py                  STRINGS dict + t() (en→es→key fallback) / other_lang() / month_name() / month_abbr(); homepage + locations + host copy
app/db.py                       SQLite schema (location + station + photo + setting) + connection helper + COLUMN_ADDITIONS / COLUMN_DROPS migrations; `python -m app.db init`
app/seed.py                     site.toml-aware seed: [[locations]] + [[stations]] → rows; `python -m app.seed`
app/storage.py                  §7.1 four-function abstraction (local backend) + layout / URL helpers
app/photos.py                   recent_active / most_recent / count_active / active_reference_set / all_active_chronological / admin_list / count_active_all_stations
app/views.py                    view-model builders (landing/locations/station/admin/host) + path helpers (station_path, locations_path, host_path) + *_meta builders
app/validation.py               §7.3 upload pipeline — HEIC transcode, EXIF orientation, captured_at, OpenCV checks, derivatives (viewer + thumb), idempotency
app/email.py                    SMTP send for the community submission form (background-task; logs failures to reframe.submissions)
app/countries.py                ISO 3166-1 alpha-2 codes → {en, es} names + admin-dropdown helpers (location.country stores the code)
app/settings_store.py           persistent key/value `setting` table — admin-toggleable runtime settings (distinct from deploy-time config.Settings)
templates/base.html             chrome shell with critical CSS inlined; per-page `{% block scripts %}` hook; meta / OG / favicon / theme-color (#163528)
templates/landing.html          "abundant brooks" homepage — hero (video + parallax), about, quote, locations (featured cards), setup
templates/station.html          single bilingual station template — hero, story, stats, reference, viewer, upload, others
templates/locations.html        /locations — Leaflet map + country→location→station grouped list
templates/host.html             /host community submission form + confirmation state (honeypot-guarded)
templates/error.html            themed 404 / 500 page (chrome reused, microcopy from app.strings)
templates/partials/header.html        fixed REFRAME logo + Locations/Setup nav + language toggle + inlined wavy bottom-mask SVG
templates/partials/footer.html        config-driven attribution + sign-off (deep-green band, light-teal text)
templates/partials/language_toggle.html
templates/partials/logo.html           inlined ReFrame logo SVG — fills via currentColor, sized + coloured by surface CSS
templates/partials/station_hero.html   full-bleed photo + charcoal block (§5.2)
templates/partials/home_location_card.html  homepage white card (image + uppercase badge + "View Timelapse →" pill)
templates/partials/viewer.html         timelapse viewer (§5.5) with inline JSON payload
templates/partials/upload.html          upload section (§6) — six-state shells + inline JSON payload
templates/admin/layout.html              admin chrome — sidebar Fotos · Lugares · Estaciones · Ajustes
templates/admin/photos.html              takedown list + Quitar form + pagination
templates/admin/locations.html           admin location list
templates/admin/location_form.html       admin location create / edit
templates/admin/stations.html            admin station list (all statuses)
templates/admin/station_form.html        admin station create / edit + seed-photo management
templates/admin/settings.html            admin editable threshold / settings view
templates/admin/_remove_confirm_dialog.html   shared confirm-dialog partial (photo removal)
templates/admin/_action_confirm_dialog.html   shared confirm-dialog partial (location / station actions)
static/css/tokens.css           "abundant brooks" token set (deep-green palette, four type families, expanded spacing scale)
static/css/app.css              @font-face + reset + fixed site-header + footer + shared primitives (.section-label, .btn-outline) + reveal system + .home-* sections + legacy station / viewer / upload / admin / locations / host / error styles
static/fonts/                   anton-400, be-vietnam-pro-{400,500,700}, permanent-marker-400, jetbrains-mono-400
static/img/                     hero-video.mp4 (~1.6 MB), hero-poster.jpg, hero-mask-{top,bottom}.svg, shared-roots.jpg, project.jpg, community-background.jpg, logo.svg (canonical) + logo.png (CSS background-image placeholders) — homepage fork-swap assets
static/branding/                favicon set (svg / 32 png / apple-touch / ico) + og-default.jpg — fork swap point
static/vendor/leaflet/          self-hosted Leaflet 1.9.4 (js / css / marker images) for the /locations map
static/js/nav.js                sticky-nav slide on scroll (rAF-throttled, gated on prefers-reduced-motion)
static/js/home.js               hero-video parallax (rAF-throttled scroll handler, gated on prefers-reduced-motion)
static/js/reveal.js             homepage scroll-reveal + hero on-load cascade (toggles [data-revealed])
static/js/viewer.js             timelapse viewer module (vanilla JS) + window.ReFrameViewer.append hook
static/js/upload.js             upload state machine — picker → preview → uploading → validating → success/failure
static/js/host.js               host-form client polish (email trim + inline format validation)
static/js/locations-map.js      /locations Leaflet map — reads an inline JSON marker payload
static/js/admin.js              admin confirm-dialog interception
data/site.toml                  branding / languages only (tracked; no secrets or operational settings — submissions, nearby-radius + SMTP are env)
data/stations.toml              editable [[locations]] + [[stations]] seed copy (tracked; bootstrap convenience)
data/reframe.db                 SQLite (git-ignored)
data/photos/{slug}/{viewer,thumb}/   uploaded photos (git-ignored)
tests/                          19 test modules + conftest.py (routing, db, seed, storage, photos, site-config, routes, pages, viewer, upload, validation, admin, phase7, countries, smoke, email, strings, security); pytest-cov wired (`uv run pytest --cov=app`)
Dockerfile                      uv-based image running uvicorn
docker-compose.yml              app + Caddy (automatic HTTPS); Caddyfile; docker-entrypoint.sh first-run bootstrap
README.md                       project overview + deployment runbook (uv + Docker/Caddy + SMTP + site.toml)
LICENSE                         MIT
pyproject.toml                  pinned deps + dev group; managed by uv
```

## Current state

All of v1 (Phases 0–7), v2 (Blocks A–J), and the "abundant brooks" homepage redesign have shipped, plus follow-up cleanups (logo/favicon refresh, dropping the `original` photo derivative, hardcoding homepage cards / dropping `is_featured`). The suite is at **292 passing tests at 92% line coverage** (`uv run pytest --cov=app`).

Non-homepage pages (station, `/locations`, `/host`, admin, error) inherit the new design tokens but keep their v2 layout — a follow-up redesign pass to bring them fully into the "abundant brooks" system is flagged.

**Meta / SEO / errors.** Per-page meta is built by `views.landing_meta` / `views.station_meta` (absolute URLs from `Request.base_url`; description, OG, Twitter-card, og:image with dimensions + alt). Landing uses the bundled `static/branding/og-default.jpg`; stations with photos use the latest viewer frame, else fall back to the default. `/robots.txt` allows everything except `/admin/` and `/api/` and points at `/sitemap.xml`, which lists the public landing + active-station URLs with `hreflang` alternates. `templates/error.html` serves themed 404/500 (404 lang inferred from URL path; 401 from admin preserved verbatim with `WWW-Authenticate`; 5xx logged to `reframe.errors` with no DB calls). Access-log middleware writes one Apache-combined line per request to the `reframe.access` logger.

**Launch-readiness sanity check** (the deploying party should follow the Deployment section of `README.md`):

- **Bare path:** `uv sync` → `uv run python -m app.db init` → `uv run python -m app.seed` → `uv run uvicorn app.main:app` boots cleanly.
- **Docker path:** `docker compose up --build` (entrypoint seeds the data volume on first run). _Not runtime-verified — Docker was unavailable in the build environment; config is syntax-checked only._
- `ADMIN_SLUG=… ADMIN_PASSWORD=…` set the admin gate; without them the admin routes 404.
- `data/site.toml` drives branding (name, footer attribution) and enabled languages only. Operational settings are env vars: `SUBMISSIONS_ENABLED` (the `/host` form toggle), `NEARBY_RADIUS_KM`, and all SMTP config (`SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_USE_TLS` / `SMTP_FROM_ADDRESS` / `SMTP_RECIPIENT` / `SMTP_PASSWORD`) — nothing secret or operational is committed.
- Validation thresholds and `site.toml` changes need a restart; the matcher's reference set is the recent active photos, so adding a photo through the admin photo form widens it on the next upload without one.

**Outstanding launch-readiness follow-ups**: Spanish stand-in copy needs Rural Hackers sign-off; real seed photos + threshold tuning from real uploads; a real Lighthouse / page-weight re-measurement against the v2 + homepage surfaces (the v1 §8.1 figures and §4.3 a11y audit are v1-only snapshots and have not been re-run); real-device a11y + hero-video behaviour; `docker compose up` end-to-end verification.
