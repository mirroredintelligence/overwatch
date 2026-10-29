"""The unit of work's repository registry (P06), and its scope (TEN-002).

The registry tests never enter the unit. The scope tests enter it on a recording fake driver
(tests/support/fake_neo4j.py): no Neo4j, so what they show is what the unit handed to the driver and
to its repositories.
"""

import asyncio
import typing
from typing import Any, cast

import pytest

from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.queries import NamedQuery, QueryRegistry, Scenario
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.unit_of_work import (
    DEFAULT_FACTORIES,
    Neo4jUnitOfWork,
    RepositoryFactory,
)
from diucs.application.ports.outbound.unit_of_work import UnitOfWork
from diucs.application.tenancy import (
    ScopeId,
    TenantNotBound,
    UnitOfWorkAlreadyOpen,
    bind_scope,
    bind_tenant,
)
from diucs.domain.errors import Conflict
from tests.support.fake_neo4j import FakeDriver

# Every attribute of the UnitOfWork port, from docs/spec/contracts.md, plus the three P16 stores
# that DEC-071 item 9 and lesson L86 ask P06 to register, and the support store (O06).
REQUIRED_NAMES = {
    "services",
    "alert_subscriptions",
    "alerts",
    "clinical_requests",
    "push_subscriptions",
    "service_moves",
    "protected_text",
    "safety_reports",
    "capacity",
    "bookings",
    "cases",
    "people",
    "criteria",
    "registrations",
    "scope",
    "flags",
    "communications",
    "link_tokens",
    "scheduled_work",
    "audit",
    "outbox",
    "contacts",
    "pins",
    "devices",
    "idempotency",
    "processed",
    "support",
}


def test_an_attribute_with_no_factory_raises_a_clear_attribute_error() -> None:
    uow = Neo4jUnitOfWork(driver=object(), factories={}, clock=None)  # type: ignore[arg-type]

    with pytest.raises(
        AttributeError, match="unit of work has no 'services' repository registered"
    ):
        _ = uow.services


def test_the_default_factories_register_every_repository_of_the_port() -> None:
    assert set(DEFAULT_FACTORIES) == REQUIRED_NAMES


# The scope of a unit of work (TEN-002, DEC-132 item 4)

A1 = ScopeId.tenant("a1")
B1 = ScopeId.tenant("b1")
NOT_OPEN = "the unit of work is not open; use it inside 'async with'"
PROBE_CYPHER = "MATCH (n:Probe {id: $id, tenantId: $tenant}) RETURN n.id AS id"


def _probe_registry() -> QueryRegistry:
    registry = QueryRegistry()
    registry.register(
        NamedQuery(
            id="Q-PROBE",
            cypher=PROBE_CYPHER,
            mode="read",
            scenario=Scenario("placeholder until TEN-004"),
        )
    )
    return registry


class _Probe:
    """A repository of the test: it runs one registered statement on the transaction it was
    given, as the real repositories do."""

    def __init__(self, tx: object, registry: QueryRegistry) -> None:
        self._tx = tx
        self._registry = registry

    async def look(self, id: str = "x") -> list[dict[str, Any]]:
        return await run_query(
            self._tx,  # type: ignore[arg-type]
            self._registry.get("Q-PROBE"),
            registry=self._registry,
            id=id,
        )

    async def refuse(self) -> None:
        raise Conflict("a write was refused")

    async def refuse_again(self) -> None:
        raise Conflict("another write was refused")

    label = "probe"


class _Rig:
    """A unit of work on a fake driver with one extra repository, `probe`, and a record of what
    its factory was given."""

    def __init__(self) -> None:
        self.driver = FakeDriver()
        self.registry = _probe_registry()
        self.received: list[tuple[object, ResourceStore]] = []

        def make(tx: Any, store: ResourceStore) -> object:
            self.received.append((tx, store))
            return _Probe(tx, self.registry)

        self.factories: dict[str, RepositoryFactory] = {"probe": make}

    def unit(self) -> Any:
        return Neo4jUnitOfWork(cast(Any, self.driver), self.factories)


async def test_a_unit_of_work_reports_the_scope_it_opened_under() -> None:
    rig = _Rig()
    with bind_tenant("a1"):
        async with rig.unit() as uow:
            assert uow.unit_scope == A1


async def test_every_repository_and_the_resource_store_are_given_a_scoped_transaction() -> None:
    rig = _Rig()
    with bind_tenant("a1"):
        async with rig.unit() as uow:
            await uow.probe.look()
    [(tx, store)] = rig.received
    assert isinstance(tx, ScopedTx)
    assert tx.scope == A1
    assert tx.tx is rig.driver.transactions[0]
    with bind_tenant("b1"):
        rig.driver.calls.clear()
        # The resource store was built on the same scoped transaction.
        assert await store.exists("Service", "x") is False
    assert rig.driver.tenants_sent() == ["a1"]


async def test_the_scope_before_the_unit_is_entered_is_not_available() -> None:
    uow = _Rig().unit()
    with pytest.raises(RuntimeError, match=NOT_OPEN):
        _ = uow.unit_scope


async def test_the_scope_stays_readable_after_the_unit_has_finished() -> None:
    rig = _Rig()
    with bind_tenant("a1"):
        async with rig.unit() as uow:
            pass
    assert uow.unit_scope == A1


async def test_the_unit_port_has_the_scope_property() -> None:
    assert "unit_scope" in typing.get_protocol_members(UnitOfWork)


async def test_rebinding_the_context_inside_a_unit_changes_nothing_for_that_unit() -> None:
    rig = _Rig()
    with bind_tenant("a1"):
        async with rig.unit() as uow:
            await uow.probe.look("1")
            with bind_tenant("b1"):
                await uow.probe.look("2")
                with bind_scope(ScopeId.network("net-pilot")):
                    await uow.probe.look("3")
            await uow.probe.look("4")
            assert uow.unit_scope == A1
    assert rig.driver.tenants_sent() == ["a1", "a1", "a1", "a1"]


async def test_a_unit_opened_with_no_scope_bound_runs_only_statements_not_yet_converted() -> None:
    rig = _Rig()
    async with rig.unit() as uow:
        assert uow.unit_scope is None
        # A scope bound later does not reach the unit: it opened unbound and stays unbound.
        with bind_tenant("b1"), pytest.raises(TenantNotBound):
            await uow.probe.look()
    assert rig.driver.calls == []


async def test_an_unbound_unit_does_not_leave_its_claim_behind() -> None:
    rig = _Rig()
    async with rig.unit():
        pass
    with bind_tenant("a1"):
        async with rig.unit() as uow:
            assert uow.unit_scope == A1


# Nested units


async def test_a_second_unit_cannot_open_while_one_is_open_and_opens_no_session() -> None:
    rig = _Rig()
    with bind_tenant("a1"):
        async with rig.unit() as first:
            with pytest.raises(UnitOfWorkAlreadyOpen):
                async with rig.unit():
                    pytest.fail("the second unit must not open")
            assert rig.driver.session_calls == 1
            await first.probe.look()
            await first.commit()
    assert rig.driver.transactions[0].committed


async def test_a_second_unit_opens_once_the_first_has_committed_inside_its_block() -> None:
    rig = _Rig()
    with bind_tenant("a1"):
        async with rig.unit() as first:
            await first.commit()
            async with rig.unit() as second:
                assert second.unit_scope == A1


async def test_a_second_unit_opens_once_the_first_has_rolled_back_inside_its_block() -> None:
    rig = _Rig()
    async with rig.unit() as first:
        await first.rollback()
        async with rig.unit():
            pass


@pytest.mark.parametrize("fails", [False, True])
async def test_a_second_unit_opens_after_the_first_block_has_exited(fails: bool) -> None:
    rig = _Rig()
    try:
        async with rig.unit():
            if fails:
                raise ValueError("stop")
    except ValueError:
        pass
    async with rig.unit():
        pass
    assert rig.driver.closed_sessions == 2


async def test_two_units_opened_in_two_tasks_both_work() -> None:
    rig = _Rig()

    async def one(tenant: str) -> ScopeId | None:
        with bind_tenant(tenant):
            async with rig.unit() as uow:
                await asyncio.sleep(0)
                await uow.probe.look()
                return uow.unit_scope  # type: ignore[no-any-return]

    assert await asyncio.gather(one("a1"), one("b1")) == [A1, B1]
    assert sorted(rig.driver.tenants_sent()) == ["a1", "b1"]


async def test_a_task_started_inside_an_open_unit_cannot_open_another() -> None:
    rig = _Rig()

    async def child() -> None:
        async with rig.unit():
            pytest.fail("the child unit must not open")

    async with rig.unit():
        with pytest.raises(UnitOfWorkAlreadyOpen):
            await asyncio.create_task(child())
    assert rig.driver.session_calls == 1


async def test_a_failed_begin_closes_the_session_releases_the_claim_and_raises_the_original() -> (
    None
):
    rig = _Rig()
    rig.driver.begin_error = ConnectionError("no route")
    with pytest.raises(ConnectionError, match="no route"):
        async with rig.unit():
            pytest.fail("the unit must not open")
    assert rig.driver.session_calls == 1
    assert rig.driver.closed_sessions == 1
    rig.driver.begin_error = None
    async with rig.unit():
        pass


async def test_a_session_that_cannot_be_opened_releases_the_claim_and_raises_the_original() -> None:
    rig = _Rig()
    rig.driver.open_error = ConnectionError("no route")
    with pytest.raises(ConnectionError, match="no route"):
        async with rig.unit():
            pytest.fail("the unit must not open")
    rig.driver.open_error = None
    async with rig.unit():
        pass


async def test_a_unit_is_used_once_and_a_refused_reuse_does_not_free_a_claim_it_does_not_hold() -> (
    None
):
    rig = _Rig()
    first = rig.unit()
    async with first:
        await first.commit()
    other = rig.unit()
    async with other:
        with pytest.raises(RuntimeError, match="used once"):
            async with first:
                pass
        with pytest.raises(UnitOfWorkAlreadyOpen):
            async with rig.unit():
                pass


# The write guard and the refused commit are unchanged


async def test_a_refused_write_still_rolls_back_the_commit_and_then_frees_the_claim() -> None:
    rig = _Rig()
    async with rig.unit() as uow:
        with pytest.raises(Conflict):
            await uow.probe.refuse()
        with pytest.raises(Conflict, match="nothing was committed"):
            await uow.commit()
        assert rig.driver.transactions[0].rolled_back
        assert not rig.driver.transactions[0].committed
        async with rig.unit():
            pass


async def test_exiting_a_unit_that_was_never_entered_does_not_free_another_units_claim() -> None:
    rig = _Rig()
    async with rig.unit():
        stranger = rig.unit()
        await stranger.__aexit__(None, None, None)
        with pytest.raises(UnitOfWorkAlreadyOpen):
            async with rig.unit():
                pytest.fail("the claim of the open unit was freed")


# The states around the scope (each guard that was already there keeps its message)


async def test_a_unit_that_is_not_open_refuses_a_repository_a_rollback_and_its_own_handles() -> (
    None
):
    rig = _Rig()
    uow = rig.unit()
    with pytest.raises(RuntimeError, match=NOT_OPEN):
        _ = uow.probe
    with pytest.raises(RuntimeError, match=NOT_OPEN):
        await uow.rollback()
    with pytest.raises(RuntimeError, match=NOT_OPEN):
        await uow.commit()
    for handle in ("_require_tx", "_require_scoped", "_require_store"):
        with pytest.raises(RuntimeError, match="use it inside 'async with'"):
            getattr(uow, handle)()
    with pytest.raises(AttributeError):
        _ = uow._private
    with pytest.raises(AttributeError, match="no 'services' repository registered"):
        _ = Neo4jUnitOfWork(cast(Any, rig.driver), {}).services


async def test_a_finished_unit_cannot_be_rolled_back() -> None:
    rig = _Rig()
    async with rig.unit() as uow:
        await uow.commit()
        with pytest.raises(RuntimeError, match="is finished"):
            await uow.rollback()


async def test_a_repository_attribute_that_is_not_a_coroutine_passes_through_the_guard() -> None:
    rig = _Rig()
    async with rig.unit() as uow:
        assert uow.probe.label == "probe"


async def test_the_first_refused_write_is_the_one_the_commit_reports() -> None:
    rig = _Rig()
    async with rig.unit() as uow:
        with pytest.raises(Conflict):
            await uow.probe.refuse()
        with pytest.raises(Conflict):
            await uow.probe.refuse_again()
        with pytest.raises(Conflict, match="nothing was committed") as raised:
            await uow.commit()
        assert str(raised.value.__cause__) == "a write was refused"
