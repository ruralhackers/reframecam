"""Runtime configuration.

Two sources:

- `Settings` — environment variables. Deployment-specific and secret-bearing
  (data root, admin credentials, validation thresholds, SMTP password).
- `SiteConfig` — `{DATA_ROOT}/site.toml`. Branding, enabled languages, and
  integration endpoints; checked in for the default build, edited per fork.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parent.parent

# Auto-load `.env` at the repo root for bare-metal dev (`uv run uvicorn …`).
# `override=False` so a real shell env (CI, systemd `EnvironmentFile=`, Docker
# Compose `env_file:`) still wins over the file.
load_dotenv(REPO_ROOT / ".env", override=False)

SITE_FILENAME = "site.toml"

# Languages the app ships full UI strings for. `SiteConfig.enabled_languages`
# is a subset of this — a fork that wants a new language adds it to both.
BUILTIN_LANGS: tuple[str, ...] = ("en", "es")

# Single source for the site.toml defaults that double as both the dataclass
# field default (missing-file branch) and the per-key `.get()` fallback.
DEFAULT_SITE_NAME = "ReFrame"
DEFAULT_SMTP_PORT = 587
DEFAULT_NEARBY_RADIUS_KM = 50.0


@dataclass(frozen=True)
class SmtpConfig:
    host: str = ""
    port: int = DEFAULT_SMTP_PORT
    username: str = ""
    use_tls: bool = True
    from_address: str = ""
    recipient: str = ""
    # Secret — never logged. Env-only, like the rest of the SMTP config.
    password: str = ""

    @property
    def configured(self) -> bool:
        """True when enough is set to actually send mail."""
        return bool(self.host and self.recipient)


@dataclass(frozen=True)
class Settings:
    data_root: Path
    storage_backend: str
    admin_slug: str
    admin_password: str
    # Validation thresholds (spec §7.3); env-overridable so Rural Hackers can
    # tune from real usage without a redeploy.
    min_resolution_long_edge: int
    blur_laplacian_threshold: float
    feature_match_min_matches: int
    # Path the borderline-match logger writes to. Empty string → stdout via
    # the standard Python logging handler. Non-empty → a file (line-appended).
    borderline_log_path: str
    # Operational toggles / tuning — deploy-time, not fork branding (so env,
    # not site.toml). `submissions_enabled` gates the /host form; radius bounds
    # the "Nearby stations" section.
    submissions_enabled: bool
    nearby_radius_km: float
    # Per-IP rate limiting on the abuse-prone endpoints (admin auth, upload,
    # the /host form). On by default; set RATE_LIMIT_ENABLED=false to disable
    # (e.g. when a smarter limiter sits at the proxy / WAF layer).
    rate_limit_enabled: bool
    # SMTP config for the submission-form mailer. Env-only (not committed) —
    # the file would otherwise leak host/recipient/etc. in a public repo.
    smtp: SmtpConfig


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _load() -> Settings:
    # A var that is *present but empty* (`X=` in `.env`, or Docker Compose's
    # `${X:-}` when unset) bypasses os.environ.get's default, so read vars with
    # a real default via `... or "<default>"` — empty string means "use the
    # default" (applies to the numeric/path vars and STORAGE_BACKEND alike).
    data_root = Path(os.environ.get("DATA_ROOT") or (REPO_ROOT / "data")).resolve()

    return Settings(
        data_root=data_root,
        storage_backend=os.environ.get("STORAGE_BACKEND") or "local",
        admin_slug=os.environ.get("ADMIN_SLUG", ""),
        admin_password=os.environ.get("ADMIN_PASSWORD", ""),
        min_resolution_long_edge=int(os.environ.get("MIN_RESOLUTION_LONG_EDGE") or "800"),
        blur_laplacian_threshold=float(
            os.environ.get("BLUR_LAPLACIAN_THRESHOLD") or "100"
        ),
        feature_match_min_matches=int(
            os.environ.get("FEATURE_MATCH_MIN_MATCHES") or "8"
        ),
        borderline_log_path=os.environ.get("BORDERLINE_LOG_PATH", ""),
        submissions_enabled=_env_bool("SUBMISSIONS_ENABLED", False),
        nearby_radius_km=float(
            os.environ.get("NEARBY_RADIUS_KM") or str(DEFAULT_NEARBY_RADIUS_KM)
        ),
        rate_limit_enabled=_env_bool("RATE_LIMIT_ENABLED", True),
        smtp=SmtpConfig(
            host=os.environ.get("SMTP_HOST", ""),
            port=int(os.environ.get("SMTP_PORT") or str(DEFAULT_SMTP_PORT)),
            username=os.environ.get("SMTP_USERNAME", ""),
            use_tls=_env_bool("SMTP_USE_TLS", True),
            from_address=os.environ.get("SMTP_FROM_ADDRESS", ""),
            recipient=os.environ.get("SMTP_RECIPIENT", ""),
            password=os.environ.get("SMTP_PASSWORD", ""),
        ),
    )


settings = _load()


# ---------------------------------------------------------------------------
# Site configuration — site.toml
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiteConfig:
    name: str = DEFAULT_SITE_NAME
    footer_attribution: dict[str, str] = field(default_factory=dict)
    enabled_languages: tuple[str, ...] = ("en",)

    @property
    def default_language(self) -> str:
        """The default language — the first enabled one."""
        return self.enabled_languages[0]

    @property
    def multilingual(self) -> bool:
        """True when the visitor is offered a language choice."""
        return len(self.enabled_languages) > 1

    def attribution(self, lang: str) -> str:
        return self.footer_attribution.get(lang) or self.footer_attribution.get(
            self.default_language, ""
        )


def site_path() -> Path:
    return settings.data_root / SITE_FILENAME


def load_site_config(path: Path | None = None) -> SiteConfig:
    """Read `site.toml`. A missing file yields sensible English-only defaults."""
    target = path or site_path()
    if not target.is_file():
        return SiteConfig(footer_attribution={"en": ""})

    with target.open("rb") as fh:
        raw = tomllib.load(fh)

    site_section = raw.get("site", {})
    footer = site_section.get("footer", {})

    enabled = tuple(raw.get("languages", {}).get("enabled", ["en"]))
    # Keep only languages the app actually ships strings for, order preserved.
    enabled = tuple(lang for lang in enabled if lang in BUILTIN_LANGS) or ("en",)

    return SiteConfig(
        name=site_section.get("name", DEFAULT_SITE_NAME),
        # Read per-language footer copy dynamically so a new BUILTIN_LANGS
        # entry is picked up without editing this loader.
        footer_attribution={
            lang: footer.get(f"attribution_{lang}", "") for lang in BUILTIN_LANGS
        },
        enabled_languages=enabled,
    )


site = load_site_config()
