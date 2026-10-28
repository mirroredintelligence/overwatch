"""Tests for diucs.domain.messages.templates: the capacity messages C1 to C12 (D15; C12 by U05).

Wording: docs/spec/domain-rules.md section 9 (samples) and the D15 prompt (templates). Where the
prompt is silent (email body, push wording for C8), DEC-034 records the choice.
Every sample value is from the rule book. No test uses a real patient, name or postcode.
"""

import re

import pytest

from diucs.domain.codes import Channel
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.sms_length import sms_segments
from diucs.domain.messages.templates import RenderedMessage, render

C1_FIELDS: dict[str, object] = {
    "service": "UCR West",
    "value": 3,
    "unit": "referrals in the next 2 hrs",
    "as_of": "08:15",
    "link": "diucs.example/k3F9a",
    "reply_by": "10:30",
}

SAMPLE_FIELDS: dict[MessageId, dict[str, object]] = {
    MessageId.C1: C1_FIELDS,
    MessageId.C2: {
        "service": "UCR West",
        "unit": "referrals",
        "window": "in the next 2 hrs",
        "reply_by": "08:30",
        "link": "diucs.example/k3F9a",
    },
    MessageId.C3: {
        "service": "UCR West",
        "value": 4,
        "unit": "referrals",
        "recorded_at": "08:06",
        "next_due": "10:00",
    },
    MessageId.C4: {
        "service": "UCR West",
        "value": 3,
        "unit": "referrals",
        "recorded_at": "14:14",
        "replaced": 4,
    },
    MessageId.C5: {
        "cutoff": "12:30",
        "rejected": 5,
        "service": "UCR West",
        "value": 3,
        "unit": "referrals",
        "reply_by": "13:11",
    },
    MessageId.C6: {"service": "UCR West"},
    MessageId.C7: {"service": "UCR West", "value": 40, "low": 0, "high": 12},
    MessageId.C8: {
        "service": "UCR West",
        "reply_by": "10:30",
        "link": "diucs.example/k3F9a",
    },
    MessageId.C9: {
        "reply_by": "10:30",
        "items": [("A", "UCR West", 3), ("B", "UCR East", 1)],
    },
    MessageId.C10: {
        "updated": [("B", "UCR East", 2)],
        "waiting": [("A", "UCR West")],
    },
    MessageId.C11: {},
    MessageId.C12: {
        "service": "UCR West",
        "value": 3,
        "unit": "referrals in the next 2 hrs",
        "as_of": "22 Oct 17:00",
        "reply_with": "a number",
        "reply_by": "12:35",
    },
}

UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b")


def test_c1_matches_the_rule_book_sample_exactly() -> None:
    rendered = render(MessageId.C1, Channel.TEXT, **C1_FIELDS)
    assert rendered.text == (
        "DIUCS: UCR West. We have 3 referrals in the next 2 hrs (as of 08:15). "
        "Confirm or update: diucs.example/k3F9a Or reply Y, or a new number. By 10:30."
    )


def test_c1_text_is_one_sms_segment() -> None:
    rendered = render(MessageId.C1, Channel.TEXT, **C1_FIELDS)
    assert sms_segments(rendered.text) == 1


def test_c2_matches_the_rule_book_first_prompt() -> None:
    rendered = render(MessageId.C2, Channel.TEXT, **SAMPLE_FIELDS[MessageId.C2])
    assert rendered.text == (
        "DIUCS: UCR West. How many referrals can you take in the next 2 hrs? "
        "Send a number (0 = closed). By 08:30."
    )


def test_c3_echo_with_unit_referrals() -> None:
    rendered = render(MessageId.C3, Channel.TEXT, **SAMPLE_FIELDS[MessageId.C3])
    assert rendered.text == "Thanks. UCR West: 4 referrals, as of 08:06. Next prompt 10:00."


def test_c4_correction_echo_matches_the_rule_book() -> None:
    rendered = render(MessageId.C4, Channel.TEXT, **SAMPLE_FIELDS[MessageId.C4])
    assert rendered.text == "Updated: UCR West 3 referrals, as of 14:14. Replaces 4."


def test_c5_too_late_matches_the_rule_book_sample() -> None:
    rendered = render(MessageId.C5, Channel.TEXT, **SAMPLE_FIELDS[MessageId.C5])
    assert rendered.text == (
        "Too late: the 12:30 cut-off had passed, so 5 was not used. "
        "New question: UCR West has 3 referrals recorded. "
        "Reply Y if right, or send the new number, by 13:11."
    )


def test_c6_y_limit_matches_the_rule_book_sample() -> None:
    rendered = render(MessageId.C6, Channel.TEXT, service="UCR West")
    assert rendered.text == "Y was used twice already. Please send the number for UCR West."


def test_c7_out_of_range_wording() -> None:
    rendered = render(MessageId.C7, Channel.TEXT, **SAMPLE_FIELDS[MessageId.C7])
    assert rendered.text == (
        "UCR West: 40 is outside the usual range of 0 to 12. If it is right, send 40 again."
    )


def test_c8_reminder_wording() -> None:
    rendered = render(MessageId.C8, Channel.TEXT, **SAMPLE_FIELDS[MessageId.C8])
    assert rendered.text == (
        "DIUCS reminder: UCR West has not updated. Confirm or update: diucs.example/k3F9a By 10:30."
    )


def test_c9_two_items_use_both_and_the_first_two_items() -> None:
    rendered = render(MessageId.C9, Channel.TEXT, **SAMPLE_FIELDS[MessageId.C9])
    assert rendered.text == (
        "DIUCS: 2 services need an update by 10:30. A) UCR West 3. B) UCR East 1. "
        "Reply Y if both right, or A 4, or B 2."
    )


def test_c9_three_items_use_all() -> None:
    rendered = render(
        MessageId.C9,
        Channel.TEXT,
        reply_by="10:30",
        items=[("A", "UCR West", 3), ("B", "UCR East", 1), ("C", "UCR North", 2)],
    )
    assert rendered.text == (
        "DIUCS: 3 services need an update by 10:30. A) UCR West 3. B) UCR East 1. "
        "C) UCR North 2. Reply Y if all right, or A 4, or B 2."
    )


def test_c9_with_one_item_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C9, Channel.TEXT, reply_by="10:30", items=[("A", "UCR West", 3)])


def test_c10_partial_echo_matches_the_rule_book_wording() -> None:
    rendered = render(MessageId.C10, Channel.TEXT, **SAMPLE_FIELDS[MessageId.C10])
    assert rendered.text == (
        "Thanks. B) UCR East updated to 2. A) UCR West still needs a reply: Y A, or A and a number."
    )


def test_c10_with_nothing_to_say_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C10, Channel.TEXT, updated=[], waiting=[])


def test_c11_unrecognised_reply_help() -> None:
    rendered = render(MessageId.C11, Channel.TEXT)
    assert rendered.text == (
        "DIUCS: reply Y if the figure is right, or send a number (0 = closed). "
        "For a booking, reply CONFIRMED or DECLINE."
    )


@pytest.mark.parametrize("message_id", list(SAMPLE_FIELDS))
def test_every_capacity_id_renders_on_the_text_channel(message_id: MessageId) -> None:
    rendered = render(message_id, Channel.TEXT, **SAMPLE_FIELDS[message_id])
    assert isinstance(rendered, RenderedMessage)
    assert rendered.channel is Channel.TEXT
    assert rendered.text
    assert rendered.subject is None
    assert rendered.html is None


def test_c1_email_has_subject_text_and_html_with_the_link() -> None:
    rendered = render(MessageId.C1, Channel.EMAIL, **C1_FIELDS)
    assert rendered.subject == "UCR West: confirm or update by 10:30"
    assert rendered.text.startswith("DIUCS: UCR West. We have 3 referrals")
    assert "The link works once, needs no login, and expires at 10:30." in rendered.text
    assert rendered.html is not None
    assert 'href="diucs.example/k3F9a"' in rendered.html
    assert "Confirm or update" in rendered.html
    assert "The link works once, needs no login, and expires at 10:30." in rendered.html


def test_email_html_escapes_service_names() -> None:
    rendered = render(MessageId.C1, Channel.EMAIL, **{**C1_FIELDS, "service": "UCR & East"})
    assert rendered.html is not None
    assert "UCR &amp; East" in rendered.html
    assert "UCR & East" in rendered.text


def test_c2_email_has_subject_and_link() -> None:
    rendered = render(MessageId.C2, Channel.EMAIL, **SAMPLE_FIELDS[MessageId.C2])
    assert rendered.subject == "UCR West: confirm or update by 08:30"
    assert rendered.html is not None
    assert 'href="diucs.example/k3F9a"' in rendered.html


def test_c8_email_has_subject_and_link() -> None:
    rendered = render(MessageId.C8, Channel.EMAIL, **SAMPLE_FIELDS[MessageId.C8])
    assert rendered.subject == "UCR West: confirm or update by 10:30"
    assert rendered.html is not None
    assert 'href="diucs.example/k3F9a"' in rendered.html


def test_c1_push_has_title_and_body() -> None:
    rendered = render(MessageId.C1, Channel.PUSH, **C1_FIELDS)
    assert rendered.subject == "UCR West: confirm or update"
    assert rendered.text == "We have 3 referrals in the next 2 hrs recorded. Reply by 10:30."
    assert rendered.html is None


def test_c2_push_has_title_and_body() -> None:
    rendered = render(MessageId.C2, Channel.PUSH, **SAMPLE_FIELDS[MessageId.C2])
    assert rendered.subject == "UCR West: confirm or update"
    assert rendered.text == "How many referrals can you take in the next 2 hrs? Reply by 08:30."


def test_c8_push_has_title_and_body() -> None:
    rendered = render(MessageId.C8, Channel.PUSH, **SAMPLE_FIELDS[MessageId.C8])
    assert rendered.subject == "UCR West: confirm or update"
    assert rendered.text == "UCR West has not updated. Reply by 10:30."


def test_missing_field_is_refused() -> None:
    fields = {k: v for k, v in C1_FIELDS.items() if k != "reply_by"}
    with pytest.raises(ValidationFailed):
        render(MessageId.C1, Channel.TEXT, **fields)


def test_unexpected_field_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C6, Channel.TEXT, service="UCR West", postcode="DT4 8XX")


def test_channel_not_supported_by_the_id_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C6, Channel.EMAIL, service="UCR West")


@pytest.mark.parametrize("channel", [Channel.EMAIL, Channel.PUSH])
def test_text_only_ids_refuse_email_and_push(channel: Channel) -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C3, channel, **SAMPLE_FIELDS[MessageId.C3])


@pytest.mark.parametrize("message_id", list(SAMPLE_FIELDS))
def test_no_rendered_capacity_message_contains_a_postcode(message_id: MessageId) -> None:
    for channel in (Channel.TEXT, Channel.EMAIL, Channel.PUSH):
        try:
            rendered = render(message_id, channel, **SAMPLE_FIELDS[message_id])
        except ValidationFailed:
            continue
        for part in (rendered.text, rendered.subject, rendered.html):
            if part is not None:
                assert UK_POSTCODE.search(part) is None


@pytest.mark.parametrize(
    "items",
    [
        "A UCR West 3",
        [("A", "UCR West")],
        [("A", "UCR West", "3"), ("B", "UCR East", 1)],
        [("A", "UCR West", True), ("B", "UCR East", 1)],
        [("A", "UCR West", 3), ("B", "UCR East")],
    ],
)
def test_c9_malformed_items_are_refused(items: object) -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C9, Channel.TEXT, reply_by="10:30", items=items)


@pytest.mark.parametrize(
    ("updated", "waiting"),
    [
        ("B UCR East 2", []),
        ([("B", "UCR East")], []),
        ([], [("A",)]),
    ],
)
def test_c10_malformed_rows_are_refused(updated: object, waiting: object) -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C10, Channel.TEXT, updated=updated, waiting=waiting)


@pytest.mark.parametrize("raw", [None, 3, "A UCR West 3"])
def test_c9_items_that_are_not_a_list_are_refused(raw: object) -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C9, Channel.TEXT, reply_by="10:30", items=raw)


@pytest.mark.parametrize("raw", [None, 3])
def test_c10_updated_or_waiting_that_is_not_a_list_is_refused(raw: object) -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C10, Channel.TEXT, updated=raw, waiting=[])
    with pytest.raises(ValidationFailed):
        render(MessageId.C10, Channel.TEXT, updated=[("B", "UCR East", 2)], waiting=raw)


@pytest.mark.parametrize("row", ["AB", ["A", "UCR West"]])
def test_c10_rows_that_are_not_tuples_are_refused(row: object) -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C10, Channel.TEXT, updated=[], waiting=[row])


@pytest.mark.parametrize(
    "row",
    [(1, "UCR West", 3), ("A", 2, 3)],
)
def test_c9_letter_and_service_must_be_text(row: tuple[object, ...]) -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.C9, Channel.TEXT, reply_by="10:30", items=[row, ("B", "UCR East", 1)])


# --- C12: the figure on record is out of date, so a Y was not used (U05, hazard H-31) -------------


def test_c12_tells_the_reporter_the_figure_is_out_of_date_and_asks_for_a_number() -> None:
    rendered = render(MessageId.C12, Channel.TEXT, **SAMPLE_FIELDS[MessageId.C12])
    assert rendered.text == (
        "DIUCS: UCR West. The figure on record, 3 referrals in the next 2 hrs, is out of date "
        "(as of 22 Oct 17:00), so Y was not used. Send a number (0 = closed). By 12:35."
    )


def test_c12_for_a_lettered_prompt_names_the_letter_to_send() -> None:
    fields = {**SAMPLE_FIELDS[MessageId.C12], "reply_with": "B and a number"}
    rendered = render(MessageId.C12, Channel.TEXT, **fields)
    assert "Send B and a number (0 = closed). By 12:35." in rendered.text


@pytest.mark.parametrize("reply_with", ["", "a figure", "B", "Z and a number", "b and a number"])
def test_c12_reply_with_is_one_of_the_two_instructions(reply_with: str) -> None:
    fields = {**SAMPLE_FIELDS[MessageId.C12], "reply_with": reply_with}
    with pytest.raises(ValidationFailed):
        render(MessageId.C12, Channel.TEXT, **fields)


def test_c12_is_sent_by_text_only() -> None:
    for channel in (Channel.EMAIL, Channel.PUSH):
        with pytest.raises(ValidationFailed):
            render(MessageId.C12, channel, **SAMPLE_FIELDS[MessageId.C12])


def test_c12_needs_every_field() -> None:
    for field in SAMPLE_FIELDS[MessageId.C12]:
        fields = {k: v for k, v in SAMPLE_FIELDS[MessageId.C12].items() if k != field}
        with pytest.raises(ValidationFailed):
            render(MessageId.C12, Channel.TEXT, **fields)
