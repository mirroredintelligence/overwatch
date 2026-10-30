"""What the signed-in reporter's app reads and does (W7C, DEC-810 to DEC-820).

A reporter's session is a bearer token for one person and one device. Every call here asks the
graph which services that person holds a reporter role for, now (their own posts, and the posts
they cover), and a service outside that set is `NotFound`, the same refusal as an unknown id and
as another tenant's service (H-452). The token's `services` claim is never the answer: a cover that
started or ended since the token was made takes effect at once.

Reads: the services with their state, one service's prompt, the day's reports, the settings and
the set-up summary. Writes: a report (a confirm, a number, closed) through the same use cases as a
text reply or a link (`ReportCapacity`, `ConfirmCapacity`, with the reply policy's rules, so a Y
never makes an old figure current, H-31, H-32), several confirms in one call, the channel, a cover
number, and the answer to "do you look after this service".

The tenant's zone and policy come from the tenant's own record and configuration (DEC-353): the day
of the history, the due times and the end of a cover are all read in that zone. Nothing here holds
or returns a whole mobile number: settings show the masked number, and a cover number goes to the
protected contact store and is hashed for the practitioner (P10).
"""

import hashlib
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Final, Literal

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher, normalise_uk_mobile
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.application.tenant_settings import TenantZones, as_zones, read_settings
from diucs.application.use_cases.confirm_capacity import (
    ConfirmCapacity,
    ConfirmCapacityCommand,
)
from diucs.application.use_cases.link_access import (
    LinkGone,
    LinkOutOfRange,
    SendTheNumber,
    iso_utc,
    judge,
    number_after_prompt,
)
from diucs.application.use_cases.report_capacity import ReportCapacity, ReportCapacityCommand
from diucs.domain.codes import Channel, ReportSource, ReportType, Role
from diucs.domain.errors import (
    ConfirmLimitReached,
    LatestReportChanged,
    NotAllowed,
    NotFound,
    NothingToConfirm,
    ValidationFailed,
)
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.people import (
    REPORTER_ROLE_CODES,
    Practitioner,
    PractitionerRole,
    is_in_effect,
)
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import TenantPolicy
from diucs.domain.rules.multi_service import letters_for
from diucs.domain.rules.reply_parser import Confirm, Number
from diucs.domain.rules.reply_policy import (
    PromptState,
    RecordConfirm,
    RecordNumber,
    decide_capacity_reply,
)
from diucs.domain.rules.reporter_app import (
    MASKED_NOTHING,
    RowState,
    assess_row,
    channel_word,
    check_report,
    cover_end,
    local_day_bounds,
    mask_mobile,
)

SERVICE_NOT_YOURS: Final = "no service with this id"
MAX_BATCH: Final = 10
"""The most services one batch confirms: the phone load limit of a reporter (D28, DEC-048)."""
COVER_CONTACT_PREFIX: Final = "cover-"
"""The protected contact of a role's cover number is stored under `cover-<role id>`, beside the
role's own number, so a cover never replaces the number the role was invited on."""
DEFAULT_COVER_UNTIL: Final = "this-week"
"""[ASSUMED] The length of a cover the settings screen sets when it names none: the week."""
_ACCEPT_USE_CASE: Final = "ReporterAcceptService"
_COVER_USE_CASE: Final = "ReporterSetCover"
_CHANNEL_USE_CASE: Final = "ReporterSetChannel"
_AUDIT_ACTION: Final = "U"

type ReportResult = Literal["recorded", "outOfRange", "sendNumber", "confirmLimit"]


def _tenant_scope(uow: UnitOfWork) -> ScopeId:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _unknown_service() -> NotFound:
    return NotFound(SERVICE_NOT_YOURS)


@dataclass(frozen=True, slots=True)
class Held:
    """The reporter and the services they hold a role for at one instant."""

    practitioner: Practitioner
    roles: dict[str, PractitionerRole]
    """Service id to the role (the lowest role id when a person holds two for one service)."""
    names: dict[str, str]
    own: tuple[PractitionerRole, ...]
    """The active reporter posts the person owns, whatever their cover."""


async def held_services(uow: UnitOfWork, actor: Actor, now: datetime) -> Held:
    """The person behind a reporter token and what they hold now. Everything is read from the
    graph in the bound tenant. A person who is missing, has left, or holds no number has nothing."""
    _tenant_scope(uow)
    if actor.practitioner_id is None or actor.role is not Role.REPORTER:
        raise NotAllowed("only a reporter has a reporter app")
    person = await uow.people.get_practitioner(actor.practitioner_id)
    if person is None or not person.active:
        raise NotFound(SERVICE_NOT_YOURS)
    roles: dict[str, PractitionerRole] = {}
    names: dict[str, str] = {}
    if person.phone_hash is not None:
        for role, name in await uow.people.services_for_phone_hash(person.phone_hash, now):
            if role.service_id is None:
                continue
            held = roles.get(role.service_id)
            if held is None or role.id < held.id:
                roles[role.service_id] = role
                names[role.service_id] = name
    own = tuple(
        sorted(
            (
                role
                for role in await uow.people.roles_for_practitioner(person.id)
                if role.code in REPORTER_ROLE_CODES
                and role.service_id is not None
                and is_in_effect(role, now)
            ),
            key=lambda role: role.id,
        )
    )
    return Held(person, roles, names, own)


def _role_of(held: Held, service_id: str) -> PractitionerRole:
    role = held.roles.get(service_id)
    if role is None:
        raise _unknown_service()
    return role


# ---------------------------------------------------------------------------------------- reads


@dataclass(frozen=True, slots=True)
class ServiceRow:
    id: str
    name: str
    state: RowState
    recorded_value: int | None
    unit_label: str
    at: datetime | None
    next_due: datetime | None
    reply_by: datetime | None
    letter: str | None
    pending_acceptance: bool = False


@dataclass(frozen=True, slots=True)
class PromptView:
    service: str
    unit_label: str
    recorded_value: int | None
    as_of: datetime | None
    low: int
    high: int
    reply_by: datetime | None
    next_due: datetime | None


@dataclass(frozen=True, slots=True)
class HistoryItem:
    at: datetime
    value: int
    kind: str


@dataclass(frozen=True, slots=True)
class SettingsView:
    channel: str
    masked_phone: str
    masked_cover: str | None
    reverify_in_days: int
    other_devices: int


@dataclass(frozen=True, slots=True)
class SetupSummary:
    service: str
    contact_by: str
    masked_phone: str
    next_update_due: datetime | None
    text_code_in_days: int


async def _suspended(uow: UnitOfWork, profile: ServiceProfile) -> bool:
    if profile.suspended:
        return True
    return any(
        flag.code == SERVICE_FLAG_SUSPENDED and flag.active
        for flag in await uow.flags.service_flags(profile.id)
    )


class ReporterReader:
    """The reads of the reporter app."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, zones: TenantZones | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._zones = as_zones(zones)

    async def services(self, actor: Actor) -> list[ServiceRow]:
        """The active services the reporter holds, by name, each with its state. When two or more
        are due they carry the letters of a grouped prompt (D28)."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            held = await held_services(uow, actor, now)
            settings = await read_settings(uow, self._zones)
            rows: list[tuple[ServiceProfile, CapacityReport | None, RowState, ServiceRow]] = []
            for service_id in sorted(held.roles, key=lambda sid: (held.names[sid], sid)):
                profile = await uow.services.get(service_id)
                if profile is None or not profile.active:
                    continue
                latest = await uow.capacity.latest(service_id)
                assessed = assess_row(
                    profile,
                    suspended=await _suspended(uow, profile),
                    latest_at=None if latest is None else latest.effective_at,
                    now=now,
                    policy=settings.policy,
                    zone=settings.zone,
                )
                row = ServiceRow(
                    id=profile.id,
                    name=profile.name,
                    state=assessed.state,
                    recorded_value=None if latest is None else latest.value,
                    unit_label=profile.unit_label,
                    at=None if latest is None else latest.effective_at,
                    next_due=assessed.next_due,
                    reply_by=assessed.reply_by,
                    letter=None,
                )
                rows.append((profile, latest, assessed.state, row))
        due = [row.name for _, _, state, row in rows if state is RowState.DUE]
        letters = letters_for(due) if len(due) > 1 else {}
        return [replace(row, letter=letters.get(row.name)) for _, _, _, row in rows]

    async def prompt(self, actor: Actor, service_id: str) -> PromptView:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            held = await held_services(uow, actor, now)
            _role_of(held, service_id)
            profile = await uow.services.get(service_id)
            if profile is None or not profile.active:
                raise _unknown_service()
            settings = await read_settings(uow, self._zones)
            latest = await uow.capacity.latest(service_id)
            assessed = assess_row(
                profile,
                suspended=await _suspended(uow, profile),
                latest_at=None if latest is None else latest.effective_at,
                now=now,
                policy=settings.policy,
                zone=settings.zone,
            )
        return PromptView(
            service=profile.name,
            unit_label=profile.unit_label,
            recorded_value=None if latest is None else latest.value,
            as_of=None if latest is None else latest.effective_at,
            low=profile.usual_range[0],
            high=profile.usual_range[1],
            reply_by=assessed.reply_by,
            next_due=assessed.next_due,
        )

    async def history(self, actor: Actor, service_id: str) -> list[HistoryItem]:
        """The reports of this service in the tenant's local day, newest first."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            held = await held_services(uow, actor, now)
            _role_of(held, service_id)
            settings = await read_settings(uow, self._zones)
            start, end = local_day_bounds(now, settings.zone)
            reports = await uow.capacity.reports_since(service_id, start)
        items = [
            HistoryItem(report.effective_at, report.value, report.report_type.value)
            for report in reports
            if start <= report.effective_at < end
            and report.report_type in (ReportType.NUMBER, ReportType.CONFIRMED)
        ]
        return sorted(items, key=lambda item: item.at, reverse=True)

    async def settings(self, actor: Actor) -> SettingsView:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            held = await held_services(uow, actor, now)
            settings = await read_settings(uow, self._zones)
            role = held.own[0] if held.own else None
            number = None if role is None else await uow.contacts.get_phone(role.id)
            covered = next(
                (
                    own
                    for own in held.own
                    if own.covered_until is not None and own.covered_until > now
                ),
                None,
            )
            cover_number = (
                None
                if covered is None
                else await uow.contacts.get_phone(f"{COVER_CONTACT_PREFIX}{covered.id}")
            )
            verified = (
                None
                if actor.device_id is None
                else await uow.devices.verified_at(held.practitioner.id, actor.device_id)
            )
            active = await uow.devices.count_active(held.practitioner.id)
            this_phone = actor.device_id is not None and await uow.devices.known(
                held.practitioner.id, actor.device_id
            )
        return SettingsView(
            channel=channel_word(None if role is None else role.channel),
            masked_phone=MASKED_NOTHING if number is None else mask_mobile(number),
            masked_cover=(
                None
                if covered is None
                else (MASKED_NOTHING if cover_number is None else mask_mobile(cover_number))
            ),
            reverify_in_days=_days_left(verified, now, settings.policy),
            other_devices=max(0, active - (1 if this_phone else 0)),
        )

    async def setup_summary(self, actor: Actor) -> SetupSummary:
        """What the All-set page says: the service (the first by name; the invited post may be on a
        service that is not live yet), how the reporter is contacted, the masked number, the next
        update and the days until the text code is needed again."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            held = await held_services(uow, actor, now)
            settings = await read_settings(uow, self._zones)
            if not held.own:
                raise _unknown_service()
            role = held.own[0]
            if role.service_id is None:
                raise _unknown_service()
            profile = await uow.services.get(role.service_id)
            if profile is None:
                raise _unknown_service()
            number = await uow.contacts.get_phone(role.id)
            verified = (
                None
                if actor.device_id is None
                else await uow.devices.verified_at(held.practitioner.id, actor.device_id)
            )
            latest = await uow.capacity.latest(profile.id)
            assessed = assess_row(
                profile,
                suspended=False,
                latest_at=None if latest is None else latest.effective_at,
                now=now,
                policy=settings.policy,
                zone=settings.zone,
            )
        return SetupSummary(
            service=profile.name,
            contact_by=channel_word(role.channel),
            masked_phone=MASKED_NOTHING if number is None else mask_mobile(number),
            next_update_due=assessed.next_due,
            text_code_in_days=_days_left(verified, now, settings.policy),
        )


def _days_left(verified: datetime | None, now: datetime, policy: TenantPolicy) -> int:
    """Whole days before the 30-day check (the tenant's period), 0 when due or never verified."""
    if verified is None:
        return 0
    remaining = policy.reverify_every - (now - verified)
    if remaining.total_seconds() <= 0:
        return 0
    return int(-(-remaining.total_seconds() // 86400))


# --------------------------------------------------------------------------------------- reports


@dataclass(frozen=True, slots=True)
class ReporterReportCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    kind: str
    value: int | None = None
    confirm_out_of_range: bool = False


@dataclass(frozen=True, slots=True)
class ReportOutcome:
    result: ReportResult
    service_name: str = ""
    value: int | None = None
    recorded_at: datetime | None = None
    next_due: datetime | None = None
    low: int | None = None
    high: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class BatchItem:
    service_id: str
    result: ReportResult
    at: datetime | None = None
    reason: str | None = None


class ReporterReporter:
    """Records what the reporter says about a service: through the capacity use cases, under the
    reply policy, and only for a service the reporter holds."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        reports: ReportCapacity,
        confirms: ConfirmCapacity,
        zones: TenantZones | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._reports = reports
        self._confirms = confirms
        self._zones = as_zones(zones)

    async def report(self, command: ReporterReportCommand) -> ReportOutcome:
        figure = check_report(command.kind, command.value)
        if not isinstance(command.confirm_out_of_range, bool):
            raise ValidationFailed("confirmOutOfRange", "must be true or false")
        if command.confirm_out_of_range and command.kind != "number":
            raise ValidationFailed("confirmOutOfRange", "only a number can be confirmed")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            held = await held_services(uow, command.actor, now)
            role = _role_of(held, command.service_id)
            profile = await uow.services.get(command.service_id)
            if profile is None or not profile.active:
                raise _unknown_service()
            settings = await read_settings(uow, self._zones)
            latest = await uow.capacity.latest(profile.id)
            trailing = await uow.capacity.trailing_confirmations(profile.id)
            since = (
                command.kind == "confirm"
                and latest is not None
                and await number_after_prompt(uow, profile.id, latest, now)
            )
        state = PromptState(
            service_id=profile.id,
            # The app is open whenever the reporter is in it: there is no prompt to be late for.
            reply_by=now + settings.policy.reply_window,
            recorded_value=None if latest is None else latest.value,
            consecutive_confirms=trailing,
            last_accepted_at=None if latest is None else latest.effective_at,
            last_accepted_value=None if latest is None else latest.value,
            pending_out_of_range=figure if command.confirm_out_of_range else None,
            usual_range=profile.usual_range,
        )
        reply = Confirm() if command.kind == "confirm" else Number(0 if figure is None else figure)
        try:
            decision = judge(
                decide_capacity_reply(reply, state, now, settings.policy),
                profile,
                latest,
                now,
                since,
            )
        except LinkOutOfRange as refused:
            return ReportOutcome(
                "outOfRange",
                service_name=profile.name,
                value=figure,
                low=refused.usual_min,
                high=refused.usual_max,
            )
        except SendTheNumber as refused:
            return _send_number(profile, refused.reason)
        except LinkGone:
            raise _unknown_service() from None

        actor = replace(command.actor, service_ids=frozenset(held.roles))
        try:
            written = await self._write(command, actor, role, profile, latest, decision)
        except SendTheNumber as refused:
            return _send_number(profile, refused.reason)
        async with self._uow_factory() as uow:
            stored = await uow.capacity.get(written.report_id)
        if stored is None:
            raise RuntimeError("the report that was just stored cannot be read")
        return ReportOutcome(
            "recorded",
            service_name=profile.name,
            value=stored.value,
            recorded_at=stored.effective_at,
            next_due=written.next_due,
        )

    async def _write(
        self,
        command: ReporterReportCommand,
        actor: Actor,
        role: PractitionerRole,
        profile: ServiceProfile,
        latest: CapacityReport | None,
        decision: RecordNumber | RecordConfirm,
    ) -> _Written:
        try:
            if isinstance(decision, RecordNumber):
                result = await self._reports.execute(
                    ReportCapacityCommand(
                        idempotency_key=command.idempotency_key,
                        actor=actor,
                        service_id=profile.id,
                        value=decision.value,
                        source=ReportSource.APP,
                        performer_role_id=role.id,
                        replaced_value=(
                            latest.value if decision.is_correction and latest is not None else None
                        ),
                        flag=decision.flag,
                    )
                )
                return _Written(result.report_id, result.next_due)
            confirmed = await self._confirms.execute(
                ConfirmCapacityCommand(
                    idempotency_key=command.idempotency_key,
                    actor=actor,
                    service_id=profile.id,
                    source=ReportSource.APP,
                    performer_role_id=role.id,
                    expected_latest_id=None if latest is None else latest.id,
                )
            )
            return _Written(confirmed.report_id, confirmed.next_due)
        except LatestReportChanged:
            raise SendTheNumber("changed") from None
        except ConfirmLimitReached:
            raise SendTheNumber("limit") from None
        except NothingToConfirm:
            raise SendTheNumber("no-figure") from None
        except NotFound, NotAllowed:
            raise _unknown_service() from None

    async def batch(self, actor: Actor, key: str, service_ids: list[str]) -> list[BatchItem]:
        """Confirm several services in one call. Every service must be the reporter's own, or
        nothing is written (one refusal, as an unknown service). Each confirm then runs on its own
        under the key and the service, so a repeat of the call repeats nothing and one service that
        must send a number does not stop the others."""
        if not 1 <= len(service_ids) <= MAX_BATCH:
            raise ValidationFailed("items", "must name from one to ten services")
        if len(set(service_ids)) != len(service_ids):
            raise ValidationFailed("items", "must name each service once")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            held = await held_services(uow, actor, now)
        for service_id in service_ids:
            _role_of(held, service_id)
        results: list[BatchItem] = []
        for service_id in service_ids:
            outcome = await self.report(
                ReporterReportCommand(
                    idempotency_key=_item_key(key, service_id),
                    actor=actor,
                    service_id=service_id,
                    kind="confirm",
                )
            )
            results.append(
                BatchItem(
                    service_id=service_id,
                    result=outcome.result,
                    at=outcome.recorded_at,
                    reason=outcome.reason,
                )
            )
        return results


@dataclass(frozen=True, slots=True)
class _Written:
    report_id: str
    next_due: datetime | None


def _item_key(key: str, service_id: str) -> str:
    """The key of one service's confirm inside a batch: a digest, so it stays inside the key
    length and names no service."""
    return hashlib.sha256(f"{key}|{service_id}".encode()).hexdigest()


def _send_number(profile: ServiceProfile, reason: str) -> ReportOutcome:
    if reason == "limit":
        return ReportOutcome("confirmLimit", service_name=profile.name, reason=reason)
    return ReportOutcome("sendNumber", service_name=profile.name, reason=reason)


# ---------------------------------------------------------------------------------------- writes


@dataclass(frozen=True, slots=True)
class CoverCommand:
    actor: Actor
    phone: str = field(repr=False)
    until: str | None = None
    day: date | None = None
    service_id: str | None = None


@dataclass(frozen=True, slots=True)
class CoverResult:
    covered_until: datetime
    services: int


class ReporterSettingsWriter:
    """The writes of the settings and the service screens: the channel, a cover number and the
    answer to a service the lead added."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        phone_hasher: PhoneHasher,
        zones: TenantZones | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._hasher = phone_hasher
        self._zones = as_zones(zones)

    async def set_channel(self, actor: Actor, channel: Channel) -> str:
        """Set how the reporter is contacted, on every post they own. `email` needs an address on
        record for the post (the lead's invitation holds none unless one was given)."""
        if not isinstance(channel, Channel):
            raise ValidationFailed("channel", "must be a channel")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow)
            held = await held_services(uow, actor, now)
            if not held.own:
                raise _unknown_service()
            if channel is Channel.EMAIL:
                for role in held.own:
                    if await uow.contacts.get_email(role.id) is None:
                        raise ValidationFailed("channel", "there is no email address on record")
            for role in held.own:
                await uow.people.save_role(replace(role, channel=channel))
            await uow.audit.append(
                AuditEntry(
                    action=_AUDIT_ACTION,
                    use_case=_CHANNEL_USE_CASE,
                    actor=replace(actor, tenant_id=scope.value),
                    entity_ids=tuple(role.id for role in held.own),
                    snapshot={"channel": channel.value},
                    at=now,
                )
            )
            await uow.commit()
        return channel_word(channel)

    async def set_cover(self, command: CoverCommand) -> CoverResult:
        """Hand the reporter's own posts (all of them, or one service) to a cover phone until 23:59
        local on the day chosen. The number is held as the post's cover contact and as the covering
        practitioner's hash; the post's own number is untouched. Only a post the reporter owns can
        be handed on: a post they cover themselves cannot be passed again."""
        try:
            national = normalise_uk_mobile(command.phone)
        except ValidationFailed:
            raise ValidationFailed("phone", "must be a UK mobile number") from None
        cover_hash = self._hasher.hash(national)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow)
            held = await held_services(uow, command.actor, now)
            settings = await read_settings(uow, self._zones)
            ends = cover_end(
                DEFAULT_COVER_UNTIL if command.until is None else command.until,
                command.day,
                now,
                settings.zone,
            )
            targets = [
                role
                for role in held.own
                if command.service_id is None or role.service_id == command.service_id
            ]
            if command.service_id is not None:
                _role_of(held, command.service_id)
            if not targets:
                raise _unknown_service()
            if cover_hash == held.practitioner.phone_hash:
                raise ValidationFailed("phone", "is already your own number")
            cover = await uow.people.find_by_phone_hash(cover_hash)
            if cover is None:
                cover = Practitioner(
                    id=self._ids.new_id(),
                    active=True,
                    display_name="Cover",
                    phone_hash=cover_hash,
                )
                await uow.people.save_practitioner(cover)
            for role in targets:
                await uow.people.save_role(
                    replace(role, covered_by_practitioner_id=cover.id, covered_until=ends)
                )
                await uow.contacts.put_phone(
                    f"{COVER_CONTACT_PREFIX}{role.id}", _international(national)
                )
            await uow.audit.append(
                AuditEntry(
                    action=_AUDIT_ACTION,
                    use_case=_COVER_USE_CASE,
                    actor=replace(command.actor, tenant_id=scope.value),
                    entity_ids=tuple(role.id for role in targets),
                    snapshot={
                        "cover_phone_hash": cover_hash,
                        "covered_until": iso_utc(ends) or "",
                        "service_count": str(len(targets)),
                    },
                    at=now,
                )
            )
            await uow.commit()
        return CoverResult(covered_until=ends, services=len(targets))

    async def accept(self, actor: Actor, service_id: str, accept: bool) -> bool:
        """The reporter's answer to a service the lead added. Yes is recorded (audit) and changes
        nothing else; no ends the reporter's own post on that service now, and the service keeps
        its other reporters. A post the reporter only covers is not theirs to give up."""
        if not isinstance(accept, bool):
            raise ValidationFailed("accept", "must be true or false")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow)
            held = await held_services(uow, actor, now)
            _role_of(held, service_id)
            own = next((role for role in held.own if role.service_id == service_id), None)
            if own is None:
                raise _unknown_service()
            if not accept:
                await uow.people.save_role(replace(own, active=False, period_end=now))
            await uow.audit.append(
                AuditEntry(
                    action=_AUDIT_ACTION,
                    use_case=_ACCEPT_USE_CASE,
                    actor=replace(actor, tenant_id=scope.value),
                    entity_ids=(own.id, service_id),
                    snapshot={"accepted": "yes" if accept else "no"},
                    at=now,
                )
            )
            await uow.commit()
        return accept


def _international(national: str) -> str:
    """The stored form of a mobile, as the invitation keeps it: +44 and the national digits."""
    return f"+44{national[1:]}"


__all__ = [
    "BatchItem",
    "CoverCommand",
    "CoverResult",
    "HistoryItem",
    "PromptView",
    "ReportOutcome",
    "ReporterReader",
    "ReporterReportCommand",
    "ReporterReporter",
    "ReporterSettingsWriter",
    "ServiceRow",
    "SettingsView",
    "SetupSummary",
    "held_services",
]
