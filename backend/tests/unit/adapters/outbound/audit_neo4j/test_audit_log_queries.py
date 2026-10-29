"""Pure tests of the audit adapter's shape (P05, DEC-055): its queries and its method set, and, from
TEN-017, that every audit and provenance statement is per scope (DEC-130 item 6, DEC-132 item 4).
The chain head, its links, the agents and the targets carry the bound tenant, and an unbound call
is refused before any Cypher is sent. No Neo4j here: the generated two-tenant test runs each scenario
on a real database."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from diucs.adapters.outbound.audit_neo4j.audit_log import Neo4jAuditLog, ensure_audit_head
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED
from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import GENESIS_HASH, AuditEntry, genesis_hash_for
from diucs.application.tenancy import TenantNotBound, bind_tenant
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed

AUDIT_QUERY_IDS = {"Q-AUDIT-APPEND", "Q-AUDIT-LIST", "Q-PROV-APPEND"}

# The statements that TEN-017 converts (the chain head, its links, the agents, the targets and the
# provenance records).
CONVERTED_BY_TEN_017: tuple[str, ...] = (
    "Q-AUDIT-APPEND",
    "Q-AUDIT-CHAIN",
    "Q-AUDIT-ENSURE-HEAD",
    "Q-AUDIT-HEAD",
    "Q-AUDIT-LINK-AGENT",
    "Q-AUDIT-LINK-ENTITY",
    "Q-AUDIT-LIST",
    "Q-AUDIT-LOCK-HEAD",
    "Q-PROV-APPEND",
    "Q-PROV-LINK",
    "Q-PROV-SOURCE",
)
_STAMP = "tenantId: $tenant"
_LABELLED_NODE = re.compile(r"\(\s*\w*\s*((?::\s*\w+)+)\s*(\{(?:[^{}]|\{[^{}]*\})*\})?\s*\)")
_AT = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
_ENTRY = AuditEntry(
    action="report-capacity",
    use_case="ReportCapacity",
    actor=Actor(
        role=Role.REPORTER,
        practitioner_id="pr-1",
        device_id="dev-sms-1",
        channel="text",
        service_ids=frozenset({"svc-ucr-west"}),
    ),
    entity_ids=("obs-1",),
    snapshot=None,
    at=_AT,
)


def test_the_audit_and_provenance_queries_are_registered() -> None:
    assert set(REGISTRY.ids()) >= AUDIT_QUERY_IDS


def test_no_audit_or_provenance_query_deletes_anything() -> None:
    audit_ids = [i for i in REGISTRY.ids() if i.startswith(("Q-AUDIT-", "Q-PROV-"))]
    assert audit_ids
    for query_id in audit_ids:
        assert "DELETE" not in REGISTRY.get(query_id).cypher.upper(), query_id


def test_the_audit_log_has_no_update_delete_or_remove() -> None:
    for name in ("update", "delete", "remove"):
        assert not hasattr(Neo4jAuditLog, name), name


@pytest.mark.parametrize("query_id", CONVERTED_BY_TEN_017)
def test_the_audit_statement_is_off_the_ratchet_and_carries_a_usable_scenario(
    query_id: str,
) -> None:
    assert query_id not in UNCONVERTED
    query = REGISTRY.get(query_id)
    assert _STAMP in query.cypher
    assert query.scenario is not None
    assert validate_scenario(query_id, query.scenario) == []


@pytest.mark.parametrize("query_id", CONVERTED_BY_TEN_017)
def test_every_labelled_node_of_the_audit_statement_carries_the_tenant(query_id: str) -> None:
    patterns = _LABELLED_NODE.findall(REGISTRY.get(query_id).cypher)
    assert patterns
    for labels, props in patterns:
        assert _STAMP in props, f"{query_id}: {labels} is matched or created without the tenant"


def test_the_chain_walk_matches_its_targets_only_within_the_tenant() -> None:
    chain = REGISTRY.get("Q-AUDIT-CHAIN").cypher
    assert "(n:ChainLink {tenantId: $tenant})" in chain
    assert "OPTIONAL MATCH (n)-[r]->(m {tenantId: $tenant})" in chain


def test_the_head_is_one_per_tenant() -> None:
    assert "MERGE (h:AuditHead {id: 'audit', tenantId: $tenant})" in (
        REGISTRY.get("Q-AUDIT-ENSURE-HEAD").cypher
    )


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def data(self) -> list[dict[str, Any]]:
        return self._rows


class _RecordingTx:
    """A raw transaction double: records every statement and its parameters. Every statement is
    answered with a head that stands at the genesis, so an append can read where the chain is."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run(self, cypher: str, parameters: dict[str, Any] | None = None, **kw: Any) -> _Rows:
        self.calls.append((cypher, dict(parameters or {})))
        return _Rows([{"lastHash": GENESIS_HASH, "lastSeq": 0}])


class _RecordingSession:
    def __init__(self, tx: _RecordingTx) -> None:
        self._tx = tx

    async def __aenter__(self) -> "_RecordingSession":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute_write(self, work: Any) -> None:
        await work(self._tx)


class _RecordingDriver:
    def __init__(self, tx: _RecordingTx) -> None:
        self._tx = tx

    def session(self) -> _RecordingSession:
        return _RecordingSession(self._tx)


@pytest.fixture
def tx() -> Iterator[_RecordingTx]:
    yield _RecordingTx()


async def test_a_provenance_extra_cannot_be_named_as_the_tenant(tx: _RecordingTx) -> None:
    # The extras are written with `SET p += $extra`: a name of the stamp would overwrite it.
    with bind_tenant("tt-unit-0001"), pytest.raises(ValidationFailed):
        await Neo4jAuditLog(cast(Any, tx)).append_provenance(
            "Communication",
            "c-1",
            "create",
            "pr-1",
            Role.REPORTER,
            extra={"tenantId": "someone-else"},
        )
    assert tx.calls == []


async def test_appending_an_entry_without_a_bound_tenant_is_refused_before_cypher(
    tx: _RecordingTx,
) -> None:
    with pytest.raises(TenantNotBound):
        await Neo4jAuditLog(cast(Any, tx)).append(_ENTRY)
    assert tx.calls == []


async def test_reading_the_chain_without_a_bound_tenant_is_refused_before_cypher(
    tx: _RecordingTx,
) -> None:
    log = Neo4jAuditLog(cast(Any, tx))
    with pytest.raises(TenantNotBound):
        await log.verify_chain()
    with pytest.raises(TenantNotBound):
        await log.records()
    assert tx.calls == []


async def test_every_statement_of_an_append_carries_the_bound_tenant(tx: _RecordingTx) -> None:
    with bind_tenant("tt-unit-0001"):
        await Neo4jAuditLog(cast(Any, tx)).append(_ENTRY)
    assert len(tx.calls) >= 4
    for cypher, parameters in tx.calls:
        assert _STAMP in cypher
        assert parameters["tenant"] == "tt-unit-0001"


async def test_the_head_is_created_for_the_bound_scope_with_its_own_genesis(
    tx: _RecordingTx,
) -> None:
    with bind_tenant("acme-icb"):
        await ensure_audit_head(cast(Any, _RecordingDriver(tx)))
    assert tx.calls == [
        (tx.calls[0][0], {"tenant": "acme-icb", "genesis": genesis_hash_for("acme-icb")})
    ]
