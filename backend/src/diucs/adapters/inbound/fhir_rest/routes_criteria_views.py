"""The criteria reads of the owner's and the approver's pages over HTTP (W7B B, DEC-799 to DEC-801).
Thin: each route runs one use case and maps the result to camelCase JSON.

GET /criteria/{service_id}           owner, clinical lead or shift lead: the current values, the
                                     draft sent back, the change waiting, the overdue date and the
                                     shift lead to ask
GET /criteria/{service_id}/pending   the change waiting for approval, in words, with its reason, the
                                     author's post and `isAuthor`

The history (with `changedOn` and `authorRole` on each version) stays on `GET /fhir/Basic`. An owner
reads only the service they hold the owner post for; any other reader, service or id is the one 404
(require_role and the use case). Every answer is no-store. Tenancy: bound at the edge (TEN-018).
"""

from typing import Annotated, Any, Final, Protocol, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from diucs.adapters.inbound.fhir_rest.app import get_container
from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.capability import FhirJSONResponse
from diucs.adapters.inbound.fhir_rest.routes_registration import NO_STORE
from diucs.application.actor import Actor
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.criteria_views import (
    GetCriteriaOverview,
    GetPendingChange,
    VersionView,
)
from diucs.domain.codes import NeedCategory, Role, display
from diucs.domain.model.criteria import ServiceCriteria

router = APIRouter()

READERS: Final = (Role.OWNER, Role.CLINICAL, Role.LEAD)


class _Container(Protocol):
    @property
    def clock(self) -> Clock: ...
    @property
    def uow_factory(self) -> UnitOfWorkFactory: ...


def _container(request: Request) -> _Container:
    return cast(_Container, get_container(request))


def _needs(needs: frozenset[NeedCategory]) -> list[dict[str, str]]:
    return [
        {"code": need.value, "label": display(need)}
        for need in sorted(needs, key=lambda need: need.value)
    ]


def _day(value: Any) -> str | None:
    return None if value is None else str(value.isoformat())


def _values(criteria: ServiceCriteria) -> dict[str, Any]:
    return {
        "id": criteria.id,
        "version": criteria.version,
        "status": criteria.status.value,
        "reviewBy": criteria.review_by.isoformat(),
        "ageMin": criteria.age_min,
        "ageMax": criteria.age_max,
        "accepts": _needs(criteria.accepts),
        "excludes": _needs(criteria.excludes),
        "districts": sorted(criteria.districts),
        "changedOn": _day(criteria.changed_on),
    }


def _version(view: VersionView) -> dict[str, Any]:
    return {**_values(view.criteria), "authorRole": view.author_role}


@router.get("/criteria/{service_id}")
async def read_criteria(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*READERS))],
) -> Response:
    container = _container(request)
    view = await GetCriteriaOverview(container.uow_factory, container.clock).execute(
        actor, service_id
    )
    draft = None
    if view.draft is not None:
        draft = {**_version(view.draft), "changeReason": view.draft.criteria.change_reason}
    pending = None
    if view.pending is not None:
        pending = {
            "id": view.pending.id,
            "version": view.pending.version,
            "changeReason": view.pending.change_reason,
            "changedOn": _day(view.pending.changed_on),
        }
    return FhirJSONResponse(
        content={
            "serviceId": view.service_id,
            "serviceName": view.service_name,
            "current": _version(view.current),
            "draft": draft,
            "pending": pending,
            "overdue": view.overdue,
            "overdueSince": _day(view.overdue_since),
            "shiftLead": None
            if view.shift_lead is None
            else {"label": view.shift_lead.label, "phone": view.shift_lead.phone},
            "isOwner": view.is_owner,
        },
        headers=NO_STORE,
    )


@router.get("/criteria/{service_id}/pending")
async def read_pending_change(
    service_id: str,
    request: Request,
    actor: Annotated[Actor, Depends(require_role(*READERS))],
) -> Response:
    view = await GetPendingChange(_container(request).uow_factory).execute(actor, service_id)
    pending = view.pending.criteria
    return FhirJSONResponse(
        content={
            "criteriaId": pending.id,
            "serviceId": view.service_id,
            "serviceName": view.service_name,
            "version": pending.version,
            "status": pending.status.value,
            "changeReason": pending.change_reason,
            "authorRole": view.pending.author_role,
            "isAuthor": view.is_author,
            "reviewMonths": pending.review_months,
            "changedOn": _day(pending.changed_on),
            "criteria": _values(pending),
            "changes": [
                {
                    "field": change.field,
                    "label": change.label,
                    "before": change.before,
                    "after": change.after,
                    "words": change.words,
                }
                for change in view.changes
            ],
        },
        headers=NO_STORE,
    )


__all__ = ["router"]
