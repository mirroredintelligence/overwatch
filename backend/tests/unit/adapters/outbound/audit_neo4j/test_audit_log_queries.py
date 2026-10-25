"""Pure tests of the audit adapter's shape (P05, DEC-054): its queries and its method set."""

from diucs.adapters.outbound.audit_neo4j.audit_log import Neo4jAuditLog
from diucs.adapters.outbound.graph_store.queries import REGISTRY

AUDIT_QUERY_IDS = {"Q-AUDIT-APPEND", "Q-AUDIT-LIST", "Q-PROV-APPEND"}


def test_the_audit_and_provenance_queries_are_registered() -> None:
    assert AUDIT_QUERY_IDS <= set(REGISTRY.ids())


def test_no_audit_or_provenance_query_deletes_anything() -> None:
    audit_ids = [i for i in REGISTRY.ids() if i.startswith(("Q-AUDIT-", "Q-PROV-"))]
    assert audit_ids
    for query_id in audit_ids:
        assert "DELETE" not in REGISTRY.get(query_id).cypher.upper(), query_id


def test_the_audit_log_has_no_update_delete_or_remove() -> None:
    for name in ("update", "delete", "remove"):
        assert not hasattr(Neo4jAuditLog, name), name
