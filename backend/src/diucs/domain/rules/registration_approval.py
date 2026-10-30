"""Rules of the registration approval steps: the distinct approver, the test answer, going live and
the send-back note (U29). Pure: no I/O and no clock.
"""

from typing import Final

from diucs.domain.codes import RegistrationStatus

MAX_NOTE_LENGTH: Final = 280


def require_distinct_approver(*, requester_practitioner_id: str | None, approver_id: str) -> None:
    raise NotImplementedError


def answers_the_test(
    *,
    answer_phone_hash: str | None,
    registered_phone_hash: str | None,
    answer_device_id: str | None,
    registered_device_id: str | None,
) -> bool:
    raise NotImplementedError


def may_set_live(status: RegistrationStatus, *, test_answered: bool) -> None:
    raise NotImplementedError


def check_note(note: str) -> str:
    raise NotImplementedError
