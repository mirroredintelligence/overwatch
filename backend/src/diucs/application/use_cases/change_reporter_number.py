"""ChangeReporterNumber: point a service's reports at a new mobile, for cover or until changed.

A shift lead names a service and a new mobile, and a duration. For `today` or `this-week` the
service's reporter role is covered by the new number's practitioner until 23:59 London on the last
day of the period (domain-rules 2.4). Replies from the original phone for that service are then not
routed to it, because the role is covered out of that phone (services_for_phone_hash). For
`until-changed` the old role ends now and a new active role is created for the new practitioner.

Cover is stored on the role (COVERED_BY with `until`). The change, its audit entry and the
idempotency record are written in one unit of work (DEC-106). Both numbers appear only as keyed
hashes (P10); the command's number is never stored, logged or echoed.

Decisions: the choices the prompt leaves open are recorded in the U16 fragment.
"""

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore, format_instant
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher, normalise_uk_mobile
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole, is_in_effect, role_holder

LONDON: Final = ZoneInfo("Europe/London")
COVER_ENDS_AT: Final = time(23, 59)
"""A cover ends at 23:59 London on its last day, the rule in domain-rules 2.4 (U16)."""
WEEK_LAST_DAY: Final = 6
"""Monday is weekday 0 and Sunday is weekday 6 (datetime.weekday), so 'this week' ends on 6."""
AUDIT_ACTION: Final = "U"
USE_CASE: Final = "ChangeReporterNumber"
NEW_REPORTER_NAME: Final = "Reporter"
"""The name of a practitioner created for a new mobile. The number is the only thing known about
them; the name is set later by the person (U16 choice, recorded in the fragment)."""


class CoverDuration(StrEnum):
    TODAY = "today"
    THIS_WEEK = "this-week"
    UNTIL_CHANGED = "until-changed"


@dataclass(frozen=True, slots=True)
class ChangeReporterNumberCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    new_mobile: str
    duration: CoverDuration


@dataclass(frozen=True, slots=True)
class ChangeReporterNumberResult:
    role_id: str
    """The role whose reports now go to the new mobile: the covered role, or the new role."""
    covered_until: datetime | None
    """The instant the cover ends, in UTC; None for until-changed."""


@dataclass(frozen=True, slots=True)
class _StoredChange:
    """What the idempotency store keeps for a command key: the result and the fingerprint of the
    command that made it (DEC-104)."""

    fingerprint: str
    result: ChangeReporterNumberResult


def _aware(field: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be a timezone-aware datetime")


def cover_until(duration: CoverDuration, now: datetime) -> datetime | None:
    """The instant a cover ends, in UTC, or None for until-changed.

    `today` ends at 23:59 London on the London date of `now`. `this-week` ends at 23:59 London on
    the Sunday of that Monday-to-Sunday week. A cover whose end is not after `now` is already over,
    and is refused, so nothing is written for it.
    """
    if not isinstance(duration, CoverDuration):
        raise ValidationFailed("duration", "must be today, this-week or until-changed")
    _aware("now", now)
    if duration is CoverDuration.UNTIL_CHANGED:
        return None
    local = now.astimezone(LONDON)
    if duration is CoverDuration.TODAY:
        last_day = local.date()
    else:
        last_day = local.date() + timedelta(days=WEEK_LAST_DAY - local.weekday())
    # Wall-clock time on the London date, converted to an instant (lesson L4: a 23:59 end never
    # falls in the 01:00 to 02:00 change hour).
    until = datetime.combine(last_day, COVER_ENDS_AT, tzinfo=LONDON).astimezone(UTC)
    if now.astimezone(UTC) >= until:
        raise ValidationFailed("duration", "has already ended")
    return until


def effective_reporter_practitioner_id(role: PractitionerRole, now: datetime) -> str:
    """The practitioner whose phone gets this role's prompts at `now`: the cover while the cover
    runs, otherwise the role's own practitioner (domain-rules 2.4, the rule in role_holder)."""
    return role_holder(role, now)


def check_new_mobile(number: str) -> str:
    """The national form of a UK mobile, or ValidationFailed on the field new_mobile. The number is
    never echoed in the message."""
    try:
        return normalise_uk_mobile(number)
    except ValidationFailed:
        raise ValidationFailed(
            "new_mobile", "must be a UK mobile number, like 07700 900123"
        ) from None


def command_key(scope: ScopeId, key: str) -> str:
    """The replay key. Replay statements are not tenant-scoped yet (lesson L160), so the tenant is
    part of the key: two tenants that use one key never share a result."""
    return f"change-reporter:{scope}:{key}"


def _fingerprint(command: ChangeReporterNumberCommand, new_hash: str) -> str:
    body = repr(
        (
            command.service_id,
            new_hash,
            command.duration.value,
            command.actor.role.value,
            command.actor.practitioner_id,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _replay(stored: _StoredChange, fingerprint: str) -> ChangeReporterNumberResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different change")
    return stored.result


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    """The tenant this unit of work is bound to. Nothing bound, or a network scope, is refused: a
    reporter's number belongs to one tenant (DEC-130, DEC-132 item 5)."""
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


class ChangeReporterNumber:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        phone_hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._hasher = phone_hasher

    async def execute(self, command: ChangeReporterNumberCommand) -> ChangeReporterNumberResult:
        if command.actor.role is not Role.LEAD:
            raise NotAllowed("only the shift lead may change a reporter's number")
        if not isinstance(command.duration, CoverDuration):
            raise ValidationFailed("duration", "must be today, this-week or until-changed")
        new_mobile = check_new_mobile(command.new_mobile)
        new_hash = self._hasher.hash(new_mobile)
        fingerprint = _fingerprint(command, new_hash)
        # An early replay check on the bound tenant's key. The authoritative check is inside the
        # unit of work, before any write (DEC-106 item 2).
        early = await self._idempotency.get(command_key(current_scope(), command.idempotency_key))
        if isinstance(early, _StoredChange):
            return _replay(early, fingerprint)

        now = self._clock.now()
        until = cover_until(command.duration, now)

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = command_key(scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _StoredChange):
                return _replay(stored, fingerprint)

            profile = await uow.services.get(command.service_id)
            if profile is None:
                raise NotFound("no service with this id")
            roles = await uow.people.reporter_roles_for_service(profile.id, now)
            active = [role for role in roles if is_in_effect(role, now)]
            if not active:
                raise NotFound("this service has no reporter to change")
            # A service with several reporter roles changes the first by role id; the rest keep
            # their numbers (U16 choice, recorded in the fragment).
            role = min(active, key=lambda candidate: candidate.id)

            old = await uow.people.get_practitioner(role.practitioner_id)
            if old is None:
                raise NotFound("the reporter of this service")
            new = await uow.people.find_by_phone_hash(new_hash)
            if new is not None and new.id == old.id:
                raise ValidationFailed("new_mobile", "is already this service's reporter number")
            if new is None:
                new = Practitioner(
                    id=self._ids.new_id(),
                    active=True,
                    display_name=NEW_REPORTER_NAME,
                    phone_hash=new_hash,
                )
                await uow.people.save_practitioner(new)

            if until is None:
                # until-changed: the old role ends now, and a new role starts for the new number.
                await uow.people.save_role(replace(role, active=False, period_end=now))
                successor = PractitionerRole(
                    id=self._ids.new_id(),
                    practitioner_id=new.id,
                    service_id=role.service_id,
                    code=role.code,
                    active=True,
                    channel=role.channel,
                    period_start=now,
                )
                await uow.people.save_role(successor)
                role_id = successor.id
            else:
                # today or this-week: the role is covered by the new practitioner until `until`.
                await uow.people.save_role(
                    replace(role, covered_by_practitioner_id=new.id, covered_until=until)
                )
                role_id = role.id

            result = ChangeReporterNumberResult(role_id=role_id, covered_until=until)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=command.actor,
                    entity_ids=(role_id, profile.id),
                    snapshot={
                        "service_id": profile.id,
                        "old_phone_hash": old.phone_hash,
                        "new_phone_hash": new_hash,
                        "duration": command.duration.value,
                        "covered_until": None if until is None else format_instant(until),
                    },
                    at=now,
                )
            )
            await uow.idempotency.put(key, _StoredChange(fingerprint, result))
            await uow.commit()
        return result
