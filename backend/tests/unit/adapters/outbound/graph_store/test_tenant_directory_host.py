"""The host of a tenant, read from its registry node (TEN-027, DEC-500).

`host_of` reuses the registered `Q-TENANT-GET` statement: no new global statement. It answers the
host in its lookup form or None, and a key that is not a tenant id sends nothing.
"""

from typing import Any, cast

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.tenant_directory import (
    Neo4jTenantDirectory,
    tenant_properties,
)
from tests.support.directory_connection import RecordingConnection
from tests.support.tenant_samples import make_tenant


def _directory(connection: RecordingConnection) -> Neo4jTenantDirectory:
    return Neo4jTenantDirectory(cast(Neo4jConnection, connection))


def _row(**extra: Any) -> dict[str, Any]:
    return {"tenant": {**tenant_properties(make_tenant()), **extra}}


async def test_the_host_is_the_property_of_the_tenants_node() -> None:
    connection = RecordingConnection({"Q-TENANT-GET": [_row(host="acme.example.org")]})
    assert await _directory(connection).host_of("example-icb") == "acme.example.org"
    assert connection.ids_called() == ["Q-TENANT-GET"]


async def test_a_tenant_with_no_host_has_none() -> None:
    connection = RecordingConnection({"Q-TENANT-GET": [_row()]})
    assert await _directory(connection).host_of("example-icb") is None


async def test_an_unknown_tenant_has_none() -> None:
    assert await _directory(RecordingConnection({})).host_of("example-icb") is None


async def test_a_key_that_is_not_a_tenant_id_sends_nothing() -> None:
    connection = RecordingConnection({})
    for bad in ("", "platform", "net-west", "A", "a/b", "x" * 40):
        assert await _directory(connection).host_of(bad) is None
    assert connection.calls == []


async def test_a_host_that_is_not_a_host_name_is_none() -> None:
    connection = RecordingConnection({"Q-TENANT-GET": [_row(host="not a host")]})
    assert await _directory(connection).host_of("example-icb") is None
