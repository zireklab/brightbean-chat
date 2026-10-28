"""Organization-tier writes shared by the session views and the platform API."""

from typing import Any

from django.db import IntegrityError, transaction
from django.utils.translation import gettext

from apps.accounts.services import DEFAULT_WORKSPACE_NAME, get_or_create_user, provision_organization_and_workspace
from apps.billing.entitlements import PlanLimitError, check_can_add_workspace, organization_locked
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.members.roles import WorkspaceRole
from apps.organizations.models import Organization
from apps.workspaces.models import Workspace

MAX_WORKSPACE_NAME = 100


class WorkspaceError(ValueError):
    """A workspace could not be created. The message is shown to the operator."""

    def __init__(self, message: str, *, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


def create_workspace(org: Any, name: str, *, creator: Any = None) -> Workspace:
    """Create a workspace in ``org``; ``creator`` (if any) becomes its admin.

    The count and the insert are one critical section — see
    ``apps.billing.entitlements.organization_locked``.
    """
    name = (name or "").strip()[:MAX_WORKSPACE_NAME]
    if not name:
        raise WorkspaceError(gettext("A workspace needs a name."))
    with organization_locked(org):
        # Inside the lock so two requests cannot both pass the check; the
        # database constraint is the backstop for a writer that bypasses it.
        if Workspace.objects.for_org(org.pk).filter(name=name).exists():
            raise WorkspaceError(gettext("A workspace with that name already exists."), code="duplicate")
        try:
            check_can_add_workspace(org)
        except PlanLimitError as exc:
            raise WorkspaceError(str(exc), code=exc.code) from exc
        try:
            with transaction.atomic():
                workspace = Workspace.objects.create(organization=org, name=name)
        except IntegrityError as exc:
            raise WorkspaceError(gettext("A workspace with that name already exists."), code="duplicate") from exc
        if creator is not None:
            # Or nobody can configure the thing they just made.
            WorkspaceMembership.objects.create(user=creator, workspace=workspace, workspace_role=WorkspaceRole.ADMIN)
    return workspace


class OrganizationError(ValueError):
    """An organization could not be provisioned. ``code`` is machine-readable."""

    def __init__(self, message: str, *, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


def create_organization(
    *, name: str, owner_email: str, owner_name: str = "", workspace_name: str = "", external_id: str | None = None
) -> tuple[Organization, bool]:
    """Provision a tenant: the organization, its owner and a first workspace.

    Returns ``(organization, created)``. A repeated ``external_id`` finds the
    organization instead of making a second one, which is what makes a retried
    request safe. The owner is created if they have no account yet, and must not
    already belong to another organization (one per account).
    """
    name = (name or "").strip()[:100]
    if not name:
        raise OrganizationError(gettext("An organization needs a name."))
    external_id = (external_id or "").strip() or None
    if external_id and (found := Organization.objects.filter(external_id=external_id).first()):
        return found, False
    try:
        with transaction.atomic():
            owner, _ = get_or_create_user(owner_email, owner_name)
            if OrgMembership.objects.filter(user=owner).exists():
                raise OrganizationError(
                    gettext("That account already belongs to an organization."), code="other_organization"
                )
            org = provision_organization_and_workspace(
                owner,
                org_name=name,
                workspace_name=(workspace_name or "").strip()[:MAX_WORKSPACE_NAME] or DEFAULT_WORKSPACE_NAME,
                external_id=external_id,
            )
    except IntegrityError:
        # A concurrent request provisioned the same external_id first.
        if external_id and (found := Organization.objects.filter(external_id=external_id).first()):
            return found, False
        raise
    return org, True
