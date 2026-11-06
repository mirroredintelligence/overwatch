"""The duty roster of a service: who may report for it, and who is on shift (DEC-1341).

A service has several pre-registered duty managers: a name and a phone number each, the number held
only as a keyed hash and in the protected contact store, as for every reporter. A roster duty
manager holds a role of its own code (`roster-duty-manager`) and reports only while on shift, so the
role is the shift: inactive means off shift, active with a period that covers now means on shift,
and inactive with an end means removed. A person who is off shift is sent no prompt, because
the prompts go to the reporter roles that are active and in effect.

  * `AddRosterManager`: the shift lead adds a person to a service's roster (off shift).
  * `RemoveRosterManager`: the shift lead takes a person off the roster for good.
  * `ListRoster`: who is on the roster and who is on shift now, the number as its last digits only.
  * `CheckIn` and `SignOff`: a person on the roster goes on or off shift (by text, see
    `handle_roster_text`). Checking in ends the shift of whoever was on, so the newest check-in
    replaces the last (the owner's rule, DEC-1341 item 5).

The shift lead's own actions are audited; so is each check-in and sign-off, by id and never by name
or number.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final

from overwatch.application.actor import Actor
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.identity import PhoneHasher, normalise_uk_mobile
from overwatch.application.ports.outbound.ids import IdGenerator
from overwatch.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from overwatch.application.use_cases.lead_views import check_lead, ending
from overwatch.application.use_cases.setup_service_by_lead import international
from overwatch.domain.codes import Channel, PractitionerRoleCode
from overwatch.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from overwatch.domain.model.people import (
    Practitioner,
    PractitionerRole,
    RosterState,
    roster_state,
)

ROSTER_CODE: Final = PractitionerRoleCode.ROSTER_DUTY_MANAGER
ADD_ACTION: Final = "roster-add"
REMOVE_ACTION: Final = "roster-remove"
CHECK_IN_ACTION: Final = "roster-check-in"
SIGN_OFF_ACTION: Final = "roster-sign-off"
DEFAULT_SHIFT_HOURS: Final = 8
MAX_SHIFT_HOURS: Final = 14
"""The longest shift a person can start: one forgotten about ends by itself (DEC-1341 item 4)."""
NAME_MIN: Final = 2
NAME_MAX: Final = 60


@dataclass(frozen=True, slots=True)
class RosterEntry:
    role_id: str
    name: str
    number_ending: str | None
    state: RosterState
    shift_end: datetime | None


@dataclass(frozen=True, slots=True)
class AddRosterManagerCommand:
    actor: Actor
    service_id: str
    name: str
    mobile: str


@dataclass(frozen=True, slots=True)
class AddRosterManagerResult:
    role_id: str
    practitioner_id: str


def check_person_name(name: str) -> str:
    """A person's name, trimmed, two to sixty characters. The practitioner record then refuses a
    postcode or an NHS number in it (DEC-065)."""
    cleaned = " ".join(name.split())
    if not NAME_MIN <= len(cleaned) <= NAME_MAX:
        raise ValidationFailed("name", f"must be {NAME_MIN} to {NAME_MAX} characters")
    return cleaned


def _lead_id(actor: Actor) -> str:
    check_lead(actor)
    if actor.practitioner_id is None:
        raise NotAllowed("the lead must act as a named practitioner")
    return actor.practitioner_id


class AddRosterManager:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        phone_hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._hasher = phone_hasher

    async def execute(self, command: AddRosterManagerCommand) -> AddRosterManagerResult:
        _lead_id(command.actor)
        name = check_person_name(command.name)
        national = normalise_uk_mobile(command.mobile)
        phone_hash = self._hasher.hash(national)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            if await uow.services.get(command.service_id) is None:
                raise NotFound("no service with this id")
            practitioner = await uow.people.find_by_phone_hash(phone_hash)
            if practitioner is None:
                practitioner = Practitioner(
                    id=self._ids.new_id(), active=True, display_name=name, phone_hash=phone_hash
                )
                await uow.people.save_practitioner(practitioner)
            else:
                roster = await uow.people.roster_for_service(command.service_id)
                if any(role.practitioner_id == practitioner.id for role in roster):
                    raise Conflict("this person is already on the roster of this service")
            role = PractitionerRole(
                id=self._ids.new_id(),
                practitioner_id=practitioner.id,
                service_id=command.service_id,
                code=ROSTER_CODE,
                active=False,
                channel=Channel.TEXT,
                period_start=now,
            )
            await uow.people.save_role(role)
            await uow.contacts.put_phone(role.id, international(national))
            await uow.audit.append(
                AuditEntry(
                    action=ADD_ACTION,
                    use_case="AddRosterManager",
                    actor=command.actor,
                    entity_ids=(command.service_id, practitioner.id, role.id),
                    snapshot={"service_id": command.service_id, "role_id": role.id},
                    at=now,
                )
            )
            await uow.commit()
        return AddRosterManagerResult(role_id=role.id, practitioner_id=practitioner.id)


class RemoveRosterManager:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, role_id: str) -> None:
        _lead_id(actor)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            role = await uow.people.get_role(role_id)
            if role is None or role.code is not ROSTER_CODE:
                raise NotFound("no roster duty manager with this id")
            if roster_state(role, now) is RosterState.REMOVED:
                raise NotFound("no roster duty manager with this id")
            await uow.people.save_role(replace(role, active=False, period_end=now))
            await uow.audit.append(
                AuditEntry(
                    action=REMOVE_ACTION,
                    use_case="RemoveRosterManager",
                    actor=actor,
                    entity_ids=(role.id,),
                    snapshot={"role_id": role.id},
                    at=now,
                )
            )
            await uow.commit()


class ListRoster:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, service_id: str) -> tuple[RosterEntry, ...]:
        _lead_id(actor)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            if await uow.services.get(service_id) is None:
                raise NotFound("no service with this id")
            entries: list[RosterEntry] = []
            for role in await uow.people.roster_for_service(service_id):
                practitioner = await uow.people.get_practitioner(role.practitioner_id)
                state = roster_state(role, now)
                entries.append(
                    RosterEntry(
                        role_id=role.id,
                        name="" if practitioner is None else practitioner.display_name,
                        number_ending=ending(await uow.contacts.get_phone(role.id), 4),
                        state=state,
                        shift_end=role.period_end if state is RosterState.ON_SHIFT else None,
                    )
                )
        return tuple(sorted(entries, key=lambda entry: (entry.name.lower(), entry.role_id)))


@dataclass(frozen=True, slots=True)
class ShiftChange:
    """One service a person went on or off shift for."""

    service_id: str
    service_name: str
    shift_end: datetime | None


async def _off_shift(uow: UnitOfWork, role: PractitionerRole) -> PractitionerRole:
    off = replace(role, active=False, period_end=None)
    await uow.people.save_role(off)
    return off


def check_hours(hours: int | None) -> int:
    """The length of a shift in hours: the default when none is said, and never past the longest."""
    if hours is None:
        return DEFAULT_SHIFT_HOURS
    if not 1 <= hours <= MAX_SHIFT_HOURS:
        raise ValidationFailed("hours", f"must be 1 to {MAX_SHIFT_HOURS}")
    return hours


class CheckIn:
    """A person on the roster goes on shift for every service they are on the roster of; the shift
    of whoever was on for each of those services ends (newest replaces last, DEC-1341 item 5)."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, phone_hash: str, hours: int | None, actor: Actor) -> list[ShiftChange]:
        length = check_hours(hours)
        now = self._clock.now()
        end = now + timedelta(hours=length)
        changes: list[ShiftChange] = []
        async with self._uow_factory() as uow:
            mine = await uow.people.roster_roles_for_phone_hash(phone_hash)
            for role in mine:
                if role.service_id is None:
                    continue
                profile = await uow.services.get(role.service_id)
                if profile is None or not profile.active:
                    continue
                for other in await uow.people.roster_for_service(role.service_id):
                    if other.id != role.id and roster_state(other, now) is RosterState.ON_SHIFT:
                        await _off_shift(uow, other)
                await uow.people.save_role(
                    replace(role, active=True, period_start=now, period_end=end)
                )
                await uow.audit.append(
                    AuditEntry(
                        action=CHECK_IN_ACTION,
                        use_case="CheckIn",
                        actor=actor,
                        entity_ids=(role.service_id, role.id),
                        snapshot={"role_id": role.id, "hours": length},
                        at=now,
                    )
                )
                changes.append(ShiftChange(role.service_id, profile.name, end))
            if changes:
                await uow.commit()
        return changes


class SignOff:
    """A person on shift goes off shift, for every service they are on."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, phone_hash: str, actor: Actor) -> list[ShiftChange]:
        now = self._clock.now()
        changes: list[ShiftChange] = []
        async with self._uow_factory() as uow:
            for role in await uow.people.roster_roles_for_phone_hash(phone_hash):
                if role.service_id is None or roster_state(role, now) is not RosterState.ON_SHIFT:
                    continue
                profile = await uow.services.get(role.service_id)
                await _off_shift(uow, role)
                await uow.audit.append(
                    AuditEntry(
                        action=SIGN_OFF_ACTION,
                        use_case="SignOff",
                        actor=actor,
                        entity_ids=(role.service_id, role.id),
                        snapshot={"role_id": role.id},
                        at=now,
                    )
                )
                changes.append(
                    ShiftChange(role.service_id, "" if profile is None else profile.name, None)
                )
            if changes:
                await uow.commit()
        return changes
