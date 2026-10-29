"""The refusals of report flags (U07) that are decided before anything is read or written.

No Neo4j: each case hands the use case a unit of work that fails the test if it is touched.
"""

from datetime import UTC, datetime, time
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.use_cases.report_capacity import ReportCapacity, ReportCapacityCommand
from diucs.application.use_cases.report_flags import raise_report_flags
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportFlagReason,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
    Status,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)

PROFILE = ServiceProfile(
    id="ucr-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-reporter-1",
    device_id="device-1",
    channel="text",
    service_ids=frozenset({"ucr-west"}),
)


class _Untouched:
    """Fails the test when anything on it is read, called or written."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the unit of work was touched: {name}")

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the unit of work factory was called")


class _NoReplay:
    async def get(self, key: str) -> None:
        return None

    async def put(self, key: str, result: object) -> None:
        raise AssertionError("nothing may be stored")


async def test_a_report_for_another_service_than_the_profile_is_refused_before_any_read() -> None:
    report = CapacityReport(
        id="obs-1",
        service_id="ward-a",
        value=4,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=NOW,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )

    with pytest.raises(ValidationFailed, match="report: is not for this service"):
        await raise_report_flags(
            _Untouched(),  # type: ignore[arg-type]
            SequentialIds(),
            profile=PROFILE,
            report=report,
            extra=None,
            now=NOW,
        )


@pytest.mark.parametrize(
    "flag",
    ["many-changes", "out-of-range-twice", "", "Jane Smith", Status.ACCEPTING, 7],
    ids=["a string", "another string", "empty", "a name", "another enum", "a number"],
)
async def test_a_flag_that_is_not_a_flag_reason_is_refused_before_any_lock(flag: object) -> None:
    use_case = ReportCapacity(
        _Untouched(),  # type: ignore[arg-type]
        FixedClock(NOW),
        SequentialIds(),
        _NoReplay(),
    )

    with pytest.raises(ValidationFailed, match="flag: must be a report flag reason") as refused:
        await use_case.execute(
            ReportCapacityCommand(
                idempotency_key="key-1",
                actor=REPORTER,
                service_id="ucr-west",
                value=4,
                source=ReportSource.TEXT,
                flag=flag,  # type: ignore[arg-type]
            )
        )

    assert refused.value.field == "flag"


def test_the_known_reasons_are_the_three_of_the_rule_book() -> None:
    assert {reason.value for reason in ReportFlagReason} == {
        "out-of-range-twice",
        "many-changes",
        "differs-from-phoned",
    }
