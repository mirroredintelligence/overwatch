"""What a registration's two readers see, and the three things an applicant can ask for (W7B A1,
A4, DEC-794 to DEC-798).

The applicant reads their own registration: its record (every step, with what is still to do), the
list of their services with a status, and the status page. The shift lead reads the queue (with the
tabs and their counts), one registration's overview (the automatic checks, who registered, the
numbers to tell apart, the names the call-back words need) and the decision (what is missing, the
approvals, the test, the timeline). Every read is read-only and tenant-bound by the unit of work.

An applicant reads only a registration whose requester post they hold: another person's, and an
unknown id, are the one `NotFound`/`NotAllowed` answer. A contact number or address never leaves:
only the last three digits of a number do. The lead reads nothing the applicant has not given.

The three actions keep their marks as non-wizard keys of the draft (`test_notification`,
`review_request`, `details_confirmed`), as the review notes and the lookups do, so no new record is
needed: a test notification (T1) is queued to the applicant by the channel they chose, a review
request is recorded, and the details of a registration that is due its check are confirmed
(reverify to live). Each is keyed, audited and replayed. No number, address or note is in an audit
entry.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.idempotency import format_instant, parse_instant
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.application.use_cases.registration_draft import (
    _check_applicant,
    encode_step,
    read_draft,
    validate_step,
    with_protected_contacts,
)
from diucs.application.use_cases.registration_session import number_ending, reporter_services
from diucs.application.use_cases.review_registration import (
    AutomaticCheck,
    GetReviewStatus,
    GetReviewStatusQuery,
    check_may_review,
)
from diucs.application.work import SCHEDULED, WorkKind
from diucs.domain.codes import Channel, RegistrationStatus, Role
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, NotFound, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.registration import Registration
from diucs.domain.rules.registration import (
    INVITATION_VALID_FOR,
    ApprovalChecks,
    missing_for_approval,
    transition_registration,
)

STEP_KEYS: Final = ("organisation", "location", "service", "reporting", "api")
OPTIONAL_STEPS: Final = frozenset({"api"})
TEST_MARK: Final = "test_notification"
REVIEW_REQUEST_MARK: Final = "review_request"
DETAILS_MARK: Final = "details_confirmed"
TEST_AGAIN_AFTER: Final = timedelta(minutes=1)
"""[ASSUMED] The shortest time between two test notifications of one registration: it stops a double
press (and a flood of texts) and is short enough to send the test again after a fix."""
TEST_STATUSES: Final = frozenset(
    {
        RegistrationStatus.SUBMITTED,
        RegistrationStatus.IN_REVIEW,
        RegistrationStatus.APPROVED,
        RegistrationStatus.LIVE,
        RegistrationStatus.REVERIFY,
    }
)
REVIEW_REQUEST_STATUSES: Final = frozenset(
    {RegistrationStatus.SUBMITTED, RegistrationStatus.IN_REVIEW}
)
OVERVIEW_STATUSES: Final = frozenset(RegistrationStatus) - {
    RegistrationStatus.INVITED,
    RegistrationStatus.DRAFT,
}
QUEUE_TABS: Final[Mapping[str, tuple[str, tuple[RegistrationStatus, ...]]]] = {
    "waiting": (
        "Waiting for review",
        (RegistrationStatus.SUBMITTED, RegistrationStatus.IN_REVIEW),
    ),
    "sent-back": ("Sent back", (RegistrationStatus.NEEDS_CHANGES,)),
    "approved": ("Approved, not live", (RegistrationStatus.APPROVED,)),
    "live": (
        "Live",
        (RegistrationStatus.LIVE, RegistrationStatus.PAUSED, RegistrationStatus.REVERIFY),
    ),
    "not-approved": ("Not approved", (RegistrationStatus.NOT_APPROVED,)),
}
"""The reviewer's tabs, in screen order: each is a label and the registration states it holds. A
registration the applicant has not submitted (invited, draft) is not in the queue."""
DEFAULT_TAB: Final = "waiting"
APPROVAL_KEYS: Final = ("automatic", "callback", "scope", "criteria")
APPROVAL_LABELS: Final = tuple(missing_for_approval(ApprovalChecks(False, False, None, False)))
"""The four approval checks in screen order, with the screen's own words (from the domain rule)."""
TERMINAL_EVENTS: Final = frozenset(
    {
        RegistrationStatus.NEEDS_CHANGES,
        RegistrationStatus.APPROVED,
        RegistrationStatus.NOT_APPROVED,
        RegistrationStatus.LIVE,
    }
)
AUDIT_ACTION: Final = "U"
USE_CASE_TEST: Final = "SendTestNotification"
USE_CASE_REVIEW: Final = "RequestRegistrationReview"
USE_CASE_CONFIRM: Final = "ConfirmRegistrationDetails"


def _scope_of(uow: UnitOfWork) -> ScopeId:
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _iso(value: datetime) -> str:
    return format_instant(value)


async def _own(uow: UnitOfWork, actor: Actor, registration_id: str) -> Registration:
    """The registration an applicant may act on: found, and its requester post is theirs."""
    registration = await uow.registrations.get(registration_id)
    if registration is None:
        raise NotFound("no registration with this id")
    await _check_applicant(uow, actor, registration)
    return registration


async def _service_name(uow: UnitOfWork, service_id: str) -> str:
    entry = await uow.scope.get_entry(service_id)
    return "" if entry is None else entry.name


async def _contacts(uow: UnitOfWork, registration: Registration) -> tuple[str | None, str | None]:
    role_id = registration.requester_role_id
    if role_id is None:
        return None, None
    return await uow.contacts.get_phone(role_id), await uow.contacts.get_email(role_id)


def _mark(registration: Registration, name: str, field: str) -> str | None:
    value = registration.draft.get(name, {}).get(field)
    return value if isinstance(value, str) else None


def _role_label(code: str) -> str:
    return code.replace("-", " ").capitalize()


# --------------------------------------------------------------------------- the applicant


@dataclass(frozen=True, slots=True)
class StepView:
    state: str
    """`complete`, `needs-attention` (answered, with something wrong) or `not-started`."""
    values: dict[str, Any]
    problems: tuple[tuple[str, str], ...]
    """(field, message) pairs, in screen order."""


@dataclass(frozen=True, slots=True)
class RegistrationRecord:
    registration_id: str
    status: RegistrationStatus
    service_id: str
    service_name: str
    submitted_at: datetime | None
    last_modified: datetime
    invitation_expires_at: datetime | None
    note: str
    note_from: str | None
    steps: dict[str, StepView]


def step_views(
    registration: Registration, phone: str | None, email: str | None
) -> dict[str, StepView]:
    """Every wizard step as the applicant sees it: its state, its values (no contact number or
    address: the last three digits and a flag stand for them) and what is wrong, in screen order."""
    draft = read_draft(registration)
    fixed_site = None if draft.location is None else draft.location.fixed_site
    views: dict[str, StepView] = {}
    for key in STEP_KEYS:
        step = getattr(draft, key)
        if step is None:
            views[key] = StepView("not-started", {}, ())
            continue
        checked = (
            with_protected_contacts(step, phone=phone, email=email) if key == "reporting" else step
        )
        problems = tuple(
            (error.field, error.message) for error in validate_step(checked, fixed_site=fixed_site)
        )
        values = encode_step(step)
        if key == "reporting":
            values["contact_mobile_ending"] = None if not phone else number_ending(phone)
            values["has_contact_email"] = bool(email)
        views[key] = StepView("needs-attention" if problems else "complete", values, problems)
    return views


class GetMyRegistration:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, registration_id: str) -> RegistrationRecord:
        async with self._uow_factory() as uow:
            registration = await _own(uow, actor, registration_id)
            phone, email = await _contacts(uow, registration)
            name = await _service_name(uow, registration.service_id)
            reviewer = await _reviewer_label(uow, registration)
        invited = registration.status is RegistrationStatus.INVITED
        return RegistrationRecord(
            registration_id=registration.id,
            status=registration.status,
            service_id=registration.service_id,
            service_name=name,
            submitted_at=registration.submitted_at,
            last_modified=registration.last_modified,
            invitation_expires_at=registration.created_at + INVITATION_VALID_FOR
            if invited
            else None,
            note=registration.note,
            note_from=reviewer if registration.note else None,
            steps=step_views(registration, phone, email),
        )


async def _reviewer_label(uow: UnitOfWork, registration: Registration) -> str | None:
    """The post of the person who decided, as words ("Shift lead"), or None when none did."""
    if registration.owner_role_id is None:
        return None
    role = await uow.people.get_role(registration.owner_role_id)
    return None if role is None else _role_label(role.code.value)


@dataclass(frozen=True, slots=True)
class MyRegistration:
    registration_id: str
    service_id: str
    service_name: str
    status: RegistrationStatus
    submitted_at: datetime | None


class ListMyRegistrations:
    """The registrations whose requester post the applicant holds, by service name."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor) -> tuple[MyRegistration, ...]:
        if actor.practitioner_id is None:
            raise NotAllowed("a named applicant is needed")
        found: list[MyRegistration] = []
        async with self._uow_factory() as uow:
            roles = await uow.people.roles_for_practitioner(actor.practitioner_id)
            held = {role.id: role for role in roles if role.service_id is not None}
            for service_id in sorted(reporter_services(roles)):
                for registration in await uow.registrations.for_service(service_id):
                    if registration.requester_role_id not in held:
                        continue
                    found.append(
                        MyRegistration(
                            registration_id=registration.id,
                            service_id=service_id,
                            service_name=await _service_name(uow, service_id),
                            status=registration.status,
                            submitted_at=registration.submitted_at,
                        )
                    )
        return tuple(sorted(found, key=lambda item: (item.service_name, item.registration_id)))


@dataclass(frozen=True, slots=True)
class RegistrationStatusView:
    registration_id: str
    status: RegistrationStatus
    service_name: str
    submitted_at: datetime | None
    note: str | None
    note_from: str | None
    reason: str | None
    first_prompt_at: datetime | None
    review_requested_at: str | None
    test_sent_at: str | None
    spoa_phone: str | None
    criteria_owner: str | None
    reporting_phone_ending: str | None


class GetRegistrationStatus:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor, registration_id: str) -> RegistrationStatusView:
        async with self._uow_factory() as uow:
            registration = await _own(uow, actor, registration_id)
            phone, _ = await _contacts(uow, registration)
            name = await _service_name(uow, registration.service_id)
            reviewer = await _reviewer_label(uow, registration)
            due = [
                work.due_at
                for work in await uow.scheduled_work.for_about(
                    registration.service_id, WorkKind.PROMPT_DUE
                )
                if work.status == SCHEDULED
            ]
        service = read_draft(registration).service
        sent_back = registration.status is RegistrationStatus.NEEDS_CHANGES
        refused = registration.status is RegistrationStatus.NOT_APPROVED
        return RegistrationStatusView(
            registration_id=registration.id,
            status=registration.status,
            service_name=name,
            submitted_at=registration.submitted_at,
            note=registration.note if sent_back else None,
            note_from=reviewer if (sent_back or refused) and registration.note else None,
            reason=registration.note if refused else None,
            first_prompt_at=min(due) if due else None,
            review_requested_at=_mark(registration, REVIEW_REQUEST_MARK, "requested_at"),
            test_sent_at=_mark(registration, TEST_MARK, "sent_at"),
            spoa_phone=None if service is None else service.spoa_phone or None,
            criteria_owner=None if service is None else service.owner_role or None,
            reporting_phone_ending=number_ending(phone) if phone else None,
        )


# -------------------------------------------------------------------------------- the reviewer


@dataclass(frozen=True, slots=True)
class QueueRow:
    registration_id: str
    service_id: str
    service_name: str
    category: str | None
    status: RegistrationStatus
    submitted_at: datetime | None
    registered_by_role: str | None
    contact_name: str | None
    review_requested_at: str | None


@dataclass(frozen=True, slots=True)
class RegistrationQueue:
    tab: str
    counts: dict[str, int]
    rows: tuple[QueueRow, ...]


def tab_of(value: str | None) -> str:
    tab = DEFAULT_TAB if value is None else value
    if tab not in QUEUE_TABS:
        raise ValidationFailed("tab", "is not one of the queue's tabs")
    return tab


class ListRegistrationQueue:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor, tab: str | None) -> RegistrationQueue:
        check_may_review(actor)
        chosen = tab_of(tab)
        by_tab: dict[str, list[Registration]] = {}
        rows: list[QueueRow] = []
        async with self._uow_factory() as uow:
            for key, (_, statuses) in QUEUE_TABS.items():
                held: list[Registration] = []
                for status in statuses:
                    held.extend(await uow.registrations.list_by_status(status))
                by_tab[key] = held
            for registration in sorted(by_tab[chosen], key=_queue_order):
                rows.append(await _queue_row(uow, registration))
        return RegistrationQueue(
            tab=chosen, counts={key: len(items) for key, items in by_tab.items()}, rows=tuple(rows)
        )


def _queue_order(registration: Registration) -> tuple[datetime, str]:
    return (registration.submitted_at or registration.created_at, registration.id)


async def _registered_by(uow: UnitOfWork, registration: Registration) -> str | None:
    """The post the applicant holds, in words: the invited person's label ("Duty manager")."""
    if registration.requester_role_id is None:
        return None
    role = await uow.people.get_role(registration.requester_role_id)
    if role is None:
        return None
    person = await uow.people.get_practitioner(role.practitioner_id)
    return None if person is None else person.display_name


async def _queue_row(uow: UnitOfWork, registration: Registration) -> QueueRow:
    entry = await uow.scope.get_entry(registration.service_id)
    organisation = read_draft(registration).organisation
    return QueueRow(
        registration_id=registration.id,
        service_id=registration.service_id,
        service_name="" if entry is None else entry.name,
        category=None if entry is None else entry.category.value,
        status=registration.status,
        submitted_at=registration.submitted_at,
        registered_by_role=await _registered_by(uow, registration),
        contact_name=None if organisation is None else organisation.contact_name or None,
        review_requested_at=_mark(registration, REVIEW_REQUEST_MARK, "requested_at"),
    )


@dataclass(frozen=True, slots=True)
class ReviewOverview:
    registration_id: str
    status: RegistrationStatus
    service_id: str
    service_name: str
    category: str | None
    checks: tuple[AutomaticCheck, ...]
    automatic_ok: bool
    callback_confirmed: bool
    scope: str | None
    criteria_approved: bool
    missing: tuple[str, ...]
    registered_by_role: str | None
    contact_name: str | None
    organisation_name: str | None
    applicant_numbers: tuple[tuple[str, str], ...]
    directory_name: str | None
    pathway_name: str | None


class _Evaluator:
    """The shared evaluation: what the review decides from, judged from what is stored now."""

    def __init__(self, status: GetReviewStatus, uow_factory: UnitOfWorkFactory) -> None:
        self._status = status
        self._uow_factory = uow_factory

    async def load(self, actor: Actor, registration_id: str) -> Registration:
        check_may_review(actor)
        async with self._uow_factory() as uow:
            registration = await uow.registrations.get(registration_id)
        if registration is None:
            raise NotFound("no registration with this id")
        if registration.status not in OVERVIEW_STATUSES:
            raise InvalidTransition("this registration has not been submitted")
        return registration


class GetReviewOverview(_Evaluator):
    async def execute(self, actor: Actor, registration_id: str) -> ReviewOverview:
        registration = await self.load(actor, registration_id)
        review = await self._status.execute(
            GetReviewStatusQuery(actor=actor, registration_id=registration_id)
        )
        async with self._uow_factory() as uow:
            entry = await uow.scope.get_entry(registration.service_id)
            registered_by = await _registered_by(uow, registration)
            phone, _ = await _contacts(uow, registration)
            config = await uow.tenant_config.current_version()
        draft = read_draft(registration)
        numbers: list[tuple[str, str]] = []
        for label, number in (
            ("Reporting phone", phone),
            (
                "Organisation contact",
                None if draft.organisation is None else draft.organisation.contact_phone,
            ),
            (
                "Service phone for the SPOA",
                None if draft.service is None else draft.service.spoa_phone,
            ),
        ):
            if number:
                numbers.append((label, number_ending(number)))
        wording = None if config is None else config.wording
        return ReviewOverview(
            registration_id=registration.id,
            status=registration.status,
            service_id=registration.service_id,
            service_name="" if entry is None else entry.name,
            category=None if entry is None else entry.category.value,
            checks=review.checks,
            automatic_ok=review.automatic_ok,
            callback_confirmed=review.callback_confirmed,
            scope=None if review.scope is None else review.scope.value,
            criteria_approved=review.criteria_approved,
            missing=review.missing,
            registered_by_role=registered_by,
            contact_name=None
            if draft.organisation is None
            else draft.organisation.contact_name or None,
            organisation_name=None
            if draft.organisation is None
            else draft.organisation.name or None,
            applicant_numbers=tuple(numbers),
            directory_name=None if wording is None else wording.referral_system_name,
            pathway_name=None if wording is None else wording.system_name,
        )


@dataclass(frozen=True, slots=True)
class DecisionView:
    registration_id: str
    status: RegistrationStatus
    missing: tuple[str, ...]
    approvals: tuple[tuple[str, str, bool], ...]
    can_approve: bool
    test_sent_at: str | None
    test_channel: str | None
    timeline: tuple[tuple[str, datetime], ...]


class GetDecision(_Evaluator):
    async def execute(self, actor: Actor, registration_id: str) -> DecisionView:
        registration = await self.load(actor, registration_id)
        review = await self._status.execute(
            GetReviewStatusQuery(actor=actor, registration_id=registration_id)
        )
        missing = set(review.missing)
        approvals = tuple(
            (key, label, label not in missing)
            for key, label in zip(APPROVAL_KEYS, APPROVAL_LABELS, strict=True)
        )
        events: list[tuple[str, datetime]] = [("invited", registration.created_at)]
        if registration.submitted_at is not None:
            events.append(("submitted", registration.submitted_at))
        for mark, field, name in (
            (REVIEW_REQUEST_MARK, "requested_at", "review-requested"),
            (TEST_MARK, "sent_at", "test-sent"),
        ):
            stamp = _mark(registration, mark, field)
            if stamp is not None:
                events.append((name, parse_instant(stamp)))
        if registration.status in TERMINAL_EVENTS:
            events.append((registration.status.value, registration.last_modified))
        return DecisionView(
            registration_id=registration.id,
            status=registration.status,
            missing=review.missing,
            approvals=approvals,
            can_approve=registration.status is RegistrationStatus.IN_REVIEW and not review.missing,
            test_sent_at=_mark(registration, TEST_MARK, "sent_at"),
            test_channel=_mark(registration, TEST_MARK, "channel"),
            timeline=tuple(sorted(events, key=lambda event: event[1])),
        )


# -------------------------------------------------------------------------------- the actions


@dataclass(frozen=True, slots=True)
class RegistrationActionCommand:
    idempotency_key: str
    actor: Actor
    registration_id: str


@dataclass(frozen=True, slots=True)
class SentTestResult:
    sent_at: datetime
    channel: Channel


@dataclass(frozen=True, slots=True)
class ReviewRequestResult:
    requested_at: datetime


@dataclass(frozen=True, slots=True)
class ConfirmDetailsResult:
    status: RegistrationStatus
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: object


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _replayed(stored: object, fingerprint: str) -> object | None:
    if stored is None:
        return None
    if not isinstance(stored, _Stored) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different registration command")
    return stored.result


def _key(operation: str, scope: ScopeId, key: str) -> str:
    return f"registration-view:{operation}:{scope}:{key}"


async def _lead_or_applicant(
    uow: UnitOfWork, actor: Actor, registration_id: str, *, lead_may: bool
) -> Registration:
    if lead_may and actor.role is Role.LEAD:
        check_may_review(actor)
        registration = await uow.registrations.get(registration_id)
        if registration is None:
            raise NotFound("no registration with this id")
        return registration
    if actor.role is not Role.REPORTER:
        raise NotAllowed("only the applicant may do this")
    return await _own(uow, actor, registration_id)


def _marked(registration: Registration, mark: str, values: dict[str, Any]) -> Registration:
    return replace(registration, draft={**registration.draft, mark: values})


class SendTestNotification:
    """Queue the test message (T1) to the applicant's post by the channel they chose. The applicant
    asks for it, or the lead sends it again. The message is sealed and sent by the sender, like any
    other; it carries no link and asks for nothing."""

    def __init__(
        self, uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock, sealer: ContentSealer
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._sealer = sealer

    async def execute(self, command: RegistrationActionCommand) -> SentTestResult:
        fingerprint = _fingerprint("test", command.registration_id, command.actor.practitioner_id)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _scope_of(uow)
            key = _key("test", scope, command.idempotency_key)
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if isinstance(replay, SentTestResult):
                return replay
            registration = await _lead_or_applicant(
                uow, command.actor, command.registration_id, lead_may=True
            )
            if registration.status not in TEST_STATUSES:
                raise InvalidTransition("a test notification needs a submitted registration")
            last = _mark(registration, TEST_MARK, "sent_at")
            if last is not None and now - parse_instant(last) < TEST_AGAIN_AFTER:
                raise Conflict("a test notification was sent a moment ago")
            role_id = registration.requester_role_id
            if role_id is None:
                raise ValidationFailed("requester_role_id", "the registration has no requester")
            channel = await self._channel(uow, registration, role_id)
            entry = await uow.scope.get_entry(registration.service_id)
            if entry is None:
                raise NotFound("this service is not on the scope list")
            await queue_message(
                uow,
                self._ids,
                self._sealer,
                scope=scope,
                rendered=render(MessageId.T1, channel, service=entry.name),
                recipient_role_id=role_id,
                about_id=registration.service_id,
                now=now,
            )
            await uow.registrations.save(
                _marked(registration, TEST_MARK, {"sent_at": _iso(now), "channel": channel.value})
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE_TEST,
                    actor=command.actor,
                    entity_ids=(registration.id, registration.service_id),
                    snapshot={"channel": channel.value},
                    at=now,
                )
            )
            result = SentTestResult(sent_at=now, channel=channel)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result

    @staticmethod
    async def _channel(uow: UnitOfWork, registration: Registration, role_id: str) -> Channel:
        """The channel the applicant chose for reports, or the one the invitation suggested. A
        channel with no contact held is refused here, so a test is never queued to nobody."""
        reporting = read_draft(registration).reporting
        chosen = None if reporting is None or not reporting.channel else reporting.channel
        if chosen is None:
            role = await uow.people.get_role(role_id)
            if role is None or role.channel is None:
                raise ValidationFailed("channel", "the reporting step has no channel yet")
            channel = role.channel
        else:
            channel = Channel(chosen)
        if channel is Channel.TEXT and not await uow.contacts.get_phone(role_id):
            raise ValidationFailed("contact", "no mobile number is held for this channel")
        if channel is Channel.EMAIL and not await uow.contacts.get_email(role_id):
            raise ValidationFailed("contact", "no email address is held for this channel")
        return channel


class RequestRegistrationReview:
    """The applicant asks for the review to be looked at: recorded for the lead's queue. It changes
    no state, and may be asked again."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RegistrationActionCommand) -> ReviewRequestResult:
        fingerprint = _fingerprint("review", command.registration_id, command.actor.practitioner_id)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _scope_of(uow)
            key = _key("review", scope, command.idempotency_key)
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if isinstance(replay, ReviewRequestResult):
                return replay
            registration = await _lead_or_applicant(
                uow, command.actor, command.registration_id, lead_may=False
            )
            if registration.status not in REVIEW_REQUEST_STATUSES:
                raise InvalidTransition("a review can be asked for only while it is waiting")
            await uow.registrations.save(
                _marked(registration, REVIEW_REQUEST_MARK, {"requested_at": _iso(now)})
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE_REVIEW,
                    actor=command.actor,
                    entity_ids=(registration.id, registration.service_id),
                    snapshot={"status": registration.status.value},
                    at=now,
                )
            )
            result = ReviewRequestResult(requested_at=now)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class ConfirmRegistrationDetails:
    """The applicant says the details are all correct when a re-check is due: reverify to live."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: RegistrationActionCommand) -> ConfirmDetailsResult:
        fingerprint = _fingerprint(
            "confirm", command.registration_id, command.actor.practitioner_id
        )
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = _scope_of(uow)
            key = _key("confirm", scope, command.idempotency_key)
            replay = _replayed(await uow.idempotency.get(key), fingerprint)
            if isinstance(replay, ConfirmDetailsResult):
                return replay
            registration = await _lead_or_applicant(
                uow, command.actor, command.registration_id, lead_may=False
            )
            if registration.status is not RegistrationStatus.REVERIFY:
                raise InvalidTransition("the details can be confirmed only when a check is due")
            status = transition_registration(registration.status, RegistrationStatus.LIVE)
            confirmed = _marked(registration, DETAILS_MARK, {"confirmed_at": _iso(now)})
            await uow.registrations.save(replace(confirmed, status=status, last_modified=now))
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE_CONFIRM,
                    actor=command.actor,
                    entity_ids=(registration.id, registration.service_id),
                    snapshot={"status": status.value},
                    at=now,
                )
            )
            result = ConfirmDetailsResult(status=status, confirmed_at=now)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result
