"""Organization-tier writes shared by the session views and the platform API."""

from typing import Any

from django.db import IntegrityError, transaction
from django.utils.translation import gettext

from apps.billing.entitlements import PlanLimitError, check_can_add_workspace, organization_locked
from apps.members.models import WorkspaceMembership
from apps.members.roles import WorkspaceRole
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
