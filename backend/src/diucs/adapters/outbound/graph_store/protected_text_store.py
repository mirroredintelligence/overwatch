"""Protected text on Neo4j (P20): free text from safety concerns, problem reports and notes.

A text is one node, (:Protected:ProtectedText {handle, kind, aboutId, text, createdAt, tenantId}),
with no relationship to anything. Only the statements named Q-PROT-* may touch the Protected label
(Neo4j Community has no role-based access control, so this is enforced by code and by a test over
the registry). The handle is a random URL-safe token of 128 bits. The text is limited to 280
characters, and the store refuses longer text with ValidationFailed. Reading it back resolves only
inside the bound tenant.

Open decision (DEC-170 for the owner): on an Enterprise edition the application's read role should
be denied the Protected label, and IG to decide whether the text is also encrypted at rest.
"""

import secrets
from typing import Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    Scenario,
    SeedNode,
    TenantSeed,
)
from diucs.domain.errors import ValidationFailed

KINDS: Final = frozenset({"safety-concern", "problem-report", "clinical-note"})
MAX_LENGTH: Final = 280
HANDLE_BYTES: Final = 16  # 128 bits; token_urlsafe(16) is 22 characters

# Scenarios (DEC-150). Both tenants hold the handle `h-1` and its text; the handle is looked up, so
# the two tenants' keys collide and only the tenant stamp keeps the texts apart.
_NODE_SERVICE: Final = SeedNode(
    "svc",
    ("Resource", "HealthcareService"),
    {
        "id": "svc-ucr-east",
        "key": "HealthcareService/svc-ucr-east",
        "active": True,
        "name": Marked("UCR East"),
    },
)
_NODE_TEXT: Final = SeedNode(
    "text",
    ("Protected", "ProtectedText"),
    {
        "handle": "h-1",
        "kind": "safety-concern",
        "aboutId": "task-1",
        "text": Marked("Board showed accepting"),
    },
)
_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-PROT-PUT": Scenario(
        "store a protected text under a new handle",
        seed=TenantSeed(nodes=(_NODE_SERVICE,)),
        params={
            "handle": "h-new",
            "kind": "safety-concern",
            "aboutId": "task-1",
            "text": "Board showed accepting but they were closed",
        },
        new=("handle", "kind", "aboutId", "text"),
        expect=Expect(
            rows=({"stored": 1},),
            nodes={"Protected": 1, "ProtectedText": 1},
        ),
    ),
    "Q-PROT-GET": Scenario(
        "read a protected text by its handle in the bound tenant",
        seed=TenantSeed(nodes=(_NODE_SERVICE, _NODE_TEXT)),
        params={"handle": "h-1"},
        lookup=("handle",),
        expect=Expect(rows=({"text": Marked("Board showed accepting")},)),
    ),
}

_QUERIES: Final[tuple[NamedQuery, ...]] = (
    NamedQuery(
        id="Q-PROT-PUT",
        cypher=(
            "CREATE (p:Protected:ProtectedText {handle: $handle, kind: $kind, aboutId: $aboutId, "
            "text: $text, createdAt: datetime({timezone: 'UTC'}), tenantId: $tenant}) "
            "RETURN count(p) AS stored"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-PROT-PUT"],
    ),
    NamedQuery(
        id="Q-PROT-GET",
        cypher=(
            # No LIMIT: (tenantId, handle) is unique (migration 0040), so the tenant's own node is
            # the only row. A LIMIT would hide a second row, so the generated test could not see
            # this statement reach another tenant's node when its tenant predicate is removed.
            "MATCH (p:Protected:ProtectedText {handle: $handle, tenantId: $tenant}) "
            "RETURN p.text AS text"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-PROT-GET"],
    ),
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in _QUERIES:
    _register(_query)


def new_handle() -> str:
    """A random URL-safe token of 128 bits (22 characters)."""
    return secrets.token_urlsafe(HANDLE_BYTES)


def checked_text(text: str) -> str:
    """The text as stored, if it is not blank and at most 280 characters. The refusal never echoes
    the text."""
    if not isinstance(text, str) or not text.strip():
        raise ValidationFailed("text", "is required")
    if len(text) > MAX_LENGTH:
        raise ValidationFailed("text", f"must be at most {MAX_LENGTH} characters")
    return text


class Neo4jProtectedTextStore:
    """Protected text. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def put(self, kind: str, about_id: str, text: str) -> str:
        if kind not in KINDS:
            raise ValidationFailed(
                "kind", "must be safety-concern, problem-report or clinical-note"
            )
        if not isinstance(about_id, str) or not about_id.strip():
            raise ValidationFailed("aboutId", "is required")
        checked = checked_text(text)
        handle = new_handle()
        await run_query(
            self._tx,
            REGISTRY.get("Q-PROT-PUT"),
            handle=handle,
            kind=kind,
            aboutId=about_id,
            text=checked,
        )
        return handle

    async def get(self, handle: str) -> str | None:
        if not isinstance(handle, str) or not handle:
            return None
        rows = await run_query(self._tx, REGISTRY.get("Q-PROT-GET"), handle=handle)
        if not rows or rows[0]["text"] is None:
            return None
        return str(rows[0]["text"])
