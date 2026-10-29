"""Report flags raised when a capacity report breaks a rule (U07).

Stub for the red commit (DEC-010): it raises nothing, so the tests fail on their assertions.
"""

from datetime import datetime

from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.domain.codes import ReportFlagReason
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import ServiceProfile


async def raise_report_flags(
    uow: UnitOfWork,
    ids: IdGenerator,
    *,
    profile: ServiceProfile,
    report: CapacityReport,
    extra: ReportFlagReason | None,
    now: datetime,
) -> list[str]:
    return []
