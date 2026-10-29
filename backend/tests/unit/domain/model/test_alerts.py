"""Alert records (P17): the subscription and the alert, with their refusals (domain-rules 8)."""

from datetime import UTC, datetime, time, timedelta

import pytest

from diucs.domain.codes import AlertKind
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.alerts import AlertRecord, AlertSubscription
from diucs.domain.rules.alerts import AlertPreferences

RAISED = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)
DUE = datetime(2026, 10, 25, 13, 27, tzinfo=UTC)
PREFS = AlertPreferences(
    kinds=frozenset({AlertKind.OVER_CAPACITY, AlertKind.SERVICE_CLOSED}),
    not_updated_hours=2,
    quiet_hours=(time(22, 0), time(6, 0)),
    quiet_critical_only=True,
    ack_minutes=15,
)


def _alert(**changes: object) -> AlertRecord:
    fields: dict[str, object] = {
        "id": "alert-1",
        "kind": AlertKind.OVER_CAPACITY,
        "service_id": "svc-hospital-at-home",
        "owner_practitioner_id": "p-1",
        "status": "new",
        "raised_at": RAISED,
        "escalation_due_at": DUE,
        "part_of_id": None,
    }
    fields.update(changes)
    return AlertRecord(**fields)  # type: ignore[arg-type]


def _subscription(**changes: object) -> AlertSubscription:
    fields: dict[str, object] = {
        "practitioner_id": "p1",
        "preferences": PREFS,
        "deputy_id": "p-deputy",
        "daily_summary": False,
        "weekly_summary": True,
        "updated_at": RAISED,
    }
    fields.update(changes)
    return AlertSubscription(**fields)  # type: ignore[arg-type]


def test_a_subscription_keeps_its_preferences_and_deputy() -> None:
    subscription = _subscription()

    assert subscription.preferences == PREFS
    assert subscription.deputy_id == "p-deputy"
    assert subscription.weekly_summary is True


@pytest.mark.parametrize("practitioner_id", ["", "   "])
def test_a_subscription_needs_a_practitioner(practitioner_id: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _subscription(practitioner_id=practitioner_id)

    assert refused.value.field == "practitioner_id"


def test_a_subscription_refuses_a_naive_update_time() -> None:
    with pytest.raises(ValidationFailed) as refused:
        _subscription(updated_at=datetime(2026, 10, 25, 13, 12))

    assert refused.value.field == "updated_at"


def test_a_subscription_refuses_a_kind_that_is_only_text() -> None:
    # Lesson L3 and L38: a plain string with the same value is not an alert kind.
    with pytest.raises(ValidationFailed):
        _subscription(
            preferences=AlertPreferences(
                kinds=frozenset({"over-capacity"}),  # type: ignore[arg-type]
                not_updated_hours=2,
                quiet_hours=None,
                quiet_critical_only=True,
                ack_minutes=15,
            )
        )


def test_an_alert_for_a_service_names_the_service_and_its_owner() -> None:
    alert = _alert()

    assert alert.service_id == "svc-hospital-at-home"
    assert alert.owner_practitioner_id == "p-1"
    assert alert.acknowledged_at is None


def test_a_system_pressure_alert_names_no_service() -> None:
    alert = _alert(kind=AlertKind.SYSTEM_PRESSURE, service_id=None)
    assert alert.service_id is None

    with pytest.raises(ValidationFailed) as refused:
        _alert(kind=AlertKind.SYSTEM_PRESSURE, service_id="svc-hospital-at-home")
    assert refused.value.field == "service_id"


def test_a_service_alert_needs_its_service() -> None:
    with pytest.raises(ValidationFailed) as refused:
        _alert(kind=AlertKind.OVER_CAPACITY, service_id=None)

    assert refused.value.field == "service_id"


@pytest.mark.parametrize("status", ["new", "acknowledged", "escalated", "closed"])
def test_each_alert_status_is_accepted(status: str) -> None:
    assert _alert(status=status).status == status


@pytest.mark.parametrize("status", ["pending", "NEW", ""])
def test_an_unknown_alert_status_is_refused(status: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _alert(status=status)

    assert refused.value.field == "status"


def test_an_alert_refuses_a_naive_raise_time() -> None:
    with pytest.raises(ValidationFailed) as refused:
        _alert(raised_at=datetime(2026, 10, 25, 13, 12))

    assert refused.value.field == "raised_at"


def test_an_escalation_due_time_must_carry_an_offset() -> None:
    with pytest.raises(ValidationFailed) as refused:
        _alert(escalation_due_at=datetime(2026, 10, 25, 13, 27))

    assert refused.value.field == "escalation_due_at"


def test_an_alert_cannot_escalate_from_itself() -> None:
    with pytest.raises(ValidationFailed) as refused:
        _alert(id="alert-1", part_of_id="alert-1")

    assert refused.value.field == "part_of_id"


def test_an_escalation_points_at_an_earlier_alert() -> None:
    escalation = _alert(
        id="alert-2",
        status="escalated",
        owner_practitioner_id="p-deputy",
        raised_at=RAISED + timedelta(minutes=15),
        escalation_due_at=None,
        part_of_id="alert-1",
    )

    assert escalation.part_of_id == "alert-1"
