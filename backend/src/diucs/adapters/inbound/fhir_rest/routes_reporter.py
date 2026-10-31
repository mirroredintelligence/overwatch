"""The reporter app's routes, behind a reporter's bearer token (W7C, DEC-814 to DEC-824).

GET   /reporter/services                          the services the reporter holds, with their state
GET   /reporter/services/{id}/prompt              what is on record, the usual range, reply-by
POST  /reporter/services/{id}/report              a confirm, a number or closed (Idempotency-Key)
GET   /reporter/services/{id}/history?day=today   the day's reports, newest first
POST  /reporter/reports/batch                     several confirms in one call (Idempotency-Key)
GET   /reporter/settings                          channel, masked number, masked cover, days left
POST  /reporter/cover                             a cover number for every post the reporter owns
POST  /reporter/services/{id}/cover               a cover number for one service
POST  /reporter/channel                           how the reporter is contacted
POST  /reporter/services/{id}/accept              yes or no to a service the lead added
GET   /reporter/setup-summary                     the All-set page
POST  /reporter/push-test                         a test notification to the reporter's own phone
GET   /reporter/bookings/{reference}              a booking by its 4-digit reference
POST  /reporter/bookings/{reference}/respond      confirm or decline it (Idempotency-Key)

The token names a person and a device, and is checked on every use (`CheckReporterAccess`): a phone
that was signed out stops working at once, not at the token's expiry. Only role `reporter` passes,
except the test notification, which an executive may ask for too (DEC-1040; any other role is the
404 of every refused role, DEC-086). The services a reporter holds are read from the graph at the
time of the request, never from the token's claim, and a service the reporter does not hold is the
same 404 as an unknown one and as another tenant's (H-452). The routes hold no
business rule: they bind nothing themselves (the token's tenant is bound by `current_actor`), run
one use case and map its result. Responses are `no-store`. A phone number, a token or a code is
never in a body or a log line: the numbers shown are masked.
"""

import datetime as dt
import logging
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import Field, StrictBool, StrictInt

from diucs.adapters.inbound.fhir_rest.auth import require_role
from diucs.adapters.inbound.fhir_rest.concurrency import idempotency_key, replay_or_run
from diucs.adapters.inbound.fhir_rest.errors import operation_outcome
from diucs.adapters.inbound.fhir_rest.routes_identity import (
    RATE_LIMITED_TEXT,
    _answer,
    _Body,
    _Container,
    _container,
    _json,
    _signed_in,
)
from diucs.adapters.inbound.fhir_rest.routes_services import UnitOfWorkIdempotency
from diucs.application.actor import Actor
from diucs.application.ports.outbound.identity import HmacPhoneHasher
from diucs.application.tenant_settings import DirectoryZones, TenantZones
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity
from diucs.application.use_cases.link_access import iso_utc
from diucs.application.use_cases.pin import RATE_WINDOW, limiter_key
from diucs.application.use_cases.report_capacity import ReportCapacity
from diucs.application.use_cases.reporter_app import (
    CoverCommand,
    ReporterReader,
    ReporterReportCommand,
    ReporterReporter,
    ReporterSettingsWriter,
    ReportOutcome,
    ServiceRow,
)
from diucs.application.use_cases.reporter_booking import (
    ReporterBookingReader,
    ReporterBookingResponder,
)
from diucs.application.use_cases.reporter_push import NoPushSubscription, SendPushTest
from diucs.application.use_cases.respond_to_booking import RespondToBooking
from diucs.domain.codes import DeclineReason, Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.reporter_app import channel_for, channel_word

log = logging.getLogger(__name__)

PUSH_TESTS_PER_WINDOW: Final = 3
"""[ASSUMED] Test notifications one reporter may queue in RATE_WINDOW (10 minutes): a few presses of
the button on the All-set page, not a way to buzz a phone."""

router = APIRouter(prefix="/reporter")
_Reporter = Annotated[Actor, Depends(require_role(Role.REPORTER))]
_Notified = Annotated[Actor, Depends(require_role(Role.REPORTER, Role.EXEC))]
"""Who may ask for a test notification: a reporter, and an executive, who holds no post and uses
the notification part of the app only (DEC-1040, DEC-1043). Every other route is a reporter's."""


class ReportBody(_Body):
    kind: str = Field(max_length=16)
    value: StrictInt | None = None
    confirmOutOfRange: StrictBool = False


class BatchItemBody(_Body):
    serviceId: str = Field(min_length=1, max_length=64)
    kind: Literal["confirm"]


class BatchBody(_Body):
    items: list[BatchItemBody] = Field(min_length=1, max_length=10)


class CoverBody(_Body):
    phone: str = Field(min_length=1, max_length=32)
    until: str | None = Field(default=None, max_length=16)
    date: dt.date | None = None


class ChannelBody(_Body):
    channel: str = Field(max_length=16)


class AcceptBody(_Body):
    accept: StrictBool


class RespondBody(_Body):
    decision: Literal["confirm", "decline"]
    reason: str | None = Field(default=None, max_length=32)


class PushTestBody(_Body):
    """A test push takes nothing."""


async def _reporter(request: Request, actor: Actor) -> _Container:
    """The container, once the person and device of the token are still signed in."""
    container = _container(request)
    await _signed_in(container, actor)
    return container


def _zones(container: _Container) -> TenantZones:
    return DirectoryZones(container.tenants)


def _stamp(moment: dt.datetime | None) -> str | None:
    return iso_utc(moment)


def _row(row: ServiceRow) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "state": row.state.value,
        "recordedValue": row.recorded_value,
        "unitLabel": row.unit_label,
        "at": _stamp(row.at),
        "nextDue": _stamp(row.next_due),
        "pendingAcceptance": row.pending_acceptance,
    }
    if row.letter is not None:
        body["letter"] = row.letter
    if row.reply_by is not None:
        body["replyBy"] = _stamp(row.reply_by)
    return body


def _report_answer(outcome: ReportOutcome) -> Response:
    if outcome.result == "recorded":
        return _json(
            200,
            {
                "result": "recorded",
                "serviceName": outcome.service_name,
                "value": outcome.value,
                "recordedAt": _stamp(outcome.recorded_at),
                "nextDue": _stamp(outcome.next_due),
            },
        )
    if outcome.result == "outOfRange":
        return _json(
            200,
            {
                "result": "outOfRange",
                "serviceName": outcome.service_name,
                "value": outcome.value,
                "low": outcome.low,
                "high": outcome.high,
            },
        )
    body: dict[str, Any] = {"result": outcome.result, "serviceName": outcome.service_name}
    if outcome.result == "sendNumber":
        body["reason"] = outcome.reason
    return _json(409, body)


def _reporting(container: _Container) -> ReporterReporter:
    idempotency = UnitOfWorkIdempotency(container.uow_factory)
    return ReporterReporter(
        container.uow_factory,
        container.clock,
        ReportCapacity(container.uow_factory, container.clock, container.ids, idempotency),
        ConfirmCapacity(container.uow_factory, container.clock, container.ids, idempotency),
        _zones(container),
    )


def _writer(container: _Container) -> ReporterSettingsWriter:
    return ReporterSettingsWriter(
        container.uow_factory,
        container.clock,
        container.ids,
        HmacPhoneHasher(container.secrets),
        _zones(container),
    )


# ------------------------------------------------------------------------------- reads


@router.get("/services")
async def services(request: Request, actor: _Reporter) -> Response:
    container = await _reporter(request, actor)
    rows = await ReporterReader(container.uow_factory, container.clock, _zones(container)).services(
        actor
    )
    return _json(200, {"services": [_row(row) for row in rows]})


@router.get("/services/{service_id}/prompt")
async def prompt(service_id: str, request: Request, actor: _Reporter) -> Response:
    container = await _reporter(request, actor)
    view = await ReporterReader(container.uow_factory, container.clock, _zones(container)).prompt(
        actor, service_id
    )
    return _json(
        200,
        {
            "service": view.service,
            "unitLabel": view.unit_label,
            "recordedValue": view.recorded_value,
            "asOf": _stamp(view.as_of),
            "low": view.low,
            "high": view.high,
            "replyBy": _stamp(view.reply_by),
            "nextDue": _stamp(view.next_due),
        },
    )


@router.get("/services/{service_id}/history")
async def history(
    service_id: str, request: Request, actor: _Reporter, day: Literal["today"] = "today"
) -> Response:
    container = await _reporter(request, actor)
    items = await ReporterReader(container.uow_factory, container.clock, _zones(container)).history(
        actor, service_id
    )
    return _json(
        200,
        {"items": [{"at": _stamp(i.at), "value": i.value, "kind": i.kind} for i in items]},
    )


@router.get("/settings")
async def settings(request: Request, actor: _Reporter) -> Response:
    container = await _reporter(request, actor)
    view = await ReporterReader(container.uow_factory, container.clock, _zones(container)).settings(
        actor
    )
    return _json(
        200,
        {
            "channel": view.channel,
            "maskedPhone": view.masked_phone,
            "maskedCover": view.masked_cover,
            "reverifyInDays": view.reverify_in_days,
            "otherDevices": view.other_devices,
        },
    )


@router.get("/setup-summary")
async def setup_summary(request: Request, actor: _Reporter) -> Response:
    container = await _reporter(request, actor)
    view = await ReporterReader(
        container.uow_factory, container.clock, _zones(container)
    ).setup_summary(actor)
    return _json(
        200,
        {
            "service": view.service,
            "contactBy": view.contact_by,
            "maskedPhone": view.masked_phone,
            "nextUpdateDue": _stamp(view.next_update_due),
            "textCodeInDays": view.text_code_in_days,
        },
    )


# ------------------------------------------------------------------------------- reports


@router.post("/services/{service_id}/report")
async def report(service_id: str, body: ReportBody, request: Request, actor: _Reporter) -> Response:
    key = idempotency_key(request)
    container = await _reporter(request, actor)

    async def run() -> Response:
        outcome = await _reporting(container).report(
            ReporterReportCommand(
                idempotency_key=key,
                actor=actor,
                service_id=service_id,
                kind=body.kind,
                value=body.value,
                confirm_out_of_range=body.confirmOutOfRange,
            )
        )
        return _report_answer(outcome)

    return await _answer(lambda: replay_or_run(request, actor, key, run))


@router.post("/reports/batch")
async def batch(body: BatchBody, request: Request, actor: _Reporter) -> Response:
    key = idempotency_key(request)
    container = await _reporter(request, actor)

    async def run() -> Response:
        items = await _reporting(container).batch(actor, key, [i.serviceId for i in body.items])
        results: list[dict[str, Any]] = []
        for item in items:
            entry: dict[str, Any] = {"serviceId": item.service_id, "result": item.result}
            if item.at is not None:
                entry["at"] = _stamp(item.at)
            if item.reason is not None and item.result == "sendNumber":
                entry["reason"] = item.reason
            results.append(entry)
        return _json(200, {"results": results})

    return await _answer(lambda: replay_or_run(request, actor, key, run))


# ------------------------------------------------------------------------------- settings writes


async def _cover(
    request: Request, actor: Actor, body: CoverBody, service_id: str | None
) -> Response:
    container = await _reporter(request, actor)
    result = await _writer(container).set_cover(
        CoverCommand(
            actor=actor, phone=body.phone, until=body.until, day=body.date, service_id=service_id
        )
    )
    return _json(200, {"coveredUntil": _stamp(result.covered_until), "services": result.services})


@router.post("/cover")
async def cover_all(body: CoverBody, request: Request, actor: _Reporter) -> Response:
    return await _cover(request, actor, body, None)


@router.post("/services/{service_id}/cover")
async def cover_one(
    service_id: str, body: CoverBody, request: Request, actor: _Reporter
) -> Response:
    return await _cover(request, actor, body, service_id)


@router.post("/channel")
async def channel(body: ChannelBody, request: Request, actor: _Reporter) -> Response:
    chosen = channel_for(body.channel)
    container = await _reporter(request, actor)
    await _writer(container).set_channel(actor, chosen)
    return _json(200, {"channel": channel_word(chosen)})


@router.post("/services/{service_id}/accept")
async def accept(service_id: str, body: AcceptBody, request: Request, actor: _Reporter) -> Response:
    container = await _reporter(request, actor)
    answer = await _writer(container).accept(actor, service_id, body.accept)
    return _json(200, {"accepted": answer})


# ------------------------------------------------------------------------------- push test


@router.post("/push-test")
async def push_test(body: PushTestBody, request: Request, actor: _Notified) -> Response:
    container = await _reporter(request, actor)

    async def run() -> Response:
        allowed = await container.rate_limiter.allow(
            limiter_key("push-test", actor.practitioner_id or ""),
            PUSH_TESTS_PER_WINDOW,
            RATE_WINDOW,
        )
        if not allowed:
            return operation_outcome(
                429,
                "throttled",
                RATE_LIMITED_TEXT,
                headers={
                    "Cache-Control": "no-store",
                    "Retry-After": str(int(RATE_WINDOW.total_seconds())),
                },
            )
        try:
            await SendPushTest(
                container.uow_factory, container.clock, container.ids, container.sealer
            ).execute(actor)
        except NoPushSubscription:
            return _json(409, {"code": "no-subscription"})
        return _json(200, {"queued": True})

    return await _answer(run)


# ------------------------------------------------------------------------------- bookings


@router.get("/bookings/{reference}")
async def booking(reference: str, request: Request, actor: _Reporter) -> Response:
    container = await _reporter(request, actor)
    view = await ReporterBookingReader(container.uow_factory, container.clock).view(
        actor, reference
    )
    body: dict[str, Any] = {
        "reference": view.reference,
        "taskId": view.task_id,
        "service": view.service,
        "ageBand": view.age_band,
        "need": view.need,
        "urgency": view.urgency,
        "replyBy": _stamp(view.reply_by),
        "status": view.status,
        "bookingStatus": view.booking_status,
        "multiService": view.multi_service,
        "spoaPhone": view.spoa_phone,
    }
    if view.confirmed_at is not None:
        body["confirmedAt"] = _stamp(view.confirmed_at)
    return _json(200, body)


def _decline_reason(reason: str | None, decision: str) -> DeclineReason | None:
    if reason is None:
        return None
    if decision != "decline":
        raise ValidationFailed("reason", "only a decline has a reason")
    try:
        return DeclineReason(reason)
    except ValueError:
        raise ValidationFailed("reason", "is not a known reason") from None


@router.post("/bookings/{reference}/respond")
async def respond(
    reference: str, body: RespondBody, request: Request, actor: _Reporter
) -> Response:
    key = idempotency_key(request)
    reason = _decline_reason(body.reason, body.decision)
    container = await _reporter(request, actor)

    async def run() -> Response:
        answer = await ReporterBookingResponder(
            container.uow_factory,
            container.clock,
            RespondToBooking(
                container.uow_factory,
                UnitOfWorkIdempotency(container.uow_factory),
                container.clock,
                container.ids,
                container.sealer,
            ),
        ).execute(actor, reference, key, body.decision, reason)
        out: dict[str, Any] = {"status": answer.status}
        if answer.confirmed_at is not None:
            out["confirmedAt"] = _stamp(answer.confirmed_at)
        return _json(200, out)

    return await _answer(lambda: replay_or_run(request, actor, key, run))
