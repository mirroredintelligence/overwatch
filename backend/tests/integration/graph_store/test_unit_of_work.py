"""Integration tests for the Neo4j unit of work (P06, DEC-012, DEC-083 item 9).

Each test runs against the throwaway Neo4j of the F10 harness. What a test asserts is read back
through a fresh session or a fresh unit of work, so it is what was really stored. Values are
synthetic.
"""

import asyncio
import contextvars
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncSession

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.health import HealthStatus, neo4j_health
from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.outbound.graph_store.queries import (
    REGISTRY,
    NamedQuery,
    QueryRegistry,
    Scenario,
)
from diucs.adapters.outbound.graph_store.unit_of_work import DEFAULT_FACTORIES, neo4j_uow_factory
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.outbox import OutboxMessage, outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, TenantNotBound, UnitOfWorkAlreadyOpen, bind_tenant
from diucs.application.work import ScheduledWork, WorkKind
from diucs.bootstrap.container import build_for_tests
from diucs.domain.codes import ReportSource, Role
from diucs.domain.errors import Conflict
from diucs.domain.events import CapacityReported
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import ThrowawayNeo4j, count_nodes
from tests.unit.adapters.outbound.graph_store.test_service_repository import UCR_WEST

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


@pytest_asyncio.fixture(loop_scope="session")
async def audit_head(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    """The audit chain head exists, as it does after startup. Runs after the graph is wiped."""
    await ensure_audit_head(neo4j_driver)


def _entry() -> AuditEntry:
    return AuditEntry(
        action="report-capacity",
        use_case="ReportCapacity",
        actor=Actor(
            role=Role.REPORTER,
            practitioner_id=None,
            device_id="dev-sms-1",
            channel="text",
            service_ids=frozenset({"svc-ucr-west"}),
            tenant_id=ACTOR_TENANT,
        ),
        entity_ids=("obs-1",),
        snapshot=None,
        at=NOW,
    )


def _capacity_message(message_id: str) -> OutboxMessage:
    event = CapacityReported(
        service_id="svc-ucr-west",
        report_id="rep-1",
        value=8,
        source=ReportSource.TEXT,
        at=NOW,
    )
    return outbox_message_for(event, id=message_id, now=NOW)


def _work(work_id: str, due_hour: int) -> ScheduledWork:
    return ScheduledWork(
        id=work_id,
        kind=WorkKind.REMINDER,
        due_at=datetime(2026, 10, 23, due_hour, 0, tzinfo=UTC),
        about_id="svc-ucr-west",
        sequence_number=None,
        status="scheduled",
    )


async def test_the_service_audit_entry_and_outbox_message_commit_together(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async with uow_factory() as uow:
        await uow.services.save(UCR_WEST)
        await uow.audit.append(_entry())
        await uow.outbox.add(_capacity_message("out-1"))
        await uow.commit()

    assert await count_nodes(neo4j_driver, "HealthcareService") == 1
    assert await count_nodes(neo4j_driver, "AuditEvent") == 1
    assert await count_nodes(neo4j_driver, "OutboxMessage") == 1
    async with uow_factory() as uow:
        assert await uow.services.get("svc-ucr-west") == UCR_WEST


async def test_without_commit_none_of_the_three_writes_is_stored(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async with uow_factory() as uow:
        await uow.services.save(UCR_WEST)
        await uow.audit.append(_entry())
        await uow.outbox.add(_capacity_message("out-1"))

    assert await count_nodes(neo4j_driver, "HealthcareService") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0
    assert await count_nodes(neo4j_driver, "OutboxMessage") == 0


async def test_an_exception_inside_the_block_stores_nothing_and_propagates(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    with pytest.raises(RuntimeError, match="stop here"):
        async with uow_factory() as uow:
            await uow.services.save(UCR_WEST)
            await uow.outbox.add(_capacity_message("out-1"))
            raise RuntimeError("stop here")

    assert await count_nodes(neo4j_driver, "HealthcareService") == 0
    assert await count_nodes(neo4j_driver, "OutboxMessage") == 0


async def test_two_repositories_in_one_unit_of_work_share_the_store_and_the_transaction(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        assert uow.services._store is uow.capacity._store  # type: ignore[attr-defined]
        assert uow.services._tx is uow.capacity._tx  # type: ignore[attr-defined]
        await uow.rollback()


async def test_a_conflict_that_the_caller_swallows_cannot_be_committed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    """DEC-083 item 9: a write that raised Conflict is never committed, even if the caller caught
    the Conflict and carried on. Scheduled work with one id and two sets of values is the
    Conflict."""
    async with uow_factory() as uow:
        await uow.services.save(UCR_WEST)
        await uow.scheduled_work.add(_work("work-1", 14))
        with pytest.raises(Conflict):
            await uow.scheduled_work.add(_work("work-1", 15))
        with pytest.raises(Conflict):
            await uow.commit()

    assert await count_nodes(neo4j_driver, "HealthcareService") == 0
    assert await count_nodes(neo4j_driver, "ScheduledWork") == 0


class _CountingSource:
    """Test instrumentation only: counts the sessions the unit of work opens and closes."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver
        self.open_sessions = 0

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        self.open_sessions += 1
        try:
            async with self._driver.session() as session:
                yield session
        finally:
            self.open_sessions -= 1


async def test_the_session_is_closed_after_commit_rollback_and_an_error(
    neo4j_driver: AsyncDriver,
) -> None:
    source = _CountingSource(neo4j_driver)
    factory = neo4j_uow_factory(source)

    async with factory() as uow:
        assert source.open_sessions == 1
        await uow.commit()
    assert source.open_sessions == 0

    with pytest.raises(RuntimeError):
        async with factory():
            raise RuntimeError("stop here")
    assert source.open_sessions == 0

    async with factory():
        pass
    assert source.open_sessions == 0


async def test_a_committed_unit_of_work_cannot_be_used_again(
    uow_factory: UnitOfWorkFactory,
) -> None:
    async with uow_factory() as uow:
        await uow.commit()

    with pytest.raises(RuntimeError):
        await uow.commit()
    with pytest.raises(RuntimeError):
        _ = uow.services


async def test_a_repository_added_to_the_mapping_is_built_on_the_unit_of_work(
    neo4j_driver: AsyncDriver,
) -> None:
    class Probe:
        async def ping(self) -> str:
            return "pong"

    factories = {**DEFAULT_FACTORIES, "probe": lambda tx, store: Probe()}
    async with neo4j_uow_factory(neo4j_driver, factories=factories)() as uow:
        assert await uow.probe.ping() == "pong"  # type: ignore[attr-defined]
        await uow.commit()


async def test_the_container_hands_out_units_of_work_on_its_own_connection(
    harness_container: ThrowawayNeo4j,
) -> None:
    """The composition root wires one unit of work factory on the process's one connection
    (DEC-012, lesson L12). A unit of work that commits leaves no session open."""
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        container = build_for_tests(neo4j=connection)
        async with container.uow_factory() as uow:
            await uow.commit()
        assert connection.open_session_count == 0
    finally:
        await connection.close()


async def test_a_unit_of_work_can_be_entered_only_once(uow_factory: UnitOfWorkFactory) -> None:
    uow = uow_factory()
    async with uow:
        await uow.commit()

    with pytest.raises(RuntimeError):
        async with uow:
            pass


async def test_a_committed_unit_of_work_cannot_be_rolled_back(
    uow_factory: UnitOfWorkFactory,
) -> None:
    uow = uow_factory()
    async with uow:
        await uow.commit()

    with pytest.raises(RuntimeError):
        await uow.rollback()


# The scope of a unit of work against the real server (TEN-002)

_TENANT_ECHO = NamedQuery(
    id="Q-TEST-UOW-ECHO",
    cypher="RETURN $tenant AS tenant",
    mode="read",
    scenario=Scenario("placeholder until TEN-004"),
)


class _Echo:
    """A repository of the test: it runs registered statements on the transaction it is given."""

    def __init__(self, tx: Any) -> None:
        self._tx = tx
        self._registry = QueryRegistry()
        self._registry.register(_TENANT_ECHO)

    async def tenant(self) -> list[dict[str, Any]]:
        return await run_query(
            self._tx, self._registry.get(_TENANT_ECHO.id), registry=self._registry
        )

    async def active_services(self) -> list[dict[str, Any]]:
        # A converted statement: it runs only under a bound tenant.
        return await run_query(self._tx, REGISTRY.get("Q-SVC-LIST-ACTIVE"))


def _echo_factory(neo4j_driver: AsyncDriver) -> UnitOfWorkFactory:
    return neo4j_uow_factory(
        neo4j_driver, factories={**DEFAULT_FACTORIES, "echo": lambda tx, s: _Echo(tx)}
    )


async def _unbound[T](work: Awaitable[T]) -> T:
    """Run the awaitable in an empty context, so nothing is bound whatever the fixtures did."""
    return await asyncio.create_task(_as_coroutine(work), context=contextvars.Context())


async def _as_coroutine[T](work: Awaitable[T]) -> T:
    return await work


async def test_the_server_accepts_the_tenant_parameter_a_unit_sends(
    neo4j_driver: AsyncDriver,
) -> None:
    with bind_tenant("a1"):
        async with _echo_factory(neo4j_driver)() as uow:
            assert await uow.echo.tenant() == [{"tenant": "a1"}]  # type: ignore[attr-defined]
            assert await uow.echo.active_services() == []  # type: ignore[attr-defined]
            await uow.commit()


async def test_a_unit_keeps_its_tenant_against_the_real_server_when_the_context_moves(
    neo4j_driver: AsyncDriver,
) -> None:
    with bind_tenant("a1"):
        async with _echo_factory(neo4j_driver)() as uow:
            with bind_tenant("b1"):
                assert await uow.echo.tenant() == [{"tenant": "a1"}]  # type: ignore[attr-defined]
            assert uow.unit_scope == ScopeId.tenant("a1")


async def test_health_and_migrations_run_with_nothing_bound_and_with_a_tenant_bound(
    harness_container: ThrowawayNeo4j, neo4j_driver: AsyncDriver
) -> None:
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        for bound in (False, True):
            if bound:
                with bind_tenant("a1"):
                    health = await neo4j_health(connection, timeout=5)
                    applied = await apply_migrations(neo4j_driver)
            else:
                health = await _unbound(neo4j_health(connection, timeout=5))
                applied = await _unbound(apply_migrations(neo4j_driver))
            assert health.status is HealthStatus.OK
            assert applied == []
        assert connection.open_session_count == 0
    finally:
        await connection.close()


async def test_a_unit_opened_with_nothing_bound_refuses_a_converted_statement_and_leaks_nothing(
    harness_container: ThrowawayNeo4j,
) -> None:
    connection = Neo4jConnection(
        harness_container.uri, harness_container.user, harness_container.password
    )
    await connection.open()
    try:
        factory = neo4j_uow_factory(
            connection, factories={**DEFAULT_FACTORIES, "echo": lambda tx, s: _Echo(tx)}
        )

        async def unbound_unit() -> None:
            async with factory() as uow:
                assert uow.unit_scope is None
                with pytest.raises(TenantNotBound):
                    await uow.echo.tenant()  # type: ignore[attr-defined]
                # Q-SVC-LIST-ACTIVE is converted (TEN-010): with nothing bound it refuses.
                with pytest.raises(TenantNotBound):
                    await uow.echo.active_services()  # type: ignore[attr-defined]

        await _unbound(unbound_unit())
        assert connection.open_session_count == 0
    finally:
        await connection.close()


async def test_a_unit_that_committed_or_raised_frees_the_next_one_in_the_same_task(
    neo4j_driver: AsyncDriver,
) -> None:
    factory = neo4j_uow_factory(neo4j_driver)
    async with factory() as first:
        await first.commit()
        async with factory() as second:
            await second.commit()
    with pytest.raises(ValueError, match="stop"):
        async with factory():
            raise ValueError("stop")
    async with factory() as third:
        await third.commit()


async def test_a_second_unit_cannot_open_inside_an_open_one_on_the_real_server(
    neo4j_driver: AsyncDriver,
) -> None:
    source_sessions = 0
    factory = neo4j_uow_factory(neo4j_driver)
    async with factory() as first:
        with pytest.raises(UnitOfWorkAlreadyOpen):
            async with factory():
                source_sessions += 1
        await first.commit()
    assert source_sessions == 0
