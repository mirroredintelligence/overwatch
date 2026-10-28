"""The contact store refuses a racing first write that the unique key rejects (P16, DEC-073 item 1).

Neo4j's MERGE serialises real racers, so the constraint error is a backstop that the integration
race test does not reach. This test forces the error from the query call, and checks that the store
maps it to Conflict and does not let the driver's error out.
"""

from typing import Any

import pytest
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store import contact_store
from diucs.adapters.outbound.graph_store.queries import NamedQuery
from diucs.domain.errors import Conflict


async def test_a_constraint_error_on_put_is_a_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(tx: Any, query: NamedQuery, **params: Any) -> list[dict[str, Any]]:
        raise ConstraintError("unique key already exists")

    monkeypatch.setattr(contact_store, "run_query", refuse)

    with pytest.raises(Conflict):
        await contact_store.Neo4jContactStore(object()).put_phone("r-west-duty", "07700 900123")  # type: ignore[arg-type]
