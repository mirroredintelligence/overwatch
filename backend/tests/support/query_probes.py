"""The generated two-tenant isolation test over the query registry (TEN-004, DEC-142, DEC-150).

STUB (DEC-010, red commit): the data tables and the types exist; the functions raise
NotImplementedError.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery, QueryRegistry
from diucs.adapters.outbound.graph_store.scenario import Expect, Slot
from tests.support.tenant_seed import Snapshot

# The 126 ids on the ratchet when TEN-004 was built (TEN-001 measured it). Never edited again. The
# live ratchet (graph_store/unconverted.py) may only shrink and may only hold ids from this list.
INITIAL_UNCONVERTED: Final[frozenset[str]] = frozenset(
    {
        "Q-AUDIT-APPEND",
        "Q-AUDIT-CHAIN",
        "Q-AUDIT-ENSURE-HEAD",
        "Q-AUDIT-HEAD",
        "Q-AUDIT-LINK-AGENT",
        "Q-AUDIT-LINK-ENTITY",
        "Q-AUDIT-LIST",
        "Q-AUDIT-LOCK-HEAD",
        "Q-BOOK-BY-REF",
        "Q-BOOK-CONFIRMED-FOR",
        "Q-BOOK-CONFIRMED-SINCE",
        "Q-BOOK-OPEN-FOR",
        "Q-BOOK-PENDING",
        "Q-BOOK-SET-PROPS",
        "Q-CAP-LATEST",
        "Q-CAP-LATEST-CONFIRMED-AT",
        "Q-CAP-LATEST-FOR",
        "Q-CAP-LOCK-SERVICE",
        "Q-CAP-SINCE",
        "Q-CAP-TRAILING-CONFIRMS",
        "Q-CASE-BY-REF",
        "Q-CASE-READ-POSTCODE",
        "Q-CASE-SET-POSTCODE",
        "Q-CASE-SET-REFERENCE",
        "Q-COMM-ADD",
        "Q-COMM-BY-PROVIDER",
        "Q-COMM-EXISTS",
        "Q-COMM-GET",
        "Q-COMM-LATEST-PROMPT",
        "Q-COMM-LINK-ABOUT",
        "Q-COMM-LINK-RECIPIENT",
        "Q-COMM-LINK-REPLY",
        "Q-COMM-SET-STATUS",
        "Q-CONTACT-GET",
        "Q-CONTACT-PUT",
        "Q-CRED-CLEAR",
        "Q-CRED-GET",
        "Q-CRED-PRACTITIONER-EXISTS",
        "Q-CRED-SAVE-STATE",
        "Q-CRED-SET",
        "Q-CRIT-CLEAR-CURRENT",
        "Q-CRIT-CURRENT",
        "Q-CRIT-CURRENT-FOR",
        "Q-CRIT-LABEL",
        "Q-CRIT-LOCK-SERVICE",
        "Q-CRIT-SET-CURRENT",
        "Q-CRIT-SUBJECT",
        "Q-CRIT-VERSIONS",
        "Q-DEVICE-KNOWN",
        "Q-DEVICE-LOCK",
        "Q-DEVICE-OWNER",
        "Q-DEVICE-REGISTER",
        "Q-DEVICE-REVOKE",
        "Q-FLAG-BASIC-STATE",
        "Q-FLAG-LABEL",
        "Q-FLAG-OBS-LOCK",
        "Q-FLAG-OBS-SERVICE",
        "Q-FLAG-REPORT-ADD",
        "Q-FLAG-REPORT-EXISTS",
        "Q-FLAG-REPORT-GET",
        "Q-FLAG-REPORT-LOCK",
        "Q-FLAG-REPORT-OPEN",
        "Q-FLAG-REPORT-SAVE",
        "Q-FLAG-SERVICE-ACTIVE",
        "Q-FLAG-SERVICE-LOCK",
        "Q-FLAG-SERVICES-WITH",
        "Q-IDEM-CREATE",
        "Q-IDEM-EDGES",
        "Q-IDEM-HEAD",
        "Q-IDEM-LINK",
        "Q-IDEM-VALUES",
        "Q-LINK-ADD",
        "Q-LINK-BURN-KEY",
        "Q-LINK-GET",
        "Q-LINK-MARK-USED",
        "Q-OUTBOX-ADD",
        "Q-OUTBOX-FAILED",
        "Q-OUTBOX-LOCK",
        "Q-OUTBOX-PENDING",
        "Q-OUTBOX-PUBLISHED",
        "Q-PERSON-PHONE-FIND",
        "Q-PERSON-ROLES-OF",
        "Q-PERSON-SET-PROPS",
        "Q-PHONE-SERVICES-AT",
        "Q-PHONE-SERVICES-HELD",
        "Q-PROCESSED-MARK",
        "Q-PROV-APPEND",
        "Q-PROV-LINK",
        "Q-PROV-SOURCE",
        "Q-REG-BY-STATUS",
        "Q-REG-DRAFT-ADD",
        "Q-REG-DRAFT-CLEAR",
        "Q-REG-DRAFT-FOR",
        "Q-REG-FOR-SERVICE",
        "Q-REG-SET-PROPS",
        "Q-RES-CLEAR-OWNED",
        "Q-RES-CLEAR-ROOT-RELS",
        "Q-RES-GET",
        "Q-RES-HISTORY",
        "Q-RES-IDEM-GET",
        "Q-RES-IDEM-RECORD",
        "Q-RES-LOAD-NODES",
        "Q-RES-LOAD-RELS",
        "Q-RES-LOCK",
        "Q-RES-MERGE-NODES",
        "Q-RES-MERGE-RELS",
        "Q-RES-SET-POSITION",
        "Q-RES-SHARED-CREATE",
        "Q-RES-SHARED-FILL",
        "Q-RES-SHARED-READ",
        "Q-RES-UPSERT-NODE",
        "Q-RES-UPSERT-ROOT",
        "Q-ROLE-CHANNEL",
        "Q-ROLE-COVER",
        "Q-SCOPE-ENSURE-LIST",
        "Q-SCOPE-ENTRIES",
        "Q-SCOPE-ENTRY-FOR",
        "Q-SCOPE-LOCK-LIST",
        "Q-SCOPE-UPSERT-ENTRY",
        "Q-SERVICE-REPORTER-ROLES",
        "Q-SVC-LAST-REPORT",
        "Q-SVC-LIST-ACTIVE",
        "Q-WORK-ADD",
        "Q-WORK-FOR-ABOUT",
        "Q-WORK-GET",
        "Q-WORK-SAVE",
    }
)


class FindingKind(StrEnum):
    ROWS_DIFFER = "rows-differ"
    OWN_STATE_DIFFERS = "own-state-differs"
    OTHER_TENANT_CHANGED = "other-tenant-changed"
    UNSTAMPED_NODE = "unstamped-node"
    CROSS_SCOPE_RELATIONSHIP = "cross-scope-relationship"
    FOREIGN_ID_EFFECT = "foreign-id-effect"
    UNEXPECTED_ROWS = "unexpected-rows"
    UNEXPECTED_EFFECT = "unexpected-effect"
    PROBE_ERROR = "probe-error"


@dataclass(frozen=True, slots=True)
class Finding:
    query_id: str
    phase: str
    kind: FindingKind
    detail: str


def normalised(rows: list[dict[str, Any]]) -> list[str]:
    raise NotImplementedError


def row_problems(
    expected: tuple[Mapping[str, Any], ...], actual: list[dict[str, Any]], slot: Slot
) -> list[str]:
    raise NotImplementedError


def effect_problems(before: Snapshot, after: Snapshot, expect: Expect, slot: Slot) -> list[str]:
    raise NotImplementedError


def production_statements(registry: QueryRegistry = REGISTRY) -> dict[str, NamedQuery]:
    raise NotImplementedError


def scenario_gaps(statements: Mapping[str, NamedQuery], unconverted: frozenset[str]) -> list[str]:
    raise NotImplementedError


def ratchet_problems(
    statements: Mapping[str, NamedQuery], unconverted: frozenset[str], initial: frozenset[str]
) -> list[str]:
    raise NotImplementedError


async def run_isolation(
    driver: AsyncDriver,
    statements: Mapping[str, NamedQuery],
    *,
    registry: QueryRegistry,
    tenant_a: str,
    tenant_b: str,
) -> list[Finding]:
    raise NotImplementedError


def format_findings(findings: list[Finding]) -> str:
    raise NotImplementedError
