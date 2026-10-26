"""Pure tests for the report and service flag records (P14). Values are synthetic."""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from diucs.domain.codes import ReportFlagReason
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.flags import (
    REPORT_FLAG_ACCEPTED,
    REPORT_FLAG_CHECKED,
    REPORT_FLAG_OPEN,
    SERVICE_FLAG_CRITERIA_OVERDUE,
    SERVICE_FLAG_SUSPENDED,
    ReportFlag,
    ServiceFlag,
)

LONDON = ZoneInfo("Europe/London")
CREATED = datetime(2026, 10, 25, 9, 14, tzinfo=UTC)
RESOLVED = datetime(2026, 10, 25, 9, 40, tzinfo=UTC)


def _open_flag(**changes: object) -> ReportFlag:
    values: dict[str, object] = {
        "id": "rf-0001",
        "report_id": "obs-ucr-west-0912",
        "service_id": "svc-ucr-west",
        "reason": ReportFlagReason.OUT_OF_RANGE_TWICE,
        "status": REPORT_FLAG_OPEN,
        "created_at": CREATED,
    }
    values.update(changes)
    return ReportFlag(**values)  # type: ignore[arg-type]


def _service_flag(**changes: object) -> ServiceFlag:
    values: dict[str, object] = {
        "service_id": "svc-ucr-west",
        "code": SERVICE_FLAG_SUSPENDED,
        "active": True,
        "reason": "Staffing shortfall",
        "actor_id": "role-ucr-west-lead",
        "at": CREATED,
    }
    values.update(changes)
    return ServiceFlag(**values)  # type: ignore[arg-type]


def test_an_open_and_a_resolved_report_flag_are_built() -> None:
    assert _open_flag().resolved_at is None
    resolved = _open_flag(
        status=REPORT_FLAG_CHECKED, resolved_at=RESOLVED, outcome="phoned, figure right"
    )
    assert resolved.outcome == "phoned, figure right"


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"status": "closed"}, "status"),
        ({"id": ""}, "id"),
        ({"report_id": ""}, "report_id"),
        ({"service_id": ""}, "service_id"),
        ({"reason": "many-changes"}, "reason"),
        ({"created_at": datetime(2026, 10, 25, 9, 14)}, "created_at"),
        ({"resolved_at": RESOLVED}, "resolved_at"),
        ({"status": REPORT_FLAG_CHECKED}, "resolved_at"),
        (
            {"status": REPORT_FLAG_CHECKED, "resolved_at": CREATED - timedelta(minutes=1)},
            "resolved_at",
        ),
        (
            {"status": REPORT_FLAG_ACCEPTED, "resolved_at": datetime(2026, 10, 25, 9, 40)},
            "resolved_at",
        ),
        ({"outcome": ""}, "outcome"),
    ],
)
def test_a_report_flag_that_breaks_a_rule_is_refused_naming_the_field(
    changes: dict[str, object], field: str
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _open_flag(**changes)
    assert refused.value.field == field


def test_a_report_flag_time_is_held_as_utc_whatever_zone_it_came_in() -> None:
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=LONDON)  # 11:00 UTC, on British Summer Time
    flag = _open_flag(created_at=summer)
    assert flag.created_at == datetime(2026, 7, 1, 11, 0, tzinfo=UTC)
    assert flag.created_at.utcoffset() == timedelta(0)


def test_a_service_flag_is_built_active_and_inactive() -> None:
    assert _service_flag().active is True
    assert _service_flag(code=SERVICE_FLAG_CRITERIA_OVERDUE, active=False).active is False


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"code": "closed"}, "code"),
        ({"code": "Suspended"}, "code"),
        ({"service_id": ""}, "service_id"),
        ({"reason": ""}, "reason"),
        ({"actor_id": ""}, "actor_id"),
        ({"active": "yes"}, "active"),
        ({"at": datetime(2026, 10, 25, 9, 14)}, "at"),
    ],
)
def test_a_service_flag_that_breaks_a_rule_is_refused_naming_the_field(
    changes: dict[str, object], field: str
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _service_flag(**changes)
    assert refused.value.field == field


def test_a_service_flag_time_is_held_as_utc() -> None:
    flag = _service_flag(at=datetime(2026, 10, 25, 2, 2, tzinfo=timezone(timedelta(hours=1))))
    assert flag.at == datetime(2026, 10, 25, 1, 2, tzinfo=UTC)
    assert flag.at.utcoffset() == timedelta(0)
