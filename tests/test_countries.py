"""Country lookup helpers."""

from __future__ import annotations

from app import countries


def test_country_name_resolves_known_code_per_language() -> None:
    assert countries.country_name("ES", "en") == "Spain"
    assert countries.country_name("ES", "es") == "España"
    assert countries.country_name("DE", "en") == "Germany"
    assert countries.country_name("DE", "es") == "Alemania"


def test_country_name_is_case_insensitive() -> None:
    assert countries.country_name("es", "en") == "Spain"
    assert countries.country_name(" es ".strip(), "es") == "España"


def test_country_name_falls_back_to_english_for_unknown_lang() -> None:
    # 'fr' isn't a populated language in `COUNTRIES`; fall back to en.
    assert countries.country_name("ES", "fr") == "Spain"


def test_country_name_returns_input_for_unknown_code() -> None:
    # Free-text values from a pre-migration row still render something.
    assert countries.country_name("Atlantis", "en") == "Atlantis"
    assert countries.country_name("", "en") == ""
    assert countries.country_name(None, "en") == ""


def test_country_choices_is_sorted_by_localised_name() -> None:
    choices_en = countries.country_choices("en")
    labels_en = [label for _, label in choices_en]
    assert labels_en == sorted(labels_en, key=str.casefold)

    choices_es = countries.country_choices("es")
    labels_es = [label for _, label in choices_es]
    assert labels_es == sorted(labels_es, key=str.casefold)


def test_country_choices_covers_all_codes() -> None:
    codes = {code for code, _ in countries.country_choices("en")}
    assert codes == set(countries.COUNTRIES.keys())
    assert "ES" in codes and "PT" in codes and "GB" in codes


def test_normalise_country_keeps_known_codes() -> None:
    assert countries.normalise_country("ES") == "ES"
    assert countries.normalise_country("es") == "ES"
    assert countries.normalise_country(" PT ") == "PT"


def test_normalise_country_maps_legacy_names() -> None:
    assert countries.normalise_country("Spain") == "ES"
    assert countries.normalise_country("España") == "ES"
    assert countries.normalise_country("portugal") == "PT"
    assert countries.normalise_country("United Kingdom") == "GB"


def test_normalise_country_falls_back_to_default() -> None:
    assert countries.normalise_country("") == countries.DEFAULT_COUNTRY
    assert countries.normalise_country(None) == countries.DEFAULT_COUNTRY
    assert countries.normalise_country("ZZ") == countries.DEFAULT_COUNTRY
    assert countries.normalise_country("Wonderland") == countries.DEFAULT_COUNTRY


def test_migrate_legacy_value_returns_code_for_known_name() -> None:
    assert countries.migrate_legacy_value("Spain") == "ES"
    assert countries.migrate_legacy_value("España") == "ES"
    assert countries.migrate_legacy_value("USA") == "US"


def test_migrate_legacy_value_is_idempotent_for_codes() -> None:
    # Already-coded values return None so the DB migration leaves them alone.
    assert countries.migrate_legacy_value("ES") is None
    assert countries.migrate_legacy_value("PT") is None


def test_migrate_legacy_value_returns_none_for_unknown() -> None:
    assert countries.migrate_legacy_value("Atlantis") is None
    assert countries.migrate_legacy_value("") is None
    assert countries.migrate_legacy_value(None) is None
