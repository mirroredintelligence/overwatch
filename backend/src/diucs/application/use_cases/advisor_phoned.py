"""RecordAdvisorPhoned: an advisor phoned a service and wrote down what it said (U13). Red stub."""

from dataclasses import dataclass
from typing import Literal

from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.report_capacity import ReportCapacity, ReportCapacityResult

PhonedAnswer = Literal["accepting", "limited", "not-accepting"]


@dataclass(frozen=True, slots=True)
class RecordAdvisorPhonedCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    told: PhonedAnswer
    value: int | None
    case_id: str | None = None


def phoned_figure(told: str, value: int | None) -> int:
    raise NotImplementedError


class RecordAdvisorPhoned:
    def __init__(self, report_capacity: ReportCapacity, uow_factory: UnitOfWorkFactory) -> None:
        self._report_capacity = report_capacity
        self._uow_factory = uow_factory

    async def execute(self, command: RecordAdvisorPhonedCommand) -> ReportCapacityResult:
        raise NotImplementedError
