"""Message templates (D15): the capacity messages C1 to C11, rendered as pure functions."""

from dataclasses import dataclass

from diucs.domain.codes import Channel
from diucs.domain.messages.catalogue import MessageId


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    message_id: MessageId
    channel: Channel
    text: str
    subject: str | None = None
    html: str | None = None


def render(message_id: MessageId, channel: Channel, **fields: object) -> RenderedMessage:
    raise NotImplementedError
