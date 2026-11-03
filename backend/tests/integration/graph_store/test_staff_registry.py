"""The staff registry on a real Neo4j (DEC-1327): the platform's writes, and the sign-in's read.

What is proved, on a graph that holds two tenants' records:

- a sync makes a tenant's records active, and a read by a person's account reference finds them;
- a sync that no longer finds a person ends their record, and another tenant's record is untouched;
- a sync that finds the same people again adds no second record (one id per tenant, person and role);
- a person no tenant lists reads nothing.

Synthetic values only. The fixtures are the registry test's: a private Neo4j for the run.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from overwatch.adapters.outbound.graph_store.connection import Neo4jConnection
from overwatch.adapters.outbound.graph_store.staff_registry import Neo4jStaffRegistry
from overwatch.adapters.outbound.graph_store.tenant_registry import Neo4jStaffRoles
from overwatch.domain.codes import Role
from overwatch.domain.model.staff_registry import StaffRoleRecord
from overwatch.domain.rules.token_exchange import account_ref

# The fixtures of the tenant registry's integration test: one private Neo4j for this module's run.
from tests.integration.graph_store.test_tenant_registry import connection, harness_driver  # noqa: F401

pytestmark = [pytest.mark.schema]

KEY = b"s" * 32
DIR_A = "11111111-1111-4111-8111-111111111111"
DIR_B = "22222222-2222-4222-8222-222222222222"
PERSON = "33333333-3333-4333-8333-333333333333"
OTHER = "66666666-6666-4666-8666-666666666666"
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)


@pytest_asyncio.fixture(loop_scope="session")
async def registry(connection: Neo4jConnection) -> Neo4jStaffRegistry:
    return Neo4jStaffRegistry(connection, Neo4jStaffRoles(connection))


def record(tenant: str, person_object: str, directory: str, role: Role) -> StaffRoleRecord:
    return StaffRoleRecord(
        tenant_id=tenant,
        practitioner_key=account_ref(KEY, directory, person_object),
        role=role,
        status="active",
    )


async def count_active(driver: AsyncDriver, tenant: str) -> int:
    async with driver.session() as session:
        result = await session.run(
            "MATCH (s:StaffRoleRecord {tenantRef: $tenant, status: 'active'}) RETURN count(s) AS n",
            tenant=tenant,
        )
        row = await result.single()
    return int(row["n"]) if row else 0


@pytest.mark.asyncio(loop_scope="session")
async def test_a_sync_makes_a_person_findable_by_their_account_reference(
    registry: Neo4jStaffRegistry, harness_driver: AsyncDriver
) -> None:
    key = account_ref(KEY, DIR_A, PERSON)
    await registry.replace_tenant("tenant-one", [record("tenant-one", PERSON, DIR_A, Role.LEAD)], NOW)
    found = await registry.active_roles(key)
    assert [(r.tenant_id, r.role, r.status) for r in found] == [("tenant-one", Role.LEAD, "active")]


@pytest.mark.asyncio(loop_scope="session")
async def test_a_sync_that_no_longer_finds_a_person_ends_their_record_and_leaves_other_tenants_alone(
    registry: Neo4jStaffRegistry, harness_driver: AsyncDriver
) -> None:
    await registry.replace_tenant("tenant-two", [record("tenant-two", PERSON, DIR_A, Role.ADVISOR)], NOW)
    await registry.replace_tenant("tenant-three", [record("tenant-three", OTHER, DIR_B, Role.LEAD)], NOW)
    await registry.replace_tenant("tenant-two", [], NOW)
    assert await count_active(harness_driver, "tenant-two") == 0
    assert await count_active(harness_driver, "tenant-three") == 1
    assert await registry.active_roles(account_ref(KEY, DIR_A, PERSON)) == ()


@pytest.mark.asyncio(loop_scope="session")
async def test_the_same_people_found_again_add_no_second_record(
    registry: Neo4jStaffRegistry, harness_driver: AsyncDriver
) -> None:
    again = [record("tenant-four", PERSON, DIR_A, Role.CLINICAL)]
    await registry.replace_tenant("tenant-four", again, NOW)
    await registry.replace_tenant("tenant-four", again, NOW)
    assert await count_active(harness_driver, "tenant-four") == 1


@pytest.mark.asyncio(loop_scope="session")
async def test_a_person_no_tenant_lists_reads_nothing(registry: Neo4jStaffRegistry) -> None:
    assert await registry.active_roles(account_ref(KEY, DIR_B, "77777777-7777-4777-8777-777777777777")) == ()
