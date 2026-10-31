"""RecordAdvisorPhoned: an advisor phoned a service and wrote down what it said (U13).

The advisor's answer becomes a capacity report with source advisor-phoned, through ReportCapacity,
so the report, its status change, its audit entry and its outbox messages are written in
ReportCapacity's one unit of work (U01). "Not accepting" stores 0. The answer itself (told, and the
case when one is given) goes into that same audit entry, so the record says what the service said,
not only the number. No echo is sent: an advisor's call is not a text to the service.

A case given with the call must exist in the tenant bound to the call; another tenant's case id, or
an unknown one, is refused as not found before any report is written (DEC-292). Who may name the
advisor-phoned source is decided by ReportCapacity (check_may_report, DEC-100): an advisor or a
lead, not a clinician. The U13 prompt also names clinicians; that conflict is recorded for the owner
in DEC-292 and is not decided here.
"""

from dataclasses import dataclass
from typing import Final, Literal

from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.report_capacity import (
    ReportCapacity,
    ReportCapacityCommand,
    ReportCapacityResult,
)
from diucs.domain.codes import ReportSource
from diucs.domain.errors import NotFound, ValidationFailed

PhonedAnswer = Literal["accepting", "limited", "not-accepting"]
ACCEPTING: Final = "accepting"
LIMITED: Final = "limited"
NOT_ACCEPTING: Final = "not-accepting"
PHONED_ANSWERS: Final = frozenset({ACCEPTING, LIMITED, NOT_ACCEPTING})


@dataclass(frozen=True, slots=True)
class RecordAdvisorPhonedCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    told: PhonedAnswer
    value: int | None
    case_id: str | None = None
    flag_id: str | None = None
    """The report flag this call resolves, when the shift lead phoned to check a flagged report
    (KI-287); it goes into the audit entry beside what the service told."""


def phoned_figure(told: str, value: int | None) -> int:
    """The number of referrals or beds the advisor was told. Accepting and limited need a whole
    number; not accepting takes none and stores 0. A value that does not match the answer is refused
    before anything is written, and the message never repeats the value."""
    if told not in PHONED_ANSWERS:
        raise ValidationFailed("told", "must be accepting, limited or not-accepting")
    if told == NOT_ACCEPTING:
        if value is not None:
            raise ValidationFailed("value", "is not used when the service is not accepting")
        return 0
    if value is None:
        raise ValidationFailed("value", "needs how many the service can take")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationFailed("value", "must be a whole number")
    return value


class RecordAdvisorPhoned:
    def __init__(self, report_capacity: ReportCapacity, uow_factory: UnitOfWorkFactory) -> None:
        self._report_capacity = report_capacity
        self._uow_factory = uow_factory

    async def execute(self, command: RecordAdvisorPhonedCommand) -> ReportCapacityResult:
        number = phoned_figure(command.told, command.value)
        detail: list[tuple[str, str]] = [("told", command.told)]
        if command.case_id is not None:
            await self._check_case(command.case_id)
            detail.append(("case_id", command.case_id))
        if command.flag_id is not None:
            detail.append(("flag_id", command.flag_id))
        return await self._report_capacity.execute(
            ReportCapacityCommand(
                idempotency_key=command.idempotency_key,
                actor=command.actor,
                service_id=command.service_id,
                value=number,
                source=ReportSource.ADVISOR_PHONED,
                send_echo=False,
                audit_detail=tuple(detail),
            )
        )

    async def _check_case(self, case_id: str) -> None:
        # Its own unit of work, closed before the report opens its own (one open unit at a time).
        async with self._uow_factory() as uow:
            if await uow.cases.get(case_id) is None:
                raise NotFound("no case with this id")
