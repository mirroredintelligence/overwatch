"""The unit of work factory that every use-case and repository test uses (P06).

The tests run the real Neo4jUnitOfWork on the harness driver, so what a test asserts is what was
really committed. There is no in-memory unit of work (DEC-004).
"""

from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.unit_of_work import RepositoryFactory, neo4j_uow_factory
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId


def uow_factory_on(driver: AsyncDriver, clock: Clock | None = None) -> UnitOfWorkFactory:
    """A factory of Neo4jUnitOfWork sessions on this driver, with the default repositories."""
    return neo4j_uow_factory(driver, clock=clock)


def tenant_uow_factory(
    driver: AsyncDriver,
    tenant: str | ScopeId,
    clock: Clock | None = None,
    *,
    factories: dict[str, RepositoryFactory] | None = None,
) -> UnitOfWorkFactory:
    """DEC-010 stub: the units bind whatever is ambient, not `tenant`."""
    if factories is None:
        return neo4j_uow_factory(driver, clock=clock)
    return neo4j_uow_factory(driver, factories=factories, clock=clock)
