"""site.toml loader tests (Block C — config & i18n foundation)."""

from __future__ import annotations

from pathlib import Path

from app import config


def test_load_site_config_parses_branding_and_languages(tmp_path: Path) -> None:
    target = tmp_path / "site.toml"
    target.write_text(
        """
[site]
name = "ForkScope"

[site.footer]
attribution_en = "A fork project"
attribution_es = "Un proyecto derivado"

[languages]
enabled = ["en", "es"]
"""
    )
    site = config.load_site_config(target)

    assert site.name == "ForkScope"
    assert site.enabled_languages == ("en", "es")
    assert site.default_language == "en"
    assert site.multilingual is True
    assert site.attribution("en") == "A fork project"


def test_english_only_fork_is_not_multilingual(tmp_path: Path) -> None:
    target = tmp_path / "site.toml"
    target.write_text(
        """
[site]
name = "Solo"

[languages]
enabled = ["en"]
"""
    )
    site = config.load_site_config(target)

    assert site.enabled_languages == ("en",)
    assert site.multilingual is False
    assert site.default_language == "en"


def test_missing_site_toml_falls_back_to_defaults(tmp_path: Path) -> None:
    site = config.load_site_config(tmp_path / "absent.toml")

    assert site.name == "ReFrame"
    assert site.enabled_languages == ("en",)


def test_unknown_enabled_language_is_dropped(tmp_path: Path) -> None:
    target = tmp_path / "site.toml"
    target.write_text(
        """
[languages]
enabled = ["en", "gl", "es"]
"""
    )
    site = config.load_site_config(target)

    # "gl" has no built-in strings, so it's filtered out; order is preserved.
    assert site.enabled_languages == ("en", "es")
