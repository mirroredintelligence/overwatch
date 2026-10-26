"""The unit of work factory that every use-case and repository test uses (P06).

The tests run the real Neo4jUnitOfWork on the harness driver, so what a test asserts is what was
really committed. There is no in-memory unit of work (DEC-004).
"""

from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_uow_factory
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory


def uow_factory_on(driver: AsyncDriver, clock: Clock | None = None) -> UnitOfWorkFactory:
    """A factory of Neo4jUnitOfWork sessions on this driver, with the default repositories."""
    return neo4j_uow_factory(driver, clock=clock)
