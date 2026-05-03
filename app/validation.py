"""Server-side upload pipeline (spec §7.3).

The pipeline runs in `POST /api/upload` and is the gatekeeper between an
incoming multipart upload and the photo table. Order is fixed by the spec:

    1. receive multipart                                    (cap 30 MB)
    2. idempotency check via X-Client-Token                 (DB UNIQUE)
    3. content-type detection
    4. HEIC → JPEG transcode                                (pillow-heif)
    5. apply EXIF orientation                               (bake into pixels)
    6. read EXIF DateTimeOriginal → captured_at             (§7.2)
    7. strip EXIF                                           (privacy, §7.7)
    8. OpenCV checks:
         a. resolution (long edge ≥ MIN_RESOLUTION_LONG_EDGE)
         b. blur (Laplacian variance ≥ BLUR_LAPLACIAN_THRESHOLD)
         c. feature match (ORB; ≥ FEATURE_MATCH_MIN_MATCHES against the
                           active reference set)
    9. on any failure → discard, return matching error code
   10. on success → derivatives (viewer 1200, thumb 400) → save_photo ×3 →
                    INSERT photo row.

Failed uploads are not persisted in any form (§7.3 discarded-on-failure).
EXIF is stripped before the canonical bytes hit disk (§7.7).
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import secrets
import sqlite3
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError

from app import config, photos, storage


pillow_heif.register_heif_opener()


# Decompression-bomb guard (§7.3 / security). The 30 MB byte cap below does
# *not* bound the decoded pixel count — a small, highly compressed file can
# expand into gigabytes of RGB and exhaust memory. Pillow's stock default
# (~89 MP) only *warns*; we set an explicit ceiling and, in `decode_to_image`,
# promote the warning to an error so an oversized image is rejected cleanly as
# a bad upload rather than crashing the worker. 100 MP comfortably clears
# current phone cameras (48–108 MP) while still capping decoded RGB at ~300 MB.
MAX_IMAGE_PIXELS = 100_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


# Failure codes — wire-compatible with Phase 4's client. Keep the §6.5 names
# the upload.js module already maps. The spec's §7.3 prose calls one of them
# `no_match`; we keep `doesnt_match` per the stable client contract — see the
# Phase 5 deviations log in CLAUDE.md.
ERR_WRONG_FILE_TYPE = "wrong_file_type"
ERR_DOESNT_MATCH = "doesnt_match"
ERR_TOO_BLURRY = "too_blurry"
ERR_SERVER_ERROR = "server_error"
# Size / resolution rejections used to share `wrong_file_type` ("we don't
# recognise this file"), which misdescribes a valid-but-oversized or
# valid-but-low-res photo. They now carry their own codes + microcopy.
ERR_TOO_LARGE = "too_large"
ERR_TOO_SMALL = "too_small"
# A station with no active reference set isn't a user error — it's an
# unconfigured station. Surface a "not ready yet" message instead of blaming
# the visitor with `doesnt_match`.
ERR_NOT_READY = "not_ready"


# Step 1 — multipart cap. The client (upload.js) compresses to ~800 KB; this
# upper bound matches the §6.4 client-side check so a HEIC bypass or a future
# protocol change can't smuggle a giant blob through.
MAX_UPLOAD_BYTES = 30 * 1024 * 1024

# Step 8 — derivative geometry (spec §7.3 step 10).
VIEWER_LONG_EDGE = 1200
THUMB_LONG_EDGE = 400
VIEWER_QUALITY = 85
THUMB_QUALITY = 80

# Step 6 — captured_at sane window (spec §7.2). The lower bound guards against
# cameras with reset clocks; the upper bound tolerates timezone drift.
CAPTURED_AT_MIN = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)


# ORB / BFMatcher parameters. ORB chosen per §7.3 (fast, patent-free, suits
# outdoor scenes). nfeatures = 1500 gives the matcher room above the default
# 500 without ballooning the per-upload cost. Lowe's-ratio test at 0.75 with
# the BFMatcher's knnMatch is the canonical pairing.
ORB_NFEATURES = 1500
ORB_LOWE_RATIO = 0.75


# Borderline-match logger — emits one line per accepted upload whose best
# match landed in the (threshold, threshold + LOG_BUFFER] range. Used by
# Rural Hackers to tune thresholds during the first weeks (§7.3).
LOG_BORDERLINE_BUFFER = 10  # i.e. the (8, 18] band with the default threshold.

_borderline_log = logging.getLogger("reframe.validation.borderline")
_pipeline_log = logging.getLogger("reframe.validation")


@dataclass(frozen=True)
class ValidationFailure(Exception):
    """Raised when one of the §7.3 checks rejects the upload.

    The `code` is one of the ERR_* constants above and round-trips into the
    `error` field of the JSON response Phase 4's client maps to §6.5
    microcopy. `detail` is for server-side logs only — never returned to the
    client.
    """

    code: str
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover — used in logs only
        return f"{self.code}: {self.detail}" if self.detail else self.code


@dataclass
class PipelineResult:
    """Outcome of a successful pipeline run, ready to write into the DB."""

    photo_id: int
    captured_at: dt.datetime
    filename: str
    viewer_url: str
    thumb_url: str


# ---------------------------------------------------------------------------
# Step 2 — idempotency
# ---------------------------------------------------------------------------


def lookup_by_client_token(
    conn: sqlite3.Connection, client_token: str
) -> sqlite3.Row | None:
    """Return the prior photo row for `client_token`, or None.

    A duplicate token shortcuts the pipeline — the same response is returned
    without re-validating or re-persisting. Spec §6.6 / §7.6.
    """
    cur = conn.execute(
        "SELECT * FROM photo WHERE client_token = ? LIMIT 1",
        (client_token,),
    )

    return cur.fetchone()


# ---------------------------------------------------------------------------
# Steps 3 + 4 — content-type detection and HEIC transcode
# ---------------------------------------------------------------------------


# Pillow's image format names for the formats we accept. Anything else fails
# step 3 with `wrong_file_type`. HEIC/HEIF are decoded by pillow-heif and
# transcoded to JPEG in-memory before the rest of the pipeline runs.
_ACCEPTED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "HEIF", "HEIC", "MPO"})
_HEIC_FORMATS: frozenset[str] = frozenset({"HEIF", "HEIC"})


def decode_to_image(data: bytes) -> Image.Image:
    """Open `data` with Pillow; fail with wrong_file_type if it isn't an image.

    HEIC files are accepted here — pillow-heif's opener has been registered
    at module import time so `Image.open` decodes them transparently. The
    caller still needs to detect HEIC explicitly (via `image.format`) to run
    the §7.3 step-4 transcode.
    """
    try:
        with warnings.catch_warnings():
            # Promote Pillow's decompression-bomb *warning* (pixels between
            # MAX_IMAGE_PIXELS and 2×) into an exception so it joins the
            # hard DecompressionBombError on the same rejection path.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            image.load()  # force decode so we surface decode errors here
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        # DecompressionBombError fires past 2×MAX_IMAGE_PIXELS; the promoted
        # warning fires between MAX and 2×. Both mean "too many pixels".
        raise ValidationFailure(
            ERR_TOO_LARGE, f"decompression bomb: {exc}"
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationFailure(ERR_WRONG_FILE_TYPE, f"decode failed: {exc}") from exc

    fmt = (image.format or "").upper()
    if fmt not in _ACCEPTED_FORMATS:
        raise ValidationFailure(ERR_WRONG_FILE_TYPE, f"unsupported format {fmt!r}")

    return image


# ---------------------------------------------------------------------------
# Step 5 — EXIF orientation
# ---------------------------------------------------------------------------


def apply_exif_orientation(image: Image.Image) -> Image.Image:
    """Bake the EXIF Orientation flag into pixels.

    `Pillow.ImageOps.exif_transpose` covers all eight orientation values and
    returns an image whose pixel data is upright; the orientation tag is
    cleared on the return value so a downstream `save` doesn't double-rotate.
    """
    return ImageOps.exif_transpose(image)


# ---------------------------------------------------------------------------
# Step 6 — captured_at resolution (§7.2)
# ---------------------------------------------------------------------------


# EXIF tag IDs — `DateTimeOriginal` and `DateTimeDigitized` both work; we
# prefer `DateTimeOriginal` and fall back to `DateTimeDigitized` if absent.
_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME_DIGITIZED = 36868


def resolve_captured_at(
    image: Image.Image, *, now: dt.datetime | None = None
) -> dt.datetime:
    """Read `DateTimeOriginal` from EXIF and apply the §7.2 sane-window rule.

    Returned `datetime` is naive UTC (no tzinfo) so it lines up with the
    DATETIME column type used elsewhere in the schema.
    """
    upload_time = (now or dt.datetime.now(dt.timezone.utc)).replace(microsecond=0)
    upper_bound = upload_time + dt.timedelta(days=1)
    candidate = _read_exif_datetime(image)

    if candidate is None:
        return _strip_tz(upload_time)

    candidate_aware = candidate.replace(tzinfo=dt.timezone.utc)
    if candidate_aware < CAPTURED_AT_MIN or candidate_aware > upper_bound:
        return _strip_tz(upload_time)

    return _strip_tz(candidate_aware)


def _read_exif_datetime(image: Image.Image) -> dt.datetime | None:
    try:
        exif = image.getexif()
    except Exception:  # pragma: no cover — Pillow returns {} for absent EXIF
        return None
    if not exif:
        return None

    raw = exif.get(_EXIF_DATETIME_ORIGINAL) or exif.get(_EXIF_DATETIME_DIGITIZED)
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("ascii", errors="replace")

    # EXIF format: "YYYY:MM:DD HH:MM:SS". Sub-second / timezone tags exist in
    # later EXIF revisions but aren't reliable on phone exports — and the
    # sane-window check tolerates the missing-precision either way.
    try:
        return dt.datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def _strip_tz(value: dt.datetime) -> dt.datetime:
    """Return a naive datetime in UTC clock terms (drops the tzinfo)."""
    if value.tzinfo is None:
        return value.replace(microsecond=0)

    return value.astimezone(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


# ---------------------------------------------------------------------------
# Steps 7 + 10 — encoding the canonical (EXIF-stripped) bytes + derivatives
# ---------------------------------------------------------------------------


def encode_jpeg(image: Image.Image, *, quality: int) -> bytes:
    """Encode `image` as a JPEG. EXIF is stripped — Pillow's `save` defaults
    don't preserve it unless explicitly asked, which honours §7.7.
    """
    rgb = _ensure_rgb(image)
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=quality, optimize=True)

    return buf.getvalue()


def make_derivative(image: Image.Image, long_edge: int) -> Image.Image:
    """Resize so the long edge is ≤ `long_edge`. Aspect ratio preserved."""
    width, height = image.size
    longest = max(width, height)
    if longest <= long_edge:
        return image.copy()

    scale = long_edge / longest
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))

    return image.resize(new_size, Image.Resampling.LANCZOS)


def _ensure_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA"):
        # Composite onto a white background so PNG/HEIC alpha doesn't end up
        # as black blocks in the JPEG output. Background colour matches the
        # cream surface of the rendered viewer well enough that the seam is
        # invisible at content scale.
        bg = Image.new("RGB", image.size, (255, 255, 255))
        bg.paste(image, mask=image.split()[-1])
        return bg

    return image.convert("RGB")


# ---------------------------------------------------------------------------
# Step 8 — OpenCV resolution / blur / feature-match
# ---------------------------------------------------------------------------


def check_resolution(image: Image.Image, *, min_long_edge: int) -> None:
    longest = max(image.size)
    if longest < min_long_edge:
        raise ValidationFailure(
            ERR_TOO_SMALL,
            f"resolution too low: longest edge {longest} < {min_long_edge}",
        )


def laplacian_variance(gray: np.ndarray) -> float:
    """Variance-of-Laplacian focus measure. Higher → sharper."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def check_blur(gray: np.ndarray, *, threshold: float) -> float:
    score = laplacian_variance(gray)
    if score < threshold:
        raise ValidationFailure(
            ERR_TOO_BLURRY,
            f"laplacian variance {score:.1f} < {threshold}",
        )

    return score


def to_gray(image: Image.Image) -> np.ndarray:
    """Convert a Pillow image to an OpenCV-compatible 8-bit grayscale array."""
    arr = np.asarray(_ensure_rgb(image))

    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


def feature_match_count(query_gray: np.ndarray, ref_gray: np.ndarray) -> int:
    """Count good ORB matches between two grayscale frames.

    Uses the Lowe's-ratio test: for each query descriptor, knnMatch returns
    the two nearest neighbours; a match is "good" iff the best is
    sufficiently better than the second-best (ratio < ORB_LOWE_RATIO). This
    is the textbook ORB/BFMatcher pairing and behaves well on outdoor scenes
    with shifting lighting.
    """
    orb = cv2.ORB_create(nfeatures=ORB_NFEATURES)
    kp_q, des_q = orb.detectAndCompute(query_gray, None)
    kp_r, des_r = orb.detectAndCompute(ref_gray, None)
    if des_q is None or des_r is None or len(kp_q) < 2 or len(kp_r) < 2:
        return 0

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    matches = matcher.knnMatch(des_q, des_r, k=2)

    good = 0
    for pair in matches:
        if len(pair) < 2:
            continue
        a, b = pair
        if a.distance < ORB_LOWE_RATIO * b.distance:
            good += 1

    return good


def check_match(
    query_gray: np.ndarray,
    reference_paths: Iterable[Path],
    *,
    threshold: int,
) -> int:
    """Match against the active reference set; return the best match count.

    Short-circuits on the first reference whose match count meets the
    threshold — no point matching against more references when one already
    accepts. Raises `ValidationFailure(ERR_DOESNT_MATCH)` only when every
    reference has been tried and none accepted.
    """
    best = 0
    for ref_path in reference_paths:
        ref_gray = _read_gray(ref_path)
        if ref_gray is None:
            # Skip unreadable reference files but log so a broken seed shows up.
            _pipeline_log.warning("skipping unreadable reference: %s", ref_path)
            continue
        count = feature_match_count(query_gray, ref_gray)
        if count > best:
            best = count
        if count >= threshold:
            return count

    raise ValidationFailure(
        ERR_DOESNT_MATCH,
        f"best match {best} < threshold {threshold}",
    )


def _read_gray(path: Path) -> np.ndarray | None:
    """Read a reference image as 8-bit grayscale.

    Falls back through Pillow when OpenCV's `imread` returns None — the seed
    file might be a HEIC, or might carry an EXIF orientation OpenCV ignores.
    """
    if not path.is_file():
        return None
    arr = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if arr is not None:
        return arr
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            return to_gray(im)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Step 10 — filename construction with collision retry
# ---------------------------------------------------------------------------


# 4 hex chars = 65 536 suffixes per date. With at most ~tens of uploads/day at
# MVP scale a collision is mathematically negligible; the retry below is the
# §7.3 safety net.
_FILENAME_SUFFIX_BYTES = 2
_FILENAME_RETRY_LIMIT = 8


def build_filename(captured_at: dt.datetime) -> str:
    """`{captured_at:YYYY-MM-DD}_{4hex}.jpg` per §7.3."""
    suffix = secrets.token_hex(_FILENAME_SUFFIX_BYTES)

    return f"{captured_at:%Y-%m-%d}_{suffix}.jpg"


def reserve_filename(
    captured_at: dt.datetime, station_slug: str
) -> str:
    """Pick a filename whose viewer-derivative path doesn't already exist.

    The local-backend collision check is filesystem-level — if the viewer
    derivative file for the proposed name is absent, we own the name. Only
    retries on the rare suffix collision; gives up after a small number of
    attempts and lets the caller surface a server_error.
    """
    for _ in range(_FILENAME_RETRY_LIMIT):
        candidate = build_filename(captured_at)
        if not storage.local_photo_path(station_slug, candidate, "viewer").exists():
            return candidate

    raise ValidationFailure(
        ERR_SERVER_ERROR,
        f"filename suffix collisions exhausted for {captured_at:%Y-%m-%d}",
    )


# ---------------------------------------------------------------------------
# Borderline-match logging (§7.3)
# ---------------------------------------------------------------------------


def log_borderline(
    *, photo_id: int, station_slug: str, match_count: int, threshold: int
) -> None:
    """Emit one structured log line if `match_count` is in the borderline band.

    Borderline band = (threshold, threshold + LOG_BORDERLINE_BUFFER]. A
    photo just inside the band passes validation but flags itself for human
    review; Rural Hackers can use the log to retune the threshold from real
    data without a redeploy. Format is parseable by `awk`/`jq` after a quick
    pre-process — kept human-readable on purpose.
    """
    if match_count <= threshold:
        return
    if match_count > threshold + LOG_BORDERLINE_BUFFER:
        return

    line = (
        f"BORDERLINE photo_id={photo_id} station={station_slug} "
        f"match_count={match_count} threshold={threshold}"
    )

    file_path = config.settings.borderline_log_path
    if file_path:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    else:
        _borderline_log.info(line)


# ---------------------------------------------------------------------------
# Pipeline driver
# ---------------------------------------------------------------------------


def process_upload(
    *,
    conn: sqlite3.Connection,
    station_slug: str,
    client_token: str,
    file_bytes: bytes,
    now: dt.datetime | None = None,
    skip_match: bool = False,
) -> PipelineResult:
    """Run the §7.3 pipeline end-to-end on `file_bytes`.

    Raises `ValidationFailure` on a check rejection (with one of the wire
    error codes); raises `ValidationFailure(ERR_SERVER_ERROR, ...)` on
    anything unexpected. The route handler maps both to the JSON response.

    `skip_match=True` bypasses the feature-match check (step 8c). Used by
    the admin-photo upload — the admin is trusted, and the bootstrap case
    (no existing photos) requires it (chicken-and-egg with the reference
    set the validator draws on). Blur + resolution still run.
    """
    settings = config.settings

    # Step 1: size cap.
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValidationFailure(
            ERR_TOO_LARGE, f"upload too large: {len(file_bytes)} bytes"
        )

    # Step 3 + Step 4: decode (HEIC handled by pillow-heif's registered opener).
    image = decode_to_image(file_bytes)
    fmt = (image.format or "").upper()
    if fmt in _HEIC_FORMATS:
        # Re-encode the decoded HEIC to JPEG in-memory; the rest of the
        # pipeline runs against a JPEG-canonical image.
        image = _ensure_rgb(image)

    # Step 5: bake orientation. After this the image's pixels are upright and
    # the EXIF Orientation tag (which Pillow's exif_transpose clears) won't
    # double-rotate any downstream save.
    image = apply_exif_orientation(image)

    # Step 6: captured_at — read EXIF before step 7 strips it.
    captured_at = resolve_captured_at(image, now=now)

    # Step 7: strip EXIF — handled implicitly by Pillow's `save` defaults
    # when we encode below. Nothing to do here.

    # Step 8a: resolution.
    check_resolution(image, min_long_edge=settings.min_resolution_long_edge)

    # Step 8b: blur (Laplacian variance on grayscale).
    gray = to_gray(image)
    check_blur(gray, threshold=settings.blur_laplacian_threshold)

    # Step 8c: feature-match against the active reference set. Skipped for
    # admin uploads (the admin establishes the reference set).
    if skip_match:
        match_count = 0
    else:
        reference_paths = photos.active_reference_set(conn, station_slug)
        if not reference_paths:
            # No active photos — Rural Hackers haven't seeded this station
            # yet. Fail closed for community uploads: refusing is safer
            # than accepting anything. Admin uploads use skip_match=True
            # to bootstrap.
            _pipeline_log.error(
                "no active reference set for station %s — rejecting upload",
                station_slug,
            )
            raise ValidationFailure(
                ERR_NOT_READY, f"no reference set for station {station_slug!r}"
            )

        match_count = check_match(
            gray, reference_paths, threshold=settings.feature_match_min_matches
        )

    # Step 10: derivatives. The viewer derivative is the canonical highest-
    # quality copy — every consumer (timelapse, hero, OG image, reference
    # matcher) reads from it.
    viewer_image = make_derivative(image, VIEWER_LONG_EDGE)
    thumb_image = make_derivative(image, THUMB_LONG_EDGE)
    viewer_bytes = encode_jpeg(viewer_image, quality=VIEWER_QUALITY)
    thumb_bytes = encode_jpeg(thumb_image, quality=THUMB_QUALITY)

    filename = reserve_filename(captured_at, station_slug)
    viewer_path = storage.save_photo(station_slug, filename, viewer_bytes, "viewer")
    thumb_path = storage.save_photo(station_slug, filename, thumb_bytes, "thumb")

    width, height = image.size

    # Persistence — single INSERT carries both the storage locators and the
    # idempotency token. The UNIQUE constraint on `client_token` is the
    # database-level guard against a race where two concurrent requests
    # both passed the lookup_by_client_token check.
    try:
        cur = conn.execute(
            """
            INSERT INTO photo (
                station_slug, captured_at, client_token, filename,
                viewer_path, thumb_path,
                width, height
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                station_slug,
                captured_at,
                client_token,
                filename,
                viewer_path,
                thumb_path,
                width,
                height,
            ),
        )
    except sqlite3.IntegrityError as exc:
        # Race lost — another request inserted the same client_token between
        # the lookup and this INSERT. Tidy up the just-written derivatives
        # and surface the prior row so the client still sees a consistent
        # outcome.
        storage.delete_photo(station_slug, filename)
        prior = lookup_by_client_token(conn, client_token)
        if prior is not None:
            return PipelineResult(
                photo_id=int(prior["id"]),
                captured_at=_parse_captured_at(prior["captured_at"]),
                filename=prior["filename"],
                viewer_url=storage.photo_url(station_slug, prior["filename"], "viewer"),
                thumb_url=storage.photo_url(station_slug, prior["filename"], "thumb"),
            )
        raise ValidationFailure(ERR_SERVER_ERROR, f"insert race: {exc}") from exc
    except Exception:
        # Any other persistence failure (disk full, locked/broken DB, …) leaves
        # the viewer/thumb derivatives written at :save_photo orphaned, with no
        # row to reference them. Remove them before the exception propagates to
        # the route handler's catch-all so a failed upload leaves nothing behind.
        storage.delete_photo(station_slug, filename)
        raise

    photo_id = int(cur.lastrowid)

    # The photo row is committed (autocommit). Borderline logging is a tuning
    # aid, not part of the upload's success contract — a log-write failure
    # (e.g. an unwritable BORDERLINE_LOG_PATH) must not turn a saved photo into
    # a server_error. Log and swallow.
    try:
        log_borderline(
            photo_id=photo_id,
            station_slug=station_slug,
            match_count=match_count,
            threshold=settings.feature_match_min_matches,
        )
    except Exception:
        _pipeline_log.exception(
            "borderline logging failed for photo_id=%s (photo saved)", photo_id
        )

    return PipelineResult(
        photo_id=photo_id,
        captured_at=captured_at,
        filename=filename,
        viewer_url=storage.photo_url(station_slug, filename, "viewer"),
        thumb_url=storage.photo_url(station_slug, filename, "thumb"),
    )


def _parse_captured_at(value) -> dt.datetime:
    """Normalise a `captured_at` row value back to a datetime.

    SQLite returns a `datetime` when PARSE_DECLTYPES picks up the DATETIME
    column type, but plain-string round-trips happen in tests; handle both.
    """
    if isinstance(value, dt.datetime):
        return value

    return dt.datetime.fromisoformat(str(value).replace("Z", ""))
