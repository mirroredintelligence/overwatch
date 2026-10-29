"""The registry of fixed statements (TEN-001, DEC-142): what can be registered, what is refused,
the ratchet of statements that are not converted yet, and the list of every statement.

The registration check is cheap and is not a proof: it catches a statement that never mentions
`$tenant`. The proof is the generated two-tenant test of TEN-004.
"""

import ast
import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import diucs.adapters.outbound.audit_neo4j as audit_package
import diucs.adapters.outbound.graph_store as graph_store_package
from diucs.adapters.outbound.graph_store import queries as queries_module
from diucs.adapters.outbound.graph_store.queries import (
    GLOBAL_QUERY_IDS,
    REGISTRY,
    NamedQuery,
    QueryRegistry,
    QueryTemplate,
    Scenario,
    ScenarioMissing,
    TenantPredicateMissing,
)
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED

SCENARIO = Scenario("placeholder until TEN-004")
SECRET_CYPHER = "MATCH (n:Marker {key: $key, note: 'secret-cypher-marker'}) RETURN n"
TENANT_CYPHER = "MATCH (n:Marker {key: $key, tenantId: $tenant}) RETURN n.key AS key"
OLD_CYPHER = "MATCH (n:Marker {key: $key}) RETURN n.key AS key"


def _tenant_query(query_id: str = "Q-T", **kw: object) -> NamedQuery:
    fields: dict[str, object] = {"cypher": TENANT_CYPHER, "mode": "read", "scenario": SCENARIO}
    fields.update(kw)
    return NamedQuery(id=query_id, **fields)  # type: ignore[arg-type]


# The statement object


def test_a_statement_is_a_tenant_statement_without_a_scenario_unless_said_otherwise() -> None:
    query = NamedQuery(id="Q-D", cypher="RETURN 1", mode="read")
    assert query.scope == "tenant"
    assert query.scenario is None


@pytest.mark.parametrize("mode", ["read", "write"])
def test_both_modes_are_accepted(mode: str) -> None:
    query = NamedQuery(id=f"Q-MODE-{mode}", cypher="RETURN 1", mode=mode)  # type: ignore[arg-type]
    assert query.mode == mode


@pytest.mark.parametrize("mode", ["", "READ", "delete"])
def test_any_other_mode_is_rejected(mode: str) -> None:
    with pytest.raises(ValueError, match="mode"):
        NamedQuery(id="Q-BAD-MODE", cypher="RETURN 1", mode=mode)  # type: ignore[arg-type]


@pytest.mark.parametrize("scope", ["", "TENANT", "network", "other"])
def test_any_scope_other_than_tenant_or_global_is_rejected(scope: str) -> None:
    with pytest.raises(ValueError, match="scope"):
        NamedQuery(id="Q-BAD-SCOPE", cypher="RETURN 1", mode="read", scope=scope)  # type: ignore[arg-type]


@pytest.mark.parametrize("scenario", ["a scenario", 3, {"seed": 1}])
def test_a_scenario_that_is_not_a_scenario_is_rejected(scenario: object) -> None:
    with pytest.raises(ValueError, match="scenario"):
        NamedQuery(id="Q-BAD-SCN", cypher="RETURN 1", mode="read", scenario=scenario)  # type: ignore[arg-type]


# Registering a statement


def test_a_converted_statement_registers_and_is_returned_by_id() -> None:
    registry = QueryRegistry()
    query = _tenant_query("Q-SVC-LATEST")
    registry.register(query)
    assert registry.get("Q-SVC-LATEST") == query
    assert registry.ids() == ["Q-SVC-LATEST"]


def test_duplicate_query_id_is_a_value_error() -> None:
    registry = QueryRegistry()
    registry.register(_tenant_query("Q-DUP"))
    with pytest.raises(ValueError, match="Q-DUP"):
        registry.register(_tenant_query("Q-DUP", mode="write"))


def test_unknown_query_id_is_a_key_error_naming_the_id() -> None:
    with pytest.raises(KeyError, match="Q-UNKNOWN"):
        QueryRegistry().get("Q-UNKNOWN")


def test_a_statement_that_never_mentions_the_tenant_is_refused_naming_the_id_only() -> None:
    registry = QueryRegistry()
    with pytest.raises(TenantPredicateMissing) as raised:
        registry.register(
            NamedQuery(id="Q-NEW", cypher=SECRET_CYPHER, mode="read", scenario=SCENARIO)
        )
    assert "Q-NEW" in str(raised.value)
    assert "secret-cypher-marker" not in str(raised.value)
    assert isinstance(raised.value, ValueError)
    assert registry.ids() == []


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n:X {tenantId: $tenantId}) RETURN n",
        "MATCH (n:X {tenantId: $tenants}) RETURN n",
        "MATCH (n:X {tenantId: $other}) RETURN n",
        "MATCH (n:X) RETURN n, 'tenant' AS t",
        "MATCH (n:X) RETURN $Tenant",
    ],
)
def test_only_the_exact_parameter_dollar_tenant_counts(cypher: str) -> None:
    registry = QueryRegistry()
    with pytest.raises(TenantPredicateMissing):
        registry.register(NamedQuery(id="Q-NEW", cypher=cypher, mode="read", scenario=SCENARIO))


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n:X {tenantId: $tenant}) RETURN n",
        "MATCH (n:X) WHERE n.tenantId=$tenant RETURN n",
        "MATCH (n:X) RETURN n, $tenant AS t",
        "MATCH (n:X {tenantId: $tenant})\nRETURN n",
    ],
)
def test_a_statement_that_mentions_dollar_tenant_passes_the_cheap_check(cypher: str) -> None:
    registry = QueryRegistry()
    registry.register(NamedQuery(id="Q-NEW", cypher=cypher, mode="read", scenario=SCENARIO))
    assert registry.ids() == ["Q-NEW"]


def test_a_converted_statement_with_no_scenario_is_refused() -> None:
    registry = QueryRegistry()
    with pytest.raises(ScenarioMissing) as raised:
        registry.register(_tenant_query("Q-NEW", scenario=None))
    assert "Q-NEW" in str(raised.value)
    assert isinstance(raised.value, ValueError)
    assert registry.ids() == []


def test_an_id_on_the_ratchet_registers_without_a_tenant_and_without_a_scenario() -> None:
    registry = QueryRegistry(unconverted=frozenset({"Q-OLD"}))
    registry.register(NamedQuery(id="Q-OLD", cypher=OLD_CYPHER, mode="read"))
    assert registry.ids() == ["Q-OLD"]
    assert registry.is_tenant_pending(registry.get("Q-OLD")) is True
    assert registry.needs_conversion(registry.get("Q-OLD")) is True


def test_the_ratchet_excuses_only_the_ids_on_it() -> None:
    registry = QueryRegistry(unconverted=frozenset({"Q-OLD"}))
    with pytest.raises(TenantPredicateMissing):
        registry.register(NamedQuery(id="Q-OLDER", cypher=OLD_CYPHER, mode="read"))
    with pytest.raises(ScenarioMissing):
        registry.register(NamedQuery(id="Q-NEWER", cypher=TENANT_CYPHER, mode="read"))
    assert registry.ids() == []


def test_a_ratchet_statement_that_was_converted_no_longer_needs_conversion() -> None:
    registry = QueryRegistry(unconverted=frozenset({"Q-OLD"}))
    registry.register(_tenant_query("Q-OLD"))
    assert registry.is_tenant_pending(registry.get("Q-OLD")) is False
    assert registry.needs_conversion(registry.get("Q-OLD")) is False


def test_a_statement_with_a_tenant_and_no_scenario_needs_conversion_but_is_not_pending() -> None:
    registry = QueryRegistry(unconverted=frozenset({"Q-OLD"}))
    registry.register(_tenant_query("Q-OLD", scenario=None))
    assert registry.is_tenant_pending(registry.get("Q-OLD")) is False
    assert registry.needs_conversion(registry.get("Q-OLD")) is True


# Global statements


def test_the_global_allowlist_holds_the_health_ping_and_gives_a_reason_for_each_entry() -> None:
    # The whole list, with each statement's text, is pinned in test_global_allowlist.py (TEN-007).
    assert "Q-NEO4J-PING" in GLOBAL_QUERY_IDS
    assert all(isinstance(reason, str) and len(reason) > 10 for reason in GLOBAL_QUERY_IDS.values())
    with pytest.raises(TypeError):
        GLOBAL_QUERY_IDS["Q-OTHER"] = "no"  # type: ignore[index]


def test_an_allowlisted_global_statement_registers_with_no_tenant_and_no_scenario() -> None:
    registry = QueryRegistry()
    ping = NamedQuery(id="Q-NEO4J-PING", cypher="RETURN 1 AS ok", mode="read", scope="global")
    registry.register(ping)
    assert registry.get("Q-NEO4J-PING") == ping
    assert registry.is_tenant_pending(ping) is False
    assert registry.needs_conversion(ping) is False


def test_a_global_statement_off_the_allowlist_is_refused_naming_the_id() -> None:
    registry = QueryRegistry()
    with pytest.raises(ValueError, match="Q-SNEAKY"):
        registry.register(
            NamedQuery(id="Q-SNEAKY", cypher="MATCH (n) RETURN n", mode="read", scope="global")
        )
    assert registry.ids() == []


def test_a_global_statement_that_mentions_the_tenant_is_refused() -> None:
    registry = QueryRegistry()
    with pytest.raises(ValueError, match="Q-NEO4J-PING"):
        registry.register(
            NamedQuery(
                id="Q-NEO4J-PING",
                cypher="RETURN $tenant AS ok",
                mode="read",
                scope="global",
            )
        )


# Is a statement registered, and is it still one that needs conversion


def test_a_registered_statement_is_registered() -> None:
    registry = QueryRegistry()
    query = _tenant_query()
    registry.register(query)
    assert registry.is_registered(query) is True
    assert registry.is_tenant_pending(query) is False


def test_the_same_id_with_other_text_is_not_the_registered_statement() -> None:
    registry = QueryRegistry()
    registry.register(_tenant_query())
    assert registry.is_registered(_tenant_query(cypher=OLD_CYPHER)) is False
    assert registry.is_registered(_tenant_query(mode="write")) is False
    assert registry.is_registered(_tenant_query(scenario=Scenario("another"))) is False


def test_an_unregistered_statement_a_string_and_other_objects_are_not_registered() -> None:
    registry = QueryRegistry()
    registry.register(_tenant_query())
    assert registry.is_registered(_tenant_query("Q-OTHER")) is False
    for not_a_query in ("Q-T", TENANT_CYPHER, None, 3, {"id": "Q-T"}):
        assert registry.is_registered(not_a_query) is False  # type: ignore[arg-type]


def test_a_statement_registered_in_another_registry_is_not_registered_here() -> None:
    one, other = QueryRegistry(), QueryRegistry()
    query = _tenant_query()
    one.register(query)
    assert other.is_registered(query) is False


# Templates: a fixed statement with one label or relationship type to insert


TEMPLATE = QueryTemplate(
    id="Q-TPL-WRITE",
    cypher="UNWIND $rows AS row MERGE (n{insert} {key: row.key, tenantId: $tenant}) RETURN n",
    mode="write",
    scenario=SCENARIO,
)


def test_a_template_registers_once_and_is_listed() -> None:
    registry = QueryRegistry()
    registry.register_template(TEMPLATE)
    assert registry.template_ids() == ["Q-TPL-WRITE"]
    assert registry.ids() == []
    with pytest.raises(ValueError, match="Q-TPL-WRITE"):
        registry.register_template(TEMPLATE)


def test_a_template_and_a_statement_cannot_share_an_id() -> None:
    registry = QueryRegistry()
    registry.register(_tenant_query("Q-TPL-WRITE"))
    with pytest.raises(ValueError, match="Q-TPL-WRITE"):
        registry.register_template(TEMPLATE)
    other = QueryRegistry()
    other.register_template(TEMPLATE)
    with pytest.raises(ValueError, match="Q-TPL-WRITE"):
        other.register(_tenant_query("Q-TPL-WRITE"))


def test_a_template_is_checked_like_a_statement() -> None:
    registry = QueryRegistry()
    no_tenant = QueryTemplate(
        id="Q-TPL-NO", cypher="MERGE (n{insert} {key: 1}) RETURN n", mode="write"
    )
    with pytest.raises(TenantPredicateMissing, match="Q-TPL-NO"):
        registry.register_template(no_tenant)
    no_scenario = QueryTemplate(
        id="Q-TPL-NS", cypher="MERGE (n{insert} {tenantId: $tenant}) RETURN n", mode="write"
    )
    with pytest.raises(ScenarioMissing, match="Q-TPL-NS"):
        registry.register_template(no_scenario)
    assert registry.template_ids() == []


def test_a_template_scope_and_mode_are_checked() -> None:
    with pytest.raises(ValueError, match="mode"):
        QueryTemplate(id="Q-TPL", cypher="RETURN 1", mode="delete")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="scope"):
        QueryTemplate(id="Q-TPL", cypher="RETURN 1", mode="read", scope="x")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="scenario"):
        QueryTemplate(id="Q-TPL", cypher="RETURN 1", mode="read", scenario="x")  # type: ignore[arg-type]


def test_an_instance_is_the_template_with_the_insert_and_is_registered_once() -> None:
    registry = QueryRegistry()
    registry.register_template(TEMPLATE)
    first = registry.instance("Q-TPL-WRITE", ":Resource:Organization")
    assert first.id == "Q-TPL-WRITE:Resource:Organization"
    assert first.cypher == (
        "UNWIND $rows AS row MERGE (n:Resource:Organization {key: row.key, tenantId: $tenant}) "
        "RETURN n"
    )
    assert (first.mode, first.scope, first.scenario) == ("write", "tenant", SCENARIO)
    assert registry.instance("Q-TPL-WRITE", ":Resource:Organization") is first
    assert registry.is_registered(first) is True
    assert registry.get(first.id) is first
    assert registry.ids() == [first.id]


@pytest.mark.parametrize(
    "insert", [":Organization", ":Resource:HealthcareService", ":HAS_X", ":_a1"]
)
def test_an_insert_that_is_a_chain_of_label_names_is_accepted(insert: str) -> None:
    registry = QueryRegistry()
    registry.register_template(TEMPLATE)
    assert registry.instance("Q-TPL-WRITE", insert).id == f"Q-TPL-WRITE{insert}"


@pytest.mark.parametrize(
    "insert",
    [
        "",
        "Organization",
        ":",
        "::A",
        ":A:",
        ":A B",
        ":A}",
        ":A) DETACH DELETE n //",
        ":A\n",
        ":1A",
        ":A-B",
        ":`A`",
        ":A;",
        ": A",
        ":é",
        ":A\x00",
    ],
)
def test_an_insert_that_is_anything_but_a_chain_of_label_names_is_refused(insert: str) -> None:
    registry = QueryRegistry()
    registry.register_template(TEMPLATE)
    with pytest.raises(ValueError, match="insert"):
        registry.instance("Q-TPL-WRITE", insert)
    assert registry.ids() == []


def test_a_template_without_the_placeholder_takes_no_insert() -> None:
    registry = QueryRegistry()
    plain = QueryTemplate(
        id="Q-TPL-PLAIN",
        cypher="MATCH (n:Marker {tenantId: $tenant}) RETURN n",
        mode="read",
        scenario=SCENARIO,
    )
    registry.register_template(plain)
    instance = registry.instance("Q-TPL-PLAIN")
    assert instance.id == "Q-TPL-PLAIN"
    assert instance.cypher == plain.cypher
    with pytest.raises(ValueError, match="insert"):
        registry.instance("Q-TPL-PLAIN", ":Organization")


def test_a_registered_template_can_be_read_back_and_an_unknown_one_is_a_key_error() -> None:
    registry = QueryRegistry(unconverted=frozenset({"Q-TPL-OLD"}))
    template = QueryTemplate(id="Q-TPL-OLD", cypher="MERGE (n{insert}) RETURN n", mode="write")
    registry.register_template(template)
    assert registry.template("Q-TPL-OLD") is template
    with pytest.raises(KeyError, match="Q-NO-TEMPLATE"):
        registry.template("Q-NO-TEMPLATE")


def test_an_instance_of_an_unknown_template_is_a_key_error() -> None:
    with pytest.raises(KeyError, match="Q-NO-TEMPLATE"):
        QueryRegistry().instance("Q-NO-TEMPLATE", ":A")


def test_an_instance_of_a_ratchet_template_is_tenant_pending_by_the_ratchet_on_the_template() -> (
    None
):
    registry = QueryRegistry(unconverted=frozenset({"Q-TPL-OLD"}))
    registry.register_template(
        QueryTemplate(id="Q-TPL-OLD", cypher="MERGE (n{insert} {key: 1}) RETURN n", mode="write")
    )
    instance = registry.instance("Q-TPL-OLD", ":Organization")
    assert registry.is_tenant_pending(instance) is True
    assert registry.is_registered(instance) is True
    assert registry.ratchet_ids() == ["Q-TPL-OLD"]


def test_a_plain_statement_id_cannot_contain_a_colon_so_it_cannot_borrow_a_template_place() -> None:
    """`Q-TPL-OLD:Evil` would otherwise take the ratchet place of the template `Q-TPL-OLD`."""
    registry = QueryRegistry(unconverted=frozenset({"Q-TPL-OLD"}))
    with pytest.raises(ValueError, match="colon"):
        registry.register(NamedQuery(id="Q-TPL-OLD:Evil", cypher=OLD_CYPHER, mode="read"))
    with pytest.raises(ValueError, match="colon"):
        registry.register_template(
            QueryTemplate(id="Q-TPL-OLD:Evil", cypher="MERGE (n{insert}) RETURN n", mode="write")
        )
    assert registry.ids() == []
    assert registry.template_ids() == []


# The module registry and the ratchet


def _import_every_module(package: object) -> None:
    for module in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):  # type: ignore[attr-defined]
        importlib.import_module(module.name)


@pytest.fixture(scope="module")
def loaded() -> QueryRegistry:
    _import_every_module(graph_store_package)
    _import_every_module(audit_package)
    return REGISTRY


def test_the_module_registry_has_no_test_statement(loaded: QueryRegistry) -> None:
    assert "Q-UNKNOWN" not in loaded.ids()
    with pytest.raises(KeyError, match="Q-UNKNOWN"):
        loaded.get("Q-UNKNOWN")


def test_every_statement_in_the_source_is_in_the_registry(loaded: QueryRegistry) -> None:
    """The registry lists every statement: each `Q-...` id literal under src is a registered
    statement, a template or the base of an instance."""
    src = Path(queries_module.__file__).parents[4]
    literal = re.compile(r"Q-[A-Z0-9]+(?:-[A-Z0-9]+)*")
    found: set[str] = set()
    for path in src.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and literal.fullmatch(node.value)
            ):
                found.add(node.value)
    known = set(loaded.ids()) | set(loaded.template_ids())
    assert found, "the scan found no statement ids: it is not looking at the source"
    assert found - known == set(), sorted(found - known)
    assert len(loaded.ids()) >= 100
    assert len(loaded.template_ids()) == 16  # 17 less the dead idempotency pair, plus LINK-SHARED


def test_every_registered_statement_is_converted_unconverted_or_global(
    loaded: QueryRegistry,
) -> None:
    for query_id in loaded.ids():
        query = loaded.get(query_id)
        if query.scope == "global":
            assert query_id in GLOBAL_QUERY_IDS
        elif loaded.needs_conversion(query):
            assert query.id.partition(":")[0] in UNCONVERTED
        else:
            assert re.search(r"\$tenant\b", query.cypher) and query.scenario is not None


def test_the_ratchet_is_exactly_the_statements_that_are_not_converted(
    loaded: QueryRegistry,
) -> None:
    """A converted statement must leave the list, and nothing may be on it that is not a
    statement (a stale entry fails here)."""
    assert set(UNCONVERTED) == set(loaded.ratchet_ids())
    assert loaded.ratchet_ids() == sorted(loaded.ratchet_ids())
    assert not set(UNCONVERTED) & set(GLOBAL_QUERY_IDS)


def test_the_ratchet_may_only_shrink() -> None:
    """126 is the number of statements and templates at TEN-001; TEN-004 converted eight of them
    (118 left), TEN-009 the seventeen of the resource store, fifteen converted and two removed
    (101 left), and L01 the four link-token statements (97 left). A conversion bundle lowers this
    number in the same commit that removes ids from the list; nothing raises it. The ids themselves
    are pinned against the initial list in test_tenant_ratchet.py. TEN-010 converted the eighteen
    statements of the service, capacity, booking and case repositories (79 left)."""
    assert len(UNCONVERTED) <= 79
    assert len(UNCONVERTED) == len(set(UNCONVERTED))


def test_the_module_registry_follows_the_ratchet_of_the_module(loaded: QueryRegistry) -> None:
    assert loaded.is_registered(loaded.get("Q-NEO4J-PING"))
    assert loaded.get("Q-NEO4J-PING").scope == "global"
    # A new statement that is not tenant-scoped cannot be added to the module registry.
    with pytest.raises(TenantPredicateMissing):
        loaded.register(NamedQuery(id="Q-BRAND-NEW", cypher=OLD_CYPHER, mode="read"))
    assert "Q-BRAND-NEW" not in loaded.ids()
