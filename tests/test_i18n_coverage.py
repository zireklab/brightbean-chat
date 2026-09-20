"""The migrated i18n surface stays translatable.

Not a hunt for every hardcoded string in the product — most of templates/ is
still 100% English on purpose (see docs/i18n-roadmap.md for the phased plan),
so a repo-wide check here would be permanently noisy. This only pins the files
each landed phase (0: infra + pilot, 1: the Settings area) migrated: presence
of `{% load i18n %}` / a gettext import is a weak signal, but it is the one
that would actually catch the regression that matters — somebody reverting the
tag while editing a string nearby.

# ponytail: presence-of-the-tag check only, not per-string coverage. Upgrade to
# a real extraction-diff check (`make i18n-extract` producing no *new* msgids
# outside an allowlist) once most of templates/ is migrated (docs/i18n-roadmap.md's
# Phase 2) and a repo-wide check stops being dominated by files nobody has
# touched yet.
"""

import re
from pathlib import Path

from django.conf import settings

_LOAD_TAG = re.compile(r"\{%\s*load\s+([\w\s]+?)\s*%\}")

#: Every template a landed phase (0: auth + app shell nav, 1: Settings area)
#: migrated.
_I18N_TEMPLATES = [
    # Phase 0
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
    # Phase 1
    "organizations/settings.html",
    "organizations/workspaces.html",
    "organizations/billing.html",
    "members/_accept_invite_body.html",
    "members/_invite_expired_body.html",
    "members/accept_invite.html",
    "members/invite_expired.html",
    "members/list.html",
    "members/manage_workspaces.html",
    "workspaces/dashboard.html",
    "workspaces/settings.html",
    "api/keys_list.html",
    "api/key_created.html",
    "api/webhooks_list.html",
    "api/webhook_detail.html",
    "api/webhook_secret.html",
    # Phase 2a (channels)
    "channels/list.html",
    "channels/new.html",
    "channels/detail.html",
    "channels/secret.html",
    "channels/telegram_connect.html",
    "channels/email_connect.html",
    "channels/instagram_connect.html",
    "channels/messenger_connect.html",
    "channels/messenger_pages.html",
    "channels/sms_connect.html",
    "channels/sms_settings.html",
    "channels/whatsapp_connect.html",
    "channels/whatsapp_cost_hints.html",
    "channels/whatsapp_templates.html",
    "channels/whatsapp_template_form.html",
    "channels/unsubscribe_confirm.html",
    "channels/unsubscribe_done.html",
    "channels/_unsubscribe_body.html",
    "channels/_instagram_posts.html",
    "channels/_messenger_posts.html",
    "channels/_sms_segments.html",
    "channels/partials/_whatsapp_template_preview.html",
]

#: Every Python module a landed phase put gettext/gettext_lazy copy in.
_I18N_MODULES = [
    # Phase 0
    "apps/common/context_processors.py",
    "apps/notifications/events.py",
    "apps/broadcasts/notifications.py",
    "apps/inbox/notifications.py",
    "apps/flows/starter.py",
    "apps/members/services.py",
    # Phase 1
    "apps/organizations/views.py",
    "apps/workspaces/views.py",
    "apps/members/views.py",
    "apps/members/roles.py",
    "apps/billing/views.py",
    "apps/billing/services.py",
    "apps/billing/entitlements.py",
    "apps/api/views_keys.py",
    "apps/api/views_webhooks.py",
    "apps/api/services.py",
    "apps/api/events.py",
    "apps/api/models.py",
    "apps/common/validators.py",
    # Phase 2a (channels)
    "apps/channels/forms.py",
    "apps/channels/forms_whatsapp.py",
    "apps/channels/models.py",
    "apps/channels/views.py",
    "apps/channels/views_email.py",
    "apps/channels/views_instagram.py",
    "apps/channels/views_messenger.py",
    "apps/channels/views_sms.py",
    "apps/channels/views_telegram.py",
    "apps/channels/views_whatsapp.py",
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
