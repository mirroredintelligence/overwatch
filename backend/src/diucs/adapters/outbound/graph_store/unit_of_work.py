"""The Neo4j unit of work (P06, DEC-012, DEC-083 item 9).

One unit of work opens one session and one explicit write transaction. Every repository it hands out
runs on that transaction and shares one ResourceStore. Repositories are built lazily from the
factories mapping, so a later task registers a repository by adding one entry to the mapping.

Commit and rollback: commit() commits once. Leaving the block without commit(), or with an
exception, rolls back and re-raises. A write that raises Conflict marks the unit of work refused,
and a refused unit of work never commits: commit() rolls back and raises Conflict. The session is
closed on every path.
"""

from collections.abc import Callable
from typing import Self

from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.application.ports.outbound.audit import AuditLog
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import ScheduledWorkRepository
from diucs.application.ports.outbound.identity import ContactStore, DeviceRegistry, PinStore
from diucs.application.ports.outbound.messaging import CommunicationRepository
from diucs.application.ports.outbound.outbox import Outbox
from diucs.application.ports.outbound.repositories import (
    BookingRepository,
    CapacityRepository,
    CaseRepository,
    CriteriaRepository,
    FlagRepository,
    PersonRepository,
    RegistrationRepository,
    ScopeListRepository,
    ServiceRepository,
)
from diucs.application.ports.outbound.tokens import LinkTokenRepository
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory

RepositoryFactory = Callable[[AsyncManagedTransaction, ResourceStore], object]

DEFAULT_FACTORIES: dict[str, RepositoryFactory] = {}


class Neo4jUnitOfWork:
    """One session and one explicit transaction. Use it once: `async with uow:`, then commit."""

    services: ServiceRepository
    capacity: CapacityRepository
    bookings: BookingRepository
    cases: CaseRepository
    people: PersonRepository
    criteria: CriteriaRepository
    registrations: RegistrationRepository
    scope: ScopeListRepository
    flags: FlagRepository
    communications: CommunicationRepository
    link_tokens: LinkTokenRepository
    scheduled_work: ScheduledWorkRepository
    audit: AuditLog
    outbox: Outbox
    contacts: ContactStore
    pins: PinStore
    devices: DeviceRegistry

    def __init__(
        self,
        driver: AsyncDriver | Neo4jConnection,
        factories: dict[str, RepositoryFactory] = DEFAULT_FACTORIES,
        clock: Clock | None = None,
    ) -> None:
        self._source = driver
        self._factories = factories
        self._clock = clock

    async def __aenter__(self) -> Self:
        raise NotImplementedError("Neo4jUnitOfWork is not built yet (P06)")

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        raise NotImplementedError("Neo4jUnitOfWork is not built yet (P06)")

    def __getattr__(self, name: str) -> object:
        raise NotImplementedError("Neo4jUnitOfWork repositories are not built yet (P06)")

    async def commit(self) -> None:
        raise NotImplementedError("Neo4jUnitOfWork.commit is not built yet (P06)")

    async def rollback(self) -> None:
        raise NotImplementedError("Neo4jUnitOfWork.rollback is not built yet (P06)")


def neo4j_uow_factory(
    driver: AsyncDriver | Neo4jConnection,
    factories: dict[str, RepositoryFactory] = DEFAULT_FACTORIES,
    clock: Clock | None = None,
) -> UnitOfWorkFactory:
    """A factory that makes a fresh Neo4jUnitOfWork on each call."""
    return lambda: Neo4jUnitOfWork(driver, factories, clock)
