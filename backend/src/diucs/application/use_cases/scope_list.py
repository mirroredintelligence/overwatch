"""Scope list management for the shift lead (U23).

The pilot's curated list of services, each flagged in pilot, later or out of scope. Invitations
(U24) may be made only for an entry flagged in pilot. Adding an entry creates the service as an
inactive placeholder (DEC-082 item 4, done by the scope list repository's save_entry); the
placeholder carries the name and the category only, and registration fills in the rest.

Every change is one unit of work with its audit entry, and carries the before and after flags.
Changing a flag away from in-pilot does not touch a live service; it only blocks new invitations
(domain-rules, U23 [ASSUMED]).
"""

import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.domain.codes import RegistrationStatus, Role, ScopeFlag, ServiceCategory
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.registration import ScopeEntry
from diucs.domain.rules.london_time import to_london

ADD_ACTION: Final = "C"
CHANGE_ACTION: Final = "U"
FLAG_ORDER: Final[dict[ScopeFlag, int]] = {
    ScopeFlag.IN_PILOT: 0,
    ScopeFlag.LATER: 1,
    ScopeFlag.OUT_OF_SCOPE: 2,
}


@dataclass(frozen=True, slots=True)
class ScopeRow:
    service_id: str
    name: str
    category: ServiceCategory
    flag: ScopeFlag
    reason: str
    registration_status: RegistrationStatus | None


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


@dataclass(frozen=True, slots=True)
class _AddStored:
    """An add's result with the fingerprint of the command that made it (DEC-104)."""

    fingerprint: str
    result: AddScopeEntryResult


@dataclass(frozen=True, slots=True)
class _SetStored:
    """A flag change's result with the fingerprint of the command that made it (DEC-104)."""

    fingerprint: str
    result: SetScopeFlagResult


def require_lead(actor: Actor) -> None:
    """Only the shift lead reads or changes the scope list (U23)."""
    if actor.role is not Role.LEAD:
        raise NotAllowed("only the shift lead may change the scope list")


def check_reason(flag: ScopeFlag, reason: str) -> str:
    """The reason, trimmed. A flag other than in-pilot needs one (U23)."""
    if not isinstance(flag, ScopeFlag):
        raise ValidationFailed("flag", "must be a scope flag")
    if not isinstance(reason, str):
        raise ValidationFailed("reason", "must be text")
    trimmed = reason.strip()
    if flag is not ScopeFlag.IN_PILOT and not trimmed:
        raise ValidationFailed("reason", "is required unless the service is in the pilot")
    return trimmed


def _name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValidationFailed("name", "is required")
    return " ".join(name.split())


def same_name(first: str, second: str) -> bool:
    """Two names are the same when they differ only in case and in spacing."""
    return " ".join(first.split()).casefold() == " ".join(second.split()).casefold()


def london_date(now: datetime) -> date:
    """The London calendar date of an instant: the date an entry is flagged on."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValidationFailed("now", "must be a timezone-aware datetime")
    return to_london(now).date()


def scope_sort_key(row: ScopeRow) -> tuple[int, str, str]:
    """In-pilot first, then later, then out of scope; then by name, then by service id."""
    return (FLAG_ORDER[row.flag], row.name.casefold(), row.service_id)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _checked(fingerprint: str, stored_fingerprint: str) -> None:
    if stored_fingerprint != fingerprint:
        raise Conflict("this command key was used for a different change")


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    """The tenant of this unit of work: one scope list per tenant (TEN-011, DEC-170)."""
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _key(operation: str, scope: ScopeId, key: str) -> str:
    """The replay key, named by operation and tenant (lesson L160)."""
    return f"scope-list:{operation}:{scope}:{key}"


class AddScopeEntry:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._ids = ids
        self._clock = clock

    async def execute(self, command: AddScopeEntryCommand) -> AddScopeEntryResult:
        require_lead(command.actor)
        name = _name(command.name)
        if not isinstance(command.category, ServiceCategory):
            raise ValidationFailed("category", "must be a service category")
        reason = check_reason(command.flag, command.reason)
        fingerprint = _fingerprint(name, command.category.value, command.flag.value, reason)
        early = await self._idempotency.get(_key("add", current_scope(), command.idempotency_key))
        if isinstance(early, _AddStored):
            _checked(fingerprint, early.fingerprint)
            return early.result

        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = _key("add", scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _AddStored):
                _checked(fingerprint, stored.fingerprint)
                return stored.result

            for entry in await uow.scope.entries():
                if same_name(entry.name, name):
                    raise Conflict("a service with this name is already on the scope list")
            service_id = self._ids.new_id()
            await uow.scope.save_entry(
                ScopeEntry(
                    service_id=service_id,
                    name=name,
                    category=command.category,
                    flag=command.flag,
                    date=london_date(now),
                    reason=reason,
                )
            )
            result = AddScopeEntryResult(service_id=service_id)
            await uow.audit.append(
                AuditEntry(
                    action=ADD_ACTION,
                    use_case="AddScopeEntry",
                    actor=command.actor,
                    entity_ids=(service_id,),
                    snapshot={
                        "service_id": service_id,
                        "before": None,
                        "after": command.flag.value,
                        "reason": reason,
                    },
                    at=now,
                )
            )
            await uow.idempotency.put(key, _AddStored(fingerprint, result))
            await uow.commit()
        return result


class SetScopeFlag:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, idempotency: IdempotencyStore, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock

    async def execute(self, command: SetScopeFlagCommand) -> SetScopeFlagResult:
        require_lead(command.actor)
        reason = check_reason(command.flag, command.reason)
        fingerprint = _fingerprint(command.service_id, command.flag.value, reason)
        early = await self._idempotency.get(_key("set", current_scope(), command.idempotency_key))
        if isinstance(early, _SetStored):
            _checked(fingerprint, early.fingerprint)
            return early.result

        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = _key("set", scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _SetStored):
                _checked(fingerprint, stored.fingerprint)
                return stored.result

            entry = await uow.scope.get_entry(command.service_id)
            if entry is None:
                raise NotFound("no scope entry for this service")
            before = entry.flag
            await uow.scope.save_entry(
                replace(entry, flag=command.flag, reason=reason, date=london_date(now))
            )
            result = SetScopeFlagResult(service_id=command.service_id, flag=command.flag)
            await uow.audit.append(
                AuditEntry(
                    action=CHANGE_ACTION,
                    use_case="SetScopeFlag",
                    actor=command.actor,
                    entity_ids=(command.service_id,),
                    snapshot={
                        "service_id": command.service_id,
                        "before": before.value,
                        "after": command.flag.value,
                        "reason": reason,
                    },
                    at=now,
                )
            )
            await uow.idempotency.put(key, _SetStored(fingerprint, result))
            await uow.commit()
        return result


class ListScope:
    """The scope list with each service's latest registration status (read only)."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor) -> tuple[ScopeRow, ...]:
        require_lead(actor)
        rows: list[ScopeRow] = []
        async with self._uow_factory() as uow:
            await _append_rows(uow, rows)
        return tuple(sorted(rows, key=scope_sort_key))


async def _append_rows(uow: UnitOfWork, rows: list[ScopeRow]) -> None:
    for entry in await uow.scope.entries():
        # The newest registration first. A service with none has no status yet, shown as None.
        registrations = await uow.registrations.for_service(entry.service_id)
        status = registrations[0].status if registrations else None
        rows.append(
            ScopeRow(
                service_id=entry.service_id,
                name=entry.name,
                category=entry.category,
                flag=entry.flag,
                reason=entry.reason,
                registration_status=status,
            )
        )
