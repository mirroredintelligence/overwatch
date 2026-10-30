"""The global statement allowlist and what a global statement may touch (TEN-007, DEC-130 item 3,
DEC-134 item 9, DEC-144 item 4).

Adding a global statement is a deliberate change: the allowlist is pinned here, with each
statement's exact text. A global statement runs with no tenant, so it must be unable to reach a
tenant's data by itself: it is read-only and it names registry labels only. The registry refuses
anything else at registration, so putting an id on the allowlist is not a way round the `$tenant`
rule. These tests are the cheap half; the behaviour on a graph that also holds data is
`tests/integration/graph_store/test_tenant_directory.py`.
"""

import hashlib
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
    "Q-TENANT-ACTIVE-LINE": (
        "MATCH (t:Tenant {id: $id, status: 'active'})-[:HAS_NUMBER]->(n:TenantNumber "
        "{status: 'active'}) "
        "RETURN properties(t) AS tenant, n.e164 AS number, n.accountSid AS accountSid, "
        "n.secretRef AS secretRef ORDER BY n.e164"
    ),
    "Q-TENANT-BY-HOST": "MATCH (t:Tenant {host: $host}) RETURN properties(t) AS tenant",
    "Q-TENANT-BY-ENTRA": (
        "MATCH (t:Tenant {entraDirectoryId: $directoryId}) RETURN properties(t) AS tenant"
    ),
    # TEN-031: the two whole-graph counts of the start-up and daily invariant check. They scan every
    # node, so they name no label, and they return only a label set or a relationship type and a
    # count: never a property value.
    "Q-INVARIANT-UNSTAMPED": (
        "MATCH (n) WHERE n.tenantId IS NULL AND none(l IN labels(n) WHERE l IN $registryLabels) "
        "RETURN labels(n) AS labels, count(*) AS n"
    ),
    "Q-INVARIANT-CROSS-SCOPE": (
        "MATCH (a)-[r]->(b) WHERE a.tenantId IS NOT NULL AND b.tenantId IS NOT NULL "
        "AND a.tenantId <> b.tenantId RETURN type(r) AS type, count(*) AS n"
    ),
}
# The two statements that count over the whole graph (TEN-031). The only ones that may name no
# label and read a `tenantId`.
WHOLE_GRAPH = {"Q-INVARIANT-UNSTAMPED", "Q-INVARIANT-CROSS-SCOPE"}
EXPECTED_PARAMETERS = {
    "Q-NEO4J-PING": set(),
    "Q-TENANT-GET": {"id"},
    "Q-TENANT-LIST-ACTIVE": set(),
    "Q-TENANT-ACTIVE-IDS": set(),
    "Q-TENANT-BY-NUMBER": {"number", "accountSid"},
    "Q-TENANT-BY-ACCOUNT": {"accountSid"},
    "Q-TENANT-ACTIVE-LINE": {"id"},
    "Q-TENANT-BY-HOST": {"host"},
    "Q-TENANT-BY-ENTRA": {"directoryId"},
    "Q-INVARIANT-UNSTAMPED": {"registryLabels"},
    "Q-INVARIANT-CROSS-SCOPE": set(),
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


def _pin(monkeypatch: pytest.MonkeyPatch, cypher: str, query_id: str = "Q-TEST-GLOBAL") -> None:
    """Pin `cypher` under `query_id` by the digest the registry computes, so a test can reach the
    structural checks that stand behind the pin."""
    pinned = MappingProxyType(
        {
            **queries_module.GLOBAL_STATEMENTS,
            query_id: hashlib.sha256(cypher.strip().encode()).hexdigest(),
        }
    )
    monkeypatch.setattr(queries_module, "GLOBAL_STATEMENTS", pinned)


# The allowlist


def test_the_allowlist_is_the_ping_the_directory_and_the_two_invariant_counts() -> None:
    assert set(GLOBAL_QUERY_IDS) == set(EXPECTED_TEXT)
    assert len(GLOBAL_QUERY_IDS) == 11
    assert queries_module.GLOBAL_WHOLE_GRAPH_IDS == WHOLE_GRAPH


def test_each_entry_gives_a_reason_that_says_what_it_reads() -> None:
    for query_id, reason in GLOBAL_QUERY_IDS.items():
        assert isinstance(reason, str) and len(reason) > 30, query_id
    for query_id in EXPECTED_TEXT:
        if query_id == "Q-NEO4J-PING":
            continue
        word = "count" if query_id in WHOLE_GRAPH else "registry"
        assert word in GLOBAL_QUERY_IDS[query_id], query_id


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
        if query_id not in WHOLE_GRAPH:
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
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "MATCH (t:Tenant) SET t.x = 1"
    _pin(monkeypatch, text)
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL.*read"):
        allowlisted.register(_global("Q-TEST-GLOBAL", text, "write"))


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
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
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
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
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
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
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
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
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
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
    allowlisted.register(_global("Q-TEST-GLOBAL", cypher))
    assert allowlisted.get("Q-TEST-GLOBAL").cypher == cypher


def test_a_statement_that_mentions_the_tenant_is_still_refused_on_the_allowlist(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "MATCH (t:Tenant {id: $tenant}) RETURN t.id AS id"
    _pin(monkeypatch, text)
    with pytest.raises(ValueError, match="cannot mention"):
        allowlisted.register(_global("Q-TEST-GLOBAL", text))


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


# Round 2: the guarantee is the pin. Each global statement is registered only when its id is in
# GLOBAL_STATEMENTS and the SHA-256 of its text (stripped of leading and trailing space, nothing
# else) equals the digest there. The structural checks stand behind it, as a second defence.


def _digest(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()


def test_the_pins_are_the_digests_of_the_exact_texts_of_the_statements() -> None:
    assert dict(queries_module.GLOBAL_STATEMENTS) == {
        i: _digest(t) for i, t in EXPECTED_TEXT.items()
    }
    assert set(queries_module.GLOBAL_STATEMENTS) == set(GLOBAL_QUERY_IDS)
    for digest in queries_module.GLOBAL_STATEMENTS.values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_the_pins_cannot_be_changed_at_run_time() -> None:
    with pytest.raises(TypeError):
        queries_module.GLOBAL_STATEMENTS["Q-OTHER"] = "0" * 64  # type: ignore[index]


@pytest.mark.parametrize("query_id", sorted(EXPECTED_TEXT))
def test_each_pinned_statement_registers_with_its_exact_text_and_with_outer_whitespace(
    query_id: str,
) -> None:
    text = EXPECTED_TEXT[query_id]
    for variant in (text, f"  {text}\n", f"\n\t{text} "):
        registry = QueryRegistry()
        registry.register(_global(query_id, variant))
        assert registry.get(query_id).cypher == variant


def _altered(text: str) -> list[str]:
    """Changes that leave the text a valid read of registry labels, so only the pin can refuse
    them: a trailing comment, a case change, doubled inner space, one character changed, a changed
    literal, an extra clause."""
    return [
        f"{text} // note",
        f"{text} /* note */",
        text.replace("MATCH", "match", 1) if "MATCH" in text else text.replace("RETURN", "return"),
        text.replace(" ", "  ", 1),
        text[:-1] + ("d" if text[-1] != "d" else "e"),
        text.replace("'active'", "'suspended'") if "'active'" in text else text + " LIMIT 1",
        text + " LIMIT 1",
    ]


@pytest.mark.parametrize("query_id", sorted(EXPECTED_TEXT))
def test_a_pinned_id_with_altered_text_is_refused_by_the_pin(query_id: str) -> None:
    for variant in _altered(EXPECTED_TEXT[query_id]):
        assert variant.strip() != EXPECTED_TEXT[query_id]
        with pytest.raises(ValueError, match=f"{query_id}.*pinned"):
            QueryRegistry().register(_global(query_id, variant))


@pytest.mark.parametrize("query_id", sorted(EXPECTED_TEXT))
def test_a_pinned_id_with_a_single_changed_character_anywhere_is_refused(query_id: str) -> None:
    text = EXPECTED_TEXT[query_id]
    for position in range(len(text)):
        changed = text[:position] + ("~" if text[position] != "~" else "^") + text[position + 1 :]
        with pytest.raises(ValueError, match=query_id):
            QueryRegistry().register(_global(query_id, changed))


def test_the_text_of_one_statement_under_the_id_of_another_is_refused() -> None:
    with pytest.raises(ValueError, match="Q-TENANT-GET.*pinned"):
        QueryRegistry().register(_global("Q-TENANT-GET", EXPECTED_TEXT["Q-TENANT-BY-HOST"]))


def test_an_id_that_is_not_in_the_pin_mapping_is_refused_whatever_its_text(
    allowlisted: QueryRegistry,
) -> None:
    """The id is on the reasons list (the fixture) but has no pin: nothing registers under it,
    even the exact text of a pinned statement."""
    for text in ("RETURN 1 AS ok", EXPECTED_TEXT["Q-TENANT-GET"]):
        with pytest.raises(ValueError, match="Q-TEST-GLOBAL.*no pinned"):
            allowlisted.register(_global("Q-TEST-GLOBAL", text))
    with pytest.raises(ValueError, match="not on the global allowlist"):
        QueryRegistry().register(_global("Q-NEW-GLOBAL", EXPECTED_TEXT["Q-TENANT-GET"]))


def test_every_global_statement_in_the_loaded_registry_matches_its_pin() -> None:
    for query_id in GLOBAL_QUERY_IDS:
        query = REGISTRY.get(query_id)
        assert query_id in queries_module.GLOBAL_STATEMENTS
        assert queries_module.GLOBAL_STATEMENTS[query_id] == _digest(query.cypher), query_id


# The structural checks, behind the pin. `MATCH(` with no space is a node pattern as much as
# `MATCH (` is: a `(` is a function call only after a name on the short list of functions.

BYPASSES = [
    "MATCH(n:Resource) RETURN n.id AS id",
    "MATCH(n) RETURN n",
    "MATCH (t:Tenant) OPTIONAL MATCH(n:Patient) RETURN n.id AS id",
    "MATCH (t:Tenant) WITH t MATCH(n:Observation) RETURN n.id AS id",
    "MATCH (t:Tenant) RETURN t.id AS id UNION MATCH(n:Patient) RETURN n.id AS id",
    "UNWIND [1] AS x MATCH(n:Resource) RETURN n.id AS id",
    "MATCH (t:Tenant) WHERE EXISTS{MATCH(n:Resource)} RETURN t.id AS id",
    "MATCH (t:Tenant) WHERE EXISTS { MATCH(n:Resource) } RETURN t.id AS id",
    "MATCH\t(n:Resource) RETURN n.id AS id",
    "MATCH\n(n:Resource) RETURN n.id AS id",
    "MATCH/**/(n:Resource) RETURN n.id AS id",
    "MATCH (t:Tenant)WHERE(t.id = 'x') MATCH(n:Resource) RETURN n.id AS id",
    "MATCH (t:Tenant) RETURN t.id AS id UNION ALL MATCH(n:Patient) RETURN n.id AS id",
    "MATCH (t:Tenant) WITH t WHERE t.id = 'x' MATCH(:Resource) RETURN t.id AS id",
    "MATCH (t:Tenant) MATCH(n)-[:R]->(m:Tenant) RETURN n.id AS id",
    "MATCH p=(t:Tenant)-[*]-(n) RETURN n.id AS id",
    "MATCH (t:Tenant) RETURN labels(t) AS l, Foo(t) AS f",
    "OPTIONAL MATCH(n:Person) RETURN n.id AS id",
    "MATCH (t:Tenant) CALL{MATCH(n:Resource) RETURN n} RETURN n.id AS id",
    "MATCH (t:Tenant) RETURN t.id AS id // fine\nUNION MATCH(n:Resource) RETURN n.id AS id",
    "/* x */ MATCH(n:Resource) RETURN n.id AS id",
    "MATCH (t:Tenant) RETURN t.id AS id; MATCH(n:Resource) RETURN n.id AS id",
]


@pytest.mark.parametrize("cypher", BYPASSES)
def test_the_structural_check_alone_refuses_every_bypass_even_when_the_text_is_pinned(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL") as raised:
        allowlisted.register(_global("Q-TEST-GLOBAL", cypher))
    assert "pinned" not in str(raised.value), "the pin let it through; the structure must refuse it"


@pytest.mark.parametrize("cypher", BYPASSES)
def test_the_pin_refuses_every_bypass_under_every_allowlisted_id(cypher: str) -> None:
    for query_id in GLOBAL_QUERY_IDS:
        with pytest.raises(ValueError, match=query_id):
            QueryRegistry().register(_global(query_id, cypher))


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (t:Tenant) RETURN t.id AS id // MATCH (n:Resource)",
        "MATCH (t:Tenant) RETURN '(n:Resource)' AS text",
        'MATCH (t:Tenant) RETURN "MATCH(n:Resource)" AS text',
        "MATCH (t:Tenant) /* MATCH(n:Resource) */ RETURN t.id AS id",
        "MATCH (t:Tenant) RETURN 'it\\'s (x)' AS text",
        "MATCH(t:Tenant) RETURN t.id AS id",
        "MATCH (t:Tenant)RETURN count(t) AS n",
        "MATCH (t:Tenant) RETURN properties(t) AS p, size(labels(t)) AS n, "
        "coalesce(t.host, '') AS h",
    ],
)
def test_a_comment_or_string_holding_a_pattern_is_not_one_and_a_spaceless_read_is_fine(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
    allowlisted.register(_global("Q-TEST-GLOBAL", cypher))


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (t:Tenant) RETURN 'unterminated AS text",
        "MATCH (t:Tenant) RETURN t.id AS id /* unterminated",
        "MATCH (t:Tenant) RETURN t.`id AS id",
    ],
)
def test_an_unterminated_string_or_comment_is_refused(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL"):
        allowlisted.register(_global("Q-TEST-GLOBAL", cypher))


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (t:Tenant) RETURN dbms.x(t:Tenant) AS x",
        "MATCH (t:Tenant) RETURN foo(t:Tenant) AS x",
        "MATCH (t:Tenant) RETURN {a: 1} AS m",
        "MATCH (t:Tenant) RETURN t{.id} AS m",
        "MATCH (t:Tenant) WHERE EXISTS { RETURN 1 } RETURN t.id AS id",
        "MATCH (t:Tenant) RETURN t.id AS id; RETURN 1 AS ok",
    ],
)
def test_a_function_that_is_not_listed_and_a_brace_outside_a_node_are_refused(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL") as raised:
        allowlisted.register(_global("Q-TEST-GLOBAL", cypher))
    assert "pinned" not in str(raised.value)


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


# TEN-031: the whole-graph counts. A statement that scans every node names no label, so the label
# rule cannot hold for it; what replaces the rule for these two ids, and only these, is that the
# statement returns a label set or a relationship type and a count and nothing else, so no
# property value leaves the graph. The pin is still the guarantee.


@pytest.fixture
def whole_graph(monkeypatch: pytest.MonkeyPatch) -> QueryRegistry:
    allowed = MappingProxyType({**GLOBAL_QUERY_IDS, "Q-TEST-GLOBAL": REASON})
    monkeypatch.setattr(queries_module, "GLOBAL_QUERY_IDS", allowed)
    monkeypatch.setattr(
        queries_module, "GLOBAL_WHOLE_GRAPH_IDS", frozenset({"Q-TEST-GLOBAL"}), raising=True
    )
    return QueryRegistry()


@pytest.mark.parametrize("query_id", sorted(WHOLE_GRAPH))
def test_each_invariant_count_registers_with_no_tenant_bound_and_is_global_and_read_only(
    query_id: str,
) -> None:
    query = REGISTRY.get(query_id)
    assert query.scope == "global" and query.mode == "read" and query.scenario is None
    assert query_id in GLOBAL_QUERY_IDS and query_id in queries_module.GLOBAL_STATEMENTS


@pytest.mark.parametrize("query_id", sorted(WHOLE_GRAPH))
def test_each_invariant_count_returns_only_a_label_set_or_a_type_and_a_count(
    query_id: str,
) -> None:
    text = REGISTRY.get(query_id).cypher
    assert re.search(r"RETURN (?:labels\(\w+\)|type\(\w+\)) AS \w+, count\(\*\) AS \w+$", text), (
        query_id
    )


@pytest.mark.parametrize(
    "cypher",
    [
        # a property value leaves the graph
        "MATCH (n) WHERE n.tenantId IS NULL RETURN n.id AS id, count(*) AS n",
        "MATCH (n) WHERE n.tenantId IS NULL RETURN labels(n) AS labels, n.id AS id",
        "MATCH (n) WHERE n.tenantId IS NULL RETURN properties(n) AS p",
        "MATCH (n) WHERE n.tenantId IS NULL RETURN n",
        "MATCH (n) RETURN labels(n) AS labels, collect(n.id) AS ids, count(*) AS n",
        "MATCH (n) RETURN labels(n) AS labels, count(*) AS n, n.id AS id",
        # a write or a procedure
        "MATCH (n) WHERE n.tenantId IS NULL SET n.x = 1 RETURN labels(n) AS labels, count(*) AS n",
        "MATCH (n) DETACH DELETE n RETURN labels(n) AS labels, count(*) AS n",
        "CALL db.labels() YIELD label RETURN labels(n) AS labels, count(*) AS n",
        # more than one statement, or a second RETURN
        "MATCH (n) RETURN labels(n) AS labels, count(*) AS n; MATCH (m) RETURN m",
        "MATCH (n) RETURN labels(n) AS labels, count(*) AS n UNION MATCH (m) RETURN m",
        # a function that is not allowed
        "MATCH (n) RETURN keys(n) AS labels, count(*) AS n",
        # a node with a property map (a lookup, not a scan)
        "MATCH (n {id: 'x'}) RETURN labels(n) AS labels, count(*) AS n",
    ],
)
def test_a_whole_graph_statement_that_could_return_a_value_or_write_is_refused(
    whole_graph: QueryRegistry, monkeypatch: pytest.MonkeyPatch, cypher: str
) -> None:
    _pin(monkeypatch, cypher)
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL") as raised:
        whole_graph.register(_global("Q-TEST-GLOBAL", cypher))
    assert "pinned" not in str(raised.value), "the pin let it through; the structure must refuse it"


def test_a_whole_graph_scan_is_accepted_only_under_a_whole_graph_id(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An id that is on the allowlist but not a whole-graph id keeps the label rule: `(n)` with no
    label is refused, whatever the pin says."""
    cypher = EXPECTED_TEXT["Q-INVARIANT-CROSS-SCOPE"]
    _pin(monkeypatch, cypher)
    with pytest.raises(ValueError, match="Q-TEST-GLOBAL") as raised:
        allowlisted.register(_global("Q-TEST-GLOBAL", cypher))
    assert "pinned" not in str(raised.value)


def test_the_two_invariant_counts_register_under_a_whole_graph_id_with_their_exact_text(
    whole_graph: QueryRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    for query_id in sorted(WHOLE_GRAPH):
        cypher = EXPECTED_TEXT[query_id]
        _pin(monkeypatch, cypher)
        registry = QueryRegistry()
        registry.register(_global("Q-TEST-GLOBAL", cypher))
        assert registry.get("Q-TEST-GLOBAL").cypher == cypher


def test_the_whole_graph_ids_are_two_and_cannot_be_changed_at_run_time() -> None:
    assert isinstance(queries_module.GLOBAL_WHOLE_GRAPH_IDS, frozenset)
    assert set(GLOBAL_QUERY_IDS) >= queries_module.GLOBAL_WHOLE_GRAPH_IDS
