"""The tenant directory on Neo4j (TEN-007). Stub: the behaviour comes with the implementation."""

from collections.abc import Mapping, Sequence
from typing import Any

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.application.ports.outbound.tenants import TenantLine
from diucs.domain.model.tenant import Tenant


def tenant_properties(tenant: Tenant) -> dict[str, Any]:
    raise NotImplementedError


def tenant_from_properties(props: Mapping[str, Any]) -> Tenant:
    raise NotImplementedError


class Neo4jTenantDirectory:
    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    async def get(self, tenant_id: str) -> Tenant | None:
        raise NotImplementedError

    async def by_inbound_number(self, to_number: str, account_sid: str) -> TenantLine | None:
        raise NotImplementedError

    async def by_account_sid(self, account_sid: str) -> TenantLine | None:
        raise NotImplementedError

    async def by_host(self, host: str) -> Tenant | None:
        raise NotImplementedError

    async def by_entra_directory(self, directory_id: str) -> Tenant | None:
        raise NotImplementedError

    async def list_active(self) -> Sequence[Tenant]:
        raise NotImplementedError

    async def active_tenant_ids(self) -> Sequence[str]:
        raise NotImplementedError
