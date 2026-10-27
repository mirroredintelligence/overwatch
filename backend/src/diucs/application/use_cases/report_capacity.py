"""ReportCapacity: record a new capacity figure for a service (U01).

Every reporting path (text, link, app, advisor phoned) ends here. The change, its audit entry, its
outbox messages and the idempotency record are written in one unit of work (DEC-084, DEC-090).
Rules: domain-rules 1.2 to 1.6 through compute_status; decisions DEC-094 for the choices the
prompt leaves open.
"""

from dataclasses import dataclass
from datetime import datetime

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import ReportFlagReason, ReportSource, Status
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile


@dataclass(frozen=True, slots=True)
class ReportCapacityCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    value: int
    source: ReportSource
    effective_at: datetime | None = None
    performer_role_id: str | None = None
    replaced_value: int | None = None
    flag: ReportFlagReason | None = None


@dataclass(frozen=True, slots=True)
class ReportCapacityResult:
    report_id: str
    status: Status
    status_changed: bool
    next_due: datetime | None
    replayed: bool = False


def record_report(
    uow: object,
    *,
    profile: ServiceProfile,
    report: CapacityReport,
    actor: Actor,
    now: datetime,
    ids: IdGenerator,
    send_echo: str | None,
    replaced_value: int | None,
) -> ReportCapacityResult:
    """Stub until U01 is built. U02 reuses this function."""
    raise NotImplementedError("U01: record_report is not built yet")


class ReportCapacity:
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

    async def execute(self, command: ReportCapacityCommand) -> ReportCapacityResult:
        """Stub until U01 is built."""
        raise NotImplementedError("U01: ReportCapacity.execute is not built yet")
