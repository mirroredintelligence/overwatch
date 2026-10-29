"""The support console's use cases (R18), over the consent model of O06 and the telemetry port of
O07.

A support person asks for a ticket on a session (RequestSupportTicket); a shift lead approves it
(ApproveSupportTicket). Support opens a session with a code (the person's own), or with an
approved ticket (OpenSupportSession). Support reads a session's events only while its own open
is live (ReadSessionEvents), and traces and session summaries with the support role (ReadTrace,
SearchSessions). EndSupportAccess ends the opens of a session at once.

Every change is one unit of work with its audit entry (the ticket request and approval, the end
of an access). Reads take no audit entry. The tenant is the unit of work's, as in O06; the
telemetry port binds its own tenant from the context (O07).
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.support_tickets import SupportTicketRecord
from diucs.application.ports.outbound.telemetry_query import (
    SessionFilters,
    SessionSummary,
    SpanRecord,
    TelemetryQuery,
    check_trace_id,
)
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.support_access import (
    OPEN_REFUSED,
    OpenSessionCommand,
    OpenSessionForSupport,
    OpenSessionResult,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from diucs.domain.rules.support import is_lead
from diucs.domain.rules.support_console import (
    EVENT_FILTERS,
    public_event,
    standout_events,
)

TICKET_REFUSED: Final = "This ticket cannot be requested for that session."
APPROVE_REFUSED: Final = "This ticket cannot be approved."
EVENTS_REFUSED: Final = "This session is not open to you."
ACTION_TICKET_REQUESTED: Final = "support-ticket-requested"
ACTION_TICKET_APPROVED: Final = "support-ticket-approved"
ACTION_ACCESS_ENDED: Final = "support-access-ended"
USE_CASE_TICKET: Final = "RequestSupportTicket"
USE_CASE_APPROVE: Final = "ApproveSupportTicket"
USE_CASE_END: Final = "EndSupportAccess"

# How far back a session's events and a trace are read: the raw-telemetry lookback of O07 [ASSUMED].
RAW_LOOKBACK: Final = timedelta(days=90)
_TICKET: Final = re.compile(r"[A-Za-z0-9-]{1,32}")
_SESSION: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass(frozen=True, slots=True)
class SessionEvents:
    events: list[dict[str, Any]]
    standout: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class TraceView:
    name: str
    total_ms: float
    spans: list[dict[str, Any]]


def _checked_session(value: str) -> str:
    if _SESSION.fullmatch(value) is None:
        raise ValidationFailed(
            "sessionId", "must be 1 to 64 letters, digits, hyphens or underscores"
        )
    return value


class RequestSupportTicket:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, session_id: str, ticket: str) -> SupportTicketRecord:
        """A support person asks for a session to be opened on a ticket. The ticket is pending
        until a
        shift lead approves it. A session that is not the tenant's, or a ticket already taken, is
        refused
        with the same message.
        """
        if actor.role is not Role.SUPPORT or actor.practitioner_id is None:
            raise NotAllowed(TICKET_REFUSED)
        _checked_session(session_id)
        if _TICKET.fullmatch(ticket) is None:
            raise ValidationFailed("ticket", "must be 1 to 32 letters, digits or hyphens")
        now = self._clock.now()
        record = SupportTicketRecord(
            id=ticket,
            session_id=session_id,
            requested_by=actor.practitioner_id,
            state="pending",
            approved_by=None,
            requested_at=now,
            approved_at=None,
        )
        async with self._uow_factory() as uow:
            if not await uow.support.session_exists(session_id):
                raise NotAllowed(TICKET_REFUSED)
            if not await uow.support_tickets.add(record):
                raise NotAllowed(TICKET_REFUSED)
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_TICKET_REQUESTED,
                    use_case=USE_CASE_TICKET,
                    actor=actor,
                    entity_ids=(ticket, session_id),
                    snapshot=None,
                    at=now,
                )
            )
            await uow.commit()
        return record


class ApproveSupportTicket:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, ticket: str) -> None:
        """A shift lead approves a pending ticket. Only an active practitioner who holds an active
        lead
        role may approve; any other answer is the same refusal.
        """
        if actor.role is not Role.LEAD or actor.practitioner_id is None:
            raise NotAllowed(APPROVE_REFUSED)
        if _TICKET.fullmatch(ticket) is None:
            raise NotAllowed(APPROVE_REFUSED)
        now = self._clock.now()
        async with self._uow_factory() as uow:
            approver = await uow.people.get_practitioner(actor.practitioner_id)
            roles = await uow.people.roles_for_practitioner(actor.practitioner_id)
            if approver is None or not is_lead(roles, approver.active):
                raise NotAllowed(APPROVE_REFUSED)
            if not await uow.support_tickets.approve(ticket, actor.practitioner_id, now):
                raise NotAllowed(APPROVE_REFUSED)
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_TICKET_APPROVED,
                    use_case=USE_CASE_APPROVE,
                    actor=actor,
                    entity_ids=(ticket,),
                    snapshot=None,
                    at=now,
                )
            )
            await uow.commit()


class OpenSupportSession:
    """Opens a session for support with a code, or with an approved ticket. The approval is read
    first, in
    a unit of work that is closed before OpenSessionForSupport opens its own (no nested units).
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        secrets: SecretStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._open = OpenSessionForSupport(uow_factory, clock, ids, secrets)

    async def execute(
        self, actor: Actor, *, code: str | None = None, ticket: str | None = None
    ) -> OpenSessionResult:
        if (code is None) == (ticket is None):
            raise NotAllowed(OPEN_REFUSED)
        if code is not None:
            return await self._open.execute(OpenSessionCommand(actor=actor, code=code))
        if ticket is None or _TICKET.fullmatch(ticket) is None:
            raise NotAllowed(OPEN_REFUSED)
        async with self._uow_factory() as uow:
            record = await uow.support_tickets.get(ticket)
        if record is None or record.state != "approved" or record.approved_by is None:
            raise NotAllowed(OPEN_REFUSED)
        return await self._open.execute(
            OpenSessionCommand(
                actor=actor,
                session_id=record.session_id,
                ticket=record.id,
                approved_by=record.approved_by,
            )
        )


class ReadSessionEvents:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, clock: Clock, telemetry: TelemetryQuery
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._telemetry = telemetry

    async def execute(self, actor: Actor, session_id: str, event_filter: str) -> SessionEvents:
        """The events of one session, filtered, with the standout ones. Only while this support
        person's
        own open of the session is live; otherwise the same refusal, whatever the session.
        """
        if actor.role is not Role.SUPPORT or actor.practitioner_id is None:
            raise NotAllowed(EVENTS_REFUSED)
        _checked_session(session_id)
        if event_filter not in EVENT_FILTERS:
            raise ValidationFailed("filter", "must be all, errors, friction, api or navigation")
        now = self._clock.now()
        async with self._uow_factory() as uow:
            accesses = await uow.support.accesses_of(session_id)
        if not any(
            access.practitioner_id == actor.practitioner_id and access.expires_at > now
            for access in accesses
        ):
            raise NotAllowed(EVENTS_REFUSED)
        timeline = await self._telemetry.session_timeline(session_id, now - RAW_LOOKBACK, now)
        start = timeline[0].at if timeline else now
        every = [
            public_event(
                kind=item.kind.value,
                name=item.name,
                at=item.at,
                start=start,
                duration_ms=item.duration_ms,
                status=item.status,
                attributes=item.attributes,
            )
            for item in timeline
        ]
        kinds = EVENT_FILTERS[event_filter]
        chosen = [event for event, item in zip(every, timeline, strict=True) if item.kind in kinds]
        return SessionEvents(events=chosen, standout=standout_events(every))


class ReadTrace:
    def __init__(self, telemetry: TelemetryQuery) -> None:
        self._telemetry = telemetry

    async def execute(self, actor: Actor, trace_id: str) -> TraceView:
        """The spans of one trace, in start order, with the offset of each from the first. A trace
        with no
        spans is not found (the same answer as a trace the tenant does not hold).
        """
        if actor.role is not Role.SUPPORT:
            raise NotAllowed(EVENTS_REFUSED)
        check_trace_id(trace_id)
        spans: list[SpanRecord] = await self._telemetry.trace(trace_id)
        if not spans:
            raise NotFound
        origin = min(span.start for span in spans)
        end = max(span.start + timedelta(milliseconds=span.duration_ms) for span in spans)
        root = next((span for span in spans if span.parent_span_id is None), spans[0])
        return TraceView(
            name=root.name,
            total_ms=(end - origin).total_seconds() * 1000,
            spans=[
                {
                    "spanId": span.span_id,
                    "parentSpanId": span.parent_span_id,
                    "name": span.name,
                    "offsetMs": int((span.start - origin).total_seconds() * 1000),
                    "durationMs": span.duration_ms,
                    "status": span.status,
                }
                for span in spans
            ],
        )


class SearchSessions:
    def __init__(self, telemetry: TelemetryQuery) -> None:
        self._telemetry = telemetry

    async def execute(
        self, actor: Actor, filters: SessionFilters, session_id: str | None
    ) -> list[SessionSummary]:
        """Session summaries (aggregates only), most recent first; one session when a session id is
        given.
        """
        if actor.role is not Role.SUPPORT:
            raise NotAllowed(EVENTS_REFUSED)
        found = await self._telemetry.search_sessions(filters)
        if session_id is None:
            return found
        _checked_session(session_id)
        return [session for session in found if session.session_id == session_id]


class EndSupportAccess:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor, session_id: str) -> int:
        """End the live opens of a session at once. Refused when none is live."""
        if actor.role is not Role.SUPPORT or actor.practitioner_id is None:
            raise NotAllowed(EVENTS_REFUSED)
        _checked_session(session_id)
        now: datetime = self._clock.now()
        async with self._uow_factory() as uow:
            ended = await uow.support.end_accesses(session_id, now)
            if ended == 0:
                raise NotAllowed(EVENTS_REFUSED)
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_ACCESS_ENDED,
                    use_case=USE_CASE_END,
                    actor=actor,
                    entity_ids=(session_id,),
                    snapshot={"accesses_ended": ended},
                    at=now,
                )
            )
            await uow.commit()
        return ended
