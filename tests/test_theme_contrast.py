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

from tests.test_theme_tokens import _COMMENT, _VAR_DEF, TOKENS, _blank_comments

#: role -> minimum contrast ratio (WCAG 2.x AA). "text" is normal-size text
#: (1.4.3); "non-text" is a UI component / graphical object boundary (1.4.11).
_MIN_RATIO = {"text": 4.5, "non-text": 3.0}

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
PAIRS: list[tuple[str, str, str]] = [
    ("--text-primary", "--surface-0", "text"),
    ("--text-primary", "--surface-page", "text"),
    ("--text-primary", "--surface-1", "text"),
    ("--text-primary", "--surface-2", "text"),
    ("--text-secondary", "--surface-0", "text"),
    ("--text-secondary", "--surface-page", "text"),
    ("--text-secondary", "--surface-1", "text"),
    ("--text-tertiary", "--surface-0", "text"),
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


_VAR_CALL = re.compile(r"var\(\s*(--[\w-]+)\s*\)")


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


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_colour: str) -> float:
    hexdigits = hex_colour.lstrip("#")
    if len(hexdigits) == 3:
        hexdigits = "".join(ch * 2 for ch in hexdigits)
    r, g, b = (int(hexdigits[i : i + 2], 16) / 255 for i in (0, 2, 4))
    r, g, b = (_srgb_to_linear(c) for c in (r, g, b))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    l1, l2 = sorted((_relative_luminance(fg_hex), _relative_luminance(bg_hex)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


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
