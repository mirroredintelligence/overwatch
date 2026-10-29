"""Outbound message senders (I10): the consumers of `messages.outbound` (DEC-115, DEC-116).

STUB for the red commit: names only. The behaviour is written in the implement commit.
"""

from dataclasses import dataclass
from typing import Final

from diucs.domain.codes import Channel

MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE_EVENT: Final = "SendMessage"
CONSUMER_SMS: Final = "sender-sms"
CONSUMER_EMAIL: Final = "sender-email"
SMS_SUBSCRIPTION: Final = "text-sender"
EMAIL_SUBSCRIPTION: Final = "email-sender"
PUSH_SUBSCRIPTION: Final = "push-sender"

NO_TENANT: Final = "message has no tenant"
NOT_A_SEND: Final = "message is not a send"
BAD_PAYLOAD: Final = "outbound payload is not one this system sends"
BAD_CHANNEL: Final = "outbound message is for another channel"
BAD_CONTENT: Final = "outbound content cannot be opened"
NO_COMMUNICATION: Final = "the communication to send is not stored"


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    communication_id: str
    channel: Channel
    recipient_role_id: str
    message_id: str
    text: str
    subject: str | None
    html: str | None


def parse_outbound(
    payload: object, *, message_id: str, tenant_id: str, sealer: object
) -> OutboundMessage:
    raise NotImplementedError


def is_handled(communication: object) -> bool:
    raise NotImplementedError


class SmsMessageSender:
    def __init__(self, senders: object, sealer: object) -> None:
        self._senders = senders
        self._sealer = sealer

    async def __call__(self, message: object, uow: object) -> None:
        raise NotImplementedError


class EmailMessageSender:
    def __init__(self, senders: object, sealer: object) -> None:
        self._senders = senders
        self._sealer = sealer

    async def __call__(self, message: object, uow: object) -> None:
        raise NotImplementedError
