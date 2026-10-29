"""Pure rules of suspending and resuming a service (U36): the reasons, the lead only, and the two
checks a resume needs. The stored effects are tested in tests/integration. Sample values only.
"""

import pytest

from diucs.application.use_cases.suspend_service import (
    SuspendReason,
    may_suspend,
    require_resume_checks,
    suspend_reason_of,
)
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed


def test_the_suspend_reasons_are_the_four_the_shift_lead_can_give() -> None:
    assert {reason.value for reason in SuspendReason} == {
        "suspected-false-reports",
        "closed-unexpectedly",
        "contact-unreachable",
        "other",
    }


@pytest.mark.parametrize("reason", [member.value for member in SuspendReason])
def test_each_reason_text_is_read_back_as_its_reason(reason: str) -> None:
    assert suspend_reason_of(reason).value == reason


@pytest.mark.parametrize("reason", ["", "closed", "Other", "not sure", "suspended"])
def test_a_reason_outside_the_four_is_refused(reason: str) -> None:
    with pytest.raises(ValidationFailed):
        suspend_reason_of(reason)


def test_only_the_shift_lead_may_suspend_or_resume() -> None:
    assert may_suspend(Role.LEAD) is True


@pytest.mark.parametrize(
    "role", [Role.ADVISOR, Role.CLINICAL, Role.REPORTER, Role.OWNER, Role.EXEC, Role.ANONYMOUS_LINK]
)
def test_no_other_role_may_suspend_or_resume(role: Role) -> None:
    assert may_suspend(role) is False


def test_a_resume_needs_both_the_phone_check_and_the_resolved_reason() -> None:
    require_resume_checks(phoned_register_number=True, reason_resolved=True)


@pytest.mark.parametrize(
    ("phoned", "resolved"), [(True, False), (False, True), (False, False)]
)
def test_a_resume_with_either_check_missing_is_a_validation_failure(
    phoned: bool, resolved: bool
) -> None:
    with pytest.raises(ValidationFailed):
        require_resume_checks(phoned_register_number=phoned, reason_resolved=resolved)
