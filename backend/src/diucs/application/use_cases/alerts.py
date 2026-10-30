"""Alerts: the evaluator, the not-updated checks, acknowledge, snooze and escalation (U34).

AlertEvaluator takes a StatusChanged (capacity.events) and raises the alerts D24 finds for it: each
subscriber who wants that kind, and who may be told now (quiet hours), gets an Alert task owned by
them, a push (K3) and an AlertRaised event, and an escalation timer at the ack window. A change to
not-updated also schedules two checks, at two and at four hours (decision DEC-408): each check
alerts only the subscribers whose threshold is its age, and only while the service is still not
updated.

Acknowledging closes an alert's whole chain and cancels its timers. Snoozing moves a new alert's
escalation an hour later. An escalation that fires on an unacknowledged alert passes it to the
owner's deputy (a new alert that is PART_OF the first); if the deputy does not act either, the shift
lead is told (AlertEscalatedToLead, once). Every timer runs through the scheduled-work consumer and
is idempotent: its work is marked done in the same unit as what it does, and a message id is marked
processed first (ProcessedMessages).

The hours a service is open, the quiet hours of a subscriber and the defaults of a deputy are the
tenant's own zone and policy (TEN-027, DEC-500): each use case reads them inside its unit of work.

No alert names a patient. The push carries the service's name and the kind, nothing else.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from diucs.application.actor import Actor, timer_actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import OutboxMessage, outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import cancel_work, schedule_work
from diucs.application.tenancy import current_tenant
from diucs.application.tenant_settings import TenantZones, as_zones, read_policy, read_settings
from diucs.application.work import DONE, SCHEDULED, ScheduledWork, WorkKind
from diucs.domain.codes import AlertKind, Channel, Status
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.events import AlertAcknowledged, AlertEscalatedToLead, AlertRaised
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.alerts import AlertRecord
from diucs.domain.model.service import ServiceProfile
from diucs.domain.model.tenant_policy import TenantPolicy
from diucs.domain.rules.alert_workflow import (
    may_acknowledge,
    may_snooze,
    not_updated_check_times,
    snoozed_due,
)
from diucs.domain.rules.alerts import (
    Alert,
    AlertPreferences,
    alerts_for_change,
    default_preferences,
    escalation_at,
    should_notify,
)
from diucs.domain.rules.opening_hours import is_in_hours

CONSUMER: Final = "alert-evaluator"
AUDIT_ACTION: Final = "U"
MESSAGES_TOPIC: Final = "messages.outbound"
SEND_MESSAGE: Final = "SendMessage"
OPEN: Final = "new"
ESCALATED: Final = "escalated"
ACKNOWLEDGED: Final = "acknowledged"
NOT_UPDATED_CHECK_HOURS: Final = (2, 4)
_KIND_NOUN: Final = {
    AlertKind.SERVICE_CLOSED: "is not accepting referrals",
    AlertKind.OVER_CAPACITY: "is over capacity",
    AlertKind.NOT_UPDATED: "has not been updated",
    AlertKind.SYSTEM_PRESSURE: "system pressure is high",
}
NO_SERVICE: Final = "no service with this id"
NO_ALERT: Final = "no alert with this id"
NO_TIMER: Final = "no escalation of this kind for this alert"


@dataclass(frozen=True, slots=True)
class StatusChangedCommand:
    """A StatusChanged message, with the id the bus gave it (idempotent on that id)."""

    message_id: str
    service_id: str
    before: Status | None
    after: Status
    at: datetime


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    raised: int
    checks_scheduled: int
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class AcknowledgeAlertCommand:
    alert_id: str
    actor: Actor


@dataclass(frozen=True, slots=True)
class AcknowledgeAlertResult:
    alert_id: str
    status: str


@dataclass(frozen=True, slots=True)
class SnoozeAlertCommand:
    alert_id: str
    actor: Actor


@dataclass(frozen=True, slots=True)
class SnoozeAlertResult:
    alert_id: str
    escalation_due_at: datetime


@dataclass(frozen=True, slots=True)
class EscalateAlertCommand:
    work_id: str
    alert_id: str


@dataclass(frozen=True, slots=True)
class EscalateAlertResult:
    acted: bool
    escalated_to: str | None = None


@dataclass(frozen=True, slots=True)
class NotUpdatedCheckCommand:
    work_id: str
    about_id: str


def check_about(service_id: str, hours: int) -> str:
    """The `about` of a not-updated check: its service and its age in hours (DEC-408)."""
    return f"{service_id}:{hours}"


def _parse_check_about(about: str) -> tuple[str, int]:
    service_id, sep, hours = about.rpartition(":")
    if (
        not sep
        or not service_id
        or not hours.isdigit()
        or int(hours) not in NOT_UPDATED_CHECK_HOURS
    ):
        raise ValidationFailed("about_id", "is not a not-updated check")
    return service_id, int(hours)


def _push_text(profile: ServiceProfile, kind: AlertKind) -> tuple[str, str]:
    return f"{profile.name} {_KIND_NOUN[kind]}", "Tap to acknowledge."


async def _push(
    uow: UnitOfWork, record: AlertRecord, profile: ServiceProfile, now: datetime
) -> None:
    """The K3 push to the alert's owner, through the outbound message queue. Its channel and sender
    are the I10 push sender's; this only records the message."""
    title, body = _push_text(profile, record.kind)
    # render checks the K3 fields (title and body) and refuses anything else.
    render(MessageId.K3, Channel.PUSH, title=title, body=body)
    await uow.outbox.add(
        OutboxMessage(
            id=f"alert-push-{record.id}",
            topic=MESSAGES_TOPIC,
            event_type=SEND_MESSAGE,
            payload={
                "message_id": MessageId.K3.value,
                "channel": Channel.PUSH.value,
                "recipient_practitioner_id": record.owner_practitioner_id,
                "alert_id": record.id,
                "title": title,
                "body": body,
            },
            created_at=now,
        )
    )


async def _alert_subscribers(
    uow: UnitOfWork,
    ids: IdGenerator,
    profile: ServiceProfile,
    alert: Alert,
    now: datetime,
    zone: ZoneInfo,
    *,
    hours: int | None = None,
) -> int:
    """Raise `alert` for every subscriber who wants it now, judging their quiet hours in the
    tenant's `zone`. For a not-updated check, only the subscribers whose threshold is `hours`.
    Returns how many alerts were raised."""
    raised = 0
    for subscription in await uow.alert_subscriptions.subscribers_for_kind(alert.kind):
        prefs: AlertPreferences = subscription.preferences
        if hours is not None and prefs.not_updated_hours != hours:
            continue
        if not should_notify(prefs, alert, now, zone):
            continue
        record = AlertRecord(
            id=ids.new_id(),
            kind=alert.kind,
            service_id=profile.id,
            owner_practitioner_id=subscription.practitioner_id,
            status=OPEN,
            raised_at=now,
            escalation_due_at=escalation_at(now, prefs),
            part_of_id=None,
        )
        await uow.alerts.add(record)
        await uow.outbox.add(
            outbox_message_for(
                AlertRaised(alert_id=record.id, kind=alert.kind, service_id=profile.id, at=now),
                id=f"alert-raised-{record.id}",
                now=now,
            )
        )
        await _push(uow, record, profile, now)
        await schedule_work(
            uow,
            ids,
            kind=WorkKind.ALERT_ESCALATE,
            about_id=record.id,
            due_at=record.escalation_due_at or now,
            now=now,
        )
        raised += 1
    return raised


class AlertEvaluator:
    """Handles StatusChanged: raises the alerts it finds, and schedules the not-updated checks."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, ids: IdGenerator, zones: TenantZones | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._zones = as_zones(zones)

    async def execute(self, command: StatusChangedCommand) -> EvaluationResult:
        now = command.at
        async with self._uow_factory() as uow:
            if not await uow.processed.mark_if_new(command.message_id, CONSUMER):
                return EvaluationResult(0, 0, duplicate=True)
            profile = await uow.services.get(command.service_id)
            if profile is None:
                raise NotFound(NO_SERVICE)
            settings = await read_settings(uow, self._zones)
            in_hours = is_in_hours(profile.available_times, now, zone=settings.zone)
            raised = 0
            for alert in alerts_for_change(
                command.service_id, command.before, command.after, in_hours, now, settings.policy
            ):
                raised += await _alert_subscribers(
                    uow, self._ids, profile, alert, now, settings.zone
                )
            checks = 0
            if command.after is Status.NOT_UPDATED:
                for hours, due in zip(
                    NOT_UPDATED_CHECK_HOURS, not_updated_check_times(now), strict=True
                ):
                    await schedule_work(
                        uow,
                        self._ids,
                        kind=WorkKind.NOT_UPDATED_CHECK,
                        about_id=check_about(profile.id, hours),
                        due_at=due,
                        now=now,
                    )
                    checks += 1
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="AlertEvaluator",
                    actor=timer_actor(current_tenant()),
                    entity_ids=(profile.id,),
                    snapshot={"raised": raised, "checks": checks},
                    at=now,
                )
            )
            await uow.commit()
        return EvaluationResult(raised, checks)


class NotUpdatedCheck:
    """A not-updated check at two or four hours (run by the scheduled-work consumer). It alerts the
    subscribers whose threshold is this age, if the service still has no report newer than it."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        zones: TenantZones | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._zones = as_zones(zones)

    async def execute(self, command: NotUpdatedCheckCommand) -> int:
        service_id, hours = _parse_check_about(command.about_id)
        async with self._uow_factory() as uow:
            work = await _work(uow, command.work_id, WorkKind.NOT_UPDATED_CHECK, command.about_id)
            if work is None:
                return 0
            await uow.scheduled_work.save(replace(work, status=DONE))
            now = self._clock.now()
            latest = await uow.capacity.latest(service_id)
            if latest is not None and now - latest.effective_at < timedelta(hours=hours):
                await uow.commit()
                return 0
            profile = await uow.services.get(service_id)
            if profile is None:
                raise NotFound(NO_SERVICE)
            settings = await read_settings(uow, self._zones)
            alert = Alert(
                AlertKind.NOT_UPDATED,
                service_id,
                now,
                AlertKind.NOT_UPDATED in settings.policy.critical_alert_kinds,
            )
            raised = await _alert_subscribers(
                uow, self._ids, profile, alert, now, settings.zone, hours=hours
            )
            await uow.commit()
        return raised


class AcknowledgeAlert:
    """The owner acknowledges an alert. Every alert in its chain is closed and its escalation timer
    cancelled. The board does not change."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: AcknowledgeAlertCommand) -> AcknowledgeAlertResult:
        async with self._uow_factory() as uow:
            alert = await uow.alerts.get(command.alert_id)
            if alert is None:
                raise NotFound(NO_ALERT)
            may_acknowledge(
                alert.status,
                owner_id=alert.owner_practitioner_id,
                actor_id=command.actor.practitioner_id,
            )
            now = self._clock.now()
            for member in await uow.alerts.chain(alert.id):
                if member.status in (OPEN, ESCALATED):
                    await uow.alerts.save(replace(member, status=ACKNOWLEDGED, acknowledged_at=now))
                await _cancel_escalations(uow, member.id, now)
            await uow.outbox.add(
                outbox_message_for(
                    AlertAcknowledged(alert_id=alert.id, by=command.actor.role, at=now),
                    id=f"alert-acknowledged-{alert.id}",
                    now=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="AcknowledgeAlert",
                    actor=command.actor,
                    entity_ids=(alert.id,),
                    snapshot={"status": ACKNOWLEDGED},
                    at=now,
                )
            )
            await uow.commit()
        return AcknowledgeAlertResult(alert.id, ACKNOWLEDGED)


class SnoozeAlert:
    """The owner snoozes a new alert: its escalation moves an hour later and the alert stays new."""

    def __init__(self, uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock

    async def execute(self, command: SnoozeAlertCommand) -> SnoozeAlertResult:
        async with self._uow_factory() as uow:
            alert = await uow.alerts.get(command.alert_id)
            if alert is None:
                raise NotFound(NO_ALERT)
            may_snooze(
                alert.status,
                owner_id=alert.owner_practitioner_id,
                actor_id=command.actor.practitioner_id,
            )
            now = self._clock.now()
            due = snoozed_due(alert.escalation_due_at or now)
            await _cancel_escalations(uow, alert.id, now)
            await uow.alerts.save(replace(alert, escalation_due_at=due))
            await schedule_work(
                uow, self._ids, kind=WorkKind.ALERT_ESCALATE, about_id=alert.id, due_at=due, now=now
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case="SnoozeAlert",
                    actor=command.actor,
                    entity_ids=(alert.id,),
                    snapshot={"escalation_due_at": due.isoformat()},
                    at=now,
                )
            )
            await uow.commit()
        return SnoozeAlertResult(alert.id, due)


class EscalateAlert:
    """The escalation timer of an alert. If it is still new: the owner's deputy gets a new alert
    that is PART_OF this one; with no deputy, or if this is already the deputy's alert, the shift
    lead is told (AlertEscalatedToLead, once for the chain)."""

    def __init__(self, uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock

    async def execute(self, command: EscalateAlertCommand) -> EscalateAlertResult:
        async with self._uow_factory() as uow:
            work = await _work(uow, command.work_id, WorkKind.ALERT_ESCALATE, command.alert_id)
            if work is None:
                return EscalateAlertResult(acted=False)
            await uow.scheduled_work.save(replace(work, status=DONE))
            alert = await uow.alerts.get(command.alert_id)
            if alert is None:
                raise NotFound(NO_ALERT)
            if alert.status != OPEN:
                await uow.commit()
                return EscalateAlertResult(acted=False)
            now = self._clock.now()
            await uow.alerts.save(replace(alert, status=ESCALATED))
            owner = await uow.alert_subscriptions.get_for_practitioner(alert.owner_practitioner_id)
            deputy_id = None if owner is None else owner.deputy_id
            if alert.part_of_id is None and deputy_id is not None:
                await self._to_deputy(uow, alert, deputy_id, now, await read_policy(uow))
                await uow.commit()
                return EscalateAlertResult(acted=True, escalated_to="deputy")
            root = alert.part_of_id or alert.id
            await uow.outbox.add(
                outbox_message_for(
                    AlertEscalatedToLead(alert_id=root, service_id=alert.service_id, at=now),
                    id=f"alert-lead-{root}",
                    now=now,
                )
            )
            await uow.commit()
        return EscalateAlertResult(acted=True, escalated_to="shift-lead")

    async def _to_deputy(
        self,
        uow: UnitOfWork,
        alert: AlertRecord,
        deputy_id: str,
        now: datetime,
        policy: TenantPolicy,
    ) -> None:
        deputy = await uow.alert_subscriptions.get_for_practitioner(deputy_id)
        prefs = default_preferences(policy) if deputy is None else deputy.preferences
        record = AlertRecord(
            id=self._ids.new_id(),
            kind=alert.kind,
            service_id=alert.service_id,
            owner_practitioner_id=deputy_id,
            status=OPEN,
            raised_at=now,
            escalation_due_at=escalation_at(now, prefs),
            part_of_id=alert.id,
        )
        await uow.alerts.add(record)
        await uow.outbox.add(
            outbox_message_for(
                AlertRaised(
                    alert_id=record.id,
                    kind=record.kind,
                    service_id=record.service_id or "",
                    at=now,
                ),
                id=f"alert-raised-{record.id}",
                now=now,
            )
        )
        profile = None if record.service_id is None else await uow.services.get(record.service_id)
        if profile is not None:
            await _push(uow, record, profile, now)
        await schedule_work(
            uow,
            self._ids,
            kind=WorkKind.ALERT_ESCALATE,
            about_id=record.id,
            due_at=record.escalation_due_at or now,
            now=now,
        )


async def _work(
    uow: UnitOfWork, work_id: str, kind: WorkKind, about_id: str
) -> ScheduledWork | None:
    """The stored timer, or None when it is not scheduled any more (done or cancelled)."""
    work = await uow.scheduled_work.get(work_id)
    if work.kind is not kind or work.about_id != about_id:
        raise NotFound(NO_TIMER)
    return work if work.status == SCHEDULED else None


async def _cancel_escalations(uow: UnitOfWork, alert_id: str, now: datetime) -> None:
    for work in await uow.scheduled_work.for_about(alert_id, WorkKind.ALERT_ESCALATE):
        if work.status == SCHEDULED:
            await cancel_work(uow, work, now)
