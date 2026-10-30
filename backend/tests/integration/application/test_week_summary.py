"""Integration tests for the week summary (U35), against the real Neo4j the harness starts.

Seeds a few cases, reports, bookings and prompts through the ports, then reads the summary. The
counts are small so the suite stays quick; the percentages and the medians at the sample sizes of
the prompt (640 cases, 448 prompts) are pinned by the pure tests in
tests/unit/application/test_week_summary_rules.py. Values are synthetic: no patient data.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.week_summary import GetWeekSummary, GetWeekSummaryCommand
from diucs.domain.codes import (
    BestFitNotUsedReason,
    Cadence,
    Channel,
    Measure,
    Outcome,
    ReportSource,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import NotAllowed
from diucs.domain.model.booking import Booking
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.case import Case
from diucs.domain.model.service import AvailableTime, ServiceProfile
from tests.support import seed
from tests.support.actors import ACTOR_TENANT

Seed = Callable[..., Awaitable[None]]
pytestmark = pytest.mark.asyncio(loop_scope="session")

MONDAY = date(2026, 10, 19)
SERVICE = "ucr-west"
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
REPORTER = Actor(
    role=Role.REPORTER,
    practitioner_id="prac-reporter",
    device_id=None,
    channel="text",
    service_ids=frozenset({SERVICE}),
    tenant_id=ACTOR_TENANT,
)
UCR_WEST = ServiceProfile(
    id=SERVICE,
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
MIDWEEK = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Settings:
    minutes_per_avoided_call: int | None


def _summary(uow_factory: UnitOfWorkFactory, minutes: int | None = 4) -> GetWeekSummary:
    return GetWeekSummary(uow_factory, Settings(minutes), FixedClock(MIDWEEK))


async def _seed(
    uow_factory: UnitOfWorkFactory,
    *,
    cases: tuple[Case, ...] = (),
    reports: tuple[CapacityReport, ...] = (),
    bookings: tuple[Booking, ...] = (),
    prompts: tuple[Communication, ...] = (),
) -> None:
    async with uow_factory() as uow:
        for case in cases:
            await uow.cases.add(case)
        for report in reports:
            await uow.capacity.add(report)
        for booking in bookings:
            await uow.bookings.add(booking)
        for prompt in prompts:
            await uow.communications.add(prompt)
        await uow.commit()


async def test_referrals_and_the_share_with_the_best_fit_not_available(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    cases = [seed.case(n, MIDWEEK) for n in range(8)]
    cases.append(seed.case(8, MIDWEEK, Outcome.NO_SERVICE_FITS))
    cases.append(seed.case(9, MIDWEEK, Outcome.DECLINED, BestFitNotUsedReason.FULL))
    await _seed(uow_factory, cases=tuple(cases))
    summary = await _summary(uow_factory).execute(GetWeekSummaryCommand(LEAD, MONDAY))
    assert summary.referrals.value == 10
    assert summary.best_fit_unavailable_pct.value == 20


async def test_the_on_time_share_counts_reports_inside_the_reply_by(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    prompts = [seed.prompt(n, SERVICE, MIDWEEK) for n in range(10)]
    on_time = [seed.report(n, SERVICE, MIDWEEK + timedelta(minutes=5)) for n in range(9)]
    late = [seed.report(20, SERVICE, MIDWEEK + timedelta(hours=2))]
    await _seed(uow_factory, prompts=tuple(prompts), reports=(*on_time, *late))
    summary = await _summary(uow_factory).execute(GetWeekSummaryCommand(LEAD, MONDAY))
    assert summary.on_time_pct.value == 90


async def test_the_median_minutes_to_a_confirmed_booking_over_ten_bookings(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    requested = MIDWEEK
    minutes = [3, 4, 4, 4, 4, 4, 4, 5, 6, 8]
    bookings = [
        seed.booking(n, SERVICE, requested, requested + timedelta(minutes=m))
        for n, m in enumerate(minutes)
    ]
    await _seed(uow_factory, bookings=tuple(bookings))
    summary = await _summary(uow_factory).execute(GetWeekSummaryCommand(LEAD, MONDAY))
    assert summary.median_minutes_to_confirmed.value == 4


async def test_seven_email_updates_are_hidden_and_text_updates_of_twelve_are_shown(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    reports = [seed.report(n, SERVICE, MIDWEEK, ReportSource.EMAIL) for n in range(7)]
    reports += [seed.report(20 + n, SERVICE, MIDWEEK, ReportSource.TEXT) for n in range(12)]
    await _seed(uow_factory, reports=tuple(reports))
    summary = await _summary(uow_factory).execute(GetWeekSummaryCommand(LEAD, MONDAY))
    assert summary.updates_by_channel["email/link"].hidden is True
    assert summary.updates_by_channel["text"].value == 12


async def test_the_clock_change_week_includes_sunday_night_and_excludes_monday_just_after(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    sunday_2330 = datetime(2026, 10, 25, 23, 30, tzinfo=UTC)  # 23:30 London, on GMT
    monday_0010 = datetime(2026, 10, 26, 0, 10, tzinfo=UTC)  # 00:10 London, on Monday
    cases = [seed.case(n, sunday_2330) for n in range(10)] + [seed.case(10, monday_0010)]
    await _seed(uow_factory, cases=tuple(cases))
    summary = await _summary(uow_factory).execute(GetWeekSummaryCommand(LEAD, MONDAY))
    assert summary.referrals.value == 10


async def test_an_unset_minutes_per_call_shows_the_placeholder(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed(
        uow_factory,
        reports=tuple(seed.report(n, SERVICE, MIDWEEK, ReportSource.TEXT) for n in range(10)),
    )
    summary = await _summary(uow_factory, minutes=None).execute(GetWeekSummaryCommand(LEAD, MONDAY))
    assert "[x]" in summary.time_back_text
    assert "Estimate" in summary.time_back_text


async def test_a_reporter_may_not_read_the_week_summary(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    with pytest.raises(NotAllowed):
        await _summary(uow_factory).execute(GetWeekSummaryCommand(REPORTER, MONDAY))


async def test_each_range_read_returns_the_records_inside_the_window_and_not_after_it(
    uow_factory: UnitOfWorkFactory, seed_service: Seed
) -> None:
    """The four range reads the summary uses, each on one inside and one outside record."""
    await seed_service(UCR_WEST)
    inside_start = MIDWEEK - timedelta(hours=1)
    inside_end = MIDWEEK + timedelta(hours=1)
    await _seed(
        uow_factory,
        cases=(seed.case(1, MIDWEEK), seed.case(2, MIDWEEK + timedelta(days=3))),
        reports=(
            seed.report(1, SERVICE, MIDWEEK),
            seed.report(2, SERVICE, MIDWEEK + timedelta(days=3)),
        ),
        bookings=(
            seed.booking(1, SERVICE, MIDWEEK, MIDWEEK + timedelta(minutes=4)),
            seed.booking(2, SERVICE, MIDWEEK, MIDWEEK + timedelta(days=3)),
        ),
        prompts=(
            seed.prompt(1, SERVICE, MIDWEEK),
            seed.prompt(2, SERVICE, MIDWEEK + timedelta(days=3)),
        ),
    )
    async with uow_factory() as uow:
        cases = await uow.cases.opened_between(inside_start, inside_end)
        reports = await uow.capacity.reports_between(inside_start, inside_end)
        bookings = await uow.bookings.confirmed_between(inside_start, inside_end)
        prompts = await uow.communications.prompts_due_between(inside_start, inside_end)
    assert [case.id for case in cases] == ["case-1"]
    assert [report.id for report in reports] == ["obs-1"]
    assert [booking.id for booking in bookings] == ["bk-1"]
    assert [(prompt.service_id, prompt.due_at) for prompt in prompts] == [(SERVICE, MIDWEEK)]
