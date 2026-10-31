"""The echo of a report is worded in the tenant's zone (KI-415).

The recorded time and the next prompt are local times. They were read in London whatever the
tenant's zone; the zone now reaches `_echo_text`, and a source of zones reaches the use cases.
"""

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from diucs.application.use_cases.report_capacity import _echo_text
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    ServiceCategory,
)
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile

NEW_YORK = ZoneInfo("America/New_York")
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
AT = datetime(2026, 7, 1, 13, 12, tzinfo=UTC)  # 14:12 in London, 09:12 in New York
NEXT = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)  # 15:00 in London, 10:00 in New York
REPORT = CapacityReport(
    id="r-1",
    service_id="ucr-west",
    value=4,
    measure=Measure.REFERRALS_ACCEPTABLE,
    effective_at=AT,
    source=ReportSource.TEXT,
    report_type=ReportType.NUMBER,
)


def test_the_c3_echo_words_both_times_in_the_tenants_zone() -> None:
    message_id, text = _echo_text(PROFILE, REPORT, NEXT, None, NEW_YORK)

    assert message_id is MessageId.C3
    assert "09:12" in text and "10:00" in text
    assert "14:12" not in text and "15:00" not in text


def test_the_c4_echo_words_the_recorded_time_in_the_tenants_zone() -> None:
    message_id, text = _echo_text(PROFILE, REPORT, NEXT, 6, NEW_YORK)

    assert message_id is MessageId.C4
    assert "09:12" in text and "14:12" not in text


def test_london_is_the_default_zone() -> None:
    _, text = _echo_text(PROFILE, REPORT, NEXT, None)

    assert "14:12" in text and "15:00" in text
