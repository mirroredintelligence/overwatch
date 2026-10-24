"""Reply parser: turns a raw text reply into structured replies (D09 single-service words)."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Confirm:
    letter: str | None = None


@dataclass(frozen=True, slots=True)
class Number:
    value: int
    letter: str | None = None


@dataclass(frozen=True, slots=True)
class BookingConfirm:
    reference: str | None


@dataclass(frozen=True, slots=True)
class BookingDecline:
    reference: str | None


@dataclass(frozen=True, slots=True)
class Unrecognised:
    text: str


ParsedReply = Confirm | Number | BookingConfirm | BookingDecline | Unrecognised


def parse_reply(text: str) -> tuple[ParsedReply, ...]:
    raise NotImplementedError
