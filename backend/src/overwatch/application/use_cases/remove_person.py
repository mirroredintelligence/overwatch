"""People-access use cases (U37): the lead removes a person, a person signs out of every phone, and
a reporter who lost a phone moves to a new one after a lead call-back.

Authentication rules this module keeps (DEC-410 to DEC-415):
- Signing out is fail closed. A device that is revoked can never sign in again (a new device id is
  needed), a credential that is deleted can never be tried, and the session store is told to end
  every session of the person (it raises the person's epoch, so a session created at the same
  moment is dead on arrival) both before the change and after it commits. A session store that
  cannot be reached is an error, never a quiet success: the change is idempotent by its key, and the
  same command sent again finishes the sign-out.
- A person who is removed is made inactive as well as losing their posts, so their number is no
  longer a known number and cannot ask for a text code (U25 reads active people only).
- The lost-phone device is `pending-callback`: not known, so it cannot sign in, until the lead has
  phoned the register number and confirms. Prompts are not texted to a person with a device waiting
  for a call-back (send_prompts); they go to the cover, or the lead is told (the missed-report
  ladder).
- Every action is audited with counts and reasons only: never a number, a hash, a PIN, a device
  token or a push subscription.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import SessionStore
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.application.use_cases.pin import PIN_SET_WINDOW
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.flags import SERVICE_FLAG_NO_REPORTER, ServiceFlag
from diucs.domain.model.people import (
    REPORTER_ROLE_CODES,
    Practitioner,
    PractitionerRole,
    is_in_effect,
    role_holder,
)

AUDIT_ACTION: Final = "U"
REMOVE_USE_CASE: Final = "RemovePerson"
SIGN_OUT_USE_CASE: Final = "SignOutEverywhere"
START_USE_CASE: Final = "StartNewPhone"
CONFIRM_USE_CASE: Final = "ConfirmNewPhone"
MAX_ID_LENGTH: Final = 128
NEW_DEVICE_PURPOSE: Final = "new-device"
"""The text-code purpose of a lost-phone move (U25): the edge starts a new phone for it."""
NO_REPORTER_REASON: Final = (
    "the reporter was removed and no one else can be texted for this service"
)


class RemovalReason(StrEnum):
    LEFT_SERVICE = "left-service"
    CHANGED_ROLE = "changed-role"
    LOST_PHONE = "lost-phone"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class RemovePersonCommand:
    idempotency_key: str
    actor: Actor
    practitioner_id: str
    reason: RemovalReason


@dataclass(frozen=True, slots=True)
class RemovePersonResult:
    roles_ended: int
    devices_revoked: int
    push_removed: int
    covers_released: int
    services_without_reporter: tuple[str, ...]
    """Services with nobody left to text: each has the no-reporter flag, and the lead is told."""
    services_covered: tuple[str, ...]
    """Services whose prompts carry on to an active cover."""


@dataclass(frozen=True, slots=True)
class SignOutEverywhereCommand:
    idempotency_key: str
    actor: Actor


@dataclass(frozen=True, slots=True)
class SignOutEverywhereResult:
    devices_signed_out: int


@dataclass(frozen=True, slots=True)
class StartNewPhoneCommand:
    practitioner_id: str
    device_id: str
    verified_at: datetime
    """When the `new-device` text code was verified, as VerifyTextCodeResult gave it. Refused when
    it is in the future or older than PIN_SET_WINDOW: the edge calls this straight after."""


@dataclass(frozen=True, slots=True)
class StartNewPhoneResult:
    started: bool
    devices_signed_out: int


@dataclass(frozen=True, slots=True)
class ConfirmNewPhoneCommand:
    idempotency_key: str
    actor: Actor
    practitioner_id: str


@dataclass(frozen=True, slots=True)
class ConfirmNewPhoneResult:
    confirmed: int


NOT_STARTED: Final = StartNewPhoneResult(started=False, devices_signed_out=0)
"""The one answer for every person or device that cannot start a new phone."""


@dataclass(frozen=True, slots=True)
class _Stored:
    """A command's first result under its key, with the fingerprint of the command (DEC-104)."""

    fingerprint: str
    result: object


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _ident(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_ID_LENGTH
        or not value.isprintable()
    ):
        raise ValidationFailed(name, "is not a valid identifier")
    return value


def _check_key(key: object) -> str:
    if not isinstance(key, str) or not key.strip() or len(key) > MAX_ID_LENGTH:
        raise ValidationFailed("idempotency_key", "is required")
    return key


def _command_key(kind: str, scope: ScopeId, key: str) -> str:
    """The replay key. It carries the tenant (lesson L160): one key, two tenants, two commands."""
    return f"people-access:{kind}:{scope}:{key}"


def _replayed[T](stored: object, fingerprint: str, result_type: type[T]) -> T | None:
    """The first result of this key when it is the same command, None when the key is new, and a
    Conflict when the key was used for a different command."""
    if stored is None:
        return None
    if (
        not isinstance(stored, _Stored)
        or stored.fingerprint != fingerprint
        or not isinstance(stored.result, result_type)
    ):
        raise Conflict("this command key was used for a different command")
    return stored.result


def _lead(actor: Actor) -> str:
    """The practitioner id of a shift lead, or NotAllowed (a non-revealing 404 at the edge)."""
    if actor.role is not Role.LEAD or actor.practitioner_id is None:
        raise NotAllowed("only the shift lead may do this")
    return actor.practitioner_id


async def _sign_out_devices(uow: UnitOfWork, person: str, now: datetime) -> tuple[int, int]:
    """Revoke every device of the person, delete their PIN credentials and remove their push
    subscriptions (each with its consent withdrawn). Returns (devices revoked, subscriptions
    removed). Past reports are untouched."""
    revoked = await uow.devices.revoke_all(person)
    await uow.pins.clear_all(person)
    subscriptions = await uow.push_subscriptions.for_practitioner(person)
    for subscription in subscriptions:
        await uow.push_subscriptions.delete(subscription.device_id)
        await uow.notification_consents.withdraw(person, subscription.device_id, now)
    return revoked, len(subscriptions)


def _active_cover(role: PractitionerRole, now: datetime) -> str | None:
    """The practitioner covering the role at `now`, or None when no cover is in force."""
    if (
        role.covered_by_practitioner_id is not None
        and role.covered_until is not None
        and now < role.covered_until
    ):
        return role.covered_by_practitioner_id
    return None


async def _someone_else_can_be_texted(
    uow: UnitOfWork, service_id: str, person: str, now: datetime
) -> bool:
    for role in await uow.people.reporter_roles_for_service(service_id, now):
        if role.practitioner_id == person or not is_in_effect(role, now):
            continue
        holder = await uow.people.get_practitioner(role_holder(role, now))
        if holder is not None and holder.active and holder.id != person:
            return True
    return False


class RemovePerson:
    """The lead removes a person's access. Every active post of theirs ends, every device is signed
    out and its credential deleted, their push subscriptions are removed, their sessions end, and
    they are made inactive. For each service left with no one to text, the cover carries on if one
    is in force, otherwise the service gets the `no-reporter` flag and the lead is told."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        sessions: SessionStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._sessions = sessions

    async def execute(self, command: RemovePersonCommand) -> RemovePersonResult:
        lead = _lead(command.actor)
        person = _ident(command.practitioner_id, "practitioner_id")
        key = _check_key(command.idempotency_key)
        if not isinstance(command.reason, RemovalReason):
            raise ValidationFailed(
                "reason", "must be left-service, changed-role, lost-phone or other"
            )
        if person == lead:
            raise NotAllowed("a lead cannot remove themself")
        fingerprint = repr(("remove", person, command.reason.value))

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            first = _replayed(
                await uow.idempotency.get(_command_key("remove", scope, key)),
                fingerprint,
                RemovePersonResult,
            )
            if first is None and await uow.people.get_practitioner(person) is None:
                raise NotFound("no person with this id")
        if first is not None:
            # A replay writes nothing. It ends the sessions again, so a revoke that failed the
            # first time is finished by the retry.
            await self._sessions.delete_all_for_person(person)
            return first

        await self._sessions.delete_all_for_person(person)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            result = await self._remove(uow, command, lead, person, now)
            await uow.idempotency.put(
                _command_key("remove", scope, key), _Stored(fingerprint, result)
            )
            await uow.commit()
        await self._sessions.delete_all_for_person(person)
        return result

    async def _remove(
        self, uow: UnitOfWork, command: RemovePersonCommand, lead: str, person: str, now: datetime
    ) -> RemovePersonResult:
        practitioner = await uow.people.get_practitioner(person)
        if practitioner is None:
            raise NotFound("no person with this id")
        roles = sorted(await uow.people.roles_for_practitioner(person), key=lambda role: role.id)
        released = await self._release_covers(uow, practitioner, now)

        covered: set[str] = set()
        reporter_services: set[str] = set()
        for role in roles:
            await uow.people.save_role(
                replace(
                    role,
                    active=False,
                    period_end=now,
                    covered_by_practitioner_id=None,
                    covered_until=None,
                )
            )
            if role.code in REPORTER_ROLE_CODES and role.service_id is not None:
                reporter_services.add(role.service_id)
                if await self._carry_on_by_cover(uow, role, person, now):
                    covered.add(role.service_id)

        without: list[str] = []
        for service_id in sorted(reporter_services - covered):
            if await _someone_else_can_be_texted(uow, service_id, person, now):
                continue
            await uow.flags.set_service_flag(
                ServiceFlag(
                    service_id=service_id,
                    code=SERVICE_FLAG_NO_REPORTER,
                    active=True,
                    reason=NO_REPORTER_REASON,
                    actor_id=lead,
                    at=now,
                )
            )
            without.append(service_id)

        revoked, push_removed = await _sign_out_devices(uow, person, now)
        await uow.people.save_practitioner(replace(practitioner, active=False))
        result = RemovePersonResult(
            roles_ended=len(roles),
            devices_revoked=revoked,
            push_removed=push_removed,
            covers_released=released,
            services_without_reporter=tuple(without),
            services_covered=tuple(sorted(covered)),
        )
        await uow.audit.append(
            AuditEntry(
                action=AUDIT_ACTION,
                use_case=REMOVE_USE_CASE,
                actor=command.actor,
                entity_ids=(person, *sorted(reporter_services)),
                snapshot={
                    "reason": command.reason.value,
                    "roles_ended": result.roles_ended,
                    "devices_revoked": result.devices_revoked,
                    "push_removed": result.push_removed,
                    "covers_released": result.covers_released,
                    "services_without_reporter": ",".join(result.services_without_reporter),
                    "services_covered": ",".join(result.services_covered),
                },
                at=now,
            )
        )
        return result

    async def _release_covers(self, uow: UnitOfWork, person: Practitioner, now: datetime) -> int:
        """Return the roles this person was covering to their own holders: a cover who has left
        would otherwise leave the role with a holder who cannot be texted."""
        if person.phone_hash is None:
            return 0
        released = 0
        for role, _name in await uow.people.services_for_phone_hash(person.phone_hash, now):
            if role.covered_by_practitioner_id == person.id and role.practitioner_id != person.id:
                await uow.people.save_role(
                    replace(role, covered_by_practitioner_id=None, covered_until=None)
                )
                released += 1
        return released

    async def _carry_on_by_cover(
        self, uow: UnitOfWork, role: PractitionerRole, person: str, now: datetime
    ) -> bool:
        """When the ended post has a cover in force, give the covering practitioner a post of their
        own for the rest of the cover, so prompts go on to them (as U16 does)."""
        cover_id = _active_cover(role, now)
        if cover_id is None or cover_id == person or role.covered_until is None:
            return False
        cover = await uow.people.get_practitioner(cover_id)
        if cover is None or not cover.active:
            return False
        await uow.people.save_role(
            PractitionerRole(
                id=self._ids.new_id(),
                practitioner_id=cover.id,
                service_id=role.service_id,
                code=role.code,
                active=True,
                channel=role.channel,
                period_start=now,
                period_end=role.covered_until,
            )
        )
        return True


class SignOutEverywhere:
    """A person signs out of every phone: all their devices are revoked and their PIN credentials
    deleted, their push subscriptions removed and their sessions ended. They sign in again with a
    text code and a PIN on a new device id. The result says how many phones were signed out."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, sessions: SessionStore
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._sessions = sessions

    async def execute(self, command: SignOutEverywhereCommand) -> SignOutEverywhereResult:
        if command.actor.practitioner_id is None:
            raise NotAllowed("only a signed-in person can sign out of every phone")
        person = command.actor.practitioner_id
        key = _check_key(command.idempotency_key)
        fingerprint = repr(("sign-out", person))
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            first = _replayed(
                await uow.idempotency.get(_command_key("sign-out", scope, key)),
                fingerprint,
                SignOutEverywhereResult,
            )
        if first is not None:
            await self._sessions.delete_all_for_person(person)
            return first

        await self._sessions.delete_all_for_person(person)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            revoked, _removed = await _sign_out_devices(uow, person, now)
            result = SignOutEverywhereResult(devices_signed_out=revoked)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=SIGN_OUT_USE_CASE,
                    actor=command.actor,
                    entity_ids=(person,),
                    snapshot={"devices_signed_out": revoked},
                    at=now,
                )
            )
            await uow.idempotency.put(
                _command_key("sign-out", scope, key), _Stored(fingerprint, result)
            )
            await uow.commit()
        await self._sessions.delete_all_for_person(person)
        return result


class StartNewPhone:
    """A reporter who lost a phone has verified a `new-device` text code on the new one.

    Every old device is signed out at once (revoked, credentials deleted, push removed, sessions
    ended) and the new device is stored `pending-callback`: it cannot sign in, and prompts are not
    texted to the person, until the lead records a call-back (ConfirmNewPhone).

    Every person or device that cannot start one (an unknown or removed person, a stale
    verification, a device id that is already registered to anyone) gets the one answer `started`
    false, and nothing is written. The same new device sent again is a no-op that keeps the device.
    """

    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, sessions: SessionStore
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._sessions = sessions

    async def execute(self, command: StartNewPhoneCommand) -> StartNewPhoneResult:
        person = _ident(command.practitioner_id, "practitioner_id")
        device = _ident(command.device_id, "device_id")
        verified_at = command.verified_at
        if verified_at.tzinfo is None or verified_at.utcoffset() is None:
            raise ValidationFailed("verified_at", "must be timezone-aware")
        now = self._clock.now()
        if verified_at > now or now - verified_at > PIN_SET_WINDOW:
            return NOT_STARTED
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            gate = await self._gate(uow, person, device)
        if gate is not None:
            return gate

        await self._sessions.delete_all_for_person(person)
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            gate = await self._gate(uow, person, device)
            if gate is not None:
                return gate
            revoked, _removed = await _sign_out_devices(uow, person, now)
            await uow.devices.register_pending(person, device, now)
            await uow.devices.mark_verified(person, device, verified_at)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=START_USE_CASE,
                    actor=_person_actor(uow, person),
                    entity_ids=(person,),
                    snapshot={"devices_signed_out": revoked},
                    at=now,
                )
            )
            await uow.commit()
        await self._sessions.delete_all_for_person(person)
        return StartNewPhoneResult(started=True, devices_signed_out=revoked)

    async def _gate(self, uow: UnitOfWork, person: str, device: str) -> StartNewPhoneResult | None:
        """None when a new phone may start; otherwise the answer to give and stop at."""
        practitioner = await uow.people.get_practitioner(person)
        if practitioner is None or not practitioner.active:
            return NOT_STARTED
        if device in await uow.devices.awaiting_callback(person):
            return StartNewPhoneResult(started=True, devices_signed_out=0)
        if await uow.devices.owner_of(device) is not None:
            return NOT_STARTED
        return None


def _person_actor(uow: UnitOfWork, person: str) -> Actor:
    """The actor of a person who proved themself by a text code only: a reporter of the unit's
    tenant, on the text-code channel."""
    return Actor(
        role=Role.REPORTER,
        practitioner_id=person,
        device_id=None,
        channel="text-code",
        service_ids=frozenset(),
        tenant_id=_tenant_scope(uow.unit_scope).value,
    )


class ConfirmNewPhone:
    """The lead has phoned the register number and records the call-back: the person's new phone
    becomes active and can sign in. A lead cannot confirm their own new phone: another lead does."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: ConfirmNewPhoneCommand) -> ConfirmNewPhoneResult:
        lead = _lead(command.actor)
        person = _ident(command.practitioner_id, "practitioner_id")
        key = _check_key(command.idempotency_key)
        if person == lead:
            raise NotAllowed("a lead cannot confirm their own new phone")
        fingerprint = repr(("confirm", person))
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            stored_key = _command_key("confirm", scope, key)
            first = _replayed(
                await uow.idempotency.get(stored_key), fingerprint, ConfirmNewPhoneResult
            )
            if first is not None:
                return first
            practitioner = await uow.people.get_practitioner(person)
            if practitioner is None or not practitioner.active:
                raise NotFound("no new phone is waiting for this person")
            confirmed = await uow.devices.confirm_pending(person, now)
            if confirmed == 0:
                raise NotFound("no new phone is waiting for this person")
            result = ConfirmNewPhoneResult(confirmed=confirmed)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=CONFIRM_USE_CASE,
                    actor=command.actor,
                    entity_ids=(person,),
                    snapshot={"confirmed": confirmed},
                    at=now,
                )
            )
            await uow.idempotency.put(stored_key, _Stored(fingerprint, result))
            await uow.commit()
        return result
