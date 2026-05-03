"""Settings (env-var) loader tests — `app.config._load`."""

from __future__ import annotations

import pytest

from app import config


def test_present_but_empty_env_vars_fall_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`X=` in `.env` (or Compose `${X:-}`) must not crash startup.

    A present-but-empty var bypasses os.environ.get's default; numeric / path
    reads treat the empty string as "use the default" rather than failing the
    type conversion. This is the "copy `.env.example` and run" path.
    """
    for name in (
        "DATA_ROOT",
        "STORAGE_BACKEND",
        "MIN_RESOLUTION_LONG_EDGE",
        "BLUR_LAPLACIAN_THRESHOLD",
        "FEATURE_MATCH_MIN_MATCHES",
        "SMTP_PORT",
        "SUBMISSIONS_ENABLED",
        "NEARBY_RADIUS_KM",
    ):
        monkeypatch.setenv(name, "")

    settings = config._load()

    assert settings.storage_backend == "local"
    assert settings.min_resolution_long_edge == 800
    assert settings.blur_laplacian_threshold == 100
    assert settings.feature_match_min_matches == 8
    assert settings.smtp.port == config.DEFAULT_SMTP_PORT
    # Empty DATA_ROOT must resolve to <repo>/data, not the current directory.
    assert settings.data_root == (config.REPO_ROOT / "data").resolve()
    # Operational settings: empty → safe defaults (off / 50 km).
    assert settings.submissions_enabled is False
    assert settings.nearby_radius_km == config.DEFAULT_NEARBY_RADIUS_KM


def test_submissions_and_radius_read_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUBMISSIONS_ENABLED", "true")
    monkeypatch.setenv("NEARBY_RADIUS_KM", "25")

    settings = config._load()

    assert settings.submissions_enabled is True
    assert settings.nearby_radius_km == 25.0


def test_submissions_default_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUBMISSIONS_ENABLED", raising=False)

    assert config._load().submissions_enabled is False
