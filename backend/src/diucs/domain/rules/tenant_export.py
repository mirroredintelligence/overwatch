"""What a tenant's export package holds, and its manifest (TEN-074, DEC-136 item 10, audit F 2.4).

A tenant is the controller of its own data, so when it leaves it is given what the platform holds
for it, class by class, with a manifest that says what is in each file and the hash of each, so the
tenant can check it arrived whole (and the operator can show later what was handed over).

The package is built from the labels of the tenant's own scope. Every label a statement of the graph
store names is in exactly one place here: a data class (exported), the set that is held back unless
the tenant asks (the protected contacts and the protected text of a safety concern), or the set that
is never exported (credentials and token hashes, the sign-in and idempotency bookkeeping, the
outbox and the scheduled work: nothing a person could use, and nothing that is the tenant's record).
A label set that none of them names is `UnclassifiedData` and the export refuses: a package that
quietly leaves a class out is worse than no package. A test keeps the table equal to the labels the
registered statements name, so a new label cannot be added without a decision about it.

Pure: classification and the manifest's bytes, no I/O. Standard library and `diucs.domain` only.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final


class ExportClass(StrEnum):
    DIRECTORY_AND_CRITERIA = "directory-and-criteria"
    CAPACITY_REPORTS = "capacity-reports"
    REGISTRATIONS = "registrations"
    COMMUNICATIONS = "communications"
    CASES_AND_REQUESTS = "cases-and-requests"
    PEOPLE = "people"
    ALERTS_AND_FLAGS = "alerts-and-flags"
    CONFIGURATION = "configuration"
    TELEMETRY = "telemetry"
    SUPPORT = "support"
    AUDIT_CHAIN = "audit-chain"
    PROTECTED = "protected"  # only when the tenant asks


_C = ExportClass
CLASS_OF_LABEL: Final[Mapping[str, ExportClass]] = MappingProxyType(
    {
        # the service directory, its criteria and what hangs off a service
        "Resource": _C.DIRECTORY_AND_CRITERIA,
        "ResourceVersion": _C.DIRECTORY_AND_CRITERIA,
        "HealthcareService": _C.DIRECTORY_AND_CRITERIA,
        "Location": _C.DIRECTORY_AND_CRITERIA,
        "ServiceCriteria": _C.DIRECTORY_AND_CRITERIA,
        "Basic": _C.DIRECTORY_AND_CRITERIA,
        "List": _C.DIRECTORY_AND_CRITERIA,
        "Concept": _C.DIRECTORY_AND_CRITERIA,
        "CodeSystem": _C.DIRECTORY_AND_CRITERIA,
        "Identifier": _C.DIRECTORY_AND_CRITERIA,
        "ServiceFlag": _C.DIRECTORY_AND_CRITERIA,
        "ServiceMove": _C.DIRECTORY_AND_CRITERIA,
        "Observation": _C.CAPACITY_REPORTS,
        "RegistrationDraftField": _C.REGISTRATIONS,
        "Provenance": _C.REGISTRATIONS,
        "Communication": _C.COMMUNICATIONS,
        "PushSubscription": _C.COMMUNICATIONS,
        "Task": _C.CASES_AND_REQUESTS,
        "Task_Output": _C.CASES_AND_REQUESTS,
        "ServiceRequest": _C.CASES_AND_REQUESTS,
        "Patient": _C.CASES_AND_REQUESTS,
        "Practitioner": _C.PEOPLE,
        "PractitionerRole": _C.PEOPLE,
        "AlertSubscription": _C.ALERTS_AND_FLAGS,
        "ReportFlag": _C.ALERTS_AND_FLAGS,
        "SafetyCounter": _C.ALERTS_AND_FLAGS,
        "TenantConfigVersion": _C.CONFIGURATION,
        "TenantSetting": _C.CONFIGURATION,
        "TenantChannel": _C.CONFIGURATION,
        "TenantContact": _C.CONFIGURATION,
        "TenantEntraBinding": _C.CONFIGURATION,
        "TenantRetention": _C.CONFIGURATION,
        "TenantRoleMapping": _C.CONFIGURATION,
        "ElementUsageDaily": _C.TELEMETRY,
        "FrictionDaily": _C.TELEMETRY,
        "FunnelDaily": _C.TELEMETRY,
        "MeasureDaily": _C.TELEMETRY,
        "ReleaseDaily": _C.TELEMETRY,
        "QueryStatDaily": _C.TELEMETRY,
        "RouteDaily": _C.TELEMETRY,
        "SupportTicket": _C.SUPPORT,
        "AuditEvent": _C.AUDIT_CHAIN,
        "ChainLink": _C.AUDIT_CHAIN,
        "AuditHead": _C.AUDIT_CHAIN,
        "Snapshot": _C.AUDIT_CHAIN,
        "AuditRef": _C.AUDIT_CHAIN,
    }
)

# Held back unless the tenant asks: the controller's staff phone numbers and the text of a safety
# concern live in the protected stores, which are kept apart on purpose.
PROTECTED_LABELS: Final = frozenset({"Protected", "ProtectedContact", "ProtectedText"})

# Never exported: secret material and bookkeeping that is no one's record.
EXCLUDED_LABELS: Final = frozenset(
    {
        "Credential",  # PIN hashes and the like
        "Device",  # device tokens
        "LinkToken",  # token hashes
        "UiSession",
        "SupportCode",
        "TallySeen",  # keyed session markers of the insight counters: bookkeeping
        "SupportAccess",
        "IdempotencyRecord",
        "IdempotencyValue",
        "Processed",
        "OutboxMessage",
        "ScheduledWork",
    }
)


class UnclassifiedData(Exception):
    """A label set that no class names. The text is fixed and names no label of a person."""

    def __init__(self, labels: Sequence[str]) -> None:
        super().__init__("a kind of data has no export class")
        self.labels = tuple(labels)


class Handling(StrEnum):
    EXPORT = "export"
    PROTECTED = "protected"
    EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class Classified:
    handling: Handling
    export_class: ExportClass | None


def classify(labels: Sequence[str]) -> Classified:
    """How one label set is handled. Excluded wins over everything (a node that carries a
    credential label is never exported, whatever else it is), then protected, then the class of
    the first label that has one (a backbone element's label, `<Resource>_<Element>`, is classified
    by the resource it hangs off: `HealthcareService_AvailableTime` is a service's); no label with a
    place is `UnclassifiedData`."""
    names = tuple(labels)
    if any(name in EXCLUDED_LABELS for name in names):
        return Classified(Handling.EXCLUDED, None)
    if any(name in PROTECTED_LABELS for name in names):
        return Classified(Handling.PROTECTED, ExportClass.PROTECTED)
    for name in sorted(names):
        found = CLASS_OF_LABEL.get(name) or CLASS_OF_LABEL.get(name.partition("_")[0])
        if found is not None:
            return Classified(Handling.EXPORT, found)
    raise UnclassifiedData(names)


def file_name(export_class: ExportClass, labels: Sequence[str]) -> str:
    """The path of one label set's file inside the package: `<class>/<labels>.jsonl`."""
    return f"{export_class.value}/{'+'.join(sorted(labels))}.jsonl"


RELATIONSHIPS_FILE: Final = "relationships.jsonl"
MANIFEST_FILE: Final = "manifest.json"


def plain(value: Any) -> Any:
    """A property value as plain JSON: an instant as UTC text, a set as a sorted list; anything
    else a JSON value already."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, set | frozenset):
        return sorted(plain(item) for item in value)
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    return value


def jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """One JSON object per line, keys sorted, no spaces: the same rows are always the same bytes."""
    lines = [
        json.dumps(plain(dict(row)), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for row in rows
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


@dataclass(frozen=True, slots=True)
class FileEntry:
    name: str
    export_class: str
    rows: int
    sha256: str


def manifest_bytes(
    *,
    tenant_id: str,
    package_id: str,
    generated_at: datetime,
    files: Sequence[FileEntry],
    held_back: Mapping[str, int],
    excluded: Mapping[str, int],
    audit_last_hash: str | None,
    audit_last_seq: int | None,
    protected_included: bool,
) -> bytes:
    """The manifest: what is in each file and its hash, what was held back or left out (by label
    set and count, so the tenant can see that it exists), and the head of the audit chain at the
    time. Canonical JSON, so the same package always has the same manifest hash."""
    body = {
        "tenant": tenant_id,
        "package": package_id,
        "generated_at": plain(generated_at),
        "protected_included": protected_included,
        "audit_chain": {"last_hash": audit_last_hash, "last_seq": audit_last_seq},
        "files": [
            {
                "name": entry.name,
                "class": entry.export_class,
                "rows": entry.rows,
                "sha256": entry.sha256,
            }
            for entry in sorted(files, key=lambda item: item.name)
        ],
        "held_back": dict(sorted(held_back.items())),
        "excluded": dict(sorted(excluded.items())),
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
