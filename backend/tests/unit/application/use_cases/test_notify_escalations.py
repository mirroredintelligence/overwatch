"""NotifyShiftLeads: the notifier of `alerts.events` (B1 task 5, N2). A report that nobody sent, a
withdrawal that nobody acknowledged and an alert that nobody acknowledged each end with an event
"for the shift lead" (U06, U21, U34), and nothing read it: the lead was never told. The notifier
queues one push for each active shift lead of the bound tenant, once for each message, with the
service's name and no patient data.

The use case runs on a small recording unit of work (DEC-004: the stored effects on a real Neo4j
are in tests/integration/application/test_notify_escalations.py). Sample values only.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Self

import pytest

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.tenancy import ScopeId, bind_scope
from diucs.application.use_cases.notify_escalations import (
    ESCALATION_EVENTS,
    NotifyLeadsCommand,
    NotifyShiftLeads,
)
from diucs.domain.codes import Channel, PractitionerRoleCode
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.messages.privacy_guard import find_patient_data
from diucs.domain.model.people import PractitionerRole

NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
TENANT = "tenant-notify-a"
SERVICE_ID = "ucr-west"
SECRETS = FixedSecretStore({LINK_TOKEN_SECRET: b"link-token-test-secret-0123456789abcdef"})
SEALER = AesGcmContentSealer(SECRETS)
AT = "2026-10-31T09:00:00Z"
PAYLOADS: dict[str, dict[str, Any]] = {
    "ReportEscalated": {"service_id": SERVICE_ID, "due_at": "2026-10-31T07:30:00Z", "at": AT},
    "WithdrawalEscalated": {"booking_id": "bk-1", "service_id": SERVICE_ID, "at": AT},
    "AlertEscalatedToLead": {"alert_id": "al-1", "service_id": SERVICE_ID, "at": AT},
}


def _lead(number: int) -> PractitionerRole:
    return PractitionerRole(
        id=f"role-lead-{number}",
        practitioner_id=f"prac-lead-{number}",
        service_id=None,
        code=PractitionerRoleCode.SHIFT_LEAD,
        active=True,
        channel=Channel.PUSH,
        period_start=NOW.replace(day=1),
    )


class _Collect:
    def __init__(self) -> None:
        self.items: list[Any] = []

    async def add(self, item: Any) -> None:
        self.items.append(item)

    async def append(self, item: Any) -> None:
        self.items.append(item)


@dataclass
class _Unit:
    leads: list[PractitionerRole]
    seen: bool = False
    service: bool = True
    committed: bool = False
    asked_codes: list[frozenset[PractitionerRoleCode]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.communications = _Collect()
        self.outbox = _Collect()
        self.audit = _Collect()
        self.processed = SimpleNamespace(mark_if_new=self._mark)
        self.services = SimpleNamespace(get=self._service)
        self.people = SimpleNamespace(active_roles_with_codes=self._roles)

    async def _mark(self, message_id: str, consumer: str) -> bool:
        return not self.seen

    async def _service(self, service_id: str) -> Any:
        if not self.service:
            return None
        return SimpleNamespace(id=service_id, name="UCR West")

    async def _roles(self, codes: frozenset[PractitionerRoleCode], now: datetime) -> list[Any]:
        self.asked_codes.append(codes)
        return list(self.leads)

    @property
    def unit_scope(self) -> ScopeId:
        return ScopeId.tenant(TENANT)

    async def commit(self) -> None:
        self.committed = True

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _use_case(unit: _Unit) -> NotifyShiftLeads:
    return NotifyShiftLeads(
        lambda: unit,  # type: ignore[arg-type, return-value]
        SequentialIds("n"),
        FixedClock(NOW),
        SEALER,
    )


async def _run(unit: _Unit, event_type: str = "ReportEscalated", message_id: str = "m-1") -> Any:
    command = NotifyLeadsCommand(
        message_id=message_id, event_type=event_type, payload=PAYLOADS.get(event_type, {})
    )
    with bind_scope(ScopeId.tenant(TENANT)):
        return await _use_case(unit).execute(command)


def _opened(unit: _Unit, index: int = 0) -> dict[str, Any]:
    message = [m for m in unit.outbox.items if m.event_type == "SendMessage"][index]
    text = SEALER.unseal(
        message.payload["sealed_content"],
        message_id=message.id,
        tenant_id=TENANT,
        recipient_role_id=message.payload["recipient_role_id"],
    )
    content: dict[str, Any] = json.loads(text)
    return content


def test_the_escalation_events_are_the_three_that_are_for_the_shift_lead() -> None:
    assert ESCALATION_EVENTS == {"ReportEscalated", "WithdrawalEscalated", "AlertEscalatedToLead"}


@pytest.mark.parametrize("event_type", sorted(PAYLOADS))
async def test_each_active_shift_lead_gets_one_push_about_the_service(event_type: str) -> None:
    unit = _Unit([_lead(1), _lead(2)])

    result = await _run(unit, event_type)

    assert result.notified == 2
    sent = [m for m in unit.outbox.items if m.event_type == "SendMessage"]
    assert [m.payload["recipient_role_id"] for m in sent] == ["role-lead-1", "role-lead-2"]
    assert all(m.payload["channel"] == "push" and m.payload["message_id"] == "K3" for m in sent)
    assert "UCR West" in _opened(unit)["subject"]
    assert unit.committed


async def test_only_the_shift_lead_post_is_asked_for() -> None:
    unit = _Unit([_lead(1)])

    await _run(unit)

    assert unit.asked_codes == [frozenset({PractitionerRoleCode.SHIFT_LEAD})]


@pytest.mark.parametrize("event_type", sorted(PAYLOADS))
async def test_the_push_names_the_service_and_holds_no_patient_data_or_identifier(
    event_type: str,
) -> None:
    unit = _Unit([_lead(1)])

    await _run(unit, event_type)

    content = _opened(unit)
    shown = json.dumps(content)
    assert find_patient_data(content["subject"]) is None
    assert find_patient_data(content["text"]) is None
    for identifier in ("bk-1", "al-1", "prac-lead-1", TENANT):
        assert identifier not in shown


async def test_the_communication_is_about_the_service_and_holds_no_secret_content() -> None:
    unit = _Unit([_lead(1)])

    await _run(unit)

    [communication] = unit.communications.items
    assert communication.about_id == SERVICE_ID
    assert communication.recipient_role_id == "role-lead-1"
    sent = [m for m in unit.outbox.items if m.event_type == "SendMessage"][0]
    assert set(sent.payload) == {
        "communication_id",
        "message_id",
        "channel",
        "recipient_role_id",
        "sealed_content",
    }


async def test_a_message_that_was_handled_before_does_nothing_the_second_time() -> None:
    unit = _Unit([_lead(1)], seen=True)

    result = await _run(unit)

    assert result.duplicate is True
    assert result.notified == 0
    assert unit.outbox.items == []
    assert not unit.committed


async def test_a_tenant_with_no_shift_lead_is_audited_and_nobody_is_told() -> None:
    unit = _Unit([])

    result = await _run(unit)

    assert result.notified == 0
    assert unit.outbox.items == []
    [entry] = unit.audit.items
    assert entry.use_case == "NotifyShiftLeads"
    assert entry.snapshot == {"event": "ReportEscalated", "notified": 0}
    assert unit.committed


async def test_the_audit_entry_names_the_event_the_service_and_the_count_only() -> None:
    unit = _Unit([_lead(1), _lead(2)])

    await _run(unit, "WithdrawalEscalated")

    [entry] = unit.audit.items
    assert entry.entity_ids == (SERVICE_ID,)
    assert entry.snapshot == {"event": "WithdrawalEscalated", "notified": 2}
    assert entry.actor.tenant_id == TENANT


async def test_an_event_that_is_not_for_the_lead_is_ignored_without_opening_a_unit() -> None:
    unit = _Unit([_lead(1)])

    result = await _run(unit, "AlertRaised")

    assert result.ignored is True
    assert unit.outbox.items == []
    assert not unit.committed


async def test_a_service_that_is_not_there_is_not_found_and_nothing_is_committed() -> None:
    unit = _Unit([_lead(1)], service=False)

    with pytest.raises(NotFound):
        await _run(unit)

    assert not unit.committed
    assert unit.outbox.items == []


async def test_a_payload_that_cannot_be_read_is_refused() -> None:
    unit = _Unit([_lead(1)])
    command = NotifyLeadsCommand(message_id="m-1", event_type="ReportEscalated", payload={})

    with bind_scope(ScopeId.tenant(TENANT)), pytest.raises(ValidationFailed):
        await _use_case(unit).execute(command)

    assert not unit.committed


async def test_an_alert_with_no_service_names_no_service_and_still_tells_the_lead() -> None:
    unit = _Unit([_lead(1)])
    payload = {"alert_id": "al-1", "service_id": None, "at": AT}
    command = NotifyLeadsCommand(
        message_id="m-2", event_type="AlertEscalatedToLead", payload=payload
    )

    with bind_scope(ScopeId.tenant(TENANT)):
        result = await _use_case(unit).execute(command)

    assert result.notified == 1
    assert "UCR West" not in json.dumps(_opened(unit))
