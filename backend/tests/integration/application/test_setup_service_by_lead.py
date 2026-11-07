"""Integration tests for SetupServiceByLead (U15), against the real Neo4j the harness starts.

Every assertion reads back through fresh units of work, or with a raw read of the graph, so it
checks what was really stored (DEC-004). The reporter's number is a sample value; it must appear
only in its protected contact node. Clock: Thursday 29 October 2026 at 09:10 London (GMT).

Tenancy (DEC-130 to DEC-134): the lead's practitioner and the phone hash are looked up inside the
bound tenant, so another tenant's practitioner is neither used nor reused.
"""

import dataclasses
from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from overwatch.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from overwatch.adapters.testing.fixed_clock import FixedClock
from overwatch.adapters.testing.fixed_ids import SequentialIds
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore
from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.use_cases.duty_roster import (
    AddRosterManager,
    AddRosterManagerCommand,
    CheckIn,
    ListRoster,
    put_on_roster,
)
from overwatch.application.use_cases.query_board import QueryBoard, QueryBoardQuery
from overwatch.application.use_cases.send_prompts import _reporters
from overwatch.application.use_cases.setup_service_by_lead import (
    SetupServiceByLead,
    SetupServiceCommand,
    SetupServiceResult,
    build_profile,
)
from overwatch.application.work import WorkKind
from overwatch.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    PractitionerRoleCode,
    ReportSource,
    ReportType,
    Role,
    ServiceCategory,
    Status,
)
from overwatch.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from overwatch.domain.model.capacity import CapacityReport
from overwatch.domain.model.people import Practitioner, RosterState
from overwatch.domain.model.service import AvailableTime
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, read_tx, run_nodes
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def audit_heads(
    neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str, clean_graph: None
) -> None:
    """A fresh container, then each tenant's audit chain head: set-up writes an audit entry, and
    the cross-tenant test reads back in the other tenant."""
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)


NOW = datetime(2026, 10, 29, 9, 10, tzinfo=UTC)
FIRST_PROMPT = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
NUMBER = "07700 900123"
STORED_NUMBER = "+447700900123"
PHONE_SECRET = b"sample-phone-hash-secret"

LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
ADVISOR = dataclasses.replace(LEAD, role=Role.ADVISOR, practitioner_id="prac-advisor-1")

UCR_WEST = SetupServiceCommand(
    idempotency_key="setup-ucr-west",
    actor=LEAD,
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    reporter_role_name="Duty manager",
    age_min=18,
    districts=frozenset({"DT1", "DT2", "DT3", "DT4"}),
    accepts=frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY}),
    review_by=date(2027, 1, 31),
    owner_role_name="Shift lead",
    phone=NUMBER,
)


def _hasher() -> HmacPhoneHasher:
    return HmacPhoneHasher(FixedSecretStore({PHONE_HASH_SECRET: PHONE_SECRET}))


def _use_case(factory: UnitOfWorkFactory, driver: AsyncDriver) -> SetupServiceByLead:
    return SetupServiceByLead(
        factory,
        FixedClock(NOW),
        SequentialIds("setup"),
        DriverIdempotencyStore(driver),
        _hasher(),
    )


async def _seed_lead(factory: UnitOfWorkFactory) -> None:
    async with factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-lead-1", active=True, display_name="Shift lead", phone_hash=None)
        )
        await uow.commit()


async def _total_nodes(driver: AsyncDriver) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        record = await (await run_nodes(tx, "count(n) AS total")).single()
        assert record is not None
        return int(record["total"])

    return await read_tx(driver, work)


async def _labels_holding(driver: AsyncDriver, needle: str) -> set[tuple[str, ...]]:
    """The label sets of every node with a string property that contains `needle`, by a raw read."""

    async def work(tx: AsyncManagedTransaction) -> set[tuple[str, ...]]:
        rows = await (await run_nodes(tx, "labels(n) AS labels, properties(n) AS props")).data()
        return {
            tuple(row["labels"])
            for row in rows
            if any(isinstance(value, str) and needle in value for value in row["props"].values())
        }

    return await read_tx(driver, work)


async def test_setting_up_ucr_west_stores_an_active_service_criteria_v1_a_role_and_a_first_prompt(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    await _seed_lead(uow_factory)
    result = await _use_case(uow_factory, neo4j_driver).execute(UCR_WEST)

    assert isinstance(result, SetupServiceResult)
    assert result.first_prompt_at == FIRST_PROMPT
    async with uow_factory() as uow:
        service = await uow.services.get(result.service_id)
        criteria = await uow.criteria.current_for_service(result.service_id)
        roles = await uow.people.reporter_roles_for_service(result.service_id, NOW)
        work = await uow.scheduled_work.for_about(result.service_id, WorkKind.PROMPT_DUE)

    assert service is not None
    assert service.active is True
    assert criteria is not None
    assert criteria.id == result.criteria_id
    assert criteria.version == 1
    assert criteria.status is CriteriaStatus.CURRENT
    assert [role.id for role in roles] == [result.role_id]
    assert roles[0].practitioner_id == result.practitioner_id
    assert [(row.due_at, row.status) for row in work] == [(FIRST_PROMPT, "scheduled")]


async def test_the_number_is_held_only_in_the_protected_contact_node(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    await _seed_lead(uow_factory)
    result = await _use_case(uow_factory, neo4j_driver).execute(UCR_WEST)

    async with uow_factory() as uow:
        assert await uow.contacts.get_phone(result.role_id) == STORED_NUMBER

    assert await _labels_holding(neo4j_driver, "7700900123") == {("ProtectedContact",)}
    assert await _labels_holding(neo4j_driver, STORED_NUMBER) == {("ProtectedContact",)}


async def test_the_same_mobile_for_a_second_service_reuses_one_practitioner_and_holds_two_roles(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    await _seed_lead(uow_factory)
    use_case = _use_case(uow_factory, neo4j_driver)
    first = await use_case.execute(UCR_WEST)
    second = await use_case.execute(
        dataclasses.replace(UCR_WEST, idempotency_key="setup-ucr-east", name="UCR East")
    )

    assert second.practitioner_id == first.practitioner_id
    async with uow_factory() as uow:
        roles = await uow.people.roles_for_practitioner(first.practitioner_id)
    reporter_services = sorted(
        role.service_id for role in roles if role.code is PractitionerRoleCode.DUTY_MANAGER
    )
    assert reporter_services == sorted([first.service_id, second.service_id])


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"usual_range": (5, 2)}, "usual_range"),
        ({"established_capacity": 0}, "established_capacity"),
        ({"phone": "0123"}, "phone"),
    ],
    ids=["range-5-2", "established-0", "phone-0123"],
)
async def test_an_invalid_set_up_is_refused_naming_the_field_and_nothing_is_written(
    neo4j_driver: AsyncDriver,
    uow_factory: UnitOfWorkFactory,
    changes: dict[str, object],
    field: str,
) -> None:
    await _seed_lead(uow_factory)
    nodes_before = await _total_nodes(neo4j_driver)

    with pytest.raises(ValidationFailed) as refused:
        await _use_case(uow_factory, neo4j_driver).execute(dataclasses.replace(UCR_WEST, **changes))

    assert refused.value.field == field
    assert await _total_nodes(neo4j_driver) == nodes_before
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0


async def test_an_advisor_is_refused_and_a_replay_stores_one_service(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    await _seed_lead(uow_factory)
    use_case = _use_case(uow_factory, neo4j_driver)

    with pytest.raises(NotAllowed):
        await use_case.execute(dataclasses.replace(UCR_WEST, actor=ADVISOR))
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0

    first = await use_case.execute(UCR_WEST)
    replay = await use_case.execute(UCR_WEST)
    assert replay == first
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1


async def test_a_saved_service_reads_back_equal_to_the_profile_that_was_saved(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    await _seed_lead(uow_factory)
    result = await _use_case(uow_factory, neo4j_driver).execute(UCR_WEST)

    async with uow_factory() as uow:
        stored = await uow.services.get(result.service_id)
    assert stored == build_profile(UCR_WEST, result.service_id)


async def test_another_tenants_lead_is_not_found_and_its_phone_is_not_reused(
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    """Tenant B holds a lead practitioner and a reporter with this phone (DEC-130 item 3). Set-up
    in tenant A refuses B's lead id as not found, and once A has its own lead it does not reuse
    B's practitioner for the same phone."""
    async with uow_factory_b() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-lead-b", active=True, display_name="Lead in B", phone_hash=None)
        )
        await uow.people.save_practitioner(
            Practitioner(
                id="prac-b-reporter",
                active=True,
                display_name="Duty manager in B",
                phone_hash=_hasher().hash(STORED_NUMBER),
            )
        )
        await uow.commit()

    foreign_lead = dataclasses.replace(
        UCR_WEST,
        idempotency_key="setup-foreign-lead",
        actor=dataclasses.replace(LEAD, practitioner_id="prac-lead-b"),
    )
    with pytest.raises(NotFound):
        await SetupServiceByLead(
            uow_factory_a,
            FixedClock(NOW),
            SequentialIds("setup"),
            DriverIdempotencyStore(neo4j_driver),
            _hasher(),
        ).execute(foreign_lead)
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0

    await _seed_lead(uow_factory_a)
    result = await _use_case(uow_factory_a, neo4j_driver).execute(UCR_WEST)
    assert result.practitioner_id != "prac-b-reporter"

    async with uow_factory_b() as uow:
        b_reporter = await uow.people.get_practitioner("prac-b-reporter")
    assert b_reporter is not None
    assert b_reporter.active is True
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1


# --- the reporter is also on the new service's duty roster (DEC-1347) -----------------------


async def test_the_reporter_is_on_the_new_services_roster_off_shift_with_the_last_four_digits(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    await _seed_lead(uow_factory)
    result = await _use_case(uow_factory, neo4j_driver).execute(UCR_WEST)

    roster = await ListRoster(uow_factory, FixedClock(NOW)).execute(LEAD, result.service_id)
    assert [(e.name, e.number_ending, e.state, e.shift_end) for e in roster] == [
        ("Duty manager", "0123", RosterState.OFF_SHIFT, None)
    ]
    assert roster[0].role_id == result.roster_role_id
    async with uow_factory() as uow:
        assert await uow.contacts.get_phone(result.roster_role_id or "") == STORED_NUMBER
        stored = await uow.people.get_practitioner(result.practitioner_id)
        assert stored is not None
        assert stored.phone_hash == _hasher().hash("07700900123")
        # The reporter post is untouched: the same practitioner, the duty manager code, active.
        post = await uow.people.get_role(result.role_id)
    assert post is not None
    assert post.code is PractitionerRoleCode.DUTY_MANAGER
    assert post.active is True
    assert await _labels_holding(neo4j_driver, "7700900123") == {("ProtectedContact",)}


async def test_a_replay_and_a_second_add_leave_one_roster_place(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    await _seed_lead(uow_factory)
    use_case = _use_case(uow_factory, neo4j_driver)
    first = await use_case.execute(UCR_WEST)
    replay = await use_case.execute(UCR_WEST)
    assert replay == first

    # The shift lead adding the same person on the roster page is the existing refusal.
    adder = AddRosterManager(uow_factory, FixedClock(NOW), SequentialIds("add"), _hasher())
    with pytest.raises(Conflict):
        await adder.execute(AddRosterManagerCommand(LEAD, first.service_id, "Someone", NUMBER))
    # And putting the person on again does nothing and does not fail.
    async with uow_factory() as uow:
        again = await put_on_roster(
            uow,
            SequentialIds("again"),
            service_id=first.service_id,
            practitioner_id=first.practitioner_id,
            national="07700900123",
            now=NOW,
        )
    assert again is None
    roster = await ListRoster(uow_factory, FixedClock(NOW)).execute(LEAD, first.service_id)
    assert len(roster) == 1


async def test_the_same_mobile_on_a_second_service_is_on_each_services_roster_once(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    await _seed_lead(uow_factory)
    use_case = _use_case(uow_factory, neo4j_driver)
    first = await use_case.execute(UCR_WEST)
    second = await use_case.execute(
        dataclasses.replace(UCR_WEST, idempotency_key="setup-ucr-east", name="UCR East")
    )
    assert second.practitioner_id == first.practitioner_id
    for result in (first, second):
        roster = await ListRoster(uow_factory, FixedClock(NOW)).execute(LEAD, result.service_id)
        assert [e.role_id for e in roster] == [result.roster_role_id]


async def test_the_roster_place_is_in_the_leads_tenant_only(
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
) -> None:
    await _seed_lead(uow_factory_a)
    result = await _use_case(uow_factory_a, neo4j_driver).execute(UCR_WEST)
    assert result.roster_role_id is not None
    phone_hash = _hasher().hash("07700900123")

    async with uow_factory_b() as uow:
        assert await uow.people.roster_roles_for_phone_hash(phone_hash) == []
        assert await uow.people.get_role(result.roster_role_id) is None
        assert await uow.contacts.get_phone(result.roster_role_id) is None
    async with uow_factory_a() as uow:
        mine = await uow.people.roster_roles_for_phone_hash(phone_hash)
    assert [role.id for role in mine] == [result.roster_role_id]


async def test_a_new_wizard_service_is_not_stale_for_want_of_a_shift_and_texts_one_phone_once(
    neo4j_driver: AsyncDriver, uow_factory: UnitOfWorkFactory
) -> None:
    """The reporter post is always on, so a rostered service nobody has checked in to is staffed
    and the board does not call it not updated (DEC-1341 item 6). When the person then goes on
    shift they hold two roles for the service and one prompt goes to their phone."""
    await _seed_lead(uow_factory)
    clock = FixedClock(NOW)
    result = await _use_case(uow_factory, neo4j_driver).execute(UCR_WEST)
    async with uow_factory() as uow:
        await uow.capacity.add(
            CapacityReport(
                id="obs-new-1",
                service_id=result.service_id,
                value=4,
                measure=Measure.REFERRALS_ACCEPTABLE,
                effective_at=NOW - timedelta(minutes=10),
                source=ReportSource.TEXT,
                report_type=ReportType.NUMBER,
            )
        )
        await uow.commit()

    async def status() -> Status:
        board = await QueryBoard(uow_factory, clock).execute(QueryBoardQuery(LEAD))
        return next(e.status for e in board.entries if e.service_id == result.service_id)

    assert await status() is not Status.NOT_UPDATED
    async with uow_factory() as uow:
        assert len(await _reporters(uow, result.service_id, NOW)) == 1

    await CheckIn(uow_factory, clock, SequentialIds("ci")).execute(
        _hasher().hash("07700900123"), None, LEAD, result.service_id
    )
    async with uow_factory() as uow:
        assert len(await uow.people.reporter_roles_for_service(result.service_id, NOW)) == 2
        assert len(await _reporters(uow, result.service_id, NOW)) == 1
    assert await status() is not Status.NOT_UPDATED
