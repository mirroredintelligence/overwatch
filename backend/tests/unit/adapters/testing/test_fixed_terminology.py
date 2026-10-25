"""Fixed terminology and validator fakes (P11). No network; answers come from the tables."""

from typing import Any

import pytest

from diucs.adapters.testing.fixed_terminology import (
    FixedTerminology,
    PassThroughValidator,
    RecordingValidator,
)
from diucs.application.ports.outbound.terminology import OdsRecord, ValidationIssue
from diucs.domain.errors import ValidationFailed

SYSTEM = "urn:example:service-type"
ACTIVE = OdsRecord("ZZ1001", "Example Community Team", True, "Community", "DT4 8XX")
CLOSED = OdsRecord("ZZ1002", "Example Closed Ward", False, "Ward", None)
RESOURCE: dict[str, Any] = {"resourceType": "Location", "id": "example-site"}
ISSUE = ValidationIssue("error", "required", "Location.name", "Name is required")


def _terminology() -> FixedTerminology:
    return FixedTerminology(
        {ACTIVE.code: ACTIVE, CLOSED.code: CLOSED},
        {(SYSTEM, "A1"): "Example display"},
    )


async def test_known_active_code_returns_its_record() -> None:
    assert await _terminology().ods_lookup("ZZ1001") == ACTIVE


async def test_inactive_record_is_returned_with_active_false() -> None:
    record = await _terminology().ods_lookup("ZZ1002")
    assert record is not None
    assert record.active is False


async def test_unknown_code_returns_none() -> None:
    assert await _terminology().ods_lookup("ZZ9999") is None


async def test_code_lookup_ignores_case_and_surrounding_spaces() -> None:
    assert await _terminology().ods_lookup(" zz1001 ") == ACTIVE


async def test_display_is_found_by_system_and_code() -> None:
    assert await _terminology().display(SYSTEM, "A1") == "Example display"


async def test_display_for_the_same_code_in_another_system_is_not_found() -> None:
    assert await _terminology().display("urn:example:other", "A1") is None


async def test_unknown_display_returns_none() -> None:
    assert await _terminology().display(SYSTEM, "Z1") is None


def test_record_stored_under_another_code_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        FixedTerminology({"ZZ1001": CLOSED}, {})


async def test_pass_through_reports_no_issues() -> None:
    assert await PassThroughValidator().validate(RESOURCE, "https://example.org/Profile") == []


@pytest.mark.parametrize("profile", ["", "x", "https://example.org/other"])
async def test_pass_through_reports_no_issues_for_any_profile(profile: str) -> None:
    assert await PassThroughValidator().validate(RESOURCE, profile) == []


async def test_recording_validator_returns_its_preset_issues() -> None:
    assert await RecordingValidator([ISSUE]).validate(RESOURCE, "p") == [ISSUE]


async def test_recording_validator_with_no_issues_reports_valid() -> None:
    assert await RecordingValidator([]).validate(RESOURCE, "p") == []


async def test_recording_validator_keeps_each_call() -> None:
    validator = RecordingValidator([])
    await validator.validate(RESOURCE, "profile-a")
    await validator.validate(RESOURCE, "profile-b")
    assert validator.calls == [(RESOURCE, "profile-a"), (RESOURCE, "profile-b")]


async def test_recording_validator_returns_a_copy_of_its_issues() -> None:
    validator = RecordingValidator([ISSUE])
    returned = await validator.validate(RESOURCE, "p")
    returned.clear()
    assert await validator.validate(RESOURCE, "p") == [ISSUE]
