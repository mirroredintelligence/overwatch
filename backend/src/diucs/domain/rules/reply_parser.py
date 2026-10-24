"""Reply parser: turns a raw text reply into structured replies (D09 single-service words).

Pure: no I/O and no clock. The grammar is docs/spec/domain-rules.md section 2.1. Only ASCII
digits and ASCII words are recognised, so look-alike characters (fullwidth, Arabic-Indic,
dotless i) are never read as a figure or a keyword.
"""

import re
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


MAX_FIGURE_DIGITS = 3
"""Digits allowed in a figure after leading zeros are removed: 0 to 999."""

SERVICE_LETTERS = "ABCDEFGH"
"""Letters that name the services of a grouped prompt, in name order (D10). At most 8."""

MIN_REFERENCE_DIGITS = 3
MAX_REFERENCE_DIGITS = 8

_CONFIRM_WORDS = frozenset({"Y", "YES"})
_BOOKING_CONFIRM_WORDS = frozenset({"CONFIRMED", "CONFIRM"})
_BOOKING_DECLINE_WORDS = frozenset({"DECLINE", "DECLINED"})

_DIGITS = re.compile(r"[0-9]+")
_REFERENCE = re.compile(rf"[0-9]{{{MIN_REFERENCE_DIGITS},{MAX_REFERENCE_DIGITS}}}")


def parse_reply(text: str) -> tuple[ParsedReply, ...]:
    """Parse one reply. Always returns exactly one item; never raises."""
    return (_parse_one(text),)


def _parse_one(text: str) -> ParsedReply:
    trimmed = text.strip()
    normalised = " ".join(trimmed.split())
    if normalised == "" or not normalised.isascii():
        return Unrecognised(trimmed)
    words = normalised.upper().split(" ")
    if len(words) == 1:
        return _parse_single(words[0], trimmed)
    if len(words) == 2:
        return _parse_pair(words[0], words[1], trimmed)
    return Unrecognised(trimmed)


def _parse_single(word: str, trimmed: str) -> ParsedReply:
    if word in _CONFIRM_WORDS:
        return Confirm()
    if word in _BOOKING_CONFIRM_WORDS:
        return BookingConfirm(None)
    if word in _BOOKING_DECLINE_WORDS:
        return BookingDecline(None)
    if _DIGITS.fullmatch(word):
        return _figure(word, trimmed)
    return Unrecognised(trimmed)


def _figure(digits: str, trimmed: str) -> ParsedReply:
    significant = digits.lstrip("0")
    if len(significant) > MAX_FIGURE_DIGITS:
        return Unrecognised(trimmed)
    return Number(int(significant) if significant else 0)


def _parse_pair(first: str, second: str, trimmed: str) -> ParsedReply:
    for word, reference in ((first, second), (second, first)):
        if not _REFERENCE.fullmatch(reference):
            continue
        if word in _BOOKING_CONFIRM_WORDS:
            return BookingConfirm(reference)
        if word in _BOOKING_DECLINE_WORDS:
            return BookingDecline(reference)
    return Unrecognised(trimmed)
