"""The daily criteria review job (U31): remind each criteria owner 14 days before review-by, and
flag a service whose criteria are overdue, so advisors see "criteria not reviewed" (U12, W13).

The job runs once a day at 07:00 London (REVIEW_RUN_AT, [ASSUMED]) and schedules its own next run
through schedule_work, at 07:00 on the next London date, so the clock change is handled by
london_to_utc, never by adding 24 hours. It never changes criteria: clearing the overdue flag is
U30's, on confirmation.

Reminder: for each current version whose review-by is 14 days away or less, the owner's role is
sent K2 by its channel (email or push: K2 is defined for those two channels only, DEC-037, so a
text-only owner gets no reminder and is left for a later run). Each review-by date is reminded once:
a processed marker keyed by the criteria version and its review-by date records it (a marker, not a
property on the criteria node, so P04's record is unchanged, DEC-342). Overdue: after review-by
the service gets the criteria-overdue flag, unless it already has it.

Idempotency: the run marks its work id as processed in the same unit of work as its writes, so a
second delivery of the same work id changes nothing and schedules no second next run. The daily
schedule is seeded at start-up with a deterministic work id per tenant and London date, so two
processes starting at once cannot create two daily chains (the second write is a Conflict).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.messaging import Communication
from diucs.application.ports.outbound.outbox import OutboxMessage
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.application.use_cases.send_prompts import MESSAGES_TOPIC, SEND_MESSAGE, _send_payload
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.codes import Channel
from diucs.domain.errors import Conflict
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.flags import SERVICE_FLAG_CRITERIA_OVERDUE, ServiceFlag
from diucs.domain.rules.criteria_workflow import is_review_overdue, review_reminder_due
from diucs.domain.rules.london_time import london_to_utc, to_london

LONDON: Final = ZoneInfo("Europe/London")
REVIEW_RUN_AT: Final = time(7, 0)
"""The daily run, London local time (U31, [ASSUMED])."""
CONSUMER: Final = "criteria-reviews"
REMINDER_CONSUMER: Final = "criteria-review-reminder"
OVERDUE_REASON: Final = "review-by passed"
SYSTEM_ACTOR: Final = "system:criteria-review"
"""The actor of the flag the job sets. It is not a person."""


def next_run_due(now: datetime) -> datetime:
    """The instant of the run after `now`: 07:00 London on the next London date, as UTC."""
    tomorrow = to_london(now).date() + timedelta(days=1)
    return london_to_utc(tomorrow, REVIEW_RUN_AT)


def first_run_due(now: datetime) -> datetime:
    """The first run: today at 07:00 London when that is still ahead, otherwise tomorrow's."""
    today = to_london(now).date()
    todays = london_to_utc(today, REVIEW_RUN_AT)
    return todays if todays > now.astimezone(UTC) else next_run_due(now)


def reminder_marker(criteria_id: str, review_by: date) -> str:
    """The processed marker of one review-by date of one criteria version."""
    return f"criteria-reminder:{criteria_id}:{review_by.isoformat()}"


def _tenant_scope(scope: ScopeId | None) -> ScopeId:
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _day(value: date) -> str:
    return f"{value.day} {value:%b}"


@dataclass(frozen=True, slots=True)
class RunCriteriaReviewsCommand:
    work_id: str


@dataclass(frozen=True, slots=True)
class CriteriaReviewsResult:
    reminders_sent: int
    flags_set: int


class _FixedId:
    """Answers the given value first (the scheduled work's id) and a derived one after it (the
    message's id). Used only for the start-up schedule, whose work id is derived from the tenant
    and the date, so that a second writer is refused."""

    def __init__(self, value: str) -> None:
        self._value = value
        self._calls = 0

    def new_id(self) -> str:
        self._calls += 1
        return self._value if self._calls == 1 else f"{self._value}:message"


def _daily_work_id(scope: ScopeId, due: datetime) -> str:
    return f"criteria-review:{scope.value}:{to_london(due).date().isoformat()}"


class RunCriteriaReviews:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        sealer: ContentSealer,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._sealer = sealer

    async def execute(self, command: RunCriteriaReviewsCommand) -> CriteriaReviewsResult:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            if not await uow.processed.mark_if_new(command.work_id, CONSUMER):
                return CriteriaReviewsResult(reminders_sent=0, flags_set=0)
            today = to_london(now).date()
            services = sorted(await uow.services.list_active(), key=lambda profile: profile.id)
            current = (
                await uow.criteria.current_for_services([profile.id for profile in services])
                if services
                else {}
            )
            reminders = 0
            flags = 0
            for profile in services:
                criteria = current.get(profile.id)
                if criteria is None:
                    continue
                if review_reminder_due(criteria, today) and await self._remind(
                    uow, profile.name, criteria, now
                ):
                    reminders += 1
                if is_review_overdue(criteria, today) and await _flag_overdue(uow, profile.id, now):
                    flags += 1
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.CRITERIA_REVIEW_REMINDER,
                about_id=scope.value,
                due_at=next_run_due(now),
                now=now,
            )
            await uow.commit()
        return CriteriaReviewsResult(reminders_sent=reminders, flags_set=flags)

    @staticmethod
    def _tenant_text(uow: UnitOfWork) -> str:
        return _tenant_scope(uow.unit_scope).value

    async def _remind(
        self, uow: UnitOfWork, service_name: str, criteria: ServiceCriteria, now: datetime
    ) -> bool:
        role = await uow.people.get_role(criteria.owner_role_id)
        if role is None or not role.active or role.channel not in (Channel.EMAIL, Channel.PUSH):
            return False
        if not await uow.processed.mark_if_new(
            reminder_marker(criteria.id, criteria.review_by), REMINDER_CONSUMER
        ):
            return False
        rendered = render(
            MessageId.K2,
            role.channel,
            service=service_name,
            review_by=_day(criteria.review_by),
        )
        communication_id = self._ids.new_id()
        await uow.communications.add(
            Communication(
                id=communication_id,
                message_id=MessageId.K2.value,
                channel=role.channel,
                recipient_role_id=role.id,
                about_id=criteria.service_id,
                payload_text=rendered.text,
                sent_at=now,
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
                    MessageId.K2,
                    role,
                    rendered,
                    self._sealer,
                    self._tenant_text(uow),
                ),
                created_at=now,
            )
        )
        return True


async def _flag_overdue(uow: UnitOfWork, service_id: str, now: datetime) -> bool:
    if any(
        flag.code == SERVICE_FLAG_CRITERIA_OVERDUE and flag.active
        for flag in await uow.flags.service_flags(service_id)
    ):
        return False
    await uow.flags.set_service_flag(
        ServiceFlag(
            service_id=service_id,
            code=SERVICE_FLAG_CRITERIA_OVERDUE,
            active=True,
            reason=OVERDUE_REASON,
            actor_id=SYSTEM_ACTOR,
            at=now,
        )
    )
    return True


async def ensure_daily_schedule(
    uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock
) -> bool:
    """Schedule the first daily run for the bound tenant when none is scheduled. Returns True when
    it wrote one. The work id is derived from the tenant and the London date of the run, so a
    second writer for the same run is a Conflict, which means it is already scheduled."""
    now = clock.now()
    scope = current_scope()
    if scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    due = first_run_due(now)
    try:
        async with uow_factory() as uow:
            _tenant_scope(uow.unit_scope)
            works = await uow.scheduled_work.for_about(
                scope.value, WorkKind.CRITERIA_REVIEW_REMINDER
            )
            if any(work.status == SCHEDULED for work in works):
                return False
            fixed = _FixedId(_daily_work_id(scope, due))
            await schedule_work(
                uow,
                fixed,
                kind=WorkKind.CRITERIA_REVIEW_REMINDER,
                about_id=scope.value,
                due_at=due,
                now=now,
            )
            await uow.commit()
    except Conflict:
        return False
    return True
