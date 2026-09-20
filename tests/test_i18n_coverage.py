"""The pilot i18n slice stays translatable.

Not a hunt for every hardcoded string in the product — most of templates/ is
still 100% English on purpose (see docs on the i18n rollout), so a repo-wide
check here would be permanently noisy. This only pins the files the pilot
slice already migrated: presence of `{% load i18n %}` / a gettext import is a
weak signal, but it is the one that would actually catch the regression that
matters — somebody reverting the tag while editing a string nearby.

# ponytail: presence-of-the-tag check only, not per-string coverage. Upgrade to
# a real extraction-diff check (`make i18n-extract` producing no *new* msgids
# outside an allowlist) once most of templates/ is migrated and a repo-wide
# check stops being dominated by files nobody has touched yet.
"""

import re
from pathlib import Path

from django.conf import settings

_LOAD_TAG = re.compile(r"\{%\s*load\s+([\w\s]+?)\s*%\}")

#: Every template the pilot slice (auth pages + app shell nav) migrated.
_I18N_TEMPLATES = [
    "base.html",
    "account/login.html",
    "account/signup.html",
    "partials/_app_sidebar.html",
    "partials/_sidebar_channels.html",
    "partials/_sub_nav.html",
    "accounts/settings.html",
    "accounts/preferences.html",
    "notifications/email/notification.html",
    "notifications/email/notification.txt",
    "members/email/invite.html",
    "members/email/invite.txt",
]

#: Every Python module the pilot slice put gettext/gettext_lazy copy in.
_I18N_MODULES = [
    "apps/common/context_processors.py",
    "apps/notifications/events.py",
    "apps/broadcasts/notifications.py",
    "apps/inbox/notifications.py",
    "apps/flows/starter.py",
    "apps/members/services.py",
]


def _loads_i18n(text: str) -> bool:
    return any("i18n" in tag.split() for tag in _LOAD_TAG.findall(text))


def test_every_pilot_template_loads_i18n():
    root = Path(settings.BASE_DIR) / "templates"
    missing = [name for name in _I18N_TEMPLATES if not _loads_i18n((root / name).read_text())]

    assert missing == [], f"these templates lost their {{% load i18n %}} tag: {missing}"


def test_every_pilot_module_imports_gettext():
    root = Path(settings.BASE_DIR)
    missing = [name for name in _I18N_MODULES if "gettext" not in (root / name).read_text()]

    assert missing == [], f"these modules lost their gettext/gettext_lazy import: {missing}"
