"""The network read use cases on a real Neo4j (TEN-057, DEC-546, DEC-132 item 4).

Written, not run, in build wave 5 (the owner's instruction: the whole integration suite runs once,
on the merged tip).

Three members of one network have each granted capacity, directory and criteria and had a service
admitted; the projector has run for all three. A member's staff read the board, the directory and
the criteria through the registry's own record of their tenant. The tests show: every member's
service is on the board; a tenant that never joined gets NotFound, as does a member who has left;
a grant that ended takes that member's service off the board and the directory at once; a member
who left stays in the history with the leave date and not on the live board; and nothing in a
result names a member's tenant, a grant or a source service id.
"""

import os
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.unit_of_work import neo4j_network_uow_factory
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.network_access import NetworkAccess
from diucs.application.use_cases.query_network_board import QueryNetworkBoard
from diucs.application.use_cases.query_network_directory import (
    QueryNetworkCriteria,
    QueryNetworkDirectory,
)
from diucs.domain.codes import Role, Status
from diucs.domain.errors import NotFound
from diucs.domain.model.network import GrantScope
from tests.support.network_world import NOW, NetworkWorld, world_ids
from tests.support.tenancy import RunIdentity

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _Tenant:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name


class _Names:
    """The tenant directory's display names, for the tenants of this run."""

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
    harness_driver: AsyncDriver, connection: Neo4jConnection, run_identity: RunIdentity
) -> AsyncIterator[NetworkWorld]:
    built = await NetworkWorld.build(harness_driver, connection, world_ids(run_identity))
    await built.run_projector()
    yield built
    await built.cleanup()


def _staff(tenant: str) -> Actor:
    return Actor(
        role=Role.ADVISOR,
        practitioner_id="prac-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _gate(world: NetworkWorld) -> NetworkAccess:
    return NetworkAccess(world.registry, _Names())  # type: ignore[arg-type]


def _factory(world: NetworkWorld):  # type: ignore[no-untyped-def]
    return neo4j_network_uow_factory(world.driver, read_only=True)


def _clock() -> FixedClock:
    return FixedClock(NOW + timedelta(minutes=2))


async def test_every_members_service_is_on_the_board_for_every_member(world: NetworkWorld) -> None:
    board = QueryNetworkBoard(_factory(world), _gate(world), _clock())
    for member in world.ids.members:
        result = await board.execute(_staff(member), world.ids.network)
        assert len(result.board.entries) == 3
        assert {e.service_name for e in result.board.entries} == {
            world.service_name(m) for m in world.ids.members
        }


async def test_a_tenant_that_never_joined_is_not_found(world: NetworkWorld) -> None:
    board = QueryNetworkBoard(_factory(world), _gate(world), _clock())
    with pytest.raises(NotFound):
        await board.execute(_staff(world.ids.outsider), world.ids.network)


async def test_the_status_is_worked_out_at_the_time_of_the_read(world: NetworkWorld) -> None:
    board = QueryNetworkBoard(_factory(world), _gate(world), _clock())
    later = QueryNetworkBoard(_factory(world), _gate(world), FixedClock(NOW + timedelta(days=5)))
    member = world.ids.members[0]
    fresh = await board.execute(_staff(member), world.ids.network)
    stale = await later.execute(_staff(member), world.ids.network)
    assert all(e.status is Status.NOT_UPDATED for e in stale.board.entries)
    assert len(fresh.board.entries) == len(stale.board.entries) == 3


async def test_a_result_names_no_tenant_no_grant_and_no_source_service(world: NetworkWorld) -> None:
    member = world.ids.members[0]
    board = await QueryNetworkBoard(_factory(world), _gate(world), _clock()).execute(
        _staff(member), world.ids.network
    )
    directory = await QueryNetworkDirectory(_factory(world), _gate(world), _clock()).execute(
        _staff(member), world.ids.network
    )
    criteria = await QueryNetworkCriteria(_factory(world), _gate(world), _clock()).execute(
        _staff(member), world.ids.network
    )
    text = repr((board, directory, criteria))
    for tenant in (*world.ids.members, world.ids.owner):
        assert tenant not in text
    assert "grant-" not in text


async def test_a_grant_that_ended_takes_the_service_off_the_board_and_the_directory(
    world: NetworkWorld,
) -> None:
    member, other = world.ids.members[0], world.ids.members[1]
    await world.end_grant(other, GrantScope.CAPACITY)
    board = await QueryNetworkBoard(_factory(world), _gate(world), _clock()).execute(
        _staff(member), world.ids.network
    )
    assert world.service_name(other) not in {e.service_name for e in board.board.entries}
    directory = await QueryNetworkDirectory(_factory(world), _gate(world), _clock()).execute(
        _staff(member), world.ids.network
    )
    assert world.service_name(other) in {e.service_name for e in directory.entries}  # its own scope


async def test_a_member_who_left_is_refused_and_stays_in_the_history(world: NetworkWorld) -> None:
    member, leaver = world.ids.members[0], world.ids.members[2]
    await world.leave(leaver)
    with pytest.raises(NotFound):
        await QueryNetworkBoard(_factory(world), _gate(world), _clock()).execute(
            _staff(leaver), world.ids.network
        )
    live = await QueryNetworkDirectory(_factory(world), _gate(world), _clock()).execute(
        _staff(member), world.ids.network
    )
    assert world.service_name(leaver) not in {e.service_name for e in live.entries}
    history = await QueryNetworkDirectory(_factory(world), _gate(world), _clock()).execute(
        _staff(member), world.ids.network, history=True
    )
    ended = [e for e in history.entries if e.ended_at is not None]
    assert {e.service_name for e in ended} == {world.service_name(leaver)}
