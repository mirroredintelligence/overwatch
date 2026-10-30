"""The statements that stamp and read a device's last text-code verification (U32): registered,
tenant-scoped on every node, given a scenario for the generated two-tenant test, and never given a
token, a PIN or a hash."""

import re

from diucs.adapters.outbound.graph_store import credential_store  # registers the queries
from diucs.adapters.outbound.graph_store.queries import REGISTRY

MARK = "Q-DEVICE-MARK-VERIFIED"
READ = "Q-DEVICE-VERIFIED"


def test_the_statements_are_registered_with_the_right_modes_and_scenarios() -> None:
    assert credential_store is not None
    assert REGISTRY.get(MARK).mode == "write"
    assert REGISTRY.get(READ).mode == "read"
    for query_id in (MARK, READ):
        assert REGISTRY.get(query_id).scenario is not None


def test_every_node_they_match_names_the_tenant() -> None:
    for query_id in (MARK, READ):
        cypher = REGISTRY.get(query_id).cypher
        nodes = re.findall(r"\(\w*:\w+[^)]*\)", cypher)
        assert len(nodes) == 2, cypher
        assert all("tenantId: $tenant" in node for node in nodes), cypher


def test_a_revoked_device_is_never_stamped_or_read() -> None:
    for query_id in (MARK, READ):
        assert "revokedAt IS NULL" in REGISTRY.get(query_id).cypher


def test_the_stamp_is_the_only_property_written_and_no_secret_is_a_parameter() -> None:
    cypher = REGISTRY.get(MARK).cypher
    assert cypher.count("SET") == 1
    assert "lastVerifiedAt" in cypher
    for query_id in (MARK, READ):
        assert not re.search(r"\$(pin|hash|token)", REGISTRY.get(query_id).cypher, re.IGNORECASE)
