"""Unit coverage for the `app.strings` resolution helpers.

`t()` and the month helpers are exercised incidentally through page rendering;
these tests pin the fallback chain and the 1–12 month indexing directly, since
they are the load-bearing bits of the i18n contract (spec §9.9).
"""

from __future__ import annotations

import pytest

from app import strings
from app.strings import MONTH_ABBR, MONTH_NAMES, STRINGS


def test_t_returns_value_for_requested_language() -> None:
    assert strings.t("html.lang", "es") == "es"
    assert strings.t("html.lang", "en") == "en"


def test_t_falls_back_to_english_for_unknown_language() -> None:
    # No table for "fr" → falls through to the English value.
    assert strings.t("html.lang", "fr") == STRINGS["en"]["html.lang"]


def test_t_falls_back_to_english_when_key_missing_in_language() -> None:
    # Inject a key that only exists in the English table, then ask for it in
    # Spanish — it should resolve via the en fallback rather than the bare key.
    key = "test.only_in_english"
    STRINGS["en"][key] = "English only"
    try:
        assert strings.t(key, "es") == "English only"
    finally:
        del STRINGS["en"][key]


def test_t_returns_bare_key_when_completely_missing() -> None:
    assert strings.t("totally.made.up.key", "en") == "totally.made.up.key"
    assert strings.t("totally.made.up.key", "es") == "totally.made.up.key"


def test_other_lang_flips_between_the_two() -> None:
    assert strings.other_lang("es") == "en"
    assert strings.other_lang("en") == "es"
    # Anything not "es" is treated as English-facing.
    assert strings.other_lang("fr") == "es"


@pytest.mark.parametrize("month", range(1, 13))
def test_month_name_covers_full_year(month: int) -> None:
    assert strings.month_name("en", month) == MONTH_NAMES["en"][month - 1]
    assert strings.month_name("es", month) == MONTH_NAMES["es"][month - 1]


@pytest.mark.parametrize("month", range(1, 13))
def test_month_abbr_covers_full_year(month: int) -> None:
    assert strings.month_abbr("en", month) == MONTH_ABBR["en"][month - 1]
    assert strings.month_abbr("es", month) == MONTH_ABBR["es"][month - 1]


def test_month_helpers_fall_back_to_default_lang() -> None:
    # An unknown language uses the DEFAULT_LANG (en) table rather than raising.
    assert strings.month_name("fr", 3) == MONTH_NAMES["en"][2]
    assert strings.month_abbr("fr", 3) == MONTH_ABBR["en"][2]
