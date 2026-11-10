"""A reply to a prompt that the webhook could not take in (DEC-1359).

A text reached Twilio and our webhook, a service it needs (the sender lookup, the replay marker,
the queue) failed on every attempt, and the sender was told to send it again. The record keeps what
a lead needs to deal with it by hand: when it came, who sent it (the phone hash only, never the
number), what they wrote (capped), which step failed and the class of the error (never its text).
It is one node per message sid, so a second failure of the same message is the same record.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from overwatch.domain.errors import ValidationFailed

TEXT_MAX: Final = 200
SID_MAX: Final = 64
ERROR_TYPE_MAX: Final = 80
LIST_MAX: Final = 100


class FailedStep(StrEnum):
    FIND_SENDER = "find-sender"
    REPLAY_MARKER = "replay-marker"
    ENQUEUE = "enqueue"


class ReplyStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class Resolution(StrEnum):
    HANDLED = "handled"
    REPROCESSED = "reprocessed"


def capped_text(text: str) -> str:
    """What the sender wrote, cut to the stored length."""
    return text.strip()[:TEXT_MAX]


@dataclass(frozen=True, slots=True)
class InboundReplyFailure:
    sid: str
    received_at: datetime
    step: FailedStep
    error_type: str
    text: str
    phone_hash: str
    status: ReplyStatus = ReplyStatus.OPEN
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution: Resolution | None = None

    def __post_init__(self) -> None:
        if not 2 <= len(self.sid) <= SID_MAX:
            raise ValidationFailed("sid", "not a message id")
        if self.received_at.utcoffset() is None:
            raise ValidationFailed("received_at", "a time must carry its zone")
        if len(self.text) > TEXT_MAX:
            raise ValidationFailed("text", "too long to keep")
        if not 1 <= len(self.error_type) <= ERROR_TYPE_MAX:
            raise ValidationFailed("error_type", "not an error class name")
        if (self.status is ReplyStatus.RESOLVED) != (self.resolution is not None):
            raise ValidationFailed("resolution", "resolved and its resolution go together")
