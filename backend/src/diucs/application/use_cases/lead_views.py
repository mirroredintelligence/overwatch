"""What the shift lead's pages read (W7B C, DEC-802 to DEC-806): the overview, the reporter post of
each service, the state of a suspension, the phones, and the set-up of the invitations.

Every read is read-only, for the shift lead only, and tenant-bound by the unit of work. A mobile
number never leaves: the last three or four digits stand for it (the register number of a suspended
service is a directory number, not a person's, and is the one number given whole, because the lead
phones it).

- `GetLeadOverview`: the services to chase (a prompt missed, with the ladder's steps and whether
  each is done), the figures getting old (reported more than the stale limit ago, not yet overdue),
  the posts a cover is holding, the counts by status and how many services reported today. It reads
  the board (`QueryBoard`), so a status here is the status everywhere else. A suspended service is
  chased by nobody: its status says why.
- `ListReporters`: the active reporter posts with their role id (what change-number and remove
  need), the channel, the end of the number and the cover.
- `GetSuspension`: whether a service is suspended, since when, why, how many requests it expired and
  the register number to phone.
- `ListPhones`: the services grouped by the phone that holds them now (a cover holds a service
  while it runs).
- `ListInvitations`: each invitation with how far the reporter's set-up has got.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.use_cases.change_reporter_number import COVER_KEY_PREFIX
from diucs.application.use_cases.missed_report_ladder import LADDER_OFFSETS
from diucs.application.use_cases.query_board import BoardEntry, QueryBoard, QueryBoardQuery
from diucs.application.use_cases.registration_draft import read_draft
from diucs.application.work import DONE, ScheduledWork, WorkKind
from diucs.domain.codes import Role, Status
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.people import PractitionerRole, role_holder
from diucs.domain.model.registration import Invitation
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.london_time import to_london

STEP_PROMPT: Final = "prompt"
LADDER: Final = (
    ("reminder", WorkKind.REMINDER),
    ("phone-task", WorkKind.PHONE_TASK),
    ("escalate", WorkKind.ESCALATE_TO_LEAD),
)
"""The steps after the prompt, in order, with the scheduled work each one is (U06)."""
NO_ENDING: Final = "----"
"""What a cover made before its number was kept shows for the end of the number."""
NO_FIGURE: Final = "No figure yet"
COVER_ROLE: Final = "Cover"
LEAD_ONLY: Final = "only the shift lead may read this"


def check_lead(actor: Actor) -> None:
    if actor.role is not Role.LEAD:
        raise NotAllowed(LEAD_ONLY)


def ending(number: str | None, digits: int) -> str | None:
    """The last `digits` digits of a number, or None when there is none."""
    if not number:
        return None
    found = "".join(char for char in number if char.isdigit())
    return found[-digits:] if found else None


# ---------------------------------------------------------------------------------- overview


@dataclass(frozen=True, slots=True)
class LadderRow:
    step: str
    at: datetime
    done: bool


@dataclass(frozen=True, slots=True)
class ChaseItem:
    service_id: str
    name: str
    due_at: datetime
    overdue_minutes: int
    last_value_text: str
    ladder: tuple[LadderRow, ...]


@dataclass(frozen=True, slots=True)
class GettingOldItem:
    service_id: str
    name: str
    reported_at: datetime
    next_due_at: datetime
    status: Status


@dataclass(frozen=True, slots=True)
class CoveringItem:
    service_id: str
    name: str
    number_ending: str
    until: datetime


@dataclass(frozen=True, slots=True)
class LeadOverviewView:
    chasing: tuple[ChaseItem, ...]
    getting_old: tuple[GettingOldItem, ...]
    covering: tuple[CoveringItem, ...]
    counts: dict[Status, int]
    reporting_today: int


def _last_value_text(entry: BoardEntry) -> str:
    figure = entry.effective_available if entry.effective_available is not None else entry.used
    return NO_FIGURE if figure is None else f"{figure} {entry.unit_label}"


def _ladder(was_due: datetime, works: list[ScheduledWork]) -> tuple[LadderRow, ...]:
    """The prompt (done: it went out) and each later step. A step with a scheduled job of its own
    says whether it ran; one with none shows when it would have run, not done."""
    rows = [LadderRow(STEP_PROMPT, was_due, True)]
    for step, kind in LADDER:
        mine = sorted(
            (work for work in works if work.kind is kind and work.due_at >= was_due),
            key=lambda work: work.due_at,
        )
        if mine:
            rows.append(LadderRow(step, mine[0].due_at, mine[0].status == DONE))
        else:
            rows.append(LadderRow(step, was_due + LADDER_OFFSETS[kind], False))
    return tuple(rows)


class GetLeadOverview:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor) -> LeadOverviewView:
        check_lead(actor)
        now = self._clock.now()
        board = await QueryBoard(self._uow_factory, self._clock).execute(QueryBoardQuery(actor))
        counts = {status: 0 for status in Status}
        for entry in board.entries:
            counts[entry.status] += 1
        chasing: list[ChaseItem] = []
        covering: list[CoveringItem] = []
        async with self._uow_factory() as uow:
            for entry in board.entries:
                if (
                    entry.status is Status.NOT_UPDATED
                    and entry.was_due_at is not None
                    and not await _is_suspended(uow, entry.service_id)
                ):
                    works = await uow.scheduled_work.for_about(entry.service_id)
                    chasing.append(
                        ChaseItem(
                            service_id=entry.service_id,
                            name=entry.name,
                            due_at=entry.was_due_at,
                            overdue_minutes=int((now - entry.was_due_at).total_seconds() // 60),
                            last_value_text=_last_value_text(entry),
                            ladder=_ladder(entry.was_due_at, works),
                        )
                    )
                for role in await uow.people.reporter_roles_for_service(entry.service_id, now):
                    until = role.covered_until
                    if role.covered_by_practitioner_id is None or until is None or until <= now:
                        continue
                    number = await uow.contacts.get_phone(f"{COVER_KEY_PREFIX}{role.id}")
                    covering.append(
                        CoveringItem(
                            entry.service_id, entry.name, ending(number, 4) or NO_ENDING, until
                        )
                    )
            reports = await uow.capacity.last_report_times()
        today = to_london(now).date()
        getting_old = tuple(
            GettingOldItem(
                entry.service_id, entry.name, entry.reported_at, entry.next_due_at, entry.status
            )
            for entry in board.entries
            if entry.reported_at is not None
            and entry.next_due_at is not None
            and entry.status not in (Status.NOT_UPDATED, Status.OUT_OF_HOURS)
            and now - entry.reported_at > DEFAULT_POLICY.stale_warning_after
        )
        return LeadOverviewView(
            chasing=tuple(sorted(chasing, key=lambda item: (item.due_at, item.service_id))),
            getting_old=tuple(sorted(getting_old, key=lambda item: (item.reported_at, item.name))),
            covering=tuple(sorted(covering, key=lambda item: (item.name, item.service_id))),
            counts=counts,
            reporting_today=sum(
                1 for at in reports.values() if at is not None and to_london(at).date() == today
            ),
        )


async def _is_suspended(uow: UnitOfWork, service_id: str) -> bool:
    return any(
        flag.code == SERVICE_FLAG_SUSPENDED and flag.active
        for flag in await uow.flags.service_flags(service_id)
    )


# ----------------------------------------------------------------------------------- reporters


@dataclass(frozen=True, slots=True)
class ReporterView:
    service_id: str
    service_name: str
    role_id: str
    role: str
    channel: str | None
    number_ending: str | None
    covered_until: datetime | None


async def _service_name(uow: UnitOfWork, service_id: str) -> str:
    profile = await uow.services.get(service_id)
    if profile is None:
        raise NotFound("no service with this id")
    return profile.name


async def _label(uow: UnitOfWork, practitioner_id: str, fallback: str) -> str:
    person = await uow.people.get_practitioner(practitioner_id)
    return person.display_name if person is not None and person.display_name.strip() else fallback


class ListReporters:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(
        self, actor: Actor, service_id: str | None = None
    ) -> tuple[ReporterView, ...]:
        check_lead(actor)
        now = self._clock.now()
        views: list[ReporterView] = []
        async with self._uow_factory() as uow:
            if service_id is not None:
                profiles = [await uow.services.get(service_id)]
                if profiles[0] is None:
                    raise NotFound("no service with this id")
            else:
                profiles = list(await uow.services.list_active())
            for profile in sorted((p for p in profiles if p is not None), key=lambda p: p.id):
                for role in sorted(
                    await uow.people.reporter_roles_for_service(profile.id, now),
                    key=lambda item: item.id,
                ):
                    until = role.covered_until
                    covered = role.covered_by_practitioner_id is not None and (
                        until is not None and until > now
                    )
                    views.append(
                        ReporterView(
                            service_id=profile.id,
                            service_name=profile.name,
                            role_id=role.id,
                            role=await _label(uow, role.practitioner_id, role.code.value),
                            channel=None if role.channel is None else role.channel.value,
                            number_ending=ending(await uow.contacts.get_phone(role.id), 4),
                            covered_until=until if covered else None,
                        )
                    )
        return tuple(views)


# --------------------------------------------------------------------------------- suspension


@dataclass(frozen=True, slots=True)
class SuspensionView:
    suspended: bool
    since: datetime | None
    reason: str | None
    expired_requests: int | None
    register_number: str | None


class GetSuspension:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor, service_id: str) -> SuspensionView:
        check_lead(actor)
        async with self._uow_factory() as uow:
            await _service_name(uow, service_id)
            flag = next(
                (
                    item
                    for item in await uow.flags.service_flags(service_id)
                    if item.code == SERVICE_FLAG_SUSPENDED and item.active
                ),
                None,
            )
            phone = None if flag is None else await uow.services.work_phone(service_id)
        if flag is None:
            return SuspensionView(False, None, None, None, None)
        return SuspensionView(True, flag.at, flag.reason, flag.expired_count, phone)


# ---------------------------------------------------------------------------------- phones


@dataclass(frozen=True, slots=True)
class PhoneView:
    phone_ending: str
    role: str
    services: tuple[tuple[str, str], ...]
    channel: str | None
    last_seen: datetime | None


class ListPhones:
    """The phones that hold services now. A service belongs to the phone of whoever holds its post
    at this moment: the covering number while a cover runs, otherwise the post's own."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor) -> tuple[PhoneView, ...]:
        check_lead(actor)
        now = self._clock.now()
        groups: dict[tuple[str, str], list[tuple[PractitionerRole, str, str]]] = {}
        async with self._uow_factory() as uow:
            reports = await uow.capacity.last_report_times()
            for profile in await uow.services.list_active():
                for role in await uow.people.reporter_roles_for_service(profile.id, now):
                    holder = role_holder(role, now)
                    covered = holder != role.practitioner_id
                    key = f"{COVER_KEY_PREFIX}{role.id}" if covered else role.id
                    number = ending(await uow.contacts.get_phone(key), 3)
                    if number is None:
                        continue
                    groups.setdefault((holder, number), []).append((role, profile.id, profile.name))
            views: list[PhoneView] = []
            for (holder, number), members in groups.items():
                first = members[0][0]
                covered = holder != first.practitioner_id
                label = COVER_ROLE if covered else await _label(uow, holder, first.code.value)
                seen = [
                    reports[service]
                    for _, service, _ in members
                    if reports.get(service) is not None
                ]
                views.append(
                    PhoneView(
                        phone_ending=number,
                        role=label,
                        services=tuple(sorted((service, name) for _, service, name in members)),
                        channel=None if first.channel is None else first.channel.value,
                        last_seen=max((at for at in seen if at is not None), default=None),
                    )
                )
        return tuple(sorted(views, key=lambda view: (view.phone_ending, view.role)))


# ------------------------------------------------------------------------------- invitations


SETUP_STEPS: Final = (
    "invited",
    "numberChecked",
    "channelChosen",
    "installed",
    "notificationsOn",
    "pinSet",
    "firstReport",
)


@dataclass(frozen=True, slots=True)
class InvitationView:
    invitation_id: str
    service_name: str
    role: str
    steps: dict[str, bool]
    invited_at: datetime
    last_seen: datetime
    first_report_at: datetime | None


class ListInvitations:
    """Each invitation with how far the invited person's set-up has got, judged from what is
    stored: a text code checked on a device, the channel chosen in the registration, a device set
    up, a push subscription, a PIN, and the service's first report."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor) -> tuple[InvitationView, ...]:
        check_lead(actor)
        views: list[InvitationView] = []
        async with self._uow_factory() as uow:
            for invitation in await uow.registrations.list_invitations():
                views.append(await self._view(uow, invitation))
        return tuple(views)

    async def _view(self, uow: UnitOfWork, invitation: Invitation) -> InvitationView:
        person = invitation.invitee_id
        devices = await uow.devices.devices_of(person)
        verified = [d.last_verified_at for d in devices if d.last_verified_at is not None]
        registration = await uow.registrations.get(invitation.registration_id)
        reporting = None if registration is None else read_draft(registration).reporting
        pin_set = False
        for device in devices:
            if await uow.pins.get(person, device.device_id) is not None:
                pin_set = True
        report = await uow.capacity.latest(invitation.service_id)
        entry = await uow.scope.get_entry(invitation.service_id)
        seen = [invitation.sent_at, *verified, *(d.registered_at for d in devices)]
        steps = {
            "invited": True,
            "numberChecked": bool(verified),
            "channelChosen": reporting is not None and bool(reporting.channel),
            "installed": bool(devices),
            "notificationsOn": bool(await uow.push_subscriptions.for_practitioner(person)),
            "pinSet": pin_set,
            "firstReport": report is not None,
        }
        return InvitationView(
            invitation_id=invitation.id,
            service_name="" if entry is None else entry.name,
            role=invitation.role_label,
            steps=steps,
            invited_at=invitation.created_at,
            last_seen=max(seen),
            first_report_at=None if report is None else report.effective_at,
        )
