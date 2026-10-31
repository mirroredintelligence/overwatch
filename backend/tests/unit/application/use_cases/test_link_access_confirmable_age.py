"""A link Y is judged against the service's own confirmable age, like a Y by text (Q4, KI-27)."""

import dataclasses
from datetime import UTC, datetime, time, timedelta

import pytest

from diucs.application.use_cases.link_access import SendTheNumber, judge
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    ServiceCategory,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.rules.reply_policy import RecordConfirm

PROMPT = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
PROFILE = ServiceProfile(
    id="svc-west",
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals in the next 2 hrs",
    established_capacity=8,
    can_exceed_established=False,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    limited_level_percent=80,
)
DAILY = dataclasses.replace(PROFILE, cadence=Cadence.ONCE_A_DAY)


def _figure(age: timedelta) -> CapacityReport:
    return CapacityReport(
        id="obs-1",
        service_id="svc-west",
        value=3,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=PROMPT - age,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


def test_a_daily_service_may_confirm_a_figure_twenty_hours_old() -> None:
    decision = judge(RecordConfirm(), DAILY, _figure(timedelta(hours=20)), PROMPT, False)

    assert isinstance(decision, RecordConfirm)


def test_a_daily_service_may_not_confirm_a_figure_past_its_day() -> None:
    with pytest.raises(SendTheNumber) as refused:
        judge(RecordConfirm(), DAILY, _figure(timedelta(hours=24, microseconds=1)), PROMPT, False)

    assert str(refused.value) == "stale"


def test_a_two_hourly_service_keeps_its_two_hours() -> None:
    assert isinstance(
        judge(RecordConfirm(), PROFILE, _figure(timedelta(hours=2)), PROMPT, False), RecordConfirm
    )
    with pytest.raises(SendTheNumber):
        judge(RecordConfirm(), PROFILE, _figure(timedelta(hours=3)), PROMPT, False)
