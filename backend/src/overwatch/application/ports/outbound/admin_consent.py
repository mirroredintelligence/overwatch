"""Outbound ports of the admin-consent invitation (DEC-1316): the invite store, and the check that
our staff app is installed in the organisation's own Entra directory (Microsoft Graph).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from overwatch.domain.rules.admin_consent import AdminConsentInvite


class AdminConsentRepository(Protocol):
    """The bound tenant's invites. Every statement names the tenant; another tenant's invite is
    never seen."""

    async def add(self, invite: AdminConsentInvite) -> None: ...

    async def by_state_hash(self, state_hash: str) -> AdminConsentInvite | None: ...

    async def latest(self) -> AdminConsentInvite | None:
        """The tenant's newest invite, whatever its status, or None."""
        ...

    async def revoke_open(self, at: datetime) -> int:
        """Revoke every pending invite (a resend replaces them). Returns how many."""
        ...

    async def mark_consented(self, invite_id: str, at: datetime) -> bool:
        """Pending to consented, once. False when the invite was not pending any more."""
        ...

    async def set_reason(self, invite_id: str, reason: str) -> None:
        """Keep the words for why the last check did not confirm the consent."""
        ...


@dataclass(frozen=True, slots=True)
class AppInstallation:
    """What Graph says about our app in one directory. `installed` is True only when the app's
    service principal exists there; `granted_roles` are the application permissions (app role
    values) the directory has granted it. `reason` is plain words when not installed."""

    installed: bool
    granted_roles: frozenset[str] = frozenset()
    reason: str | None = None


class GraphUnavailable(Exception):
    """The check could not be made now (token refused, Graph down or throttled). The invite stays
    as it was. The text names no secret, token or directory."""


class AppInstallationCheck(Protocol):
    async def check(self, directory_id: str) -> AppInstallation:
        """Get an application token for the directory and read our service principal and its app
        role assignments there. Raises GraphUnavailable when it cannot be answered."""
        ...
