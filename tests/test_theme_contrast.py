"""WCAG contrast for the token pairs the UI actually puts together.

A token can be "defined" (test_theme_tokens.py) and still be an unreadable
combination once painted next to the surface it sits on. This is the other
half of the guard: a fixed list of (foreground, background) token pairs,
each checked at the WCAG 2.x AA threshold for its role.

The list is deliberately small and literal, not "every text token against
every surface token" — a token the file itself documents as fill-only or
ghost/placeholder (``--text-ghost``, ``--success-500``) is not a body-text
contrast claim anyone is making, so it stays out rather than fail on a
combination nobody uses that way. Phase 2c's OKLCH palette solver reads this
same PAIRS list when it derives dark values — one shared source of truth for
"what has to stay legible", not two lists that can drift apart.

Resolution already handles ``light-dark(a, b)``, split on balanced parens
rather than a naive comma split (a branch like
``color-mix(in srgb, var(--x) 6%, transparent)`` has its own commas). Today
every token is a single literal, so both branches resolve identically; from
Phase 2c onward this same code checks the real dark values with no changes
here.
"""

import re

import pytest

from tests.test_theme_tokens import _COMMENT, _VAR_DEF, TOKENS, _blank_comments

#: role -> minimum contrast ratio (WCAG 2.x AA). "text" is normal-size text
#: (1.4.3). Only role PAIRS ever uses today — add "non-text": 3.0 (UI
#: component / graphical object boundary, 1.4.11) back when a pair actually
#: needs it, not before: an entry with no PAIRS row exercising it is a
#: reviewer trap, not documentation (found in review of PR #7).
_MIN_RATIO = {"text": 4.5}

#: (foreground token, background token, role). Scoped to exactly what Phase
#: 2's "Done when" names — ``--text-*`` on ``--surface-*`` — not every token
#: that happens to carry colour. ``--text-on-fill`` (white on ``--primary``/
#: ``--error-500``) and the border tokens were tried here too: both already
#: fail their WCAG threshold on the *current, shipping* light palette
#: (``--text-on-fill`` on ``--primary`` is 2.80:1; ``--border-strong`` on
#: ``--surface-0`` is 1.26:1). That's real, but it's a pre-existing gap in
#: the light theme, not something Phase 2 (dark mode) introduces or is
#: scoped to fix — changing brand/border colours needs a design decision,
#: not a side effect of this guard. Left out on purpose; worth its own pass.
#:
#: The three prose-text tokens against the four generic content surfaces —
#: a deliberate small cross-product, not a grep of every real callsite (the
#: builder alone puts ``--text-tertiary`` on dozens of component classes,
#: each with its own effective background; auditing all of them belongs to
#: Phase 2d's per-app visual pass, not this list). Kept symmetric on purpose:
#: an uneven list invites the question "why does this token get fewer
#: surfaces than that one", with no good answer.
_PROSE_TEXT = ("--text-primary", "--text-secondary", "--text-tertiary")
_CONTENT_SURFACES = ("--surface-0", "--surface-page", "--surface-1", "--surface-2")
#: The full cross-product above is what the list *should* check. These two
#: combinations already fail 4.5:1 on the current, shipping light palette
#: (--text-tertiary is #78716C — 4.44:1 on --surface-page, 4.40:1 on
#: --surface-2, both just under the line) — another pre-existing gap the
#: same story as --text-on-fill/--border-strong above: real, found here,
#: not introduced by or in scope for Phase 2, and not this guard's call to
#: paper over by quietly dropping --text-tertiary from the cross-product.
_KNOWN_LIGHT_MODE_GAPS = {
    ("--text-tertiary", "--surface-page"),
    ("--text-tertiary", "--surface-2"),
}
PAIRS: list[tuple[str, str, str]] = [
    (text, surface, "text")
    for text in _PROSE_TEXT
    for surface in _CONTENT_SURFACES
    if (text, surface) not in _KNOWN_LIGHT_MODE_GAPS
]


def _parse_tokens() -> dict[str, str]:
    """``{name: raw value}`` for every ``--x: value;`` in tokens.css."""
    css = _blank_comments(TOKENS.read_text(), _COMMENT)
    values: dict[str, str] = {}
    for match in _VAR_DEF.finditer(css):
        name = match.group(1)
        start = match.end()
        end = css.find(";", start)
        values[name] = css[start:end].strip()
    return values


#: The fallback (``, ...``) is matched but discarded: every token this file
#: resolves is already covered by test_theme_tokens.py's "every var() is
#: defined" guard, so the fallback branch is never the one that's live.
_VAR_CALL = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,.*)?\)", re.DOTALL)


def _split_top_level(value: str) -> list[str]:
    """Split on commas that are not inside nested parens."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(value):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(value[start:i].strip())
            start = i + 1
    parts.append(value[start:].strip())
    return parts


def _light_dark_branches(value: str) -> tuple[str, str]:
    """``light-dark(a, b)`` -> ``(a, b)``; anything else -> ``(value, value)``."""
    match = re.match(r"^light-dark\((.*)\)$", value.strip(), re.DOTALL)
    if not match:
        return value, value
    light, dark = _split_top_level(match.group(1))
    return light, dark


def _resolve(name: str, tokens: dict[str, str], branch: int, seen: frozenset[str] = frozenset()) -> str:
    """Follow ``var()`` chains to a literal colour, picking one light-dark() branch."""
    assert name not in seen, f"circular var() reference: {name}"
    value = tokens[name]
    light, dark = _light_dark_branches(value)
    value = (light, dark)[branch]
    ref = _VAR_CALL.fullmatch(value.strip())
    if ref:
        return _resolve(ref.group(1), tokens, branch, seen | {name})
    return value.strip()


_HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(colour: str) -> float:
    if not _HEX_COLOUR.match(colour):
        raise ValueError(
            f"{colour!r} isn't a hex colour — the resolver only follows var()/"
            "light-dark() chains down to a hex literal. A PAIRS entry that "
            "resolves through color-mix()/rgb()/a named colour needs that "
            "format taught to _relative_luminance first, not a guess here."
        )
    hexdigits = colour.lstrip("#")
    if len(hexdigits) == 3:
        hexdigits = "".join(ch * 2 for ch in hexdigits)
    r, g, b = (int(hexdigits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    r, g, b = (_srgb_to_linear(c) for c in (r, g, b))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    l1, l2 = sorted((_relative_luminance(fg_hex), _relative_luminance(bg_hex)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


class TestContrastMath:
    """The PAIRS check only proves today's palette; these pin the formulas
    themselves, so a future refactor that breaks the maths doesn't just
    quietly change which offenders show up."""

    def test_black_on_white_is_the_maximum_ratio(self):
        assert _contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)

    def test_a_colour_against_itself_is_the_minimum_ratio(self):
        assert _contrast_ratio("#78716C", "#78716C") == pytest.approx(1.0)

    def test_argument_order_does_not_matter(self):
        assert _contrast_ratio("#000000", "#FFFFFF") == _contrast_ratio("#FFFFFF", "#000000")

    def test_an_unresolvable_colour_format_raises_a_clear_error(self):
        with pytest.raises(ValueError, match="hex colour"):
            _relative_luminance("rgb(0 0 0)")

    def test_a_plain_value_has_identical_light_and_dark_branches(self):
        assert _light_dark_branches("#FFFFFF") == ("#FFFFFF", "#FFFFFF")

    def test_light_dark_splits_only_on_the_outer_comma(self):
        # The light branch is itself a comma-bearing function call — a naive
        # split(",") would cut it in the wrong place.
        light, dark = _light_dark_branches("light-dark(color-mix(in srgb, red 6%, transparent), blue)")
        assert light == "color-mix(in srgb, red 6%, transparent)"
        assert dark == "blue"

    def test_var_with_a_fallback_resolves_through_the_referenced_name(self):
        tokens = {"--a": "var(--b, #000000)", "--b": "#FFFFFF"}
        assert _resolve("--a", tokens, branch=0) == "#FFFFFF"

    def test_resolve_follows_a_var_chain_into_a_light_dark_token(self):
        tokens = {"--text": "var(--neutral-900)", "--neutral-900": "light-dark(#1C1917, #F5F5F4)"}
        assert _resolve("--text", tokens, branch=0) == "#1C1917"
        assert _resolve("--text", tokens, branch=1) == "#F5F5F4"


#: The known-failing pairs from the PAIRS comment above, pinned to their
#: current ratio. This repo has GitHub issues disabled, so there's no
#: tracking-issue link to lean on as the forcing function (found in review
#: of PR #7) — a plain ``pytest.approx`` pin is the substitute: it fails
#: either way a token changes, not just when it gets worse, so nobody can
#: quietly drift these further or quietly fix them without updating this
#: test and docs/themes-roadmap.md's Phase 2a note together.
_KNOWN_LIGHT_MODE_GAP_RATIOS: list[tuple[str, str, float]] = [
    ("--text-on-fill", "--primary", 2.80),
    ("--text-on-fill", "--error-500", 3.76),
    ("--border-strong", "--surface-0", 1.26),
    ("--text-tertiary", "--surface-page", 4.44),
    ("--text-tertiary", "--surface-2", 4.40),
]


class TestKnownLightModeGaps:
    @pytest.mark.parametrize(("fg", "bg", "expected_ratio"), _KNOWN_LIGHT_MODE_GAP_RATIOS)
    def test_ratio_is_pinned(self, fg, bg, expected_ratio):
        tokens = _parse_tokens()
        ratio = _contrast_ratio(_resolve(fg, tokens, branch=0), _resolve(bg, tokens, branch=0))
        assert ratio == pytest.approx(expected_ratio, abs=0.01), (
            f"{fg} on {bg} moved from the pinned {expected_ratio}:1 to {ratio:.2f}:1 — a real "
            "change either way, not a flake. If it now clears 4.5:1 (or 3.0:1 for --border-strong), "
            "wire it into PAIRS/_PROSE_TEXT properly and delete it from here instead of just "
            "updating the number; if it's still failing, update the pin and check that "
            "docs/themes-roadmap.md's Phase 2a note still matches these ratios."
        )


class TestTextSurfaceContrast:
    def test_every_pair_meets_its_wcag_aa_threshold(self):
        tokens = _parse_tokens()
        offenders = []
        for fg, bg, role in PAIRS:
            min_ratio = _MIN_RATIO[role]
            for branch, label in ((0, "light"), (1, "dark")):
                fg_hex = _resolve(fg, tokens, branch)
                bg_hex = _resolve(bg, tokens, branch)
                ratio = _contrast_ratio(fg_hex, bg_hex)
                if ratio < min_ratio:
                    offenders.append(
                        f"{fg} on {bg} ({label}): {ratio:.2f}:1, needs {min_ratio}:1 ({fg_hex} vs {bg_hex})"
                    )

        assert not offenders, f"{len(offenders)} pair(s) fail WCAG AA:\n  " + "\n  ".join(offenders)
