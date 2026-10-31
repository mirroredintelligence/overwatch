"""ReportCapacity: record a new capacity figure for a service (U01).

Every reporting path (text, link, app, advisor phoned) ends here. The change, its audit entry, its
outbox messages and the idempotency record are written in one unit of work (DEC-084, DEC-090).
Rules: domain-rules 1.2 to 1.6 through compute_status; decisions DEC-100 for the choices the
prompt leaves open. A report that breaks a flag rule (domain-rules 2.3) is stored with its flags
in the same unit of work (U07, DEC-161); the flags never change or hold back the report.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

from diucs.application.actor import Actor, require_actor_in_bound_tenant
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.outbox import OutboxMessage, outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantMismatch, TenantNotBound
from diucs.application.tenant_settings import TenantZones, as_zones, read_settings
from diucs.application.use_cases.missed_report_ladder import stop_answered_ladders
from diucs.application.use_cases.report_flags import raise_report_flags
from diucs.domain.codes import (
    Channel,
    ReportFlagReason,
    ReportSource,
    ReportType,
    Role,
    Status,
)
from diucs.domain.errors import (
    Conflict,
    DomainError,
    EffectiveBeforeConfirmation,
    EffectiveNotAfterLatest,
    NotAllowed,
    NotFound,
    ValidationFailed,
)
from diucs.domain.events import CapacityReported, StatusChanged
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.people import REPORTER_ROLE_CODES, PractitionerRole
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.effective_time import default_effective_at, is_later_than_latest
from diucs.domain.rules.london_time import LONDON, format_hhmm, format_stamp
from diucs.domain.rules.schedule import next_due
from diucs.domain.rules.status import compute_status

MIN_VALUE: Final = 0
MAX_VALUE: Final = 999
"""A figure is a whole number from 0 to 999. 0 means closed to referrals (domain-rules, U01)."""

CAPACITY_TOPIC: Final = "capacity.events"
MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE: Final = "SendMessage"
USE_CASE: Final = "ReportCapacity"
AUDIT_ACTION: Final = "C"


@dataclass(frozen=True, slots=True)
class ReportCapacityCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    value: int
    source: ReportSource
    effective_at: datetime | None = None
    performer_role_id: str | None = None
    replaced_value: int | None = None
    flag: ReportFlagReason | None = None
    send_echo: bool = True
    """False when the caller sends its own reply: U05 answers a grouped text with one C10 (DEC-148).
    The performer is recorded either way."""
    audit_detail: tuple[tuple[str, str], ...] = ()
    """Extra text keys added to the audit snapshot, as sorted-by-caller (name, value) pairs. The
    advisor's answer to a phone call is recorded this way (U13, DEC-292). Empty for every other
    caller, so their snapshots do not change."""


@dataclass(frozen=True, slots=True)
class ReportCapacityResult:
    report_id: str
    status: Status
    status_changed: bool
    next_due: datetime | None
    replayed: bool = False
    flag_ids: tuple[str, ...] = ()
    """The report flags this report raised (U07), in the order raised; empty when none."""


def _check_figure(field: str, value: int) -> None:
    if not MIN_VALUE <= value <= MAX_VALUE:
        raise ValidationFailed(field, "must be from 0 to 999")


def check_may_report(actor: Actor, source: ReportSource, service_id: str) -> None:
    """A reporter reports for their own services, from any source but advisor-phoned, which only
    an advisor or lead may name. An advisor or lead reports any service, only as advisor-phoned
    (DEC-100 item 3)."""
    if actor.role is Role.REPORTER:
        if source is ReportSource.ADVISOR_PHONED or service_id not in actor.service_ids:
            raise NotAllowed("a reporter may report only for their own services")
        return
    if actor.role in (Role.ADVISOR, Role.LEAD) and source is ReportSource.ADVISOR_PHONED:
        return
    raise NotAllowed("this role may not report this capacity")


PERFORMER_NOT_FOUND: Final = "no practitioner role with this id"


def check_performer(
    role: PractitionerRole | None, *, service_id: str, actor: Actor, now: datetime
) -> None:
    """The performer of a report is a role the actor holds for this service (TEN-024). The role was
    read through the tenant-bound store, so another tenant's role id arrives as None; every way a
    role can be wrong (unknown, another tenant's, inactive, of another service, not a reporter's,
    not yet started, held by someone else, or the actor is no person) is the one NotFound, so the
    refusal tells a caller nothing about which. The holder is the owner or the practitioner covering
    the role, whichever the actor is: a reply sent while a cover was in force and processed after it
    ended is still that person's reply (the text path judges it at its received time, DEC-148).
    The role's end is not checked, for the same reason."""
    holders = (
        None if role is None else {role.practitioner_id, role.covered_by_practitioner_id} - {None}
    )
    if (
        role is None
        or holders is None
        or not role.active
        or role.service_id != service_id
        or role.code not in REPORTER_ROLE_CODES
        or actor.practitioner_id is None
        or actor.practitioner_id not in holders
        or role.period_start.astimezone(UTC) > now.astimezone(UTC)
    ):
        raise NotFound(PERFORMER_NOT_FOUND)


def _echo_text(
    profile: ServiceProfile,
    report: CapacityReport,
    next_prompt: datetime,
    replaced_value: int | None,
    zone: ZoneInfo = LONDON,
) -> tuple[MessageId, str]:
    """The C3 echo, or the C4 echo when a figure is replaced (DEC-100 item 1). The times are the
    tenant's local times, in `zone` (KI-415)."""
    recorded_at = format_hhmm(report.effective_at, zone)
    if replaced_value is not None:
        rendered = render(
            MessageId.C4,
            Channel.TEXT,
            service=profile.name,
            value=report.value,
            unit=profile.unit_label,
            recorded_at=recorded_at,
            replaced=replaced_value,
        )
        return MessageId.C4, rendered.text
    rendered = render(
        MessageId.C3,
        Channel.TEXT,
        service=profile.name,
        value=report.value,
        unit=profile.unit_label,
        recorded_at=recorded_at,
        next_due=format_hhmm(next_prompt, zone),
    )
    return MessageId.C3, rendered.text


async def record_report(
    uow: UnitOfWork,
    *,
    profile: ServiceProfile,
    report: CapacityReport,
    actor: Actor,
    now: datetime,
    ids: IdGenerator,
    send_echo: str | None,
    replaced_value: int | None,
    use_case: str = USE_CASE,
    audit_snapshot: dict[str, Any] | None = None,
    flag: ReportFlagReason | None = None,
    audit_detail: tuple[tuple[str, str], ...] = (),
    policy: TenantPolicy = DEFAULT_POLICY,
    config_version: int | None = None,
    zone: ZoneInfo = LONDON,
) -> ReportCapacityResult:
    """Store one report with its status change, echo, audit entry and outbox messages, inside the
    caller's unit of work. The caller commits. U02 reuses this function (DEC-100).

    `send_echo` is the performer role to echo to, or None for no echo. The caller passes the
    performer only when the source is text. A suspended service (an active suspended flag) is
    read as suspended for the status before and after the report.

    `use_case` names the caller in the audit entry, and `audit_snapshot` replaces the default
    snapshot when a caller records its own (U02, DEC-112 item 1). `flag` is a reason the caller
    has already decided (the reply policy's `out-of-range-twice`); the flag rules of D12 are
    always applied as well (U07, DEC-161). The caller holds the service lock.

    `policy` is the tenant's policy (TEN-024): the status, the next prompt and the flag windows read
    it, and the default is today's behaviour. `config_version` is the version of the tenant
    configuration the policy came from; the default audit snapshot records it, and leaves the key
    out when no version is in force (the built-in defaults). `zone` is the tenant's time zone: the
    status, the next prompt and the echo's times are read in it (KI-415).
    """
    flags: Sequence[ServiceFlag] = await uow.flags.service_flags(profile.id)
    if any(flag.code == SERVICE_FLAG_SUSPENDED for flag in flags):
        profile = replace(profile, suspended=True)

    latest_before = await uow.capacity.latest(profile.id)
    since = now
    confirmed = await uow.bookings.confirmed_since(profile.id, since)
    before = compute_status(profile, latest_before, confirmed, now, policy, zone).status
    after = compute_status(profile, report, confirmed, now, policy, zone).status

    await uow.capacity.add(report)

    events: list[CapacityReported | StatusChanged] = [
        CapacityReported(
            service_id=profile.id,
            report_id=report.id,
            value=report.value,
            source=report.source,
            at=now,
        )
    ]
    if before is not after:
        events.append(StatusChanged(service_id=profile.id, before=before, after=after, at=now))
    for event in events:
        await uow.outbox.add(outbox_message_for(event, id=ids.new_id(), now=now))

    flag_ids = await raise_report_flags(
        uow, ids, profile=profile, report=report, extra=flag, now=now, policy=policy
    )
    # A report at or after a prompt's due time answers it: the rest of its missed-report ladder is
    # cancelled in this unit of work (U06, domain-rules 1.5). prompt-due work is left alone.
    await stop_answered_ladders(
        uow, profile.id, answered_at=report.effective_at, now=now, policy=policy
    )

    next_prompt = next_due(profile, now, policy, zone)
    if send_echo is not None:
        # Unreachable for a valid profile: every window yields a due time on each day it starts,
        # and SEARCH_DAYS covers more than a week. Refusing here is the only honest outcome.
        if next_prompt is None:
            raise DomainError("a profile with available times always has a next due instant")
        message_id, text = _echo_text(profile, report, next_prompt, replaced_value, zone)
        communication = Communication(
            id=ids.new_id(),
            message_id=message_id.value,
            channel=Channel.TEXT,
            recipient_role_id=send_echo,
            about_id=profile.id,
            payload_text=text,
            sent_at=now,
            delivery_status="queued",
        )
        await uow.communications.add(communication)
        await uow.outbox.add(
            OutboxMessage(
                id=ids.new_id(),
                topic=MESSAGES_TOPIC,
                event_type=SEND_MESSAGE,
                payload={
                    "communication_id": communication.id,
                    "message_id": message_id.value,
                    "channel": Channel.TEXT.value,
                    "recipient_role_id": send_echo,
                    "text": text,
                },
                created_at=now,
            )
        )

    snapshot: dict[str, Any] = (
        audit_snapshot
        if audit_snapshot is not None
        else {
            "value": report.value,
            "source": report.source.value,
            "status_before": before.value,
            "status_after": after.value,
            **({} if config_version is None else {"config_version": config_version}),
        }
    )
    snapshot = {**snapshot, **dict(audit_detail)}
    await uow.audit.append(
        AuditEntry(
            action=AUDIT_ACTION,
            use_case=use_case,
            actor=actor,
            entity_ids=(report.id, profile.id, *flag_ids),
            snapshot=snapshot,
            at=now,
        )
    )
    return ReportCapacityResult(
        report_id=report.id,
        status=after,
        status_changed=before is not after,
        next_due=next_prompt,
        flag_ids=tuple(flag_ids),
    )


def _fingerprint(command: ReportCapacityCommand) -> str:
    """The command body and the actor who sent it, tenant included. A replay must match both
    (DEC-104); the tenant is a belt-and-braces term, as the store is already tenant-scoped
    (TEN-016, TEN-024)."""
    effective = None if command.effective_at is None else command.effective_at.isoformat()
    flag = None if command.flag is None else command.flag.value
    body = repr(
        (
            command.actor.tenant_id,
            command.service_id,
            command.value,
            command.source.value,
            effective,
            command.performer_role_id,
            command.replaced_value,
            flag,
            command.actor.role.value,
            command.actor.practitioner_id,
            command.send_echo,
            command.audit_detail,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _StoredReport:
    """What the idempotency store keeps for a command key: the result and the fingerprint of the
    command that made it (DEC-104)."""

    fingerprint: str
    result: ReportCapacityResult


def _replay(stored: object, fingerprint: str) -> ReportCapacityResult:
    """A stored result for this key replays only for the same command by the same actor. Any other
    stored value, including a key that ConfirmCapacity stored, is a Conflict, as it is there: it is
    refused before the time or the figure is judged."""
    if not isinstance(stored, _StoredReport) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different report")
    return replace(stored.result, replayed=True)


def _explicit_effective(given: datetime | None, now: datetime) -> datetime | None:
    """The command's effective time in UTC, or None when it gives none. A naive time, or one after
    `now` (read before the unit of work), is refused before any lock is taken."""
    if given is None:
        return None
    if given.utcoffset() is None:
        raise ValidationFailed("effective_at", "must include a timezone")
    if given > now:
        raise ValidationFailed("effective_at", "is after the current time")
    return given.astimezone(UTC)


class ReportCapacity:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        zones: TenantZones | None = None,
    ) -> None:
        """`zones` is the tenant's time zone source; None is London, the one zone on the allow-list
        (KI-415). The serving process passes `DirectoryZones`."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._zones = as_zones(zones)

    async def execute(self, command: ReportCapacityCommand) -> ReportCapacityResult:
        # Before anything is read, the early replay included: the actor's tenant is the bound one
        # (a wiring fault otherwise, never an access decision) and a tenant is bound at all.
        require_actor_in_bound_tenant(command.actor)
        if command.flag is not None and not isinstance(command.flag, ReportFlagReason):
            raise ValidationFailed("flag", "must be a report flag reason")
        fingerprint = _fingerprint(command)
        # An early read outside the unit of work. The authoritative replay check is inside it.
        early = await self._idempotency.get(command.idempotency_key)
        if early is not None:
            return _replay(early, fingerprint)

        _check_figure("value", command.value)
        if command.replaced_value is not None:
            _check_figure("replaced_value", command.replaced_value)
        explicit = _explicit_effective(command.effective_at, self._clock.now())

        async with self._uow_factory() as uow:
            # The unit opened under the actor's tenant, and under a tenant at all. Checked before
            # the lock, so a unit of another scope takes none.
            scope = uow.unit_scope
            if scope is None or scope.kind is not ScopeKind.TENANT:
                raise TenantNotBound
            if scope.value != command.actor.tenant_id:
                raise TenantMismatch
            # The service lock comes before every read that decides the report, and before the
            # default effective time is taken (DEC-139). A report that waits behind a confirmation
            # is therefore timed after it, so it sorts after the confirmation on the board.
            await uow.capacity.lock_service(command.service_id)
            # The authoritative replay check, before any write (DEC-106 item 2).
            stored = await uow.idempotency.get(command.idempotency_key)
            if stored is not None:
                return _replay(stored, fingerprint)

            profile = await uow.services.get(command.service_id)
            if profile is None or not profile.active:
                raise NotFound("no active service with this id")
            check_may_report(command.actor, command.source, profile.id)

            now = self._clock.now()
            if command.performer_role_id is not None:
                # After the permission check, so a caller who may not report learns nothing about
                # which roles exist; the store answers None for another tenant's role (TEN-024).
                check_performer(
                    await uow.people.get_role(command.performer_role_id),
                    service_id=profile.id,
                    actor=command.actor,
                    now=now,
                )
            settings = await read_settings(uow, self._zones)
            policy = settings.policy
            # The effective time is judged against the latest figure of the service, read under the
            # lock: a number that is not later than it would be hidden behind it, or tie with it, so
            # an explicit one is refused and nothing is written (DEC-140 as changed by DEC-1100 Q8,
            # KI-7, KI-9). With none given, the clock is used, but never at or before that figure
            # (KI-8).
            latest = await uow.capacity.latest(profile.id)
            latest_at = None if latest is None else latest.effective_at
            if (
                explicit is not None
                and latest is not None
                and not is_later_than_latest(explicit, latest.effective_at)
            ):
                refusal = (
                    EffectiveBeforeConfirmation
                    if latest.report_type is ReportType.CONFIRMED
                    else EffectiveNotAfterLatest
                )
                kind = "confirmed figure" if refusal is EffectiveBeforeConfirmation else "figure"
                raise refusal(
                    f"is not after the latest {kind} of this service, which is for "
                    f"{format_stamp(latest.effective_at, settings.zone)}",
                    latest.effective_at.astimezone(UTC),
                )
            effective = explicit if explicit is not None else default_effective_at(now, latest_at)

            report = CapacityReport(
                id=self._ids.new_id(),
                service_id=profile.id,
                value=command.value,
                measure=profile.measure,
                effective_at=effective,
                source=command.source,
                report_type=ReportType.NUMBER,
                performer_role_id=command.performer_role_id,
            )
            send_echo = (
                command.performer_role_id
                if command.source is ReportSource.TEXT and command.send_echo
                else None
            )
            result = await record_report(
                uow,
                profile=profile,
                report=report,
                actor=command.actor,
                now=now,
                ids=self._ids,
                send_echo=send_echo,
                replaced_value=command.replaced_value,
                flag=command.flag,
                audit_detail=command.audit_detail,
                policy=policy,
                config_version=settings.config_version,
                zone=settings.zone,
            )
            await uow.idempotency.put(command.idempotency_key, _StoredReport(fingerprint, result))
            await uow.commit()
        return result
