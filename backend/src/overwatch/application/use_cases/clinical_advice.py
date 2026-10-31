"""Clinical advice requests (U40): an advisor asks a clinical advisor for advice on a case; a
clinical advisor takes the request (which locks it for 10 minutes) and gives structured advice.
Untouched or idle locks return to the queue.

Clinical advisors are the holders of an active clinical-lead role in effect now (DEC-394): the
model has no other clinical directory. Presence is a cache key per clinician with a 120-second
lifetime, refreshed by the client (DEC-395); advisors see only the count. Going away returns the
clinician's taken, unadvised requests to the queue. Advice is stored as a handle to the protected
text store, never as text, and never in audit (DEC-396). The queue is per tenant: a shared
clinical pool across tenants is out of scope (DEC-130).

Pure rules: domain/rules/clinical_queue (take, return_if_idle, give_advice, queue_order). The
presence key, the choices and the notice wording are here (DEC-395, DEC-396).
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final

from diucs.application.actor import Actor, timer_actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.outbox import outbox_message_for
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.scheduling import cancel_work, schedule_work
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeId, ScopeKind, TenantNotBound
from diucs.application.use_cases.clinical_context import pinned_display
from diucs.application.work import WorkKind
from diucs.domain.codes import AdviceChoice, AgeBand, Channel, NeedCategory, Role, Urgency
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.events import ClinicalAdviceGiven
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render
from diucs.domain.model.case import Case
from diucs.domain.model.clinical import ClinicalAdvice, ClinicalRequestRecord
from diucs.domain.model.scores import News2
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.clinical_queue import (
    TAKE_TIMEOUT,
    ClinicalRequest,
    Presence,
    available_count,
    give_advice,
    queue_order,
    release_for_away,
    return_if_idle,
    take,
    validate_note,
)
from diucs.domain.rules.need_words import need_words

PRESENCE_TTL: Final = timedelta(seconds=120)
PRESENCE_PREFIX: Final = "presence:clinical:"
REQUEST_URGENCIES: Final = frozenset({"now", "within-15-min"})
REQUEST_WHYS: Final = frozenset({"borderline-criteria", "unsure-of-urgency", "other"})
ADVICE_CHOICES: Final = frozenset(
    {"go-ahead", "use-another-service", "clinical-call-to-referrer", "emergency-route"}
)
ADVICE_REASONS: Final = frozenset({"within-criteria-on-judgement", "safer-alternative", "other"})
CLINICAL_NOTE_KIND: Final = "clinical-note"
REQUEST_USE_CASE: Final = "RequestClinicalAdvice"
PRESENCE_USE_CASE: Final = "SetPresence"
TAKE_USE_CASE: Final = "TakeClinicalRequest"
RETURN_USE_CASE: Final = "ReturnIdleRequest"
ADVICE_USE_CASE: Final = "GiveClinicalAdvice"
CREATE: Final = "C"
UPDATE: Final = "U"
NO_REQUEST: Final = "no clinical advice request with this id"
LIST_WAITING: Final = "waiting"
LIST_MINE: Final = "mine"
LIST_DONE: Final = "done"
DONE_LIMIT: Final = 50
"""The most requests a clinician's Done list shows (W7A, DEC-774)."""
NOT_CLOSED_FOR_REQUEST: Final = "the case is closed"


def presence_key(practitioner_id: str) -> str:
    if not practitioner_id.strip():
        raise ValidationFailed("practitioner_id", "is required")
    return f"{PRESENCE_PREFIX}{practitioner_id}"


def parse_presence(text: str | None) -> Presence | None:
    """A stored presence, or None: an unknown or missing value is not available (DEC-395)."""
    if text is None:
        return None
    try:
        return Presence(text)
    except ValueError:
        return None


def validate_request(urgency: str, why: str) -> None:
    if urgency not in REQUEST_URGENCIES:
        raise ValidationFailed("urgency", "must be now or within-15-min")
    if why not in REQUEST_WHYS:
        raise ValidationFailed("why", "is not a known reason")


def validate_advice(choice: str, reason: str | None) -> None:
    if choice not in ADVICE_CHOICES:
        raise ValidationFailed("choice", "is not a known advice choice")
    if reason is not None and reason not in ADVICE_REASONS:
        raise ValidationFailed("reason", "is not a known reason")


def queue_now(
    records: Sequence[ClinicalRequestRecord], now: datetime
) -> list[ClinicalRequestRecord]:
    """The queue at `now`: idle locks are released first (queue_order leaves out a locked request,
    so the release must come before it; DEC-039 item 8), then the order of queue_order."""
    released: dict[str, ClinicalRequestRecord] = {}
    for record in records:
        released[record.request.id] = replace(
            record, request=return_if_idle(record.request, now, DEFAULT_POLICY)
        )
    ordered = queue_order([r.request for r in released.values()])
    return [released[request.id] for request in ordered]


def advice_notice(urgency: str, age_band: str, need: str) -> tuple[str, str]:
    """The K3 notice to a clinical advisor: urgency, age band and need, never a postcode or a
    name (DEC-396)."""
    when = "now" if urgency == "now" else "within 15 min"
    return (
        "Clinical advice requested",
        f"Advice needed {when}. Age {age_band}. Need: {need}.",
    )


def _need_text(needs: Sequence[str]) -> str:
    """The needs in the one table of plain words (DEC-062 item 2)."""
    return need_words([NeedCategory(need) for need in needs]) if needs else "no need recorded"


def _tenant(scope: ScopeId | None) -> ScopeId:
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def _practitioner(actor: Actor) -> str:
    if actor.practitioner_id is None:
        raise NotAllowed("a clinical action needs a practitioner")
    return actor.practitioner_id


async def _available_clinicians(uow: UnitOfWork, cache: Cache, now: datetime) -> list[str]:
    """The role id of each clinical advisor whose presence is available now."""
    found: list[str] = []
    for role in await uow.people.active_clinical_leads(now):
        key = presence_key(role.practitioner_id)
        if parse_presence(await cache.get(key)) is Presence.AVAILABLE:
            found.append(role.id)
    return found


@dataclass(frozen=True, slots=True)
class RequestClinicalAdviceCommand:
    actor: Actor
    case_id: str
    urgency: str
    why: str
    service_id: str | None = None
    """The service the advisor was considering (KI-768): a service of this tenant that is active.
    Another tenant's service and an unknown one are the same not found."""


@dataclass(frozen=True, slots=True)
class RequestClinicalAdviceResult:
    request_id: str
    notified: int


class RequestClinicalAdvice:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        ids: IdGenerator,
        clock: Clock,
        cache: Cache,
        sealer: ContentSealer,
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._cache = cache
        self._sealer = sealer

    async def execute(self, command: RequestClinicalAdviceCommand) -> RequestClinicalAdviceResult:
        if command.actor.role is not Role.ADVISOR:
            raise NotAllowed("only a call advisor may ask for clinical advice")
        validate_request(command.urgency, command.why)
        requester = _practitioner(command.actor)
        async with self._uow_factory() as uow:
            scope = _tenant(uow.unit_scope)
            case = await uow.cases.get(command.case_id)
            if case is None:
                raise NotFound("no case with this id")
            if case.closed_at is not None:
                raise Conflict(NOT_CLOSED_FOR_REQUEST)
            if command.service_id is not None:
                considered = await uow.services.get(command.service_id)
                if considered is None or not considered.active:
                    raise NotFound("no active service with this id")
            now = self._clock.now()
            request_id = self._ids.new_id()
            # The display of the options this advisor had when they asked is kept with the request,
            # so the clinician is shown what the advisor saw then, not a later display (W9G).
            display = pinned_display(await uow.audit.records_for(case.id), requester, now)
            await uow.clinical_requests.add(
                ClinicalRequestRecord(
                    request=ClinicalRequest(
                        id=request_id,
                        case_id=case.id,
                        urgency=command.urgency,
                        requested_at=now,
                    ),
                    requester_id=requester,
                    why=command.why,
                    snapshot_ref=None if display is None else display.id,
                    service_id=command.service_id,
                )
            )
            age = "not recorded" if case.age_band is None else case.age_band.value
            title, body = advice_notice(command.urgency, age, _need_text(case.needs))
            notice = render(MessageId.K3, Channel.PUSH, title=title, body=body)
            recipients = await _available_clinicians(uow, self._cache, now)
            for role_id in recipients:
                await queue_message(
                    uow,
                    self._ids,
                    self._sealer,
                    scope=scope,
                    rendered=notice,
                    recipient_role_id=role_id,
                    about_id=None,
                    now=now,
                )
            await uow.audit.append(
                AuditEntry(
                    action=CREATE,
                    use_case=REQUEST_USE_CASE,
                    actor=command.actor,
                    entity_ids=(request_id, case.id),
                    snapshot={"urgency": command.urgency, "why": command.why},
                    at=now,
                )
            )
            await uow.commit()
        return RequestClinicalAdviceResult(request_id=request_id, notified=len(recipients))


@dataclass(frozen=True, slots=True)
class SetPresenceCommand:
    actor: Actor
    presence: Presence


class SetPresence:
    """A clinical advisor's presence: a cache key with a 120-second lifetime, refreshed by the
    client. Going away returns the taken, unadvised requests to the queue (DEC-395)."""

    def __init__(self, uow_factory: UnitOfWorkFactory, cache: Cache, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._cache = cache
        self._clock = clock

    async def execute(self, command: SetPresenceCommand) -> None:
        if command.actor.role is not Role.CLINICAL:
            raise NotAllowed("only a clinical advisor has a clinical presence")
        clinician = _practitioner(command.actor)
        await self._cache.set(presence_key(clinician), command.presence.value, PRESENCE_TTL)
        if command.presence is not Presence.AWAY:
            return
        async with self._uow_factory() as uow:
            now = self._clock.now()
            taken = await uow.clinical_requests.taken_by(clinician)
            released = release_for_away([r.request for r in taken], clinician)
            by_id = {r.request.id: r for r in taken}
            for request in released:
                await uow.clinical_requests.save(replace(by_id[request.id], request=request))
            await uow.audit.append(
                AuditEntry(
                    action=UPDATE,
                    use_case=PRESENCE_USE_CASE,
                    actor=command.actor,
                    entity_ids=tuple(request.id for request in released),
                    snapshot={"released": len(released)},
                    at=now,
                )
            )
            await uow.commit()


@dataclass(frozen=True, slots=True)
class AvailableClinicians:
    """The number of clinical advisors available now. A count, never a name (U40)."""

    uow_factory: UnitOfWorkFactory
    cache: Cache
    clock: Clock

    async def execute(self) -> int:
        async with self.uow_factory() as uow:
            now = self.clock.now()
            presences: list[Presence | None] = []
            for role in await uow.people.active_clinical_leads(now):
                key = presence_key(role.practitioner_id)
                presences.append(parse_presence(await self.cache.get(key)))
        return available_count([p for p in presences if p is not None])


@dataclass(frozen=True, slots=True)
class TakeClinicalRequestCommand:
    actor: Actor
    request_id: str


class TakeClinicalRequest:
    """Lock a request to one clinical advisor. The return timer is due TAKE_TIMEOUT later. A
    second take by someone else is a Conflict (the rule)."""

    def __init__(self, uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock

    async def execute(self, command: TakeClinicalRequestCommand) -> None:
        if command.actor.role is not Role.CLINICAL:
            raise NotAllowed("only a clinical advisor may take a request")
        clinician = _practitioner(command.actor)
        async with self._uow_factory() as uow:
            record = await uow.clinical_requests.get(command.request_id)
            if record is None:
                raise NotFound(NO_REQUEST)
            now = self._clock.now()
            taken = take(record.request, clinician, now, DEFAULT_POLICY)
            if taken == record.request:
                return
            await uow.clinical_requests.save(replace(record, request=taken))
            for old in await uow.scheduled_work.for_about(
                command.request_id, WorkKind.CLINICAL_RETURN
            ):
                await cancel_work(uow, old, now)
            await schedule_work(
                uow,
                self._ids,
                kind=WorkKind.CLINICAL_RETURN,
                about_id=command.request_id,
                due_at=now + TAKE_TIMEOUT,
                now=now,
            )
            await uow.audit.append(
                AuditEntry(
                    action=UPDATE,
                    use_case=TAKE_USE_CASE,
                    actor=command.actor,
                    entity_ids=(command.request_id,),
                    snapshot=None,
                    at=now,
                )
            )
            await uow.commit()


@dataclass(frozen=True, slots=True)
class ReturnIdleRequest:
    """The work handler for clinical-return: an unadvised lock held for TAKE_TIMEOUT goes back to
    the queue. Idempotent: a request that is advised, or no longer idle, is left as it is."""

    uow_factory: UnitOfWorkFactory
    clock: Clock

    async def execute(self, request_id: str) -> None:
        async with self.uow_factory() as uow:
            record = await uow.clinical_requests.get(request_id)
            if record is None:
                return
            now = self.clock.now()
            returned = return_if_idle(record.request, now, DEFAULT_POLICY)
            if returned == record.request:
                return
            await uow.clinical_requests.save(replace(record, request=returned))
            await uow.audit.append(
                AuditEntry(
                    action=UPDATE,
                    use_case=RETURN_USE_CASE,
                    actor=timer_actor(_tenant(uow.unit_scope).value),
                    entity_ids=(request_id,),
                    snapshot=None,
                    at=now,
                )
            )
            await uow.commit()


@dataclass(frozen=True, slots=True)
class GiveClinicalAdviceCommand:
    actor: Actor
    request_id: str
    choice: str
    reason: str | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class GiveClinicalAdviceResult:
    request_id: str
    choice: str


class GiveClinicalAdvice:
    """The advice on a locked request. The note goes to the protected text store, and only its
    handle is kept on the request; the audit entry holds the choice and the reason (DEC-396).
    Advice cancels the return timer."""

    def __init__(self, uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock

    async def execute(self, command: GiveClinicalAdviceCommand) -> GiveClinicalAdviceResult:
        if command.actor.role is not Role.CLINICAL:
            raise NotAllowed("only a clinical advisor may give clinical advice")
        validate_advice(command.choice, command.reason)
        if command.note is not None:
            validate_note(command.note)
        clinician = _practitioner(command.actor)
        async with self._uow_factory() as uow:
            record = await uow.clinical_requests.get(command.request_id)
            if record is None:
                raise NotFound(NO_REQUEST)
            now = self._clock.now()
            advised = give_advice(record.request, clinician, now, DEFAULT_POLICY)
            handle = None
            if command.note is not None:
                handle = await uow.protected_text.put(
                    CLINICAL_NOTE_KIND, command.request_id, command.note
                )
            advice = ClinicalAdvice(
                choice=command.choice,
                reason=command.reason,
                note_handle=handle,
                clinician_id=clinician,
                at=now,
            )
            await uow.clinical_requests.save(
                ClinicalRequestRecord(
                    request=advised,
                    requester_id=record.requester_id,
                    why=record.why,
                    snapshot_ref=record.snapshot_ref,
                    advice=advice,
                    service_id=record.service_id,
                )
            )
            for work in await uow.scheduled_work.for_about(
                command.request_id, WorkKind.CLINICAL_RETURN
            ):
                await cancel_work(uow, work, now)
            event = ClinicalAdviceGiven(
                request_id=command.request_id, choice=AdviceChoice(command.choice), at=now
            )
            await uow.outbox.add(outbox_message_for(event, id=self._ids.new_id(), now=now))
            await uow.audit.append(
                AuditEntry(
                    action=CREATE,
                    use_case=ADVICE_USE_CASE,
                    actor=command.actor,
                    entity_ids=(command.request_id, record.request.case_id),
                    snapshot={
                        "choice": command.choice,
                        "reason": command.reason,
                        "snapshot_ref": record.snapshot_ref,
                    },
                    at=now,
                )
            )
            await uow.commit()
        return GiveClinicalAdviceResult(request_id=command.request_id, choice=command.choice)


@dataclass(frozen=True, slots=True)
class ListClinicalQueue:
    """The queue at now, with idle locks returned (U40). Clinical advisors only."""

    uow_factory: UnitOfWorkFactory
    clock: Clock

    async def execute(self, actor: Actor) -> list[ClinicalRequestRecord]:
        if actor.role is not Role.CLINICAL:
            raise NotAllowed("only a clinical advisor may see the clinical queue")
        async with self.uow_factory() as uow:
            open_records = await uow.clinical_requests.open_requests()
        now = self.clock.now()
        await persist_returns(self.uow_factory, self.clock, _lapsed(open_records, now))
        return queue_now(open_records, now)


@dataclass(frozen=True, slots=True)
class CaseGlance:
    """What a clinical advisor and the advisor who asked may see of the case: its number, age band,
    needs, urgency and NEWS2. Never the postcode, the district or any identifier (DEC-396)."""

    reference: str
    age_band: AgeBand | None
    needs: tuple[NeedCategory, ...]
    urgency: Urgency | None
    news2: int | None


def glance_of(case: Case) -> CaseGlance:
    news2 = next((score.value for score in case.scores if isinstance(score, News2)), None)
    return CaseGlance(
        reference=case.reference,
        age_band=case.age_band,
        needs=case.needs,
        urgency=case.urgency,
        news2=news2,
    )


@dataclass(frozen=True, slots=True)
class ClinicalRequestView:
    """A request as it is shown: the record after any lapsed lock is returned, the glance of its
    case (None when the case cannot be read), the advice note (read for one request only) and the
    time a held lock ends."""

    record: ClinicalRequestRecord
    case: CaseGlance | None
    note: str | None
    returns_at: datetime | None
    service_name: str | None = None
    """The name now of the service the advisor was considering (KI-768); None when none was named
    or the service is no longer listed."""


def _lock_ends(record: ClinicalRequestRecord) -> datetime | None:
    request = record.request
    if request.taken_at is None or request.advised_at is not None:
        return None
    return request.taken_at + DEFAULT_POLICY.clinical_take_timeout


async def _glances(uow: UnitOfWork, case_ids: Sequence[str]) -> dict[str, CaseGlance]:
    found: dict[str, CaseGlance] = {}
    for case_id in dict.fromkeys(case_ids):
        case = await uow.cases.get(case_id)
        if case is not None:
            found[case_id] = glance_of(case)
    return found


async def _service_names(
    uow: UnitOfWork, records: Sequence[ClinicalRequestRecord]
) -> dict[str, str]:
    """The name now of each service a request was about; one no longer listed has none."""
    found: dict[str, str] = {}
    for service_id in dict.fromkeys(r.service_id for r in records if r.service_id is not None):
        profile = await uow.services.get(service_id)
        if profile is not None:
            found[service_id] = profile.name
    return found


async def persist_returns(
    uow_factory: UnitOfWorkFactory, clock: Clock, request_ids: Sequence[str]
) -> None:
    """Release the locks that have lapsed among these requests in the store (KI-233), so what is
    stored is what the queue shows. Its own unit of work, run after the read that found them, and
    it reads each request afresh: a read never fails because another read got there first, and a
    request that is no longer idle, or is advised, is left as it is. Written as the system, in
    the tenant (the same entry the return timer writes)."""
    if not request_ids:
        return
    try:
        async with uow_factory() as uow:
            now = clock.now()
            released = 0
            for request_id in request_ids:
                record = await uow.clinical_requests.get(request_id)
                if record is None:
                    continue
                returned = return_if_idle(record.request, now, DEFAULT_POLICY)
                if returned == record.request:
                    continue
                await uow.clinical_requests.save(replace(record, request=returned))
                for work in await uow.scheduled_work.for_about(
                    request_id, WorkKind.CLINICAL_RETURN
                ):
                    await cancel_work(uow, work, now)
                await uow.audit.append(
                    AuditEntry(
                        action=UPDATE,
                        use_case=RETURN_USE_CASE,
                        actor=timer_actor(_tenant(uow.unit_scope).value),
                        entity_ids=(request_id,),
                        snapshot=None,
                        at=now,
                    )
                )
                released += 1
            if released:
                await uow.commit()
    except Conflict:
        return  # another reader released it first: what is stored is what the queue shows


def _lapsed(records: Sequence[ClinicalRequestRecord], now: datetime) -> list[str]:
    return [
        r.request.id for r in records if return_if_idle(r.request, now, DEFAULT_POLICY) != r.request
    ]


@dataclass(frozen=True, slots=True)
class ReadClinicalRequest:
    """One request, for the advisor who asked and for any clinical advisor. Another advisor, and any
    other role, are refused with NotFound, the answer for an id that is not there. None means the id
    is not a clinical advice request at all (the caller may then try it as something else)."""

    uow_factory: UnitOfWorkFactory
    clock: Clock

    async def execute(self, actor: Actor, request_id: str) -> ClinicalRequestView | None:
        async with self.uow_factory() as uow:
            record = await uow.clinical_requests.get(request_id)
            if record is None:
                return None
            if actor.role is Role.CLINICAL:
                pass
            elif actor.role is Role.ADVISOR:
                if actor.practitioner_id is None or actor.practitioner_id != record.requester_id:
                    raise NotFound(NO_REQUEST)
            else:
                raise NotFound(NO_REQUEST)
            now = self.clock.now()
            released = replace(record, request=return_if_idle(record.request, now, DEFAULT_POLICY))
            case = await uow.cases.get(record.request.case_id)
            advice = record.advice
            note = (
                None
                if advice is None or advice.note_handle is None
                else await uow.protected_text.get(advice.note_handle)
            )
            names = await _service_names(uow, [record])
        return ClinicalRequestView(
            record=released,
            case=None if case is None else glance_of(case),
            note=note,
            returns_at=_lock_ends(released),
            service_name=None if record.service_id is None else names.get(record.service_id),
        )


@dataclass(frozen=True, slots=True)
class ListClinicalRequests:
    """A clinical advisor's lists (W7A): `waiting` is the queue, `mine` the requests this clinician
    holds (a lapsed lock is not held), `done` the requests this clinician advised on, the latest
    first and at most DONE_LIMIT. Each carries the glance of its case."""

    uow_factory: UnitOfWorkFactory
    clock: Clock

    async def execute(self, actor: Actor, which: str) -> list[ClinicalRequestView]:
        if actor.role is not Role.CLINICAL:
            raise NotAllowed("only a clinical advisor may see the clinical lists")
        if which not in (LIST_WAITING, LIST_MINE, LIST_DONE):
            raise ValidationFailed("status", "is not a clinical list")
        clinician = _practitioner(actor) if which != LIST_WAITING else None
        now = self.clock.now()
        async with self.uow_factory() as uow:
            stored: list[ClinicalRequestRecord] = []
            if which == LIST_WAITING:
                stored = await uow.clinical_requests.open_requests()
                records = queue_now(stored, now)
            elif which == LIST_MINE:
                assert clinician is not None
                stored = await uow.clinical_requests.taken_by(clinician)
                records = [
                    held
                    for held in (
                        replace(r, request=return_if_idle(r.request, now, DEFAULT_POLICY))
                        for r in stored
                    )
                    if held.request.taken_by == clinician
                ]
            else:
                assert clinician is not None
                records = await uow.clinical_requests.advised_by(clinician, DONE_LIMIT)
            glances = await _glances(uow, [r.request.case_id for r in records])
            names = await _service_names(uow, records)
        # What a list drops, or shows as released, is released in the store too (KI-233).
        await persist_returns(self.uow_factory, self.clock, _lapsed(stored, now))
        return [
            ClinicalRequestView(
                record=record,
                case=glances.get(record.request.case_id),
                note=None,
                returns_at=_lock_ends(record),
                service_name=None if record.service_id is None else names.get(record.service_id),
            )
            for record in records
        ]


@dataclass(frozen=True, slots=True)
class PresenceView:
    """The clinician's own presence (None when none is set or it has lapsed) and the number of
    clinical advisors available now. A count, never a name."""

    own: Presence | None
    available: int


@dataclass(frozen=True, slots=True)
class ReadPresence:
    uow_factory: UnitOfWorkFactory
    cache: Cache
    clock: Clock

    async def execute(self, actor: Actor) -> PresenceView:
        if actor.role is not Role.CLINICAL:
            raise NotAllowed("only a clinical advisor has a clinical presence")
        own = parse_presence(await self.cache.get(presence_key(_practitioner(actor))))
        count = await AvailableClinicians(self.uow_factory, self.cache, self.clock).execute()
        return PresenceView(own=own, available=count)
