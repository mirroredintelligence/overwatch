"""RequestBooking: an advisor asks one service to take the patient on an open case (U17).

STUB (red commit): the names exist so the unit tests fail on their assertions. The build follows in
the next commit.
"""

from dataclasses import dataclass
from datetime import datetime

from diucs.application.actor import Actor
from diucs.domain.codes import Channel, Urgency
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.model.case import Case


@dataclass(frozen=True, slots=True)
class RequestBookingCommand:
    idempotency_key: str
    actor: Actor
    case_id: str
    service_id: str


@dataclass(frozen=True, slots=True)
class RequestBookingResult:
    booking_id: str
    reference: str
    reply_by: datetime
    phone_prompt_at: datetime


class RequestBooking:
    def __init__(self, *args: object, link_base_url_for: object) -> None:
        raise NotImplementedError

    async def execute(self, command: RequestBookingCommand) -> RequestBookingResult:
        raise NotImplementedError


def urgency_wording(urgency: Urgency) -> str:
    raise NotImplementedError


def need_text(case: Case) -> str:
    raise NotImplementedError


def message_for_channel(channel: Channel) -> MessageId:
    raise NotImplementedError


def command_key(scope: object, key: str) -> str:
    raise NotImplementedError
