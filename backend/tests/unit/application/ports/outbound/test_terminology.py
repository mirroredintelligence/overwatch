"""Value objects of the terminology port (P11). ValidationIssue takes only FHIR severities."""

from typing import cast

import pytest

from diucs.application.ports.outbound.terminology import OdsRecord, Severity, ValidationIssue
from diucs.domain.errors import ValidationFailed


def _issue(severity: str) -> ValidationIssue:
    return ValidationIssue(
        cast(Severity, severity), "required", "Location.name", "Name is required"
    )


@pytest.mark.parametrize("severity", ["fatal", "error", "warning", "information"])
def test_each_fhir_severity_is_accepted(severity: str) -> None:
    assert _issue(severity).severity == severity


@pytest.mark.parametrize("severity", ["warn", "Error", "", "info"])
def test_other_severities_are_refused(severity: str) -> None:
    with pytest.raises(ValidationFailed) as info:
        _issue(severity)
    assert info.value.field == "severity"


def test_issue_keeps_its_path_and_message() -> None:
    issue = ValidationIssue("error", "required", "Location.name", "Name is required")
    assert (issue.code, issue.path, issue.message) == (
        "required",
        "Location.name",
        "Name is required",
    )


def test_ods_record_keeps_its_active_flag() -> None:
    record = OdsRecord("ZZ1001", "Example Community Team", False, "Community", None)
    assert record.active is False
    assert record.postcode is None
