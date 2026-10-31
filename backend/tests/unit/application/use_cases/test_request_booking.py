"""The pure rules of RequestBooking (U17): the urgency wording, the need text, the message per
channel and the replay key, plus the B1 template accepting two needs joined with "and".
"""

from datetime import UTC, datetime

import pytest

from diucs.application.use_cases.request_booking import (
    command_key,
    message_for_channel,
    need_text,
    urgency_wording,
)
from diucs.domain.codes import AgeBand, Channel, NeedCategory, ReferrerType, Urgency
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.case import Case

OPENED = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)


def case_with(needs: tuple[NeedCategory, ...]) -> Case:
    return Case(
        id="case-1",
        reference="C-0001",
        referrer_type=ReferrerType.GP,
        age_band=AgeBand.A80_PLUS,
        postcode=None,
        needs=needs,
        urgency=Urgency.WITHIN_2_HRS,
        scores=(),
        opened_at=OPENED,
    )


@pytest.mark.parametrize(
    ("urgency", "wording"),
    [
        (Urgency.WITHIN_2_HRS, "within 2 hrs"),
        (Urgency.TODAY, "today"),
        (Urgency.PLANNED, "planned"),
    ],
)
def test_each_urgency_has_its_rule_book_wording(urgency: Urgency, wording: str) -> None:
    assert urgency_wording(urgency) == wording


def test_every_urgency_member_has_a_wording() -> None:
    for urgency in Urgency:
        assert urgency_wording(urgency) in {"within 2 hrs", "today", "planned"}


def test_one_need_is_its_plain_words() -> None:
    assert need_text(case_with((NeedCategory.FALL_NO_INJURY,))) == "fall, no injury"


def test_two_needs_are_joined_with_and_in_their_order() -> None:
    needs = (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY)
    assert need_text(case_with(needs)) == "fall, no injury and frailty"


def test_three_needs_are_all_named_with_and_before_the_last() -> None:
    """DEC-1150: no need is left off (the U17 cap of two is lifted); the last joins with and."""
    needs = (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY, NeedCategory.DEMENTIA)
    assert need_text(case_with(needs)) == "fall, no injury, frailty and dementia"


def test_no_raw_code_reaches_the_text() -> None:
    needs = tuple(NeedCategory)
    text = need_text(case_with(needs))
    assert not any("-" in word for word in text.split())


def test_a_case_with_no_need_is_refused_as_incomplete() -> None:
    with pytest.raises(ValidationFailed) as error:
        need_text(case_with(()))
    assert error.value.field == "needs"


@pytest.mark.parametrize(
    ("channel", "message"),
    [(Channel.TEXT, MessageId.B1), (Channel.EMAIL, MessageId.B2), (Channel.PUSH, MessageId.B3)],
)
def test_each_channel_sends_its_booking_message(channel: Channel, message: MessageId) -> None:
    assert message_for_channel(channel) is message


def test_the_replay_key_names_the_tenant_so_two_tenants_never_share_a_result() -> None:
    assert command_key("tenant-a", "k-1") != command_key("tenant-b", "k-1")
    assert command_key("tenant-a", "k-1") == command_key("tenant-a", "k-1")


def test_the_text_request_accepts_the_plain_words_of_two_needs_joined_with_and() -> None:
    fields = {
        "reference": "4821",
        "service": "UCR West",
        "age_band": "80+",
        "need": "fall, no injury and frailty",
        "urgency": "within 2 hrs",
        "link": "https://dorset.diucs.example/l/abcdef",
        "reply_by": "14:26",
        "referral_system_name": "the referral system",
    }
    assert (
        "Age 80+, fall, no injury and frailty, within 2 hrs"
        in render(MessageId.B1, Channel.TEXT, **fields).text
    )


def test_the_text_request_refuses_a_raw_need_code() -> None:
    fields = {
        "reference": "4821",
        "service": "UCR West",
        "age_band": "80+",
        "need": "fall-no-injury and frailty",
        "urgency": "within 2 hrs",
        "link": "https://dorset.diucs.example/l/abcdef",
        "reply_by": "14:26",
        "referral_system_name": "the referral system",
    }
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, Channel.TEXT, **fields)


def test_a_joined_need_with_a_word_that_is_no_code_is_still_refused() -> None:
    fields = {
        "reference": "4821",
        "service": "UCR West",
        "age_band": "80+",
        "need": "fall and frailty",
        "urgency": "within 2 hrs",
        "link": "https://dorset.diucs.example/l/abcdef",
        "reply_by": "14:26",
    }
    with pytest.raises(ValidationFailed):
        render(MessageId.B1, Channel.TEXT, **fields)
