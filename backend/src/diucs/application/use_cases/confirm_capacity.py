"""ConfirmCapacity: a Y that says the figure on record is still right (U02).

RED STUB (DEC-010): execute() writes nothing and returns a result no test expects, so every test
fails on its own assertion (or on a missing raise), not on an import or NotImplementedError.
"""

from dataclasses import dataclass
from datetime import datetime

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import ReportSource, Status


@dataclass(frozen=True, slots=True)
class ConfirmCapacityCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    source: ReportSource
    performer_role_id: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmCapacityResult:
    report_id: str
    status: Status
    status_changed: bool
    next_due: datetime | None
    confirmed_value: int
    replayed: bool = False


class ConfirmCapacity:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency

    async def execute(self, command: ConfirmCapacityCommand) -> ConfirmCapacityResult:
        return ConfirmCapacityResult(
            report_id="",
            status=Status.NOT_UPDATED,
            status_changed=False,
            next_due=None,
            confirmed_value=-1,
        )
