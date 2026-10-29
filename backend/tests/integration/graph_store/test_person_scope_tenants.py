"""Two tenants with the same keys in the person, registration and scope-list repositories (TEN-011).

Both tenants hold a practitioner `p-1` with the same phone hash, a role `r-1`, a service `svc-1`,
a registration `reg-1` and a scope list. The keys are composite with the tenant (TEN-005), so both
can be written; every read and every write must stay in the bound tenant. These tests run on a
private container with the superseded single-property keys dropped (`contracted_container`), the
schema the platform has after TEN-032. All values are synthetic.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.person_repository import Neo4jPersonRepository
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.registration_repository import Neo4jRegistrationRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.scenario import SeedNode, SeedRel, TenantSeed
from diucs.adapters.outbound.graph_store.scope_list_repository import Neo4jScopeListRepository
from diucs.adapters.outbound.graph_store.service_repository import codeable_to_fhir
from diucs.application.tenancy import bind_tenant
from diucs.domain.codes import (
    Channel,
    PractitionerRoleCode,
    RegistrationStatus,
    ScopeFlag,
    ServiceCategory,
    coding_for,
)
from diucs.domain.errors import NotFound
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.registration import Registration, ScopeEntry
from diucs.domain.rules.registration import ApprovalChecks
from tests.support.neo4j import read_tx, wipe, write_tx
from tests.support.tenant_seed import contracted_container, invariant_breaks, seed_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)
PERIOD_START = datetime(2026, 10, 1, tzinfo=UTC)
PHONE = "c" * 64
CREATED = datetime(2026, 10, 25, 12, 40, tzinfo=UTC)
DAY = date(2026, 10, 25)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def two(two_tenant_driver: AsyncDriver) -> AsyncIterator[AsyncDriver]:
    await wipe(two_tenant_driver)
    yield two_tenant_driver
    await wipe(two_tenant_driver)


def _repo(tx: AsyncManagedTransaction) -> Neo4jPersonRepository:
    return Neo4jPersonRepository(tx, ResourceStore(tx))


async def _as(driver: AsyncDriver, tenant: str, step: Any) -> None:
    """One committed write, as the tenant: `step(tx)` runs inside it."""
    with bind_tenant(tenant):
        await write_tx(driver, step)


async def _read_as(driver: AsyncDriver, tenant: str, step: Any) -> Any:
    with bind_tenant(tenant):
        return await read_tx(driver, step)


async def _rows_as(
    driver: AsyncDriver, bound: str, cypher: str, **params: Any
) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = await (await tx.run(cypher, **params)).data()
        return rows

    result: list[dict[str, Any]] = await _read_as(driver, bound, work)
    return result


async def _seed_service(tx: AsyncManagedTransaction, service_id: str, name: str) -> None:
    await ResourceStore(tx).put(
        {
            "resourceType": "HealthcareService",
            "id": service_id,
            "active": True,
            "name": name,
            "category": codeable_to_fhir(ServiceCategory.URGENT_COMMUNITY_RESPONSE),
        },
        None,
    )


def _person(name: str) -> Practitioner:
    return Practitioner(id="p-1", active=True, display_name=name, phone_hash=PHONE)


def _role(service_id: str, channel: Channel | None = None) -> PractitionerRole:
    return PractitionerRole(
        id="r-1",
        practitioner_id="p-1",
        service_id=service_id,
        code=PractitionerRoleCode.DUTY_MANAGER,
        active=True,
        channel=channel,
        period_start=PERIOD_START,
    )


async def _reporter(driver: AsyncDriver, tenant: str, name: str, service: str) -> None:
    """A practitioner with the shared phone, one role at one service, in one tenant."""

    async def work(tx: AsyncManagedTransaction) -> None:
        await _seed_service(tx, service, f"Service of {name}")
        repo = _repo(tx)
        await repo.save_practitioner(_person(name))
        await repo.save_role(_role(service, Channel.TEXT))

    await _as(driver, tenant, work)


async def test_a_phone_held_in_both_tenants_is_found_once_in_each_and_never_conflicts(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _reporter(two, tenant_id, "Reporter A", "svc-1")
    await _reporter(two, other_tenant_id, "Reporter B", "svc-1")

    found_a = await _read_as(two, tenant_id, lambda tx: _repo(tx).find_by_phone_hash(PHONE))
    found_b = await _read_as(two, other_tenant_id, lambda tx: _repo(tx).find_by_phone_hash(PHONE))

    assert found_a is not None and found_a.display_name == "Reporter A"
    assert found_b is not None and found_b.display_name == "Reporter B"


async def test_the_phone_of_one_tenant_is_not_read_by_the_other_when_it_is_only_there(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _reporter(two, tenant_id, "Reporter A", "svc-1")

    found_b = await _read_as(two, other_tenant_id, lambda tx: _repo(tx).find_by_phone_hash(PHONE))

    assert found_b is None


async def test_the_services_of_a_phone_are_the_bound_tenants_only(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _reporter(two, tenant_id, "Reporter A", "svc-1")
    await _reporter(two, other_tenant_id, "Reporter B", "svc-1")

    held = await _read_as(two, tenant_id, lambda tx: _repo(tx).services_for_phone_hash(PHONE, NOW))

    assert [(role.id, name) for role, name in held] == [("r-1", "Service of Reporter A")]


async def test_the_roles_of_a_practitioner_and_the_reporters_of_a_service_are_the_bound_tenants(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _reporter(two, tenant_id, "Reporter A", "svc-1")
    await _reporter(two, other_tenant_id, "Reporter B", "svc-1")

    roles = await _read_as(two, tenant_id, lambda tx: _repo(tx).roles_for_practitioner("p-1"))
    reporters = await _read_as(
        two, tenant_id, lambda tx: _repo(tx).reporter_roles_for_service("svc-1", NOW)
    )

    assert [role.id for role in roles] == ["r-1"]
    assert [role.id for role in reporters] == ["r-1"]


async def test_a_channel_in_one_tenant_never_links_to_the_concept_of_the_other(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """Both tenants save a text channel. Each role's CHANNEL points at its own tenant's Concept,
    and no relationship joins the two tenants."""
    await _reporter(two, other_tenant_id, "Reporter B", "svc-1")
    await _reporter(two, tenant_id, "Reporter A", "svc-1")

    assert await invariant_breaks_of(two) == ([], [])
    rows = await _rows_as(
        two,
        tenant_id,
        "MATCH (:PractitionerRole {id: 'r-1', tenantId: $tenant})-[:CHANNEL]->(c:Concept) "
        "RETURN c.tenantId AS tenant",
        tenant=tenant_id,
    )
    assert rows == [{"tenant": tenant_id}]


async def test_a_channel_for_a_role_that_is_not_there_creates_no_concept(
    two: AsyncDriver, tenant_id: str
) -> None:
    coding = coding_for(Channel.TEXT)

    async def work(tx: AsyncManagedTransaction) -> None:
        await run_query(
            tx,
            REGISTRY.get("Q-ROLE-CHANNEL"),
            roleKey="PractitionerRole/no-such-role",
            system=coding.system,
            code=coding.code,
            display=coding.display,
            conceptKey=f"Concept|{coding.system}|{coding.code}",
        )

    await _as(two, tenant_id, work)

    rows = await _rows_as(
        two,
        tenant_id,
        "MATCH (c:Concept {tenantId: $tenant}) RETURN count(c) AS concepts",
        tenant=tenant_id,
    )
    assert rows == [{"concepts": 0}]


async def test_a_cover_by_a_practitioner_of_the_other_tenant_is_not_found(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    async def other(tx: AsyncManagedTransaction) -> None:
        await _seed_service(tx, "svc-1", "Ward")
        await _repo(tx).save_practitioner(
            Practitioner(id="p-2", active=True, display_name="Cover", phone_hash="d" * 64)
        )

    await _as(two, other_tenant_id, other)

    async def mine(tx: AsyncManagedTransaction) -> None:
        await _seed_service(tx, "svc-1", "Ward")
        await _repo(tx).save_practitioner(_person("Reporter A"))
        covered = PractitionerRole(
            id="r-1",
            practitioner_id="p-1",
            service_id="svc-1",
            code=PractitionerRoleCode.DUTY_MANAGER,
            active=True,
            channel=None,
            period_start=PERIOD_START,
            covered_by_practitioner_id="p-2",
            covered_until=datetime(2026, 10, 25, 19, 0, tzinfo=UTC),
        )
        with pytest.raises(NotFound):
            await _repo(tx).save_role(covered)

    await _as(two, tenant_id, mine)


async def test_a_phone_saved_in_one_tenant_does_not_move_the_same_practitioner_of_the_other(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """The phone property is written to the bound tenant's practitioner only."""
    await _reporter(two, tenant_id, "Reporter A", "svc-1")
    other_phone = "e" * 64

    async def move(tx: AsyncManagedTransaction) -> None:
        await _repo(tx).save_practitioner(
            Practitioner(id="p-1", active=True, display_name="Reporter B", phone_hash=other_phone)
        )

    await _as(two, other_tenant_id, move)

    found_a = await _read_as(two, tenant_id, lambda tx: _repo(tx).find_by_phone_hash(PHONE))
    found_none = await _read_as(
        two, tenant_id, lambda tx: _repo(tx).find_by_phone_hash(other_phone)
    )
    assert found_a is not None and found_a.display_name == "Reporter A"
    assert found_none is None


def _registration(service_id: str, draft: dict[str, dict[str, Any]]) -> Registration:
    return Registration(
        id="reg-1",
        service_id=service_id,
        status=RegistrationStatus.SUBMITTED,
        requester_role_id=None,
        owner_role_id=None,
        created_at=CREATED,
        last_modified=CREATED,
        submitted_at=CREATED,
        draft=draft,
        checks=ApprovalChecks(True, False, None, False),
    )


async def test_the_draft_of_a_registration_is_the_bound_tenants_draft(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    for tenant, owner, draft in (
        (other_tenant_id, "B", {"organisation": {"name": "Org B"}}),
        (tenant_id, "A", {"organisation": {"name": "Org A"}}),
    ):

        async def work(tx: AsyncManagedTransaction, owner: str = owner, draft: Any = draft) -> None:
            await _seed_service(tx, "svc-1", f"Service {owner}")
            await Neo4jRegistrationRepository(tx, ResourceStore(tx)).add(
                _registration("svc-1", draft)
            )

        await _as(two, tenant, work)

    found = await _read_as(
        two, tenant_id, lambda tx: Neo4jRegistrationRepository(tx, ResourceStore(tx)).get("reg-1")
    )
    assert found is not None
    assert found.draft == {"organisation": {"name": "Org A"}}


async def test_registrations_listed_by_status_and_service_are_the_bound_tenants(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    for tenant, label in ((other_tenant_id, "B"), (tenant_id, "A")):

        async def work(tx: AsyncManagedTransaction, label: str = label) -> None:
            await _seed_service(tx, "svc-1", f"Service {label}")
            await Neo4jRegistrationRepository(tx, ResourceStore(tx)).add(_registration("svc-1", {}))

        await _as(two, tenant, work)

    async def listed(tx: AsyncManagedTransaction) -> tuple[list[str], list[str]]:
        repo = Neo4jRegistrationRepository(tx, ResourceStore(tx))
        by_status = await repo.list_by_status(RegistrationStatus.SUBMITTED)
        for_service = await repo.for_service("svc-1")
        return [r.id for r in by_status], [r.id for r in for_service]

    assert await _read_as(two, tenant_id, listed) == (["reg-1"], ["reg-1"])


async def test_each_tenant_has_its_own_scope_list_and_entries_do_not_cross(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    for tenant, flag in ((other_tenant_id, ScopeFlag.LATER), (tenant_id, ScopeFlag.IN_PILOT)):

        async def work(tx: AsyncManagedTransaction, flag: ScopeFlag = flag) -> None:
            await _seed_service(tx, "svc-1", "Pilot service")
            await Neo4jScopeListRepository(tx, ResourceStore(tx)).save_entry(
                ScopeEntry(
                    service_id="svc-1",
                    name="Pilot service",
                    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                    flag=flag,
                    date=DAY,
                )
            )

        await _as(two, tenant, work)

    async def entries(tx: AsyncManagedTransaction) -> list[str]:
        return [
            e.flag.value for e in await Neo4jScopeListRepository(tx, ResourceStore(tx)).entries()
        ]

    assert await _read_as(two, tenant_id, entries) == ["in-pilot"]
    assert await _read_as(two, other_tenant_id, entries) == ["later"]
    assert await invariant_breaks_of(two) == ([], [])


async def test_a_scope_entry_for_a_service_the_other_tenant_holds_names_the_tenants_own(
    two: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """Tenant B holds `svc-2`; tenant A has no `svc-2` and records an entry for it. The entry must
    point at A's own new `svc-2`, and never at B's (an unscoped match would link both)."""

    async def other(tx: AsyncManagedTransaction) -> None:
        await _seed_service(tx, "svc-2", "Other service")

    await _as(two, other_tenant_id, other)

    async def mine(tx: AsyncManagedTransaction) -> None:
        await Neo4jScopeListRepository(tx, ResourceStore(tx)).save_entry(
            ScopeEntry(
                service_id="svc-2",
                name="Mine",
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                flag=ScopeFlag.IN_PILOT,
                date=DAY,
            )
        )

    await _as(two, tenant_id, mine)

    query = (
        "MATCH (:List {tenantId: $tenant})-[:ENTRY]->(s:HealthcareService) "
        "RETURN s.id AS id, s.tenantId AS tenant"
    )
    assert await _rows_as(two, tenant_id, query, tenant=tenant_id) == [
        {"id": "svc-2", "tenant": tenant_id}
    ]
    assert await _rows_as(two, other_tenant_id, query, tenant=other_tenant_id) == []
    assert await invariant_breaks_of(two) == ([], [])


async def test_a_seeded_relationship_keeps_the_properties_it_is_given(two: AsyncDriver) -> None:
    """The scenario seeder writes a relationship's properties (TEN-011: a cover has an `until`)."""
    seed = TenantSeed(
        nodes=(
            SeedNode("role", ("PractitionerRole",), {"id": "r-1"}),
            SeedNode("person", ("Practitioner",), {"id": "p-1", "name": "Duty"}),
        ),
        rels=(SeedRel("role", "COVERED_BY", "person", {"until": "2026-10-25T19:00:00Z"}),),
    )
    await seed_tenant(two, "tenant-seed-check", "A", seed)

    async def read(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        query = (
            "MATCH (:PractitionerRole {tenantId: 'tenant-seed-check'})-[c:COVERED_BY]->() "
            "RETURN c.until AS until"
        )
        return await (await tx.run(query)).data()

    rows = await read_tx(two, read)
    assert rows == [{"until": "2026-10-25T19:00:00Z"}]


async def invariant_breaks_of(driver: AsyncDriver) -> tuple[list[str], list[str]]:
    return await read_tx(driver, invariant_breaks)
