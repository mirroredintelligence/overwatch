"""The case summary (H-322), against the real Neo4j.

The summary to copy into the referral names the destination the advisor is referring to, whether a
booking was made there for this case and how old the destination's figure was. Without a
destination those rows are left out. A booking of another case, or one that did not hold, is not a
booked line. Another tenant's case and service read as unknown; a closed case has no summary.
Synthetic values only; the postcode row is the district.
"""

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.case_summary import (
    BuildCaseSummary,
    BuildCaseSummaryQuery,
    CaseSummary,
)
from diucs.application.use_cases.query_board import QueryBoard
from diucs.domain.codes import BookingStatus, Outcome, Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound
from diucs.domain.model.booking import Booking
from tests.integration.application.test_filter_options import (
    ACTOR,
    CASE_ID,
    NOW,
    UCR_EAST,
    UCR_WEST,
    _case,
    _profile,
    _report,
)
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

REQUESTED = datetime(2026, 10, 23, 13, 5, tzinfo=UTC)  # 14:05 London (summer time in October)


def _booking(
    booking_id: str, service: str, case: str, status: BookingStatus, **extra: object
) -> Booking:
    return Booking(
        id=booking_id,
        reference=f"48{booking_id[-2:]}",
        service_id=service,
        case_id=case,
        requester_id="prac-advisor-1",
        status=status,
        requested_at=REQUESTED,
        reply_by=REQUESTED + timedelta(minutes=30),
        **extra,  # type: ignore[arg-type]
    )


async def _seed(factory: UnitOfWorkFactory, driver: AsyncDriver, tenant: str) -> None:
    await ensure_audit_heads(driver, tenant)
    west, east = _profile(UCR_WEST, "UCR West"), _profile(UCR_EAST, "UCR East")
    async with factory() as uow:
        await uow.services.save(west)
        await uow.services.save(east)
        await uow.capacity.add(
            _report("obs-west", west, 4, datetime(2026, 10, 23, 13, 4, tzinfo=UTC))
        )
        await uow.cases.add(_case())
        await uow.commit()


async def _summary(
    factory: UnitOfWorkFactory,
    destination: str | None = None,
    case_id: str = CASE_ID,
    actor=ACTOR,  # type: ignore[no-untyped-def]
) -> CaseSummary:
    clock = FixedClock(NOW)
    return await BuildCaseSummary(factory, clock, QueryBoard(factory, clock)).execute(
        BuildCaseSummaryQuery(actor, case_id, destination)
    )


def _rows(summary: CaseSummary) -> dict[str, str]:
    return dict(summary.rows)


async def test_without_a_destination_the_destination_booking_and_data_age_rows_are_left_out(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    rows = _rows(await _summary(uow_factory))

    assert {"Referrer", "Age band", "Postcode", "Needs", "Urgency"} <= set(rows)
    assert not {"Destination", "Booked", "Data age"} & set(rows)
    assert rows["Postcode"] == "DT4"


async def test_a_destination_with_a_booking_for_this_case_is_named_with_the_booking_and_data_age(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.bookings.add(
            _booking(
                "bk-01",
                UCR_WEST,
                CASE_ID,
                BookingStatus.CONFIRMED,
                confirmed_at=REQUESTED + timedelta(minutes=12),
                responded_at=REQUESTED + timedelta(minutes=12),
            )
        )
        await uow.commit()

    summary = await _summary(uow_factory, UCR_WEST)

    rows = _rows(summary)
    assert summary.reference == "4821"
    assert rows["Destination"] == "UCR West"
    assert rows["Booked"] == "Confirmed 14:17"
    assert rows["Data age"] == "9 min ago"
    assert [label for label, _ in summary.rows][-3:] == ["Destination", "Booked", "Data age"]


async def test_a_destination_with_no_booking_has_no_booked_row(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    rows = _rows(await _summary(uow_factory, UCR_WEST))

    assert rows["Destination"] == "UCR West"
    assert "Booked" not in rows


async def test_a_destination_that_never_reported_says_no_figure_reported(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    rows = _rows(await _summary(uow_factory, UCR_EAST))

    assert rows["Data age"] == "No figure reported"


async def test_a_booking_of_another_case_at_the_same_service_is_not_this_cases_booking(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.cases.add(_case(case_id="case-other", reference="4999"))
        await uow.bookings.add(_booking("bk-02", UCR_WEST, "case-other", BookingStatus.REQUESTED))
        await uow.commit()

    assert "Booked" not in _rows(await _summary(uow_factory, UCR_WEST))


@pytest.mark.parametrize("status", [BookingStatus.REQUESTED])
async def test_a_requested_booking_says_it_is_waiting(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, status: BookingStatus
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.bookings.add(_booking("bk-03", UCR_WEST, CASE_ID, status))
        await uow.commit()

    rows = _rows(await _summary(uow_factory, UCR_WEST))

    assert rows["Booked"] == "Requested 14:05, waiting for the service to confirm"


async def test_a_declined_booking_is_not_a_booked_line(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        await uow.bookings.add(
            _booking(
                "bk-04",
                UCR_WEST,
                CASE_ID,
                BookingStatus.DECLINED,
                responded_at=REQUESTED + timedelta(minutes=3),
            )
        )
        await uow.commit()

    assert "Booked" not in _rows(await _summary(uow_factory, UCR_WEST))


async def test_a_destination_that_is_unknown_is_not_found(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    with pytest.raises(NotFound):
        await _summary(uow_factory, "svc-nowhere")


async def test_another_tenants_service_is_the_same_not_found_as_an_unknown_one(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    await ensure_audit_heads(neo4j_driver, other_tenant_id)
    async with uow_factory_b() as uow:
        await uow.services.save(_profile("svc-b-only", "Org B Service"))
        await uow.commit()

    with pytest.raises(NotFound):
        await _summary(uow_factory, "svc-b-only")


async def test_an_unknown_case_is_not_found(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    with pytest.raises(NotFound):
        await _summary(uow_factory, case_id="no-such-case")


async def test_another_tenants_case_is_not_found(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    async with uow_factory_b() as uow:
        await uow.cases.add(_case(case_id="case-of-b", reference="7391"))
        await uow.commit()

    with pytest.raises(NotFound):
        await _summary(uow_factory, case_id="case-of-b")


async def test_a_closed_case_has_no_summary(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)
    async with uow_factory() as uow:
        case = await uow.cases.get(CASE_ID)
        assert case is not None
        await uow.cases.save(case.close(Outcome.DECLINED, NOW))
        await uow.commit()

    with pytest.raises(Conflict):
        await _summary(uow_factory)


@pytest.mark.parametrize("role", [Role.REPORTER, Role.LEAD, Role.OWNER, Role.EXEC, Role.WALL])
async def test_a_role_that_is_not_an_advisor_or_a_clinician_is_refused(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, role: Role
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    with pytest.raises(NotAllowed):
        await _summary(uow_factory, actor=dataclasses.replace(ACTOR, role=role))


async def test_the_summary_never_holds_the_full_postcode(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed(uow_factory, neo4j_driver, tenant_id)

    text = repr(await _summary(uow_factory, UCR_WEST))

    assert "DT4 8XX" not in text
