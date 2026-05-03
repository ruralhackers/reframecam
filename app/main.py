"""FastAPI app entry.

Public routes:

  /                                       → 302 to /{lang}/
  /{lang}/                                → marketing landing page
  /{lang}/{location-slug}/{station-slug}  → station page
  POST /api/upload                        → upload pipeline (§7.3)

Templates live under /templates; static assets under /static. The local
storage backend serves uploaded photos under /photos/. On startup the
on-disk photo layout (§7.3) is reconciled for whatever stations
already exist in the DB.
"""

from __future__ import annotations

import base64
import datetime as dt
import logging
import re
import secrets as _secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, countries, db, photos, settings_store, storage, validation, views
from app.config import REPO_ROOT
from app.email import send_submission, send_upload_notification
from app.strings import other_lang, t


TEMPLATES_DIR = REPO_ROOT / "templates"
STATIC_DIR = REPO_ROOT / "static"


def _pick_lang_from_accept(header_value: str | None) -> str:
    """Pick an enabled language from an Accept-Language header.

    Honours quality values loosely — first enabled tag wins. Falls back to
    the configured default language when no enabled tag is present.
    """
    enabled = config.site.enabled_languages
    default = config.site.default_language
    if not header_value:
        return default

    parts = [chunk.strip() for chunk in header_value.split(",") if chunk.strip()]
    for part in parts:
        tag = part.split(";", 1)[0].strip().lower()
        primary = tag.split("-", 1)[0]
        if primary in enabled:
            return primary

    return default


def _existing_station_slugs() -> list[str]:
    """Read slugs from the DB if it exists; otherwise return an empty list.

    A fresh checkout boots before `python -m app.seed` has run; we don't
    want app startup to error out, just to no-op on the layout reconcile.
    """
    if not db.db_path().is_file():
        return []
    try:
        conn = db.connect()
    except sqlite3.OperationalError:
        return []
    try:
        cur = conn.execute("SELECT slug FROM station ORDER BY slug")
        return [row["slug"] for row in cur.fetchall()]
    except sqlite3.OperationalError:
        # DB exists but the schema isn't applied yet.
        return []
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.ensure_storage_layout(_existing_station_slugs())
    cleanup_expired_removals()
    yield


# ---------------------------------------------------------------------------
# 30-day soft-delete file cleanup (spec §7.5)
# ---------------------------------------------------------------------------
#
# Soft-deleted photos retain their files on disk for 30 days as the safety net
# against accidental removal. After that, the files are hard-deleted; the DB
# row stays (audit trail). A photo that has already been cleaned has its three
# `*_path` columns blanked, which is how this scan idempotently skips already-
# cleaned rows. APScheduler is overkill at MVP scale — running once per server
# boot is enough; on a typical deploy this fires whenever uvicorn restarts.

CLEANUP_RETENTION_DAYS = 30

_cleanup_log = logging.getLogger("reframe.cleanup")


def cleanup_expired_removals(*, now: dt.datetime | None = None) -> int:
    """Hard-delete files for photos soft-deleted >30 days ago.

    Returns the number of rows whose files were cleaned this run. Idempotent:
    a row whose `*_path` columns are already empty is skipped, so re-running
    on the same DB hits no work.
    """
    if not db.db_path().is_file():
        return 0
    try:
        conn = db.connect()
    except sqlite3.OperationalError:
        return 0

    cutoff = (now or dt.datetime.utcnow()) - dt.timedelta(days=CLEANUP_RETENTION_DAYS)

    try:
        cur = conn.execute(
            """
            SELECT id, station_slug, filename
            FROM photo
            WHERE removed_at IS NOT NULL
              AND removed_at <= ?
              AND viewer_path != ''
            """,
            (cutoff,),
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        # Schema not applied yet (e.g. fresh checkout before `python -m app.db init`).
        conn.close()
        return 0

    cleaned = 0
    try:
        for row in rows:
            try:
                storage.delete_photo(row["station_slug"], row["filename"])
            except Exception:  # noqa: BLE001
                _cleanup_log.exception(
                    "cleanup: delete_photo failed photo_id=%s", row["id"]
                )
                continue
            conn.execute(
                """
                UPDATE photo
                SET viewer_path = '', thumb_path = ''
                WHERE id = ?
                """,
                (int(row["id"]),),
            )
            cleaned += 1
            _cleanup_log.info(
                "cleanup: hard-deleted files photo_id=%s station=%s filename=%s",
                row["id"], row["station_slug"], row["filename"],
            )
    finally:
        conn.close()

    return cleaned


app = FastAPI(title="ReFrame", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Exception handlers — themed 404 / 500 (§10.4)
# ---------------------------------------------------------------------------
#
# Registered here, immediately after the app is created, so any later
# route that raises HTTPException(404) or unhandled Exception returns the
# themed page rather than FastAPI's default JSON error body. The /api/upload
# endpoint owns its own JSON-shaped error responses (§6.5) and does not
# raise HTTPException for those — they're returned via JSONResponse.


# ---------------------------------------------------------------------------
# Request access log (§10.4)
# ---------------------------------------------------------------------------
#
# Apache "combined" log format on the `reframe.access` logger so the
# deploying party can hook a file handler without code changes. uvicorn ships
# its own access log; this is the application-level mirror, useful for the
# basic post-launch usage analysis Rural Hackers may want (§8.5).
#
#   <ip> - - [<time>] "<method> <path> HTTP/1.1" <status> <bytes> "<ref>" "<ua>" <ms>


_access_log = logging.getLogger("reframe.access")


@app.middleware("http")
async def access_log_middleware(request: Request, call_next):
    import time as _time

    started = _time.perf_counter()
    response: Response = await call_next(request)
    elapsed_ms = int((_time.perf_counter() - started) * 1000)

    client_ip = request.client.host if request.client else "-"
    when = dt.datetime.utcnow().strftime("%d/%b/%Y:%H:%M:%S +0000")
    method = request.method
    path = request.url.path
    if request.url.query:
        path = f"{path}?{request.url.query}"
    status = response.status_code
    length = response.headers.get("content-length", "-")
    referer = request.headers.get("referer", "-")
    user_agent = request.headers.get("user-agent", "-")

    _access_log.info(
        '%s - - [%s] "%s %s HTTP/1.1" %s %s "%s" "%s" %dms',
        client_ip,
        when,
        method,
        path,
        status,
        length,
        referer,
        user_agent,
        elapsed_ms,
    )

    return response


# ---------------------------------------------------------------------------
# Same-origin guard (CSRF defence)
# ---------------------------------------------------------------------------
#
# Every state-changing route in this app (upload, the /host form, all admin
# POSTs) is driven by the site's own pages — there is no cross-origin API. So
# for any unsafe method we require that a present Origin/Referer match the
# request's Host. This blocks a forged cross-site POST (which the browser
# always stamps with an Origin) — including ones that would replay a logged-in
# admin's cached Basic-Auth credentials.
#
# We only reject on a *mismatch*: a request with neither header (a non-browser
# client, or the test suite) is let through — those aren't the CSRF threat
# model, and the SOP guarantees a genuine cross-site browser POST carries one.

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_security_log = logging.getLogger("reframe.security")


# ---------------------------------------------------------------------------
# Per-IP rate limiting
# ---------------------------------------------------------------------------
#
# A small in-process fixed-window limiter on the abuse-prone surfaces — admin
# (Basic-Auth brute force), uploads (CPU/disk burn: each runs a HEIC decode +
# OpenCV feature match), and the /host form (mail-spam). It's deliberately
# dependency-free and single-process: fine for the single-uvicorn deployment
# this ships with, and it fails open on restart. A fork running multiple
# workers or wanting a shared store should put a limiter at the proxy/WAF layer
# and set RATE_LIMIT_ENABLED=false.
#
# Limits are (max_requests, window_seconds) per IP per category. Generous for a
# community site; a fork tunes them here.
_RATE_LIMITS: dict[str, tuple[int, int]] = {
    "admin": (60, 60),     # 60 req / minute / IP across the admin surface
    "upload": (30, 60),    # 30 uploads / minute / IP
    "host": (10, 3600),    # 10 submissions / hour / IP
}

# key = (category, client_ip) → list of request monotonic timestamps in-window.
_rate_buckets: dict[tuple[str, str], list[float]] = {}


def _rate_category(request: Request) -> str | None:
    """Classify a request into a rate-limit bucket, or None to skip limiting."""
    path = request.url.path
    if path.startswith("/admin/"):
        return "admin"
    if path == "/api/upload":
        return "upload"
    # /host is localised (/{lang}/host, /{lang}/acoger); only the POST submits.
    if request.method == "POST" and (path.endswith("/host") or path.endswith("/acoger")):
        return "host"

    return None


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if config.settings.rate_limit_enabled:
        category = _rate_category(request)
        if category is not None:
            limit, window = _RATE_LIMITS[category]
            ip = request.client.host if request.client else "-"
            key = (category, ip)
            now = time.monotonic()
            cutoff = now - window

            bucket = _rate_buckets.get(key)
            if bucket is None:
                bucket = []
                _rate_buckets[key] = bucket
            # Drop timestamps that have aged out of the window (in place).
            bucket[:] = [ts for ts in bucket if ts > cutoff]

            if len(bucket) >= limit:
                _security_log.warning(
                    "rate limit hit: category=%s ip=%s limit=%d/%ds",
                    category, ip, limit, window,
                )
                return Response(
                    content="rate limit exceeded",
                    status_code=429,
                    headers={"Retry-After": str(window)},
                )
            bucket.append(now)

    return await call_next(request)


@app.middleware("http")
async def same_origin_guard(request: Request, call_next):
    if request.method not in _SAFE_METHODS:
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            source_host = urlsplit(source).netloc
            expected_host = request.headers.get("host", "")
            if source_host and source_host != expected_host:
                _security_log.warning(
                    "cross-origin %s blocked: path=%s origin/referer-host=%s host=%s",
                    request.method,
                    request.url.path,
                    source_host,
                    expected_host,
                )
                return Response(content="cross-origin request blocked", status_code=403)

    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return _render_error(request, 404)
    if exc.status_code == 401 and exc.headers:
        # Preserve the WWW-Authenticate challenge for the admin Basic-Auth
        # path — browsers won't show their password prompt without it.
        return Response(
            content=exc.detail or "Unauthorized",
            status_code=401,
            headers=exc.headers,
            media_type="text/plain",
        )
    if exc.status_code >= 500:
        return _render_error(request, 500)

    # 400 / 403 / etc — preserve the upstream behaviour (FastAPI default)
    # but route 4xx that don't have specific copy through a plain text body
    # so we don't need bespoke templates for every HTTP status.
    return Response(
        content=exc.detail or "",
        status_code=exc.status_code,
        media_type="text/plain",
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # Log, then surface the themed 500. The middleware already records the
    # request line; this is the place to attach the traceback.
    logging.getLogger("reframe.errors").exception("unhandled error: %s", request.url.path)

    return _render_error(request, 500)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _mount_data_dirs() -> None:
    """Mount the local-backend photo directory."""
    data_root = config.settings.data_root
    photos_dir = data_root / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/photos", StaticFiles(directory=photos_dir), name="photos")


_mount_data_dirs()


templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["t"] = t
templates.env.globals["other_lang"] = other_lang
templates.env.globals["site"] = config.site
templates.env.globals["enabled_langs"] = config.site.enabled_languages
templates.env.globals["submissions_enabled"] = config.settings.submissions_enabled


@app.get("/", include_in_schema=False)
async def root(request: Request) -> RedirectResponse:
    lang = _pick_lang_from_accept(request.headers.get("accept-language"))

    return RedirectResponse(url=f"/{lang}/", status_code=302)


def _enabled(lang: str) -> bool:
    return lang in config.site.enabled_languages


# ---------------------------------------------------------------------------
# Themed 404 / 500 pages (§10.4)
# ---------------------------------------------------------------------------
#
# Same chrome, same tokens. Language inferred from the URL path so an English
# 404 on /en/missing/ stays in English. The 500 handler is conservative —
# it never re-enters the request stack (no DB calls, no view-model builders),
# so a fault in the data layer can't loop into another 500.


def _lang_from_path(path: str) -> str:
    parts = path.split("/", 2)
    if len(parts) > 1 and parts[1] in config.site.enabled_languages:
        return parts[1]

    return config.site.default_language


def _render_error(request: Request, status_code: int) -> Response:
    lang = _lang_from_path(request.url.path)
    key = "404" if status_code == 404 else "500"
    context = {
        "request": request,
        "lang": lang,
        "status_code": status_code,
        "page_title": t(f"error.{key}.title", lang),
        "error_label": t(f"error.{key}.label", lang),
        "error_heading": t(f"error.{key}.heading", lang),
        "error_body": t(f"error.{key}.body", lang),
        "error_cta": t(f"error.{key}.cta", lang),
        # Skip the `meta_description` / OG block on error pages — they
        # shouldn't appear in link previews or be canonicalised.
    }

    return templates.TemplateResponse(
        request, "error.html", context, status_code=status_code
    )


# ---------------------------------------------------------------------------
# robots.txt + sitemap.xml (§10.4)
# ---------------------------------------------------------------------------
#
# Standard SEO basics. The sitemap covers the eight public URLs (two landings
# + three stations × two languages) and links each station's bilingual pair
# via `xhtml:link rel="alternate" hreflang=...` so search engines pick the
# right language for the right region.


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt(request: Request) -> Response:
    sitemap = str(request.base_url).rstrip("/") + "/sitemap.xml"
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin/\n"
        "Disallow: /api/\n"
        f"Sitemap: {sitemap}\n"
    )

    return Response(body, media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(request: Request) -> Response:
    base = str(request.base_url).rstrip("/")
    conn = db.connect()
    try:
        # Only active stations are listed — draft / archived are "render but
        # unlisted" and stay out of the sitemap.
        rows = views.fetch_public_stations(conn)
        stations = [(row["location_slug"], row["slug"]) for row in rows]
    finally:
        conn.close()

    langs = config.site.enabled_languages
    urls: list[tuple[str, dict[str, str]]] = []
    # Landing pages.
    landing_alternates = {lang: f"{base}/{lang}/" for lang in langs}
    for lang in langs:
        urls.append((landing_alternates[lang], landing_alternates))
    # Station pages.
    for location_slug, station_slug in stations:
        alt = {
            lang: f"{base}{views.station_path(lang, location_slug, station_slug)}"
            for lang in langs
        }
        for lang in langs:
            urls.append((alt[lang], alt))

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for loc, alternates in urls:
        parts.append("  <url>")
        parts.append(f"    <loc>{loc}</loc>")
        for lang, href in alternates.items():
            parts.append(
                f'    <xhtml:link rel="alternate" hreflang="{lang}" href="{href}" />'
            )
        parts.append("  </url>")
    parts.append("</urlset>")
    body = "\n".join(parts) + "\n"

    return Response(body, media_type="application/xml")


@app.get("/{lang}/", name="landing")
async def landing(request: Request, lang: str):
    if not _enabled(lang):
        return RedirectResponse(
            url=f"/{config.site.default_language}/", status_code=302
        )

    conn = db.connect()
    try:
        view = views.landing_view(conn, lang)
    finally:
        conn.close()

    base_url = str(request.base_url)
    meta = views.landing_meta(lang, base_url)

    return templates.TemplateResponse(
        request,
        "landing.html",
        {"lang": lang, "view": view, **meta},
    )


# The station page route (`/{lang}/{location}/{station}`) is a three-segment
# catch-all — it would shadow `/admin/{slug}/stations` etc. To keep it from
# swallowing other three-segment paths it is registered LAST, at the end of
# this module, after every literal-prefixed route.


# ---------------------------------------------------------------------------
# Upload endpoint — Phase 5 (real validator)
# ---------------------------------------------------------------------------
#
# Wires the §7.3 pipeline to `POST /api/upload`. Pipeline lives in
# `app.validation`; this handler does I/O glue: parse the multipart body,
# look up by client_token for idempotency, run the pipeline (or short-circuit
# on a duplicate), map failures back to the §6.5-keyed JSON shape Phase 4's
# upload.js consumes.
#
# Response contract (preserved from Phase 4 so the client doesn't change):
#   200 {ok: true, id, captured_at, filename, station_slug, viewer_url, thumb_url}
#   200 {ok: false, error: "wrong_file_type" | "doesnt_match" | "too_blurry"}
#   500 {ok: false, error: "server_error"}
# The `network` failure code is generated client-side when the XHR errors or
# the upload stalls — never returned by the server.
#
# `?test_failure=<code>` is preserved as a dev-only convenience for UI smoke
# testing; the `unknown_test_failure → 400` rule still applies. Phase 6 may
# strip it once the admin / e2e harness is in place.

_log = logging.getLogger("reframe.upload")

_UPLOAD_FAILURE_STATUS: dict[str, int] = {
    "wrong_file_type": 200,
    "doesnt_match": 200,
    "too_blurry": 200,
    "too_large": 200,
    "too_small": 200,
    "not_ready": 200,
    "server_error": 500,
}


def _failure_response(code: str) -> JSONResponse:
    status = _UPLOAD_FAILURE_STATUS.get(code, 500)

    return JSONResponse({"ok": False, "error": code}, status_code=status)


def _success_response(
    *,
    photo_id: int,
    captured_at,
    filename: str,
    station_slug: str,
    viewer_url: str,
    thumb_url: str,
) -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "id": photo_id,
            "captured_at": _captured_at_iso(captured_at),
            "filename": filename,
            "station_slug": station_slug,
            "viewer_url": viewer_url,
            "thumb_url": thumb_url,
        }
    )


def _captured_at_iso(value) -> str:
    """Format `captured_at` as `YYYY-MM-DDTHH:MM:SSZ`.

    Phase 4's upload.js parses this with `new Date(...)` to build the
    success-state date overlay. The replay path can hand back either a
    `datetime` (PARSE_DECLTYPES) or a plain string (when SQLite's deprecated
    converter isn't picked up); normalise both to the same wire shape.
    """
    import datetime as _dt

    if hasattr(value, "isoformat"):
        text = value.replace(microsecond=0).isoformat()
    else:
        text = str(value).replace("T", " ")
        try:
            parsed = _dt.datetime.fromisoformat(text)
            text = parsed.replace(microsecond=0).isoformat()
        except ValueError:
            return str(value)
    if not text.endswith("Z"):
        text = text + "Z"

    return text


@app.post("/api/upload", name="upload")
async def upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile,
    station_slug: str = Form(),
    test_failure: str | None = None,
    x_client_token: str | None = Header(default=None, alias="X-Client-Token"),
):
    body = await file.read()
    _log.info(
        "upload: station=%s token=%s bytes=%d content_type=%s filename=%s magic=%s test_failure=%s",
        station_slug,
        x_client_token,
        len(body),
        file.content_type,
        file.filename,
        body[:16].hex() if body else "empty",
        test_failure,
    )

    # Dev-only short-circuit — surface a known failure code without touching
    # the pipeline. Useful for client-side testing of §6.5 microcopy paths.
    if test_failure is not None:
        if test_failure not in _UPLOAD_FAILURE_STATUS:
            raise HTTPException(status_code=400, detail="unknown test_failure")
        return _failure_response(test_failure)

    if not x_client_token:
        # The client always sends one; an absent token means a malformed
        # request — surface as a server_error. (The client reuses its existing
        # token on a server_error retry, but a request that reaches here had no
        # token to begin with, so there's no idempotency state to collide with.)
        return _failure_response("server_error")

    conn = db.connect()
    try:
        # Reject uploads to a station we don't know about — preserves the
        # FK-style guarantee even though the photo INSERT would also fail.
        cur = conn.execute("SELECT slug FROM station WHERE slug = ?", (station_slug,))
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="unknown station")

        # Step 2: idempotency. A duplicate token returns the prior response
        # bytes-for-bytes — no re-validation, no re-persistence.
        prior = validation.lookup_by_client_token(conn, x_client_token)
        if prior is not None:
            _log.info("upload idempotent hit: photo_id=%s", prior["id"])
            return _success_response(
                photo_id=int(prior["id"]),
                captured_at=prior["captured_at"],
                filename=prior["filename"],
                station_slug=prior["station_slug"],
                viewer_url=storage.photo_url(station_slug, prior["filename"], "viewer"),
                thumb_url=storage.photo_url(station_slug, prior["filename"], "thumb"),
            )

        try:
            result = validation.process_upload(
                conn=conn,
                station_slug=station_slug,
                client_token=x_client_token,
                file_bytes=body,
            )
        except validation.ValidationFailure as failure:
            _log.warning(
                "upload rejected: station=%s code=%s detail=%s",
                station_slug,
                failure.code,
                failure.detail,
            )
            return _failure_response(failure.code)
        except Exception:  # noqa: BLE001 — pipeline-wide catch-all for §7.3 step 9
            _log.exception("upload pipeline crashed: station=%s", station_slug)
            return _failure_response("server_error")

        _maybe_schedule_upload_notification(
            conn,
            background_tasks=background_tasks,
            request=request,
            station_slug=station_slug,
            result=result,
        )

        return _success_response(
            photo_id=result.photo_id,
            captured_at=result.captured_at,
            filename=result.filename,
            station_slug=station_slug,
            viewer_url=result.viewer_url,
            thumb_url=result.thumb_url,
        )
    finally:
        conn.close()


def _maybe_schedule_upload_notification(
    conn,
    *,
    background_tasks: BackgroundTasks,
    request: Request,
    station_slug: str,
    result: validation.PipelineResult,
) -> None:
    """Schedule an operator notification email if the toggle is on.

    Only called from the fresh-success branch — the idempotent-replay path
    must not re-notify (the recipient already received the original email).

    The photo is already persisted by the time we get here, so notification is
    best-effort: any fault (a DB read, a missing station row, the base-url
    parse) must be logged and swallowed rather than escaping the handler and
    turning a saved photo into a 500.
    """
    try:
        if not settings_store.upload_notifications_enabled(conn):
            return

        row = views.fetch_station(conn, station_slug)
        if row is None:
            return

        station_name = row["name_en"] or row["name_es"] or station_slug
        base = str(request.base_url).rstrip("/")
        viewer_url = f"{base}{result.viewer_url}"
        thumb_path = storage.local_photo_path(station_slug, result.filename, "thumb")

        background_tasks.add_task(
            send_upload_notification,
            station_name=station_name,
            station_slug=station_slug,
            captured_at=result.captured_at,
            viewer_url=viewer_url,
            thumb_path=thumb_path,
        )
    except Exception:
        _log.exception(
            "upload notification scheduling failed: station=%s (photo saved)",
            station_slug,
        )


# ---------------------------------------------------------------------------
# Admin (§7.5) — Spanish-only takedown surface
# ---------------------------------------------------------------------------
#
# A single password-protected page at `/admin/{ADMIN_SLUG}/`. Both the slug
# and the password are env vars (§11.1) — values must be communicated to
# Rural Hackers privately. The slug acts as a non-guessable URL segment;
# Basic auth gates the actual page. A wrong slug returns 404 even with valid
# credentials so we don't leak that the path exists.

_ADMIN_AUTH_REALM = "ReFrame admin"


def _check_admin_slug(slug: str) -> None:
    """404 if `slug` doesn't match `ADMIN_SLUG`; never a 401, to avoid leaking
    the slug's existence to a guesser. Empty config (slug or password unset)
    also 404s — the surface is unavailable until the env is configured."""
    expected = config.settings.admin_slug
    if not expected or not config.settings.admin_password:
        raise HTTPException(status_code=404)
    if not _secrets.compare_digest(slug, expected):
        raise HTTPException(status_code=404)


def _basic_auth_unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="auth required",
        headers={"WWW-Authenticate": f'Basic realm="{_ADMIN_AUTH_REALM}"'},
    )


def _require_admin_auth(authorization: str | None) -> None:
    """Validate the `Authorization: Basic ...` header against `ADMIN_PASSWORD`.

    Username is ignored — there's a single shared password (§11.1: "single
    shared password — no user accounts"). Any non-Basic / malformed / wrong-
    password header surfaces a 401 with the WWW-Authenticate challenge.
    """
    expected = config.settings.admin_password
    if not authorization or not authorization.lower().startswith("basic "):
        raise _basic_auth_unauthorized()
    try:
        decoded = base64.b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise _basic_auth_unauthorized()
    _username, _, password = decoded.partition(":")
    if not _secrets.compare_digest(password, expected):
        raise _basic_auth_unauthorized()


_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _valid_slug(value: str) -> bool:
    return bool(_SLUG_RE.match(value))


def _clean_from_location(value: str | None) -> str:
    """Normalise a `from_location` origin signal to a safe slug (or empty).

    Threaded through the station create / edit / update flow so that a station
    reached from a location's detail page returns there on save / back, rather
    than to the global Stations list. Empty when absent or not slug-shaped.
    """
    value = (value or "").strip()

    return value if _valid_slug(value) else ""


def _admin_render(request: Request, template: str, *, active: str, **context):
    """Render an admin sub-page with the shared Spanish-only chrome."""
    return templates.TemplateResponse(
        request,
        template,
        {
            "lang": "es",
            "show_language_toggle": False,
            "admin_slug": context.get("admin_slug"),
            "admin_active": active,
            **context,
        },
    )


def _admin_guard(slug: str, authorization: str | None) -> None:
    _check_admin_slug(slug)
    _require_admin_auth(authorization)


# ── Photos ──────────────────────────────────────────────────────────────────


@app.get("/admin/{slug}/", name="admin_index")
async def admin_index(
    slug: str,
    authorization: str | None = Header(default=None),
):
    """Admin landing → Locations.

    Auth and slug are gated here so the existing 401 / 404 semantics are
    preserved; the actual page is the locations list one redirect away.
    """
    _admin_guard(slug, authorization)

    return RedirectResponse(url=f"/admin/{slug}/locations", status_code=303)


@app.get("/admin/{slug}/photos", name="admin_photos")
async def admin_photos(
    request: Request,
    slug: str,
    page: int = 1,
    notice: str | None = None,
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        view = views.admin_photos_view(conn, page=page, admin_slug=slug)
    finally:
        conn.close()

    return _admin_render(
        request,
        "admin/photos.html",
        active="photos",
        admin_slug=slug,
        page_title=view["page_title"],
        view=view,
        notice=notice,
    )


@app.post("/admin/{slug}/photo/{photo_id}/remove", name="admin_remove_photo")
async def admin_remove_photo(
    slug: str,
    photo_id: int,
    removal_reason: str | None = Form(default=None),
    redirect_to: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    reason = (removal_reason or "").strip() or None

    removed = False
    demoted = False
    conn = db.connect()
    try:
        # Look up the row before the soft-delete so we know which on-disk
        # derivatives to remove.
        row = conn.execute(
            "SELECT station_slug, filename FROM photo "
            "WHERE id = ? AND removed_at IS NULL",
            (photo_id,),
        ).fetchone()
        cur = conn.execute(
            """
            UPDATE photo
            SET removed_at = CURRENT_TIMESTAMP,
                removal_reason = ?,
                viewer_path = '',
                thumb_path = ''
            WHERE id = ? AND removed_at IS NULL
            """,
            (reason, photo_id),
        )
        # Empty rowcount means either an unknown id or an already-removed photo;
        # in both cases we silently noop rather than 404 — a stale tab clicking
        # Quitar twice shouldn't surface as an error to Rural Hackers.
        if cur.rowcount and row is not None:
            removed = True
            # Hard-delete the viewer + thumb files immediately. The DB row
            # stays (audit), but the bytes are gone — Rural Hackers expect
            # Quitar to actually remove the photo from disk, not defer it.
            try:
                storage.delete_photo(row["station_slug"], row["filename"])
            except Exception:  # noqa: BLE001
                _log.exception(
                    "admin remove: delete_photo failed photo_id=%s", photo_id
                )
            _log.info("admin remove: photo_id=%s reason=%s", photo_id, reason)
            # Removing the last active photo breaks the active-status gate
            # (§ active requires ≥1 photo). Demote the station to draft so an
            # empty station can't stay active. A location's active-ness is
            # derived from its active stations, so this also drops a now-empty
            # location out of the admin's Activos group automatically.
            if photos.count_active(conn, row["station_slug"]) == 0:
                demote = conn.execute(
                    "UPDATE station SET status = 'draft' "
                    "WHERE slug = ? AND status = 'active'",
                    (row["station_slug"],),
                )
                demoted = bool(demote.rowcount)
    finally:
        conn.close()

    # Return to the page the delete came from. The station edit page sends a
    # `redirect_to`; the Photos list sends nothing and falls back to itself.
    # Only honour same-admin local paths so the field can't drive an open redirect.
    target = f"/admin/{slug}/photos"
    if redirect_to and redirect_to.startswith(f"/admin/{slug}/"):
        target = redirect_to

    # Surface the outcome as a toast. `removed_draft` flags the knock-on
    # demotion (last photo gone → station back to draft); `removed` is the
    # plain delete. An idempotent no-op (already removed) gets no toast.
    notice = "removed_draft" if demoted else "removed" if removed else None
    if notice:
        sep = "&" if "?" in target else "?"
        target = f"{target}{sep}notice={notice}"

    return RedirectResponse(url=target, status_code=303)


# ── Locations ───────────────────────────────────────────────────────────────


@app.get("/admin/{slug}/locations", name="admin_locations")
async def admin_locations(
    request: Request,
    slug: str,
    notice: str | None = None,
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        view = views.admin_locations_view(conn, admin_slug=slug)
    finally:
        conn.close()

    return _admin_render(
        request,
        "admin/locations.html",
        active="locations",
        admin_slug=slug,
        page_title="Lugares · ReFrame",
        view=view,
        notice=notice,
    )


@app.get("/admin/{slug}/locations/new", name="admin_location_new")
async def admin_location_new(
    request: Request,
    slug: str,
    error: str | None = None,
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    return _admin_render(
        request,
        "admin/location_form.html",
        active="locations",
        admin_slug=slug,
        page_title="Nuevo lugar · ReFrame",
        is_edit=False,
        location=None,
        error=error,
        country_choices=countries.country_choices("es"),
        selected_country=countries.DEFAULT_COUNTRY,
    )


@app.post("/admin/{slug}/locations/new", name="admin_location_create")
async def admin_location_create(
    slug: str,
    location_slug: str = Form(),
    name: str = Form(),
    country: str = Form(default=""),
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    location_slug = location_slug.strip().lower()
    if not _valid_slug(location_slug) or not name.strip():
        return RedirectResponse(
            url=f"/admin/{slug}/locations/new?error=invalid", status_code=303
        )

    conn = db.connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM location WHERE slug = ?", (location_slug,)
        ).fetchone()
        if exists:
            return RedirectResponse(
                url=f"/admin/{slug}/locations/new?error=duplicate", status_code=303
            )
        conn.execute(
            "INSERT INTO location (slug, name, country) VALUES (?, ?, ?)",
            (location_slug, name.strip(), countries.normalise_country(country)),
        )
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/{slug}/locations/{location_slug}?notice=created", status_code=303
    )


@app.get("/admin/{slug}/locations/{location_slug}", name="admin_location_edit")
async def admin_location_edit(
    request: Request,
    slug: str,
    location_slug: str,
    notice: str | None = None,
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        row = views.fetch_location(conn, location_slug)
        if row is None:
            raise HTTPException(status_code=404)
        stations = views.admin_stations_for_location(
            conn, admin_slug=slug, location_slug=location_slug
        )
    finally:
        conn.close()

    location_dict = dict(row)
    return _admin_render(
        request,
        "admin/location_form.html",
        active="locations",
        admin_slug=slug,
        page_title="Editar lugar · ReFrame",
        is_edit=True,
        location=location_dict,
        error=None,
        notice=notice,
        country_choices=countries.country_choices("es"),
        selected_country=countries.normalise_country(location_dict.get("country")),
        stations=stations,
        add_station_href=f"/admin/{slug}/stations/new?location={location_slug}",
    )


@app.post("/admin/{slug}/locations/{location_slug}", name="admin_location_update")
async def admin_location_update(
    slug: str,
    location_slug: str,
    name: str = Form(),
    country: str = Form(default=""),
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        cur = conn.execute(
            "UPDATE location SET name = ?, country = ? WHERE slug = ?",
            (name.strip(), countries.normalise_country(country), location_slug),
        )
        if not cur.rowcount:
            raise HTTPException(status_code=404)
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/{slug}/locations?notice=saved", status_code=303
    )


@app.post(
    "/admin/{slug}/locations/{location_slug}/delete", name="admin_location_delete"
)
async def admin_location_delete(
    slug: str,
    location_slug: str,
    authorization: str | None = Header(default=None),
):
    """Hard-delete a location. Only permitted when it has no stations — the
    UI only surfaces the affordance for empty locations, and this re-checks
    server-side so a stale form can't orphan stations."""
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        if conn.execute(
            "SELECT 1 FROM station WHERE location_slug = ?", (location_slug,)
        ).fetchone():
            return RedirectResponse(
                url=f"/admin/{slug}/locations/{location_slug}?error=has_stations",
                status_code=303,
            )
        cur = conn.execute(
            "DELETE FROM location WHERE slug = ?", (location_slug,)
        )
        if not cur.rowcount:
            raise HTTPException(status_code=404)
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/{slug}/locations?notice=deleted", status_code=303
    )


# ── Stations ────────────────────────────────────────────────────────────────


@app.get("/admin/{slug}/stations", name="admin_stations")
async def admin_stations(
    request: Request,
    slug: str,
    notice: str | None = None,
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        view = views.admin_stations_view(conn, admin_slug=slug)
    finally:
        conn.close()

    return _admin_render(
        request,
        "admin/stations.html",
        active="stations",
        admin_slug=slug,
        page_title="Estaciones · ReFrame",
        view=view,
        notice=notice,
    )


@app.get("/admin/{slug}/stations/new", name="admin_station_new")
async def admin_station_new(
    request: Request,
    slug: str,
    error: str | None = None,
    location: str | None = None,
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        view = views.admin_station_form_view(
            conn,
            admin_slug=slug,
            row=None,
            preselected_location_slug=location,
        )
    finally:
        conn.close()

    return _admin_render(
        request,
        "admin/station_form.html",
        active="stations",
        admin_slug=slug,
        page_title="Nueva estación · ReFrame",
        view=view,
        error=error,
        notice=None,
        # Opened from a location detail page → return there on save / cancel.
        from_location=_clean_from_location(location),
    )


def _station_form_fields(
    name_es: str,
    name_en: str,
    location_slug: str,
    story_es: str,
    story_en: str,
    latitude: str,
    longitude: str,
) -> dict:
    """Normalise the shared station form fields. English doubles for Spanish
    when Spanish is left blank (English-only forks)."""
    name_en = name_en.strip()
    name_es = name_es.strip() or name_en
    story_en = story_en.strip()
    story_es = story_es.strip() or story_en

    def _coord(value: str) -> float | None:
        value = value.strip()
        try:
            return float(value) if value else None
        except ValueError:
            return None

    return {
        "name_es": name_es,
        "name_en": name_en,
        "location_slug": location_slug.strip(),
        "story_es": story_es,
        "story_en": story_en,
        "latitude": _coord(latitude),
        "longitude": _coord(longitude),
    }


@app.post("/admin/{slug}/stations/new", name="admin_station_create")
async def admin_station_create(
    slug: str,
    station_slug: str = Form(),
    name_es: str = Form(default=""),
    name_en: str = Form(default=""),
    location_slug: str = Form(),
    story_es: str = Form(default=""),
    story_en: str = Form(default=""),
    latitude: str = Form(default=""),
    longitude: str = Form(default=""),
    from_location: str = Form(default=""),
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    station_slug = station_slug.strip().lower()
    origin = _clean_from_location(from_location)
    # Preserve the origin (which also drives the location preselect) when
    # bouncing back to the form on a validation error.
    origin_qs = f"&location={origin}" if origin else ""
    fields = _station_form_fields(
        name_es, name_en, location_slug, story_es, story_en,
        latitude, longitude,
    )
    if (
        not _valid_slug(station_slug)
        or not fields["name_en"]
        or not fields["story_en"]
    ):
        return RedirectResponse(
            url=f"/admin/{slug}/stations/new?error=invalid{origin_qs}", status_code=303
        )

    conn = db.connect()
    try:
        if conn.execute(
            "SELECT 1 FROM station WHERE slug = ?", (station_slug,)
        ).fetchone():
            return RedirectResponse(
                url=f"/admin/{slug}/stations/new?error=duplicate{origin_qs}",
                status_code=303,
            )
        if not conn.execute(
            "SELECT 1 FROM location WHERE slug = ?", (fields["location_slug"],)
        ).fetchone():
            return RedirectResponse(
                url=f"/admin/{slug}/stations/new?error=location{origin_qs}",
                status_code=303,
            )
        # A new station has no seed photo yet, so it can only be created
        # as a draft (§ active-status validation rule).
        conn.execute(
            """
            INSERT INTO station (
                slug, name_es, name_en, location_slug, story_es, story_en,
                latitude, longitude, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """,
            (
                station_slug, fields["name_es"], fields["name_en"],
                fields["location_slug"], fields["story_es"], fields["story_en"],
                fields["latitude"], fields["longitude"],
            ),
        )
    finally:
        conn.close()

    storage.ensure_storage_layout([station_slug])

    created_qs = f"&from_location={origin}" if origin else ""

    return RedirectResponse(
        url=f"/admin/{slug}/stations/{station_slug}?notice=created{created_qs}",
        status_code=303,
    )


@app.get("/admin/{slug}/stations/{station_slug}", name="admin_station_edit")
async def admin_station_edit(
    request: Request,
    slug: str,
    station_slug: str,
    error: str | None = None,
    notice: str | None = None,
    from_location: str | None = None,
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        row = views.fetch_station(conn, station_slug)
        if row is None:
            raise HTTPException(status_code=404)
        view = views.admin_station_form_view(conn, admin_slug=slug, row=row)
    finally:
        conn.close()

    return _admin_render(
        request,
        "admin/station_form.html",
        active="stations",
        admin_slug=slug,
        page_title="Editar estación · ReFrame",
        view=view,
        error=error,
        notice=notice,
        from_location=_clean_from_location(from_location),
    )


@app.post("/admin/{slug}/stations/{station_slug}", name="admin_station_update")
async def admin_station_update(
    slug: str,
    station_slug: str,
    name_es: str = Form(default=""),
    name_en: str = Form(default=""),
    location_slug: str = Form(),
    story_es: str = Form(default=""),
    story_en: str = Form(default=""),
    latitude: str = Form(default=""),
    longitude: str = Form(default=""),
    status: str = Form(default="draft"),
    from_location: str = Form(default=""),
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    origin = _clean_from_location(from_location)
    fields = _station_form_fields(
        name_es, name_en, location_slug, story_es, story_en,
        latitude, longitude,
    )
    if status not in views.STATION_STATUSES:
        status = "draft"

    conn = db.connect()
    try:
        row = views.fetch_station(conn, station_slug)
        if row is None:
            raise HTTPException(status_code=404)

        notice = None
        # Active-status gate: a station can't go active without ≥1 photo
        # (admin's seed). Clamp to draft and flag it.
        if status == "active":
            readiness = views.station_readiness(conn, station_slug)
            if not readiness["ready"]:
                status = "draft"
                notice = "forced_draft"

        conn.execute(
            """
            UPDATE station SET
                name_es = ?, name_en = ?, location_slug = ?,
                story_es = ?, story_en = ?,
                latitude = ?, longitude = ?, status = ?
            WHERE slug = ?
            """,
            (
                fields["name_es"], fields["name_en"], fields["location_slug"],
                fields["story_es"], fields["story_en"],
                fields["latitude"], fields["longitude"],
                status, station_slug,
            ),
        )
    finally:
        conn.close()

    if notice == "forced_draft":
        # Clamped to draft — stay on the station page so the admin sees the
        # explanation alongside the readiness rail. Keep the origin so the
        # next save still returns to the right place.
        origin_qs = f"&from_location={origin}" if origin else ""
        target = (
            f"/admin/{slug}/stations/{station_slug}?notice=forced_draft{origin_qs}"
        )
    elif origin:
        # Reached from a location detail page → return there.
        target = f"/admin/{slug}/locations/{origin}?notice=saved"
    else:
        target = f"/admin/{slug}/stations?notice=saved"

    return RedirectResponse(url=target, status_code=303)


@app.post(
    "/admin/{slug}/stations/{station_slug}/photos",
    name="admin_station_photo_add",
)
async def admin_station_photo_add(
    slug: str,
    station_slug: str,
    photo: UploadFile = File(),
    authorization: str | None = Header(default=None),
):
    """Admin-side seed-photo upload — runs through the full validator
    pipeline (HEIC, EXIF, blur, resolution, derivatives, DB insert) but
    skips the feature-match step. The admin is trusted, and the bootstrap
    case (no existing photos) requires it."""
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        if views.fetch_station(conn, station_slug) is None:
            raise HTTPException(status_code=404)

        data = await photo.read()
        client_token = f"admin-{_secrets.token_hex(16)}"
        notice = None
        try:
            validation.process_upload(
                conn=conn,
                station_slug=station_slug,
                client_token=client_token,
                file_bytes=data,
                skip_match=True,
            )
        except validation.ValidationFailure as failure:
            _log.info(
                "admin photo upload failed: station=%s error=%s",
                station_slug, failure.code,
            )
            notice = f"photo_{failure.code}"
    finally:
        conn.close()

    target = f"/admin/{slug}/stations/{station_slug}"
    if notice:
        target += f"?notice={notice}"
    return RedirectResponse(url=target, status_code=303)


@app.post(
    "/admin/{slug}/stations/{station_slug}/archive", name="admin_station_archive"
)
async def admin_station_archive(
    slug: str,
    station_slug: str,
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        cur = conn.execute(
            "UPDATE station SET status = 'archived' WHERE slug = ?",
            (station_slug,),
        )
        if not cur.rowcount:
            raise HTTPException(status_code=404)
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/{slug}/stations?notice=archived", status_code=303
    )


# ── Settings ────────────────────────────────────────────────────────────────


@app.get("/admin/{slug}/settings", name="admin_settings")
async def admin_settings(
    request: Request,
    slug: str,
    notice: str | None = None,
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        upload_notifications_on = settings_store.upload_notifications_enabled(conn)
    finally:
        conn.close()

    return _admin_render(
        request,
        "admin/settings.html",
        active="settings",
        admin_slug=slug,
        page_title="Ajustes · ReFrame",
        notice=notice,
        thresholds={
            "min_resolution_long_edge": config.settings.min_resolution_long_edge,
            "blur_laplacian_threshold": config.settings.blur_laplacian_threshold,
            "feature_match_min_matches": config.settings.feature_match_min_matches,
        },
        operational={
            "submissions_enabled": config.settings.submissions_enabled,
            "nearby_radius_km": config.settings.nearby_radius_km,
        },
        upload_notifications_enabled=upload_notifications_on,
        smtp_configured=config.settings.smtp.configured,
        smtp_recipient=config.settings.smtp.recipient,
    )


@app.post(
    "/admin/{slug}/settings/upload-notifications",
    name="admin_settings_upload_notifications",
)
async def admin_settings_upload_notifications(
    slug: str,
    enabled: str | None = Form(default=None),
    authorization: str | None = Header(default=None),
):
    _admin_guard(slug, authorization)

    conn = db.connect()
    try:
        settings_store.set_upload_notifications_enabled(conn, enabled == "on")
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/{slug}/settings?notice=saved", status_code=303
    )


# ---------------------------------------------------------------------------
# Standalone marketing pages
# ---------------------------------------------------------------------------
#
# Two-segment routes (`/{lang}/locations`, `/{lang}/lugares`, etc.). They
# don't collide with the three-segment station catch-all, but are registered
# before it for clarity. The path segment is localised: a request whose
# segment doesn't match the URL's language 404s, so each page keeps one
# canonical URL.


@app.get("/{lang}/locations", include_in_schema=False)
@app.get("/{lang}/lugares", include_in_schema=False)
async def locations(request: Request, lang: str):
    if not _enabled(lang):
        raise HTTPException(status_code=404)
    segment = request.url.path.strip("/").rsplit("/", 1)[-1]
    if views.LOCATIONS_SEGMENT.get(lang) != segment:
        raise HTTPException(status_code=404)

    conn = db.connect()
    try:
        view = views.locations_view(conn, lang)
    finally:
        conn.close()

    return templates.TemplateResponse(
        request,
        "locations.html",
        {
            "lang": lang,
            "view": view,
            "toggle_href": views.locations_path(other_lang(lang)),
            **views.locations_meta(lang, str(request.base_url)),
        },
    )


# ---------------------------------------------------------------------------
# Community submission form — /host (v2)
# ---------------------------------------------------------------------------
#
# An expression-of-interest form. Gated by site.toml's `submissions.enabled`
# — a fork that doesn't want it sets the flag false and every route 404s.
# No DB table: a valid submission is emailed to Rural Hackers in a background
# task so a slow SMTP server never blocks the response.

_submissions_log = logging.getLogger("reframe.submissions")

# Minimal email format check: a non-space run, an `@`, another non-space run,
# a dot, and a final non-space run. Catches the common "x", "foo@bar",
# "@bar.com" mistakes without pretending to be RFC 5322. Anchored with \A…\Z
# (not ^…$) so a trailing newline can't slip past into the Reply-To header —
# `\s` already excludes interior CR/LF, but $ would otherwise match before a
# final newline. Belt-and-braces with the `.strip()` the caller applies.
_EMAIL_RE = re.compile(r"\A[^@\s]+@[^@\s]+\.[^@\s]+\Z")


def _check_host_access(request: Request, lang: str) -> None:
    if not _enabled(lang):
        raise HTTPException(status_code=404)
    if not config.settings.submissions_enabled:
        raise HTTPException(status_code=404)
    segment = request.url.path.strip("/").rsplit("/", 1)[-1]
    if views.HOST_SEGMENT.get(lang) != segment:
        raise HTTPException(status_code=404)


def _render_host(
    request: Request,
    lang: str,
    *,
    submitted: bool,
    error: str | None = None,
    form_email: str = "",
    form_location: str = "",
    form_notes: str = "",
    form_interests: list[str] | None = None,
):
    return templates.TemplateResponse(
        request,
        "host.html",
        {
            "lang": lang,
            "toggle_href": views.host_path(other_lang(lang)),
            "submitted": submitted,
            "error": error,
            "interests": views.SUBMISSION_INTERESTS,
            "form_action": views.host_path(lang),
            "form_email": form_email,
            "form_location": form_location,
            "form_notes": form_notes,
            "form_interests": form_interests or [],
            **views.host_meta(lang, str(request.base_url)),
        },
    )


@app.get("/{lang}/host", include_in_schema=False)
@app.get("/{lang}/acoger", include_in_schema=False)
async def host_form(request: Request, lang: str):
    _check_host_access(request, lang)

    return _render_host(request, lang, submitted=False)


@app.post("/{lang}/host", include_in_schema=False)
@app.post("/{lang}/acoger", include_in_schema=False)
async def host_submit(
    request: Request,
    background_tasks: BackgroundTasks,
    lang: str,
    email: str = Form(default=""),
    location: str = Form(default=""),
    notes: str = Form(default=""),
    interests: list[str] = Form(default=[]),
    website: str = Form(default=""),
):
    _check_host_access(request, lang)

    # Honeypot: a bot filled the hidden field. Show the same confirmation a
    # human sees — so the bot learns nothing — but send no email.
    if website.strip():
        _submissions_log.info("submission honeypot tripped — dropped")
        return _render_host(request, lang, submitted=True)

    email = email.strip()
    location = location.strip()
    error_key: str | None = None
    if not email or not location:
        error_key = "host.error.missing"
    elif not _EMAIL_RE.match(email):
        error_key = "host.error.invalid_email"

    if error_key is not None:
        return _render_host(
            request,
            lang,
            submitted=False,
            error=error_key,
            form_email=email,
            form_location=location,
            form_notes=notes,
            form_interests=interests,
        )

    background_tasks.add_task(
        send_submission,
        email=email,
        location=location,
        interests=interests,
        notes=notes,
    )

    return _render_host(request, lang, submitted=True)


# ---------------------------------------------------------------------------
# Station pages — registered LAST (three-segment catch-all, see note above)
# ---------------------------------------------------------------------------
#
# A station lives at `/{lang}/{location-slug}/{station-slug}`. Draft and
# archived stations still render here ("render but unlisted"); only the
# listings and sitemap filter on status. The URL's location segment must
# match the station's location, else 404 — this keeps URLs canonical.


@app.get("/{lang}/{location_slug}/{station_slug}", name="station")
async def station(request: Request, lang: str, location_slug: str, station_slug: str):
    if not _enabled(lang):
        raise HTTPException(status_code=404)

    conn = db.connect()
    try:
        row = views.fetch_station(conn, station_slug)
        if row is None or row["location_slug"] != location_slug:
            raise HTTPException(status_code=404)
        model = views.station_view(conn, row, lang)
    finally:
        conn.close()

    other = other_lang(lang)
    toggle_href = views.station_path(other, location_slug, station_slug)
    meta = views.station_meta(model, lang, str(request.base_url))

    return templates.TemplateResponse(
        request,
        "station.html",
        {
            "lang": lang,
            "station": model,
            "toggle_href": toggle_href,
            **meta,
        },
    )
