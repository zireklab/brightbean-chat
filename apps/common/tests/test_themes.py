"""The theme registry, ``{% theme_attrs %}`` and the registry/defaults check."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.test import Client, RequestFactory

from apps.common import themes
from apps.common.checks import check_themes

DUO = themes.Theme("duo", "Duo", ("light", "dark"))


@pytest.fixture
def duo(monkeypatch):
    """A second theme that has a dark palette, which the real registry does not yet."""
    monkeypatch.setitem(themes.THEMES, "duo", DUO)
    return DUO


def _user(**fields):
    return get_user_model().objects.create_user(email="themed@example.test", password="not-a-real-password", **fields)


class TestModes:
    def test_one_palette_is_one_mode(self):
        assert themes.THEMES["brightbean"].modes == ("light",)

    def test_both_palettes_add_system(self):
        """A theme offers one mode or all of them, so a mode select on screen
        always holds the stored choice and a save cannot silently drop it."""
        assert set(DUO.modes) == set(themes.COLOR_MODES)


class TestResolve:
    def test_blank_is_the_instance_default(self, settings):
        theme, scheme = themes.resolve("", "")

        assert theme.slug == settings.THEME_DEFAULT
        assert scheme == themes.COLOR_MODES[settings.COLOR_MODE_DEFAULT].scheme

    def test_an_unknown_theme_or_mode_falls_back_rather_than_raising(self, settings):
        """A theme can be unregistered while users still have it stored."""
        theme, scheme = themes.resolve("retired", "sepia")

        assert theme.slug == settings.THEME_DEFAULT
        assert scheme == "light"

    @pytest.mark.parametrize("mode", ["dark", "system"])
    def test_a_mode_the_theme_has_no_tokens_for_is_clamped(self, mode):
        """``system`` on a light-only theme would give dark native controls on light tokens."""
        _theme, scheme = themes.resolve("brightbean", mode)

        assert scheme == "light"

    @pytest.mark.parametrize(("mode", "scheme"), [("light", "light"), ("dark", "dark"), ("system", "light dark")])
    def test_a_supported_mode_maps_to_its_color_scheme(self, duo, mode, scheme):
        assert themes.resolve("duo", mode) == (duo, scheme)

    def test_a_broken_default_still_renders(self, settings):
        """This runs on the error pages; the check is what reports the typo."""
        settings.THEME_DEFAULT = "nope"
        settings.COLOR_MODE_DEFAULT = "sepia"

        theme, scheme = themes.resolve("", "")

        assert (theme.slug, scheme) == ("brightbean", "light")


@pytest.mark.django_db
class TestThemeAttrsTag:
    def _render(self, **context):
        return Template("{% load common_extras %}<html {% theme_attrs %}>").render(Context(context))

    def test_a_bare_context_gets_the_default(self):
        """The 500 path: no request, no processors."""
        assert self._render() == '<html data-theme="brightbean" style="color-scheme: light">'

    def test_an_anonymous_request_gets_the_default(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()

        assert 'data-theme="brightbean"' in self._render(request=request)

    def test_a_signed_in_user_gets_their_own_choice(self, duo):
        request = RequestFactory().get("/")
        request.user = _user(theme="duo", color_mode="system")

        assert self._render(request=request) == '<html data-theme="duo" style="color-scheme: light dark">'

    def test_a_404_for_a_signed_in_user_carries_their_choice(self, duo, client: Client):
        """The error layout does not extend base.html; it gets there by its own path."""
        client.force_login(_user(theme="duo", color_mode="dark"))

        response = client.get("/no-such-page")

        assert response.status_code == 404
        assert 'data-theme="duo" style="color-scheme: dark"' in response.content.decode()


class TestThemesCheck:
    def test_the_shipped_registry_and_defaults_pass(self):
        assert check_themes() == []

    @pytest.mark.parametrize(
        ("theme", "mode", "needle"),
        [
            ("nope", "light", "THEME_DEFAULT 'nope'"),
            ("brightbean", "sepia", "COLOR_MODE_DEFAULT 'sepia' is not a colour mode"),
            ("brightbean", "dark", "not supported by theme 'brightbean'"),
        ],
    )
    def test_a_default_that_would_be_silently_replaced_is_an_error(self, settings, theme, mode, needle):
        settings.THEME_DEFAULT = theme
        settings.COLOR_MODE_DEFAULT = mode

        (error,) = check_themes()

        assert error.id == "common.E007"
        assert needle in error.msg

    @pytest.mark.parametrize("palettes", [(), ("sepia",), ("light", "light")])
    def test_a_malformed_theme_is_an_error(self, monkeypatch, palettes):
        monkeypatch.setitem(themes.THEMES, "bad", themes.Theme("bad", "Bad", palettes))

        (error,) = check_themes()

        assert "'bad'" in error.msg
