"""Outbound port: the platform's own audit chain (TEN-084, DEC-528, audit F section 2.4 and 4.2).

A tenant's audit chain records what happened in that tenant, and the tenant can read it. The
platform's chain records what the platform's own people did across tenants: every opening, use and
ending of a support access, with the support person's opaque reference and the one tenant it was
for. Both chains are written for a support access, so the tenant sees what the operator did and the
operator keeps a record the tenant cannot change.

The entry names a person by the account reference of the operator directory (never a name) and a
tenant by its id. The real adapter is a hash chain in a platform scope (the same chain as TEN-017,
under a scope id that is no tenant's); that scope does not exist yet, so the only implementation
today is the recording fake in `adapters/testing/recording_platform_audit.py`.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PlatformAuditEntry:
    action: str
    principal_ref: str
    tenant_id: str
    access_id: str | None
    snapshot: dict[str, Any] | None
    at: datetime


class PlatformAudit(Protocol):
    async def append(self, entry: PlatformAuditEntry) -> None:
        """Add one entry to the platform chain. A failure is raised: the caller then does not let
        the access it was recording stand."""
        ...
