"""Sample tenants and activation facts for the pure tenant tests (TEN-006).

Every tenant here is a made-up organisation. The wording values are the original deployment's
words, kept in test fixtures only: no source file may contain them (a test greps the sources).
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from diucs.domain.model.tenant import (
    ContactKind,
    OrganisationType,
    RetentionClass,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantStatus,
)
from diucs.domain.rules.tenant_lifecycle import ActivationFacts

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
SAMPLE_WORDING = {
    "systemName": "Dorset urgent care capacity",
    "referralSystemName": "SystmOne",
    "coordinationTeamName": "The SPOA shift lead",
}
SAMPLE_ID = "example-icb"

_S = TenantStatus


def make_tenant(status: TenantStatus = _S.ACTIVE, **overrides: Any) -> Tenant:
    """A valid tenant in the given status; keyword overrides replace any field."""
    fields: dict[str, Any] = {
        "id": SAMPLE_ID,
        "display_name": "Example ICB",
        "legal_name": "Example Integrated Care Board",
        "organisation_type": OrganisationType.ICB,
        "status": status,
        "created_at": T0,
    }
    if status is not _S.PROVISIONING:
        fields["activated_at"] = T0 + timedelta(days=1)
    if status is _S.SUSPENDED:
        fields["suspended_at"] = T0 + timedelta(days=2)
        fields["suspend_mode"] = SuspendMode.READ_ONLY
        fields["suspend_reason"] = SuspendReason.CONTRACT
    if status in (_S.OFFBOARDING, _S.OFFBOARDED, _S.PURGED):
        fields["offboarding_started_at"] = T0 + timedelta(days=10)
    if status in (_S.OFFBOARDED, _S.PURGED):
        fields["offboarded_at"] = T0 + timedelta(days=45)
    if status is _S.PURGED:
        fields["purged_at"] = T0 + timedelta(days=60)
    fields.update(overrides)
    return Tenant(**fields)


def passing_facts(**overrides: Any) -> ActivationFacts:
    """Activation facts where every check passes; keyword overrides replace a fact."""
    facts = ActivationFacts(
        config_approved=True,
        time_zone="Europe/London",
        active_numbers_tested=1,
        email_in_use=True,
        email_sender_verified=True,
        first_admin_invited=True,
        entra_binding_verified=True,
        role_mappings=1,
        contact_kinds=frozenset(
            {ContactKind.COORDINATION_PHONE, ContactKind.CLINICAL_SAFETY_OFFICER}
        ),
        retention_classes_set=frozenset(RetentionClass),
        references_recorded=frozenset({"dsa", "dpia", "dcb0160"}),
        wording_complete=True,
        registers_services=True,
        area_districts_set=True,
        network_member=True,
        agreement_accepted=True,
    )
    return replace(facts, **overrides)
