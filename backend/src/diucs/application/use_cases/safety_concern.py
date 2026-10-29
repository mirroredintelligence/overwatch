"""ReportSafetyConcern and ReportProblem: the Help screen's reports (U41).

A safety concern is stored as a Task with a per-tenant SC- reference. Its text goes to the protected
store and the Task holds only the handle. The clinical safety officer is told by a K3 that names the
reference and nothing else. A reference to a case or a booking is kept as the focus only when it
matches one; otherwise it is ignored [ASSUMED].

A problem report is stored as a Task too, with its category, an optional text (protected) and
whether
the session was shared. It goes to nobody.

One unit of work holds the report, its text, its counter, its notice and its audit entry (DEC-106).
Any signed-in person may report; a link or a wall screen may not.
"""

import hashlib
from dataclasses import dataclass
from typing import Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope
from diucs.domain.codes import Channel, Role
from diucs.domain.errors import Conflict, NotAllowed, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.safety import SafetyReport
from diucs.domain.rules.safety_report import (
    PROBLEM_REPORT_CODE,
    SAFETY_CONCERN_CODE,
    ProblemCategory,
    SafetyConcernCategory,
    checked_concern_text,
    checked_problem_text,
    concern_notice,
)

SAFETY_OFFICER_ROLE_ID: Final = "clinical-safety-officer"
"""The clinical safety officer's role: the owner of every concern (per tenant, TEN-0xx)."""
CONCERN_KIND: Final = "safety-concern"
PROBLEM_KIND: Final = "problem-report"
AUDIT_ACTION: Final = "C"
CONCERN_USE_CASE: Final = "ReportSafetyConcern"
PROBLEM_USE_CASE: Final = "ReportProblem"
NOT_A_PERSON: Final = "only a signed-in person may report"
NEEDS_PRACTITIONER: Final = "a report needs the person who makes it"


@dataclass(frozen=True, slots=True)
class ReportSafetyConcernCommand:
    idempotency_key: str
    actor: Actor
    category: SafetyConcernCategory
    reference: str | None
    text: str


@dataclass(frozen=True, slots=True)
class ReportSafetyConcernResult:
    reference: str


@dataclass(frozen=True, slots=True)
class ReportProblemCommand:
    idempotency_key: str
    actor: Actor
    category: ProblemCategory
    text: str | None
    session_shared: bool


@dataclass(frozen=True, slots=True)
class ReportProblemResult:
    report_id: str


@dataclass(frozen=True, slots=True)
class _Stored:
    fingerprint: str
    result: ReportSafetyConcernResult | ReportProblemResult


def _check_reporter(actor: Actor) -> str:
    if actor.role in (Role.ANONYMOUS_LINK, Role.WALL):
        raise NotAllowed(NOT_A_PERSON)
    if actor.practitioner_id is None:
        raise NotAllowed(NEEDS_PRACTITIONER)
    return actor.practitioner_id


def _tenant_scope(unit_scope: ScopeId | None) -> ScopeId:
    if unit_scope is None or unit_scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return unit_scope


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


def _replay(stored: _Stored, fingerprint: str) -> ReportSafetyConcernResult | ReportProblemResult:
    if stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different report")
    return stored.result


def _key(kind: str, scope: ScopeId, key: str) -> str:
    return f"{kind}:{scope}:{key}"


async def _focus(uow: UnitOfWork, reference: str | None) -> str | None:
    """The case (or the case of the booking) a reference names, when it names one this tenant holds.
    Otherwise the reference is ignored (U41, [ASSUMED])."""
    if reference is None:
        return None
    case = await uow.cases.get_by_reference(reference)
    if case is not None:
        return case.id
    booking = await uow.bookings.get_by_reference(reference)
    return None if booking is None else booking.case_id


class ReportSafetyConcern:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        ids: IdGenerator,
        clock: Clock,
        sealer: ContentSealer,
    ) -> None:
        """`sealer` seals the officer's K3 notice under its outbox message id (DEC-116)."""
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._ids = ids
        self._clock = clock
        self._sealer = sealer

    async def execute(self, command: ReportSafetyConcernCommand) -> ReportSafetyConcernResult:
        person = _check_reporter(command.actor)
        text = checked_concern_text(command.text)
        try:
            category = SafetyConcernCategory(command.category)
        except ValueError:
            raise ValidationFailed("category", "not a safety concern category") from None
        # The fingerprint never holds the text: a hash of free text would be stored at rest.
        fingerprint = _fingerprint("concern", category.value, command.reference)
        early = await self._idempotency.get(
            _key(CONCERN_KIND, current_scope(), command.idempotency_key)
        )
        if isinstance(early, _Stored):
            return _replay_concern(early, fingerprint)

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = _key(CONCERN_KIND, scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return _replay_concern(stored, fingerprint)

            focus = await _focus(uow, command.reference)
            now = self._clock.now()
            report_id = self._ids.new_id()
            handle = await uow.protected_text.put(CONCERN_KIND, report_id, text)
            reference = await uow.safety_reports.next_concern_reference()
            await uow.safety_reports.add(
                SafetyReport(
                    id=report_id,
                    code=SAFETY_CONCERN_CODE,
                    requester_id=person,
                    category=category.value,
                    created_at=now,
                    reference=reference,
                    focus_id=focus,
                    text_handle=handle,
                    owner_role_id=SAFETY_OFFICER_ROLE_ID,
                )
            )
            title, body = concern_notice(reference)
            notice = render(MessageId.K3, Channel.PUSH, title=title, body=body)
            await queue_message(
                uow,
                self._ids,
                self._sealer,
                scope=scope,
                rendered=notice,
                recipient_role_id=SAFETY_OFFICER_ROLE_ID,
                about_id=report_id,
                now=now,
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=CONCERN_USE_CASE,
                    actor=command.actor,
                    entity_ids=(report_id, *([] if focus is None else [focus])),
                    snapshot={"category": category.value},
                    at=now,
                )
            )
            result = ReportSafetyConcernResult(reference=reference)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class ReportProblem:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        ids: IdGenerator,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._ids = ids
        self._clock = clock

    async def execute(self, command: ReportProblemCommand) -> ReportProblemResult:
        person = _check_reporter(command.actor)
        text = checked_problem_text(command.text)
        if not isinstance(command.session_shared, bool):
            raise ValidationFailed("session_shared", "must say whether the session was shared")
        try:
            category = ProblemCategory(command.category)
        except ValueError:
            raise ValidationFailed("category", "not a problem category") from None
        fingerprint = _fingerprint("problem", category.value, command.session_shared)
        early = await self._idempotency.get(
            _key(PROBLEM_KIND, current_scope(), command.idempotency_key)
        )
        if isinstance(early, _Stored):
            return _replay_problem(early, fingerprint)

        async with self._uow_factory() as uow:
            scope = _tenant_scope(uow.unit_scope)
            key = _key(PROBLEM_KIND, scope, command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _Stored):
                return _replay_problem(stored, fingerprint)

            now = self._clock.now()
            report_id = self._ids.new_id()
            handle = (
                None
                if text is None
                else await uow.protected_text.put(PROBLEM_KIND, report_id, text)
            )
            await uow.safety_reports.add(
                SafetyReport(
                    id=report_id,
                    code=PROBLEM_REPORT_CODE,
                    requester_id=person,
                    category=category.value,
                    created_at=now,
                    text_handle=handle,
                    session_shared=command.session_shared,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=PROBLEM_USE_CASE,
                    actor=command.actor,
                    entity_ids=(report_id,),
                    snapshot={
                        "category": category.value,
                        "session_shared": command.session_shared,
                    },
                    at=now,
                )
            )
            result = ReportProblemResult(report_id=report_id)
            await uow.idempotency.put(key, _Stored(fingerprint, result))
            await uow.commit()
        return result


def _replay_concern(stored: _Stored, fingerprint: str) -> ReportSafetyConcernResult:
    result = _replay(stored, fingerprint)
    assert isinstance(result, ReportSafetyConcernResult)
    return result


def _replay_problem(stored: _Stored, fingerprint: str) -> ReportProblemResult:
    result = _replay(stored, fingerprint)
    assert isinstance(result, ReportProblemResult)
    return result
