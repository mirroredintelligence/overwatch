"""Tests for diucs.domain.messages.templates: booking, invitation, code and alert messages (D16).

Wording: docs/spec/domain-rules.md section 9 and the D16 prompt (exact text). Where the prompt is
silent or marks a text [ASSUMED], DEC-037 records the choice. ui-screens.md is the screen wording
for B1, B2, B3, B4, B5, I1, I2 and K2; the prompt text is followed where the two differ.
Sample values are from the rule book, except B1 `need`, which is a NeedCategory code (DEC-047 item 9,
owner-pending): the B1 text therefore differs from the rule-book sample "fall and frailty".
No test uses a real patient, name or postcode.
"""

import re

import pytest

from diucs.domain.codes import Channel
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.sms_length import sms_segments
from diucs.domain.messages.templates import RenderedMessage, render

UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}\b")

B1_FIELDS: dict[str, object] = {
    "reference": "4821",
    "service": "UCR West",
    "age_band": "80+",
    "need": "frailty",
    "urgency": "within 2 hrs",
    "link": "diucs.example/b4821",
    "reply_by": "14:26",
}

BOOKING_FIELDS: dict[MessageId, dict[str, object]] = {
    MessageId.B1: B1_FIELDS,
    MessageId.B2: B1_FIELDS,
    MessageId.B3: {"reference": "4821", "service": "UCR West", "reply_by": "14:26"},
    MessageId.B4: {"reference": "4821", "service": "UCR West", "confirmed_at": "14:19"},
    MessageId.B5: {"reference": "4821"},
    MessageId.B6: {"reference": "4821", "cancelled_at": "14:40"},
    MessageId.B7: {"references": ["4821", "4830"]},
    MessageId.I1: {"service": "UCR West", "link": "diucs.example/i/Qx82"},
    MessageId.I2: {"link": "diucs.example/i/Ab41"},
    MessageId.I3: {"service": "UCR West"},
    MessageId.K1: {"code": "582913"},
    MessageId.K2: {"service": "UCR West", "review_by": "12 Dec"},
    MessageId.K3: {"title": "UCR West is over capacity", "body": "Open the board to see it."},
    MessageId.K4: {"service": "UCR East"},
}


# Booking (B1 to B7)


def test_b1_renders_the_need_code_pending_owner_wording() -> None:
    rendered = render(MessageId.B1, Channel.TEXT, **B1_FIELDS)
    assert rendered.text == (
        "DIUCS REQUEST 4821: UCR West. Age 80+, frailty, within 2 hrs. "
        "Referral details follow in SystmOne. Reply CONFIRMED or DECLINE, "
        "or open diucs.example/b4821 by 14:26."
    )
    assert rendered.subject is None
    assert rendered.html is None


def test_b1_is_at_most_two_sms_segments() -> None:
    text = render(MessageId.B1, Channel.TEXT, **B1_FIELDS).text
    assert sms_segments(text) <= 2


def test_b4_confirmed_echo_matches_the_rule_book() -> None:
    rendered = render(MessageId.B4, Channel.TEXT, **BOOKING_FIELDS[MessageId.B4])
    assert rendered.text == "Booked: 4821, UCR West, confirmed 14:19. Thank you."


def test_b5_declined_echo_matches_the_rule_book() -> None:
    rendered = render(MessageId.B5, Channel.TEXT, reference="4821")
    assert rendered.text == (
        "Noted: 4821 declined. Optional reason: reply 1 full, 2 outside criteria, 3 other."
    )


def test_b6_cancelled_notice_matches_the_screen_text() -> None:
    # ui-screens.md line 1276: "Booking 4821 was cancelled at 14:40. No action needed."
    rendered = render(MessageId.B6, Channel.TEXT, reference="4821", cancelled_at="14:40")
    assert rendered.text == "Booking 4821 was cancelled at 14:40. No action needed."


def test_b7_names_both_references_and_the_confirm_example() -> None:
    rendered = render(MessageId.B7, Channel.TEXT, references=["4821", "4830"])
    assert rendered.text == (
        "You have more than one open request: 4821, 4830. Reply CONFIRMED or DECLINE "
        "with the reference, for example CONFIRMED 4821."
    )


@pytest.mark.parametrize("references", [["4821"], [], "4821"])
def test_b7_needs_two_references_given_as_a_list(references: object) -> None:
    # A bare string is iterable, so "4821" would otherwise join as "4, 8, 2, 1".
    with pytest.raises(ValidationFailed):
        render(MessageId.B7, Channel.TEXT, references=references)


def test_b2_email_subject_and_labelled_review_link() -> None:
    rendered = render(MessageId.B2, Channel.EMAIL, **B1_FIELDS)
    assert rendered.subject == "Booking request 4821: UCR West, reply by 14:26"
    assert rendered.text.splitlines()[:6] == [
        "Booking request 4821 for UCR West.",
        "Age band 80+",
        "Need: frailty",
        "Response wanted: within 2 hrs",
        "Referral details follow in SystmOne.",
        "Please review and reply by 14:26.",
    ]
    assert "Review request: diucs.example/b4821" in rendered.text
    assert "Opening the link does not book anything." in rendered.text
    assert "The link works once and needs no login." in rendered.text
    assert rendered.html is not None
    assert ">Review request</a>" in rendered.html
    assert 'href="diucs.example/b4821"' in rendered.html


def test_b2_email_html_escapes_the_service_name() -> None:
    rendered = render(MessageId.B2, Channel.EMAIL, **{**B1_FIELDS, "service": "A & B"})
    assert rendered.html is not None
    assert "A &amp; B" in rendered.html
    assert "A & B" not in rendered.html


def test_b3_push_title_and_text() -> None:
    rendered = render(MessageId.B3, Channel.PUSH, **BOOKING_FIELDS[MessageId.B3])
    assert rendered.subject == "Booking request 4821: UCR West"
    assert rendered.text == "Reply by 14:26. Not booked until you confirm."


# Invitations (I1 to I3)


def test_i1_invitation_for_a_service_matches_the_rule_book() -> None:
    rendered = render(MessageId.I1, Channel.TEXT, service="UCR West", link="diucs.example/i/Qx82")
    assert rendered.text == (
        "DIUCS: You are invited to report capacity for UCR West. "
        "Set up takes about 3 minutes: diucs.example/i/Qx82 Valid for 48 hrs."
    )


def test_i2_invitation_for_the_exec_view() -> None:
    rendered = render(MessageId.I2, Channel.TEXT, link="diucs.example/i/Ab41")
    assert rendered.text == (
        "DIUCS: You are invited to see Dorset urgent care capacity on your phone. "
        "Set up takes about 3 minutes: diucs.example/i/Ab41 Valid for 48 hrs."
    )


def test_i3_test_prompt_wording() -> None:
    rendered = render(MessageId.I3, Channel.TEXT, service="UCR West")
    assert rendered.text == "DIUCS test: UCR West. Reply Y to show you receive prompts."


# Codes and alerts (K1 to K4)


def test_k1_text_code_wording() -> None:
    rendered = render(MessageId.K1, Channel.TEXT, code="582913")
    assert rendered.text == "DIUCS code: 582913. It works for 10 minutes. Do not share it."


def test_k2_email_subject_and_body_carry_the_review_text() -> None:
    rendered = render(MessageId.K2, Channel.EMAIL, service="UCR West", review_by="12 Dec")
    assert rendered.subject == "UCR West criteria: review due"
    assert "Due 12 Dec. Confirm or update in 2 minutes." in rendered.text


def test_k2_push_title_and_text() -> None:
    rendered = render(MessageId.K2, Channel.PUSH, service="UCR West", review_by="12 Dec")
    assert rendered.subject == "UCR West criteria: review due"
    assert rendered.text == "Due 12 Dec. Confirm or update in 2 minutes."


def test_k3_alert_push_takes_title_and_body_as_given() -> None:
    rendered = render(
        MessageId.K3,
        Channel.PUSH,
        title="UCR West is over capacity",
        body="Open the board to see it.",
    )
    assert rendered.subject == "UCR West is over capacity"
    assert rendered.text == "Open the board to see it."


def test_k4_suspended_notice_wording() -> None:
    rendered = render(MessageId.K4, Channel.TEXT, service="UCR East")
    assert rendered.text == (
        "DIUCS: UCR East is suspended. Prompts have stopped. The SPOA shift lead will phone you."
    )


# Channels, fields and refusals


@pytest.mark.parametrize(
    ("message_id", "channel"),
    [
        (MessageId.B1, Channel.EMAIL),
        (MessageId.B1, Channel.PUSH),
        (MessageId.B2, Channel.TEXT),
        (MessageId.B2, Channel.PUSH),
        (MessageId.B3, Channel.TEXT),
        (MessageId.B3, Channel.EMAIL),
        (MessageId.K2, Channel.TEXT),
        (MessageId.K3, Channel.TEXT),
        (MessageId.K3, Channel.EMAIL),
        (MessageId.K1, Channel.EMAIL),
        (MessageId.I1, Channel.PUSH),
    ],
)
def test_channel_the_id_is_not_sent_on_is_refused(message_id: MessageId, channel: Channel) -> None:
    with pytest.raises(ValidationFailed):
        render(message_id, channel, **BOOKING_FIELDS[message_id])


def test_b1_on_email_is_refused_even_with_all_fields() -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, Channel.EMAIL, **B1_FIELDS)


def test_b1_with_a_name_field_is_refused() -> None:
    with pytest.raises(ValidationFailed) as error:
        render(MessageId.B1, Channel.TEXT, **B1_FIELDS, name="x")
    assert error.value.field == "name"


def test_b1_missing_reference_is_refused() -> None:
    fields = {key: value for key, value in B1_FIELDS.items() if key != "reference"}
    with pytest.raises(ValidationFailed) as error:
        render(MessageId.B1, Channel.TEXT, **fields)
    assert error.value.field == "reference"


@pytest.mark.parametrize("message_id", list(BOOKING_FIELDS))
def test_every_booking_invitation_and_code_id_renders_on_a_channel(
    message_id: MessageId,
) -> None:
    channels = (Channel.TEXT, Channel.EMAIL, Channel.PUSH)
    rendered: list[RenderedMessage] = []
    for channel in channels:
        try:
            rendered.append(render(message_id, channel, **BOOKING_FIELDS[message_id]))
        except ValidationFailed:
            continue
    assert rendered, f"{message_id.value} renders on no channel"


@pytest.mark.parametrize("message_id", list(BOOKING_FIELDS))
def test_no_booking_invitation_or_code_message_contains_a_postcode(
    message_id: MessageId,
) -> None:
    for channel in (Channel.TEXT, Channel.EMAIL, Channel.PUSH):
        try:
            rendered = render(message_id, channel, **BOOKING_FIELDS[message_id])
        except ValidationFailed:
            continue
        for part in (rendered.text, rendered.subject, rendered.html):
            if part is not None:
                assert UK_POSTCODE.search(part) is None


def test_no_placeholder_is_left_in_any_rendered_text() -> None:
    for message_id, fields in BOOKING_FIELDS.items():
        for channel in (Channel.TEXT, Channel.EMAIL, Channel.PUSH):
            try:
                rendered = render(message_id, channel, **fields)
            except ValidationFailed:
                continue
            for part in (rendered.text, rendered.subject, rendered.html):
                if part is not None:
                    assert "{" not in part and "}" not in part
