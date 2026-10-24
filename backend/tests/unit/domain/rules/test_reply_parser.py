"""Reply parser: single-service capacity words and booking words (D09).

Grammar: docs/spec/domain-rules.md section 2.1. Lettered multi-service replies are D10.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.rules.reply_parser import (
    BookingConfirm,
    BookingDecline,
    Confirm,
    Number,
    Unrecognised,
    parse_reply,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Confirm the recorded figure
        ("Y", (Confirm(),)),
        ("y", (Confirm(),)),
        (" yes ", (Confirm(),)),
        ("YES", (Confirm(),)),
        # A new figure, 0 to 999; leading zeros are fine
        ("4", (Number(4),)),
        ("0", (Number(0),)),
        ("04", (Number(4),)),
        ("999", (Number(999),)),
        ("000", (Number(0),)),
        ("0000000000000000000000000012", (Number(12),)),
        # Numeric-looking text that is not a figure
        ("1000", (Unrecognised("1000"),)),
        ("-1", (Unrecognised("-1"),)),
        ("+4", (Unrecognised("+4"),)),
        ("3.5", (Unrecognised("3.5"),)),
        ("4.", (Unrecognised("4."),)),
        ("four", (Unrecognised("four"),)),
        ("9" * 5000, (Unrecognised("9" * 5000),)),
        # Booking confirm, with or without a reference
        ("CONFIRMED", (BookingConfirm(None),)),
        ("confirmed", (BookingConfirm(None),)),
        ("Confirm", (BookingConfirm(None),)),
        ("CONFIRMED 4821", (BookingConfirm("4821"),)),
        ("4821 CONFIRMED", (BookingConfirm("4821"),)),
        ("CONFIRMED    4821", (BookingConfirm("4821"),)),
        ("\t4821 CONFIRMED ", (BookingConfirm("4821"),)),
        ("CONFIRMED 123", (BookingConfirm("123"),)),
        ("CONFIRMED 12345678", (BookingConfirm("12345678"),)),
        # Booking decline, with or without a reference
        ("DECLINE", (BookingDecline(None),)),
        ("declined", (BookingDecline(None),)),
        ("DECLINE 4821", (BookingDecline("4821"),)),
        ("DECLINE 0482", (BookingDecline("0482"),)),
        # The parser does not know the prompt, so a lone digit is a figure
        ("1", (Number(1),)),
        # Words the product does not use
        ("STOP", (Unrecognised("STOP"),)),
        ("HELP", (Unrecognised("HELP"),)),
        ("START", (Unrecognised("START"),)),
        ("yes please", (Unrecognised("yes please"),)),
        ("", (Unrecognised(""),)),
        ("   ", (Unrecognised(""),)),
        ("Y.", (Unrecognised("Y."),)),
        ("YESS", (Unrecognised("YESS"),)),
        # Two answers at once are not allowed for one service
        ("Y 4", (Unrecognised("Y 4"),)),
        # Reference must be 3 to 8 digits
        ("CONFIRMED 12", (Unrecognised("CONFIRMED 12"),)),
        ("CONFIRMED 123456789", (Unrecognised("CONFIRMED 123456789"),)),
        ("DECLINE 1", (Unrecognised("DECLINE 1"),)),
        ("1 CONFIRMED", (Unrecognised("1 CONFIRMED"),)),
        ("CONFIRMED AB12", (Unrecognised("CONFIRMED AB12"),)),
        ("CONFIRMED 4821 4821", (Unrecognised("CONFIRMED 4821 4821"),)),
        ("CONFIRMED DECLINE", (Unrecognised("CONFIRMED DECLINE"),)),
        ("0 4", (Unrecognised("0 4"),)),
        ("Y 4821", (Unrecognised("Y 4821"),)),
        ("4821 YES", (Unrecognised("4821 YES"),)),
        # Only ASCII digits and words count
        ("٤", (Unrecognised("٤"),)),  # ARABIC-INDIC DIGIT FOUR
        ("４", (Unrecognised("４"),)),  # FULLWIDTH DIGIT FOUR
        ("ＹＥＳ", (Unrecognised("ＹＥＳ"),)),  # fullwidth YES
        ("CONFıRMED", (Unrecognised("CONFıRMED"),)),  # dotless i
    ],
)
def test_reply_is_parsed(text: str, expected: tuple[object, ...]) -> None:
    assert parse_reply(text) == expected


def test_unrecognised_keeps_the_trimmed_original_text_not_the_normalised_text() -> None:
    assert parse_reply("  Four   please  ") == (Unrecognised("Four   please"),)


def test_a_reply_is_one_item_in_a_tuple() -> None:
    replies = parse_reply("Y")
    assert isinstance(replies, tuple)
    assert len(replies) == 1


@given(st.text())
def test_parser_never_raises_and_only_returns_in_range_figures(text: str) -> None:
    replies = parse_reply(text)
    assert len(replies) == 1
    reply = replies[0]
    if isinstance(reply, Number):
        assert 0 <= reply.value <= 999
    if isinstance(reply, Unrecognised):
        assert reply.text == text.strip()


@given(
    value=st.integers(min_value=0, max_value=999),
    zeros=st.integers(min_value=0, max_value=40),
)
def test_every_figure_0_to_999_parses_with_any_leading_zeros(value: int, zeros: int) -> None:
    assert parse_reply("0" * zeros + str(value)) == (Number(value),)


@given(value=st.integers(min_value=1000, max_value=10**30))
def test_every_whole_number_above_999_is_unrecognised(value: int) -> None:
    text = str(value)
    assert parse_reply(text) == (Unrecognised(text),)


@given(reference=st.from_regex(r"\A[0-9]{3,8}\Z"))
def test_any_3_to_8_digit_reference_is_kept_as_typed(reference: str) -> None:
    assert parse_reply(f"CONFIRMED {reference}") == (BookingConfirm(reference),)
    assert parse_reply(f"{reference} DECLINED") == (BookingDecline(reference),)
