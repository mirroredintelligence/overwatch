"""Tests for the pure rules of the registration approval steps (U29): who may approve, what counts
as
the test answer, when a service may go live, and what a send-back note may say.

The approver must differ from the requester (DEC-032, an assumption until the owner rules). A test
answer counts only from the registered phone hash or the registered app device. Sample values only.
"""

import pytest

from diucs.domain.codes import RegistrationStatus
from diucs.domain.errors import InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.rules.registration_approval import (
    answers_the_test,
    check_note,
    may_set_live,
    require_distinct_approver,
)


def test_an_approver_who_requested_the_registration_is_refused() -> None:
    with pytest.raises(NotAllowed, match="differ"):
        require_distinct_approver(requester_practitioner_id="prac-1", approver_id="prac-1")


def test_a_different_approver_is_allowed() -> None:
    require_distinct_approver(requester_practitioner_id="prac-1", approver_id="lead-1")


def test_a_requester_that_is_unknown_cannot_be_matched_so_the_approval_is_refused() -> None:
    with pytest.raises(NotAllowed):
        require_distinct_approver(requester_practitioner_id=None, approver_id="lead-1")


def test_the_registered_phone_hash_answers_the_test() -> None:
    assert answers_the_test(
        answer_phone_hash="ab" * 32,
        registered_phone_hash="ab" * 32,
        answer_device_id=None,
        registered_device_id=None,
    )


def test_another_phone_hash_does_not_answer_the_test() -> None:
    assert not answers_the_test(
        answer_phone_hash="cd" * 32,
        registered_phone_hash="ab" * 32,
        answer_device_id=None,
        registered_device_id=None,
    )


def test_a_missing_registered_phone_never_matches() -> None:
    assert not answers_the_test(
        answer_phone_hash=None,
        registered_phone_hash=None,
        answer_device_id=None,
        registered_device_id=None,
    )


def test_the_registered_app_device_answers_the_test() -> None:
    assert answers_the_test(
        answer_phone_hash=None,
        registered_phone_hash=None,
        answer_device_id="device-7",
        registered_device_id="device-7",
    )


def test_a_different_device_does_not_answer_the_test() -> None:
    assert not answers_the_test(
        answer_phone_hash=None,
        registered_phone_hash=None,
        answer_device_id="device-8",
        registered_device_id="device-7",
    )


def test_a_service_goes_live_only_from_approved_with_a_test_answer() -> None:
    may_set_live(RegistrationStatus.APPROVED, test_answered=True)


@pytest.mark.parametrize(
    ("status", "answered"),
    [
        (RegistrationStatus.APPROVED, False),
        (RegistrationStatus.IN_REVIEW, True),
        (RegistrationStatus.NOT_APPROVED, True),
        (RegistrationStatus.LIVE, True),
    ],
)
def test_setting_live_is_refused_without_approval_and_a_test_answer(
    status: RegistrationStatus, answered: bool
) -> None:
    with pytest.raises((NotAllowed, InvalidTransition)):
        may_set_live(status, test_answered=answered)


def test_a_send_back_note_is_required() -> None:
    with pytest.raises(ValidationFailed, match="note"):
        check_note("   ")


def test_a_send_back_note_with_a_long_digit_run_is_refused_as_patient_information() -> None:
    with pytest.raises(ValidationFailed, match="note"):
        check_note("Please check the number 9434765919 on the form.")


def test_a_short_note_is_kept_as_it_is() -> None:
    assert check_note("Please add the call-back number.") == "Please add the call-back number."


def test_a_note_longer_than_the_limit_is_refused() -> None:
    with pytest.raises(ValidationFailed, match="note"):
        check_note("x" * 281)
