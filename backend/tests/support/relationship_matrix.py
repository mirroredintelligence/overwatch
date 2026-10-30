"""The relationship matrix of the cross-tenant reference test (TEN-029).

A relationship is in the scope of the two nodes it joins, and no query joins two scopes (DEC-130
item 1). The matrix lists every relationship type the graph store writes by name and says what the
entry point that writes it does when the caller names a record that belongs to another tenant:

- `CHECKED`: the entry point looks the target up in the bound tenant first and refuses an unknown
  one with `NotFound`, before it writes. A foreign id is an unknown id, so the refusal must read
  the same as for an id that exists nowhere (`shape`), and nothing may be written. The integration
  test runs each case of the matrix (`integration/graph_store/test_cross_tenant_references.py`).
- `PLACEHOLDER`: the entry point writes through the resource store, which creates a placeholder
  node in the bound tenant for an id it does not know (DEC-053 item 8). A foreign id is unknown in
  the bound tenant, so the placeholder is the tenant's own and nothing links across. It is not
  refused: the integration test proves the tenant-local result, and the refusal the audit asks for
  (F 3.4 item 1) is a known issue (DEC-272, known issues).
- `TENANT_LOCAL`: every node of the statement is matched or merged on `tenantId: $tenant`, so the
  statement cannot reach a foreign node. The generated two-tenant test (TEN-004) proves this for
  every registered statement.
- `SHARED`: the target is shared reference data, a `Concept` (DEC-130 item 5).
- `REGISTRY`: the platform's own registry nodes, which carry no `tenantId` (DEC-132).

`written_types` reads the Cypher text of the graph store, so a new relationship type that is not in
the table fails the unit test that completes it. Test code only.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

_STORE: Final = Path(__file__).resolve().parents[2] / "src/diucs/adapters/outbound/graph_store"
_TYPE_IN_PATTERN: Final = re.compile(r"\[[a-z_]*:([A-Z][A-Z_]*(?:\|[A-Z][A-Z_]*)*)")
ID_PLACEHOLDER: Final = "<id>"


class Handling(StrEnum):
    CHECKED = "checked"
    PLACEHOLDER = "placeholder"
    TENANT_LOCAL = "tenant-local"
    SHARED = "shared"
    REGISTRY = "registry"


@dataclass(frozen=True, slots=True)
class Relationship:
    """One relationship type. `cases` are the integration cases of a `CHECKED` entry, each named
    `<area>.<entry point>.<argument>`. `literal` is false for a type the store derives from a FHIR
    reference instead of writing it by name."""

    type: str
    handling: Handling
    literal: bool = True
    cases: tuple[str, ...] = ()
    note: str = ""


def _checked(type_: str, *cases: str) -> Relationship:
    return Relationship(type_, Handling.CHECKED, cases=cases)


def _local(type_: str, note: str = "") -> Relationship:
    return Relationship(type_, Handling.TENANT_LOCAL, note=note)


def _shared(type_: str) -> Relationship:
    return Relationship(type_, Handling.SHARED, note="the target is a Concept (DEC-130 item 5)")


_RESOURCE_STORE_PLACEHOLDER: Final = (
    "written through the resource store, which makes a placeholder in the bound tenant for an id "
    "it does not hold (DEC-053 item 8)"
)

RELATIONSHIPS: Final = (
    _local("ABOUT", "a communication or a piece of scheduled work about a record of the tenant"),
    _shared("ACCEPTS_NEED"),
    _shared("CHANNEL"),
    _shared("CODE"),
    _local("CONTACT", "an alert subscription checks its practitioner (NotFound) before it writes"),
    _checked("COVERED_BY", "person.save_role.cover"),
    _local("CURRENT_CRITERIA", "a criteria version checks its service (NotFound) before it writes"),
    _local("DRAFT_OF"),
    Relationship(
        "ENTRY",
        Handling.PLACEHOLDER,
        note="a scope entry for an unknown service makes the tenant's own minimal service",
    ),
    _shared("EXCLUDES_NEED"),
    _checked("FOCUS", "capacity.add.service"),
    _checked("FOR", "move.add.service"),
    _checked("FROM", "move.add.practitioner"),
    _local("FOR_SESSION", "a support ticket to the session it is about, both on the tenant"),
    _local("HAS_CREDENTIAL"),
    _local("HAS_DEVICE"),
    _local(
        "HAS_LOCATION", "a projected service to its location, both in one network scope (TEN-053)"
    ),
    Relationship(
        "HAS_NUMBER",
        Handling.REGISTRY,
        note="a Tenant registry node to its TenantNumber, neither carries a tenantId (DEC-132)",
    ),
    _local(
        "HAS_OPENING_HOUR",
        "a projected service to each opening window, both in one network scope (TEN-053)",
    ),
    _local("HAS_OUTPUT"),
    _local("HAS_SETTING"),
    _local("HAS_VALUE"),
    _local("HAS_VERSION"),
    _checked("HEALTHCARE_SERVICE", "person.save_role.service"),
    _local("IN_RESPONSE_TO", "a reply checks the communication it answers (NotFound)"),
    _local(
        "LOCATION",
        "a read of a service position: the service and its place are both matched on the tenant",
    ),
    _shared("MEDIUM"),
    _local("MEMBER"),
    _checked("ON", "flag.add_report_flag.report"),
    _local("OPENED"),
    _local("OPENED_BY"),
    Relationship("OWNER", Handling.PLACEHOLDER, note=_RESOURCE_STORE_PLACEHOLDER),
    _checked("PRACTITIONER", "person.save_role.practitioner"),
    _local("RECIPIENT"),
    _local("SHARED_BY"),
    _local("SHARED_VIA"),
    _checked("SUBJECT", "flag.set_service_flag.service"),
    _local("SUPERSEDES", "a criteria version checks the version it supersedes (NotFound)"),
    _shared("TOPIC"),
    _shared("TYPE"),
    _checked("USED_BY", "push.save.practitioner"),
)


def written_types(root: Path | None = None) -> frozenset[str]:
    """Every relationship type the Cypher text of the graph store names."""
    found: set[str] = set()
    for path in sorted((root or _STORE).glob("*.py")):
        for match in _TYPE_IN_PATTERN.finditer(path.read_text(encoding="utf-8")):
            found.update(match.group(1).split("|"))
    return frozenset(found)


def checked_cases() -> dict[str, str]:
    """Each case of the matrix and the relationship type it covers."""
    return {case: entry.type for entry in RELATIONSHIPS for case in entry.cases}


def shape(error: Exception, *ids: str) -> str:
    """The message of a refusal with the ids the caller named taken out, so that a refusal for an
    id held by another tenant and one for an id held by nobody can be compared."""
    text = str(error)
    for identifier in sorted(ids, key=len, reverse=True):
        text = text.replace(identifier, ID_PLACEHOLDER)
    return text
