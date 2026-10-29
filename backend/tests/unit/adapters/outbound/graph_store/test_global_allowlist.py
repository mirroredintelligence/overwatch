"""The global statement allowlist and what a global statement may touch (TEN-007, DEC-130 item 3,
DEC-134 item 9, DEC-144 item 4).

Adding a global statement is a deliberate change: the allowlist is pinned here, with each
statement's exact text. A global statement runs with no tenant, so it must be unable to reach a
tenant's data by itself: it is read-only and it names registry labels only. The registry refuses
anything else at registration, so putting an id on the allowlist is not a way round the `$tenant`
rule. These tests are the cheap half; the behaviour on a graph that also holds data is
`tests/integration/graph_store/test_tenant_directory.py`.
"""

import re
from types import MappingProxyType
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store import health, tenant_directory  # noqa: F401
from diucs.adapters.outbound.graph_store import queries as queries_module
from diucs.adapters.outbound.graph_store.driver import run_global_query, run_query
from diucs.adapters.outbound.graph_store.queries import (
    GLOBAL_QUERY_IDS,
    GLOBAL_STATEMENT_LABELS,
    REGISTRY,
    NamedQuery,
    QueryRegistry,
    QueryTemplate,
)
from diucs.application.tenancy import (
    GlobalStatementMisuse,
    TenantParameterRefused,
    bind_tenant,
)

# The only global statements, with the exact text of each. A change to a line here is a change to
# what runs before a tenant is known: it needs a reason on GLOBAL_QUERY_IDS and a reviewer's eye.
EXPECTED_TEXT = {
    "Q-NEO4J-PING": "RETURN 1 AS ok",
    "Q-TENANT-GET": "MATCH (t:Tenant {id: $id}) RETURN properties(t) AS tenant",
    "Q-TENANT-LIST-ACTIVE": (
        "MATCH (t:Tenant {status: 'active'}) RETURN properties(t) AS tenant ORDER BY t.id"
    ),
    "Q-TENANT-ACTIVE-IDS": "MATCH (t:Tenant {status: 'active'}) RETURN t.id AS id ORDER BY t.id",
    "Q-TENANT-BY-NUMBER": (
        "MATCH (t:Tenant)-[:HAS_NUMBER]->(n:TenantNumber "
        "{e164: $number, accountSid: $accountSid, status: 'active'}) "
        "RETURN properties(t) AS tenant, n.e164 AS number, n.accountSid AS accountSid, "
        "n.secretRef AS secretRef"
    ),
    "Q-TENANT-BY-ACCOUNT": (
        "MATCH (t:Tenant)-[:HAS_NUMBER]->(n:TenantNumber "
        "{accountSid: $accountSid, status: 'active'}) "
        "RETURN properties(t) AS tenant, n.e164 AS number, n.accountSid AS accountSid, "
        "n.secretRef AS secretRef ORDER BY n.e164"
    ),
    "Q-TENANT-BY-HOST": "MATCH (t:Tenant {host: $host}) RETURN properties(t) AS tenant",
    "Q-TENANT-BY-ENTRA": (
        "MATCH (t:Tenant {entraDirectoryId: $directoryId}) RETURN properties(t) AS tenant"
    ),
}
EXPECTED_PARAMETERS = {
    "Q-NEO4J-PING": set(),
    "Q-TENANT-GET": {"id"},
    "Q-TENANT-LIST-ACTIVE": set(),
    "Q-TENANT-ACTIVE-IDS": set(),
    "Q-TENANT-BY-NUMBER": {"number", "accountSid"},
    "Q-TENANT-BY-ACCOUNT": {"accountSid"},
    "Q-TENANT-BY-HOST": {"host"},
    "Q-TENANT-BY-ENTRA": {"directoryId"},
}
REASON = "x" * 30


def _global(query_id: str, cypher: str, mode: Any = "read") -> NamedQuery:
    return NamedQuery(id=query_id, cypher=cypher, mode=mode, scope="global")


@pytest.fixture
def allowlisted(monkeypatch: pytest.MonkeyPatch) -> QueryRegistry:
    """A private registry in which the id `Q-TEST-GLOBAL` is on the allowlist, so the rules that
    apply to every allowlisted statement can be tried with statements that must be refused."""
    allowed = MappingProxyType({**GLOBAL_QUERY_IDS, "Q-TEST-GLOBAL": REASON})
    monkeypatch.setattr(queries_module, "GLOBAL_QUERY_IDS", allowed)
    return QueryRegistry()


# The allowlist


def test_the_allowlist_is_the_ping_and_the_seven_directory_statements() -> None:
    assert set(GLOBAL_QUERY_IDS) == set(EXPECTED_TEXT)
    assert len(GLOBAL_QUERY_IDS) == 8


def test_each_entry_gives_a_reason_that_says_what_it_reads() -> None:
    for query_id, reason in GLOBAL_QUERY_IDS.items():
        assert isinstance(reason, str) and len(reason) > 30, query_id
    for query_id in EXPECTED_TEXT:
        if query_id != "Q-NEO4J-PING":
            assert "registry" in GLOBAL_QUERY_IDS[query_id], query_id


def test_the_allowlist_cannot_be_changed_at_run_time() -> None:
    with pytest.raises(TypeError):
        GLOBAL_QUERY_IDS["Q-OTHER"] = "no"  # type: ignore[index]


def test_every_global_statement_in_the_registry_is_on_the_allowlist_and_the_reverse() -> None:
    registered = {i for i in REGISTRY.ids() if REGISTRY.get(i).scope == "global"}
    assert registered == set(GLOBAL_QUERY_IDS)


def test_the_text_of_each_global_statement_is_exactly_what_was_reviewed() -> None:
    for query_id, text in EXPECTED_TEXT.items():
        assert REGISTRY.get(query_id).cypher == text, query_id


# What each one is


def test_every_global_statement_reads_never_mentions_the_tenant_and_takes_known_parameters() -> (
    None
):
    for query_id in GLOBAL_QUERY_IDS:
        query = REGISTRY.get(query_id)
        assert query.scope == "global" and query.mode == "read", query_id
        assert query.scenario is None, query_id
        assert re.search(r"\$tenant\b", query.cypher) is None, query_id
        assert set(re.findall(r"\$(\w+)", query.cypher)) == EXPECTED_PARAMETERS[query_id], query_id
        assert re.search(r"\btenantId\b", query.cypher, re.IGNORECASE) is None, query_id


def test_every_global_statement_names_registry_labels_only() -> None:
    assert frozenset({"Tenant", "TenantNumber"}) == GLOBAL_STATEMENT_LABELS
    for query_id in GLOBAL_QUERY_IDS:
        labels = set(re.findall(r"\(\w*:(\w+)", REGISTRY.get(query_id).cypher))
        assert labels <= GLOBAL_STATEMENT_LABELS, query_id


def test_no_global_statement_writes_or_calls_a_procedure() -> None:
    forbidden = re.compile(
        r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|CALL|LOAD|FOREACH|DROP)\b", re.IGNORECASE
    )
    for query_id in GLOBAL_QUERY_IDS:
        assert forbidden.search(REGISTRY.get(query_id).cypher) is None, query_id


# The registry's rules on a global statement


def test_a_global_statement_that_writes_is_refused_even_on_the_allowlist(
    allowlisted: QueryRegistry,
) -> None:
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL.*read"):
        allowlisted.register(_global("Q-TEST-GLOBAL", "MATCH (t:Tenant) SET t.x = 1", "write"))


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (t:Tenant) SET t.x = 1",
        "MATCH (t:Tenant) CREATE (:Tenant {id: 'x'})",
        "MATCH (t:Tenant) DETACH DELETE t",
        "MATCH (t:Tenant) CALL db.labels() YIELD label RETURN label",
        "match (t:Tenant) merge (t)-[:HAS_NUMBER]->(:TenantNumber)",
    ],
)
def test_a_read_that_contains_a_write_or_a_procedure_is_refused(
    allowlisted: QueryRegistry, cypher: str
) -> None:
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL.*write"):
        allowlisted.register(_global("Q-TEST-GLOBAL", cypher))


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (t:Tenant) WHERE (t.id = 'x') RETURN t.id AS id",
        "MATCH (t:Tenant) RETURN (1 + 2) AS three",
    ],
)
def test_a_parenthesis_that_is_neither_a_node_nor_a_function_call_is_refused(
    allowlisted: QueryRegistry, cypher: str
) -> None:
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL.*parentheses"):
        allowlisted.register(_global("Q-TEST-GLOBAL", cypher))


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (o:Observation {id: $id}) RETURN o.id AS id",
        "MATCH (t:Tenant)-[:HAS_NUMBER]->(n:Person) RETURN n.id AS id",
        "MATCH (t:Tenant) OPTIONAL MATCH (o:Observation) RETURN o.id AS id",
        "MATCH (n:Tenant:Observation) RETURN n.id AS id",
        "MATCH (n :Observation) RETURN n.id AS id",
        "MATCH (n:`Observation`) RETURN n.id AS id",
        "MATCH (n:Tenant) WHERE exists { MATCH (o:Observation) } RETURN n.id AS id",
    ],
)
def test_a_global_statement_that_names_a_label_outside_the_registry_is_refused(
    allowlisted: QueryRegistry, cypher: str
) -> None:
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL"):
        allowlisted.register(_global("Q-TEST-GLOBAL", cypher))


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n) RETURN n.id AS id",
        "MATCH (n {id: $id}) RETURN n.id AS id",
        "MATCH (t:Tenant)-->(n) RETURN n.id AS id",
        "MATCH (t:Tenant)-[:HAS_NUMBER]->() RETURN t.id AS id",
        "MATCH (t:Tenant)<-[]-(n) RETURN n.id AS id",
        "MATCH ()-[r]->(t:Tenant) RETURN t.id AS id",
        "MATCH (t:Tenant) MATCH (n) RETURN n.id AS id",
    ],
)
def test_a_global_statement_with_a_node_that_has_no_label_is_refused(
    allowlisted: QueryRegistry, cypher: str
) -> None:
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL"):
        allowlisted.register(_global("Q-TEST-GLOBAL", cypher))


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (t:Tenant) RETURN count(t) AS n",
        "MATCH (t:Tenant {id: toLower($id)}) RETURN t.id AS id",
        "MATCH (t:Tenant {id: $id}) RETURN coalesce(t.host, '') AS host",
        "MATCH (t:Tenant)-[:HAS_NUMBER]->(n:TenantNumber {e164: $number}) RETURN t.id AS id",
        "MATCH (t:Tenant) WHERE t.status IN ['active'] RETURN t.id AS id ORDER BY t.id",
        "RETURN 1 AS ok",
    ],
)
def test_a_read_of_registry_labels_registers_when_its_id_is_on_the_allowlist(
    allowlisted: QueryRegistry, cypher: str
) -> None:
    allowlisted.register(_global("Q-TEST-GLOBAL", cypher))
    assert allowlisted.get("Q-TEST-GLOBAL").cypher == cypher


def test_a_statement_that_mentions_the_tenant_is_still_refused_on_the_allowlist(
    allowlisted: QueryRegistry,
) -> None:
    with pytest.raises(ValueError, match="cannot mention"):
        allowlisted.register(
            _global("Q-TEST-GLOBAL", "MATCH (t:Tenant {id: $tenant}) RETURN t.id AS id")
        )


def test_an_id_that_is_not_on_the_allowlist_is_refused_whatever_the_statement_reads() -> None:
    with pytest.raises(ValueError, match="not on the global allowlist"):
        QueryRegistry().register(_global("Q-NEW-GLOBAL", "MATCH (t:Tenant) RETURN t.id AS id"))


def test_an_allowlisted_id_cannot_be_registered_as_a_tenant_statement() -> None:
    with pytest.raises(ValueError, match="scope='global'"):
        QueryRegistry().register(
            NamedQuery(
                id="Q-TENANT-GET",
                cypher="MATCH (t:Tenant {id: $id, tenantId: $tenant}) RETURN t.id AS id",
                mode="read",
            )
        )


def test_a_template_cannot_be_global_because_its_insert_would_choose_the_label() -> None:
    template = QueryTemplate(
        id="Q-NEO4J-PING", cypher="MATCH (n{insert}) RETURN n.id AS id", mode="read", scope="global"
    )
    with pytest.raises(ValueError, match="template"):
        QueryRegistry().register_template(template)
    for template_id in REGISTRY.template_ids():
        assert REGISTRY.template(template_id).scope == "tenant", template_id


# Running them


class _Tx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> _Tx:
        self.calls.append((cypher, parameters or {}))
        return self

    async def data(self) -> list[dict[str, Any]]:
        return []


@pytest.mark.parametrize("query_id", sorted(set(EXPECTED_TEXT) - {"Q-NEO4J-PING"}))
async def test_a_directory_statement_runs_only_through_the_global_runner(query_id: str) -> None:
    query = REGISTRY.get(query_id)
    params = {name: "x" for name in EXPECTED_PARAMETERS[query_id]}

    tx = _Tx()
    with bind_tenant("tenant-a"), pytest.raises(GlobalStatementMisuse):
        await run_query(tx, query, **params)  # type: ignore[arg-type]
    assert tx.calls == []

    with pytest.raises(TenantParameterRefused):
        await run_global_query(tx, query, tenant="tenant-b", **params)  # type: ignore[arg-type]
    assert tx.calls == []

    with bind_tenant("tenant-a"):
        await run_global_query(tx, query, **params)  # type: ignore[arg-type]
    assert tx.calls == [(query.cypher, params)]
