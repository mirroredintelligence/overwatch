"""The approval steps of a registration (U29): approve, send back, not approve, reopen, record the
test answer, set the service live, and read the registration record.

Only the shift lead (acting as a named practitioner) decides, and never on their own request: the
approver must differ from the requester (DEC-405). Approval re-runs the automatic checks and the
criteria check from what is stored now, not from the flags kept on the registration (H-144); the
call-back flag is the one RecordCallBack recorded. Approval queues the test prompt (I3) to the
requester's registered role. A test answer counts only from the registered phone hash (DEC-405).
Going live flips the service, its location and its organisation to active (DEC-406) and schedules
its first prompt at the next due time.

Every step is audited and written in one unit of work with its record (DEC-407): the
registration's draft holds `<step>_at` and `<step>_by` as typed text fields, and the record is read
back by registration_steps.

Known gaps, recorded in the fragment: the send-back note has no approved wording and no channel
send; the call-back, scope and criteria steps have no time of their own; commands are not replayed
by key (a repeat of an approval finds the registration already moved and is refused).
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import PhoneHasher
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import schedule_work
from diucs.application.sealed_send import queue_message
from diucs.application.use_cases.review_registration import (
    AreaDistrictsFor,
    _audit,
    _checks_of,
    _evaluate,
    _hash_or_none,
    _load,
    _reporting_phone,
    _require_in_review,
    _tenant_scope,
    check_may_review,
)
from diucs.application.work import WorkKind
from diucs.domain.codes import Channel, RegistrationStatus
from diucs.domain.errors import InvalidTransition, NotAllowed, NotFound
from diucs.domain.events import RegistrationApproved
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.registration import Registration
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.registration import approve_registration, transition_registration
from diucs.domain.rules.registration_approval import (
    answers_the_test,
    check_note,
    may_set_live,
    require_distinct_approver,
)
from diucs.domain.rules.registration_record import RECORD_STEP, RecordedStep, registration_steps
from diucs.domain.rules.schedule import next_due

NO_REGISTRATION: Final = "no registration with this id"
NO_SERVICE: Final = "no service with this id"
ANSWERED: Final = "test_answered_at"


@dataclass(frozen=True, slots=True)
class RegistrationDecisionCommand:
    registration_id: str
    actor: Actor


@dataclass(frozen=True, slots=True)
class NoteCommand:
    registration_id: str
    actor: Actor
    note: str


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    registration_id: str
    status: RegistrationStatus


@dataclass(frozen=True, slots=True)
class RecordTestAnswerCommand:
    registration_id: str
    actor: Actor
    phone_hash: str | None
    device_id: str | None = None


@dataclass(frozen=True, slots=True)
class RecordTestAnswerResult:
    registration_id: str
    recorded: bool


def _record_of(registration: Registration) -> dict[str, Any]:
    return dict(registration.draft.get(RECORD_STEP, {}))


def _draft_with(registration: Registration, record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {**registration.draft, RECORD_STEP: record}


def _stamp(record: dict[str, Any], step: str, now: datetime, who: str | None) -> dict[str, Any]:
    """Record one step: when it happened and who did it."""
    return {**record, f"{step}_at": now.isoformat(), f"{step}_by": who or ""}


async def _requester_practitioner(uow: UnitOfWork, registration: Registration) -> str | None:
    if registration.requester_role_id is None:
        return None
    role = await uow.people.get_role(registration.requester_role_id)
    return None if role is None else role.practitioner_id


class _Decide:
    """What the lead's moves share: the unit of work factory and the clock."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock


class ApproveRegistration(_Decide):
    """Approve an in-review registration whose four checks all pass (re-run now), and queue the test
    prompt (I3) to the requester."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        sealer: ContentSealer,
        *,
        phone_hasher: PhoneHasher,
        area_districts_for: AreaDistrictsFor,
    ) -> None:
        super().__init__(uow_factory, clock)
        self._hasher = phone_hasher
        self._area_districts_for = area_districts_for
        self._ids = ids
        self._sealer = sealer

    async def execute(self, command: RegistrationDecisionCommand) -> RegistrationResult:
        lead_id = check_may_review(command.actor)
        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            registration = await _load(uow, command.registration_id)
            _require_in_review(registration)
            requester = await _requester_practitioner(uow, registration)
            require_distinct_approver(requester_practitioner_id=requester, approver_id=lead_id)
            if registration.requester_role_id is None:
                raise NotAllowed("the registration has no requester to receive the test prompt")
            now = self._clock.now()
            evaluation = await _evaluate(
                uow, registration, self._hasher, self._area_districts_for, now
            )
            checks = _checks_of(registration, evaluation)
            target = approve_registration(registration.status, checks)
            profile = await uow.services.get(registration.service_id)
            if profile is None:
                raise NotFound(NO_SERVICE)
            await queue_message(
                uow,
                self._ids,
                self._sealer,
                scope=scope,
                rendered=render(MessageId.I3, Channel.TEXT, service=profile.name),
                recipient_role_id=registration.requester_role_id,
                about_id=profile.id,
                now=now,
            )
            record = _stamp(_record_of(registration), "approved", now, lead_id)
            record = _stamp(record, "test_prompt", now, registration.requester_role_id)
            saved = replace(
                registration,
                status=target,
                checks=checks,
                last_modified=now,
                draft=_draft_with(registration, record),
            )
            await uow.registrations.save(saved)
            await _audit(
                uow,
                command.actor,
                registration,
                "ApproveRegistration",
                {"status": target.value},
                now,
            )
            await uow.commit()
        return RegistrationResult(registration.id, target)


class _Stepped(_Decide):
    """A lead's move between two states that records the step and its note."""

    async def _move(
        self,
        command: NoteCommand | RegistrationDecisionCommand,
        *,
        target: RegistrationStatus,
        step: str,
        note: str | None,
        use_case: str,
    ) -> RegistrationResult:
        lead_id = check_may_review(command.actor)
        async with self._uow_factory() as uow:
            registration = await _load(uow, command.registration_id)
            moved = transition_registration(registration.status, target)
            now = self._clock.now()
            record = _stamp(_record_of(registration), step, now, lead_id)
            saved = replace(
                registration,
                status=moved,
                note=registration.note if note is None else note,
                last_modified=now,
                draft=_draft_with(registration, record),
            )
            await uow.registrations.save(saved)
            await _audit(uow, command.actor, registration, use_case, {"status": moved.value}, now)
            await uow.commit()
        return RegistrationResult(registration.id, moved)


class SendBackRegistration(_Stepped):
    """Send an in-review registration back to the applicant with a short note (in-review ->
    needs-changes). The note is required and carries no number that could identify someone."""

    async def execute(self, command: NoteCommand) -> RegistrationResult:
        note = check_note(command.note)
        return await self._move(
            command,
            target=RegistrationStatus.NEEDS_CHANGES,
            step="sent_back",
            note=note,
            use_case="SendBackRegistration",
        )


class NotApproveRegistration(_Stepped):
    """Refuse an in-review registration with a reason (in-review -> not-approved)."""

    async def execute(self, command: NoteCommand) -> RegistrationResult:
        reason = check_note(command.note)
        return await self._move(
            command,
            target=RegistrationStatus.NOT_APPROVED,
            step="not_approved",
            note=reason,
            use_case="NotApproveRegistration",
        )


class ReopenRegistration(_Stepped):
    """Reopen a refused registration for review (not-approved -> in-review)."""

    async def execute(self, command: RegistrationDecisionCommand) -> RegistrationResult:
        return await self._move(
            command,
            target=RegistrationStatus.IN_REVIEW,
            step="reopened",
            note=None,
            use_case="ReopenRegistration",
        )


class RecordTestAnswer:
    """The test prompt was answered. It counts only from the registered phone hash (DEC-405). An
    answer from anyone else is ignored and nothing is written."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        *,
        phone_hasher: PhoneHasher,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._hasher = phone_hasher

    async def execute(self, command: RecordTestAnswerCommand) -> RecordTestAnswerResult:
        async with self._uow_factory() as uow:
            registration = await _load(uow, command.registration_id)
            if registration.status is not RegistrationStatus.APPROVED:
                raise InvalidTransition(
                    "a test prompt is answered for an approved registration only"
                )
            registered = _hash_or_none(self._hasher, await _reporting_phone(uow, registration))
            if not answers_the_test(
                answer_phone_hash=command.phone_hash,
                registered_phone_hash=registered,
                answer_device_id=command.device_id,
                registered_device_id=None,
            ):
                await uow.commit()
                return RecordTestAnswerResult(registration.id, recorded=False)
            record = _record_of(registration)
            if ANSWERED not in record:
                now = self._clock.now()
                record = _stamp(record, "test_answered", now, registration.requester_role_id)
                await uow.registrations.save(
                    replace(
                        registration,
                        last_modified=now,
                        draft=_draft_with(registration, record),
                    )
                )
                await _audit(
                    uow,
                    command.actor,
                    registration,
                    "RecordTestAnswer",
                    {"status": registration.status.value},
                    now,
                )
            await uow.commit()
        return RecordTestAnswerResult(registration.id, recorded=True)


class SetServiceLive:
    """Set an approved, answered registration live: the service, its location and organisation
    become active (DEC-406), the first prompt is scheduled at the next due time, and
    RegistrationApproved is emitted."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, command: RegistrationDecisionCommand) -> RegistrationResult:
        lead_id = check_may_review(command.actor)
        async with self._uow_factory() as uow:
            registration = await _load(uow, command.registration_id)
            record = _record_of(registration)
            may_set_live(registration.status, test_answered=ANSWERED in record)
            now = self._clock.now()
            await uow.services.set_active(registration.service_id)
            profile = await uow.services.get(registration.service_id)
            if profile is None:
                raise NotFound(NO_SERVICE)
            due = next_due(profile, now, DEFAULT_POLICY)
            if due is not None:
                await schedule_work(
                    uow,
                    self._ids,
                    kind=WorkKind.PROMPT_DUE,
                    about_id=profile.id,
                    due_at=due,
                    now=now,
                )
            record = _stamp(record, "live", now, lead_id)
            await uow.registrations.save(
                replace(
                    registration,
                    status=RegistrationStatus.LIVE,
                    last_modified=now,
                    draft=_draft_with(registration, record),
                )
            )
            await uow.outbox.add(
                outbox_message_for(
                    RegistrationApproved(
                        registration_id=registration.id, service_id=profile.id, at=now
                    ),
                    id=f"registration-live-{registration.id}",
                    now=now,
                )
            )
            await _audit(
                uow,
                command.actor,
                registration,
                "SetServiceLive",
                {"status": RegistrationStatus.LIVE.value},
                now,
            )
            await uow.commit()
        return RegistrationResult(registration.id, RegistrationStatus.LIVE)


class GetRegistrationRecord:
    """The steps of a registration with who did each and when, in time order (for export)."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, command: RegistrationDecisionCommand) -> tuple[RecordedStep, ...]:
        check_may_review(command.actor)
        async with self._uow_factory() as uow:
            registration = await _load(uow, command.registration_id)
        return registration_steps(
            registration.submitted_at, registration.requester_role_id, _record_of(registration)
        )
