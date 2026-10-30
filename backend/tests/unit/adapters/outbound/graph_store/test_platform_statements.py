"""The platform statements: the tenant registry's writes (TEN-028, DEC-503; refines DEC-163).

The registry nodes carry no tenant, so a tenant statement cannot write them and a global statement
is read-only. The few statements that write the registry have a scope of their own. This file pins
the list, the exact text of each statement and the rules that make the list closed: an id on
`PLATFORM_QUERY_IDS`, the SHA-256 pin of its text, registry labels only, CREATE, MERGE and SET only,
no `$tenant`, and a run through `run_platform_query` and nothing else. The behaviour against a real
graph is `tests/integration/graph_store/test_tenant_registry.py`.
"""

import hashlib
import re
from types import MappingProxyType
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store import health, tenant_directory, tenant_registry  # noqa: F401
from diucs.adapters.outbound.graph_store import queries as queries_module
from diucs.adapters.outbound.graph_store.driver import (
    run_global_query,
    run_platform_query,
    run_query,
)
from diucs.adapters.outbound.graph_store.queries import (
    GLOBAL_QUERY_IDS,
    PLATFORM_QUERY_IDS,
    PLATFORM_STATEMENTS,
    REGISTRY,
    NamedQuery,
    QueryRegistry,
    QueryTemplate,
    statement_digest,
)
from diucs.application.tenancy import (
    GlobalStatementMisuse,
    PlatformStatementMisuse,
    TenantParameterRefused,
    bind_tenant,
)

# The only platform statements, with the exact text of each: a change to a line here is a change to
# what writes the tenant registry. It needs a reason on PLATFORM_QUERY_IDS and a reviewer's eye.
EXPECTED_TEXT = {
    "Q-TENANT-REG-CREATE": "CREATE (t:Tenant {id: $id}) SET t += $props RETURN t.id AS id",
    "Q-TENANT-REG-SAVE": (
        "MATCH (t:Tenant {id: $id, epoch: $expectedEpoch, status: $expectedStatus}) "
        "SET t += $props RETURN t.id AS id"
    ),
    "Q-TENANT-REG-SET-HOST": "MATCH (t:Tenant {id: $id}) SET t.host = $host RETURN t.id AS id",
    "Q-TENANT-REG-SET-DIRECTORY": (
        "MATCH (t:Tenant {id: $id}) SET t.entraDirectoryId = $directoryId RETURN t.id AS id"
    ),
    "Q-TENANT-REG-PUT-NUMBER": (
        "MATCH (t:Tenant {id: $id}) "
        "MERGE (t)-[:HAS_NUMBER]->(n:TenantNumber {e164: $e164}) "
        "SET n += $props RETURN n.e164 AS e164"
    ),
    "Q-TENANT-REG-MARK-TESTED": (
        "MATCH (:Tenant {id: $id})-[:HAS_NUMBER]->(n:TenantNumber {e164: $e164}) "
        "SET n.testedAt = $at RETURN n.e164 AS e164"
    ),
    "Q-TENANT-REG-NUMBERS": (
        "MATCH (:Tenant {id: $id})-[:HAS_NUMBER]->(n:TenantNumber) "
        "RETURN n.e164 AS e164, n.accountSid AS accountSid, n.secretRef AS secretRef, "
        "n.status AS status, n.testedAt AS testedAt, n.quarantineUntil AS quarantineUntil "
        "ORDER BY n.e164"
    ),
}
EXPECTED_MODE = {query_id: "write" for query_id in EXPECTED_TEXT} | {"Q-TENANT-REG-NUMBERS": "read"}
EXPECTED_PARAMETERS = {
    "Q-TENANT-REG-CREATE": {"id", "props"},
    "Q-TENANT-REG-SAVE": {"id", "expectedEpoch", "expectedStatus", "props"},
    "Q-TENANT-REG-SET-HOST": {"id", "host"},
    "Q-TENANT-REG-SET-DIRECTORY": {"id", "directoryId"},
    "Q-TENANT-REG-PUT-NUMBER": {"id", "e164", "props"},
    "Q-TENANT-REG-MARK-TESTED": {"id", "e164", "at"},
    "Q-TENANT-REG-NUMBERS": {"id"},
}
REASON = "x" * 30


def _platform(query_id: str, cypher: str, mode: Any = "write") -> NamedQuery:
    return NamedQuery(id=query_id, cypher=cypher, mode=mode, scope="platform")


@pytest.fixture
def allowlisted(monkeypatch: pytest.MonkeyPatch) -> QueryRegistry:
    """A private registry in which `Q-TEST-PLATFORM` is on the platform list, so the rules that
    apply to every platform statement can be tried with statements that must be refused."""
    allowed = MappingProxyType({**PLATFORM_QUERY_IDS, "Q-TEST-PLATFORM": REASON})
    monkeypatch.setattr(queries_module, "PLATFORM_QUERY_IDS", allowed)
    return QueryRegistry()


def _pin(monkeypatch: pytest.MonkeyPatch, cypher: str, query_id: str = "Q-TEST-PLATFORM") -> None:
    pinned = MappingProxyType(
        {**PLATFORM_STATEMENTS, query_id: hashlib.sha256(cypher.strip().encode()).hexdigest()}
    )
    monkeypatch.setattr(queries_module, "PLATFORM_STATEMENTS", pinned)


# -- the list ------------------------------------------------------------------------------------


def test_the_platform_list_is_the_seven_registry_statements() -> None:
    assert set(PLATFORM_QUERY_IDS) == set(EXPECTED_TEXT)
    assert set(PLATFORM_STATEMENTS) == set(EXPECTED_TEXT)
    assert len(PLATFORM_QUERY_IDS) == 7


def test_no_id_is_on_both_the_global_and_the_platform_list() -> None:
    assert set(PLATFORM_QUERY_IDS).isdisjoint(GLOBAL_QUERY_IDS)


def test_each_entry_gives_a_reason_that_says_what_it_touches() -> None:
    for query_id, reason in PLATFORM_QUERY_IDS.items():
        assert isinstance(reason, str) and len(reason) > 30, query_id
        assert "registry" in reason, query_id


def test_the_list_cannot_be_changed_at_run_time() -> None:
    with pytest.raises(TypeError):
        PLATFORM_QUERY_IDS["Q-OTHER"] = "no"  # type: ignore[index]
    with pytest.raises(TypeError):
        PLATFORM_STATEMENTS["Q-OTHER"] = "no"  # type: ignore[index]


def test_every_platform_statement_in_the_registry_is_on_the_list_and_the_reverse() -> None:
    registered = {i for i in REGISTRY.ids() if REGISTRY.get(i).scope == "platform"}
    assert registered == set(PLATFORM_QUERY_IDS)


def test_the_text_of_each_platform_statement_is_exactly_what_was_reviewed() -> None:
    for query_id, text in EXPECTED_TEXT.items():
        assert REGISTRY.get(query_id).cypher == text, query_id


def test_each_digest_is_the_hash_of_the_reviewed_text() -> None:
    for query_id, text in EXPECTED_TEXT.items():
        assert PLATFORM_STATEMENTS[query_id] == statement_digest(text), query_id


def test_every_platform_statement_has_its_mode_no_scenario_and_known_parameters() -> None:
    for query_id in PLATFORM_QUERY_IDS:
        query = REGISTRY.get(query_id)
        assert query.scope == "platform" and query.mode == EXPECTED_MODE[query_id], query_id
        assert query.scenario is None, query_id
        assert re.search(r"\$tenant\b", query.cypher) is None, query_id
        assert re.search(r"\btenantId\b", query.cypher, re.IGNORECASE) is None, query_id
        assert set(re.findall(r"\$(\w+)", query.cypher)) == EXPECTED_PARAMETERS[query_id], query_id


def test_no_platform_statement_deletes_calls_or_loops() -> None:
    for query_id in PLATFORM_QUERY_IDS:
        text = REGISTRY.get(query_id).cypher
        assert re.search(r"\b(DELETE|DETACH|REMOVE|CALL|LOAD|FOREACH|DROP|UNWIND)\b", text) is None


def test_the_read_statement_writes_nothing() -> None:
    text = REGISTRY.get("Q-TENANT-REG-NUMBERS").cypher
    assert re.search(r"\b(CREATE|MERGE|SET)\b", text) is None


# -- what registration refuses -------------------------------------------------------------------


def test_an_id_that_is_not_on_the_list_is_refused_whatever_it_writes() -> None:
    with pytest.raises(ValueError, match="not on the platform allowlist"):
        QueryRegistry().register(_platform("Q-NEW-PLATFORM", "CREATE (t:Tenant {id: $id})"))


def test_a_platform_id_cannot_be_registered_as_a_tenant_or_a_global_statement() -> None:
    with pytest.raises(ValueError, match="scope='platform'"):
        QueryRegistry().register(
            NamedQuery(
                id="Q-TENANT-REG-CREATE",
                cypher="CREATE (t:Tenant {id: $id, tenantId: $tenant})",
                mode="write",
            )
        )
    with pytest.raises(ValueError, match="scope='platform'"):
        QueryRegistry().register(
            NamedQuery(
                id="Q-TENANT-REG-NUMBERS",
                cypher=EXPECTED_TEXT["Q-TENANT-REG-NUMBERS"],
                mode="read",
                scope="global",
            )
        )


def test_a_global_id_cannot_be_registered_as_a_platform_statement() -> None:
    with pytest.raises(ValueError, match="scope='global'"):
        QueryRegistry().register(_platform("Q-TENANT-GET", "MATCH (t:Tenant {id: $id}) RETURN t"))


def test_a_platform_statement_may_not_mention_the_tenant(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "CREATE (t:Tenant {id: $tenant})"
    _pin(monkeypatch, text)
    with pytest.raises(ValueError, match="cannot mention"):
        allowlisted.register(_platform("Q-TEST-PLATFORM", text))


@pytest.mark.parametrize(
    "text",
    [
        "MATCH (t:Tenant {id: $id}) DELETE t",
        "MATCH (t:Tenant {id: $id}) DETACH DELETE t",
        "MATCH (t:Tenant {id: $id}) REMOVE t.host",
        "MATCH (t:Tenant {id: $id}) CALL db.labels()",
        "LOAD CSV FROM 'x' AS row CREATE (t:Tenant {id: row[0]})",
        "MATCH (t:Tenant {id: $id}) FOREACH (x IN [1] | SET t.a = x)",
    ],
)
def test_a_platform_write_may_only_create_merge_and_set(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    _pin(monkeypatch, text)
    with pytest.raises(ValueError, match="only create, merge and set"):
        allowlisted.register(_platform("Q-TEST-PLATFORM", text))


@pytest.mark.parametrize(
    "text",
    [
        "CREATE (n:Resource {id: $id})",
        "MATCH (t:Tenant {id: $id}) MERGE (t)-[:OWNS]->(n:Observation {id: $x})",
        "MATCH (n) SET n.a = 1",
        "CREATE (:Tenant {id: $id})-[:HAS_NUMBER]->(:Network {id: $x})",
    ],
)
def test_a_platform_statement_names_registry_labels_only(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    _pin(monkeypatch, text)
    with pytest.raises(ValueError, match="registry labels only|needs a label"):
        allowlisted.register(_platform("Q-TEST-PLATFORM", text))


def test_a_bare_variable_is_allowed_only_after_a_registry_label_declared_it(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    declared = "MATCH (t:Tenant {id: $id}) MERGE (t)-[:HAS_NUMBER]->(n:TenantNumber {e164: $e})"
    _pin(monkeypatch, declared)
    allowlisted.register(_platform("Q-TEST-PLATFORM", declared))

    undeclared = "MERGE (t)-[:HAS_NUMBER]->(n:TenantNumber {e164: $e})"
    other = QueryRegistry()
    monkeypatch.setattr(queries_module, "PLATFORM_QUERY_IDS", MappingProxyType({"Q-X": REASON}))
    monkeypatch.setattr(
        queries_module,
        "PLATFORM_STATEMENTS",
        MappingProxyType({"Q-X": hashlib.sha256(undeclared.encode()).hexdigest()}),
    )
    with pytest.raises(ValueError, match="needs a label"):
        other.register(_platform("Q-X", undeclared))


def test_a_bare_variable_is_refused_in_a_read_statement(
    allowlisted: QueryRegistry, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = "MATCH (t:Tenant {id: $id}) MATCH (t)-[:HAS_NUMBER]->(n:TenantNumber) RETURN n.e164 AS e"
    _pin(monkeypatch, text)
    with pytest.raises(ValueError, match="needs a label"):
        allowlisted.register(_platform("Q-TEST-PLATFORM", text, mode="read"))


def test_a_changed_byte_is_refused_by_the_pin() -> None:
    changed = EXPECTED_TEXT["Q-TENANT-REG-SET-HOST"].replace("RETURN", "RETURN ")
    with pytest.raises(ValueError, match="not the pinned text"):
        QueryRegistry().register(_platform("Q-TENANT-REG-SET-HOST", changed))


def test_the_text_of_another_platform_statement_under_this_id_is_refused() -> None:
    with pytest.raises(ValueError, match="not the pinned text"):
        QueryRegistry().register(
            _platform("Q-TENANT-REG-SET-HOST", EXPECTED_TEXT["Q-TENANT-REG-SET-DIRECTORY"])
        )


def test_every_listed_statement_registers_in_a_fresh_registry() -> None:
    fresh = QueryRegistry()
    for query_id, text in EXPECTED_TEXT.items():
        fresh.register(_platform(query_id, text, EXPECTED_MODE[query_id]))
    assert set(fresh.ids()) == set(EXPECTED_TEXT)


def test_a_template_cannot_be_a_platform_statement() -> None:
    template = QueryTemplate(
        id="Q-TENANT-REG-CREATE", cypher="CREATE (t{insert})", mode="write", scope="platform"
    )
    with pytest.raises(ValueError, match="template"):
        QueryRegistry().register_template(template)


def test_a_scope_that_is_not_one_of_the_three_is_refused() -> None:
    with pytest.raises(ValueError, match="scope must be"):
        NamedQuery(id="Q-X", cypher="RETURN 1", mode="read", scope="everything")  # type: ignore[arg-type]


# -- how one runs --------------------------------------------------------------------------------


class _Tx:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None) -> _Result:
        self.calls.append((cypher, {} if parameters is None else dict(parameters)))
        return _Result()


class _Result:
    async def data(self) -> list[dict[str, Any]]:
        return []


def _statement() -> NamedQuery:
    return REGISTRY.get("Q-TENANT-REG-SET-HOST")


async def test_a_platform_statement_runs_with_the_parameters_it_is_given_and_no_tenant() -> None:
    tx = _Tx()
    await run_platform_query(tx, _statement(), id="example-icb", host="a.example.org")  # type: ignore[arg-type]
    [(cypher, parameters)] = tx.calls
    assert cypher == EXPECTED_TEXT["Q-TENANT-REG-SET-HOST"]
    assert parameters == {"id": "example-icb", "host": "a.example.org"}


async def test_a_platform_statement_runs_whether_or_not_a_tenant_is_bound() -> None:
    tx = _Tx()
    with bind_tenant("example-icb"):
        await run_platform_query(tx, _statement(), id="other-org", host="b.example.org")  # type: ignore[arg-type]
    await run_platform_query(tx, _statement(), id="other-org", host="b.example.org")  # type: ignore[arg-type]
    assert all("tenant" not in parameters for _, parameters in tx.calls)
    assert len(tx.calls) == 2


async def test_a_platform_statement_refuses_a_tenant_parameter() -> None:
    with pytest.raises(TenantParameterRefused):
        await run_platform_query(_Tx(), _statement(), id="a", host="b", tenant="x")  # type: ignore[arg-type]


async def test_a_platform_statement_is_refused_by_the_tenant_and_the_global_paths() -> None:
    tx = _Tx()
    with bind_tenant("example-icb"), pytest.raises(PlatformStatementMisuse):
        await run_query(tx, _statement(), id="a", host="b")  # type: ignore[arg-type]
    with pytest.raises(GlobalStatementMisuse):
        await run_global_query(tx, _statement(), id="a", host="b")  # type: ignore[arg-type]
    assert tx.calls == []


async def test_the_platform_path_refuses_a_tenant_or_a_global_statement() -> None:
    tx = _Tx()
    with pytest.raises(PlatformStatementMisuse):
        await run_platform_query(tx, REGISTRY.get("Q-TENANT-GET"), id="a")  # type: ignore[arg-type]
    with pytest.raises(PlatformStatementMisuse):
        await run_platform_query(tx, REGISTRY.get("Q-NEO4J-PING"))  # type: ignore[arg-type]
    assert tx.calls == []


async def test_the_platform_path_refuses_a_string_and_an_unregistered_statement() -> None:
    from diucs.application.tenancy import QueryNotRegistered

    tx = _Tx()
    with pytest.raises(QueryNotRegistered):
        await run_platform_query(tx, "CREATE (t:Tenant {id: $id})", id="a")  # type: ignore[arg-type]
    unregistered = _platform("Q-TENANT-REG-SET-HOST", EXPECTED_TEXT["Q-TENANT-REG-SET-HOST"])
    # The same id and text, but a different statement object (another mode): not the registered one.
    other = NamedQuery(
        id=unregistered.id, cypher=unregistered.cypher, mode="read", scope="platform"
    )
    with pytest.raises(QueryNotRegistered):
        await run_platform_query(tx, other, id="a", host="b")  # type: ignore[arg-type]
    assert tx.calls == []
