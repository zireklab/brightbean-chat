"""The service-layer writes the platform API reuses: workspaces, direct members, system-issued keys."""

import pytest

from apps.accounts.services import provision_organization_and_workspace
from apps.api.services import ApiKeysError, issue_api_key
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.members.roles import OrgRole, WorkspaceRole
from apps.members.services import MembershipError, add_member_directly
from apps.organizations.models import Organization
from apps.organizations.services import WorkspaceError, create_workspace
from apps.workspaces.models import Workspace
from tests.support import create_user


@pytest.mark.django_db
class TestCreateWorkspace:
    def test_a_workspace_without_a_creator_has_no_members(self, tenancy):
        workspace = create_workspace(tenancy.organization, "  Support  ")

        assert workspace.name == "Support"
        assert not WorkspaceMembership.objects.filter(workspace=workspace).exists()

    def test_the_creator_becomes_its_admin(self, tenancy):
        workspace = create_workspace(tenancy.organization, "Sales", creator=tenancy.owner)

        membership = WorkspaceMembership.objects.get(workspace=workspace, user=tenancy.owner)
        assert membership.workspace_role == WorkspaceRole.ADMIN

    def test_a_duplicate_name_is_refused(self, tenancy):
        with pytest.raises(WorkspaceError) as exc:
            create_workspace(tenancy.organization, tenancy.workspace.name)

        assert exc.value.code == "duplicate"

    def test_a_blank_name_is_refused(self, tenancy):
        with pytest.raises(WorkspaceError):
            create_workspace(tenancy.organization, "   ")

    def test_the_session_view_still_creates_through_it(self, client_for, tenancy):
        response = client_for(tenancy.owner).post("/organization/workspaces/create/", {"name": "Via view"})

        assert response.status_code == 302
        assert Workspace.objects.filter(organization=tenancy.organization, name="Via view").exists()


@pytest.mark.django_db
class TestAddMemberDirectly:
    def test_it_writes_both_memberships_with_no_invitation(self, tenancy):
        user = create_user("direct@example.test")

        add_member_directly(
            tenancy.organization,
            user,
            OrgRole.MEMBER,
            [{"workspace_id": str(tenancy.workspace.pk), "role": WorkspaceRole.EDITOR}],
        )

        assert OrgMembership.objects.get(user=user).org_role == OrgRole.MEMBER
        assert WorkspaceMembership.objects.get(user=user).workspace_role == WorkspaceRole.EDITOR
        user.refresh_from_db()
        assert user.last_workspace_id == tenancy.workspace.pk

    def test_it_is_idempotent_and_leaves_an_existing_member_alone(self, tenancy):
        user = tenancy.user_for(WorkspaceRole.EDITOR)

        membership = add_member_directly(tenancy.organization, user, OrgRole.ADMIN, [])

        assert membership.org_role == OrgRole.MEMBER

    def test_nobody_is_added_as_an_owner(self, tenancy):
        with pytest.raises(MembershipError, match="owner"):
            add_member_directly(tenancy.organization, create_user("o@example.test"), OrgRole.OWNER, [])

    def test_a_workspace_of_another_organization_is_refused(self, tenancy, other_tenancy):
        with pytest.raises(MembershipError):
            add_member_directly(
                tenancy.organization,
                create_user("x@example.test"),
                OrgRole.MEMBER,
                [{"workspace_id": str(other_tenancy.workspace.pk), "role": WorkspaceRole.VIEWER}],
            )

    def test_an_account_in_another_organization_is_refused(self, tenancy, other_tenancy):
        with pytest.raises(MembershipError, match="already belongs"):
            add_member_directly(tenancy.organization, other_tenancy.owner, OrgRole.MEMBER, [])


@pytest.mark.django_db
class TestProvisionOnBehalf:
    def test_names_and_external_id_are_used(self):
        user = create_user("owner@example.test")

        org = provision_organization_and_workspace(user, org_name="Acme", workspace_name="Main", external_id="t-1")

        assert (org.name, org.external_id) == ("Acme", "t-1")
        assert Workspace.objects.get(organization=org).name == "Main"
        assert Organization.objects.filter(external_id="t-1").count() == 1


@pytest.mark.django_db
class TestSystemIssuedKey:
    def test_no_issuer_is_needed_and_the_key_carries_no_creator(self, tenancy):
        key = issue_api_key(workspace=tenancy.workspace, issuer=None, name="zirek", scopes=["read", "write", "erase"])

        assert key.raw_token.startswith("bb_")
        assert key.created_by is None
        assert key.scopes == ["erase", "read", "write"]

    def test_scope_and_name_validation_still_apply(self, tenancy):
        with pytest.raises(ApiKeysError):
            issue_api_key(workspace=tenancy.workspace, issuer=None, name="x", scopes=["root"])
        with pytest.raises(ApiKeysError):
            issue_api_key(workspace=tenancy.workspace, issuer=None, name=" ", scopes=["read"])
