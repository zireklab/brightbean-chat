"""Platform keys: issuance, the commands, and ``PlatformKeyAuth`` on its own.

The HTTP surface that uses them arrives with the platform API's endpoints; here
the authenticator is called directly, which is the unit that decides who gets in.
"""

import logging

import pytest
from django.core.management import call_command
from django.test import RequestFactory

from apps.api import keys as key_tokens
from apps.api.auth import ApiKeyAuth, PlatformKeyAuth
from apps.api.models import PlatformApiKey
from apps.api.tests.conftest import make_key, make_platform_key


def request():
    return RequestFactory().get("/", secure=True)


@pytest.mark.django_db
class TestPlatformKeyAuth:
    def test_a_platform_key_authenticates_and_binds_no_workspace(self):
        key, token = make_platform_key()
        req = request()

        assert PlatformKeyAuth().authenticate(req, token) == key
        assert req.platform_key == key
        assert not hasattr(req, "workspace")

    def test_a_workspace_key_is_not_a_platform_key_and_the_reverse(self, tenancy):
        _, workspace_token = make_key(tenancy.workspace)
        _, platform_token = make_platform_key()

        assert PlatformKeyAuth().authenticate(request(), workspace_token) is None
        assert ApiKeyAuth().authenticate(request(), platform_token) is None

    def test_a_revoked_key_is_refused_at_once(self):
        key, token = make_platform_key()
        call_command("revoke_platform_key", str(key.pk))

        assert PlatformKeyAuth().authenticate(request(), token) is None

    def test_plain_http_is_refused(self):
        _, token = make_platform_key()

        assert PlatformKeyAuth().authenticate(RequestFactory().get("/"), token) is None

    def test_the_prefixes_do_not_parse_as_each_other(self):
        minted = key_tokens.mint(key_tokens.PLATFORM_TOKEN_PREFIX)

        assert key_tokens.parse(minted.plaintext) is None
        assert key_tokens.parse(minted.plaintext, key_tokens.PLATFORM_TOKEN_PREFIX) is not None
        assert key_tokens.parse(key_tokens.mint().plaintext, key_tokens.PLATFORM_TOKEN_PREFIX) is None


@pytest.mark.django_db
class TestCommands:
    def test_create_prints_the_token_once_and_stores_only_a_digest(self, capsys):
        call_command("create_platform_key", "--name", "zirek")

        token = capsys.readouterr().out.strip()
        assert token.startswith("bbp_")
        key = PlatformApiKey.objects.get()
        assert token not in {key.token_digest, key.lookup_prefix, key.name}
        assert key.matches(key_tokens.parse(token, key_tokens.PLATFORM_TOKEN_PREFIX)[0])

    def test_revoking_twice_is_harmless(self, capsys):
        key, _ = make_platform_key()

        call_command("revoke_platform_key", str(key.pk))
        call_command("revoke_platform_key", str(key.pk))

        assert "Already revoked" in capsys.readouterr().out

    def test_the_token_is_scrubbed_from_logs(self, caplog):
        _, token = make_platform_key()

        logging.getLogger("apps.api").error("echoed header: Bearer %s", token)

        assert token not in caplog.text
