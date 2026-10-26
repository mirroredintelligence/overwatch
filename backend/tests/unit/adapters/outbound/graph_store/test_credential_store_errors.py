"""Credential store refusals that a real database rarely reaches (P16, DEC-074).

Two guards are checked with the query call replaced: a read that finds two credentials for one
device must fail closed (a duplicate would defeat the PIN lockout), and a constraint error on a
credential write must be a Conflict. Both are backstops behind the unique deviceId constraint, so
the tests force the query result rather than racing for it.
"""

from typing import Any

import pytest
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store import credential_store
from diucs.domain.errors import Conflict


async def test_a_read_that_finds_two_credentials_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {"pinHash": "c" * 64, "failed": 0, "locked": False, "lastOutcome": None}

    async def two_rows(tx: Any, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return [row, dict(row, pinHash="d" * 64)]

    monkeypatch.setattr(credential_store, "run_query", two_rows)

    with pytest.raises(Conflict):
        await credential_store.Neo4jPinStore(object()).get("p1", "dev-1")  # type: ignore[arg-type]


async def test_a_constraint_error_on_set_pin_is_a_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def practitioner_then_refuse(
        tx: Any, query_id: str, **params: Any
    ) -> list[dict[str, Any]]:
        if query_id == "Q-CRED-PRACTITIONER-EXISTS":
            return [{"n": 1}]
        raise ConstraintError("unique deviceId already exists")

    monkeypatch.setattr(credential_store, "run_query", practitioner_then_refuse)

    with pytest.raises(Conflict):
        await credential_store.Neo4jPinStore(object()).set_pin(  # type: ignore[arg-type]
            "p1", "dev-1", "c" * 64
        )
