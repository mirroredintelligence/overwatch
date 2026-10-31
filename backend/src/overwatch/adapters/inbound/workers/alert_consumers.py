"""The consumers of the two alert subscriptions (B1 task 5, N2).

`alert-evaluator` on `capacity.events` (read through sessions, one for each service) takes a
`StatusChanged` and has `AlertEvaluator` raise the alerts D24 finds for it and schedule the
not-updated checks. Until now nothing read it, so no status change ever raised an alert.
`notifier` on `alerts.events` takes the three escalations that are for the shift lead and has
`NotifyShiftLeads` tell the leads. Every other event on either topic is completed and does nothing.

The shape is the board consumer's (DEC-165): a consumer (`handle(message)`) run inside a
`TenantBoundConsumer`, which checks the message's tenant against the directory and binds it before
the use case opens a unit of work. The use cases mark the message in their own unit, so a redelivery
is a duplicate. A payload that cannot be read and a service that is not there can never succeed and
are dead-lettered; anything else is retried. Only the class name of a failure is logged, because
its text can carry data.
"""

import logging
from typing import Final, Protocol

from azure.servicebus.aio import ServiceBusClient

from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import ActiveTenants
from diucs.adapters.inbound.workers.servicebus_runner import ServiceBusRunner
from diucs.adapters.inbound.workers.tenant_binding import Observe, TenantBoundConsumer, untraced
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.use_cases.alerts import EvaluationResult, StatusChangedCommand
from diucs.application.use_cases.notify_escalations import NotifyLeadsCommand, NotifyLeadsResult
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.events import StatusChanged

logger = logging.getLogger(__name__)

ALERT_EVALUATOR_SUBSCRIPTION: Final = "alert-evaluator"
NOTIFIER_SUBSCRIPTION: Final = "notifier"
CAPACITY_TOPIC: Final = "capacity.events"
ALERTS_TOPIC: Final = "alerts.events"
UNREADABLE: Final = "the event cannot be read"
NOT_FOUND: Final = "the event names a record that is not there"


class StatusEvaluator(Protocol):
    async def execute(self, command: StatusChangedCommand) -> EvaluationResult: ...


class EscalationNotifier(Protocol):
    async def execute(self, command: NotifyLeadsCommand) -> NotifyLeadsResult: ...


def _failed(message: BusMessage, error: Exception) -> Outcome:
    if isinstance(error, ValidationFailed):
        return Outcome("dead-letter", UNREADABLE)
    if isinstance(error, NotFound):
        return Outcome("dead-letter", NOT_FOUND)
    logger.warning("message %s will retry: %s", message.id, type(error).__name__)
    return Outcome("retry", type(error).__name__)


class AlertEvaluationConsumer:
    """Run inside a `TenantBoundConsumer` (`alert_runners`), which binds the tenant first."""

    def __init__(self, evaluator: StatusEvaluator) -> None:
        self._evaluator = evaluator

    async def handle(self, message: BusMessage) -> Outcome:
        if message.event_type != StatusChanged.event_type:
            return Outcome("completed")
        try:
            event = StatusChanged.decode(message.payload)
            result = await self._evaluator.execute(
                StatusChangedCommand(
                    message_id=message.id,
                    service_id=event.service_id,
                    before=event.before,
                    after=event.after,
                    at=event.at,
                )
            )
        except Exception as error:
            return _failed(message, error)
        return Outcome("duplicate" if result.duplicate else "completed")


class EscalationNotifyConsumer:
    """Run inside a `TenantBoundConsumer` (`alert_runners`), which binds the tenant first."""

    def __init__(self, notifier: EscalationNotifier) -> None:
        self._notifier = notifier

    async def handle(self, message: BusMessage) -> Outcome:
        try:
            result = await self._notifier.execute(
                NotifyLeadsCommand(
                    message_id=message.id, event_type=message.event_type, payload=message.payload
                )
            )
        except Exception as error:
            return _failed(message, error)
        return Outcome("duplicate" if result.duplicate else "completed")


def alert_runners(
    client: ServiceBusClient,
    evaluator: StatusEvaluator,
    notifier: EscalationNotifier,
    tenants: ActiveTenants,
    observe: Observe = untraced,
) -> list[ServiceBusRunner]:
    """The two runners: the evaluator's subscription of `capacity.events` (sessions, as the topic
    requires) and the notifier's of `alerts.events`. Each binds the message's tenant."""
    return [
        ServiceBusRunner(
            client,
            CAPACITY_TOPIC,
            ALERT_EVALUATOR_SUBSCRIPTION,
            TenantBoundConsumer(AlertEvaluationConsumer(evaluator), tenants, observe),
            sessions=True,
        ),
        ServiceBusRunner(
            client,
            ALERTS_TOPIC,
            NOTIFIER_SUBSCRIPTION,
            TenantBoundConsumer(EscalationNotifyConsumer(notifier), tenants, observe),
        ),
    ]
