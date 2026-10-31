"""The effective time of a report or a confirmation against the figures on record (KI-7, KI-8, KI-9,
KI-415; DEC-1100 Q8), on the real Neo4j the harness starts.

- An explicit time equal to the latest confirmed figure is refused, like one before it (KI-7).
- An explicit time that is not later than the latest figure of any kind is refused, and the refusal
  names the latest figure's time (Q8, KI-9): the reporter is never told a number was taken when the
  board would ignore it.
- A figure with no explicit time is taken at the clock but never at or before the latest figure's
  time, for a report and for a confirmation (KI-8).
- The echo's times are the tenant's local times (KI-415).

Sample values only; UCR West is seeded with a number of 3 at 08:15 London on 23 October 2026.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity, ConfirmCapacityCommand
from diucs.application.use_cases.report_capacity import ReportCapacity, ReportCapacityCommand
from diucs.domain.codes import ReportSource, ReportType
from diucs.domain.errors import (
    Conflict,
    EffectiveBeforeConfirmation,
    EffectiveNotAfterLatest,
    ValidationFailed,
)
from diucs.domain.model.capacity import CapacityReport
from tests.integration.application.test_confirm_capacity import (
    AT_1005,
    AT_1205,
    REPORT_AT,
    REPORTER,
    SEED_REPORT_ID,
    Rig,
    Seed,
    _latest,
    _seed_report,
    _seed_with_report,
)
from tests.integration.application.test_confirm_capacity import (
    _outbox as outbox_of,
)
from tests.support.neo4j import count_nodes

pytestmark = pytest.mark.asyncio(loop_scope="session")

ONE_MICROSECOND = timedelta(microseconds=1)
NEW_YORK = ZoneInfo("America/New_York")


def _report_at(
    _rig: Rig, key: str, value: int, effective_at: datetime | None
) -> ReportCapacityCommand:
    return ReportCapacityCommand(
        idempotency_key=key,
        actor=REPORTER,
        service_id="ucr-west",
        value=value,
        source=ReportSource.TEXT,
        effective_at=effective_at,
    )


async def _nothing_written(
    factory: UnitOfWorkFactory, driver: AsyncDriver, observations: int, outbox: int, audits: int
) -> None:
    assert await count_nodes(driver, "Observation") == observations
    assert len(await outbox_of(factory)) == outbox
    assert await count_nodes(driver, "AuditEvent") == audits


# --- KI-7: equal to the latest confirmed figure --------------------------------------------------


async def test_an_explicit_time_equal_to_the_latest_confirmed_figure_is_refused_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    await rig.yes(AT_1005, "k1")
    before = (
        await count_nodes(neo4j_driver, "Observation"),
        len(await outbox_of(uow_factory)),
        await count_nodes(neo4j_driver, "AuditEvent"),
    )
    rig.clock.set(AT_1205)

    with pytest.raises(EffectiveBeforeConfirmation) as refused:
        await rig.report.execute(_report_at(rig, "tie-1", 5, AT_1005))

    assert refused.value.latest_at == AT_1005
    await _nothing_written(uow_factory, neo4j_driver, *before)


async def test_an_explicit_time_one_microsecond_after_the_latest_confirmed_figure_is_accepted(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    await rig.yes(AT_1005, "k1")
    rig.clock.set(AT_1205)

    result = await rig.report.execute(_report_at(rig, "later-1", 5, AT_1005 + ONE_MICROSECOND))

    latest = await _latest(uow_factory)
    assert latest is not None and latest.id == result.report_id
    assert latest.effective_at == AT_1005 + ONE_MICROSECOND


# --- Q8, KI-9: behind or equal to a later number --------------------------------------------------


async def test_a_number_dated_before_the_latest_number_is_refused_naming_that_time(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    before = (
        await count_nodes(neo4j_driver, "Observation"),
        len(await outbox_of(uow_factory)),
        await count_nodes(neo4j_driver, "AuditEvent"),
    )
    rig.clock.set(AT_1205)

    with pytest.raises(EffectiveNotAfterLatest) as refused:
        await rig.report.execute(_report_at(rig, "back-1", 5, REPORT_AT - timedelta(minutes=1)))

    assert not isinstance(refused.value, EffectiveBeforeConfirmation)
    assert isinstance(refused.value, ValidationFailed)
    assert refused.value.field == "effective_at"
    assert refused.value.latest_at == REPORT_AT
    # 07:15 UTC is 08:15 in London: the reporter is told the latest figure's time in local words.
    assert "23 Oct 08:15" in refused.value.message
    await _nothing_written(uow_factory, neo4j_driver, *before)


async def test_a_number_dated_at_the_latest_numbers_time_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    rig.clock.set(AT_1205)

    with pytest.raises(EffectiveNotAfterLatest):
        await rig.report.execute(_report_at(rig, "tie-2", 5, REPORT_AT))


async def test_a_number_dated_just_after_the_latest_number_is_accepted(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    rig.clock.set(AT_1205)

    result = await rig.report.execute(_report_at(rig, "ok-1", 5, REPORT_AT + ONE_MICROSECOND))

    latest = await _latest(uow_factory)
    assert latest is not None and latest.id == result.report_id


async def test_any_explicit_time_is_accepted_when_the_service_has_no_figure(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, None)
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    rig.clock.set(AT_1205)

    await rig.report.execute(_report_at(rig, "first-1", 5, REPORT_AT - timedelta(days=3)))

    latest = await _latest(uow_factory)
    assert latest is not None and latest.effective_at == REPORT_AT - timedelta(days=3)


async def test_a_key_used_by_a_confirmation_is_a_conflict_before_the_time_is_judged(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """A key that another command used is refused as a Conflict first, like ConfirmCapacity does,
    so the answer does not depend on a time that was refused for another reason."""
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    await rig.yes(AT_1005, "shared-key")

    with pytest.raises(Conflict):
        await rig.report.execute(_report_at(rig, "shared-key", 5, AT_1005))


# --- KI-8: the default time never precedes a figure on record -------------------------------------


def _seed_ahead(minutes: int) -> CapacityReport:
    """A figure written by a host whose clock runs ahead of this one."""
    return CapacityReport(
        id=SEED_REPORT_ID,
        service_id="ucr-west",
        value=3,
        measure=_seed_report().measure,
        effective_at=AT_1005 + timedelta(minutes=minutes),
        source=ReportSource.TEXT,
        report_type=ReportType.NUMBER,
    )


async def test_a_number_with_no_time_is_taken_just_after_a_figure_dated_ahead_of_the_clock(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_ahead(5))
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    rig.clock.set(AT_1005)

    result = await rig.report.execute(_report_at(rig, "default-1", 6, None))

    latest = await _latest(uow_factory)
    assert latest is not None and latest.id == result.report_id
    assert latest.value == 6
    assert latest.effective_at == AT_1005 + timedelta(minutes=5) + ONE_MICROSECOND


async def test_a_number_with_no_time_is_taken_at_the_clock_when_the_clock_is_later(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    rig.clock.set(AT_1005)

    await rig.report.execute(_report_at(rig, "default-2", 6, None))

    latest = await _latest(uow_factory)
    assert latest is not None and latest.effective_at == AT_1005


async def test_a_confirmation_is_taken_just_after_a_figure_dated_ahead_of_the_clock(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_ahead(5))
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())

    result = await rig.yes(AT_1005, "yes-ahead")

    latest = await _latest(uow_factory)
    assert latest is not None and latest.id == result.report_id
    assert latest.report_type is ReportType.CONFIRMED
    assert latest.effective_at == AT_1005 + timedelta(minutes=5) + ONE_MICROSECOND


async def test_a_confirmation_with_the_clock_later_is_taken_at_the_clock(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())

    await rig.yes(AT_1005, "yes-now")

    latest = await _latest(uow_factory)
    assert latest is not None and latest.effective_at == AT_1005


# --- KI-415: the tenant's zone in the echo -------------------------------------------------------


class _NewYork:
    async def zone_of(self, scope: ScopeId) -> ZoneInfo:
        return NEW_YORK


async def test_the_c3_echo_of_a_report_is_worded_in_the_tenants_zone(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, None)
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    rig.clock.set(AT_1005)  # 09:05 UTC: 05:05 in New York, 10:05 in London
    use_case = ReportCapacity(
        uow_factory,
        rig.clock,
        SequentialIds("z"),
        DriverIdempotencyStore(neo4j_driver),
        zones=_NewYork(),
    )

    await use_case.execute(
        ReportCapacityCommand(
            idempotency_key="zone-1",
            actor=REPORTER,
            service_id="ucr-west",
            value=4,
            source=ReportSource.TEXT,
            performer_role_id="role-1",
        )
    )

    sends = [m for m in await outbox_of(uow_factory) if m.event_type == "SendMessage"]
    assert len(sends) == 1
    text = sends[0].payload["text"]
    assert "05:05" in text and "10:05" not in text
    # The service is open 08:00 to 20:00 local: in New York the next prompt is 08:00, not London's.
    assert "Next prompt 08:00." in text


async def test_the_c3_echo_of_a_confirmation_is_worded_in_the_tenants_zone(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_with_report(uow_factory, seed_service, _seed_report())
    rig = Rig(uow_factory, neo4j_driver, SequentialIds())
    rig.clock.set(AT_1005)
    use_case = ConfirmCapacity(
        uow_factory,
        rig.clock,
        SequentialIds("z"),
        DriverIdempotencyStore(neo4j_driver),
        zones=_NewYork(),
    )

    await use_case.execute(
        ConfirmCapacityCommand(
            idempotency_key="zone-2",
            actor=REPORTER,
            service_id="ucr-west",
            source=ReportSource.TEXT,
            performer_role_id="role-1",
        )
    )

    sends = [m for m in await outbox_of(uow_factory) if m.event_type == "SendMessage"]
    assert len(sends) == 1
    assert "05:05" in sends[0].payload["text"]
    assert "10:05" not in sends[0].payload["text"]
