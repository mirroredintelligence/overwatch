"""Reply parser: turns a raw text reply into structured replies.

Single-service words and booking words are D09; lettered multi-service replies are D10. The
grammar is docs/spec/domain-rules.md section 2.1. Pure: no I/O and no clock. Only ASCII digits
and ASCII words are recognised, so look-alike characters (fullwidth, Arabic-Indic, dotless i)
are never read as a figure, a letter or a keyword.
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
_LETTER_FIGURE = re.compile(rf"([{SERVICE_LETTERS}])([0-9]+)")
_LETTER_CONFIRM = re.compile(rf"Y([{SERVICE_LETTERS}])")
_TOKEN_SEPARATORS = re.compile(r"[\s,]+")


def parse_reply(text: str) -> tuple[ParsedReply, ...]:
    """Parse one reply. Never raises.

    Returns one item for a single-service reply. A lettered reply returns one item per
    service, in the order written, or a single Unrecognised if any part does not parse.
    """
    trimmed = text.strip()
    normalised = " ".join(trimmed.split())
    # ASCII is checked before upper-casing: upper() maps dotless i to I, which would let
    # look-alike text read as a keyword.
    if normalised == "" or not normalised.isascii():
        return (Unrecognised(trimmed),)
    upper = normalised.upper()
    if any(_is_lettered_token(token) for token in _TOKEN_SEPARATORS.split(upper)):
        return _parse_lettered(upper, trimmed)
    return (_parse_single(upper, trimmed),)


def _parse_single(upper: str, trimmed: str) -> ParsedReply:
    words = upper.split(" ")
    if len(words) == 1:
        return _parse_word(words[0], trimmed)
    if len(words) == 2:
        return _parse_pair(words[0], words[1], trimmed)
    return Unrecognised(trimmed)


def _parse_word(word: str, trimmed: str) -> ParsedReply:
    if word in _CONFIRM_WORDS:
        return Confirm()
    if word in _BOOKING_CONFIRM_WORDS:
        return BookingConfirm(None)
    if word in _BOOKING_DECLINE_WORDS:
        return BookingDecline(None)
    if _DIGITS.fullmatch(word):
        value = _figure_value(word)
        return Unrecognised(trimmed) if value is None else Number(value)
    return Unrecognised(trimmed)


def _figure_value(digits: str) -> int | None:
    significant = digits.lstrip("0")
    if len(significant) > MAX_FIGURE_DIGITS:
        return None
    return int(significant) if significant else 0


def _parse_pair(first: str, second: str, trimmed: str) -> ParsedReply:
    for word, reference in ((first, second), (second, first)):
        if not _REFERENCE.fullmatch(reference):
            continue
        if word in _BOOKING_CONFIRM_WORDS:
            return BookingConfirm(reference)
        if word in _BOOKING_DECLINE_WORDS:
            return BookingDecline(reference)
    return Unrecognised(trimmed)


def _is_letter(token: str) -> bool:
    return len(token) == 1 and token in SERVICE_LETTERS


def _is_lettered_token(token: str) -> bool:
    return (
        _is_letter(token)
        or _LETTER_FIGURE.fullmatch(token) is not None
        or _LETTER_CONFIRM.fullmatch(token) is not None
    )


def _parse_lettered(upper: str, trimmed: str) -> tuple[ParsedReply, ...]:
    """Commas separate items; within an item, tokens are separated by spaces.

    A bare Y is only valid as the whole message, which the single-service path handles, so a
    Y here must be followed by a letter. Any unparsed part makes the whole reply Unrecognised.
    """
    items: list[ParsedReply] = []
    for segment in upper.split(","):
        parsed = _parse_segment(segment.split())
        if parsed is None:
            return (Unrecognised(trimmed),)
        items.extend(parsed)
    letters = [item.letter for item in items if isinstance(item, Confirm | Number) and item.letter]
    if len(set(letters)) != len(letters):
        return (Unrecognised(trimmed),)
    return tuple(items)


def _parse_segment(tokens: list[str]) -> list[ParsedReply] | None:
    if not tokens:
        return None
    items: list[ParsedReply] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if token in _CONFIRM_WORDS:
            if following is None or not _is_letter(following):
                return None
            items.append(Confirm(following))
            index += 2
        elif confirm := _LETTER_CONFIRM.fullmatch(token):
            items.append(Confirm(confirm.group(1)))
            index += 1
        elif figure := _LETTER_FIGURE.fullmatch(token):
            value = _figure_value(figure.group(2))
            if value is None:
                return None
            items.append(Number(value, figure.group(1)))
            index += 1
        elif _is_letter(token):
            if following is None or _DIGITS.fullmatch(following) is None:
                return None
            value = _figure_value(following)
            if value is None:
                return None
            items.append(Number(value, token))
            index += 2
        else:
            return None
    return items
