"""QueryBoard: the read model behind the wall board and the exec view (U08).

Contract: docs/spec/contracts.md, "QueryBoard result". Stub for the red commit (DEC-010): the types
are final, the behaviour is not written yet.
"""

from dataclasses import dataclass
from datetime import datetime

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import ServiceCategory, Status
from diucs.domain.rules.pressure import Pressure


@dataclass(frozen=True, slots=True)
class QueryBoardQuery:
    actor: Actor


@dataclass(frozen=True, slots=True)
class BoardEntry:
    service_id: str
    name: str
    category: ServiceCategory
    status: Status
    effective_available: int | None
    over_by: int | None
    used: int | None
    established: int
    pending: int
    unit_label: str
    comment: str
    reported_at: datetime | None
    next_due_at: datetime | None
    was_due_at: datetime | None


@dataclass(frozen=True, slots=True)
class Board:
    entries: tuple[BoardEntry, ...]
    pressure: Pressure
    all_limited_or_worse: bool
    generated_at: datetime


class QueryBoard:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, query: QueryBoardQuery) -> Board:
        raise NotImplementedError
