"""Unit test for the connection guard: no Docker needed, nothing listens on port 1."""

import pytest

from tests.support.neo4j import START_MESSAGE, Neo4jNotRunning, connect_or_fail


async def test_connect_or_fail_raises_the_exact_start_message_when_nothing_listens() -> None:
    with pytest.raises(Neo4jNotRunning) as excinfo:
        await connect_or_fail("bolt://localhost:1", "neo4j", "unused", timeout_s=1)

    assert str(excinfo.value) == START_MESSAGE
    assert START_MESSAGE == (
        "Neo4j is not running. Start it with: docker compose -f infra/docker-compose.yml up -d neo4j"
    )
