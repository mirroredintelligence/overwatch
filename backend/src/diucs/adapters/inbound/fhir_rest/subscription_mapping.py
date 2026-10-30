"""Alert preferences, alerts and the week summary as FHIR (R12). The mapping is pure: no store, no
clock, no app.

Verified against `fhir.resources.R4B` before this was written (the prompt asked for it):
- `Subscription` (FHIR 4.3.0 as R4B) has the elements status, contact, end, reason, criteria, error
  and channel. Channel has type, endpoint, payload, header and extension. `channel` is the one
  element the model requires.
- There is no `topic` element on R4B `Subscription`. Topic-based subscriptions belong to the R5
  model; `SubscriptionTopic` is a separate resource in 4.3.0 that `Subscription` does not reference.
  So the alert preferences here use `criteria` as a fixed name ("alert-preferences") and carry
  each setting as an extension under the platform's code system (`code_system_url`).
- `channel.type` is set to "message", the R4B code for a message channel. The alerts are delivered
  by push and text (I14), not by a REST hook, so the channel names no endpoint.

Preferences are a platform node (P17), not a FHIR resource. This mapping gives them a FHIR shape
for the API only. The version the `If-Match` header compares is derived from the stored save: 1 for
preferences never saved, else the save's epoch milliseconds plus one (always a positive whole
number, which the concurrency module accepts).

A PUT carries the whole state. A setting it leaves out keeps the rule book's default; the alert
kinds it leaves out are none (the body is the list of kinds that are on).
"""

from datetime import time
from typing import Any, Final

from diucs.adapters.inbound.fhir_rest.parameters import reference_id
from diucs.application.actor import Actor
from diucs.application.use_cases.subscribe_alert import NEVER_SAVED, SaveAlertPreferencesCommand
from diucs.application.use_cases.week_summary import Measure, WeekSummary
from diucs.domain.codes import AlertKind, code_system_url
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.alerts import AlertRecord, AlertSubscription
from diucs.domain.rules.alerts import (
    ACK_MINUTES,
    NOT_UPDATED_HOURS,
    QUIET_END,
    QUIET_START,
    AlertPreferences,
    default_preferences,
)

SUBSCRIPTION: Final = "Subscription"
CRITERIA: Final = "alert-preferences"
REASON: Final = "Alert preferences of a shift lead or an executive"
TASK_CODE_SYSTEM: Final = code_system_url("task-code")
ALERT_CODE: Final = "acknowledge-alert"
ALERT_STATUS_SYSTEM: Final = code_system_url("alert-status")
ALERT_KIND_SYSTEM: Final = code_system_url("alert-kind")
OPEN_STATUSES: Final = frozenset({"new", "escalated"})
QUIET_TEXT: Final = "22:00-06:00"
"""The one quiet-hours window the preferences allow (D24)."""


def _setting_url(name: str) -> str:
    return code_system_url(f"{CRITERIA}/{name}")


def subscription_version(subscription: AlertSubscription) -> int:
    """The version of the saved preferences, for `If-Match` and the ETag. Never saved is 1."""
    if subscription.updated_at == NEVER_SAVED:
        return 1
    return int(subscription.updated_at.timestamp() * 1000) + 1


def _setting(name: str, value_key: str, value: Any) -> dict[str, Any]:
    return {"url": _setting_url(name), value_key: value}


def subscription_to_fhir(subscription: AlertSubscription) -> dict[str, Any]:
    """The practitioner's preferences as a Subscription. The id is the practitioner's id: one
    subscription per practitioner (P17). The status is `active` while any alert kind is on."""
    prefs = subscription.preferences
    extensions: list[dict[str, Any]] = [
        _setting("kind", "valueCode", kind.value) for kind in sorted(prefs.kinds, key=str)
    ]
    extensions.append(_setting("not-updated-hours", "valueInteger", prefs.not_updated_hours))
    extensions.append(_setting("ack-minutes", "valueInteger", prefs.ack_minutes))
    extensions.append(_setting("quiet-critical-only", "valueBoolean", prefs.quiet_critical_only))
    if prefs.quiet_hours is not None:
        extensions.append(_setting("quiet-hours", "valueString", QUIET_TEXT))
    if subscription.deputy_id is not None:
        deputy = {"reference": f"Practitioner/{subscription.deputy_id}"}
        extensions.append(_setting("deputy", "valueReference", deputy))
    extensions.append(_setting("daily-summary", "valueBoolean", subscription.daily_summary))
    extensions.append(_setting("weekly-summary", "valueBoolean", subscription.weekly_summary))
    return {
        "resourceType": SUBSCRIPTION,
        "id": subscription.practitioner_id,
        "meta": {"versionId": str(subscription_version(subscription))},
        "status": "active" if prefs.kinds else "off",
        "reason": REASON,
        "criteria": CRITERIA,
        "channel": {"type": "message"},
        "extension": extensions,
    }


def _items(body: dict[str, Any], name: str) -> list[dict[str, Any]]:
    url = _setting_url(name)
    return [item for item in body.get("extension") or [] if item.get("url") == url]


def _one(body: dict[str, Any], name: str) -> dict[str, Any] | None:
    items = _items(body, name)
    if len(items) > 1:
        raise ValidationFailed(name, "is given once")
    return items[0] if items else None


def _whole_in(body: dict[str, Any], name: str, field: str, allowed: frozenset[int]) -> int | None:
    item = _one(body, name)
    if item is None:
        return None
    value = item.get("valueInteger")
    if type(value) is not int or value not in allowed:
        listed = ", ".join(str(v) for v in sorted(allowed))
        raise ValidationFailed(field, f"must be one of {listed}")
    return value


def _flag(body: dict[str, Any], name: str, default: bool, field: str) -> bool:
    item = _one(body, name)
    if item is None:
        return default
    value = item.get("valueBoolean")
    if type(value) is not bool:
        raise ValidationFailed(field, "must be true or false")
    return value


def _kinds(body: dict[str, Any]) -> frozenset[AlertKind]:
    kinds: set[AlertKind] = set()
    for item in _items(body, "kind"):
        try:
            kinds.add(AlertKind(str(item.get("valueCode"))))
        except ValueError:
            raise ValidationFailed("kinds", "must be alert kinds") from None
    return frozenset(kinds)


def preferences_from_fhir(body: object) -> AlertPreferences:
    """The alert preferences a Subscription body sets. A setting the body leaves out keeps the
    default. A value out of range is refused, named by the setting's element (camel case)."""
    if not isinstance(body, dict) or body.get("resourceType") != SUBSCRIPTION:
        raise ValidationFailed(SUBSCRIPTION, "the body must be a FHIR Subscription")
    defaults = default_preferences()
    quiet_item = _one(body, "quiet-hours")
    quiet: tuple[time, time] | None = None
    if quiet_item is not None:
        if quiet_item.get("valueString") != QUIET_TEXT:
            raise ValidationFailed("quietHours", "must be 22:00 to 06:00, or none")
        quiet = (QUIET_START, QUIET_END)
    not_updated = _whole_in(body, "not-updated-hours", "notUpdatedHours", NOT_UPDATED_HOURS)
    ack = _whole_in(body, "ack-minutes", "ackMinutes", ACK_MINUTES)
    return AlertPreferences(
        kinds=_kinds(body),
        not_updated_hours=defaults.not_updated_hours if not_updated is None else not_updated,
        quiet_hours=quiet,
        quiet_critical_only=_flag(body, "quiet-critical-only", False, "quietCriticalOnly"),
        ack_minutes=defaults.ack_minutes if ack is None else ack,
    )


def save_command(body: object, actor: Actor, key: str) -> SaveAlertPreferencesCommand:
    """The save command of one Subscription body. The deputy is a Practitioner reference, checked
    by the use case, which also checks that the deputy holds a leadership role."""
    if not isinstance(body, dict):
        raise ValidationFailed(SUBSCRIPTION, "the body must be a FHIR Subscription")
    prefs = preferences_from_fhir(body)
    deputy_item = _one(body, "deputy")
    deputy: str | None = None
    if deputy_item is not None:
        reference = (deputy_item.get("valueReference") or {}).get("reference")
        deputy = reference_id(reference, "deputy", "Practitioner")
    return SaveAlertPreferencesCommand(
        idempotency_key=key,
        actor=actor,
        kinds=prefs.kinds,
        not_updated_hours=prefs.not_updated_hours,
        quiet_hours=prefs.quiet_hours,
        quiet_critical_only=prefs.quiet_critical_only,
        ack_minutes=prefs.ack_minutes,
        deputy_id=deputy,
        daily_summary=_flag(body, "daily-summary", False, "dailySummary"),
        weekly_summary=_flag(body, "weekly-summary", False, "weeklySummary"),
    )


def alert_to_task(alert: AlertRecord) -> dict[str, Any]:
    """An alert as a Task for its owner. The business status is the alert's status. An alert holds
    no free text (H-09), so none is shown."""
    task: dict[str, Any] = {
        "resourceType": "Task",
        "id": alert.id,
        "status": "requested" if alert.status in OPEN_STATUSES else "completed",
        "code": {"coding": [{"system": TASK_CODE_SYSTEM, "code": ALERT_CODE}]},
        "businessStatus": {"coding": [{"system": ALERT_STATUS_SYSTEM, "code": alert.status}]},
        "owner": {"reference": f"Practitioner/{alert.owner_practitioner_id}"},
        "authoredOn": alert.raised_at.isoformat(),
        "extension": [{"url": ALERT_KIND_SYSTEM, "valueCode": alert.kind.value}],
    }
    if alert.service_id is not None:
        task["focus"] = {"reference": f"HealthcareService/{alert.service_id}"}
    if alert.escalation_due_at is not None:
        task["executionPeriod"] = {"end": alert.escalation_due_at.isoformat()}
    return task


def _measure_parts(measure: Measure) -> list[dict[str, Any]]:
    """A figure as its parts. A withheld figure has the suppressed flag and no value: a count under
    the small-group threshold is never shown, not even as a rounded number (R12)."""
    parts: list[dict[str, Any]] = [{"name": "suppressed", "valueBoolean": measure.hidden}]
    if measure.hidden or measure.value is None:
        return parts
    if type(measure.value) is int:
        parts.append({"name": "value", "valueInteger": measure.value})
    else:
        parts.append({"name": "value", "valueDecimal": float(measure.value)})
    return parts


def summary_parameters(summary: WeekSummary) -> dict[str, Any]:
    """The week summary as Parameters: one parameter per figure, with the suppressed flag and, when
    the figure is shown, its value."""
    parameters: list[dict[str, Any]] = [
        {"name": "weekStart", "valueDate": summary.week_start.isoformat()},
        {"name": "referrals", "part": _measure_parts(summary.referrals)},
        {"name": "bestFitUnavailablePct", "part": _measure_parts(summary.best_fit_unavailable_pct)},
        {"name": "onTimePct", "part": _measure_parts(summary.on_time_pct)},
        {
            "name": "medianMinutesToConfirmed",
            "part": _measure_parts(summary.median_minutes_to_confirmed),
        },
        {
            "name": "updatesByChannel",
            "part": [
                {"name": channel, "part": _measure_parts(measure)}
                for channel, measure in summary.updates_by_channel.items()
            ],
        },
    ]
    if summary.time_back_text:
        parameters.append({"name": "timeBackText", "valueString": summary.time_back_text})
    return {"resourceType": "Parameters", "parameter": parameters}


__all__ = [
    "alert_to_task",
    "preferences_from_fhir",
    "save_command",
    "subscription_to_fhir",
    "subscription_version",
    "summary_parameters",
]
