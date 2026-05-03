"""Guard the hand-maintained design-token duplication.

The colour tokens live in TWO places that must stay in sync by hand (there is no
build step): `static/css/tokens.css` (the single canonical token set) and the
inlined critical `<style>` block in `templates/base.html` (first paint).

When they drift, the page paints the inlined value then shifts to the stylesheet
value after it loads — a FOUC. This test asserts that every custom property shared
between the two sources holds an identical value, so a future edit to one file
that forgets the other fails CI instead of shipping a flash.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKENS_CSS = REPO_ROOT / "static" / "css" / "tokens.css"
BASE_HTML = REPO_ROOT / "templates" / "base.html"

# `--name: value;` — value is everything up to the terminating semicolon, so
# comma-bearing values (rgb channels, shadows) are captured whole.
_DECL = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);")


def _tokens(text: str) -> dict[str, str]:
    """Extract custom-property declarations, values normalised for comparison.

    Whitespace is collapsed and hex is lower-cased so `#F4F4F2` and `#f4f4f2`,
    or `11, 33, 26` and `11,33,26`, compare equal — only genuine value drift
    should fail the test.
    """
    out: dict[str, str] = {}
    for name, value in _DECL.findall(text):
        normalised = re.sub(r"\s+", " ", value.strip()).lower()
        out[name] = normalised

    return out


def _style_block(html: str) -> str:
    """The inlined critical CSS — the only place base.html declares tokens."""
    match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert match, "expected an inlined <style> block in base.html"

    return match.group(1)


SOURCES = {
    "tokens.css": _tokens(TOKENS_CSS.read_text()),
    "base.html": _tokens(_style_block(BASE_HTML.read_text())),
}

# The (pair-of-sources) to compare, so the parametrised test names the files.
_PAIRS = [
    ("tokens.css", "base.html"),
]


@pytest.mark.parametrize("left, right", _PAIRS)
def test_shared_tokens_match(left: str, right: str) -> None:
    """Tokens declared in both sources must hold the same value."""
    a, b = SOURCES[left], SOURCES[right]
    mismatches = {
        name: (a[name], b[name])
        for name in a.keys() & b.keys()
        if a[name] != b[name]
    }

    assert not mismatches, (
        f"token values drift between {left} and {right}: {mismatches} — "
        "the three token sources must be kept in sync by hand (no build step)."
    )


def test_surface_alt_specifically_synced() -> None:
    """Regression guard for the surface-alt drift this test was written for."""
    values = {src: toks.get("--colour-surface-alt") for src, toks in SOURCES.items()}
    assert len(set(values.values())) == 1, (
        f"--colour-surface-alt differs across sources: {values}"
    )


def test_colour_tokens_are_present() -> None:
    """Sanity: the parser actually found the palette (guards a broken regex)."""
    for src, toks in SOURCES.items():
        colour_tokens = [name for name in toks if name.startswith("--colour-")]
        assert len(colour_tokens) >= 10, f"{src}: parsed too few colour tokens"
