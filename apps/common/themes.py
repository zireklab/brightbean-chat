"""The theme registry: which themes exist and which colour modes each supports.

Two independent axes (docs/themes-roadmap.md): a **theme** is a palette, fonts
and radii, printed as ``data-theme`` on ``<html>``; a **mode** is light, dark or
system, printed as the ``color-scheme`` property, which is what every
``light-dark()`` token resolves against. *System* is not a third palette, it is
``color-scheme: light dark`` and lets the OS pick.

This module is the one list. The preferences view validates against it, the
``{% theme_attrs %}`` tag resolves through it, ``apps.common.checks`` checks it
and the instance defaults, and the tests read it rather than restating it.
"""

from dataclasses import dataclass
from typing import NamedTuple

from django.conf import settings
from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

#: The palettes a theme can ship tokens for.
PALETTES = ("light", "dark")


class ColorMode(NamedTuple):
    #: The ``color-scheme`` value printed on ``<html>``.
    scheme: str
    label: Promise


COLOR_MODES = {
    "light": ColorMode("light", _("Light")),
    "dark": ColorMode("dark", _("Dark")),
    "system": ColorMode("light dark", _("Match my system")),
}


@dataclass(frozen=True)
class Theme:
    slug: str
    #: A product name, so it is not translated.
    label: str
    #: The palettes this theme has tokens for, from :data:`PALETTES`. The first
    #: one is where an unsupported mode lands.
    palettes: tuple[str, ...]

    @property
    def modes(self) -> tuple[str, ...]:
        """Derived rather than declared: *system* means "either palette", so it
        exists exactly when both do. A theme therefore offers either one mode or
        all of them, and a stored mode is never missing from a select that is
        on screen."""
        return self.palettes + (("system",) if len(self.palettes) > 1 else ())


THEMES = {
    "brightbean": Theme("brightbean", "BrightBean", ("light",)),
}


def resolve(theme_slug: str, mode: str) -> tuple[Theme, str]:
    """A stored preference → the theme to render and its ``color-scheme`` value.

    Never raises, whatever the settings say: this runs on the error pages too.
    A bad instance default is reported by ``apps.common.checks``, not by a
    ``KeyError`` on every page.

    Blank or unknown falls back to the instance default. A mode the theme has no
    tokens for falls back to the default mode, or failing that the theme's first
    palette. Only here, at render time: the stored choice is left alone, so
    someone who picked *system* gets it the moment their theme grows a dark
    palette.
    """
    theme = THEMES.get(theme_slug) or THEMES.get(settings.THEME_DEFAULT) or next(iter(THEMES.values()))
    if mode not in theme.modes:
        mode = settings.COLOR_MODE_DEFAULT
    if mode not in theme.modes:
        mode = theme.modes[0]
    return theme, COLOR_MODES[mode].scheme
