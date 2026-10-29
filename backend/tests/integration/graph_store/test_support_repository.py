"""Neo4j round trips of the support records (O06, docs/spec/fhir-data-model.md "Platform nodes"),
read back in a fresh session, and the two-tenant isolation of a code. Synthetic values only. Written
in the build wave and run in the verification stage (one Neo4j at a time)."""

from datetime import UTC, datetime, timedelta

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.support_repository import Neo4jSupportRepository
from diucs.application.ports.outbound.support import SupportAccessRecord, SupportCodeRecord
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.round_trip import assert_round_trip

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
CODE_HASH = "c" * 64


async def _seed_practitioner(driver: AsyncDriver, tenant: str, practitioner: str) -> None:
    async def work(tx: object) -> None:
        await tx.run(  # type: ignore[attr-defined]
            "CREATE (:Practitioner {id: $id, tenantId: $t, active: true, displayName: 'Sample'})",
            id=practitioner,
            t=tenant,
        )

    await write_tx(driver, work)


async def test_a_ui_session_round_trips_without_any_person_link(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    async def save(tx: object) -> None:
        await Neo4jSupportRepository(tx).ensure_session(  # type: ignore[arg-type]
            "ui-1", "phone", "browser", "2026.10.29", NOW
        )

    async def load(tx: object) -> bool:
        return await Neo4jSupportRepository(tx).session_exists("ui-1")  # type: ignore[arg-type]

    await assert_round_trip(neo4j_driver, save, load, True)
    props = await node_props(neo4j_driver, "UiSession", id="ui-1")
    assert props["deviceType"] == "phone"
    assert "tenantId" in props


async def test_a_support_code_round_trips_with_only_its_hash(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed_practitioner(neo4j_driver, tenant_id, "p-reporter")
    record = SupportCodeRecord(
        code_hash=CODE_HASH,
        session_id="ui-1",
        practitioner_id="p-reporter",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=4),
    )

    async def save(tx: object) -> None:
        await write_tx_session_ensure(tx)
        assert await Neo4jSupportRepository(tx).add_code(record) is True  # type: ignore[arg-type]

    async def load(tx: object) -> SupportCodeRecord | None:
        return await Neo4jSupportRepository(tx).code_by_hash(CODE_HASH)  # type: ignore[arg-type]

    await assert_round_trip(neo4j_driver, save, load, record)
    assert await count_nodes(neo4j_driver, "SupportCode") == 1


async def test_a_support_access_round_trips_with_its_window(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _seed_practitioner(neo4j_driver, tenant_id, "p-support")
    access = SupportAccessRecord(
        id="acc-1",
        session_id="ui-1",
        practitioner_id="p-support",
        reason="ticket INC-1001, approved by p-lead",
        opened_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    async def save(tx: object) -> None:
        await write_tx_session_ensure(tx)
        assert await Neo4jSupportRepository(tx).add_access(access) is True  # type: ignore[arg-type]

    async def load(tx: object) -> list[SupportAccessRecord]:
        return await Neo4jSupportRepository(tx).accesses_of("ui-1")  # type: ignore[arg-type]

    await assert_round_trip(neo4j_driver, save, load, [access])


async def test_a_code_of_tenant_a_is_not_found_by_tenant_b(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    await _seed_practitioner(neo4j_driver, tenant_id, "p-reporter")
    record = SupportCodeRecord(
        code_hash=CODE_HASH,
        session_id="ui-1",
        practitioner_id="p-reporter",
        created_at=NOW,
        expires_at=NOW + timedelta(hours=4),
    )
    from tests.support.tenancy import as_tenant

    async def save(tx: object) -> None:
        await write_tx_session_ensure(tx)
        await Neo4jSupportRepository(tx).add_code(record)  # type: ignore[arg-type]

    with as_tenant(tenant_id):
        await write_tx(neo4j_driver, save)
    with as_tenant(other_tenant_id):
        found = await read_tx(
            neo4j_driver,
            lambda tx: Neo4jSupportRepository(tx).code_by_hash(CODE_HASH),  # type: ignore[arg-type, return-value]
        )

    assert found is None


async def write_tx_session_ensure(tx: object) -> None:
    await Neo4jSupportRepository(tx).ensure_session(  # type: ignore[arg-type]
        "ui-1", "phone", "browser", "2026.10.29", NOW
    )
