"""The unit of work port (P06, DEC-012).

One unit of work is one database transaction. Its repositories share that transaction. Use cases
write the change, the audit entry and the outbox messages inside one unit of work:

    async with uow_factory() as uow:
        ...
        await uow.commit()

Leaving the block without commit(), or with an exception, rolls back and re-raises. After commit()
or rollback() the unit of work cannot be used again. A write that raised Conflict is never
committed (DEC-083 item 9).
"""

from collections.abc import Callable
from typing import Protocol, Self

from diucs.application.ports.outbound.audit import AuditLog
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


class UnitOfWork(Protocol):
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

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    async def commit(self) -> None:
        """Commit every write of this unit of work at once. Refused (and rolled back) after a
        Conflict from any write in it."""
        ...

    async def rollback(self) -> None:
        """Discard every write of this unit of work."""
        ...


UnitOfWorkFactory = Callable[[], UnitOfWork]
