"""The outbox statement that creates a message carries the tenant, and the properties it is given
cannot replace it (TEN-004, DEC-150 item 11). `Q-OUTBOX-ADD` is `CREATE (m {tenantId: $tenant}) SET
m += $props`: a `tenantId` in `props` would overwrite the stamp, so `Neo4jOutbox.add` must never
write one, whatever the payload holds.
"""

from datetime import UTC, datetime
from typing import Any

from diucs.adapters.outbound.audit_neo4j.outbox import Neo4jOutbox
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.tenancy import bind_tenant


class _Result:
    async def data(self) -> list[dict[str, Any]]:
        return [{"written": 1}]


class _Tx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(
        self, cypher: str, parameters: dict[str, Any] | None = None, **kw: Any
    ) -> _Result:
        self.calls.append((cypher, dict(parameters or {})))
        return _Result()


async def test_a_payload_field_named_tenant_id_is_stored_under_its_own_prefix() -> None:
    tx = _Tx()
    message = OutboxMessage(
        id="m-1",
        topic="topic",
        event_type="capacity.reported",
        payload={"tenantId": "someone-else", "tenant": "x", "seedMarker": "y"},
        created_at=datetime(2026, 10, 25, 9, 0, tzinfo=UTC),
        status="pending",
        attempts=0,
        session_id=None,
    )
    with bind_tenant("tt-unit-0001"):
        await Neo4jOutbox(tx).add(message)  # type: ignore[arg-type]
    ((cypher, parameters),) = tx.calls
    assert "tenantId: $tenant" in cypher
    assert parameters["tenant"] == "tt-unit-0001"
    props = parameters["props"]
    assert "tenantId" not in props
    assert props["payload_tenantId"] == "someone-else"
    assert set(props) >= {"id", "topic", "eventType", "status", "attempts", "createdAt"}
