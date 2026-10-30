"""The replay-record statements and the outbox's lock, publish and fail statements carry the tenant
(TEN-016, DEC-130 item 6, DEC-142 item 5, DEC-150). Pure: no Neo4j. The generated two-tenant test
(tests/integration/graph_store/test_tenant_isolation.py) runs each scenario on a real database; here
we pin the shape of the statements and of their scenarios, and that an unbound call is refused
before any Cypher is sent.
"""

import re
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from diucs.adapters.outbound.audit_neo4j.outbox import Neo4jOutbox
from diucs.adapters.outbound.graph_store.idempotency_store import Neo4jIdempotencyStore
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.application.actor import Actor
from diucs.application.tenancy import RawTransactionRefused
from diucs.domain.codes import Role
from tests.support.actors import ACTOR_TENANT
from tests.support.scoped import scoped_stub

# The statements that TEN-016 converts. Each carries `tenantId: $tenant` and a scenario.
CONVERTED_BY_TEN_016: tuple[str, ...] = (
    "Q-IDEM-CREATE",
    "Q-IDEM-EDGES",
    "Q-IDEM-HEAD",
    "Q-IDEM-LINK",
    "Q-IDEM-VALUES",
    "Q-OUTBOX-FAILED",
    "Q-OUTBOX-LOCK",
    "Q-OUTBOX-PUBLISHED",
)

# A labelled node pattern such as `(m:OutboxMessage {id: $id})`, with one level of nested braces
# allowed (`datetime({timezone: 'UTC'})` inside a property map).
_LABELLED_NODE = re.compile(r"\(\s*\w*\s*((?::\s*\w+)+)\s*(\{(?:[^{}]|\{[^{}]*\})*\})?\s*\)")
_STAMP = "tenantId: $tenant"
_AT = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
# A command result the replay codec accepts (a dataclass of diucs.application).
_RESULT = Actor(
    role=Role.REPORTER,
    practitioner_id=None,
    device_id="dev-sms-1",
    channel="text",
    service_ids=frozenset({"svc-ucr-west"}),
    tenant_id=ACTOR_TENANT,
)


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def data(self) -> list[dict[str, Any]]:
        return self._rows


class _RecordingTx:
    """A raw transaction double: records every statement and its parameters."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._rows = rows or []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None, **kw: Any) -> _Rows:
        self.calls.append((cypher, dict(parameters or {})))
        return _Rows(self._rows)


@pytest.mark.parametrize("query_id", CONVERTED_BY_TEN_016)
def test_the_statement_carries_a_scenario(query_id: str) -> None:
    query = REGISTRY.get(query_id)
    assert _STAMP in query.cypher
    assert query.scenario is not None


@pytest.mark.parametrize("query_id", CONVERTED_BY_TEN_016)
def test_the_scenario_is_usable(query_id: str) -> None:
    scenario = REGISTRY.get(query_id).scenario
    assert scenario is not None
    assert validate_scenario(query_id, scenario) == []


@pytest.mark.parametrize("query_id", CONVERTED_BY_TEN_016)
def test_every_labelled_node_the_statement_names_carries_the_tenant(query_id: str) -> None:
    cypher = REGISTRY.get(query_id).cypher
    patterns = _LABELLED_NODE.findall(cypher)
    assert patterns, f"{query_id} names no labelled node"
    for labels, props in patterns:
        assert _STAMP in props, f"{query_id}: {labels} is matched or created without the tenant"


def test_the_replay_record_is_stamped_on_the_record_and_on_every_value() -> None:
    create = REGISTRY.get("Q-IDEM-CREATE").cypher
    assert "(r:IdempotencyRecord {key: $key, resultType: $resultType, createdAt:" in create
    assert "CREATE (v:IdempotencyValue {seq: row.seq" in create
    assert "tenantId: $tenant" in create
    link = REGISTRY.get("Q-IDEM-LINK").cypher
    assert "(p:IdempotencyValue {seq: e.parent, tenantId: $tenant})" in link
    assert "(c:IdempotencyValue {seq: e.child, tenantId: $tenant})" in link


async def test_reading_a_replay_record_on_a_raw_transaction_is_refused_before_cypher() -> None:
    tx = _RecordingTx()
    store = Neo4jIdempotencyStore(cast(Any, tx))
    with pytest.raises(RawTransactionRefused):
        await store.get("pairing:key-1")
    assert tx.calls == []


async def test_storing_a_replay_record_on_a_raw_transaction_is_refused_before_cypher() -> None:
    tx = _RecordingTx()
    store = Neo4jIdempotencyStore(cast(Any, tx))
    with pytest.raises(RawTransactionRefused):
        await store.put("pairing:key-1", _RESULT)
    assert tx.calls == []


async def test_the_replay_read_is_stamped_with_the_bound_tenant() -> None:
    tx = _RecordingTx()
    assert await Neo4jIdempotencyStore(scoped_stub(tx, "tt-unit-0001")).get("pairing:key-1") is None
    assert tx.calls
    for cypher, parameters in tx.calls:
        assert _STAMP in cypher
        assert parameters["tenant"] == "tt-unit-0001"


async def test_marking_an_outbox_message_published_on_a_raw_transaction_is_refused() -> None:
    tx = _RecordingTx()
    with pytest.raises(RawTransactionRefused):
        await Neo4jOutbox(cast(Any, tx)).mark_published("m-1", _AT)
    assert tx.calls == []


async def test_failing_an_outbox_message_on_a_raw_transaction_is_refused() -> None:
    tx = _RecordingTx()
    with pytest.raises(RawTransactionRefused):
        await Neo4jOutbox(cast(Any, tx)).mark_failed("m-1", "boom")
    assert tx.calls == []


async def test_publishing_an_outbox_message_is_stamped_with_the_bound_tenant() -> None:
    tx = _RecordingTx(rows=[{"status": "pending"}])
    await Neo4jOutbox(scoped_stub(tx, "tt-unit-0001")).mark_published("m-1", _AT)
    assert len(tx.calls) == 2
    for cypher, parameters in tx.calls:
        assert _STAMP in cypher
        assert parameters["tenant"] == "tt-unit-0001"


async def test_failing_an_outbox_message_is_stamped_with_the_bound_tenant() -> None:
    tx = _RecordingTx(rows=[{"attempts": 1, "status": "pending"}])
    await Neo4jOutbox(scoped_stub(tx, "tt-unit-0001")).mark_failed("m-1", "boom")
    assert len(tx.calls) == 1
    cypher, parameters = tx.calls[0]
    assert _STAMP in cypher
    assert parameters["tenant"] == "tt-unit-0001"
