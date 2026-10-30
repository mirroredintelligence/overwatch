"""Scope kinds and the label partition (TEN-037, DEC-132 item 4, DEC-542).

A statement declares the kinds of scope it runs in: `tenant` (the default), `network`, or both for
the statements that are scope-stamped and label-generic (the audit chain, the idempotency record,
the processed marker). The registration check is cheap and is not a proof: it refuses a tenant
statement that names a network label and a network statement that names anything but a network or
scope-generic label, so a statement cannot be made to write a projection from a tenant scope or to
read private data from a network scope. The proof is the generated test (TEN-060).
"""

import pytest

from diucs.adapters.outbound.graph_store import queries as queries_module
from diucs.adapters.outbound.graph_store import scope_labels
from diucs.adapters.outbound.graph_store.queries import (
    BOTH_KINDS,
    NETWORK_KINDS,
    REGISTRY,
    TENANT_KINDS,
    NamedQuery,
    QueryRegistry,
    QueryTemplate,
    Scenario,
    statement_labels,
)
from diucs.domain.rules import projection as allowlist
from tests.support.query_probes import production_statements

SCENARIO = Scenario("placeholder until TEN-060")


def _tenant(cypher: str, **kw: object) -> NamedQuery:
    return NamedQuery(id="Q-T", cypher=cypher, mode="read", scenario=SCENARIO, **kw)  # type: ignore[arg-type]


def _network(cypher: str) -> NamedQuery:
    return NamedQuery(
        id="Q-N", cypher=cypher, mode="read", scenario=SCENARIO, scope_kinds=NETWORK_KINDS
    )


# The kinds


def test_a_statement_runs_in_a_tenant_scope_unless_it_says_otherwise() -> None:
    query = NamedQuery(id="Q-D", cypher="RETURN 1", mode="read")
    assert query.scope_kinds == frozenset({"tenant"}) == TENANT_KINDS
    assert NETWORK_KINDS == frozenset({"network"})
    assert BOTH_KINDS == frozenset({"tenant", "network"})


@pytest.mark.parametrize(
    "kinds",
    [
        frozenset(),
        frozenset({"global"}),
        frozenset({"tenant", "x"}),
        {"tenant"},
        ["tenant"],
        "tenant",
    ],
)
def test_a_set_of_kinds_that_is_not_one_of_the_three_is_refused(kinds: object) -> None:
    with pytest.raises(ValueError, match="scope_kinds"):
        NamedQuery(id="Q-K", cypher="RETURN 1", mode="read", scope_kinds=kinds)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="scope_kinds"):
        QueryTemplate(id="Q-K", cypher="RETURN 1", mode="read", scope_kinds=kinds)  # type: ignore[arg-type]


def test_a_global_statement_has_no_kinds_of_its_own() -> None:
    with pytest.raises(ValueError, match="scope_kinds"):
        NamedQuery(
            id="Q-NEO4J-PING", cypher="RETURN 1 AS ok", mode="read", scope="global",
            scope_kinds=NETWORK_KINDS,
        )  # fmt: skip


def test_a_registered_statement_is_the_one_with_the_same_kinds() -> None:
    registry = QueryRegistry()
    registry.register(_network("MATCH (p:ProjectedService {tenantId: $tenant}) RETURN p"))
    twin = NamedQuery(
        id="Q-N",
        cypher="MATCH (p:ProjectedService {tenantId: $tenant}) RETURN p",
        mode="read",
        scenario=SCENARIO,
        scope_kinds=BOTH_KINDS,
    )
    assert registry.is_registered(registry.get("Q-N"))
    assert not registry.is_registered(twin)


# The partition


def test_the_label_sets_are_disjoint_and_the_network_set_is_the_allowlist_and_two_more() -> None:
    assert scope_labels.NETWORK_ONLY_LABELS == frozenset(allowlist.ALLOWLIST) | {
        "ProjectionSource",
        "ProjectionCursor",
    }
    assert scope_labels.SCOPE_GENERIC_LABELS == frozenset(
        {
            "AuditHead",
            "AuditEvent",
            "ChainLink",
            "AuditRef",
            "Snapshot",
            "IdempotencyRecord",
            "IdempotencyValue",
            "Processed",
        }
    )
    assert not scope_labels.NETWORK_ONLY_LABELS & scope_labels.SCOPE_GENERIC_LABELS
    assert not scope_labels.NETWORK_ONLY_LABELS & scope_labels.REGISTRY_NODE_LABELS
    assert not scope_labels.SCOPE_GENERIC_LABELS & scope_labels.REGISTRY_NODE_LABELS


@pytest.mark.parametrize(
    "label", sorted(scope_labels.NETWORK_ONLY_LABELS | scope_labels.REGISTRY_NODE_LABELS)
)
def test_a_tenant_statement_cannot_name_a_network_or_registry_label(label: str) -> None:
    registry = QueryRegistry()
    with pytest.raises(ValueError, match="network label"):
        registry.register(_tenant(f"MATCH (n:{label} {{id: $id, tenantId: $tenant}}) RETURN n"))


@pytest.mark.parametrize("label", ["HealthcareService", "Observation", "Patient", "Practitioner"])
def test_a_network_statement_cannot_name_a_tenant_data_label(label: str) -> None:
    registry = QueryRegistry()
    with pytest.raises(ValueError, match="network"):
        registry.register(_network(f"MATCH (n:{label} {{id: $id, tenantId: $tenant}}) RETURN n"))


def test_a_network_statement_may_name_a_projection_and_a_generic_label() -> None:
    registry = QueryRegistry()
    registry.register(
        NamedQuery(
            id="Q-N",
            cypher=(
                "MATCH (p:ProjectedCapacity {tenantId: $tenant, sourceTenantId: $sourceTenant}) "
                "MATCH (h:AuditHead {id: 'audit', tenantId: $tenant}) RETURN p, h"
            ),
            mode="read",
            scenario=SCENARIO,
            scope_kinds=NETWORK_KINDS,
        )
    )


def test_a_statement_for_both_kinds_may_name_only_generic_labels() -> None:
    registry = QueryRegistry()
    registry.register(
        NamedQuery(
            id="Q-B",
            cypher="MATCH (h:AuditHead {id: 'audit', tenantId: $tenant}) RETURN h.lastSeq AS s",
            mode="read",
            scenario=SCENARIO,
            scope_kinds=BOTH_KINDS,
        )
    )
    for label in ("ProjectedCapacity", "HealthcareService"):
        with pytest.raises(ValueError, match="both"):
            QueryRegistry().register(
                NamedQuery(
                    id="Q-B2",
                    cypher=f"MATCH (n:{label} {{tenantId: $tenant}}) RETURN n",
                    mode="read",
                    scenario=SCENARIO,
                    scope_kinds=BOTH_KINDS,
                )
            )


@pytest.mark.parametrize(
    "cypher",
    [
        # A second label on a node.
        "MATCH (n:Observation:ProjectedService {tenantId: $tenant}) RETURN n",
        # A label test in a WHERE and a label added by SET are labels too.
        "MATCH (n:Observation {tenantId: $tenant}) WHERE n:ProjectedService RETURN n",
        "MATCH (n:Observation {tenantId: $tenant}) SET n:ProjectedService RETURN n",
        # A node with no variable, a quoted label, a node after a comma and one on a new line.
        "MATCH (:ProjectedService {tenantId: $tenant}) RETURN 1 AS one",
        "MATCH (n:`ProjectedService` {tenantId: $tenant}) RETURN n",
        "MATCH (a:Observation {tenantId: $tenant}), (b:ProjectedCapacity {tenantId: $tenant}) RETURN a",
        "MATCH (a:Observation {tenantId: $tenant})\n--(b:\nProjectedCapacity {tenantId: $tenant}) RETURN a",
        # A label hidden after a relationship pattern with a type.
        "MATCH (a:Observation {tenantId: $tenant})-[:FOCUS]->(b:ProjectedService {tenantId: $tenant}) "
        "RETURN a",
        # No space before the parenthesis.
        "MATCH(n:ProjectedService {tenantId: $tenant}) RETURN n",
    ],
)
def test_a_network_label_is_found_wherever_it_is_written(cypher: str) -> None:
    with pytest.raises(ValueError, match="network label"):
        QueryRegistry().register(_tenant(cypher))


def test_a_label_in_a_comment_or_a_string_is_not_a_label() -> None:
    registry = QueryRegistry()
    registry.register(
        _tenant(
            "MATCH (n:Observation {note: 'ProjectedService', tenantId: $tenant}) "
            "// MATCH (x:ProjectedService)\n"
            "/* (y:ProjectedCapacity) */ RETURN n"
        )
    )


def test_a_relationship_type_and_a_property_value_are_not_labels() -> None:
    registry = QueryRegistry()
    registry.register(
        _tenant(
            "MATCH (a:Observation {tenantId: $tenant})-[r:Network]->(b:Observation "
            "{kind: 'Grant', tenantId: $tenant}) RETURN a"
        )
    )


def test_statement_labels_lists_each_label_once_in_the_order_written() -> None:
    assert statement_labels(
        "MATCH (a:Observation:Resource {tenantId: $tenant}) "
        "MATCH (b:Observation {tenantId: $tenant}) WHERE b:Resource RETURN a"
    ) == ["Observation", "Resource"]
    assert statement_labels("RETURN 1 AS one") == []


def test_a_template_instance_is_judged_by_its_insert_too() -> None:
    registry = QueryRegistry()
    registry.register_template(
        QueryTemplate(
            id="Q-TPL",
            cypher="MATCH (n{insert} {id: $id, tenantId: $tenant}) RETURN n.id AS id",
            mode="read",
            scenario=Scenario("placeholder", insert=":Resource:Observation"),
        )
    )
    assert registry.instance("Q-TPL", ":Resource:Observation").id == "Q-TPL:Resource:Observation"
    with pytest.raises(ValueError, match="network label"):
        registry.instance("Q-TPL", ":ProjectedService")
    with pytest.raises(ValueError, match="network label"):
        registry.instance("Q-TPL", ":Resource:Grant")


# $sourceTenant


def test_only_a_network_statement_may_mention_the_source_tenant() -> None:
    cypher = (
        "MATCH (p:ProjectedCapacity {tenantId: $tenant, sourceTenantId: $sourceTenant}) RETURN p"
    )
    QueryRegistry().register(_network(cypher))
    with pytest.raises(ValueError, match="sourceTenant"):
        QueryRegistry().register(_tenant(cypher.replace("ProjectedCapacity", "Observation")))
    with pytest.raises(ValueError, match="sourceTenant"):
        QueryRegistry().register(
            NamedQuery(
                id="Q-B", cypher=cypher.replace("ProjectedCapacity", "AuditHead"), mode="read",
                scenario=SCENARIO, scope_kinds=BOTH_KINDS,
            )
        )  # fmt: skip


def test_a_network_statement_still_needs_the_scope_entry_and_a_scenario() -> None:
    with pytest.raises(queries_module.TenantPredicateMissing):
        QueryRegistry().register(_network("MATCH (p:ProjectedService {id: $id}) RETURN p"))
    with pytest.raises(queries_module.ScenarioMissing):
        QueryRegistry().register(
            NamedQuery(
                id="Q-N", cypher="MATCH (p:ProjectedService {tenantId: $tenant}) RETURN p",
                mode="read", scope_kinds=NETWORK_KINDS,
            )
        )  # fmt: skip


# The production registry


def test_every_registered_statement_obeys_the_partition_with_its_own_kinds() -> None:
    statements = production_statements()
    assert statements
    for query_id, query in statements.items():
        labels = set(statement_labels(query.cypher))
        if query.scope_kinds == TENANT_KINDS:
            bad = labels & (scope_labels.NETWORK_ONLY_LABELS | scope_labels.REGISTRY_NODE_LABELS)
        else:
            allowed = scope_labels.SCOPE_GENERIC_LABELS
            if query.scope_kinds == NETWORK_KINDS:
                allowed = allowed | scope_labels.NETWORK_ONLY_LABELS
            bad = labels - allowed
        assert not bad, query_id


def test_the_scope_generic_statements_declare_both_kinds_and_nothing_else_does_yet() -> None:
    both = {
        query_id
        for query_id, query in production_statements().items()
        if query.scope_kinds == BOTH_KINDS
    }
    assert both == {
        "Q-AUDIT-ENSURE-HEAD",
        "Q-AUDIT-LOCK-HEAD",
        "Q-AUDIT-APPEND",
        "Q-AUDIT-LINK-AGENT",
        "Q-AUDIT-LINK-ENTITY",
        "Q-AUDIT-LIST",
        "Q-AUDIT-FOR-ENTITY",
        "Q-AUDIT-HEAD",
        "Q-AUDIT-CHAIN",
        "Q-IDEM-HEAD",
        "Q-IDEM-VALUES",
        "Q-IDEM-EDGES",
        "Q-IDEM-CREATE",
        "Q-IDEM-LINK",
        "Q-PROCESSED-MARK",
        "Q-PROCESSED-SEEN",
    }


def test_the_production_registry_holds_a_statement_for_every_kind_it_declares() -> None:
    kinds = {query.scope_kinds for query in production_statements().values()}
    assert TENANT_KINDS in kinds
    assert BOTH_KINDS in kinds
    assert queries_module.REGISTRY is REGISTRY
