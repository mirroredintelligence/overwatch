"""Registration and scope-list records (P13). Red-commit stub: fields only, no checks yet."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from diucs.domain.codes import RegistrationStatus, ScopeFlag, ServiceCategory
from diucs.domain.rules.registration import ApprovalChecks


@dataclass(frozen=True, slots=True)
class Registration:
    id: str
    service_id: str
    status: RegistrationStatus
    requester_role_id: str | None
    owner_role_id: str | None
    created_at: datetime
    last_modified: datetime
    submitted_at: datetime | None = None
    draft: dict[str, dict[str, Any]] = field(default_factory=dict)
    checks: ApprovalChecks = ApprovalChecks(False, False, None, False)
    note: str = ""


@dataclass(frozen=True, slots=True)
class ScopeEntry:
    service_id: str
    name: str
    category: ServiceCategory
    flag: ScopeFlag
    date: date
    reason: str = ""
