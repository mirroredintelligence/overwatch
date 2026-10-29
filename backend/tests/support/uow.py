"""The unit of work factory that every use-case and repository test uses (P06).

The tests run the real Neo4jUnitOfWork on the harness driver, so what a test asserts is what was
really committed. There is no in-memory unit of work (DEC-004).

`tenant_uow_factory` (TEN-003) makes units that bind a chosen tenant while they open, so one test
can use a unit for tenant A and then one for tenant B without `as_tenant` blocks.
"""

from typing import Self

from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.unit_of_work import (
    DEFAULT_FACTORIES,
    Neo4jUnitOfWork,
    RepositoryFactory,
    neo4j_uow_factory,
)
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, bind_scope
from tests.support.tenancy import tenant_scope


async def ensure_audit_heads(driver: AsyncDriver, *tenants: str | ScopeId) -> None:
    """Give each tenant its audit chain head, as the product's start-up does (Container.startup,
    TEN-017): each tenant is bound in turn and `ensure_audit_head` runs under it. Appending without
    a head raises AuditHeadMissing, so a rig that writes as a tenant calls this for that tenant.
    Each binding is restored afterwards, so the caller's own binding (or none) is unchanged.

    Call it after the graph is wiped: a wipe removes the heads too. Idempotent."""
    for tenant in tenants:
        with bind_scope(tenant_scope(tenant)):
            await ensure_audit_head(driver)


def uow_factory_on(driver: AsyncDriver, clock: Clock | None = None) -> UnitOfWorkFactory:
    """A factory of Neo4jUnitOfWork sessions on this driver, with the default repositories. The
    units bind whatever scope is bound when they are entered: under the conftest, the run tenant."""
    return neo4j_uow_factory(driver, clock=clock)


class _TenantUnitOfWork(Neo4jUnitOfWork):
    """A unit of work that binds its tenant while it is being entered and nowhere else. The unit
    then keeps that scope (TEN-002's snapshot); the ambient binding after `__aenter__` returns is
    what it was before, and the nested-unit refusal still applies."""

    def __init__(
        self,
        driver: AsyncDriver,
        tenant: ScopeId,
        factories: dict[str, RepositoryFactory],
        clock: Clock | None,
    ) -> None:
        super().__init__(driver, factories, clock)
        self._tenant = tenant

    async def __aenter__(self) -> Self:
        with bind_scope(self._tenant):
            return await super().__aenter__()


def tenant_uow_factory(
    driver: AsyncDriver,
    tenant: str | ScopeId,
    clock: Clock | None = None,
    *,
    factories: dict[str, RepositoryFactory] | None = None,
) -> UnitOfWorkFactory:
    """A factory whose units bind `tenant` while they open. An invalid id, or a network scope, is
    refused when the factory is built (ScopeInvalid). `factories` adds a repository to the default
    ones, as `neo4j_uow_factory` does."""
    scope = tenant_scope(tenant)
    repositories = DEFAULT_FACTORIES if factories is None else factories
    return lambda: _TenantUnitOfWork(driver, scope, repositories, clock)
