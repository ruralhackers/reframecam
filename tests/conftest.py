"""Phase 1+ test fixtures.

Each test runs against a temp data root with a fresh SQLite DB. Fixtures:

- `data_root` — a per-test tempdir with the `photos/` layout pre-created.
  `app.config.settings` is monkeypatched to point at it so `db`, `storage`,
  `seed`, and `photos` resolve paths to the temp tree.
- `db_conn` — an open connection to a fresh DB at `{data_root}/reframe.db`,
  schema applied. Closed and discarded after the test.
- `seeded_stations` — `db_conn` plus three seeded station rows. Returns the
  slug list.
- `insert_photo` — factory function that inserts a photo row with a chosen
  `captured_at`. Used by validator-adjacent tests in later phases too.
- `seed_reference_files` — factory that inserts photo rows backed by fake
  JPEGs (raw bytes; not decodable) under `photos/{slug}/` so
  `active_reference_set` can pick them up without actual image content.
- `make_jpeg` — factory that returns the bytes of a real, decodable JPEG
  matched to a given pattern. Used by Phase 5 tests so the validation
  pipeline has something it can decode and feature-match against.
- `seed_reference_jpeg` — inserts a photo row backed by a real JPEG under
  `photos/{slug}/` so the feature matcher has a reference set with content.
  Built on `make_jpeg`.
"""

from __future__ import annotations

import dataclasses
import io
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from app import config, db, seed, storage
from app.config import SmtpConfig


# ---------------------------------------------------------------------------
# Settings override
# ---------------------------------------------------------------------------


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect all path-resolving code at a per-test tempdir."""
    new_settings = dataclasses.replace(config.settings, data_root=tmp_path)
    monkeypatch.setattr(config, "settings", new_settings)

    storage.ensure_storage_layout([])

    return tmp_path


def _apply_site(monkeypatch: pytest.MonkeyPatch, new_site: config.SiteConfig) -> None:
    """Swap in a SiteConfig everywhere it's read.

    `app.main` binds `site` as a Jinja global once at import, so it must be
    patched alongside `config.site` for templates (e.g. the nav, OG tags) to
    reflect the change — not just the route guards that read `config.site` live.
    """
    from app import main

    monkeypatch.setattr(config, "site", new_site)
    monkeypatch.setitem(main.templates.env.globals, "site", new_site)


def _apply_submissions(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    """Flip `submissions_enabled` everywhere it's read.

    It lives in `config.settings` (env) and is mirrored as a Jinja global, so
    both must move together — the route guard reads `config.settings` live, the
    public templates (nav, setup section) read the global bound at import.
    """
    from app import main

    new_settings = dataclasses.replace(config.settings, submissions_enabled=enabled)
    monkeypatch.setattr(config, "settings", new_settings)
    monkeypatch.setitem(main.templates.env.globals, "submissions_enabled", enabled)


@pytest.fixture
def set_submissions(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[bool], None]:
    """Return a setter that flips `submissions_enabled` on/off for a test."""

    def _set(enabled: bool) -> None:
        _apply_submissions(monkeypatch, enabled)

    return _set


@pytest.fixture(autouse=True)
def _default_site_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic baseline so the suite doesn't depend on editable config.

    `data/site.toml` (brand name) and the `SUBMISSIONS_ENABLED` env var are both
    editable, so pin the brand name and submissions flag to known values here.
    Tests that exercise the disabled path call `set_submissions(False)`.

    Per-IP rate limiting is also disabled here: the suite fires many requests
    from the single `testclient` host and would otherwise trip the limiter.
    `test_security.py` re-enables it explicitly to exercise the limiter.
    """
    _apply_site(
        monkeypatch,
        dataclasses.replace(config.site, name=config.DEFAULT_SITE_NAME),
    )
    _apply_submissions(monkeypatch, True)
    monkeypatch.setattr(
        config,
        "settings",
        dataclasses.replace(config.settings, rate_limit_enabled=False),
    )


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_conn(data_root: Path) -> Iterator[sqlite3.Connection]:
    db.init()
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


SEEDED_SLUGS: tuple[str, ...] = (
    "bosque-comestible",
    "casa-do-pobo",
    "ies-ponte-caldelas",
)


@pytest.fixture
def seeded_stations(db_conn: sqlite3.Connection, data_root: Path) -> list[str]:
    """Insert three station rows by way of the real seed config.

    Going through `seed.run()` exercises the same code path the CLI uses, so
    the fixture doubles as integration coverage for the seed pipeline.
    """
    repo_seed = Path(__file__).resolve().parent.parent / "data" / "stations.toml"
    target = data_root / seed.SEED_FILENAME
    target.write_bytes(repo_seed.read_bytes())

    slugs = seed.run()
    assert sorted(slugs) == sorted(SEEDED_SLUGS)

    return slugs


# ---------------------------------------------------------------------------
# Photo / reference fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def insert_photo(db_conn: sqlite3.Connection) -> Callable[..., int]:
    """Return a factory that inserts a photo row and returns its rowid."""
    counter = {"n": 0}

    def _insert(
        station_slug: str,
        captured_at: str,
        *,
        client_token: str | None = None,
        filename: str | None = None,
        removed_at: str | None = None,
    ) -> int:
        counter["n"] += 1
        n = counter["n"]
        token = client_token or f"token-{station_slug}-{n}"
        name = filename or f"{captured_at[:10]}_{n:04x}.jpg"
        viewer_path = f"photos/{station_slug}/viewer/{name}"
        cur = db_conn.execute(
            """
            INSERT INTO photo (
                station_slug, captured_at, client_token, filename,
                viewer_path, thumb_path,
                width, height, removed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                station_slug,
                captured_at,
                token,
                name,
                viewer_path,
                f"photos/{station_slug}/thumb/{name}",
                1200,
                900,
                removed_at,
            ),
        )

        return int(cur.lastrowid)

    return _insert


@pytest.fixture
def seed_reference_files(
    db_conn: sqlite3.Connection, data_root: Path
) -> Callable[..., list[Path]]:
    """Plant fake admin-seed photos. References are now `photo` rows.

    Writes a stub byte string to data/photos/{slug}/{viewer,thumb}/{name},
    inserts a photo row, returns the viewer paths. The bytes are not real
    JPEGs — only suitable for tests that don't open them through cv2.
    For OpenCV-readable fixtures use `seed_reference_jpeg`.
    """

    counter = {"n": 0}

    def _seed(station_slug: str, count: int = 2) -> list[Path]:
        paths: list[Path] = []
        for i in range(1, count + 1):
            counter["n"] += 1
            n = counter["n"]
            name = f"seed-{n:04x}.jpg"
            data = b"\xff\xd8\xff stub-reference \xff\xd9"
            storage.save_photo(station_slug, name, data, "viewer")
            storage.save_photo(station_slug, name, data, "thumb")
            db_conn.execute(
                """
                INSERT INTO photo (
                    station_slug, captured_at, client_token, filename,
                    viewer_path, thumb_path, width, height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    station_slug,
                    f"2026-01-{i:02d} 09:00:00",
                    f"seed-{station_slug}-{n}",
                    name,
                    f"photos/{station_slug}/viewer/{name}",
                    f"photos/{station_slug}/thumb/{name}",
                    1200,
                    900,
                ),
            )
            paths.append(storage._local_photo_path(station_slug, name, "viewer"))

        return paths

    return _seed


# ---------------------------------------------------------------------------
# Phase 5 — real-image fixtures for the validation pipeline
# ---------------------------------------------------------------------------


def _make_pattern(width: int, height: int, *, seed_value: int = 0) -> bytes:
    """Build the bytes of a real JPEG with enough texture for ORB features.

    A flat colour patch yields zero ORB features and the matcher would
    short-circuit with no descriptors, which doesn't model real failure. We
    place a deterministic sprinkling of contrasting blobs and lines whose
    *positions* depend on `seed_value`, so two images with different seeds
    produce different ORB feature sets and won't pass the Lowe's-ratio
    match. Two images with the same seed produce identical pixels.
    """
    import random

    from PIL import Image, ImageDraw

    rng = random.Random(seed_value)
    image = Image.new("RGB", (width, height), (240, 235, 220))
    draw = ImageDraw.Draw(image)
    # Lay down ~600 contrasting filled rectangles + a handful of long lines.
    # 600 random shapes give ORB plenty of corners (well above the 1500
    # nfeatures cap), and the seeded RNG means same-seed → identical layout.
    for _ in range(600):
        x0 = rng.randint(0, width - 1)
        y0 = rng.randint(0, height - 1)
        w = rng.randint(8, 60)
        h = rng.randint(8, 60)
        r, g, b = rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)
        draw.rectangle([x0, y0, x0 + w, y0 + h], fill=(r, g, b))
    for _ in range(60):
        x0 = rng.randint(0, width - 1)
        y0 = rng.randint(0, height - 1)
        x1 = rng.randint(0, width - 1)
        y1 = rng.randint(0, height - 1)
        draw.line([x0, y0, x1, y1], fill=(0, 0, 0), width=rng.randint(1, 3))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=90)

    return buf.getvalue()


@pytest.fixture
def make_jpeg() -> Callable[..., bytes]:
    """Factory returning real JPEG bytes for a given pattern.

    `seed_value` controls the pattern: two images with the same `seed_value`
    feature-match; two with different seeds don't (any matches that survive
    the Lowe's-ratio check come from incidental tile collisions).
    """

    def _make(
        *,
        width: int = 1600,
        height: int = 1200,
        seed_value: int = 0,
    ) -> bytes:
        return _make_pattern(width, height, seed_value=seed_value)

    return _make


@pytest.fixture
def seed_reference_jpeg(
    db_conn: sqlite3.Connection,
    data_root: Path,
    make_jpeg: Callable[..., bytes],
) -> Callable[..., list[Path]]:
    """Plant one or more real admin-seed photos for `station_slug`.

    References are unified into the `photo` table: each seed inserts a
    photo row plus a viewer derivative on disk (real JPEG bytes the
    validator's OpenCV pipeline can read). Returns the viewer paths.
    """

    counter = {"n": 0}

    def _seed(station_slug: str, *, seed_value: int = 0, count: int = 1) -> list[Path]:
        paths: list[Path] = []
        for i in range(1, count + 1):
            counter["n"] += 1
            n = counter["n"]
            name = f"seed-{n:04x}.jpg"
            data = make_jpeg(seed_value=seed_value + i)
            storage.save_photo(station_slug, name, data, "viewer")
            storage.save_photo(station_slug, name, data, "thumb")
            db_conn.execute(
                """
                INSERT INTO photo (
                    station_slug, captured_at, client_token, filename,
                    viewer_path, thumb_path, width, height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    station_slug,
                    f"2026-01-{i:02d} 09:00:00",
                    f"refseed-{station_slug}-{n}",
                    name,
                    f"photos/{station_slug}/viewer/{name}",
                    f"photos/{station_slug}/thumb/{name}",
                    1600,
                    1200,
                ),
            )
            paths.append(storage._local_photo_path(station_slug, name, "viewer"))

        return paths

    return _seed


# ---------------------------------------------------------------------------
# SMTP — in-memory fake shared by the email-path tests (`test_pages`, the
# `/host` form; `test_email`, the send functions directly).
# ---------------------------------------------------------------------------


class FakeSMTP:
    """Stand-in for `smtplib.SMTP` — records sent messages instead of sending."""

    sent: list = []

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture
def configure_smtp(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list]:
    """Point SMTP at an in-memory `FakeSMTP` and return its (reset) outbox.

    Call with keyword overrides to vary the `SmtpConfig` — e.g.
    `configure_smtp(recipient="")` to exercise the not-configured no-op.
    """

    def _configure(**overrides) -> list:
        from app import email as email_mod

        smtp_kwargs = dict(
            host="smtp.test",
            port=587,
            recipient="hola@ruralhackers.test",
            from_address="bot@reframe.test",
            use_tls=True,
        )
        smtp_kwargs.update(overrides)
        configured = dataclasses.replace(
            config.settings, smtp=SmtpConfig(**smtp_kwargs)
        )
        monkeypatch.setattr(config, "settings", configured)
        FakeSMTP.sent = []
        monkeypatch.setattr(email_mod.smtplib, "SMTP", FakeSMTP)
        return FakeSMTP.sent

    return _configure
