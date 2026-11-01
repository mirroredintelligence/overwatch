"""Outbound port: the groups of an organisation's own Entra directory (DEC-1317).

Every call is made with an application token for that directory (client credentials, our staff app,
the secret `entra-staff-client-secret`), so it can only touch what the organisation's administrator
consented to (DEC-1316). The adapter is Microsoft Graph (`adapters/outbound/entra_graph/groups.py`);
the tests use a fake directory. Nothing here is stored: a member is read from the directory when it
is shown and is not kept.

`GraphUnavailable` (the port of the consent check) is raised for a token refused, Graph down or
throttled, or a body that is not what Graph sends; its text names no secret, token or directory.
`GroupMissing` is raised when a group the caller names is not in the directory (it was deleted
there): the answer is clear and says nothing else.
"""

from dataclasses import dataclass
from typing import Protocol

from overwatch.application.ports.outbound.admin_consent import GraphUnavailable

__all__ = ["DirectoryMember", "EntraGroupDirectory", "GraphUnavailable", "GroupMissing"]


class GroupMissing(Exception):
    """A group the caller named is not in the directory (deleted there). Carries no name."""


@dataclass(frozen=True, slots=True)
class DirectoryMember:
    """A member as the directory shows it. Shown to the organisation's own administrator and not
    stored."""

    object_id: str
    display_name: str | None
    mail: str | None


class EntraGroupDirectory(Protocol):
    async def find_group(self, directory_id: str, name: str) -> str | None:
        """The object id of the one group with exactly this display name, or None. More than one
        group with the name is a refusal (`GraphUnavailable`): we never pick one."""
        ...

    async def create_group(self, directory_id: str, name: str, description: str) -> str:
        """A new security group (mail disabled, security enabled). Returns its object id."""
        ...

    async def group_name(self, directory_id: str, group_id: str) -> str:
        """The group's display name as the directory holds it. Raises GroupMissing."""
        ...

    async def assign_app_role(
        self, directory_id: str, service_principal_id: str, group_id: str, app_role_id: str
    ) -> bool:
        """Assign the group to the app role on the service principal. True when this call made the
        assignment, False when it was already there (idempotent). Raises GroupMissing."""
        ...

    async def find_user(self, directory_id: str, address: str) -> str | None:
        """The object id of the one user whose mail or user principal name is the address, or
        None. More than one is a refusal (`GraphUnavailable`)."""
        ...

    async def add_member(self, directory_id: str, group_id: str, user_id: str) -> bool:
        """True when added, False when already a member. Raises GroupMissing."""
        ...

    async def remove_member(self, directory_id: str, group_id: str, user_id: str) -> bool:
        """True when removed, False when not a member. Raises GroupMissing."""
        ...

    async def members(self, directory_id: str, group_id: str) -> tuple[DirectoryMember, ...]:
        """The group's direct user members. Raises GroupMissing."""
        ...
