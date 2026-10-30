"""T1, the test message a registration's test notification and a lead's test prompt send (W7B).

It names the service and says it is a test and needs no answer: no link, no figure and nothing to
reply to, so nobody can mistake it for a capacity prompt and answer it with a number (a number sent
back to it would be a report). [ASSUMED] wording, awaiting the owner's and IG's approval."""

import pytest

from diucs.domain.codes import Channel
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render


@pytest.mark.parametrize("channel", [Channel.TEXT, Channel.EMAIL, Channel.PUSH])
def test_the_test_message_says_it_is_a_test_and_needs_no_answer(channel: Channel) -> None:
    rendered = render(MessageId.T1, channel, service="UCR West")

    text = rendered.text
    assert "UCR West" in text
    assert "test" in text.lower()
    assert "no reply" in text.lower() or "nothing to" in text.lower()
    for word in ("http", "reply with", "send a number", "confirm or update"):
        assert word not in text.lower()


def test_the_text_is_short_enough_for_one_message() -> None:
    assert len(render(MessageId.T1, Channel.TEXT, service="UCR West").text) <= 160


def test_the_test_message_takes_the_service_and_nothing_else() -> None:
    with pytest.raises(ValidationFailed):
        render(MessageId.T1, Channel.TEXT, service="UCR West", link="https://example.test/x")
    with pytest.raises(ValidationFailed):
        render(MessageId.T1, Channel.TEXT)
