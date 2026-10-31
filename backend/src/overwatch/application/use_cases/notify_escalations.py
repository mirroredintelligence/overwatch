"""NotifyShiftLeads: tell the shift leads of an escalation that is "for the shift lead" (B1 task 5,
N2, U06, U21, U34).

Three events end a chain of reminders with the shift lead and publish to `alerts.events`: a prompt
that went unanswered for an hour and a half (`ReportEscalated`), a booking withdrawal nobody
acknowledged (`WithdrawalEscalated`) and an alert nobody acknowledged, deputy included
(`AlertEscalatedToLead`). Nothing read them, so the lead was never told. The `notifier` subscription
reads them and this use case queues one K3 push for each active shift lead of the bound tenant, the
way the safety concern notifies the officer (a sealed push through the outbox, the Communication
about the service). The push names the service and what to do, and nothing else: no booking, alert
or person identifier, no patient data.

Once for each message: the message is marked in the same unit that writes the pushes, so a
redelivery does nothing. A tenant with no active shift lead is audited with a count of none (and the
worker logs it): the escalation has nowhere to go and that is on record. Every other event that
reaches the subscription is ignored without opening a unit.

Wording is [ASSUMED] (information governance has not approved push wording, DEC-1100 Q2).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from diucs.application.actor import timer_actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.sealing import ContentSealer
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.sealed_send import queue_message
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.domain.codes import Channel, PractitionerRoleCode
from diucs.domain.errors import NotFound
from diucs.domain.events import AlertEscalatedToLead, ReportEscalated, WithdrawalEscalated
from diucs.domain.messages.catalogue import MessageId
from diucs.domain.messages.templates import render

log = logging.getLogger(__name__)

CONSUMER: Final = "notifier"
AUDIT_ACTION: Final = "U"
USE_CASE: Final = "NotifyShiftLeads"
NO_SERVICE: Final = "no service with this id"
ESCALATION_EVENTS: Final = frozenset(
    {ReportEscalated.event_type, WithdrawalEscalated.event_type, AlertEscalatedToLead.event_type}
)
_LEADS: Final = frozenset({PractitionerRoleCode.SHIFT_LEAD})
UNNAMED_SERVICE: Final = "A service"


@dataclass(frozen=True, slots=True)
class NotifyLeadsCommand:
    """An event of `alerts.events`, with the id the bus gave it (the marker of once)."""

    message_id: str
    event_type: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class NotifyLeadsResult:
    notified: int
    duplicate: bool = False
    ignored: bool = False


def _service_of(command: NotifyLeadsCommand) -> str | None:
    """The service the escalation is about, decoded by the event's own reader (a payload that
    cannot be read is `ValidationFailed`)."""
    if command.event_type == ReportEscalated.event_type:
        return ReportEscalated.decode(command.payload).service_id
    if command.event_type == WithdrawalEscalated.event_type:
        return WithdrawalEscalated.decode(command.payload).service_id
    return AlertEscalatedToLead.decode(command.payload).service_id


def _words(event_type: str, service: str) -> tuple[str, str]:
    if event_type == ReportEscalated.event_type:
        return (
            f"{service} has not reported",
            "No figure has come in after the last prompt. Please phone the service.",
        )
    if event_type == WithdrawalEscalated.event_type:
        return (
            f"Withdrawn booking for {service}",
            "A withdrawn booking has not been acknowledged by the advisor. Please check with them.",
        )
    return (
        f"{service} alert not acknowledged",
        "No one has acknowledged the alert. Please follow it up.",
    )


class NotifyShiftLeads:
    def __init__(
        self, uow_factory: UnitOfWorkFactory, ids: IdGenerator, clock: Clock, sealer: ContentSealer
    ) -> None:
        self._uow_factory = uow_factory
        self._ids = ids
        self._clock = clock
        self._sealer = sealer

    async def execute(self, command: NotifyLeadsCommand) -> NotifyLeadsResult:
        if command.event_type not in ESCALATION_EVENTS:
            return NotifyLeadsResult(0, ignored=True)
        service_id = _service_of(command)
        async with self._uow_factory() as uow:
            scope = uow.unit_scope
            if scope is None or scope.kind is not ScopeKind.TENANT:
                raise TenantNotBound
            if not await uow.processed.mark_if_new(command.message_id, CONSUMER):
                return NotifyLeadsResult(0, duplicate=True)
            service_name = UNNAMED_SERVICE
            if service_id is not None:
                profile = await uow.services.get(service_id)
                if profile is None:
                    raise NotFound(NO_SERVICE)
                service_name = profile.name
            now = self._clock.now()
            title, body = _words(command.event_type, service_name)
            notice = render(MessageId.K3, Channel.PUSH, title=title, body=body)
            leads = {
                role.id: role for role in await uow.people.active_roles_with_codes(_LEADS, now)
            }
            for role_id in sorted(leads):
                await queue_message(
                    uow,
                    self._ids,
                    self._sealer,
                    scope=scope,
                    rendered=notice,
                    recipient_role_id=role_id,
                    about_id=service_id,
                    now=now,
                )
            if not leads:
                log.warning("no active shift lead to tell of an escalation: %s", command.event_type)
            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_ACTION,
                    use_case=USE_CASE,
                    actor=timer_actor(scope.value),
                    entity_ids=() if service_id is None else (service_id,),
                    snapshot={"event": command.event_type, "notified": len(leads)},
                    at=now,
                )
            )
            await uow.commit()
        return NotifyLeadsResult(len(leads))
