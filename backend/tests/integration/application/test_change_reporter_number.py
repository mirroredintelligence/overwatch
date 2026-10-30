"""Integration tests for ChangeReporterNumber (U16), against the real Neo4j the harness starts.

A shift lead points a service's reports at a new mobile, for cover (today, this week) or until it is
changed. Every assertion reads back through a fresh unit of work or the harness helpers. Numbers are
the sample values of the prompt; nothing here is a patient.

The routing of a reply is checked where the handler decides it: `services_for_phone_hash` and
`role_holder`, the two reads HandleInboundText and SendPrompts make (lesson L27 of the prompt).
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.change_reporter_number import (
    ChangeReporterNumber,
    ChangeReporterNumberCommand,
    ChangeReporterNumberResult,
    CoverDuration,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole, role_holder
from tests.support.actors import ACTOR_TENANT
from tests.support.ladder_rig import reporter, seed_people, virtual_ward
from tests.support.neo4j import count_nodes, node_props, wipe
from tests.support.tenant_seed import contracted_container
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

LONDON = ZoneInfo("Europe/London")
SERVICE_ID = "vw-frailty"
OLD_MOBILE = "07700 900123"
NEW_MOBILE = "07700 900456"
PHONE_SECRET = b"phone-hash-test-secret-0123456789ab"
HASHER = HmacPhoneHasher(FixedSecretStore({PHONE_HASH_SECRET: PHONE_SECRET}))
OLD_HASH = HASHER.hash(OLD_MOBILE)
NEW_HASH = HASHER.hash(NEW_MOBILE)

LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="lead-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)


def london(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=LONDON).astimezone(UTC)


FRIDAY_14 = london(2026, 11, 6, 14)


def use_case(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, at: datetime
) -> ChangeReporterNumber:
    return ChangeReporterNumber(
        uow_factory,
        FixedClock(at),
        SequentialIds("cr"),
        DriverIdempotencyStore(driver),
        HASHER,
    )


def command(
    key: str, duration: CoverDuration, mobile: str = NEW_MOBILE
) -> ChangeReporterNumberCommand:
    return ChangeReporterNumberCommand(
        idempotency_key=key,
        actor=LEAD,
        service_id=SERVICE_ID,
        new_mobile=mobile,
        duration=duration,
    )


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    """A private Neo4j with every migration applied and the superseded single-property keys dropped
    (DEC-159). The cross-tenant test writes practitioner prac-1 in both tenants, which the shared
    schema refuses until TEN-032."""
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    """Overrides the session driver for this module."""
    return two_tenant_driver


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def fresh_graph(neo4j_driver: AsyncDriver) -> None:
    """Wipes the module's own container before each test (clean_graph wipes only the harness)."""
    await wipe(neo4j_driver)


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    """The service and its reporter: practitioner prac-1 on the old mobile, role role-1 for it.
    Both tenants' audit heads exist, so the cross-tenant test can read and write in tenant B."""
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)
    async with uow_factory() as uow:
        await uow.services.save(virtual_ward(SERVICE_ID))
        await uow.commit()
    await seed_people(uow_factory, reporter(1, OLD_HASH, service_id=SERVICE_ID))


async def _seed_practitioner(
    uow_factory: UnitOfWorkFactory, practitioner_id: str, phone: str
) -> None:
    async with uow_factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(
                id=practitioner_id, active=True, display_name="Reporter two", phone_hash=phone
            )
        )
        await uow.commit()


async def _role_and_holder(
    uow_factory: UnitOfWorkFactory, at: datetime
) -> tuple[PractitionerRole, str]:
    async with uow_factory() as uow:
        roles = await uow.people.reporter_roles_for_service(SERVICE_ID, at)
    assert len(roles) == 1
    return roles[0], role_holder(roles[0], at)


async def test_cover_today_ends_at_2359_london_and_the_new_phone_gets_the_1600_prompt(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    result = await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
        command("cover-today-1", CoverDuration.TODAY)
    )
    assert isinstance(result, ChangeReporterNumberResult)
    assert result.covered_until == datetime(2026, 11, 6, 23, 59, tzinfo=UTC)
    role, holder = await _role_and_holder(uow_factory, london(2026, 11, 6, 16))
    assert holder != "prac-1"
    assert role.covered_until == datetime(2026, 11, 6, 23, 59, tzinfo=UTC)


async def test_a_reply_from_the_old_phone_at_1605_is_not_routed_to_the_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
        command("cover-today-2", CoverDuration.TODAY)
    )
    async with uow_factory() as uow:
        held = await uow.people.services_for_phone_hash(OLD_HASH, london(2026, 11, 6, 16, 5))
    assert [service for _, service in held] == []


async def test_the_original_phone_gets_prompts_again_at_0001_on_saturday(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
        command("cover-today-3", CoverDuration.TODAY)
    )
    role, holder = await _role_and_holder(uow_factory, london(2026, 11, 7, 0, 1))
    assert holder == "prac-1"
    async with uow_factory() as uow:
        held = await uow.people.services_for_phone_hash(OLD_HASH, london(2026, 11, 7, 0, 1))
    assert [service_role.id for service_role, _ in held] == ["role-1"]


async def test_this_week_on_a_friday_runs_to_sunday_2359_london(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    result = await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
        command("cover-week-1", CoverDuration.THIS_WEEK)
    )
    assert result.covered_until == datetime(2026, 11, 8, 23, 59, tzinfo=UTC)


async def test_until_changed_ends_the_old_role_and_starts_one_for_the_new_practitioner(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    result = await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
        command("until-changed-1", CoverDuration.UNTIL_CHANGED)
    )
    assert result.covered_until is None
    async with uow_factory() as uow:
        old_roles = await uow.people.roles_for_practitioner("prac-1")
        new_practitioners = [
            p for p in [await uow.people.find_by_phone_hash(NEW_HASH)] if p is not None
        ]
    assert old_roles == []  # the old role is inactive, so it is not listed as active
    assert len(new_practitioners) == 1
    async with uow_factory() as uow:
        roles = await uow.people.reporter_roles_for_service(SERVICE_ID, FRIDAY_14)
    assert [r.id for r in roles] == [result.role_id]
    assert roles[0].practitioner_id == new_practitioners[0].id
    assert roles[0].active is True


async def test_a_new_number_already_held_in_this_tenant_is_reused_not_duplicated(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await _seed_practitioner(uow_factory, "prac-2", NEW_HASH)
    result = await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
        command("reuse-1", CoverDuration.UNTIL_CHANGED)
    )
    assert await count_nodes(neo4j_driver, "Practitioner") == 2
    async with uow_factory() as uow:
        roles = await uow.people.reporter_roles_for_service(SERVICE_ID, FRIDAY_14)
    assert [(r.id, r.practitioner_id) for r in roles] == [(result.role_id, "prac-2")]


async def test_an_invalid_mobile_or_an_advisor_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    before = (
        await count_nodes(neo4j_driver, "PractitionerRole"),
        await count_nodes(neo4j_driver, "Practitioner"),
        await count_nodes(neo4j_driver, "AuditEvent"),
    )
    with pytest.raises(ValidationFailed) as refused:
        await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
            command("bad-mobile-1", CoverDuration.TODAY, mobile="0123")
        )
    assert refused.value.field == "new_mobile"
    with pytest.raises(NotAllowed):
        await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
            ChangeReporterNumberCommand(
                idempotency_key="advisor-1",
                actor=ADVISOR,
                service_id=SERVICE_ID,
                new_mobile=NEW_MOBILE,
                duration=CoverDuration.TODAY,
            )
        )
    after = (
        await count_nodes(neo4j_driver, "PractitionerRole"),
        await count_nodes(neo4j_driver, "Practitioner"),
        await count_nodes(neo4j_driver, "AuditEvent"),
    )
    assert after == before


async def test_the_audit_snapshot_holds_two_hashes_and_no_number(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seeded: None
) -> None:
    await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
        command("audit-1", CoverDuration.TODAY)
    )
    event = await node_props(neo4j_driver, "AuditEvent", useCase="ChangeReporterNumber")
    snapshot_node = await node_props(neo4j_driver, "Snapshot")
    snapshot = json.loads(snapshot_node["json"])
    assert set(snapshot) == {
        "service_id",
        "old_phone_hash",
        "new_phone_hash",
        "duration",
        "covered_until",
    }
    assert snapshot["old_phone_hash"] == OLD_HASH
    assert snapshot["new_phone_hash"] == NEW_HASH
    text = repr(event) + repr(snapshot_node)
    assert "900123" not in text and "900456" not in text


async def test_a_cover_in_tenant_a_leaves_tenant_b_with_the_same_mobile_unchanged(
    uow_factory: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seeded: None,
) -> None:
    async with uow_factory_b() as uow:
        await uow.services.save(virtual_ward(SERVICE_ID))
        await uow.commit()
    await seed_people(uow_factory_b, reporter(1, OLD_HASH, service_id=SERVICE_ID))
    async with uow_factory_b() as uow:
        before = await uow.people.reporter_roles_for_service(SERVICE_ID, FRIDAY_14)
    await use_case(uow_factory, neo4j_driver, FRIDAY_14).execute(
        command("tenant-a-1", CoverDuration.UNTIL_CHANGED)
    )
    async with uow_factory_b() as uow:
        after = await uow.people.reporter_roles_for_service(SERVICE_ID, FRIDAY_14)
    assert [r.id for r in after] == [r.id for r in before]
    assert all(r.active and r.covered_by_practitioner_id is None for r in after)
