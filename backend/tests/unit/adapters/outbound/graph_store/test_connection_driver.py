"""The driver the start-up steps take (TEN-007): available while the connection is open, and a
clear refusal before it opens and after it closes. No server is contacted."""

import pytest

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection, Neo4jConnectionError


def test_the_driver_is_refused_before_the_connection_is_opened() -> None:
    connection = Neo4jConnection("bolt://localhost:1", "neo4j", "unused-without-a-session")
    with pytest.raises(Neo4jConnectionError, match="not open"):
        _ = connection.driver


async def test_the_driver_is_refused_after_the_connection_is_closed() -> None:
    connection = Neo4jConnection("bolt://localhost:1", "neo4j", "unused-without-a-session")
    await connection.close()
    with pytest.raises(Neo4jConnectionError, match="closed"):
        _ = connection.driver
