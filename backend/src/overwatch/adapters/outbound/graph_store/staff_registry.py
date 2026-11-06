"""The staff registry on Neo4j (DEC-1327): which tenants a person holds a staff role in.

The read is a global statement, pinned by digest (`Q-STAFF-ROLES-OF`): it matches registry nodes
only, by the person's account reference, and names no tenant, so a sign-in can run it before a
tenant is bound. The writes are the platform's and live in `tenant_registry.py`, the only module
that runs platform statements; this adapter delegates them there.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from neo4j import AsyncManagedTransaction

from overwatch.adapters.outbound.graph_store.connection import Neo4jConnection
from overwatch.adapters.outbound.graph_store.driver import run_global_query
from overwatch.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from overwatch.adapters.outbound.graph_store.tenant_registry import Neo4jStaffRoles
from overwatch.domain.codes import Role
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.staff_registry import StaffRoleRecord

_ROLES_OF = NamedQuery(
    id="Q-STAFF-ROLES-OF",
    cypher=(
        "MATCH (r:StaffRoleRecord {practitionerKey: $practitionerKey, status: 'active'}) "
        "RETURN properties(r) AS record"
    ),
    mode="read",
    scope="global",
)
REGISTRY.register(_ROLES_OF)


def record_from_properties(props: Any) -> StaffRoleRecord:
    """One record from a registry node's properties. A node the domain refuses is a registry fault:
    it raises, and the caller answers as for any failed read, never with a guessed tenant."""
    if type(props) is not dict:
        raise ValidationFailed("record", "must be a registry node")
    try:
        role = Role(str(props.get("role")))
    except ValueError:
        raise ValidationFailed("role", "must be a staff role") from None
    tenant_ref = props.get("tenantRef")
    practitioner_key = props.get("practitionerKey")
    if type(tenant_ref) is not str or type(practitioner_key) is not str:
        raise ValidationFailed("record", "must name its tenant and its practitioner")
    return StaffRoleRecord(
        tenant_id=tenant_ref,
        practitioner_key=practitioner_key,
        role=role,
        status="active",
    )


class Neo4jStaffRegistry:
    """The `StaffRegistry` port: the global read here, the platform writes delegated."""

    def __init__(self, connection: Neo4jConnection, roles: Neo4jStaffRoles) -> None:
        self._connection = connection
        self._roles = roles

    async def active_roles(self, practitioner_key: str) -> tuple[StaffRoleRecord, ...]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_global_query(tx, _ROLES_OF, practitionerKey=practitioner_key)

        rows = await self._connection.run_read(work)
        return tuple(record_from_properties(row["record"]) for row in rows)

    async def replace_tenant(
        self, tenant_id: str, records: Sequence[StaffRoleRecord], now: datetime
    ) -> None:
        await self._roles.replace_tenant(tenant_id, records, now)
