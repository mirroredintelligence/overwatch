"""The safety report record (U41): a concern holds its reference and owner, a problem report holds
whether the session was shared. Sample values only.
"""

from datetime import UTC, datetime

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.safety import SafetyReport

AT = datetime(2026, 10, 29, 14, 20, tzinfo=UTC)


def concern(**changes: object) -> SafetyReport:
    values: dict[str, object] = {
        "id": "sr-1",
        "code": "safety-concern",
        "requester_id": "prac-1",
        "category": "wrong-status-on-board",
        "created_at": AT,
        "reference": "SC-0001",
        "focus_id": None,
        "text_handle": "h-1",
        "owner_role_id": "clinical-safety-officer",
        "session_shared": None,
    }
    values.update(changes)
    return SafetyReport(**values)  # type: ignore[arg-type]


def test_a_concern_holds_its_reference_owner_and_text_handle() -> None:
    report = concern()
    assert report.reference == "SC-0001"
    assert report.owner_role_id == "clinical-safety-officer"
    assert report.session_shared is None


def test_a_concern_without_its_reference_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        concern(reference=None)


def test_a_concern_must_be_in_one_of_the_five_categories() -> None:
    with pytest.raises(ValidationFailed):
        concern(category="screen-slow")


def test_a_problem_report_carries_whether_the_session_was_shared_and_no_reference() -> None:
    report = concern(
        id="pr-1",
        code="problem-report",
        category="screen-slow",
        reference=None,
        owner_role_id=None,
        session_shared=True,
    )
    assert report.session_shared is True
    assert report.reference is None


def test_a_problem_report_needs_to_say_whether_the_session_was_shared() -> None:
    with pytest.raises(ValidationFailed):
        concern(
            id="pr-2",
            code="problem-report",
            category="screen-slow",
            reference=None,
            owner_role_id=None,
            session_shared=None,
        )


def test_the_code_is_one_of_the_two_report_codes() -> None:
    with pytest.raises(ValidationFailed):
        concern(code="clinical-advice-request")
