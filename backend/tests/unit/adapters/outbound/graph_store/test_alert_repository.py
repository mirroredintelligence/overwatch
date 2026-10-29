"""Pure tests of the alert store (P17): the Task mapping, the subscription properties and the
statement shape. The Neo4j behaviour is in tests/integration/graph_store/test_alert_repository.py.
"""

import re
from datetime import UTC, datetime, time
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store import alert_repository  # noqa: F401 (registers Q-ALERT-*)
from diucs.adapters.outbound.graph_store.alert_repository import (
    alert_from_fhir,
    alert_to_fhir,
    subscription_from_props,
    subscription_to_props,
)
from diucs.adapters.outbound.graph_store.queries import REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.adapters.outbound.graph_store.unconverted import UNCONVERTED
from diucs.domain.codes import AlertKind, code_system_url
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.alerts import AlertRecord, AlertSubscription
from diucs.domain.rules.alerts import AlertPreferences

RAISED = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)
DUE = datetime(2026, 10, 25, 13, 27, tzinfo=UTC)
ESCALATED = datetime(2026, 10, 25, 13, 27, tzinfo=UTC)

FIRST = AlertRecord(
    id="alert-1",
    kind=AlertKind.OVER_CAPACITY,
    service_id="svc-hospital-at-home",
    owner_practitioner_id="p-1",
    status="new",
    raised_at=RAISED,
    escalation_due_at=DUE,
    part_of_id=None,
)
ESCALATION = AlertRecord(
    id="alert-2",
    kind=AlertKind.OVER_CAPACITY,
    service_id="svc-hospital-at-home",
    owner_practitioner_id="p-deputy",
    status="escalated",
    raised_at=ESCALATED,
    escalation_due_at=None,
    part_of_id="alert-1",
)
PRESSURE = AlertRecord(
    id="alert-3",
    kind=AlertKind.SYSTEM_PRESSURE,
    service_id=None,
    owner_practitioner_id="p-1",
    status="new",
    raised_at=RAISED,
    escalation_due_at=None,
    part_of_id=None,
)
ACKNOWLEDGED = AlertRecord(
    id="alert-4",
    kind=AlertKind.NOT_UPDATED,
    service_id="svc-hospital-at-home",
    owner_practitioner_id="p-1",
    status="acknowledged",
    raised_at=RAISED,
    escalation_due_at=None,
    part_of_id=None,
    acknowledged_at=ESCALATED,
)

PREFS_ON = AlertPreferences(
    kinds=frozenset({AlertKind.OVER_CAPACITY, AlertKind.SERVICE_CLOSED}),
    not_updated_hours=2,
    quiet_hours=(time(22, 0), time(6, 0)),
    quiet_critical_only=True,
    ack_minutes=15,
)
PREFS_OFF = AlertPreferences(
    kinds=frozenset({AlertKind.SERVICE_CLOSED}),
    not_updated_hours=4,
    quiet_hours=None,
    quiet_critical_only=False,
    ack_minutes=30,
)
SUBSCRIPTION = AlertSubscription(
    practitioner_id="p1",
    preferences=PREFS_ON,
    deputy_id="p-deputy",
    daily_summary=False,
    weekly_summary=True,
    updated_at=RAISED,
)
TASK_CODE = code_system_url("task-code")
ALERT_CODE = "acknowledge-alert"


def _alert_ids() -> list[str]:
    return [query_id for query_id in REGISTRY.ids() if query_id.startswith("Q-ALERT")]


def _coding(resource: dict[str, Any]) -> dict[str, Any]:
    return resource["code"]["coding"][0]


def test_an_alert_is_a_task_with_the_acknowledge_alert_code() -> None:
    resource = alert_to_fhir(FIRST)

    assert resource["resourceType"] == "Task"
    assert resource["id"] == "alert-1"
    assert _coding(resource) == {"system": TASK_CODE, "code": ALERT_CODE}


def test_a_service_alert_focuses_its_service_and_is_owned_by_the_practitioner() -> None:
    resource = alert_to_fhir(FIRST)

    assert resource["focus"] == {"reference": "HealthcareService/svc-hospital-at-home"}
    assert resource["owner"] == {"reference": "Practitioner/p-1"}


def test_a_system_pressure_alert_has_no_focus() -> None:
    assert "focus" not in alert_to_fhir(PRESSURE)


def test_an_escalation_is_part_of_the_alert_it_follows() -> None:
    assert alert_to_fhir(ESCALATION)["partOf"] == [{"reference": "Task/alert-1"}]
    assert "partOf" not in alert_to_fhir(FIRST)


def test_the_escalation_due_time_is_a_utc_extension() -> None:
    resource = alert_to_fhir(FIRST)
    extensions = {item["url"]: item for item in resource["extension"]}

    due_url = next(url for url in extensions if url.endswith("/escalationDueAt"))
    assert extensions[due_url]["valueDateTime"] == "2026-10-25T13:27:00Z"


@pytest.mark.parametrize("alert", [FIRST, ESCALATION, PRESSURE, ACKNOWLEDGED])
def test_an_alert_round_trips_through_its_task(alert: AlertRecord) -> None:
    assert alert_from_fhir(alert_to_fhir(alert)) == alert


@pytest.mark.parametrize(
    ("status", "task_status"),
    [
        ("new", "requested"),
        ("escalated", "requested"),
        ("acknowledged", "completed"),
        ("closed", "completed"),
    ],
)
def test_an_alert_status_maps_to_a_task_status(status: str, task_status: str) -> None:
    alert = AlertRecord(
        id="alert-9",
        kind=AlertKind.OVER_CAPACITY,
        service_id="svc-hospital-at-home",
        owner_practitioner_id="p-1",
        status=status,
        raised_at=RAISED,
        escalation_due_at=None,
        part_of_id=None,
        acknowledged_at=ESCALATED if status != "new" and status != "escalated" else None,
    )

    assert alert_to_fhir(alert)["status"] == task_status


def test_a_task_that_is_not_an_alert_is_refused() -> None:
    resource = alert_to_fhir(FIRST)
    resource["code"]["coding"][0]["code"] = "register-service"

    with pytest.raises(ValidationFailed):
        alert_from_fhir(resource)


@pytest.mark.parametrize("prefs", [PREFS_ON, PREFS_OFF])
def test_a_subscription_round_trips_through_its_properties(prefs: AlertPreferences) -> None:
    subscription = AlertSubscription(
        practitioner_id="p1",
        preferences=prefs,
        deputy_id=None,
        daily_summary=True,
        weekly_summary=False,
        updated_at=RAISED,
    )

    assert subscription_from_props(subscription_to_props(subscription)) == subscription


def test_quiet_hours_are_stored_as_clock_text() -> None:
    props = subscription_to_props(SUBSCRIPTION)

    assert props["quietStart"] == "22:00"
    assert props["quietEnd"] == "06:00"
    assert props["kinds"] == sorted(props["kinds"])


def test_no_quiet_hours_are_stored_as_none() -> None:
    props = subscription_to_props(
        AlertSubscription(
            practitioner_id="p1",
            preferences=PREFS_OFF,
            deputy_id=None,
            daily_summary=False,
            weekly_summary=False,
            updated_at=RAISED,
        )
    )

    assert props["quietStart"] is None
    assert props["quietEnd"] is None


def test_the_alert_statements_are_registered() -> None:
    assert {
        "Q-ALERT-SUB-LOCK",
        "Q-ALERT-SUB-SAVE",
        "Q-ALERT-SUB-FOR",
        "Q-ALERT-SUB-KIND",
        "Q-ALERT-OPEN-FOR-OWNER",
        "Q-ALERT-SET-STATUS",
    } <= set(_alert_ids())


def test_every_alert_statement_names_its_tenant_on_every_node_it_matches_or_creates() -> None:
    pattern = re.compile(r"\((?:\w+)?(?::\w+)+\s*(\{[^}]*\})?\)")
    for query_id in _alert_ids():
        for match in pattern.finditer(REGISTRY.get(query_id).cypher):
            assert match.group(1) is not None, (query_id, match.group(0))
            assert "tenantId: $tenant" in match.group(1), (query_id, match.group(0))


def test_every_alert_statement_carries_a_valid_scenario() -> None:
    for query_id in _alert_ids():
        query = REGISTRY.get(query_id)
        assert query.scenario is not None, query_id
        assert validate_scenario(query_id, query.scenario) == [], query_id


def test_no_alert_statement_is_on_the_ratchet() -> None:
    assert not {query_id for query_id in _alert_ids() if query_id in UNCONVERTED}


def test_the_subscription_statements_do_not_hold_a_second_subscription_per_practitioner() -> None:
    # The save takes the practitioner's write lock before it merges (lesson L73).
    assert "SET p.id = p.id" in REGISTRY.get("Q-ALERT-SUB-LOCK").cypher
