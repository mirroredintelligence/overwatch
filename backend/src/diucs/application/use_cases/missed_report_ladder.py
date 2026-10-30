"""MissedReportLadder: chase a service that has not answered its prompt (U06, DEC-166).

When a prompt goes unanswered, three jobs scheduled by SendPrompts (U03) run in turn, each about
the prompt's communication (or about the service, when nobody could be texted, DEC-115 item 15):

    +30 min  reminder    C8 to the reporter with a fresh link (reply by now + 30 min); the status
                         of the service moves to Not updated (StatusChanged on capacity.events)
    +60 min  phone task  PhoneTaskRaised on capacity.events, for the advisors
    +90 min  escalation  ReportEscalated on alerts.events, for the shift lead

A report with `effective_at` at or after the prompt's due time answers it and stops the rest
(domain-rules 1.5): `record_report` calls `stop_answered_ladders` in the unit of work that
stores the report, and each step looks again before it acts, under the service lock, so a report
that lands between the two is never missed. `prompt-due` jobs are never touched.

The offsets of the steps, the reminder's reply window and the times in the text are the tenant's own
policy and zone, and the link is on the tenant's own host (TEN-027, DEC-500). The tenant is not on
the command. It is the scope the consumer bound before it opened the unit of
work (DEC-130 item 3), read from `uow.unit_scope`, and it goes into the replay keys and the
sealed-content associated data (DEC-160, DEC-116). Rules: domain-rules 1.5, 2.1 (C8), 7 (links).
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Final

from diucs.application.actor import Actor, unit_tenant_scope
from diucs.application.idempotency import format_instant
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.outbox import OutboxMessage, outbox_message_for
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import cancel_work
from diucs.application.tenancy import ScopeId
from diucs.application.tenant_settings import (
    LinkBases,
    TenantSettings,
    TenantZones,
    as_link_base,
    as_zones,
    read_settings,
)
from diucs.application.use_cases.send_prompts import (
    LINK_PLACEHOLDER,
    LINK_PURPOSE,
    MESSAGES_TOPIC,
    SEND_MESSAGE,
    LinkTokenServiceFactory,
    _phone_hash,
    _send_payload,
)
from diucs.application.work import DONE, SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import Status
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.events import PhoneTaskRaised, ReportEscalated, StatusChanged
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.flags import SERVICE_FLAG_SUSPENDED
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import DEFAULT_POLICY, TenantPolicy
from diucs.domain.rules.freshness import ONE_MICROSECOND
from diucs.domain.rules.london_time import format_hhmm
from diucs.domain.rules.schedule import (
    ESCALATE_AFTER,
    PHONE_TASK_AFTER,
    REMINDER_AFTER,
    reply_by,
)
from diucs.domain.rules.status import compute_status

REMINDED: Final = "reminded"
PHONE_TASK_RAISED: Final = "phone-task"
ESCALATED: Final = "escalated"
STOPPED: Final = "stopped"
IGNORED: Final = "ignored"

LADDER_OFFSETS: Final[Mapping[WorkKind, timedelta]] = MappingProxyType(
    {
        WorkKind.REMINDER: REMINDER_AFTER,
        WorkKind.PHONE_TASK: PHONE_TASK_AFTER,
        WorkKind.ESCALATE_TO_LEAD: ESCALATE_AFTER,
    }
)
"""The ladder steps and how long after the prompt's due time each runs (domain-rules 1.5)."""

LADDER_KINDS: Final = tuple(LADDER_OFFSETS)

REMINDER_REPLY_WINDOW: Final = timedelta(minutes=30)
"""[ASSUMED] How long a reporter has to answer a reminder, from when it is sent (U06 prompt)."""

USE_CASE: Final = "MissedReportLadder"
AUDIT_ACTION: Final = "U"

_PROMPT_MESSAGES: Final = (MessageId.C1.value, MessageId.C2.value, MessageId.C9.value)
"""The messages that start a ladder. A reminder (C8) does not."""

_STATUS: Final = "status"
_PHONE_TASK: Final = "phone-task"
_ESCALATION: Final = "escalation"


@dataclass(frozen=True, slots=True)
class LadderStepCommand:
    idempotency_key: str
    actor: Actor
    work_id: str


@dataclass(frozen=True, slots=True)
class LadderStepResult:
    """What a step did. `communication_id` is the reminder it sent, or None when it sent nothing."""

    action: str
    communication_id: str | None = None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class _StoredStep:
    """What the replay store keeps for a command key: the result and the fingerprint of the command
    that made it (DEC-104)."""

    fingerprint: str
    result: LadderStepResult


@dataclass(frozen=True, slots=True)
class _Raised:
    """The marker that an alert, or a status change, has been raised for one missed report, by the
    step with this work id. It is kept under a key that names the tenant, the service and the due
    time, so a second reporter's ladder for the same missed report raises nothing more."""

    work_id: str


def ladder_offsets(policy: TenantPolicy = DEFAULT_POLICY) -> Mapping[WorkKind, timedelta]:
    """How long after the prompt's due time each step runs, in the tenant's policy."""
    return MappingProxyType(
        {
            WorkKind.REMINDER: policy.reminder_after,
            WorkKind.PHONE_TASK: policy.phone_task_after,
            WorkKind.ESCALATE_TO_LEAD: policy.escalate_after,
        }
    )


def ladder_due(work: ScheduledWork, policy: TenantPolicy = DEFAULT_POLICY) -> datetime:
    """The due time of the prompt a ladder step belongs to: the step's time less its offset in the
    tenant's policy. Anything but a ladder step has none and is refused."""
    offset = ladder_offsets(policy).get(work.kind)
    if offset is None:
        raise ValidationFailed("kind", "is not a missed-report ladder step")
    return work.due_at.astimezone(UTC) - offset


def prompt_answered(effective_at: datetime, due: datetime) -> bool:
    """A report answers a prompt when it is timed at or after the prompt's due time (domain-rules
    1.5). Instants are compared as UTC (lesson L52)."""
    return effective_at.astimezone(UTC) >= due.astimezone(UTC)


async def stop_answered_ladders(
    uow: UnitOfWork,
    service_id: str,
    *,
    answered_at: datetime,
    now: datetime,
    policy: TenantPolicy = DEFAULT_POLICY,
) -> tuple[str, ...]:
    """Cancel the scheduled ladder steps of this service that a report timed `answered_at` answers,
    in the caller's unit of work, and return their work ids. `prompt-due` work is never listed.

    The ladders are found through the service itself (the ladder of a service nobody could be
    texted for) and through the latest prompt of each of its reporter roles (the ladder of a
    prompt is about its communication, DEC-115 item 16). An older prompt's ladder, or one of a role
    that has since gone, is not listed; its steps stop themselves when they run (DEC-166 item 3).
    """
    about_ids = [service_id]
    for role in await uow.people.reporter_roles_for_service(service_id, now):
        prompt = await uow.communications.latest_prompt_for_phone([role.id], _PROMPT_MESSAGES)
        if prompt is not None:
            about_ids.append(prompt.id)
    cancelled: list[str] = []
    for about_id in about_ids:
        for kind in LADDER_KINDS:
            for work in await uow.scheduled_work.for_about(about_id, kind):
                if work.status == SCHEDULED and prompt_answered(
                    answered_at, ladder_due(work, policy)
                ):
                    await cancel_work(uow, work, now)
                    cancelled.append(work.id)
    return tuple(cancelled)


def _fingerprint(command: LadderStepCommand) -> str:
    """The step and the actor who ran it, as DEC-104 requires."""
    body = repr((command.work_id, command.actor.role.value, command.actor.practitioner_id))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _command_key(scope: ScopeId, key: str) -> str:
    """The replay key, made with the tenant: until the replay store is tenant-scoped (lesson L160)
    two tenants that use one key would refuse each other."""
    return f"ladder:{scope}:{key}"


def _marker_key(scope: ScopeId, what: str, service_id: str, due: datetime) -> str:
    return f"ladder-raised:{scope}:{what}:{service_id}:{format_instant(due)}"


def _replay(stored: _StoredStep, fingerprint: str) -> LadderStepResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different ladder step")
    return replace(stored.result, replayed=True)


async def _first_to_raise(
    uow: UnitOfWork, scope: ScopeId, what: str, service_id: str, due: datetime, work_id: str
) -> bool:
    """True when nothing has been raised yet for this missed report of this service, and this step
    now holds the marker. Each reporter's prompt has a ladder of its own, so a service with two
    reporters has two steps at each offset, and the advisors and the lead hear once."""
    key = _marker_key(scope, what, service_id, due)
    if await uow.idempotency.get(key) is not None:
        return False
    await uow.idempotency.put(key, _Raised(work_id))
    return True


class MissedReportLadder:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        link_tokens: LinkTokenServiceFactory,
        link_base_url: str | LinkBases,
        sealer: ContentSealer,
        zones: TenantZones | None = None,
    ) -> None:
        """`link_base_url` is the tenant source of the link (`DirectoryLinkBase` in the serving
        process); a plain string is one base for every tenant, for a test or a one-host
        deployment. `zones` is the tenant's time zone source; None is London."""
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._link_tokens = link_tokens
        self._links = as_link_base(link_base_url)
        self._sealer = sealer
        self._zones = as_zones(zones)

    async def execute(self, command: LadderStepCommand) -> LadderStepResult:
        fingerprint = _fingerprint(command)
        async with self._uow_factory() as uow:
            scope = unit_tenant_scope(uow.unit_scope)
            key = _command_key(scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _StoredStep):
                return _replay(stored, fingerprint)

            settings = await read_settings(uow, self._zones)
            work = await uow.scheduled_work.get(command.work_id)
            due = ladder_due(work, settings.policy)
            prompt = await uow.communications.get(work.about_id)
            service_id = work.about_id if prompt is None else prompt.about_id
            profile = None if service_id is None else await uow.services.get(service_id)
            if profile is None:
                # Another tenant's work reads as not found here: its service is not in this scope.
                raise NotFound("no service for this ladder step")

            # The service lock comes before the figure is read, and the work is read again after it:
            # a report that holds the lock cancels the step in its own unit of work, and a step that
            # waited behind it must see that (H-13).
            await uow.capacity.lock_service(profile.id)
            work = await uow.scheduled_work.get(work.id)
            if work.status != SCHEDULED:
                return LadderStepResult(IGNORED)

            at = max(self._clock.now().astimezone(UTC), work.due_at)
            result = await self._run(uow, scope, settings, command, work, prompt, profile, due, at)
            await uow.idempotency.put(key, _StoredStep(fingerprint, result))
            await uow.commit()
        return result

    async def _run(
        self,
        uow: UnitOfWork,
        scope: ScopeId,
        settings: TenantSettings,
        command: LadderStepCommand,
        work: ScheduledWork,
        prompt: Communication | None,
        profile: ServiceProfile,
        due: datetime,
        at: datetime,
    ) -> LadderStepResult:
        latest = await uow.capacity.latest(profile.id)
        flags = await uow.flags.service_flags(profile.id)
        suspended = any(flag.code == SERVICE_FLAG_SUSPENDED for flag in flags)
        if (latest is not None and prompt_answered(latest.effective_at, due)) or (
            not profile.active or suspended
        ):
            await self._cancel_rest(uow, work, due, at, settings.policy)
            result = LadderStepResult(STOPPED)
        elif work.kind is WorkKind.REMINDER:
            result = await self._remind(
                uow, scope, settings, work, prompt, profile, latest, due, at
            )
        elif work.kind is WorkKind.PHONE_TASK:
            raised = await _first_to_raise(uow, scope, _PHONE_TASK, profile.id, due, work.id)
            if raised:
                event = PhoneTaskRaised(service_id=profile.id, due_at=due, at=at)
                await uow.outbox.add(outbox_message_for(event, id=self._ids.new_id(), now=at))
            result = LadderStepResult(PHONE_TASK_RAISED if raised else IGNORED)
        else:
            raised = await _first_to_raise(uow, scope, _ESCALATION, profile.id, due, work.id)
            if raised:
                escalation = ReportEscalated(service_id=profile.id, due_at=due, at=at)
                await uow.outbox.add(outbox_message_for(escalation, id=self._ids.new_id(), now=at))
            result = LadderStepResult(ESCALATED if raised else IGNORED)

        await uow.scheduled_work.save(replace(work, status=DONE))
        await uow.audit.append(
            AuditEntry(
                action=AUDIT_ACTION,
                use_case=USE_CASE,
                actor=command.actor,
                entity_ids=(
                    work.id,
                    *(() if result.communication_id is None else (result.communication_id,)),
                    profile.id,
                ),
                snapshot={
                    "kind": work.kind.value,
                    "action": result.action,
                    "due_at": format_instant(due),
                },
                at=at,
            )
        )
        return result

    async def _cancel_rest(
        self,
        uow: UnitOfWork,
        work: ScheduledWork,
        due: datetime,
        at: datetime,
        policy: TenantPolicy,
    ) -> None:
        """Cancel the other scheduled steps of the same ladder: those about the same subject and
        due time."""
        for kind in LADDER_KINDS:
            for other in await uow.scheduled_work.for_about(work.about_id, kind):
                if (
                    other.id != work.id
                    and other.status == SCHEDULED
                    and ladder_due(other, policy) == due
                ):
                    await cancel_work(uow, other, at)

    async def _remind(
        self,
        uow: UnitOfWork,
        scope: ScopeId,
        settings: TenantSettings,
        work: ScheduledWork,
        prompt: Communication | None,
        profile: ServiceProfile,
        latest: CapacityReport | None,
        due: datetime,
        at: datetime,
    ) -> LadderStepResult:
        sent = await self._send_reminder(uow, scope, settings, prompt, profile, at)
        if await _first_to_raise(uow, scope, _STATUS, profile.id, due, work.id):
            await self._announce_status(uow, settings, profile, latest, due, at)
        return LadderStepResult(REMINDED, sent)

    async def _send_reminder(
        self,
        uow: UnitOfWork,
        scope: ScopeId,
        settings: TenantSettings,
        prompt: Communication | None,
        profile: ServiceProfile,
        at: datetime,
    ) -> str | None:
        """C8 to the reporter the prompt went to, with a fresh link that expires at the new
        reply-by. Nothing is sent when the ladder is about the service (nobody could be texted), or
        the reporter's role has ended or its holder has no phone now: the service is still marked
        Not updated, and the next steps still run."""
        if prompt is None:
            return None
        roles = await uow.people.reporter_roles_for_service(profile.id, at)
        role = next((r for r in roles if r.id == prompt.recipient_role_id), None)
        phone_hash = None if role is None else await _phone_hash(uow, role, at)
        if role is None or phone_hash is None:
            return None
        reply = at + settings.policy.reply_window
        communication_id = self._ids.new_id()
        token = await self._link_tokens(uow.link_tokens).issue(
            LINK_PURPOSE, communication_id, phone_hash, reply
        )
        link = f"{await self._links.link_base_url(scope)}/{token}"
        rendered = render(
            MessageId.C8,
            prompt.channel,
            service=profile.name,
            reply_by=format_hhmm(reply, zone=settings.zone),
            link=link,
        )
        await uow.communications.add(
            Communication(
                id=communication_id,
                message_id=MessageId.C8.value,
                channel=prompt.channel,
                recipient_role_id=role.id,
                about_id=profile.id,
                payload_text=rendered.text.replace(link, LINK_PLACEHOLDER),
                sent_at=at,
                delivery_status="queued",
            )
        )
        outbox_id = self._ids.new_id()
        await uow.outbox.add(
            OutboxMessage(
                id=outbox_id,
                topic=MESSAGES_TOPIC,
                event_type=SEND_MESSAGE,
                payload=_send_payload(
                    outbox_id,
                    communication_id,
                    MessageId.C8,
                    role,
                    rendered,
                    self._sealer,
                    scope.value,
                ),
                created_at=at,
            )
        )
        return communication_id

    async def _announce_status(
        self,
        uow: UnitOfWork,
        settings: TenantSettings,
        profile: ServiceProfile,
        latest: CapacityReport | None,
        due: datetime,
        at: datetime,
    ) -> None:
        """StatusChanged from the status just before the reply-by to the status just after it,
        which is when the service becomes overdue (it is overdue only once the reply-by has passed).
        Nothing is raised when the two are the same: the board already reads the service as it will
        read it."""
        confirmed = (
            []
            if latest is None
            else await uow.bookings.confirmed_since(profile.id, latest.effective_at)
        )
        deadline = reply_by(due, settings.policy)
        before: Status = compute_status(
            profile,
            latest,
            confirmed,
            deadline - ONE_MICROSECOND,
            settings.policy,
            settings.zone,
        ).status
        after: Status = compute_status(
            profile,
            latest,
            confirmed,
            max(at, deadline + ONE_MICROSECOND),
            settings.policy,
            settings.zone,
        ).status
        if before is not after:
            event = StatusChanged(service_id=profile.id, before=before, after=after, at=at)
            await uow.outbox.add(outbox_message_for(event, id=self._ids.new_id(), now=at))
