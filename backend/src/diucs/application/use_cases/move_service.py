"""Moving services between phones (U38): a shift lead moves one service to another phone, for good
or as cover until a date; or adds a service to a phone that the person must accept.

A move has three steps, in order (domain-rules 2.5 and the prompt): (1) the new number is verified
by a text code (VerifyServiceMoveCode, through the CodeVerifier port, which is U25's check); (2)
the lead phones the service on its register number and records the call-back; (3)
CompleteServiceMove moves the service's reporter role. A permanent move ends the old role and
starts a new active role for the new phone's practitioner. A cover sets `covered_by` and
`covered_until` on the old role instead, and the role returns by itself at `until` (role_holder
reads it). The old phone keeps its other services.

Numbers are never stored: a move keeps the hash of the new number (P20), and the code check takes
the number again from the lead. A phone that holds more than three services gets the flag holds-
many-services on each of its services (D28, after any change). The change, its audit entry and its
flags are written in one unit of work per use case.

Not built here: replay of the start and add commands by idempotency key (an open move per service
and a pending addition per role refuse a repeat; DEC-343 item 9), and the live check of a service
before a prompt reaches its new phone (the registration rules own it)."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Protocol

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher, normalise_uk_mobile
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.flags import SERVICE_FLAG_HOLDS_MANY, ServiceFlag
from diucs.domain.model.people import Practitioner, PractitionerRole
from diucs.domain.model.service_move import ServiceMove
from diucs.domain.rules.multi_service import MAX_SERVICES_PER_PHONE, phone_overloaded

MOVE_CODE_PURPOSE: Final = "setup"
"""The text-code purpose of a move: the new phone is being set up to report a service (U25)."""
AUDIT_ACTION: Final = "U"
FLAG_ACTOR: Final = "system:multi-service"
ALLOWED_ROLES: Final = frozenset({Role.LEAD})


class CodeVerifier(Protocol):
    """The text-code check of U25 for one phone and purpose: True when the code matches and is in
    time. A recording fake in tests; the composition root adapts U25's VerifyTextCode."""

    async def verify(self, phone: str, purpose: str, code: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class StartServiceMoveCommand:
    actor: Actor
    service_id: str
    to_mobile: str
    until: datetime | None


@dataclass(frozen=True, slots=True)
class MoveResult:
    move_id: str


@dataclass(frozen=True, slots=True)
class VerifyServiceMoveCodeCommand:
    move_id: str
    mobile: str
    """The new number again: a move stores only its hash, and the code is texted to the number."""
    code: str


@dataclass(frozen=True, slots=True)
class RecordMoveCallBackCommand:
    actor: Actor
    move_id: str


@dataclass(frozen=True, slots=True)
class CompleteServiceMoveCommand:
    actor: Actor
    move_id: str


@dataclass(frozen=True, slots=True)
class AddServiceToPhoneCommand:
    actor: Actor
    service_id: str
    mobile: str


@dataclass(frozen=True, slots=True)
class AddServiceToPhoneResult:
    role_id: str


@dataclass(frozen=True, slots=True)
class AnswerServiceAdditionCommand:
    actor: Actor
    role_id: str
    accept: bool


def _lead(actor: Actor) -> None:
    if actor.role not in ALLOWED_ROLES:
        raise NotAllowed("only the shift lead may move or add a service")


def _tenant_scope(scope: ScopeId | None) -> ScopeId:
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _mobile(number: str) -> str:
    """The national form of a UK mobile, or ValidationFailed on to_mobile. Never echoed."""
    try:
        return normalise_uk_mobile(number)
    except ValidationFailed:
        raise ValidationFailed(
            "to_mobile", "must be a UK mobile number, like 07700 900123"
        ) from None


async def _open_move(uow: UnitOfWork, move_id: str) -> ServiceMove:
    move = await uow.service_moves.get(move_id)
    if move is None:
        raise NotFound("no service move with this id")
    if not move.is_open:
        raise NotAllowed("this service move is already finished or cancelled")
    return move


async def _flag_if_overloaded(
    uow: UnitOfWork, practitioner_phone: str | None, now: datetime
) -> int:
    """Set holds-many-services on each service of a phone that holds more than three services.
    Returns how many flags were set. A phone with no hash (a practitioner without a number) holds
    nothing this rule can count."""
    if practitioner_phone is None:
        return 0
    held = await uow.people.services_for_phone_hash(practitioner_phone, now)
    if not phone_overloaded(len(held)):
        return 0
    count = len(held)
    flags = 0
    for role, _name in held:
        if role.service_id is None:
            continue
        await uow.flags.set_service_flag(
            ServiceFlag(
                service_id=role.service_id,
                code=SERVICE_FLAG_HOLDS_MANY,
                active=True,
                reason=f"phone holds {count} services, more than {MAX_SERVICES_PER_PHONE}",
                actor_id=FLAG_ACTOR,
                at=now,
            )
        )
        flags += 1
    return flags


class StartServiceMove:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._hasher = hasher

    async def execute(self, command: StartServiceMoveCommand) -> MoveResult:
        _lead(command.actor)
        number = _mobile(command.to_mobile)
        now = self._clock.now()
        if command.until is not None:
            if command.until.tzinfo is None or command.until.utcoffset() is None:
                raise ValidationFailed("until", "must carry a UTC offset")
            if command.until <= now:
                raise ValidationFailed("until", "must be in the future")
        to_hash = self._hasher.hash(number)
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            if await uow.service_moves.open_for_service(command.service_id):
                raise Conflict("this service already has a move in progress")
            profile = await uow.services.get(command.service_id)
            if profile is None:
                raise NotFound("no service with this id")
            roles = await uow.people.reporter_roles_for_service(profile.id, now)
            active = sorted((r for r in roles if r.active), key=lambda role: role.id)
            if not active:
                raise NotFound("this service has no reporter to move")
            move = ServiceMove(
                id=self._ids.new_id(),
                service_id=profile.id,
                from_practitioner_id=active[0].practitioner_id,
                to_phone_hash=to_hash,
                until=command.until,
            )
            await uow.service_moves.add(move)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="StartServiceMove",
                    actor=command.actor,
                    entity_ids=(move.id, profile.id),
                    snapshot={
                        "until": None if command.until is None else command.until.isoformat()
                    },
                    at=now,
                )
            )
            await uow.commit()
        return MoveResult(move_id=move.id)


class VerifyServiceMoveCode:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        verifier: CodeVerifier,
        clock: Clock,
        hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._verifier = verifier
        self._clock = clock
        self._hasher = hasher

    async def execute(self, command: VerifyServiceMoveCodeCommand) -> None:
        number = _mobile(command.mobile)
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            move = await _open_move(uow, command.move_id)
            if self._hasher.hash(number) != move.to_phone_hash:
                raise ValidationFailed("mobile", "is not the number this move was started for")
            if move.code_verified_at is not None:
                return
        if not await self._verifier.verify(number, MOVE_CODE_PURPOSE, command.code):
            raise ValidationFailed("code", "the code is not right or has expired")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            move = await _open_move(uow, command.move_id)
            await uow.service_moves.save(replace(move, code_verified_at=now))
            await uow.commit()


class RecordMoveCallBack:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RecordMoveCallBackCommand) -> None:
        _lead(command.actor)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            move = await _open_move(uow, command.move_id)
            if move.code_verified_at is None:
                raise NotAllowed("the new phone's code is not verified yet")
            if move.callback_at is None:
                await uow.service_moves.save(replace(move, callback_at=now))
            await uow.commit()


class CompleteServiceMove:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._hasher = hasher

    async def execute(self, command: CompleteServiceMoveCommand) -> None:
        _lead(command.actor)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            move = await _open_move(uow, command.move_id)
            if move.code_verified_at is None:
                raise NotAllowed("step 1 is not done: the new phone's code is not verified")
            if move.callback_at is None:
                raise NotAllowed("step 2 is not done: the call-back to the service is not recorded")
            roles = await uow.people.reporter_roles_for_service(move.service_id, now)
            old = next((r for r in roles if r.practitioner_id == move.from_practitioner_id), None)
            if old is None:
                raise NotFound("the reporter role of this service is not found")
            new = await uow.people.find_by_phone_hash(move.to_phone_hash)
            if new is None:
                new = Practitioner(
                    id=self._ids.new_id(),
                    active=True,
                    display_name="Reporter",
                    phone_hash=move.to_phone_hash,
                )
                await uow.people.save_practitioner(new)
            if move.until is None:
                await uow.people.save_role(replace(old, active=False, period_end=now))
                await uow.people.save_role(
                    PractitionerRole(
                        id=self._ids.new_id(),
                        practitioner_id=new.id,
                        service_id=old.service_id,
                        code=old.code,
                        active=True,
                        channel=old.channel,
                        period_start=now,
                    )
                )
            else:
                await uow.people.save_role(
                    replace(old, covered_by_practitioner_id=new.id, covered_until=move.until)
                )
            await uow.service_moves.save(replace(move, completed_at=now))
            from_practitioner = await uow.people.get_practitioner(move.from_practitioner_id)
            await _flag_if_overloaded(uow, move.to_phone_hash, now)
            if from_practitioner is not None:
                await _flag_if_overloaded(uow, from_practitioner.phone_hash, now)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="CompleteServiceMove",
                    actor=command.actor,
                    entity_ids=(move.id, move.service_id),
                    snapshot={"cover": move.until is not None},
                    at=now,
                )
            )
            await uow.commit()


class AddServiceToPhone:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._hasher = hasher

    async def execute(self, command: AddServiceToPhoneCommand) -> AddServiceToPhoneResult:
        _lead(command.actor)
        to_hash = self._hasher.hash(_mobile(command.mobile))
        now = self._clock.now()
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            person = await uow.people.find_by_phone_hash(to_hash)
            if person is None:
                raise NotFound("no reporter holds this number")
            profile = await uow.services.get(command.service_id)
            if profile is None:
                raise NotFound("no service with this id")
            existing = await uow.people.roles_for_practitioner(person.id)
            if any(role.service_id == profile.id for role in existing):
                raise Conflict("this number already holds this service or has it pending")
            code = existing[0].code if existing else None
            if code is None:
                raise NotFound("this number has no reporter role to copy")
            role = PractitionerRole(
                id=self._ids.new_id(),
                practitioner_id=person.id,
                service_id=profile.id,
                code=code,
                active=False,
                channel=existing[0].channel,
                period_start=now,
            )
            await uow.people.save_role(role)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="AddServiceToPhone",
                    actor=command.actor,
                    entity_ids=(role.id, profile.id),
                    snapshot=None,
                    at=now,
                )
            )
            await uow.commit()
        return AddServiceToPhoneResult(role_id=role.id)


class AnswerServiceAddition:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: AnswerServiceAdditionCommand) -> None:
        now = self._clock.now()
        if command.actor.practitioner_id is None:
            raise NotFound("no pending service addition with this id")
        async with self._uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            role = await uow.people.get_role(command.role_id)
            if role is None or role.practitioner_id != command.actor.practitioner_id:
                raise NotFound("no pending service addition with this id")
            if role.active or role.period_end is not None:
                raise NotAllowed("this service addition is already answered")
            if command.accept:
                await uow.people.save_role(replace(role, active=True))
            else:
                await uow.people.save_role(replace(role, active=False, period_end=now))
            person = await uow.people.get_practitioner(role.practitioner_id)
            if command.accept and person is not None:
                await _flag_if_overloaded(uow, person.phone_hash, now)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="AnswerServiceAddition",
                    actor=command.actor,
                    entity_ids=(role.id,),
                    snapshot={"accepted": command.accept},
                    at=now,
                )
            )
            await uow.commit()


__all__ = [
    "AddServiceToPhone",
    "AddServiceToPhoneCommand",
    "AddServiceToPhoneResult",
    "AnswerServiceAddition",
    "AnswerServiceAdditionCommand",
    "CodeVerifier",
    "CompleteServiceMove",
    "CompleteServiceMoveCommand",
    "MOVE_CODE_PURPOSE",
    "MoveResult",
    "RecordMoveCallBack",
    "RecordMoveCallBackCommand",
    "StartServiceMove",
    "StartServiceMoveCommand",
    "VerifyServiceMoveCode",
    "VerifyServiceMoveCodeCommand",
]
