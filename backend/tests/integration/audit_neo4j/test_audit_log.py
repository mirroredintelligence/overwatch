"""Integration tests for the audit log and provenance on Neo4j (P05, DEC-055).

They run against the throwaway Neo4j of the F10 harness (DEC-008). Every write commits in its own
transaction and every assertion reads back in a fresh session, so the tests check what was really
stored. All values are synthetic: no patient data.
"""

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.audit_neo4j.audit_log import (
    AuditHeadMissing,
    Neo4jAuditLog,
    ensure_audit_head,
)
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import GENESIS_HASH, AuditEntry
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 25, 9, 30, tzinfo=UTC)


def entry_at(minute: int, snapshot: dict[str, object] | None = None) -> AuditEntry:
    return AuditEntry(
        action="report-capacity",
        use_case="ReportCapacity",
        actor=Actor(
            role=Role.REPORTER,
            practitioner_id=None,
            device_id="dev-sms-1",
            channel="text",
            service_ids=frozenset({"svc-ucr-west"}),
        ),
        entity_ids=("obs-1",),
        snapshot=snapshot,
        at=datetime(2026, 10, 25, 9, minute, tzinfo=UTC),
    )


async def scalar(driver: AsyncDriver, cypher: str) -> int:
    async def work(tx: AsyncManagedTransaction) -> int:
        record = await (await tx.run(cypher)).single()
        assert record is not None
        return int(record["total"])

    return await read_tx(driver, work)


@pytest_asyncio.fixture(loop_scope="session")
async def audit_head(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    """The chain head exists, as it does after startup. Runs after the graph is wiped."""
    await ensure_audit_head(neo4j_driver)


async def test_three_appends_read_back_in_order_and_each_links_to_the_last(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    entries = [entry_at(0), entry_at(1), entry_at(2)]
    for entry in entries:
        await write_tx(neo4j_driver, lambda tx, e=entry: Neo4jAuditLog(tx).append(e))

    records = await read_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).records())

    assert [record.entry for record in records] == entries
    assert records[0].previous_hash == GENESIS_HASH
    assert records[1].previous_hash == records[0].chain_hash
    assert records[2].previous_hash == records[1].chain_hash


async def test_verify_chain_is_true_then_false_after_an_entry_is_edited(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    for minute in range(3):
        await write_tx(neo4j_driver, lambda tx, m=minute: Neo4jAuditLog(tx).append(entry_at(m)))
    assert await read_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).verify_chain()) is True

    async def edit(tx: AsyncManagedTransaction) -> None:
        result = await tx.run(
            "MATCH (e:AuditEvent {seq: 2}) "
            "SET e.entryJson = replace(e.entryJson, 'svc-ucr-west', 'svc-other')"
        )
        await result.consume()

    await write_tx(neo4j_driver, edit)

    assert await read_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).verify_chain()) is False


async def test_an_append_that_is_rolled_back_leaves_no_event_and_does_not_move_the_head(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async with neo4j_driver.session() as session:
        tx = await session.begin_transaction()
        try:
            await Neo4jAuditLog(tx).append(entry_at(0))
        finally:
            await tx.rollback()

    assert await count_nodes(neo4j_driver, "AuditEvent") == 0
    head = await node_props(neo4j_driver, "AuditHead", id="audit")
    assert head["lastHash"] == GENESIS_HASH


async def test_a_snapshot_is_stored_with_the_sha256_of_its_canonical_json(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    snapshot: dict[str, object] = {"service_ids": ["svc-ucr-west"], "status": "accepting"}
    await write_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).append(entry_at(0, snapshot)))

    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected_hash = hashlib.sha256(canonical.encode()).hexdigest()
    stored = await node_props(neo4j_driver, "Snapshot", hash=expected_hash)
    assert stored["json"] == canonical
    linked = await scalar(
        neo4j_driver, "MATCH (:AuditEvent)-[r:SNAPSHOT]->(:Snapshot) RETURN count(r) AS total"
    )
    assert linked == 1


async def test_two_concurrent_appends_both_succeed_and_the_chain_verifies(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    await asyncio.gather(
        write_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).append(entry_at(0))),
        write_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).append(entry_at(1))),
    )

    records = await read_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).records())
    assert len(records) == 2
    assert records[1].previous_hash == records[0].chain_hash
    assert await read_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).verify_chain()) is True


async def test_a_call_back_provenance_stores_number_called_and_role_spoken_to(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    await write_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).append(entry_at(0)))

    async def record_call_back(tx: AsyncManagedTransaction) -> str:
        log = Neo4jAuditLog(tx, clock=FixedClock(NOW))
        return await log.append_provenance(
            target_type="Booking",
            target_id="bk-1",
            activity="call-back",
            agent_id="prac-1",
            agent_role=Role.ADVISOR,
            source_communication_id="comm-1",
            extra={"numberCalled": "switchboard-ref-1", "roleSpokenTo": "receptionist"},
        )

    prov_id = await write_tx(neo4j_driver, record_call_back)

    stored = await node_props(neo4j_driver, "Provenance", id=prov_id)
    assert stored["activity"] == "call-back"
    assert stored["numberCalled"] == "switchboard-ref-1"
    assert stored["roleSpokenTo"] == "receptionist"
    assert await read_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).verify_chain()) is True


async def test_an_edited_provenance_property_is_detected(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async def record(tx: AsyncManagedTransaction) -> str:
        return await Neo4jAuditLog(tx, clock=FixedClock(NOW)).append_provenance(
            target_type="Booking",
            target_id="bk-1",
            activity="call-back",
            agent_id="prac-1",
            agent_role=Role.ADVISOR,
            extra={"numberCalled": "switchboard-ref-1"},
        )

    prov_id = await write_tx(neo4j_driver, record)

    async def edit(tx: AsyncManagedTransaction) -> None:
        result = await tx.run(
            "MATCH (p:Provenance {id: $id}) SET p.numberCalled = 'switchboard-ref-2'",
            id=prov_id,
        )
        await result.consume()

    await write_tx(neo4j_driver, edit)

    assert await read_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).verify_chain()) is False


async def test_provenance_links_its_target_agent_and_source(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async def record(tx: AsyncManagedTransaction) -> str:
        return await Neo4jAuditLog(tx, clock=FixedClock(NOW)).append_provenance(
            target_type="Booking",
            target_id="bk-1",
            activity="confirm",
            agent_id="prac-1",
            agent_role=Role.ADVISOR,
            source_communication_id="comm-1",
        )

    await write_tx(neo4j_driver, record)

    assert (
        await scalar(
            neo4j_driver,
            "MATCH (:Provenance)-[r:AGENT {role: 'advisor'}]->(:AuditRef {id: 'prac-1'}) "
            "RETURN count(r) AS total",
        )
        == 1
    )
    assert (
        await scalar(
            neo4j_driver,
            "MATCH (:Provenance)-[:TARGET]->(:AuditRef {id: 'bk-1'}) RETURN count(*) AS total",
        )
        == 1
    )
    assert (
        await scalar(
            neo4j_driver,
            "MATCH (:Provenance)-[:ENTITY {role: 'source'}]->(:AuditRef {id: 'comm-1'}) "
            "RETURN count(*) AS total",
        )
        == 1
    )
    assert (
        await scalar(
            neo4j_driver,
            "MATCH (:Provenance)-[:ACTIVITY]->(c:Concept {code: 'confirm'}) "
            "RETURN count(c) AS total",
        )
        == 1
    )


async def test_an_agent_is_linked_on_the_audit_event(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    practitioner = Actor(
        role=Role.ADVISOR,
        practitioner_id="prac-1",
        device_id=None,
        channel="advisor-app",
        service_ids=frozenset(),
    )
    entry = replace(entry_at(0), actor=practitioner)
    await write_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).append(entry))

    assert (
        await scalar(
            neo4j_driver,
            "MATCH (:AuditEvent)-[r:AGENT {role: 'advisor', requestor: true}]->"
            "(:AuditRef {id: 'prac-1'}) RETURN count(r) AS total",
        )
        == 1
    )


async def test_a_provenance_extra_that_reuses_a_reserved_name_is_refused(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async def record(tx: AsyncManagedTransaction) -> str:
        return await Neo4jAuditLog(tx, clock=FixedClock(NOW)).append_provenance(
            target_type="Booking",
            target_id="bk-1",
            activity="confirm",
            agent_id="prac-1",
            agent_role=Role.ADVISOR,
            extra={"chainHash": "not-the-chain"},
        )

    with pytest.raises(ValidationFailed, match="chainHash"):
        await write_tx(neo4j_driver, record)


async def test_an_unknown_provenance_activity_is_refused(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async def record(tx: AsyncManagedTransaction) -> str:
        return await Neo4jAuditLog(tx, clock=FixedClock(NOW)).append_provenance(
            target_type="Booking",
            target_id="bk-1",
            activity="delete",
            agent_id="prac-1",
            agent_role=Role.ADVISOR,
        )

    with pytest.raises(ValidationFailed, match="activity"):
        await write_tx(neo4j_driver, record)


async def test_appending_without_a_chain_head_is_refused_not_repaired(
    neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    with pytest.raises(AuditHeadMissing):
        await write_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).append(entry_at(0)))
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0


async def test_an_untampered_chain_with_snapshot_entities_and_provenance_verifies(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    snapshot: dict[str, object] = {"service_ids": ["svc-ucr-west"], "status": "accepting"}
    entry = replace(entry_at(0, snapshot), entity_ids=("obs-1", "obs-2"))
    await write_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).append(entry))

    async def record(tx: AsyncManagedTransaction) -> str:
        return await Neo4jAuditLog(tx, clock=FixedClock(NOW)).append_provenance(
            target_type="Booking",
            target_id="bk-1",
            activity="call-back",
            agent_id="prac-1",
            agent_role=Role.ADVISOR,
            source_communication_id="comm-1",
            extra={"numberCalled": "switchboard-ref-1"},
        )

    await write_tx(neo4j_driver, record)

    assert await _verifies(neo4j_driver) is True


async def test_an_honest_append_with_a_repeated_entity_id_verifies(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    entry = replace(entry_at(0), entity_ids=("obs-1", "obs-1"))
    await write_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).append(entry))

    assert await _verifies(neo4j_driver) is True


async def test_a_retyped_activity_concept_system_is_detected(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async def record(tx: AsyncManagedTransaction) -> str:
        return await Neo4jAuditLog(tx, clock=FixedClock(NOW)).append_provenance(
            target_type="Booking",
            target_id="bk-1",
            activity="confirm",
            agent_id="prac-1",
            agent_role=Role.ADVISOR,
        )

    await write_tx(neo4j_driver, record)
    assert await _verifies(neo4j_driver) is True

    await _run_tamper(
        neo4j_driver,
        "MATCH (:Provenance)-[:ACTIVITY]->(c:Concept {code: 'confirm'}) "
        "SET c.system = 'https://diucs.example/CodeSystem/other'",
    )

    assert await _verifies(neo4j_driver) is False


async def _run_tamper(driver: AsyncDriver, cypher: str, **params: object) -> None:
    async def edit(tx: AsyncManagedTransaction) -> None:
        result = await tx.run(cypher, **params)
        await result.consume()

    await write_tx(driver, edit)


async def _verifies(driver: AsyncDriver) -> bool:
    return await read_tx(driver, lambda tx: Neo4jAuditLog(tx).verify_chain())


async def test_an_edited_audit_event_recorded_time_is_detected(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    await write_tx(neo4j_driver, lambda tx: Neo4jAuditLog(tx).append(entry_at(0)))
    assert await _verifies(neo4j_driver) is True

    await _run_tamper(
        neo4j_driver,
        "MATCH (e:AuditEvent {seq: 1}) SET e.recorded = datetime('2026-10-25T10:00:00Z')",
    )

    assert await _verifies(neo4j_driver) is False


async def test_an_edited_provenance_recorded_time_is_detected(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async def record(tx: AsyncManagedTransaction) -> str:
        return await Neo4jAuditLog(tx, clock=FixedClock(NOW)).append_provenance(
            target_type="Booking",
            target_id="bk-1",
            activity="confirm",
            agent_id="prac-1",
            agent_role=Role.ADVISOR,
        )

    prov_id = await write_tx(neo4j_driver, record)
    assert await _verifies(neo4j_driver) is True

    await _run_tamper(
        neo4j_driver,
        "MATCH (p:Provenance {id: $id}) SET p.recorded = datetime('2026-10-25T10:00:00Z')",
        id=prov_id,
    )

    assert await _verifies(neo4j_driver) is False


async def test_a_retargeted_provenance_target_is_detected(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    async def record(tx: AsyncManagedTransaction) -> str:
        return await Neo4jAuditLog(tx, clock=FixedClock(NOW)).append_provenance(
            target_type="Booking",
            target_id="bk-1",
            activity="confirm",
            agent_id="prac-1",
            agent_role=Role.ADVISOR,
        )

    prov_id = await write_tx(neo4j_driver, record)
    assert await _verifies(neo4j_driver) is True

    await _run_tamper(
        neo4j_driver,
        "MATCH (:Provenance {id: $id})-[:TARGET]->(t:AuditRef) SET t.id = 'bk-9'",
        id=prov_id,
    )

    assert await _verifies(neo4j_driver) is False


async def test_an_edited_audit_agent_edge_is_detected(
    neo4j_driver: AsyncDriver, audit_head: None
) -> None:
    practitioner = Actor(
        role=Role.ADVISOR,
        practitioner_id="prac-1",
        device_id=None,
        channel="advisor-app",
        service_ids=frozenset(),
    )
    await write_tx(
        neo4j_driver,
        lambda tx: Neo4jAuditLog(tx).append(replace(entry_at(0), actor=practitioner)),
    )
    assert await _verifies(neo4j_driver) is True

    await _run_tamper(
        neo4j_driver,
        "MATCH (:AuditEvent)-[r:AGENT]->(:AuditRef {id: 'prac-1'}) SET r.role = 'lead'",
    )

    assert await _verifies(neo4j_driver) is False
