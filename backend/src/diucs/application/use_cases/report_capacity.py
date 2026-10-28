"""ReportCapacity: record a new capacity figure for a service (U01).

Every reporting path (text, link, app, advisor phoned) ends here. The change, its audit entry, its
outbox messages and the idempotency record are written in one unit of work (DEC-084, DEC-090).
Rules: domain-rules 1.2 to 1.6 through compute_status; decisions DEC-100 for the choices the
prompt leaves open.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.outbox import OutboxMessage, outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
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
    NotAllowed,
    NotFound,
    ValidationFailed,
)
from diucs.domain.events import CapacityReported, StatusChanged
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED, ServiceFlag
from diucs.domain.model.service import ServiceProfile
from diucs.domain.rules.london_time import format_hhmm
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


@dataclass(frozen=True, slots=True)
class ReportCapacityResult:
    report_id: str
    status: Status
    status_changed: bool
    next_due: datetime | None
    replayed: bool = False


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


def _echo_text(
    profile: ServiceProfile,
    report: CapacityReport,
    next_prompt: datetime,
    replaced_value: int | None,
) -> tuple[MessageId, str]:
    """The C3 echo, or the C4 echo when a figure is replaced (DEC-100 item 1)."""
    recorded_at = format_hhmm(report.effective_at)
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
        next_due=format_hhmm(next_prompt),
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
) -> ReportCapacityResult:
    """Store one report with its status change, echo, audit entry and outbox messages, inside the
    caller's unit of work. The caller commits. U02 reuses this function (DEC-100).

    `send_echo` is the performer role to echo to, or None for no echo. The caller passes the
    performer only when the source is text. A suspended service (an active suspended flag) is
    read as suspended for the status before and after the report.

    `use_case` names the caller in the audit entry, and `audit_snapshot` replaces the default
    snapshot when a caller records its own (U02, DEC-112 item 1).
    """
    flags: Sequence[ServiceFlag] = await uow.flags.service_flags(profile.id)
    if any(flag.code == SERVICE_FLAG_SUSPENDED for flag in flags):
        profile = replace(profile, suspended=True)

    latest_before = await uow.capacity.latest(profile.id)
    since = now
    confirmed = await uow.bookings.confirmed_since(profile.id, since)
    before = compute_status(profile, latest_before, confirmed, now).status
    after = compute_status(profile, report, confirmed, now).status

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

    next_prompt = next_due(profile, now)
    if send_echo is not None:
        # Unreachable for a valid profile: every window yields a due time on each day it starts,
        # and SEARCH_DAYS covers more than a week. Refusing here is the only honest outcome.
        if next_prompt is None:
            raise DomainError("a profile with available times always has a next due instant")
        message_id, text = _echo_text(profile, report, next_prompt, replaced_value)
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

    await uow.audit.append(
        AuditEntry(
            action=AUDIT_ACTION,
            use_case=use_case,
            actor=actor,
            entity_ids=(report.id, profile.id),
            snapshot=(
                audit_snapshot
                if audit_snapshot is not None
                else {
                    "value": report.value,
                    "source": report.source.value,
                    "status_before": before.value,
                    "status_after": after.value,
                }
            ),
            at=now,
        )
    )
    return ReportCapacityResult(
        report_id=report.id,
        status=after,
        status_changed=before is not after,
        next_due=next_prompt,
    )


def _fingerprint(command: ReportCapacityCommand) -> str:
    """The command body and the actor who sent it. A replay must match both (DEC-104)."""
    effective = None if command.effective_at is None else command.effective_at.isoformat()
    flag = None if command.flag is None else command.flag.value
    body = repr(
        (
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
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _StoredReport:
    """What the idempotency store keeps for a command key: the result and the fingerprint of the
    command that made it (DEC-104)."""

    fingerprint: str
    result: ReportCapacityResult


def _replay(stored: _StoredReport, fingerprint: str) -> ReportCapacityResult:
    if stored.fingerprint != fingerprint:
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
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency

    async def execute(self, command: ReportCapacityCommand) -> ReportCapacityResult:
        fingerprint = _fingerprint(command)
        # An early read outside the unit of work. The authoritative replay check is inside it.
        early = await self._idempotency.get(command.idempotency_key)
        if isinstance(early, _StoredReport):
            return _replay(early, fingerprint)

        _check_figure("value", command.value)
        if command.replaced_value is not None:
            _check_figure("replaced_value", command.replaced_value)
        if command.flag is not None:
            raise ValidationFailed(
                "flag", "report flags are recorded by U07, not by ReportCapacity"
            )
        explicit = _explicit_effective(command.effective_at, self._clock.now())

        async with self._uow_factory() as uow:
            # The service lock comes before every read that decides the report, and before the
            # default effective time is taken (DEC-139). A report that waits behind a confirmation
            # is therefore timed after it, so it sorts after the confirmation on the board.
            await uow.capacity.lock_service(command.service_id)
            # The authoritative replay check, before any write (DEC-106 item 2).
            stored = await uow.idempotency.get(command.idempotency_key)
            if isinstance(stored, _StoredReport):
                return _replay(stored, fingerprint)

            profile = await uow.services.get(command.service_id)
            if profile is None or not profile.active:
                raise NotFound("no active service with this id")
            check_may_report(command.actor, command.source, profile.id)

            now = self._clock.now()
            effective = now if explicit is None else explicit
            if explicit is not None:
                # A number back-dated behind the latest confirmed figure would never reach the
                # board, so it is refused and nothing is written (DEC-140).
                confirmed_at = await uow.capacity.latest_confirmation_at(profile.id)
                if confirmed_at is not None and explicit < confirmed_at:
                    raise EffectiveBeforeConfirmation(
                        "effective_at", "is before the latest confirmed figure of this service"
                    )

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
            )
            await uow.idempotency.put(command.idempotency_key, _StoredReport(fingerprint, result))
            await uow.commit()
        return result
