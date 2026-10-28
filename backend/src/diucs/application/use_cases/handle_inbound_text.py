"""HandleInboundText (U05). DEC-010 stub: names and signatures only, no behaviour."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity
from diucs.application.use_cases.report_capacity import ReportCapacity

RECORDED: Final = "recorded"
CONFIRMED: Final = "confirmed"
LATE: Final = "late"
CONFIRM_LIMIT: Final = "confirm-limit"
RECHECK: Final = "recheck"
HELP: Final = "help"
DROPPED: Final = "dropped"
BOOKING_NOT_HANDLED: Final = "booking-not-handled"
STALE_FIGURE: Final = "stale-figure"
NEED_NUMBER: Final = "need-number"

CONFIRMABLE_FIGURE_AGE: Final = timedelta(hours=2)


@dataclass(frozen=True, slots=True)
class HandleInboundTextCommand:
    idempotency_key: str
    from_phone_hash: str
    text: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class HandleInboundTextResult:
    outcome: str
    service_ids: tuple[str, ...]
    replayed: bool = False


def figure_is_out_of_date(figure_as_of: datetime, prompt_sent_at: datetime) -> bool:
    raise NotImplementedError


class HandleInboundText:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        cache: Cache,
        report_capacity: ReportCapacity,
        confirm_capacity: ConfirmCapacity,
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: HandleInboundTextCommand) -> HandleInboundTextResult:
        raise NotImplementedError
