"""What the owner's and the approver's criteria pages read (W7B B, DEC-799 to DEC-801).

`GetCriteriaOverview`: a service's current criteria, the draft the approver sent back (U30 keeps no
draft store: a sent-back version is the draft), the change waiting for approval, whether the
review is overdue (and since when), the shift lead to ask, and whether the reader holds the owner
post. `GetPendingChange`: the change waiting for approval, told in words against the current
version, with its reason, the author's post and whether the reader wrote it (the author may not
approve their own change, so the page says so). Read-only.

The owner reads the criteria of a service they hold the criteria-owner post for; a clinical lead
and the shift lead read any service of the tenant. Anyone else, another service and an unknown
one are the one NotFound/NotAllowed answer. The shift lead's phone is the tenant's own contact
(`shift-lead-escalation`): with none, the page names none, never a default. The overdue date is the
review-by date, judged on the London day.
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.use_cases.criteria import author_label
from diucs.domain.codes import CriteriaStatus, NeedCategory, PractitionerRoleCode, Role, display
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.tenant import ContactKind
from diucs.domain.rules.criteria_workflow import is_review_overdue
from diucs.domain.rules.london_time import to_london

READERS: Final = frozenset({Role.OWNER, Role.CLINICAL, Role.LEAD})
NO_LIMIT: Final = "no limit"


@dataclass(frozen=True, slots=True)
class VersionView:
    criteria: ServiceCriteria
    author_role: str | None


@dataclass(frozen=True, slots=True)
class ShiftLead:
    label: str
    phone: str


@dataclass(frozen=True, slots=True)
class CriteriaOverviewView:
    service_id: str
    service_name: str
    current: VersionView
    draft: VersionView | None
    pending: ServiceCriteria | None
    overdue: bool
    overdue_since: date | None
    shift_lead: ShiftLead | None
    is_owner: bool


@dataclass(frozen=True, slots=True)
class Change:
    field: str
    label: str
    before: object
    after: object
    words: str


@dataclass(frozen=True, slots=True)
class PendingChangeView:
    service_id: str
    service_name: str
    pending: VersionView
    is_author: bool
    changes: tuple[Change, ...]


async def _service_name(uow: UnitOfWork, service_id: str) -> str:
    entry = await uow.scope.get_entry(service_id)
    if entry is not None:
        return entry.name
    profile = await uow.services.get(service_id)
    if profile is None:
        raise NotFound("no service with this id")
    return profile.name


async def _held_roles(uow: UnitOfWork, actor: Actor) -> list[str]:
    """The ids of the posts the reader holds. A reader with no named practitioner holds none."""
    if actor.practitioner_id is None:
        return []
    return [role.id for role in await uow.people.roles_for_practitioner(actor.practitioner_id)]


async def _check_reader(uow: UnitOfWork, actor: Actor, service_id: str) -> None:
    if actor.role not in READERS:
        raise NotAllowed("this role may not read criteria")
    if actor.role is not Role.OWNER:
        return
    if actor.practitioner_id is None:
        raise NotAllowed("a named owner is needed")
    roles = await uow.people.roles_for_practitioner(actor.practitioner_id)
    if not any(
        role.active
        and role.code is PractitionerRoleCode.CRITERIA_OWNER
        and role.service_id == service_id
        for role in roles
    ):
        raise NotAllowed("only the criteria owner of this service may read its criteria")


async def _version(uow: UnitOfWork, criteria: ServiceCriteria) -> VersionView:
    return VersionView(criteria, await author_label(uow, criteria.owner_role_id))


class GetCriteriaOverview:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, service_id: str) -> CriteriaOverviewView:
        today = to_london(self._clock.now()).date()
        async with self._uow_factory() as uow:
            await _check_reader(uow, actor, service_id)
            current = await uow.criteria.current_for_service(service_id)
            if current is None:
                raise NotFound("this service has no current criteria")
            versions = await uow.criteria.history(service_id)
            held = await _held_roles(uow, actor)
            contacts = await uow.tenant_config.contacts()
            name = await _service_name(uow, service_id)
            current_view = await _version(uow, current)
            returned = next((v for v in versions if v.status is CriteriaStatus.DRAFT), None)
            waiting = next(
                (v for v in versions if v.status is CriteriaStatus.PENDING_APPROVAL), None
            )
            draft_view = None if returned is None else await _version(uow, returned)
        overdue = is_review_overdue(current, today)
        lead = next((c for c in contacts if c.kind is ContactKind.SHIFT_LEAD_ESCALATION), None)
        return CriteriaOverviewView(
            service_id=service_id,
            service_name=name,
            current=current_view,
            draft=draft_view,
            pending=waiting,
            overdue=overdue,
            overdue_since=current.review_by if overdue else None,
            shift_lead=None if lead is None else ShiftLead(lead.label, lead.value),
            is_owner=current.owner_role_id in held,
        )


def _labels(needs: frozenset[NeedCategory]) -> list[str]:
    return [display(need) for need in sorted(needs, key=lambda need: need.value)]


def _joined(items: list[str]) -> str:
    return ", ".join(items)


def _set_words(verb_now: str, verb_no_longer: str, added: list[str], removed: list[str]) -> str:
    parts: list[str] = []
    if added:
        parts.append(f"{verb_now}: {_joined(added)}")
    if removed:
        parts.append(f"{verb_no_longer}: {_joined(removed)}")
    return ". ".join(parts)


def _limit(value: int | None) -> str:
    return NO_LIMIT if value is None else str(value)


def describe_changes(
    current: ServiceCriteria | None, proposed: ServiceCriteria
) -> tuple[Change, ...]:
    """What the proposed version changes against the current one, in words, in the order of the
    screen: the two ages, then the needs accepted and excluded, then the districts. A field that is
    the same is not listed. With no current version nothing is a change."""
    if current is None:
        return ()
    changes: list[Change] = []
    if proposed.age_min != current.age_min:
        changes.append(
            Change(
                "ageMin",
                "Youngest age",
                current.age_min,
                proposed.age_min,
                f"Youngest age: {current.age_min} becomes {proposed.age_min}",
            )
        )
    if proposed.age_max != current.age_max:
        changes.append(
            Change(
                "ageMax",
                "Oldest age",
                current.age_max,
                proposed.age_max,
                f"Oldest age: {_limit(current.age_max)} becomes {_limit(proposed.age_max)}",
            )
        )
    for field, label, before, after, now_word, then_word in (
        (
            "accepts",
            "Accepts",
            current.accepts,
            proposed.accepts,
            "Now accepts",
            "No longer accepts",
        ),
        (
            "excludes",
            "Excludes",
            current.excludes,
            proposed.excludes,
            "Now excludes",
            "No longer excludes",
        ),
    ):
        if before != after:
            changes.append(
                Change(
                    field,
                    label,
                    _labels(before),
                    _labels(after),
                    _set_words(
                        now_word, then_word, _labels(after - before), _labels(before - after)
                    ),
                )
            )
    if proposed.districts != current.districts:
        changes.append(
            Change(
                "districts",
                "Districts",
                sorted(current.districts),
                sorted(proposed.districts),
                _set_words(
                    "Now covers",
                    "No longer covers",
                    sorted(proposed.districts - current.districts),
                    sorted(current.districts - proposed.districts),
                ),
            )
        )
    return tuple(changes)


class GetPendingChange:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def execute(self, actor: Actor, service_id: str) -> PendingChangeView:
        async with self._uow_factory() as uow:
            await _check_reader(uow, actor, service_id)
            versions = await uow.criteria.history(service_id)
            waiting = next(
                (v for v in versions if v.status is CriteriaStatus.PENDING_APPROVAL), None
            )
            if waiting is None:
                raise NotFound("no change is waiting for approval")
            current = await uow.criteria.current_for_service(service_id)
            held = await _held_roles(uow, actor)
            name = await _service_name(uow, service_id)
            view = await _version(uow, waiting)
        return PendingChangeView(
            service_id=service_id,
            service_name=name,
            pending=view,
            is_author=waiting.owner_role_id in held,
            changes=describe_changes(current, waiting),
        )
