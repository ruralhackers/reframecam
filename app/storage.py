"""Storage abstraction for station photos.

Spec §7.1 pins a four-function surface so the rest of the codebase doesn't
know whether bytes live on local disk, on Backblaze B2, or anywhere else:

    save_photo(station_slug, filename, data, kind) -> str
    read_photo(station_slug, filename, kind) -> bytes
    delete_photo(station_slug, filename) -> None
    photo_url(station_slug, filename, kind) -> str

`kind` is one of "viewer", "thumb".

Phase 1 ships the local backend only; backend dispatch is keyed off
`STORAGE_BACKEND` so a B2 implementation can slot in later without touching
call sites. `ensure_storage_layout(...)` is a backend-specific bootstrap
helper kept out of the four-function front-door interface — call sites
should not depend on it.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app import config


KINDS: tuple[str, ...] = ("viewer", "thumb")


# URL prefix the local backend serves under. Templates only ever see the
# URL strings these helpers return; the static mounts live in `app.main`.
LOCAL_URL_PREFIX = "/photos"


class StorageError(RuntimeError):
    """Raised when a storage operation hits an unrecoverable error."""


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown photo kind {kind!r}; expected one of {KINDS}")


def _check_backend() -> str:
    backend = config.settings.storage_backend
    if backend != "local":
        raise StorageError(
            f"storage backend {backend!r} not implemented; only 'local' is supported in MVP"
        )

    return backend


# ---------------------------------------------------------------------------
# Local-backend helpers
# ---------------------------------------------------------------------------


def _photos_root() -> Path:
    return config.settings.data_root / "photos"


def _local_photo_path(slug: str, filename: str, kind: str) -> Path:
    return _photos_root() / slug / kind / filename


def _relative_photo_path(slug: str, filename: str, kind: str) -> str:
    """Storage-locator string written into the photo table's *_path columns."""
    return f"photos/{slug}/{kind}/{filename}"


# ---------------------------------------------------------------------------
# Four-function abstraction (spec §7.1)
# ---------------------------------------------------------------------------


def save_photo(station_slug: str, filename: str, data: bytes, kind: str) -> str:
    """Persist `data` and return the storage-locator string for the DB row.

    The returned string is what the upload pipeline writes into the photo
    record's `viewer_path` / `thumb_path` columns. For the
    local backend it's a path relative to `data_root`; for a future B2
    backend it would be the object key. Either way it round-trips through
    `read_photo` and `photo_url`.
    """
    _check_kind(kind)
    _check_backend()

    target = _local_photo_path(station_slug, filename, kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    return _relative_photo_path(station_slug, filename, kind)


def read_photo(station_slug: str, filename: str, kind: str) -> bytes:
    _check_kind(kind)
    _check_backend()

    return _local_photo_path(station_slug, filename, kind).read_bytes()


def delete_photo(station_slug: str, filename: str) -> None:
    """Remove all derivatives. Missing files are silently tolerated.

    `kind` is intentionally not part of the signature: deletion is per-photo,
    not per-derivative — the admin takedown (§7.5) removes everything.
    """
    _check_backend()

    for kind in KINDS:
        path = _local_photo_path(station_slug, filename, kind)
        path.unlink(missing_ok=True)


def photo_url(station_slug: str, filename: str, kind: str) -> str:
    _check_kind(kind)
    _check_backend()

    return f"{LOCAL_URL_PREFIX}/{station_slug}/{kind}/{filename}"


# ---------------------------------------------------------------------------
# Backend bootstrap (kept out of the four-function abstraction surface)
# ---------------------------------------------------------------------------


def ensure_storage_layout(slugs: Iterable[str]) -> None:
    """Create the on-disk layout per spec §7.3 if absent.

    Called from app startup and from `python -m app.seed`. A no-op for any
    backend other than local; a B2 backend would have nothing analogous.
    """
    if config.settings.storage_backend != "local":
        return

    photos = _photos_root()
    for slug in slugs:
        for kind in KINDS:
            (photos / slug / kind).mkdir(parents=True, exist_ok=True)


def local_photo_path(station_slug: str, filename: str, kind: str) -> Path:
    """Backend-private accessor used by the validator's reference-set loader.

    Not part of the spec §7.1 surface — the local backend exposes filesystem
    paths so OpenCV can `imread` them directly without an extra copy through
    `read_photo`. A B2 backend would expose a download/cache helper instead.
    """
    _check_kind(kind)

    return _local_photo_path(station_slug, filename, kind)
