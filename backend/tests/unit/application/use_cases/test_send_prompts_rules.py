"""SendPrompts: the closing-time prompt (Q3), the per-service confirmable age (Q4) and the label of
a lost race (KI-24). Pure helpers and stubs: no Neo4j.
"""

import dataclasses
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest

from diucs.application.use_cases.send_prompts import (
    RACED_MESSAGE,
    SKIP_OUT_OF_HOURS,
    _skip_reason,
    _too_old_to_confirm,
    store_prompt_result,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    Measure,
    ReportSource,
    ReportType,
    ServiceCategory,
)
from diucs.domain.errors import Conflict
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.service import AvailableTime, ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.london_time import local_to_utc

DAY = date(2026, 10, 23)
WINDOW = ("referrals", "in the next 2 hrs")
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
ONCE_A_DAY = dataclasses.replace(PROFILE, cadence=Cadence.ONCE_A_DAY)
TWICE_A_DAY = dataclasses.replace(PROFILE, cadence=Cadence.TWICE_A_DAY)


def _london(hour: int, minute: int = 0) -> datetime:
    return local_to_utc(DAY, time(hour, minute))


def _figure(effective_at: datetime) -> CapacityReport:
    return CapacityReport(
        id="obs-1",
        service_id="svc-west",
        value=3,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=effective_at,
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


# --- Q3: the prompt due at the closing time is sent ----------------------------------------------


def test_the_prompt_due_at_the_closing_time_is_not_skipped_as_out_of_hours() -> None:
    due = _london(20)

    reason = _skip_reason(PROFILE, False, due, due + timedelta(seconds=5), True, WINDOW)

    assert reason is None


def test_a_prompt_due_after_the_closing_time_is_still_out_of_hours() -> None:
    due = _london(20) + timedelta(microseconds=1)

    reason = _skip_reason(PROFILE, False, due, due + timedelta(seconds=5), True, WINDOW)

    assert reason == SKIP_OUT_OF_HOURS


def test_a_prompt_due_before_opening_is_still_out_of_hours() -> None:
    due = _london(7, 59)

    assert _skip_reason(PROFILE, False, due, due, True, WINDOW) == SKIP_OUT_OF_HOURS


# --- Q4: a figure may be as old as the service's own interval -------------------------------------


@pytest.mark.parametrize(
    ("profile", "age", "too_old"),
    [
        (PROFILE, timedelta(hours=2), False),
        (PROFILE, timedelta(hours=2, microseconds=1), True),
        (ONCE_A_DAY, timedelta(hours=20), False),
        (ONCE_A_DAY, timedelta(hours=24), False),
        (ONCE_A_DAY, timedelta(hours=24, microseconds=1), True),
        (TWICE_A_DAY, timedelta(hours=18), False),
        (TWICE_A_DAY, timedelta(hours=18, microseconds=1), True),
    ],
)
def test_a_figure_is_too_old_to_confirm_at_the_services_own_window(
    profile: ServiceProfile, age: timedelta, too_old: bool
) -> None:
    now = _london(10)

    assert _too_old_to_confirm(_figure(now - age), now, DEFAULT_POLICY, profile) is too_old


def test_without_a_profile_the_tenants_stale_limit_is_the_window() -> None:
    now = _london(10)

    assert _too_old_to_confirm(_figure(now - timedelta(hours=3)), now, DEFAULT_POLICY) is True
    assert _too_old_to_confirm(_figure(now - timedelta(hours=2)), now, DEFAULT_POLICY) is False


# --- KI-24: a lost race says so ------------------------------------------------------------------


class _Idempotency:
    def __init__(self, error: Exception | None) -> None:
        self._error = error
        self.stored: dict[str, Any] = {}

    async def put(self, key: str, value: Any) -> None:
        if self._error is not None:
            raise self._error
        self.stored[key] = value


class _Unit:
    def __init__(self, error: Exception | None = None) -> None:
        self.idempotency = _Idempotency(error)


async def test_a_lost_race_is_a_conflict_that_says_another_request_sent_the_prompt() -> None:
    unit = _Unit(Conflict("a different result is already stored for this command key"))

    with pytest.raises(Conflict) as refused:
        await store_prompt_result(unit, "prompt:key", object())  # type: ignore[arg-type]

    assert str(refused.value) == RACED_MESSAGE
    assert "different result" not in str(refused.value)


async def test_a_result_that_can_be_stored_is_stored() -> None:
    unit = _Unit()
    marker = object()

    await store_prompt_result(unit, "prompt:key", marker)  # type: ignore[arg-type]

    assert unit.idempotency.stored == {"prompt:key": marker}


async def test_any_other_error_of_the_store_is_not_relabelled() -> None:
    unit = _Unit(RuntimeError("the store is down"))

    with pytest.raises(RuntimeError):
        await store_prompt_result(unit, "prompt:key", object())  # type: ignore[arg-type]


def test_the_sample_times_are_utc() -> None:
    assert _london(20).tzinfo is UTC or _london(20).utcoffset() == timedelta(0)
