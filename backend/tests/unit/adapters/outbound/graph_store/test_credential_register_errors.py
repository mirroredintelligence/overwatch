"""A racing device registration that the unique Device.id constraint refuses is a Conflict
(P16, DEC-071 item 4). The race itself is not reproduced here: the test forces the constraint error
from the query call, because a real second practitioner's write would take the same path."""

from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store import credential_store
from diucs.adapters.outbound.graph_store.queries import NamedQuery
from diucs.domain.errors import Conflict

AT = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)


async def test_a_constraint_error_on_register_is_a_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def another_owner_then_refuse(
        tx: Any, query: NamedQuery, **params: Any
    ) -> list[dict[str, Any]]:
        if query.id == "Q-DEVICE-LOCK":
            return [{"n": 1}]
        if query.id == "Q-DEVICE-OWNER":
            return []
        raise ConstraintError("Device.id already exists")

    monkeypatch.setattr(credential_store, "run_query", another_owner_then_refuse)

    with pytest.raises(Conflict):
        await credential_store.Neo4jDeviceRegistry(object()).register(  # type: ignore[arg-type]
            "p2", "dev-1", AT
        )
