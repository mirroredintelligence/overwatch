"""The staff registry port (DEC-1327): which tenants a person holds a staff role in.

Two calls. `active_roles` is read before any tenant is bound, by the sign-in that has to find the
person's tenants. `replace_tenant` is run by the platform's sync for one tenant: it makes the given
records active and ends every other active record of that tenant, so a person the tenant's groups no
longer hold stops being offered. The records hold keyed account references only (never a name, an
address or a number).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from overwatch.domain.model.staff_registry import StaffRoleRecord


class StaffRegistry(Protocol):
    async def active_roles(self, practitioner_key: str) -> tuple[StaffRoleRecord, ...]:
        """The active roles of one person, in every tenant that lists them (none: no tenant)."""
        ...

    async def replace_tenant(
        self, tenant_id: str, records: Sequence[StaffRoleRecord], now: datetime
    ) -> None:
        """Make `records` active for this tenant and end the tenant's other active records."""
        ...
