"""Criteria change, approval, confirmation and history (U30, docs/spec/domain-rules.md section 4.2).

Change: the owner of a service's criteria drafts version n+1 and sends it for second approval. Until
it is approved, advisors keep seeing the current version, and only one version per service may be
pending. Approval: a practitioner holding the clinical-lead code approves or sends back; the author
(the holder of the version's owner role) may not decide on their own change. Confirmation: the
owner says the current criteria are still right, with no new version.

The author of a version is the owner role it was written under (the FHIR `author` element). A
version carries the review period the owner chose, so approval can set review-by from the approval
date (DEC-174). Decisions: docs/delivery/fragments/U30.md.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Literal

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.domain.codes import CriteriaStatus, NeedCategory, PractitionerRoleCode, Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import CriteriaApproved
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.flags import SERVICE_FLAG_CRITERIA_OVERDUE, ServiceFlag
from diucs.domain.model.people import PractitionerRole
from diucs.domain.rules.criteria_workflow import approve, next_review_by, transition_criteria
from diucs.domain.rules.london_time import to_london

AUDIT_CHANGE: str = "C"
AUDIT_UPDATE: str = "U"
_HISTORY_ROLES: frozenset[Role] = frozenset({Role.OWNER, Role.CLINICAL, Role.LEAD})


@dataclass(frozen=True, slots=True)
class CriteriaValues:
    age_min: int
    age_max: int | None
    accepts: frozenset[NeedCategory]
    excludes: frozenset[NeedCategory]
    districts: frozenset[str]


def _active_for(role: PractitionerRole, now: datetime) -> bool:
    if not role.active:
        return False
    return role.period_end is None or role.period_end.astimezone(UTC) > now.astimezone(UTC)


def pending_version(
    *,
    current: ServiceCriteria,
    new_id: str,
    owner_role_id: str,
    values: CriteriaValues,
    change_reason: str,
    review_months: int,
    today: date,
) -> ServiceCriteria:
    """Version n+1 of the current criteria with the owner's values, in pending-approval. Its
    review-by is `today` plus the chosen period; approval sets it again from the approval date."""
    transition_criteria(CriteriaStatus.DRAFT, CriteriaStatus.PENDING_APPROVAL)
    return ServiceCriteria(
        id=new_id,
        service_id=current.service_id,
        version=current.version + 1,
        status=CriteriaStatus.PENDING_APPROVAL,
        age_min=values.age_min,
        age_max=values.age_max,
        districts=values.districts,
        accepts=values.accepts,
        excludes=values.excludes,
        review_by=next_review_by(today, review_months),
        owner_role_id=owner_role_id,
        change_reason=change_reason,
        supersedes_id=current.id,
        review_months=review_months,
    )


def check_may_change(
    roles: Sequence[PractitionerRole], *, service_id: str, owner_role_id: str, now: datetime
) -> None:
    """Only the holder of the service's criteria-owner role may change or confirm its criteria."""
    for role in roles:
        if (
            role.id == owner_role_id
            and role.service_id == service_id
            and role.code is PractitionerRoleCode.CRITERIA_OWNER
            and _active_for(role, now)
        ):
            return
    raise NotAllowed("only the criteria owner of this service may change its criteria")


def check_may_approve(
    roles: Sequence[PractitionerRole], *, service_id: str, author_role_id: str | None, now: datetime
) -> None:
    """A clinical lead of this service (or of the organisation, with no service) decides, and the
    author of the version may not. Fail closed: anything else is refused."""
    if author_role_id is not None and any(role.id == author_role_id for role in roles):
        raise NotAllowed("the author of a criteria change cannot approve it")
    for role in roles:
        if (
            role.code is PractitionerRoleCode.CLINICAL_LEAD
            and role.service_id in (None, service_id)
            and _active_for(role, now)
        ):
            return
    raise NotAllowed("only a clinical lead may approve criteria")


def approved_versions(
    current: ServiceCriteria | None, pending: ServiceCriteria, today: date
) -> tuple[ServiceCriteria | None, ServiceCriteria]:
    """The superseded current version (or None) and the new current version, with review-by set
    from `today` (the approval date) and the period the owner chose."""
    if pending.review_months is None:
        raise ValidationFailed("review_months", "the pending version has no chosen review period")
    old, new = approve(current, pending)
    return old, replace(new, review_by=next_review_by(today, pending.review_months))


def confirmed_review_by(today: date, months: int) -> date:
    return next_review_by(today, months)


@dataclass(frozen=True, slots=True)
class ChangeCriteriaCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    values: CriteriaValues
    change_reason: str
    review_months: int


@dataclass(frozen=True, slots=True)
class ChangeCriteriaResult:
    criteria_id: str
    version: int
    status: CriteriaStatus
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ApproveCriteriaCommand:
    idempotency_key: str
    actor: Actor
    criteria_id: str
    decision: Literal["approve", "send-back"]
    note: str = ""


@dataclass(frozen=True, slots=True)
class ApproveCriteriaResult:
    criteria_id: str
    status: CriteriaStatus
    review_by: date | None
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ConfirmCriteriaCommand:
    idempotency_key: str
    actor: Actor
    service_id: str
    review_months: int


@dataclass(frozen=True, slots=True)
class ConfirmCriteriaResult:
    criteria_id: str
    review_by: date
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class CriteriaHistoryQuery:
    actor: Actor
    service_id: str


@dataclass(frozen=True, slots=True)
class CriteriaVersionView:
    criteria_id: str
    version: int
    status: CriteriaStatus
    review_by: date
    author_role_id: str


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class _Stored:
    """What the idempotency store keeps for a command key: the result and the fingerprint of the
    command that made it (DEC-104)."""

    fingerprint: str
    result: object


def _replay(stored: object, fingerprint: str) -> object | None:
    if stored is None:
        return None
    if not isinstance(stored, _Stored) or stored.fingerprint != fingerprint:
        raise Conflict("this command key was used for a different criteria command")
    return stored.result


def _practitioner_roles(
    actor: Actor, roles_of: list[PractitionerRole] | None
) -> list[PractitionerRole]:
    if actor.practitioner_id is None or roles_of is None:
        raise NotAllowed("a named practitioner is needed for this criteria command")
    return roles_of


class ChangeCriteria:
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

    async def execute(self, command: ChangeCriteriaCommand) -> ChangeCriteriaResult:
        fingerprint = _fingerprint(
            "change",
            command.service_id,
            command.values,
            command.change_reason,
            command.review_months,
            command.actor.practitioner_id,
        )
        early = _replay(await self._idempotency.get(command.idempotency_key), fingerprint)
        if isinstance(early, ChangeCriteriaResult):
            return replace(early, replayed=True)
        now = self._clock.now()
        today = to_london(now).date()
        async with self._uow_factory() as uow:
            await uow.capacity.lock_service(command.service_id)
            stored = _replay(await uow.idempotency.get(command.idempotency_key), fingerprint)
            if isinstance(stored, ChangeCriteriaResult):
                return replace(stored, replayed=True)
            if await uow.services.get(command.service_id) is None:
                raise NotFound("no service with this id")
            current = await uow.criteria.current_for_service(command.service_id)
            if current is None:
                raise NotFound("this service has no current criteria")
            roles = _practitioner_roles(
                command.actor,
                await uow.people.roles_for_practitioner(command.actor.practitioner_id or ""),
            )
            check_may_change(
                roles,
                service_id=command.service_id,
                owner_role_id=current.owner_role_id,
                now=now,
            )
            history = await uow.criteria.history(command.service_id)
            if any(version.status is CriteriaStatus.PENDING_APPROVAL for version in history):
                raise Conflict("a change to these criteria is already waiting for approval")
            pending = pending_version(
                current=current,
                new_id=self._ids.new_id(),
                owner_role_id=current.owner_role_id,
                values=command.values,
                change_reason=command.change_reason,
                review_months=command.review_months,
                today=today,
            )
            await uow.criteria.add(pending)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_CHANGE,
                    use_case="ChangeCriteria",
                    actor=command.actor,
                    entity_ids=(pending.id, command.service_id),
                    snapshot={"version": pending.version, "status": pending.status.value},
                    at=now,
                )
            )
            result = ChangeCriteriaResult(
                criteria_id=pending.id, version=pending.version, status=pending.status
            )
            await uow.idempotency.put(command.idempotency_key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class ApproveCriteria:
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

    async def execute(self, command: ApproveCriteriaCommand) -> ApproveCriteriaResult:
        fingerprint = _fingerprint(
            "approve",
            command.criteria_id,
            command.decision,
            command.note,
            command.actor.practitioner_id,
        )
        early = _replay(await self._idempotency.get(command.idempotency_key), fingerprint)
        if isinstance(early, ApproveCriteriaResult):
            return replace(early, replayed=True)
        now = self._clock.now()
        today = to_london(now).date()
        async with self._uow_factory() as uow:
            seen = await uow.criteria.get(command.criteria_id)
            if seen is None:
                raise NotFound("no criteria version with this id")
            # The service lock comes before the reads that decide the change (lesson L99).
            await uow.capacity.lock_service(seen.service_id)
            stored = _replay(await uow.idempotency.get(command.idempotency_key), fingerprint)
            if isinstance(stored, ApproveCriteriaResult):
                return replace(stored, replayed=True)
            pending = await uow.criteria.get(command.criteria_id)
            if pending is None:
                raise NotFound("no criteria version with this id")
            roles = _practitioner_roles(
                command.actor,
                await uow.people.roles_for_practitioner(command.actor.practitioner_id or ""),
            )
            check_may_approve(
                roles,
                service_id=pending.service_id,
                author_role_id=pending.owner_role_id,
                now=now,
            )
            if command.decision == "send-back":
                returned = replace(
                    pending, status=transition_criteria(pending.status, CriteriaStatus.DRAFT)
                )
                await uow.criteria.save(returned)
                result = ApproveCriteriaResult(
                    criteria_id=returned.id, status=returned.status, review_by=None
                )
            else:
                current = await uow.criteria.current_for_service(pending.service_id)
                old, new = approved_versions(current, pending, today)
                if old is not None:
                    await uow.criteria.save(old)
                await uow.criteria.save(new)
                await uow.outbox.add(
                    outbox_message_for(
                        CriteriaApproved(
                            criteria_id=new.id,
                            service_id=new.service_id,
                            version=new.version,
                            at=now,
                        ),
                        id=self._ids.new_id(),
                        now=now,
                    )
                )
                result = ApproveCriteriaResult(
                    criteria_id=new.id, status=new.status, review_by=new.review_by
                )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_UPDATE,
                    use_case="ApproveCriteria",
                    actor=command.actor,
                    entity_ids=(result.criteria_id, pending.service_id),
                    snapshot={"decision": command.decision, "status": result.status.value},
                    at=now,
                )
            )
            await uow.idempotency.put(command.idempotency_key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class ConfirmCriteria:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        idempotency: IdempotencyStore,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency
        self._clock = clock

    async def execute(self, command: ConfirmCriteriaCommand) -> ConfirmCriteriaResult:
        fingerprint = _fingerprint(
            "confirm", command.service_id, command.review_months, command.actor.practitioner_id
        )
        early = _replay(await self._idempotency.get(command.idempotency_key), fingerprint)
        if isinstance(early, ConfirmCriteriaResult):
            return replace(early, replayed=True)
        now = self._clock.now()
        today = to_london(now).date()
        async with self._uow_factory() as uow:
            await uow.capacity.lock_service(command.service_id)
            stored = _replay(await uow.idempotency.get(command.idempotency_key), fingerprint)
            if isinstance(stored, ConfirmCriteriaResult):
                return replace(stored, replayed=True)
            current = await uow.criteria.current_for_service(command.service_id)
            if current is None:
                raise NotFound("this service has no current criteria")
            roles = _practitioner_roles(
                command.actor,
                await uow.people.roles_for_practitioner(command.actor.practitioner_id or ""),
            )
            check_may_change(
                roles,
                service_id=command.service_id,
                owner_role_id=current.owner_role_id,
                now=now,
            )
            review_by = confirmed_review_by(today, command.review_months)
            await uow.criteria.save(replace(current, review_by=review_by))
            await uow.flags.set_service_flag(
                ServiceFlag(
                    service_id=command.service_id,
                    code=SERVICE_FLAG_CRITERIA_OVERDUE,
                    active=False,
                    reason="criteria confirmed as still right",
                    actor_id=command.actor.practitioner_id or "",
                    at=now,
                )
            )
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_UPDATE,
                    use_case="ConfirmCriteria",
                    actor=command.actor,
                    entity_ids=(current.id, command.service_id),
                    snapshot={"role": command.actor.role.value, "date": today.isoformat()},
                    at=now,
                )
            )
            result = ConfirmCriteriaResult(criteria_id=current.id, review_by=review_by)
            await uow.idempotency.put(command.idempotency_key, _Stored(fingerprint, result))
            await uow.commit()
        return result


class CriteriaHistory:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: CriteriaHistoryQuery) -> list[CriteriaVersionView]:
        if query.actor.role not in _HISTORY_ROLES:
            raise NotAllowed("this role may not read criteria history")
        async with self._uow_factory() as uow:
            versions = await uow.criteria.history(query.service_id)
        return [
            CriteriaVersionView(
                criteria_id=version.id,
                version=version.version,
                status=version.status,
                review_by=version.review_by,
                author_role_id=version.owner_role_id,
            )
            for version in versions
        ]
