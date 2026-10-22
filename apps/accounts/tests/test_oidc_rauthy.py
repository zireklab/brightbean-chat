"""Signing in through Rauthy: who may be created, and what they get.

End to end through allauth's own views. Only the three calls that leave the
process are replaced — the discovery document, the token exchange and the
userinfo fetch — so state, PKCE, the adapter and the ``user_signed_up`` receiver
all run for real.
"""

import copy
from types import SimpleNamespace
from typing import Any
from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from allauth.socialaccount.providers.openid_connect.views import OpenIDConnectOAuth2Adapter
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import Client
from django.urls import reverse

from apps.members.models import Invitation, OrgMembership
from apps.members.roles import OrgRole, WorkspaceRole
from apps.members.services import MembershipError, create_invitation
from apps.members.signals_keys import PENDING_INVITE_SESSION_KEY
from apps.organizations.models import Organization
from tests.support import create_user

ISSUER = "https://auth.example.test/auth/v1"
LOGIN = "/accounts/login/"
START = "/accounts/oidc/rauthy/login/"
CALLBACK = "/accounts/oidc/rauthy/login/callback/"
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/oidc/authorize",
    "token_endpoint": f"{ISSUER}/oidc/token",
    "userinfo_endpoint": f"{ISSUER}/oidc/userinfo",
    "jwks_uri": f"{ISSUER}/oidc/certs",
}


@pytest.fixture
def rauthy(settings: Any) -> None:
    """SOCIALACCOUNT_PROVIDERS is built from the env at import, so put the app
    into the dict. Deep-copied because pytest-django restores the attribute, not
    the nested object."""
    providers = copy.deepcopy(settings.SOCIALACCOUNT_PROVIDERS)
    providers["openid_connect"]["APPS"] = [
        {
            "provider_id": "rauthy",
            "name": "Zirek",
            "client_id": "bb",
            "secret": "s3cret",  # noqa: S105 - a fake credential
            "settings": {"server_url": ISSUER},
        }
    ]
    settings.SOCIALACCOUNT_PROVIDERS = providers
    settings.RAUTHY_CONFIGURED = True


def sign_in(client: Client, **claims: Any) -> Any:
    """Run the whole authorization-code round trip as the user Rauthy describes."""
    userinfo = {"sub": "sub-1", "email": "joiner@example.test", "email_verified": True, "name": "Jo Iner", **claims}
    with (
        mock.patch.object(OpenIDConnectOAuth2Adapter, "openid_config", DISCOVERY),
        mock.patch.object(OAuth2Client, "get_access_token", return_value={"access_token": "at"}),
        mock.patch.object(OpenIDConnectOAuth2Adapter, "_fetch_user_info", return_value=userinfo),
    ):
        started = client.post(START)
        assert started.status_code == 302
        query = parse_qs(urlparse(started["Location"]).query)
        assert query["code_challenge_method"] == ["S256"], "PKCE must be on"
        return client.get(CALLBACK, {"code": "c", "state": query["state"][0]})


def invite(tenancy: Any, email: str = "joiner@example.test") -> Invitation:
    return create_invitation(
        org=tenancy.organization,
        email=email,
        org_role=OrgRole.MEMBER,
        workspace_assignments=[{"workspace_id": str(tenancy.workspace.pk), "role": WorkspaceRole.AGENT.value}],
        invited_by=tenancy.owner,
    )


def hold(client: Client, invitation: Invitation) -> None:
    """What opening the invitation link does: park the token in the session."""
    assert client.get(reverse("accept_invite", kwargs={"token": invitation.raw_token})).status_code == 200


def orgs() -> int:
    return Organization.objects.count()


@pytest.mark.django_db
class TestTheButton:
    def test_absent_without_credentials(self, client: Client) -> None:
        assert b"Zirek" not in client.get(LOGIN).content

    def test_present_when_configured_and_google_is_not_dragged_in(self, client: Client, rauthy: None) -> None:
        body = client.get(LOGIN).content

        assert b"Continue with Zirek" in body
        assert b"Continue with Google" not in body


@pytest.mark.django_db
class TestNewIdentities:
    def test_no_invitation_means_no_account_and_no_organization(
        self, client: Client, rauthy: None, tenancy: Any
    ) -> None:
        before = orgs()

        response = sign_in(client)

        assert response.status_code == 200
        assert b"Sign up is closed" in response.content
        assert not SocialAccount.objects.exists()
        assert orgs() == before

    def test_an_invitation_with_a_verified_matching_address_joins_that_organization(
        self, client: Client, rauthy: None, tenancy: Any
    ) -> None:
        invitation = invite(tenancy)
        hold(client, invitation)
        before = orgs()

        response = sign_in(client)

        assert response.status_code == 302
        membership = OrgMembership.objects.get(user__email="joiner@example.test")
        assert membership.organization == tenancy.organization
        assert OrgMembership.objects.filter(user=membership.user).count() == 1
        assert orgs() == before, "an invited user must not get an organization of their own"
        assert SocialAccount.objects.get(provider="rauthy").uid == "sub-1"
        invitation.refresh_from_db()
        assert invitation.is_accepted
        assert client.get("/").status_code == 302
        assert orgs() == before, "ensure_provisioned must have nothing left to do"

    @pytest.mark.parametrize(
        "claims",
        [
            {"email_verified": False},
            {"email": "someone.else@example.test"},
            {"email_verified": None},
        ],
    )
    def test_an_unverified_or_different_address_is_refused(
        self, client: Client, rauthy: None, tenancy: Any, claims: dict[str, Any]
    ) -> None:
        hold(client, invite(tenancy))

        response = sign_in(client, **claims)

        assert b"Sign up is closed" in response.content
        assert not SocialAccount.objects.exists()
        assert not OrgMembership.objects.filter(user__email="someone.else@example.test").exists()

    def test_case_does_not_matter(self, client: Client, rauthy: None, tenancy: Any) -> None:
        hold(client, invite(tenancy))

        sign_in(client, email="Joiner@Example.Test")

        assert SocialAccount.objects.filter(provider="rauthy").exists()

    @pytest.mark.parametrize(
        ("failure", "shown"),
        [
            (MembershipError("No seats left."), b"No seats left."),
            (IntegrityError("duplicate key"), b"just created"),
        ],
    )
    def test_a_refused_invitation_leaves_nothing_behind(
        self, client: Client, rauthy: None, tenancy: Any, failure: Exception, shown: bytes
    ) -> None:
        """The seat is gone, or a twin request won, by the time the identity
        arrives. The user row must roll back with it: ``ensure_provisioned`` gives
        an organization to anyone signed in without one."""
        hold(client, invite(tenancy))
        before = orgs()

        with mock.patch("apps.accounts.adapters.accept_invitation", side_effect=failure):
            response = sign_in(client)

        assert response.status_code == 403
        assert shown in response.content
        assert not SocialAccount.objects.exists()
        assert not get_user_model().objects.filter(email="joiner@example.test").exists()
        assert orgs() == before
        assert PENDING_INVITE_SESSION_KEY in client.session, "a refusal must not cost the visitor the invitation"

    def test_an_expired_token_is_no_better_than_none(self, client: Client, rauthy: None, tenancy: Any) -> None:
        invitation = invite(tenancy)
        hold(client, invitation)
        Invitation.objects.filter(pk=invitation.pk).update(expires_at="2000-01-01T00:00:00Z")

        response = sign_in(client)

        assert b"Sign up is closed" in response.content
        assert not SocialAccount.objects.exists()


@pytest.mark.django_db
class TestKnownIdentities:
    def test_a_linked_identity_signs_in_without_an_invitation(self, client: Client, rauthy: None, tenancy: Any) -> None:
        user = tenancy.owner
        SocialAccount.objects.create(user=user, provider="rauthy", uid="sub-1")

        response = sign_in(client, email=user.email)

        assert response.status_code == 302
        assert client.session["_auth_user_id"] == str(user.pk)

    def test_a_local_account_with_the_same_address_is_told_the_way_out_and_not_taken_over(
        self, client: Client, rauthy: None, tenancy: Any
    ) -> None:
        """No auto-connect: ACCOUNT_EMAIL_VERIFICATION is optional, so a local
        account can hold an address its owner never proved. The visitor is told
        to sign in and connect, rather than dropped into a form that says the
        address is taken."""
        local = create_user("joiner@example.test")
        hold(client, invite(tenancy))

        response = sign_in(client)

        assert response.status_code == 403
        assert b"already exists" in response.content
        assert "_auth_user_id" not in client.session
        assert not SocialAccount.objects.filter(user=local).exists()


@pytest.mark.django_db
class TestTheSignupFormPath:
    """allauth's signup form lets the visitor edit the address. Nothing in the
    callback reaches the form once the checks above are in place, so ``save_user``
    is exercised directly with the form's data."""

    def _request(self, client: Client) -> Any:
        from django.test import RequestFactory

        request = RequestFactory().post("/accounts/3rdparty/signup/")
        request.session = client.session
        return request

    def _sociallogin(self, request: Any) -> Any:
        from allauth.socialaccount.adapter import get_adapter

        provider = get_adapter().get_provider(request, provider="rauthy")
        return provider.sociallogin_from_response(
            request, {"userinfo": {"sub": "sub-9", "email": "joiner@example.test", "email_verified": True}}
        )

    def test_an_edited_address_does_not_become_the_accounts_address(
        self, client: Client, rauthy: None, tenancy: Any
    ) -> None:
        from apps.accounts.adapters import SocialAccountAdapter

        hold(client, invite(tenancy))
        request = self._request(client)
        form = SimpleNamespace(cleaned_data={"email": "edited@example.test"})

        user = SocialAccountAdapter().save_user(request, self._sociallogin(request), form=form)

        assert user.email == "joiner@example.test", "the provider-verified address wins over the form's"
        assert OrgMembership.objects.get(user=user).organization == tenancy.organization

    def test_a_mismatch_is_refused_whatever_allauth_does_with_the_address(
        self, client: Client, rauthy: None, tenancy: Any
    ) -> None:
        from allauth.core.exceptions import ImmediateHttpResponse

        from apps.accounts.adapters import SocialAccountAdapter

        hold(client, invite(tenancy, email="invited@example.test"))
        request = self._request(client)
        before = orgs()

        with pytest.raises(ImmediateHttpResponse) as caught:
            SocialAccountAdapter().save_user(request, self._sociallogin(request))

        assert caught.value.response.status_code == 403
        assert not get_user_model().objects.filter(email="joiner@example.test").exists()
        assert not SocialAccount.objects.exists()
        assert orgs() == before


@pytest.mark.django_db
class TestTheSignalFailsLoudly:
    def test_a_rauthy_signup_without_a_membership_is_logged(self, rauthy: None, caplog: Any) -> None:
        from allauth.socialaccount.models import SocialAccount as Account

        from apps.accounts.signals import provision_on_signup

        user = create_user("orphan@example.test")
        sociallogin = mock.Mock(account=Account(provider="rauthy", uid="x"))

        provision_on_signup(sender=type(user), request=None, user=user, sociallogin=sociallogin)

        assert "without an organization membership" in caplog.text
        assert not OrgMembership.objects.filter(user=user).exists(), "the receiver must not provision one"


class TestTheConfiguration:
    def test_disabled_without_all_three_values(self, settings: Any) -> None:
        assert settings.RAUTHY_CONFIGURED is False
        assert settings.SOCIALACCOUNT_PROVIDERS["openid_connect"]["APPS"] == []

    def test_login_still_requires_post_and_never_auto_connects(self, settings: Any) -> None:
        assert settings.SOCIALACCOUNT_LOGIN_ON_GET is False
        assert getattr(settings, "SOCIALACCOUNT_EMAIL_AUTHENTICATION", False) is False


class TestTheRedirectIsPermittedByCsp:
    @pytest.mark.parametrize(
        ("issuer", "origin"),
        [(ISSUER, "https://auth.example.test"), ("http://localhost:8443/auth/v1", "http://localhost:8443")],
    )
    def test_the_issuer_origin_is_what_form_action_gets(self, issuer: str, origin: str) -> None:
        from config.settings.base import csp_origin

        assert csp_origin(issuer) == origin
