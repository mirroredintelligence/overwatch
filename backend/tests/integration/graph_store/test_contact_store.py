"""Integration tests for the protected contact store (P16, DEC-004, DEC-070).

They run against the throwaway Neo4j the F10 harness starts for the session. Each save commits in
one transaction and each load runs in a fresh session. The phone number used here is a synthetic
sample; no patient data is used.
"""

import asyncio
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ConstraintError
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.contact_store import Neo4jContactStore
from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.application.tenancy import current_tenant
from diucs.domain.errors import Conflict, ValidationFailed
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.scoped import scoped

pytestmark = pytest.mark.asyncio(loop_scope="session")

ROLE = "r-west-duty"
OTHER_ROLE = "r-east-duty"
PHONE = "07700 900123"
NEW_PHONE = "07700 900456"
EMAIL = "duty.west@nhs.example"


async def _put_phone(driver: AsyncDriver, role_id: str, number: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jContactStore(tx).put_phone(role_id, number)

    await write_tx(driver, work)


async def _get_phone(driver: AsyncDriver, role_id: str) -> str | None:
    async def work(tx: AsyncManagedTransaction) -> str | None:
        return await Neo4jContactStore(tx).get_phone(role_id)

    return await read_tx(driver, work)


async def _nodes_holding(driver: AsyncDriver, text: str) -> list[list[str]]:
    """The labels of every node that holds `text` in one of its properties (a string, or a list
    of strings). Scans every node, so a copy anywhere in the graph is found."""
    query = "MATCH (n) RETURN labels(n) AS labels, properties(n) AS props"

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(query)).data()

    rows = await read_tx(driver, work)
    holding: list[list[str]] = []
    for row in rows:
        for value in row["props"].values():
            values = value if isinstance(value, list) else [value]
            if any(isinstance(item, str) and text in item for item in values):
                holding.append(list(row["labels"]))
                break
    return holding


async def test_put_phone_then_get_phone_in_a_fresh_unit_of_work_returns_the_number(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put_phone(neo4j_driver, ROLE, PHONE)

    assert await _get_phone(neo4j_driver, ROLE) == PHONE


async def test_the_number_is_held_only_by_the_protected_contact_node(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put_phone(neo4j_driver, ROLE, PHONE)

    assert await _nodes_holding(neo4j_driver, "07700900123") == []
    assert await _nodes_holding(neo4j_driver, "900123") == [["ProtectedContact"]]
    assert await count_nodes(neo4j_driver, "Resource") == 0


async def test_the_protected_contact_node_has_the_documented_properties(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put_phone(neo4j_driver, ROLE, PHONE)

    props = await node_props(neo4j_driver, "ProtectedContact", roleId=ROLE, kind="phone")

    assert props["value"] == PHONE
    assert isinstance(props["updatedAt"], DateTime)


async def test_a_second_put_phone_replaces_the_number_and_keeps_one_node(
    neo4j_driver: AsyncDriver,
) -> None:
    await _put_phone(neo4j_driver, ROLE, PHONE)
    await _put_phone(neo4j_driver, ROLE, NEW_PHONE)

    assert await _get_phone(neo4j_driver, ROLE) == NEW_PHONE
    assert await count_nodes(neo4j_driver, "ProtectedContact") == 1


async def test_an_email_and_a_phone_for_one_role_are_kept_apart(
    neo4j_driver: AsyncDriver,
) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        store = Neo4jContactStore(tx)
        await store.put_phone(ROLE, PHONE)
        await store.put_email(ROLE, EMAIL)

    await write_tx(neo4j_driver, work)

    async def read(tx: AsyncManagedTransaction) -> tuple[str | None, str | None]:
        store = Neo4jContactStore(tx)
        return await store.get_phone(ROLE), await store.get_email(ROLE)

    assert await read_tx(neo4j_driver, read) == (PHONE, EMAIL)
    assert await count_nodes(neo4j_driver, "ProtectedContact") == 2


async def test_a_role_with_no_contact_gives_none(neo4j_driver: AsyncDriver) -> None:
    await _put_phone(neo4j_driver, ROLE, PHONE)

    assert await _get_phone(neo4j_driver, OTHER_ROLE) is None


async def test_a_blank_phone_is_refused_and_writes_nothing(neo4j_driver: AsyncDriver) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jContactStore(tx).put_phone(ROLE, "   ")

    with pytest.raises(ValidationFailed) as refused:
        await write_tx(neo4j_driver, work)

    assert "   " not in str(refused.value)
    assert await count_nodes(neo4j_driver, "ProtectedContact") == 0


async def test_an_email_without_an_at_sign_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver,
) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jContactStore(tx).put_email(ROLE, "duty.west.nhs.example")

    with pytest.raises(ValidationFailed):
        await write_tx(neo4j_driver, work)

    assert await count_nodes(neo4j_driver, "ProtectedContact") == 0


async def test_a_racing_first_put_is_refused_while_the_first_write_is_uncommitted(
    neo4j_driver: AsyncDriver,
) -> None:
    """Deterministic interleaving, not a race run (lesson L92). The first write is held
    uncommitted. The second write runs while the first is open. Without the unique key it finishes
    at once and creates a second node, so the commit leaves two. With the key it waits for the
    first commit, then either updates that node (stored) or is refused (conflict). Either is
    correct; what is asserted is one node. The schema is applied first, so the result does not
    depend on other tests."""
    await apply_migrations(neo4j_driver)
    first_session = neo4j_driver.session()
    second_session = neo4j_driver.session()
    try:
        first_tx = scoped(await first_session.begin_transaction())
        await Neo4jContactStore(first_tx).put_phone(ROLE, PHONE)
        second_tx = scoped(await second_session.begin_transaction())
        racing = asyncio.create_task(Neo4jContactStore(second_tx).put_phone(ROLE, NEW_PHONE))
        await asyncio.wait({racing}, timeout=1.0)
        await first_tx.commit()
        outcome = "stored"
        try:
            await racing
        except Conflict:
            outcome = "conflict"
        if outcome == "stored":
            await second_tx.commit()
        else:
            await second_tx.rollback()
    finally:
        await first_session.close()
        await second_session.close()

    assert outcome in {"stored", "conflict"}
    assert await count_nodes(neo4j_driver, "ProtectedContact") == 1
    assert await _get_phone(neo4j_driver, ROLE) == (NEW_PHONE if outcome == "stored" else PHONE)


async def test_a_second_protected_contact_for_one_role_and_kind_is_refused_by_the_schema(
    neo4j_driver: AsyncDriver,
) -> None:
    """Deterministic: a second raw CREATE with the same key in the same tenant raises
    ConstraintError (lesson L92). The key is composite since TEN-032: a node with no tenant is
    not covered (Neo4j Community ignores a null), which the invariant check finds instead."""
    await apply_migrations(neo4j_driver)

    async def create(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "CREATE (:ProtectedContact {key: 'r-west-duty|phone', value: 'x', tenantId: $tenant})",
            tenant=current_tenant(),
        )

    await write_tx(neo4j_driver, create)
    with pytest.raises(ConstraintError):
        await write_tx(neo4j_driver, create)
    assert await count_nodes(neo4j_driver, "ProtectedContact") == 1
