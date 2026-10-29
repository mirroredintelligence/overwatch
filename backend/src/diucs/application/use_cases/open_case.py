"""OpenCase and UpdateCase: an advisor's case for a patient need (U11, P21, D18, D19).

An advisor opens an empty case at the start of a call, then fills in the age band, the postcode
district, the needs, the urgency and the referrer's scores. Only the district of the postcode is
stored (DEC-067 item 1). The reference is four digits, unique in the tenant among every case,
closed ones included (DEC-067 item 7). The case, its audit entry and its replay record are written
in one unit of work. No outbox message is written: a case sends nothing.

The tenant comes only from the unit of work's scope, never from a parameter (DEC-130 to DEC-134).
Replay is keyed by the use case, the tenant and the caller's key; a key reused with another body is
a Conflict.
"""

import hashlib
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.idempotency import IdempotencyStore
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound, current_scope_or_none
from diucs.domain.codes import AgeBand, NeedCategory, ReferrerType, Role, Urgency
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.case import Case
from diucs.domain.model.scores import (
    AmbulanceCategory,
    ClinicalFrailty,
    ManchesterTriage,
    News2,
    PathwaysDx,
    Score,
)
from diucs.domain.rules.booking_rules import REFERENCE_ATTEMPTS, new_reference
from diucs.domain.rules.postcode import normalise_postcode, postcode_district

OPEN_CASE: Final = "OpenCase"
UPDATE_CASE: Final = "UpdateCase"
CREATE_ACTION: Final = "C"
UPDATE_ACTION: Final = "U"
ALLOWED_ROLES: Final = frozenset({Role.ADVISOR, Role.CLINICAL})
_SCORE_TYPES: Final = (News2, ClinicalFrailty, AmbulanceCategory, ManchesterTriage, PathwaysDx)


@dataclass(frozen=True, slots=True)
class OpenCaseCommand:
    idempotency_key: str
    actor: Actor
    referrer_type: ReferrerType


@dataclass(frozen=True, slots=True)
class OpenCaseResult:
    case_id: str
    reference: str


@dataclass(frozen=True, slots=True)
class UpdateCaseCommand:
    idempotency_key: str
    actor: Actor
    case_id: str
    age_band: AgeBand | None = None
    postcode: str | None = None
    needs: tuple[NeedCategory, ...] | None = None
    urgency: Urgency | None = None
    scores: tuple[Score, ...] | None = None


@dataclass(frozen=True, slots=True)
class UpdateCaseResult:
    case_id: str
    complete: bool
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _StoredOpen:
    """What the idempotency store keeps for an open: the command's fingerprint and its result."""

    fingerprint: str
    result: OpenCaseResult


@dataclass(frozen=True, slots=True)
class _StoredUpdate:
    """What the idempotency store keeps for an update: the command's fingerprint and its result."""

    fingerprint: str
    result: UpdateCaseResult


def check_role(actor: Actor) -> None:
    if actor.role not in ALLOWED_ROLES:
        raise NotAllowed("only an advisor or a clinician may open or update a case")


def tenant_scope(scope: ScopeId | None) -> ScopeId:
    """The bound tenant. No scope, or a network scope, is refused: a case is one tenant's."""
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def district_for(text: object) -> str:
    """The postcode district of a full postcode typed in any spacing or case. Anything that is not
    a full postcode is refused, and the message does not repeat the value."""
    if not isinstance(text, str):
        raise ValidationFailed("postcode", "must be a full postcode")
    full = normalise_postcode(text)
    if full is None:
        raise ValidationFailed("postcode", "must be a full postcode")
    return postcode_district(full)


def new_open_case(
    case_id: str, reference: str, referrer_type: ReferrerType, opened_at: datetime
) -> Case:
    return Case(
        id=case_id,
        reference=reference,
        referrer_type=referrer_type,
        age_band=None,
        postcode=None,
        needs=(),
        urgency=None,
        scores=(),
        opened_at=opened_at,
    )


def missing_fields(case: Case) -> tuple[str, ...]:
    """The fields a case still needs before it is complete, in this order."""
    missing: list[str] = []
    if case.age_band is None:
        missing.append("age_band")
    if case.postcode is None:
        missing.append("postcode")
    if not case.needs:
        missing.append("needs")
    if case.urgency is None:
        missing.append("urgency")
    return tuple(missing)


def apply_update(case: Case, command: UpdateCaseCommand) -> Case:
    """The case with the command's fields set. A field left as None is unchanged. Every value is
    checked before the case is rebuilt, so a refusal changes nothing."""
    if case.closed_at is not None:
        raise Conflict("the case is closed and cannot change")
    changes: dict[str, Any] = {}
    if command.age_band is not None:
        if not isinstance(command.age_band, AgeBand):
            raise ValidationFailed("age_band", "must be an age band")
        changes["age_band"] = command.age_band
    if command.postcode is not None:
        changes["postcode"] = district_for(command.postcode)
    if command.needs is not None:
        changes["needs"] = _needs(command.needs)
    if command.urgency is not None:
        if not isinstance(command.urgency, Urgency):
            raise ValidationFailed("urgency", "must be an urgency")
        changes["urgency"] = command.urgency
    if command.scores is not None:
        changes["scores"] = _scores(case, command.scores)
    return replace(case, **changes)


def _needs(needs: object) -> tuple[NeedCategory, ...]:
    if not isinstance(needs, tuple) or not needs:
        raise ValidationFailed("needs", "must be a non-empty tuple of need categories")
    checked = tuple(item for item in needs if isinstance(item, NeedCategory))
    if len(checked) != len(needs):
        raise ValidationFailed("needs", "must be listed need categories")
    if len(set(checked)) != len(checked):
        raise ValidationFailed("needs", "a need may be listed once")
    return checked


def _scores(case: Case, scores: object) -> tuple[Score, ...]:
    """Scores are recorded once and then never change (the CaseRepository port). Repeating the
    recorded scores unchanged is accepted."""
    if not isinstance(scores, tuple):
        raise ValidationFailed("scores", "must be a tuple of scores")
    checked = tuple(item for item in scores if isinstance(item, _SCORE_TYPES))
    if len(checked) != len(scores):
        raise ValidationFailed("scores", "must be listed score values")
    if case.scores and checked != case.scores:
        raise ValidationFailed("scores", "recorded scores cannot change")
    return checked


def snapshot_of(case: Case) -> dict[str, Any]:
    """The audit snapshot: reference, referrer, age band, needs and urgency. Never the postcode."""
    return {
        "reference": case.reference,
        "referrer_type": case.referrer_type,
        "age_band": case.age_band,
        "needs": case.needs,
        "urgency": case.urgency,
    }


async def free_reference(rng: random.Random, is_held: Callable[[str], Awaitable[bool]]) -> str:
    """A four-digit reference that is_held does not report as held (DEC-007). A candidate that is
    held is set aside and another is drawn, up to the attempts the booking rules allow."""
    taken: set[str] = set()
    for _ in range(REFERENCE_ATTEMPTS):
        candidate = new_reference(rng, taken)
        if not await is_held(candidate):
            return candidate
        taken.add(candidate)
    raise Conflict("no free case reference after repeated collisions")


def replay_key(use_case: str, scope: ScopeId, key: str) -> str:
    """The replay key, named by the use case and the tenant. The same key in another tenant is
    another command (TEN-016)."""
    return f"{use_case}:{scope}:{key}"


def open_fingerprint(command: OpenCaseCommand) -> str:
    body = repr(
        (command.actor.role.value, command.actor.practitioner_id, command.referrer_type.value)
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def update_fingerprint(command: UpdateCaseCommand) -> str:
    body = repr(
        (
            command.case_id,
            command.actor.role.value,
            command.actor.practitioner_id,
            command.age_band,
            command.postcode,
            command.needs,
            command.urgency,
            command.scores,
        )
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _same_command(stored: str, fingerprint: str) -> None:
    if stored != fingerprint:
        raise Conflict("this command key was used for a different command")


async def _holds_reference(uow: UnitOfWork, reference: str) -> bool:
    return await uow.cases.get_by_reference(reference) is not None


class OpenCase:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        idempotency: IdempotencyStore,
        rng: random.Random,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._idempotency = idempotency
        self._rng = rng

    async def execute(self, command: OpenCaseCommand) -> OpenCaseResult:
        check_role(command.actor)
        scope = tenant_scope(current_scope_or_none())
        fingerprint = open_fingerprint(command)
        early = await self._idempotency.get(replay_key(OPEN_CASE, scope, command.idempotency_key))
        if isinstance(early, _StoredOpen):
            _same_command(early.fingerprint, fingerprint)
            return early.result

        async with self._uow_factory() as uow:
            key = replay_key(OPEN_CASE, tenant_scope(uow.unit_scope), command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _StoredOpen):
                _same_command(stored.fingerprint, fingerprint)
                return stored.result

            now = self._clock.now()
            reference = await free_reference(self._rng, lambda held: _holds_reference(uow, held))
            case = new_open_case(self._ids.new_id(), reference, command.referrer_type, now)
            await uow.cases.add(case)
            await uow.audit.append(
                AuditEntry(
                    action=CREATE_ACTION,
                    use_case=OPEN_CASE,
                    actor=command.actor,
                    entity_ids=(case.id,),
                    snapshot=snapshot_of(case),
                    at=now,
                )
            )
            result = OpenCaseResult(case_id=case.id, reference=reference)
            await uow.idempotency.put(key, _StoredOpen(fingerprint, result))
            await uow.commit()
        return result


class UpdateCase:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        idempotency: IdempotencyStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._idempotency = idempotency

    async def execute(self, command: UpdateCaseCommand) -> UpdateCaseResult:
        check_role(command.actor)
        scope = tenant_scope(current_scope_or_none())
        fingerprint = update_fingerprint(command)
        early = await self._idempotency.get(replay_key(UPDATE_CASE, scope, command.idempotency_key))
        if isinstance(early, _StoredUpdate):
            _same_command(early.fingerprint, fingerprint)
            return early.result

        async with self._uow_factory() as uow:
            key = replay_key(UPDATE_CASE, tenant_scope(uow.unit_scope), command.idempotency_key)
            stored = await uow.idempotency.get(key)
            if isinstance(stored, _StoredUpdate):
                _same_command(stored.fingerprint, fingerprint)
                return stored.result

            case = await uow.cases.get(command.case_id)
            if case is None:
                raise NotFound("no case with this id")
            updated = apply_update(case, command)
            await uow.cases.save(updated)
            now = self._clock.now()
            missing = missing_fields(updated)
            await uow.audit.append(
                AuditEntry(
                    action=UPDATE_ACTION,
                    use_case=UPDATE_CASE,
                    actor=command.actor,
                    entity_ids=(updated.id,),
                    snapshot=snapshot_of(updated),
                    at=now,
                )
            )
            result = UpdateCaseResult(case_id=updated.id, complete=not missing, missing=missing)
            await uow.idempotency.put(key, _StoredUpdate(fingerprint, result))
            await uow.commit()
        return result
