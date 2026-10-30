"""Integration tests for scope list management (U23), against the real Neo4j the harness starts.

The shift lead's list of services, each flagged in pilot, later or out of scope. Every assertion
reads back through a fresh unit of work or the harness helpers. Service names are sample values.
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.scope_list import (
    AddScopeEntry,
    AddScopeEntryCommand,
    AddScopeEntryResult,
    ListScope,
    ScopeRow,
    SetScopeFlag,
    SetScopeFlagCommand,
)
from diucs.domain.codes import RegistrationStatus, Role, ScopeFlag, ServiceCategory
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.registration import Registration
from tests.support.actors import ACTOR_TENANT
from tests.support.neo4j import count_nodes, node_props, read_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
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


def add_use_case(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, ids: SequentialIds
) -> AddScopeEntry:
    return AddScopeEntry(uow_factory, DriverIdempotencyStore(driver), ids, FixedClock(NOW))


def set_use_case(uow_factory: UnitOfWorkFactory, driver: AsyncDriver) -> SetScopeFlag:
    return SetScopeFlag(uow_factory, DriverIdempotencyStore(driver), FixedClock(NOW))


@pytest.fixture
async def clean(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    """A fresh graph with its audit head (the wipe removes it)."""
    await ensure_audit_head(neo4j_driver)


async def _add_ucr_east(
    uow_factory: UnitOfWorkFactory, driver: AsyncDriver, key: str = "add-ucr-east"
) -> AddScopeEntryResult:
    return await add_use_case(uow_factory, driver, SequentialIds("svc")).execute(
        AddScopeEntryCommand(
            idempotency_key=key,
            actor=LEAD,
            name="UCR East",
            category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
            flag=ScopeFlag.IN_PILOT,
        )
    )


async def test_adding_ucr_east_in_pilot_stores_an_inactive_placeholder_and_one_audit_entry(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean: None
) -> None:
    result = await _add_ucr_east(uow_factory, neo4j_driver)
    async with uow_factory() as uow:
        entry = await uow.scope.get_entry(result.service_id)
    assert entry is not None and entry.flag is ScopeFlag.IN_PILOT
    assert entry.name == "UCR East"
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1
    # A placeholder has no profile until it registers, so ServiceRepository.get refuses it (L104).
    service = await node_props(neo4j_driver, "HealthcareService", id=result.service_id)
    assert service["active"] is False
    audit = await node_props(neo4j_driver, "AuditEvent", useCase="AddScopeEntry")
    assert audit["action"] == "C"


async def test_a_later_entry_without_a_reason_is_refused_and_creates_no_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean: None
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        await add_use_case(uow_factory, neo4j_driver, SequentialIds("svc")).execute(
            AddScopeEntryCommand(
                idempotency_key="later-1",
                actor=LEAD,
                name="UCR North",
                category=ServiceCategory.OTHER,
                flag=ScopeFlag.LATER,
            )
        )
    assert refused.value.field == "reason"
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0


async def test_changing_to_out_of_scope_reads_back_the_flag_and_audits_before_and_after(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean: None
) -> None:
    result = await _add_ucr_east(uow_factory, neo4j_driver)
    await set_use_case(uow_factory, neo4j_driver).execute(
        SetScopeFlagCommand(
            idempotency_key="out-1",
            actor=LEAD,
            service_id=result.service_id,
            flag=ScopeFlag.OUT_OF_SCOPE,
            reason="Not on the Dorset pathway",
        )
    )
    async with uow_factory() as uow:
        entry = await uow.scope.get_entry(result.service_id)
    assert entry is not None
    assert entry.flag is ScopeFlag.OUT_OF_SCOPE
    assert entry.reason == "Not on the Dorset pathway"
    audit = await node_props(neo4j_driver, "AuditEvent", useCase="SetScopeFlag")
    assert audit["action"] == "U"
    snapshot = await _snapshot_of(neo4j_driver, "SetScopeFlag")
    assert snapshot["before"] == "in-pilot"
    assert snapshot["after"] == "out-of-scope"


async def test_an_advisor_is_not_allowed_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean: None
) -> None:
    with pytest.raises(NotAllowed):
        await add_use_case(uow_factory, neo4j_driver, SequentialIds("svc")).execute(
            AddScopeEntryCommand(
                idempotency_key="advisor-1",
                actor=ADVISOR,
                name="UCR East",
                category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
                flag=ScopeFlag.IN_PILOT,
            )
        )
    assert await count_nodes(neo4j_driver, "HealthcareService") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0


async def test_the_list_puts_in_pilot_first_and_shows_none_before_any_invitation(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean: None
) -> None:
    await _add_ucr_east(uow_factory, neo4j_driver)
    await add_use_case(uow_factory, neo4j_driver, SequentialIds("later")).execute(
        AddScopeEntryCommand(
            idempotency_key="later-2",
            actor=LEAD,
            name="Alpha Ward",
            category=ServiceCategory.INPATIENT_BEDS,
            flag=ScopeFlag.LATER,
            reason="Not yet",
        )
    )
    rows: tuple[ScopeRow, ...] = await ListScope(uow_factory).execute(LEAD)
    assert [row.name for row in rows] == ["UCR East", "Alpha Ward"]
    assert [row.registration_status for row in rows] == [None, None]


async def test_the_list_shows_the_latest_registration_status_of_a_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean: None
) -> None:
    result = await _add_ucr_east(uow_factory, neo4j_driver)
    async with uow_factory() as uow:
        await uow.registrations.add(
            Registration(
                id="reg-1",
                service_id=result.service_id,
                status=RegistrationStatus.INVITED,
                requester_role_id=None,
                owner_role_id=None,
                created_at=NOW,
                last_modified=NOW,
            )
        )
        await uow.commit()
    rows = await ListScope(uow_factory).execute(LEAD)
    assert rows[0].registration_status is RegistrationStatus.INVITED


async def test_the_same_key_replayed_gives_the_same_service_and_one_service(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean: None
) -> None:
    first = await _add_ucr_east(uow_factory, neo4j_driver, key="replay-1")
    second = await _add_ucr_east(uow_factory, neo4j_driver, key="replay-1")
    assert first == second
    assert await count_nodes(neo4j_driver, "HealthcareService") == 1


async def _snapshot_of(driver: AsyncDriver, use_case: str) -> dict[str, Any]:
    """The snapshot an audit entry of this use case holds, read through its SNAPSHOT link. The graph
    holds one snapshot per entry, so a read by label alone is ambiguous."""

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (:AuditEvent {useCase: $useCase})-[:SNAPSHOT]->(s:Snapshot) "
            "RETURN s.json AS json",
            useCase=use_case,
        )
        return await result.data()

    rows = await read_tx(driver, work)
    assert len(rows) == 1, f"expected exactly 1 snapshot for {use_case}, found {len(rows)}"
    parsed: dict[str, Any] = json.loads(rows[0]["json"])
    return parsed
