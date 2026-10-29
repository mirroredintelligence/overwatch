"""The notification consent resource (I14): a FHIR Consent that R4B accepts without a patient.

Pure: the resource is built and validated against fhir.resources R4B, no graph is used. The write
through the resource store, and the round trip, are in tests/integration.
"""

from datetime import UTC, datetime

from fhir.resources.R4B.consent import Consent

from diucs.adapters.outbound.graph_store.notification_consent_store import (
    CONSENT_CATEGORY_CODE,
    CONSENT_WORDING_SYSTEM,
    consent_id,
    consent_resource,
)

AT = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)


def test_a_consent_is_an_active_notification_consent_performed_by_the_practitioner() -> None:
    resource = consent_resource("p1", "dev-1", "wording-v1", "active", AT)
    model = Consent.model_validate(resource)
    assert model.status == "active"
    assert model.performer[0].reference == "Practitioner/p1"
    assert model.sourceReference.reference == "Device/dev-1"
    assert model.patient is None
    assert CONSENT_CATEGORY_CODE == "notification"
    assert model.category[0].coding[0].code == "notification"
    assert model.dateTime.astimezone(UTC) == AT


def test_the_wording_version_is_carried_as_the_policy_rule_coding() -> None:
    """DEC-340: the wording version is a policyRule coding, not an extension (the mapper keeps
    only registered extensions)."""
    resource = consent_resource("p1", "dev-1", "wording-v1", "active", AT)
    coding = Consent.model_validate(resource).policyRule.coding[0]
    assert (coding.system, coding.code) == (CONSENT_WORDING_SYSTEM, "wording-v1")


def test_a_withdrawn_consent_is_inactive_and_keeps_its_wording_version() -> None:
    resource = consent_resource("p1", "dev-1", "wording-v1", "inactive", AT)
    model = Consent.model_validate(resource)
    assert model.status == "inactive"
    assert model.policyRule.coding[0].code == "wording-v1"


def test_the_consent_id_is_one_per_device() -> None:
    assert consent_id("dev-1") == "notif-dev-1"
    assert consent_id("dev-2") != consent_id("dev-1")


def test_no_name_telephone_or_postcode_is_in_the_consent() -> None:
    resource = consent_resource("p1", "dev-1", "wording-v1", "active", AT)
    text = repr(resource)
    assert "07700" not in text
    assert "telecom" not in text
    assert "name" not in resource
    assert "patient" not in resource
