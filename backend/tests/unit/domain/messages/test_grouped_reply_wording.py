"""Refusals of one item of a grouped prompt name the service's letter (KI-26, D15 C7, C6, C5, C2).

On a grouped prompt (C9) a bare figure is not understood, so a refusal that tells the reporter to
"send 40 again" sends them into a reply that is then not understood. With a `letter` the wording
says what to type: `A 40`. Without one the wording is the single-service wording, unchanged.
"""

import pytest

from diucs.domain.codes import Channel
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render

C7 = {"service": "UCR West", "value": 40, "low": 0, "high": 12}
C6 = {"service": "UCR West", "confirm_limit": 2}
C5 = {
    "cutoff": "10:30",
    "rejected": "40",
    "service": "UCR West",
    "value": 3,
    "unit": "referrals",
    "reply_by": "11:10",
}
C2 = {
    "service": "UCR West",
    "unit": "referrals",
    "window": "in the next 2 hrs",
    "reply_by": "11:10",
}


def _text(message_id: MessageId, **fields: object) -> str:
    return render(message_id, Channel.TEXT, **fields).text


def test_c7_asks_for_the_lettered_figure_again_on_a_grouped_prompt() -> None:
    text = _text(MessageId.C7, **C7, letter="A")

    assert text.endswith("If it is right, send A 40 again.")


def test_c7_is_unchanged_without_a_letter() -> None:
    assert _text(MessageId.C7, **C7).endswith("If it is right, send 40 again.")


def test_c6_asks_for_the_letter_and_the_number_on_a_grouped_prompt() -> None:
    assert _text(MessageId.C6, **C6, letter="B") == (
        "Y was used twice already. Please send B and the number for UCR West."
    )


def test_c6_is_unchanged_without_a_letter() -> None:
    assert _text(MessageId.C6, **C6) == (
        "Y was used twice already. Please send the number for UCR West."
    )


def test_c5_names_the_lettered_replies_on_a_grouped_prompt() -> None:
    text = _text(MessageId.C5, **C5, letter="A")

    assert text.endswith("Reply Y A if right, or send A and the new number, by 11:10.")


def test_c5_is_unchanged_without_a_letter() -> None:
    assert _text(MessageId.C5, **C5).endswith("Reply Y if right, or send the new number, by 11:10.")


def test_c2_asks_for_the_letter_and_a_number_on_a_grouped_prompt() -> None:
    text = _text(MessageId.C2, **C2, letter="B")

    assert "Send B and a number (0 = closed). By 11:10." in text


def test_c2_is_unchanged_without_a_letter() -> None:
    assert "Send a number (0 = closed). By 11:10." in _text(MessageId.C2, **C2)


@pytest.mark.parametrize("letter", ["", "a", "AB", "1", " ", None, 5])
def test_a_letter_must_be_one_capital(letter: object) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _text(MessageId.C7, **C7, letter=letter)

    assert refused.value.field == "letter"


@pytest.mark.parametrize("message_id", [MessageId.C1, MessageId.C3, MessageId.C8, MessageId.C11])
def test_a_message_that_takes_no_letter_refuses_one(message_id: MessageId) -> None:
    fields = {
        MessageId.C1: {
            "service": "UCR West",
            "value": 3,
            "unit": "referrals",
            "as_of": "23 Oct 08:15",
            "link": "https://x.example/l/t",
            "reply_by": "10:30",
        },
        MessageId.C3: {
            "service": "UCR West",
            "value": 3,
            "unit": "referrals",
            "recorded_at": "10:12",
            "next_due": "12:00",
        },
        MessageId.C8: {"service": "UCR West", "reply_by": "10:30", "link": "https://x.example/l/t"},
        MessageId.C11: {},
    }[message_id]

    with pytest.raises(ValidationFailed) as refused:
        _text(message_id, **fields, letter="A")

    assert refused.value.field == "letter"
