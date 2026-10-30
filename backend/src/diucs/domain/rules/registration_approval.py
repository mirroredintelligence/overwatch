"""Rules of the registration approval steps: the distinct approver, the test answer, going live and
the send-back note (U29). Pure: no I/O and no clock.
"""

import re
from typing import Final

from diucs.domain.codes import RegistrationStatus
from diucs.domain.errors import InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.rules.registration import transition_registration

MAX_NOTE_LENGTH: Final = 280
# A run of nine or more digits can be an NHS number or a phone number: a note must not carry one.
_LONG_DIGIT_RUN: Final = re.compile(r"[0-9]{9,}")


def require_distinct_approver(*, requester_practitioner_id: str | None, approver_id: str) -> None:
    """The person who approves must not be the person who requested the registration (DEC-032).
    An unknown requester cannot be told apart, so the approval is refused (fail closed)."""
    if requester_practitioner_id is None or requester_practitioner_id == approver_id:
        raise NotAllowed("the approver must differ from the person who requested the registration")


def answers_the_test(
    *,
    answer_phone_hash: str | None,
    registered_phone_hash: str | None,
    answer_device_id: str | None,
    registered_device_id: str | None,
) -> bool:
    """A test answer counts only from the registered phone hash or the registered app device. A
    registration with neither registered never matches (fail closed)."""
    if registered_phone_hash is not None and answer_phone_hash == registered_phone_hash:
        return True
    return registered_device_id is not None and answer_device_id == registered_device_id


def may_set_live(status: RegistrationStatus, *, test_answered: bool) -> None:
    """Going live is a move from approved to live, and needs the test answer (U29)."""
    transition_registration(status, RegistrationStatus.LIVE)
    if status is not RegistrationStatus.APPROVED:
        raise InvalidTransition("only an approved registration can go live")
    if not test_answered:
        raise NotAllowed("the service cannot go live until the test prompt has been answered")


def check_note(note: str) -> str:
    """A send-back or refusal note: required, short, and with no long run of digits (no patient
    identifier). The text is kept as it was given, trimmed at the ends only."""
    text = note.strip()
    if not text:
        raise ValidationFailed("note", "is required")
    if len(text) > MAX_NOTE_LENGTH:
        raise ValidationFailed("note", "is too long")
    if _LONG_DIGIT_RUN.search(text) is not None:
        raise ValidationFailed("note", "must not contain a number that could identify a person")
    return text
