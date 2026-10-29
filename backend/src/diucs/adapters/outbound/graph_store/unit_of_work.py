"""The Neo4j unit of work (P06, DEC-012, DEC-083 item 9).

One unit of work opens one session and one explicit write transaction. Every repository it hands out
runs on that transaction and shares one ResourceStore. Repositories are built lazily from the
factories mapping, so a later task registers a repository by adding one entry to the mapping.

Commit and rollback: commit() commits once. Leaving the block without commit(), or with an
exception, rolls back and re-raises. A write that raises Conflict marks the unit of work refused,
and a refused unit of work never commits: commit() rolls back and raises Conflict. The session is
closed on every path.

The scope (TEN-002, DEC-132 item 4): a unit of work binds exactly one scope and keeps it. It reads
the scope bound in the context once, when it is entered, and wraps its transaction in a ScopedTx
that carries it; every repository and the resource store run on that ScopedTx, so rebinding the
context afterwards changes nothing for the unit. A second unit cannot be entered while one is open
in the same context (UnitOfWorkAlreadyOpen), and a unit is entered and left in the same task. The
claim is given back as soon as the unit finishes: commit, rollback, a refused commit, leaving the
block, or a failed open.
"""

import inspect
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, suppress
from types import TracebackType
from typing import Self, cast

from neo4j import AsyncDriver, AsyncManagedTransaction, AsyncSession, AsyncTransaction

from diucs.adapters.outbound.audit_neo4j.audit_log import Neo4jAuditLog
from diucs.adapters.outbound.audit_neo4j.outbox import Neo4jOutbox
from diucs.adapters.outbound.graph_store.booking_repository import Neo4jBookingRepository
from diucs.adapters.outbound.graph_store.capacity_repository import Neo4jCapacityRepository
from diucs.adapters.outbound.graph_store.case_repository import Neo4jCaseRepository
from diucs.adapters.outbound.graph_store.communication_repository import (
    Neo4jCommunicationRepository,
)
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.contact_store import Neo4jContactStore
from diucs.adapters.outbound.graph_store.credential_store import (
    Neo4jDeviceRegistry,
    Neo4jPinStore,
)
from diucs.adapters.outbound.graph_store.criteria_repository import Neo4jCriteriaRepository
from diucs.adapters.outbound.graph_store.driver import ScopedTx
from diucs.adapters.outbound.graph_store.flag_repository import Neo4jFlagRepository
from diucs.adapters.outbound.graph_store.idempotency_store import (
    Neo4jIdempotencyStore,
    Neo4jProcessedMessages,
)
from diucs.adapters.outbound.graph_store.link_token_repository import Neo4jLinkTokenRepository
from diucs.adapters.outbound.graph_store.person_repository import Neo4jPersonRepository
from diucs.adapters.outbound.graph_store.registration_repository import (
    Neo4jRegistrationRepository,
)
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.scheduled_work_repository import (
    Neo4jScheduledWorkRepository,
)
from diucs.adapters.outbound.graph_store.scope_list_repository import Neo4jScopeListRepository
from diucs.adapters.outbound.graph_store.service_repository import Neo4jServiceRepository
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditLog
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.event_bus import ScheduledWorkRepository
from diucs.application.ports.outbound.idempotency import ProcessedMessages
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
from diucs.application.tenancy import ScopeId, claim_unit, release_unit, scope_for_new_unit
from diucs.domain.errors import Conflict

RepositoryFactory = Callable[[AsyncManagedTransaction, ResourceStore], object]

# Every repository of the UnitOfWork port, built on the unit of work's transaction. A later task
# registers its repository by adding one entry here (P06 "Later tasks register new repositories").
DEFAULT_FACTORIES: dict[str, RepositoryFactory] = {
    "services": lambda tx, store: Neo4jServiceRepository(tx, store),
    "capacity": lambda tx, store: Neo4jCapacityRepository(tx, store),
    "bookings": lambda tx, store: Neo4jBookingRepository(tx, store),
    "cases": lambda tx, store: Neo4jCaseRepository(tx, store),
    "people": lambda tx, store: Neo4jPersonRepository(tx, store),
    "criteria": lambda tx, store: Neo4jCriteriaRepository(tx, store),
    "registrations": lambda tx, store: Neo4jRegistrationRepository(tx, store),
    "scope": lambda tx, store: Neo4jScopeListRepository(tx, store),
    "flags": lambda tx, store: Neo4jFlagRepository(tx, store),
    "communications": lambda tx, store: Neo4jCommunicationRepository(tx),
    "link_tokens": lambda tx, store: Neo4jLinkTokenRepository(tx),
    "scheduled_work": lambda tx, store: Neo4jScheduledWorkRepository(tx),
    "audit": lambda tx, store: Neo4jAuditLog(tx),
    "outbox": lambda tx, store: Neo4jOutbox(tx),
    "contacts": lambda tx, store: Neo4jContactStore(tx),
    "pins": lambda tx, store: Neo4jPinStore(tx),
    "devices": lambda tx, store: Neo4jDeviceRegistry(tx),
    "idempotency": lambda tx, store: Neo4jIdempotencyStore(tx),
    "processed": lambda tx, store: Neo4jProcessedMessages(tx),
}

_NOT_OPEN = "the unit of work is not open; use it inside 'async with'"
_NEW = "new"
_OPEN = "open"
_FINISHED = "finished"


class _WriteGuard:
    """Wraps one repository. A Conflict from any of its write methods marks the unit of work
    refused, so the unit of work can never commit that write (DEC-083 item 9). The Conflict is
    still raised to the caller, who may catch it; the commit is what is refused."""

    def __init__(self, target: object, on_conflict: Callable[[Conflict], None]) -> None:
        self._target = target
        self._on_conflict = on_conflict

    def __getattr__(self, name: str) -> object:
        attribute = getattr(self._target, name)
        if not inspect.iscoroutinefunction(attribute):
            return attribute
        on_conflict = self._on_conflict

        async def guarded(*args: object, **kwargs: object) -> object:
            try:
                return await attribute(*args, **kwargs)
            except Conflict as conflict:
                on_conflict(conflict)
                raise

        return guarded


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
    idempotency: IdempotencyStore
    processed: ProcessedMessages

    def __init__(
        self,
        driver: AsyncDriver | Neo4jConnection,
        factories: dict[str, RepositoryFactory] = DEFAULT_FACTORIES,
        clock: Clock | None = None,
    ) -> None:
        self._source = driver
        self._factories = factories
        self._clock = clock
        self._state = _NEW
        self._session_cm: AbstractAsyncContextManager[AsyncSession] | None = None
        self._tx: AsyncTransaction | None = None
        self._scoped: ScopedTx | None = None
        self._scope: ScopeId | None = None
        self._store: ResourceStore | None = None
        self._repositories: dict[str, object] = {}
        self._refused: Conflict | None = None

    @property
    def unit_scope(self) -> ScopeId | None:
        """The scope this unit opened under: the one bound when it was entered, None if none was.
        Fixed for the life of the unit and still readable after it has finished."""
        if self._state == _NEW:
            raise RuntimeError(_NOT_OPEN)
        return self._scope

    async def __aenter__(self) -> Self:
        if self._state != _NEW:
            raise RuntimeError("a unit of work is used once; open a new one")
        scope = scope_for_new_unit()
        claim_unit(self)
        try:
            session_cm = self._source.session()
            session = await session_cm.__aenter__()
            try:
                tx = await session.begin_transaction()
            except BaseException:
                await session_cm.__aexit__(None, None, None)
                raise
        except BaseException:
            release_unit(self)
            raise
        self._session_cm = session_cm
        self._tx = tx
        self._scope = scope
        self._scoped = ScopedTx(tx, scope)
        self._store = ResourceStore(cast(AsyncManagedTransaction, self._scoped), self._clock)
        self._state = _OPEN
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if self._state == _OPEN:
                self._state = _FINISHED
                if exc_type is None:
                    await self._require_tx().rollback()
                else:
                    with suppress(Exception):
                        await self._require_tx().rollback()
        finally:
            session_cm, self._session_cm = self._session_cm, None
            try:
                if session_cm is not None:
                    await session_cm.__aexit__(exc_type, exc, tb)
            finally:
                release_unit(self)

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)
        factory = self._factories.get(name)
        if factory is None:
            raise AttributeError(f"unit of work has no '{name}' repository registered")
        if self._state != _OPEN:
            raise RuntimeError(_NOT_OPEN)
        repository = self._repositories.get(name)
        if repository is None:
            repository = _WriteGuard(
                factory(
                    cast(AsyncManagedTransaction, self._require_scoped()), self._require_store()
                ),
                self._refuse,
            )
            self._repositories[name] = repository
        return repository

    async def commit(self) -> None:
        self._require_open()
        refused = self._refused
        if refused is not None:
            self._state = _FINISHED
            try:
                await self._require_tx().rollback()
            finally:
                release_unit(self)
            raise Conflict(
                "a write in this unit of work was refused, so nothing was committed"
            ) from refused
        await self._require_tx().commit()
        self._state = _FINISHED
        release_unit(self)

    async def rollback(self) -> None:
        if self._state == _FINISHED:
            raise RuntimeError("the unit of work is finished; open a new one")
        if self._state == _NEW:
            raise RuntimeError(_NOT_OPEN)
        self._state = _FINISHED
        try:
            await self._require_tx().rollback()
        finally:
            release_unit(self)

    def _refuse(self, conflict: Conflict) -> None:
        if self._refused is None:
            self._refused = conflict

    def _require_open(self) -> None:
        if self._state != _OPEN:
            raise RuntimeError(_NOT_OPEN)

    def _require_tx(self) -> AsyncTransaction:
        if self._tx is None:
            raise RuntimeError("the unit of work has no transaction; use it inside 'async with'")
        return self._tx

    def _require_scoped(self) -> ScopedTx:
        if self._scoped is None:
            raise RuntimeError("the unit of work has no transaction; use it inside 'async with'")
        return self._scoped

    def _require_store(self) -> ResourceStore:
        if self._store is None:
            raise RuntimeError("the unit of work has no resource store; use it inside 'async with'")
        return self._store


def neo4j_uow_factory(
    driver: AsyncDriver | Neo4jConnection,
    factories: dict[str, RepositoryFactory] = DEFAULT_FACTORIES,
    clock: Clock | None = None,
) -> UnitOfWorkFactory:
    """A factory that makes a fresh Neo4jUnitOfWork on each call."""
    return lambda: Neo4jUnitOfWork(driver, factories, clock)
