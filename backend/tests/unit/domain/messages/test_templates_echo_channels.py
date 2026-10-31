"""The echoes of a booking reply or cancellation (B4, B5, B6) on email and push (H-135, KI-357,
KI-361, WB4). Until now they existed as text only, so a service whose reporter is on email or push
was told nothing when its confirmation was recorded, or when the SPOA cancelled.

[ASSUMED] wording: new patient- and clinician-facing text stays marked assumed until information
governance approves it in writing (DEC-1100, Q2). The wording here follows the text echoes (D16) and
the email and push wording of the booking request (B2, B3): short, no patient information, no link
(an echo asks for nothing), and a push has a subject and no HTML.
"""

import pytest

from diucs.domain.codes import Channel
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.messages.templates import render

B4 = {"reference": "4821", "service": "UCR West", "confirmed_at": "14:19"}
B5 = {"reference": "4821"}
B6 = {"reference": "4821", "cancelled_at": "14:40"}


def test_b4_email_names_the_reference_the_service_and_the_time() -> None:
    rendered = render(MessageId.B4, Channel.EMAIL, **B4)
    assert rendered.subject == "Booked: 4821, UCR West"
    assert "Booked: 4821, UCR West, confirmed 14:19. Thank you." in rendered.text
    assert rendered.html is not None and "4821" in rendered.html and "14:19" in rendered.html
    assert "This email has no patient information." in rendered.text


def test_b4_push_has_a_subject_and_a_short_body_and_no_html() -> None:
    rendered = render(MessageId.B4, Channel.PUSH, **B4)
    assert rendered.subject == "Booked: 4821"
    assert rendered.text == "UCR West, confirmed 14:19."
    assert rendered.html is None


def test_b5_email_and_push_say_declined_and_ask_for_no_reason_by_reply() -> None:
    email = render(MessageId.B5, Channel.EMAIL, **B5)
    push = render(MessageId.B5, Channel.PUSH, **B5)
    assert email.subject == "Declined: 4821"
    assert "Noted: 4821 declined." in email.text
    assert push.subject == "Declined: 4821"
    assert push.text == "Noted: 4821 declined."
    # A reply by text names a reason with 1, 2 or 3. An email or push has no such reply.
    for rendered in (email, push):
        assert "reply 1" not in rendered.text.lower()


def test_b6_email_and_push_say_cancelled_and_when() -> None:
    email = render(MessageId.B6, Channel.EMAIL, **B6)
    push = render(MessageId.B6, Channel.PUSH, **B6)
    assert email.subject == "Cancelled: 4821"
    assert "Booking 4821 was cancelled at 14:40. No action needed." in email.text
    assert push.subject == "Cancelled: 4821"
    assert push.text == "Booking 4821 was cancelled at 14:40. No action needed."


def test_the_text_echoes_are_unchanged() -> None:
    assert (
        render(MessageId.B4, Channel.TEXT, **B4).text
        == "Booked: 4821, UCR West, confirmed 14:19. Thank you."
    )
    assert render(MessageId.B6, Channel.TEXT, **B6).text.startswith("Booking 4821 was cancelled")


@pytest.mark.parametrize(
    ("message", "fields"),
    [(MessageId.B4, B4), (MessageId.B5, B5), (MessageId.B6, B6)],
)
@pytest.mark.parametrize("channel", [Channel.TEXT, Channel.EMAIL, Channel.PUSH])
def test_no_echo_holds_a_link_or_patient_data(
    message: MessageId, fields: dict[str, str], channel: Channel
) -> None:
    rendered = render(message, channel, **fields)
    text = " ".join(part for part in (rendered.subject, rendered.text, rendered.html) if part)
    assert "http" not in text and "/l/" not in text
    assert find_patient_data(text) == []


@pytest.mark.parametrize("message", [MessageId.B4, MessageId.B5, MessageId.B6])
def test_an_echo_still_refuses_a_patient_shape_in_any_field(message: MessageId) -> None:
    fields = {"B4": B4, "B5": B5, "B6": B6}[message.value]
    for channel in (Channel.EMAIL, Channel.PUSH):
        with pytest.raises(ValidationFailed):
            render(message, channel, **{**fields, "reference": "DT4 8XX"})
