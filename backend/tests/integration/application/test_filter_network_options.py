"""The network variant of the options (KI-349, KI-181, KI-794), on a real Neo4j.

Three members of one network have granted capacity, directory and criteria, had a service admitted
and been projected (the world of test_query_network). A member's advisor asks for the options of a
case of their own tenant and gets the other members' services as read-only options: labelled by
organisation, named by their listing and never by a tenant or a service id, filtered by the
projected criteria, and with no row for the advisor's own services. A tenant that is not a member,
a role that never sees a network, a grant that ended, a case that is closed or another tenant's:
each reads as it does everywhere else. The advisor's own audit trail records what was shown; the
network scope holds nothing of the case. Synthetic values only.
"""

import dataclasses
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_network_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_geo import FixedPostcodeLocator, FixedTravelTime
from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess
from diucs.application.ports.outbound.geo import LatLon, TravelRange
from diucs.application.use_cases.filter_network_options import (
    FilterNetworkOptions,
    FilterNetworkOptionsCommand,
)
from diucs.domain.codes import (
    AgeBand,
    NeedCategory,
    Outcome,
    ReferrerType,
    Role,
    Status,
    Urgency,
)
from diucs.domain.errors import Conflict, NotAllowed, NotFound
from diucs.domain.model.case import Case
from diucs.domain.model.network import GrantScope
from tests.support.network_world import NetworkWorld, world_ids
from tests.support.tenancy import RunIdentity
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

CASE_ID = "case-net-1"
# Half an hour after the members' sample report (09:00 on a Thursday, in hours): a current figure.
READ_AT = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
OPENED = READ_AT - timedelta(minutes=5)


class _Tenant:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name


class _Names:
    async def get(self, tenant_id: str) -> _Tenant | None:
        return _Tenant(f"Org {tenant_id.rsplit('-', 1)[-1]}")


@pytest_asyncio.fixture(loop_scope="session")
async def connection(harness_driver: AsyncDriver) -> AsyncIterator[Neo4jConnection]:
    conn = Neo4jConnection(
        os.environ["NEO4J_URI"], os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]
    )
    await conn.open()
    try:
        yield conn
    finally:
        await conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def world(
    harness_driver: AsyncDriver,
    connection: Neo4jConnection,
    run_identity: RunIdentity,
    clean_graph: None,
) -> AsyncIterator[NetworkWorld]:
    built = await NetworkWorld.build(harness_driver, connection, world_ids(run_identity))
    await built.run_projector()
    yield built
    await built.cleanup()


def _clock() -> FixedClock:
    return FixedClock(READ_AT)


def _advisor(tenant: str, role: Role = Role.ADVISOR) -> Actor:
    return Actor(
        role=role,
        practitioner_id="prac-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _case(**changes: object) -> Case:
    fields: dict[str, object] = {
        "id": CASE_ID,
        "reference": "4821",
        "referrer_type": ReferrerType.AMBULANCE_CREW,
        "age_band": AgeBand.A80_PLUS,
        "postcode": "DT4",
        "needs": (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
        "urgency": Urgency.WITHIN_2_HRS,
        "scores": (),
        "opened_at": OPENED.astimezone(UTC),
    }
    fields.update(changes)
    return Case(**fields)  # type: ignore[arg-type]


async def _own_case(world: NetworkWorld, tenant: str, case: Case | None = None) -> None:
    await ensure_audit_heads(world.driver, tenant)
    async with tenant_uow_factory(world.driver, tenant, _clock())() as uow:
        await uow.cases.add(case or _case())
        await uow.commit()


def _use_case(world: NetworkWorld, tenant: str) -> FilterNetworkOptions:
    return FilterNetworkOptions(
        tenant_uow_factory(world.driver, tenant, _clock()),
        neo4j_network_uow_factory(world.driver, read_only=True),
        NetworkAccess(world.registry, _Names()),  # type: ignore[arg-type]
        _clock(),
        FixedPostcodeLocator(postcodes={}, districts={"DT4": LatLon(50.72, -2.44)}),
        FixedTravelTime(TravelRange(10, 20, "fixed")),
    )


async def _ask(
    world: NetworkWorld,
    tenant: str,
    *,
    role: Role = Role.ADVISOR,
    network: str | None = None,
    case_id: str = CASE_ID,
):  # type: ignore[no-untyped-def]
    return await _use_case(world, tenant).execute(
        FilterNetworkOptionsCommand(_advisor(tenant, role), case_id, network or world.ids.network)
    )


async def test_the_other_members_services_are_read_only_options_labelled_by_organisation(
    world: NetworkWorld,
) -> None:
    m1, m2, m3 = world.ids.members
    await _own_case(world, m1)

    result = await _ask(world, m1)

    assert {o.organisation for o in result.options} == {"Org m2", "Org m3"}
    assert {o.name for o in result.options} == {world.service_name(m2), world.service_name(m3)}
    assert {o.service_id for o in result.options} == {world.listing_id(m2), world.listing_id(m3)}
    assert all(o.status is Status.ACCEPTING for o in result.options)
    assert all(o.organisation_source == "Entered by the organisation" for o in result.options)
    assert all(o.fits[0] == "Covers this postcode" for o in result.options)


async def test_the_advisors_own_services_are_not_among_the_network_options(
    world: NetworkWorld,
) -> None:
    m1 = world.ids.members[0]
    await _own_case(world, m1)

    result = await _ask(world, m1)

    assert world.service_name(m1) not in {o.name for o in result.options}
    assert "Org m1" not in {o.organisation for o in result.options}


async def test_no_tenant_id_and_no_service_id_of_a_member_is_in_any_option(
    world: NetworkWorld,
) -> None:
    m1 = world.ids.members[0]
    await _own_case(world, m1)

    result = await _ask(world, m1)

    text = repr(result)
    for member in (*world.ids.members, world.ids.owner):
        assert member not in text
    assert "svc-1" not in text
    assert all(world.poison[m][0] not in text for m in world.ids.members)


async def test_a_case_outside_the_projected_criteria_gets_no_network_options(
    world: NetworkWorld,
) -> None:
    m1 = world.ids.members[0]
    await _own_case(world, m1, _case(postcode="ZZ9"))

    result = await _ask(world, m1)

    assert result.options == ()


async def test_a_need_the_projected_criteria_exclude_is_not_offered(world: NetworkWorld) -> None:
    m1 = world.ids.members[0]
    await _own_case(world, m1, _case(needs=(NeedCategory.IV_THERAPY,)))

    assert (await _ask(world, m1)).options == ()


async def test_a_member_whose_criteria_grant_ended_is_not_offered_because_it_cannot_be_filtered(
    world: NetworkWorld,
) -> None:
    m1, m2, m3 = world.ids.members
    await _own_case(world, m1)
    await world.end_grant(m2, GrantScope.CRITERIA)

    result = await _ask(world, m1)

    assert {o.organisation for o in result.options} == {"Org m3"}


async def test_a_member_whose_capacity_grant_ended_is_not_offered(world: NetworkWorld) -> None:
    m1, m2, m3 = world.ids.members
    await _own_case(world, m1)
    await world.end_grant(m3, GrantScope.CAPACITY)

    result = await _ask(world, m1)

    assert {o.organisation for o in result.options} == {"Org m2"}


async def test_a_member_who_left_is_not_offered(world: NetworkWorld) -> None:
    m1, m2, m3 = world.ids.members
    await _own_case(world, m1)
    await world.leave(m3)

    assert {o.organisation for o in (await _ask(world, m1)).options} == {"Org m2"}


async def test_a_tenant_outside_the_network_is_not_found_and_reads_nothing(
    world: NetworkWorld,
) -> None:
    outsider = world.ids.outsider
    await _own_case(world, outsider)

    with pytest.raises(NotFound):
        await _ask(world, outsider)


@pytest.mark.parametrize(
    "role", [Role.LEAD, Role.OWNER, Role.EXEC, Role.REPORTER, Role.WALL, Role.SUPPORT]
)
async def test_a_role_that_is_not_an_advisor_or_a_clinician_is_refused(
    world: NetworkWorld, role: Role
) -> None:
    m1 = world.ids.members[0]
    await _own_case(world, m1)

    with pytest.raises(NotAllowed):
        await _ask(world, m1, role=role)


async def test_a_clinical_advisor_may_ask(world: NetworkWorld) -> None:
    m1 = world.ids.members[0]
    await _own_case(world, m1)

    assert (await _ask(world, m1, role=Role.CLINICAL)).options


async def test_a_network_the_tenant_never_joined_is_not_found(world: NetworkWorld) -> None:
    m1 = world.ids.members[0]
    await _own_case(world, m1)

    with pytest.raises(NotFound):
        await _ask(world, m1, network=world.ids.other_network)


async def test_an_unknown_case_and_another_tenants_case_are_the_same_not_found(
    world: NetworkWorld,
) -> None:
    m1, m2, _ = world.ids.members
    await _own_case(world, m2)  # the case exists, in another tenant

    with pytest.raises(NotFound):
        await _ask(world, m1, case_id=CASE_ID)
    with pytest.raises(NotFound):
        await _ask(world, m1, case_id="no-such-case")


async def test_a_closed_case_is_a_conflict(world: NetworkWorld) -> None:
    m1 = world.ids.members[0]
    closed = _case().close(Outcome.DECLINED, READ_AT)
    await _own_case(world, m1, closed)

    with pytest.raises(Conflict):
        await _ask(world, m1)


async def test_the_advisors_audit_trail_names_what_was_shown_by_listing_and_nothing_else(
    world: NetworkWorld,
) -> None:
    m1, m2, m3 = world.ids.members
    await _own_case(world, m1)

    await _ask(world, m1)

    async with tenant_uow_factory(world.driver, m1, _clock())() as uow:
        entries = [r.entry for r in await uow.audit.records()]
    shown = [e for e in entries if e.use_case == "FilterNetworkOptions"]
    assert len(shown) == 1
    snapshot = shown[0].snapshot
    assert {row["row_ref"] for row in snapshot["services"]} == {
        world.listing_id(m2),
        world.listing_id(m3),
    }
    text = repr(snapshot)
    for member in (*world.ids.members, world.ids.owner):
        assert member not in text
    assert "Org m2" not in text and world.service_name(m2) not in text
    assert "DT4" not in text


async def test_the_network_scope_holds_nothing_of_the_case(world: NetworkWorld) -> None:
    m1 = world.ids.members[0]
    await _own_case(world, m1)
    before = await world.invariants()

    await _ask(world, m1)

    assert await world.invariants() == before
    assert all(rows == [] for rows in (await world.invariants()).values())


async def test_the_use_case_is_never_given_a_case_value_to_pass_on() -> None:
    fields = {field.name for field in dataclasses.fields(FilterNetworkOptionsCommand)}
    assert fields == {"actor", "case_id", "network_id"}
