"""Scope list management for the shift lead (U23).

STUB (red commit): the names exist so the unit tests fail on their assertions. The build follows in
the next commit.
"""

from dataclasses import dataclass
from datetime import date, datetime

from diucs.application.actor import Actor
from diucs.domain.codes import RegistrationStatus, ScopeFlag, ServiceCategory


@dataclass(frozen=True, slots=True)
class ScopeRow:
    service_id: str
    name: str
    category: ServiceCategory
    flag: ScopeFlag
    reason: str
    registration_status: RegistrationStatus | None


def require_lead(actor: Actor) -> None:
    raise NotImplementedError


def check_reason(flag: ScopeFlag, reason: str) -> str:
    raise NotImplementedError


def same_name(first: str, second: str) -> bool:
    raise NotImplementedError


def london_date(now: datetime) -> date:
    raise NotImplementedError


def scope_sort_key(row: ScopeRow) -> tuple[int, str, str]:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class AddScopeEntryCommand:
    idempotency_key: str
    actor: Actor
    name: str
    category: ServiceCategory
    flag: ScopeFlag
    reason: str = ""


@dataclass(frozen=True, slots=True)
class AddScopeEntryResult:
    service_id: str


class AddScopeEntry:
    def __init__(
        self, uow_factory: object, idempotency: object, ids: object, clock: object
    ) -> None:
        raise NotImplementedError

    async def execute(self, command: AddScopeEntryCommand) -> AddScopeEntryResult:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SetScopeFlagCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    flag: ScopeFlag
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SetScopeFlagResult:
    service_id: str
    flag: ScopeFlag


class SetScopeFlag:
    def __init__(self, uow_factory: object, idempotency: object, clock: object) -> None:
        raise NotImplementedError

    async def execute(self, command: SetScopeFlagCommand) -> SetScopeFlagResult:
        raise NotImplementedError


class ListScope:
    def __init__(self, uow_factory: object) -> None:
        raise NotImplementedError

    async def execute(self, actor: Actor) -> tuple[ScopeRow, ...]:
        raise NotImplementedError
