"""Reply parser: single-service words (D09) and lettered multi-service replies (D10).

Grammar: docs/spec/domain-rules.md section 2.1.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.rules.reply_parser import (
    SERVICE_LETTERS,
    BookingConfirm,
    BookingDecline,
    Confirm,
    Number,
    ParsedReply,
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
    assert len(replies) >= 1
    for reply in replies:
        if isinstance(reply, Number):
            assert 0 <= reply.value <= 999
            assert reply.letter is None or reply.letter in SERVICE_LETTERS
        if isinstance(reply, Confirm):
            assert reply.letter is None or reply.letter in SERVICE_LETTERS
        if isinstance(reply, Unrecognised):
            assert len(replies) == 1
            assert reply.text == text.strip()
    letters = [r.letter for r in replies if isinstance(r, (Confirm, Number)) and r.letter]
    assert len(letters) == len(set(letters))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Confirm one service of a grouped prompt
        ("Y A", (Confirm("A"),)),
        ("YA", (Confirm("A"),)),
        ("y a", (Confirm("A"),)),
        # A new figure for one service
        ("A 4", (Number(4, "A"),)),
        ("A4", (Number(4, "A"),)),
        ("a 4", (Number(4, "A"),)),
        ("B 2", (Number(2, "B"),)),
        ("B 0", (Number(0, "B"),)),
        ("H 999", (Number(999, "H"),)),
        ("A 04", (Number(4, "A"),)),
        # Several items, separated by spaces and/or commas, in the order written
        ("A 4 B 2", (Number(4, "A"), Number(2, "B"))),
        ("A4,B2", (Number(4, "A"), Number(2, "B"))),
        ("A 4, B 2", (Number(4, "A"), Number(2, "B"))),
        ("b 2 a 4", (Number(2, "B"), Number(4, "A"))),
        (
            "A 4 B 2 C 3 D 4 E 5 F 6 G 7 H 8",
            (
                Number(4, "A"),
                Number(2, "B"),
                Number(3, "C"),
                Number(4, "D"),
                Number(5, "E"),
                Number(6, "F"),
                Number(7, "G"),
                Number(8, "H"),
            ),
        ),
        # A confirmation and a figure in one message
        ("Y A B 2", (Confirm("A"), Number(2, "B"))),
        ("YA, B 2", (Confirm("A"), Number(2, "B"))),
        ("Y A, B 0", (Confirm("A"), Number(0, "B"))),
        # Plain Y still confirms the whole prompt
        ("Y", (Confirm(),)),
        # Lettered replies that do not parse make the whole message unrecognised
        ("A 4 A 5", (Unrecognised("A 4 A 5"),)),
        ("YA A 4", (Unrecognised("YA A 4"),)),
        ("A 4 YA", (Unrecognised("A 4 YA"),)),
        ("4 B 2", (Unrecognised("4 B 2"),)),
        ("J 4", (Unrecognised("J 4"),)),
        ("I 3", (Unrecognised("I 3"),)),
        ("A", (Unrecognised("A"),)),
        ("A 1000", (Unrecognised("A 1000"),)),
        ("A -1", (Unrecognised("A -1"),)),
        ("A 4 B", (Unrecognised("A 4 B"),)),
        ("A4 4", (Unrecognised("A4 4"),)),
        ("Y A 4", (Unrecognised("Y A 4"),)),
        ("A 4 Y", (Unrecognised("A 4 Y"),)),
        ("A,4", (Unrecognised("A,4"),)),
        ("A 4,,B 2", (Unrecognised("A 4,,B 2"),)),
        ("A 4,", (Unrecognised("A 4,"),)),
        ("Y, A 4", (Unrecognised("Y, A 4"),)),
        ("AB 4", (Unrecognised("AB 4"),)),
        ("A 4 CONFIRMED", (Unrecognised("A 4 CONFIRMED"),)),
        ("A 4 B 2 C 3 D 4 E 5 F 6 G 7 H 8 A 1", (Unrecognised("A 4 B 2 C 3 D 4 E 5 F 6 G 7 H 8 A 1"),)),
        ("٤ A", (Unrecognised("٤ A"),)),  # ARABIC-INDIC DIGIT FOUR
        ("Ａ 4", (Unrecognised("Ａ 4"),)),  # FULLWIDTH LATIN CAPITAL LETTER A
    ],
)
def test_lettered_reply_is_parsed(text: str, expected: tuple[ParsedReply, ...]) -> None:
    assert parse_reply(text) == expected


def test_the_exchange_from_the_canvas_parses_one_message_at_a_time() -> None:
    assert parse_reply("B 2") == (Number(2, "B"),)
    assert parse_reply("Y A") == (Confirm("A"),)


def test_service_letters_are_a_to_h() -> None:
    assert SERVICE_LETTERS == "ABCDEFGH"


@st.composite
def _lettered_messages(draw: st.DrawFn) -> tuple[str, tuple[ParsedReply, ...]]:
    letters = draw(
        st.lists(st.sampled_from(SERVICE_LETTERS), unique=True, min_size=1, max_size=8)
    )
    expected: list[ParsedReply] = []
    pieces: list[str] = []
    for letter in letters:
        if draw(st.booleans()):
            value = draw(st.integers(min_value=0, max_value=999))
            expected.append(Number(value, letter))
            pieces.append(draw(st.sampled_from([f"{letter} {value}", f"{letter}{value}"])))
        else:
            expected.append(Confirm(letter))
            pieces.append(draw(st.sampled_from([f"Y {letter}", f"Y{letter}"])))
    separators = draw(
        st.lists(
            st.sampled_from([" ", ", ", ","]),
            min_size=len(pieces) - 1,
            max_size=len(pieces) - 1,
        )
    )
    text = pieces[0] + "".join(sep + piece for sep, piece in zip(separators, pieces[1:]))
    return text, tuple(expected)


@given(_lettered_messages())
def test_any_well_formed_lettered_message_parses_to_its_items_in_order(
    case: tuple[str, tuple[ParsedReply, ...]],
) -> None:
    text, expected = case
    assert parse_reply(text) == expected


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
