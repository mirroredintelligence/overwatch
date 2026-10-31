"""How old a figure may be for a Y to confirm it, per service (DEC-1100 Q4, KI-27).

A daily ward or a twice-a-day service could never confirm with Y: its figure was older than two
hours when the prompt went out, so every Y was refused. The window is the larger of the tenant's
stale limit (two hours) and the service's own reporting interval, capped at 26 hours. [ASSUMED]
(DEC-1100: relaxing H-31 and H-32 is signed off with Q2.) A service that reports every two hours
keeps exactly the two hours it always had.
"""

import dataclasses
from datetime import time, timedelta

import pytest

from diucs.domain.codes import Cadence, Channel, Measure, ServiceCategory
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.confirmable_age import (
    MAX_CONFIRMABLE_AGE,
    REPORTING_INTERVAL,
    confirmable_age,
)


def _profile(cadence: Cadence) -> ServiceProfile:
    return ServiceProfile(
        id="svc",
        name="Sample Ward",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=cadence,
        available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
    )


def test_a_two_hourly_service_keeps_two_hours() -> None:
    assert confirmable_age(_profile(Cadence.EVERY_2_HRS), DEFAULT_POLICY) == timedelta(hours=2)


def test_a_twice_a_day_service_may_confirm_a_figure_from_its_longest_gap() -> None:
    # 08:00 and 14:00: the gaps are 6 and 18 hours; the 14:00 figure meets the next 08:00 prompt.
    assert confirmable_age(_profile(Cadence.TWICE_A_DAY), DEFAULT_POLICY) == timedelta(hours=18)


def test_a_once_a_day_service_may_confirm_a_figure_a_day_old() -> None:
    assert confirmable_age(_profile(Cadence.ONCE_A_DAY), DEFAULT_POLICY) == timedelta(hours=24)


def test_the_window_never_exceeds_twenty_six_hours() -> None:
    assert timedelta(hours=26) == MAX_CONFIRMABLE_AGE
    assert all(interval <= MAX_CONFIRMABLE_AGE for interval in REPORTING_INTERVAL.values())


def test_every_cadence_has_an_interval() -> None:
    assert set(REPORTING_INTERVAL) == set(Cadence)


def test_the_tenants_own_longer_stale_limit_is_the_floor_for_a_two_hourly_service() -> None:
    four_hours = dataclasses.replace(DEFAULT_POLICY, stale_warning_after=timedelta(hours=4))

    assert confirmable_age(_profile(Cadence.EVERY_2_HRS), four_hours) == timedelta(hours=4)
    assert confirmable_age(_profile(Cadence.ONCE_A_DAY), four_hours) == timedelta(hours=24)


def test_the_tenants_shorter_stale_limit_is_the_floor_for_a_two_hourly_service() -> None:
    short = dataclasses.replace(DEFAULT_POLICY, stale_warning_after=timedelta(hours=1))

    assert confirmable_age(_profile(Cadence.EVERY_2_HRS), short) == timedelta(hours=2)


@pytest.mark.parametrize("cadence", list(Cadence))
def test_the_window_is_never_below_the_tenants_stale_limit(cadence: Cadence) -> None:
    assert confirmable_age(_profile(cadence), DEFAULT_POLICY) >= DEFAULT_POLICY.stale_warning_after
