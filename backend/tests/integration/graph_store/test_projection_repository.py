"""The projection repository on a real Neo4j (TEN-053, DEC-542, DEC-132 item 4).

Written, not run, in build wave 5 (the owner's instruction: the whole integration suite runs once,
on the merged tip).

A network scope holds the allowlisted copies the projector writes. The tests show: what is written
is read back equal; an older version never replaces a newer one and a replay is idempotent; nothing
is written for a source that was never opened or has ended; ending marks the rows and keeps them,
and reopening makes them live again; two networks holding the same member and the same service ids
see only their own rows; a tenant scope and a read-only unit cannot write; and every property of
every node in the scope is on the allowlist (the layer-2 proof of TEN-062 starts here).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.unit_of_work import Neo4jUnitOfWork
from diucs.application.ports.outbound.projection import (
    GrantRef,
    ProjectionEndReason,
    SourceStatus,
)
from diucs.application.tenancy import (
    ReadOnlyUnitWrite,
    ScopeKindMismatch,
    UnitOfWorkAlreadyOpen,
    bind_network,
    bind_tenant,
)
from diucs.domain.messages.privacy_guard import scan_value
from diucs.domain.model.network import GrantScope
from diucs.domain.rules import projection as allowlist
from tests.support.neo4j import read_tx, write_tx
from tests.support.projection_samples import (
    sample_capacity_projection,
    sample_criteria_projection,
    sample_service_projection,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

SOURCE = "tenant-x"
OTHER_SOURCE = "tenant-y"
GRANT = GrantRef("grant-x-1", 1)
AT = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
LEFT = AT + timedelta(days=1)


@pytest.fixture
def net_a(network_id: str) -> str:
    return network_id


@pytest.fixture
def net_b(network_id: str) -> str:
    return f"{network_id}-b"


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean_networks(
    harness_driver: AsyncDriver, net_a: str, net_b: str
) -> AsyncIterator[None]:
    """The harness wipes the run tenants; these tests clear their own two network scopes."""

    async def wipe(tx: AsyncManagedTransaction) -> None:
        await tx.run("MATCH (n) WHERE n.tenantId IN $nets DETACH DELETE n", nets=[net_a, net_b])

    await write_tx(harness_driver, wipe)
    yield
    await write_tx(harness_driver, wipe)


@asynccontextmanager
async def unit(driver: AsyncDriver, scope: str, *, read_only: bool = False) -> AsyncIterator[Any]:
    with bind_network(scope):
        async with Neo4jUnitOfWork(driver, read_only=read_only) as uow:
            yield uow


async def open_all(driver: AsyncDriver, scope: str, source: str = SOURCE) -> None:
    async with unit(driver, scope) as uow:
        for kind in GrantScope:
            await uow.projections.open_source(source, kind, GRANT)
        await uow.commit()


async def put(driver: AsyncDriver, scope: str, source: str = SOURCE, **changes: Any) -> None:
    async with unit(driver, scope) as uow:
        service = sample_service_projection(**changes.get("service", {}))
        assert await uow.projections.upsert_service(source, service, grant=GRANT, projected_at=AT)
        assert await uow.projections.upsert_capacity(
            source, sample_capacity_projection(), grant=GRANT, projected_at=AT
        )
        assert await uow.projections.upsert_criteria(
            source, sample_criteria_projection(), grant=GRANT, projected_at=AT
        )
        await uow.commit()


async def view(driver: AsyncDriver, scope: str, *, live_only: bool = True) -> Any:
    async with unit(driver, scope, read_only=True) as uow:
        return (
            await uow.network_view.services(live_only=live_only),
            await uow.network_view.capacities(live_only=live_only),
            await uow.network_view.criteria(live_only=live_only),
        )


async def test_what_is_written_is_read_back_equal(harness_driver: AsyncDriver, net_a: str) -> None:
    await open_all(harness_driver, net_a)
    await put(harness_driver, net_a)
    services, capacities, criteria = await view(harness_driver, net_a)
    assert [r.projection for r in services] == [sample_service_projection()]
    assert [r.projection for r in capacities] == [sample_capacity_projection()]
    assert [r.projection for r in criteria] == [sample_criteria_projection()]
    assert {r.source_tenant_id for r in (*services, *capacities, *criteria)} == {SOURCE}
    assert services[0].projected_at == AT and services[0].grant_id == "grant-x-1"
    assert services[0].ended_at is None


async def test_nothing_is_written_for_a_source_that_was_never_opened(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    async with unit(harness_driver, net_a) as uow:
        assert not await uow.projections.upsert_service(
            SOURCE, sample_service_projection(), grant=GRANT, projected_at=AT
        )
        assert not await uow.projections.upsert_capacity(
            SOURCE, sample_capacity_projection(), grant=GRANT, projected_at=AT
        )
        await uow.commit()
    assert await view(harness_driver, net_a) == ([], [], [])


async def test_an_older_version_never_replaces_a_newer_one_and_a_replay_is_idempotent(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await open_all(harness_driver, net_a)
    newer = sample_capacity_projection(source_version=2_000)
    older = sample_capacity_projection(source_version=1_000)
    async with unit(harness_driver, net_a) as uow:
        assert await uow.projections.upsert_capacity(SOURCE, newer, grant=GRANT, projected_at=AT)
        assert not await uow.projections.upsert_capacity(
            SOURCE, older, grant=GRANT, projected_at=AT
        )
        assert await uow.projections.upsert_capacity(SOURCE, newer, grant=GRANT, projected_at=AT)
        await uow.commit()
    _, capacities, _ = await view(harness_driver, net_a)
    assert [r.projection for r in capacities] == [newer]


async def test_a_new_version_with_fewer_hours_and_no_location_ends_the_old_ones(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await open_all(harness_driver, net_a)
    await put(harness_driver, net_a)
    first = sample_service_projection()
    assert len(first.opening_hours) >= 2
    slimmer = replace(
        first,
        source_version=first.source_version + 1,
        location=None,
        opening_hours=first.opening_hours[:1],
    )
    async with unit(harness_driver, net_a) as uow:
        assert await uow.projections.upsert_service(SOURCE, slimmer, grant=GRANT, projected_at=AT)
        await uow.commit()
    services, _, _ = await view(harness_driver, net_a)
    assert [r.projection for r in services] == [slimmer]
    # The history view does not show the windows and the place a newer version replaced.
    history, _, _ = await view(harness_driver, net_a, live_only=False)
    assert [r.projection for r in history] == [slimmer]


async def test_ending_marks_the_rows_and_keeps_them_and_reopening_makes_them_live_again(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await open_all(harness_driver, net_a)
    await put(harness_driver, net_a)
    async with unit(harness_driver, net_a) as uow:
        for kind in GrantScope:
            assert await uow.projections.end_source(
                SOURCE, kind, at=LEFT, reason=ProjectionEndReason.LEFT
            )
            assert (
                await uow.projections.mark_ended(
                    SOURCE, kind, at=LEFT, reason=ProjectionEndReason.LEFT
                )
                >= 1
            )
        assert not await uow.projections.upsert_capacity(
            SOURCE, sample_capacity_projection(), grant=GRANT, projected_at=AT
        )
        await uow.commit()
    assert await view(harness_driver, net_a) == ([], [], [])
    services, capacities, criteria = await view(harness_driver, net_a, live_only=False)
    for row in (*services, *capacities, *criteria):
        assert row.ended_at == LEFT and row.end_reason is ProjectionEndReason.LEFT
    async with unit(harness_driver, net_a, read_only=True) as uow:
        state = await uow.network_view.source(SOURCE, GrantScope.CAPACITY)
    assert state is not None and state.status is SourceStatus.ENDED and state.ended_at == LEFT
    # A new grant reopens the source; the next projection makes the rows live and clears the marks.
    await open_all(harness_driver, net_a)
    await put(harness_driver, net_a)
    services, capacities, criteria = await view(harness_driver, net_a)
    assert len(services) == len(capacities) == len(criteria) == 1
    assert all(r.ended_at is None for r in (*services, *capacities, *criteria))


async def test_two_networks_holding_the_same_member_and_service_ids_see_only_their_own_rows(
    harness_driver: AsyncDriver, net_a: str, net_b: str
) -> None:
    await open_all(harness_driver, net_a)
    await open_all(harness_driver, net_b)
    await put(harness_driver, net_a)
    await put(harness_driver, net_b, service={"source_version": 9})
    in_a, _, _ = await view(harness_driver, net_a)
    in_b, _, _ = await view(harness_driver, net_b)
    assert [r.projection.source_version for r in in_a] == [2]
    assert [r.projection.source_version for r in in_b] == [9]
    async with unit(harness_driver, net_a) as uow:
        await uow.projections.end_source(
            SOURCE, GrantScope.CAPACITY, at=LEFT, reason=ProjectionEndReason.LEFT
        )
        await uow.projections.mark_ended(
            SOURCE, GrantScope.CAPACITY, at=LEFT, reason=ProjectionEndReason.LEFT
        )
        await uow.commit()
    assert (await view(harness_driver, net_a))[1] == []
    assert len((await view(harness_driver, net_b))[1]) == 1


async def test_two_members_in_one_network_do_not_collide_on_service_ids(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await open_all(harness_driver, net_a, SOURCE)
    await open_all(harness_driver, net_a, OTHER_SOURCE)
    await put(harness_driver, net_a, SOURCE)
    await put(harness_driver, net_a, OTHER_SOURCE, service={"source_version": 5})
    services, _, _ = await view(harness_driver, net_a)
    assert {(r.source_tenant_id, r.projection.source_version) for r in services} == {
        (SOURCE, 2),
        (OTHER_SOURCE, 5),
    }


async def test_a_tenant_scope_a_read_only_unit_and_a_second_unit_cannot_write(
    harness_driver: AsyncDriver, net_a: str, tenant_id: str
) -> None:
    await open_all(harness_driver, net_a)
    with bind_tenant(tenant_id):
        async with Neo4jUnitOfWork(harness_driver) as uow:
            with pytest.raises(ScopeKindMismatch):
                await uow.projections.upsert_capacity(
                    SOURCE, sample_capacity_projection(), grant=GRANT, projected_at=AT
                )
            with pytest.raises(ScopeKindMismatch):
                await uow.network_view.capacities()
    async with unit(harness_driver, net_a, read_only=True) as uow:
        with pytest.raises(ReadOnlyUnitWrite):
            await uow.projections.upsert_capacity(
                SOURCE, sample_capacity_projection(), grant=GRANT, projected_at=AT
            )
        with bind_tenant(tenant_id), pytest.raises(UnitOfWorkAlreadyOpen):
            async with Neo4jUnitOfWork(harness_driver):
                pass
    assert await view(harness_driver, net_a) == ([], [], [])


async def test_every_property_of_every_node_in_the_scope_is_on_the_allowlist(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await open_all(harness_driver, net_a)
    await put(harness_driver, net_a)

    async def nodes(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (
            await tx.run(
                "MATCH (n {tenantId: $net}) RETURN labels(n) AS labels, properties(n) AS props",
                net=net_a,
            )
        ).data()

    rows = await read_tx(harness_driver, nodes)
    assert rows
    for row in rows:
        [label] = row["labels"]
        permitted = {spec.prop for spec in allowlist.ALLOWLIST.get(label, ())}
        permitted |= allowlist.SYSTEM_PROPERTIES[label]
        assert set(row["props"]) <= permitted, label
        scalars = {k: v for k, v in row["props"].items() if isinstance(v, str | int | float | bool)}
        system = allowlist.SYSTEM_PROPERTIES[label]
        # The scope stamp and the bookkeeping keys (`tenantId`, `sourceTenantId`) are the store's
        # own and are on the permitted list above: a forbidden-key scan of a message does not apply
        # to them, but their values are still scanned for patient-like text.
        assert scan_value({k: v for k, v in scalars.items() if k not in system}) == []
        assert scan_value([v for k, v in scalars.items() if k in system]) == []


async def test_a_duplicate_key_is_refused_by_the_schema(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    async def twice(tx: AsyncManagedTransaction) -> None:
        for _ in range(2):
            await tx.run(
                "CREATE (:ProjectedCapacity {tenantId: $net, sourceTenantId: 'tenant-x', "
                "sourceServiceId: 'svc-1'})",
                net=net_a,
            )

    with pytest.raises(ConstraintError):
        await write_tx(harness_driver, twice)


async def test_of_racing_versions_the_newest_wins_and_nothing_is_written_after_an_end(
    harness_driver: AsyncDriver, net_a: str
) -> None:
    await open_all(harness_driver, net_a)

    async def write(version: int) -> bool:
        async with unit(harness_driver, net_a) as uow:
            done = await uow.projections.upsert_capacity(
                SOURCE,
                sample_capacity_projection(source_version=1_000 + version),
                grant=GRANT,
                projected_at=AT,
            )
            await uow.commit()
            return bool(done)

    await asyncio.gather(*(write(n) for n in (3, 1, 7, 5, 2, 6, 4)))
    _, capacities, _ = await view(harness_driver, net_a)
    assert [r.projection.source_version for r in capacities] == [1_007]
    async with unit(harness_driver, net_a) as uow:
        await uow.projections.end_source(
            SOURCE, GrantScope.CAPACITY, at=LEFT, reason=ProjectionEndReason.GRANT_ENDED
        )
        await uow.commit()
    assert not await write(9)
    _, capacities, _ = await view(harness_driver, net_a)
    assert [r.projection.source_version for r in capacities] == [1_007]
