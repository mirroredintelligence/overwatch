"""The subscription, alert and week-summary mappings (R12) with no store and no app.

The FHIR R4B Subscription was verified against fhir.resources.R4B before the mapping was written
(the prompt asked for that check; the result is at the top of subscription_mapping.py). Here: the
mapping parses with R4B, every setting range is checked at the edge with the name of the setting,
and a summary figure under the small-group threshold is withheld with no value.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, time

import pytest
from fhir.resources.R4B.subscription import Subscription

from diucs.adapters.inbound.fhir_rest.subscription_mapping import (
    alert_to_task,
    preferences_from_fhir,
    subscription_to_fhir,
    subscription_version,
    summary_parameters,
)
from diucs.application.actor import Actor
from diucs.application.use_cases.subscribe_alert import NEVER_SAVED
from diucs.application.use_cases.week_summary import Measure, WeekSummary
from diucs.domain.codes import AlertKind, Role, code_system_url
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.alerts import AlertRecord, AlertSubscription
from diucs.domain.rules.alerts import AlertPreferences

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead",
    device_id=None,
    channel="api",
    service_ids=frozenset(),
    tenant_id="tt-sample",
)


def _subscription(**changes: object) -> AlertSubscription:
    preferences = AlertPreferences(
        kinds=frozenset({AlertKind.NOT_UPDATED, AlertKind.SERVICE_CLOSED}),
        not_updated_hours=4,
        quiet_hours=(time(22, 0), time(6, 0)),
        quiet_critical_only=True,
        ack_minutes=15,
    )
    base = AlertSubscription(
        practitioner_id="prac-lead",
        preferences=preferences,
        deputy_id="prac-deputy",
        daily_summary=True,
        weekly_summary=False,
        updated_at=NOW,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_the_subscription_parses_with_the_r4b_model_and_carries_its_settings() -> None:
    body = subscription_to_fhir(_subscription())

    parsed = Subscription.model_validate(body)

    assert parsed.id == "prac-lead"
    assert parsed.criteria == "alert-preferences"
    assert parsed.status == "active"
    extensions = {item.url: item for item in parsed.extension}
    assert extensions[code_system_url("alert-preferences/not-updated-hours")].valueInteger == 4


def test_a_subscription_with_no_alert_kinds_is_off() -> None:
    body = subscription_to_fhir(
        _subscription(
            preferences=AlertPreferences(
                kinds=frozenset(),
                not_updated_hours=2,
                quiet_hours=None,
                quiet_critical_only=False,
                ack_minutes=10,
            ),
            deputy_id=None,
        )
    )

    assert Subscription.model_validate(body).status == "off"


def test_a_subscription_never_saved_has_the_version_one() -> None:
    never = _subscription(updated_at=NEVER_SAVED)

    assert subscription_version(never) == 1


def test_a_saved_subscription_has_a_version_that_moves_with_its_last_save() -> None:
    first = subscription_version(_subscription(updated_at=NOW))
    later = subscription_version(
        _subscription(updated_at=datetime(2026, 10, 23, 14, 0, tzinfo=UTC))
    )

    assert first > 1
    assert later > first


def test_an_alert_is_a_task_for_its_owner_with_its_business_status() -> None:
    alert = AlertRecord(
        id="alert-1",
        kind=AlertKind.NOT_UPDATED,
        service_id="svc-1",
        owner_practitioner_id="prac-lead",
        status="new",
        raised_at=NOW,
        escalation_due_at=None,
        part_of_id=None,
    )

    task = alert_to_task(alert)

    assert task["resourceType"] == "Task"
    assert task["id"] == "alert-1"
    assert task["businessStatus"]["coding"][0]["code"] == "new"
    assert task["owner"]["reference"] == "Practitioner/prac-lead"


@pytest.mark.parametrize("hours", [0, 1, 3, 5, 24])
def test_a_not_updated_threshold_other_than_two_or_four_hours_is_refused(hours: int) -> None:
    body = {
        "resourceType": "Subscription",
        "id": "prac-lead",
        "extension": [
            {"url": code_system_url("alert-preferences/not-updated-hours"), "valueInteger": hours}
        ],
    }

    with pytest.raises(ValidationFailed) as refused:
        preferences_from_fhir(body)

    assert refused.value.field == "notUpdatedHours"


@pytest.mark.parametrize("minutes", [5, 20, 60])
def test_an_acknowledgement_window_other_than_ten_fifteen_or_thirty_is_refused(
    minutes: int,
) -> None:
    body = {
        "resourceType": "Subscription",
        "id": "prac-lead",
        "extension": [
            {"url": code_system_url("alert-preferences/ack-minutes"), "valueInteger": minutes}
        ],
    }

    with pytest.raises(ValidationFailed) as refused:
        preferences_from_fhir(body)

    assert refused.value.field == "ackMinutes"


def test_quiet_hours_are_none_or_ten_pm_to_six_am_only() -> None:
    body = {
        "resourceType": "Subscription",
        "id": "prac-lead",
        "extension": [
            {"url": code_system_url("alert-preferences/quiet-hours"), "valueString": "23:00-07:00"}
        ],
    }

    with pytest.raises(ValidationFailed) as refused:
        preferences_from_fhir(body)

    assert refused.value.field == "quietHours"


def test_a_figure_under_ten_is_withheld_with_no_value() -> None:
    summary = _summary(referrals=Measure(value=None, hidden=True, label="referrals"))

    parameters = summary_parameters(summary)

    referrals = _part(parameters, "referrals")
    assert [item["name"] for item in referrals["part"]] == ["suppressed"]
    assert referrals["part"][0]["valueBoolean"] is True


def test_a_figure_of_ten_or_more_shows_its_value() -> None:
    summary = _summary(referrals=Measure(value=12, hidden=False, label="referrals"))

    parameters = summary_parameters(summary)

    referrals = _part(parameters, "referrals")
    values = {item["name"]: item for item in referrals["part"]}
    assert values["value"]["valueInteger"] == 12
    assert values["suppressed"]["valueBoolean"] is False


def _part(parameters: dict, name: str) -> dict:
    return next(item for item in parameters["parameter"] if item["name"] == name)


def _summary(**overrides: Measure) -> WeekSummary:
    measure = Measure(value=None, hidden=True, label="unused")
    values: dict[str, object] = {
        "week_start": date(2026, 10, 19),
        "referrals": measure,
        "best_fit_unavailable_pct": measure,
        "on_time_pct": measure,
        "median_minutes_to_confirmed": measure,
        "updates_by_channel": {"text": measure, "app": measure, "email/link": measure},
        "time_back_text": "",
    }
    values.update(overrides)
    return WeekSummary(**values)  # type: ignore[arg-type]
