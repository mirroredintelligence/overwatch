"""Alert preferences, alerts and the week summary as FHIR (R12). Stub: built in the implement
commit of R12."""

from typing import Any

from diucs.application.use_cases.subscribe_alert import NEVER_SAVED  # noqa: F401
from diucs.application.use_cases.week_summary import WeekSummary
from diucs.domain.model.alerts import AlertRecord, AlertSubscription
from diucs.domain.rules.alerts import AlertPreferences


def subscription_to_fhir(subscription: AlertSubscription) -> dict[str, Any]:
    raise NotImplementedError("R12: the Subscription mapping is not built yet")


def subscription_version(subscription: AlertSubscription) -> int:
    raise NotImplementedError("R12: the version is not built yet")


def preferences_from_fhir(body: object) -> AlertPreferences:
    raise NotImplementedError("R12: the Subscription parse is not built yet")


def alert_to_task(alert: AlertRecord) -> dict[str, Any]:
    raise NotImplementedError("R12: the alert Task mapping is not built yet")


def summary_parameters(summary: WeekSummary) -> dict[str, Any]:
    raise NotImplementedError("R12: the summary mapping is not built yet")
