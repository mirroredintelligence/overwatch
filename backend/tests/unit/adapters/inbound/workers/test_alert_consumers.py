"""The consumers of the alert subscriptions (B1 task 5, N2): `alert-evaluator` on `capacity.events`
(StatusChanged raises the alerts D24 finds and schedules the not-updated checks) and `notifier` on
`alerts.events` (the escalations that are for the shift lead). Both bind the message's tenant
first. No Docker and no Service Bus: the use cases are recorders and the runners never start."""

from typing import Any

import pytest

from diucs.adapters.inbound.workers.alert_consumers import (
    ALERT_EVALUATOR_SUBSCRIPTION,
    NOTIFIER_SUBSCRIPTION,
    AlertEvaluationConsumer,
    EscalationNotifyConsumer,
    alert_runners,
)
from diucs.adapters.inbound.workers.consumer import Outcome
from diucs.adapters.inbound.workers.outbox_relay import StaticTenants
from diucs.adapters.inbound.workers.tenant_binding import TenantBoundConsumer
from diucs.application.ports.outbound.event_bus import BusMessage
from diucs.application.tenancy import current_scope_or_none
from diucs.application.use_cases.alerts import EvaluationResult, StatusChangedCommand
from diucs.application.use_cases.notify_escalations import NotifyLeadsCommand, NotifyLeadsResult
from diucs.domain.codes import Status
from diucs.domain.errors import NotFound, ValidationFailed


class _Evaluator:
    def __init__(self, result: EvaluationResult | Exception | None = None) -> None:
        self.commands: list[StatusChangedCommand] = []
        self.scopes: list[str | None] = []
        self._result = EvaluationResult(1, 0) if result is None else result

    async def execute(self, command: StatusChangedCommand) -> EvaluationResult:
        self.commands.append(command)
        scope = current_scope_or_none()
        self.scopes.append(None if scope is None else scope.value)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _Notifier:
    def __init__(self, result: NotifyLeadsResult | Exception | None = None) -> None:
        self.commands: list[NotifyLeadsCommand] = []
        self._result = NotifyLeadsResult(2) if result is None else result

    async def execute(self, command: NotifyLeadsCommand) -> NotifyLeadsResult:
        self.commands.append(command)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _status(
    tenant: str = "tenant-a",
    payload: dict[str, Any] | None = None,
    event_type: str = "StatusChanged",
) -> BusMessage:
    return BusMessage(
        id="m-1",
        topic="capacity.events",
        event_type=event_type,
        payload=payload
        or {
            "service_id": "svc-1",
            "before": "accepting",
            "after": "not-updated",
            "at": "2026-10-31T09:00:00Z",
        },
        session_id="svc-1",
        tenant_id=tenant,
    )


def _escalation(event_type: str = "ReportEscalated", tenant: str = "tenant-a") -> BusMessage:
    return BusMessage(
        id="m-2",
        topic="alerts.events",
        event_type=event_type,
        payload={"service_id": "svc-1"},
        tenant_id=tenant,
    )


def test_the_subscriptions_are_the_ones_of_the_topology() -> None:
    assert ALERT_EVALUATOR_SUBSCRIPTION == "alert-evaluator"
    assert NOTIFIER_SUBSCRIPTION == "notifier"


async def test_a_status_change_is_evaluated_in_the_scope_of_the_messages_tenant() -> None:
    evaluator = _Evaluator()
    consumer = AlertEvaluationConsumer(evaluator)  # type: ignore[arg-type]
    wrapped = TenantBoundConsumer(consumer, StaticTenants(["tenant-a", "tenant-b"]))  # type: ignore[arg-type]

    outcome = await wrapped.handle(_status("tenant-b"))

    assert outcome == Outcome("completed")
    [command] = evaluator.commands
    assert (command.message_id, command.service_id) == ("m-1", "svc-1")
    assert (command.before, command.after) == (Status.ACCEPTING, Status.NOT_UPDATED)
    assert evaluator.scopes == ["tenant-b"]


async def test_a_first_status_with_no_before_is_evaluated() -> None:
    evaluator = _Evaluator()
    payload = {
        "service_id": "svc-1",
        "before": None,
        "after": "accepting",
        "at": "2026-10-31T09:00:00Z",
    }

    outcome = await AlertEvaluationConsumer(evaluator).handle(_status(payload=payload))  # type: ignore[arg-type]

    assert outcome == Outcome("completed")
    assert evaluator.commands[0].before is None


async def test_another_event_on_the_capacity_topic_is_completed_and_not_evaluated() -> None:
    evaluator = _Evaluator()

    outcome = await AlertEvaluationConsumer(evaluator).handle(  # type: ignore[arg-type]
        _status(event_type="CapacityReported")
    )

    assert outcome == Outcome("completed")
    assert evaluator.commands == []


async def test_a_duplicate_is_settled_as_a_duplicate() -> None:
    evaluator = _Evaluator(EvaluationResult(0, 0, duplicate=True))

    outcome = await AlertEvaluationConsumer(evaluator).handle(_status())  # type: ignore[arg-type]

    assert outcome == Outcome("duplicate")


async def test_a_payload_that_cannot_be_read_is_dead_lettered_without_its_text() -> None:
    evaluator = _Evaluator()

    outcome = await AlertEvaluationConsumer(evaluator).handle(  # type: ignore[arg-type]
        _status(payload={"service_id": "svc-1", "after": "nonsense", "before": None, "at": "x"})
    )

    assert outcome.kind == "dead-letter"
    assert "nonsense" not in (outcome.reason or "")
    assert evaluator.commands == []


async def test_a_service_that_is_not_there_is_dead_lettered() -> None:
    evaluator = _Evaluator(NotFound("no service with this id"))

    outcome = await AlertEvaluationConsumer(evaluator).handle(_status())  # type: ignore[arg-type]

    assert outcome.kind == "dead-letter"


async def test_any_other_failure_is_retried_by_class_name_only() -> None:
    evaluator = _Evaluator(RuntimeError("database says svc-1 and a name"))

    outcome = await AlertEvaluationConsumer(evaluator).handle(_status())  # type: ignore[arg-type]

    assert outcome == Outcome("retry", "RuntimeError")


async def test_an_escalation_is_handed_to_the_notifier_in_the_messages_tenant() -> None:
    notifier = _Notifier()
    wrapped = TenantBoundConsumer(
        EscalationNotifyConsumer(notifier),  # type: ignore[arg-type]
        StaticTenants(["tenant-a"]),  # type: ignore[arg-type]
    )

    outcome = await wrapped.handle(_escalation("WithdrawalEscalated"))

    assert outcome == Outcome("completed")
    [command] = notifier.commands
    assert (command.message_id, command.event_type) == ("m-2", "WithdrawalEscalated")


async def test_a_tenant_the_directory_does_not_list_is_dead_lettered_and_nobody_is_told() -> None:
    notifier = _Notifier()
    wrapped = TenantBoundConsumer(
        EscalationNotifyConsumer(notifier),  # type: ignore[arg-type]
        StaticTenants(["tenant-a"]),  # type: ignore[arg-type]
    )

    outcome = await wrapped.handle(_escalation(tenant="tenant-z"))

    assert outcome.kind == "dead-letter"
    assert notifier.commands == []


async def test_an_ignored_event_is_completed_and_a_duplicate_is_a_duplicate() -> None:
    ignored = await EscalationNotifyConsumer(_Notifier(NotifyLeadsResult(0, ignored=True))).handle(  # type: ignore[arg-type]
        _escalation("AlertRaised")
    )
    duplicate = await EscalationNotifyConsumer(
        _Notifier(NotifyLeadsResult(0, duplicate=True))
    ).handle(  # type: ignore[arg-type]
        _escalation()
    )

    assert ignored == Outcome("completed")
    assert duplicate == Outcome("duplicate")


@pytest.mark.parametrize("error", [NotFound("x"), ValidationFailed("f", "bad")])
async def test_a_refused_escalation_is_dead_lettered(error: Exception) -> None:
    outcome = await EscalationNotifyConsumer(_Notifier(error)).handle(_escalation())  # type: ignore[arg-type]

    assert outcome.kind == "dead-letter"


async def test_a_failure_of_the_notifier_is_retried() -> None:
    outcome = await EscalationNotifyConsumer(_Notifier(OSError("down"))).handle(_escalation())  # type: ignore[arg-type]

    assert outcome == Outcome("retry", "OSError")


def test_the_runners_read_the_two_subscriptions_and_each_binds_the_tenant() -> None:
    runners = alert_runners(
        None,  # type: ignore[arg-type]
        _Evaluator(),  # type: ignore[arg-type]
        _Notifier(),  # type: ignore[arg-type]
        StaticTenants(["tenant-a"]),  # type: ignore[arg-type]
    )

    assert [(r._entity, r._subscription, r._sessions) for r in runners] == [
        ("capacity.events", "alert-evaluator", True),
        ("alerts.events", "notifier", False),
    ]
    assert all(isinstance(r._consumer, TenantBoundConsumer) for r in runners)
