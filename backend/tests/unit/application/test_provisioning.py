"""What provisioning builds and the scope every new tenant gets (TEN-028, DEC-503).

The pure functions (the new record, the activation facts, the extra blocker) and `provision_scope`
on recording fakes. The whole flow on a real graph is
`tests/integration/application/test_tenant_provisioning.py`.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord
from diucs.application.provisioning import (
    MISSING_HOST,
    activation_facts,
    count_tested_numbers,
    extra_blockers,
    new_tenant,
    provision_scope,
    references_recorded,
    same_creation,
    seed_recurring_work,
)
from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope
from diucs.application.use_cases.tenant_config import ConfigurationFacts
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import (
    ContactKind,
    NumberStatus,
    OrganisationType,
    RetentionClass,
    TenantStatus,
)
from diucs.domain.rules.tenant_lifecycle import (
    ActivationFacts,
    activation_blockers,
)
from tests.support.provisioning_fakes import NOW, TENANT, FakeHeads, FakeWorld, provisioning_tenant
from tests.support.tenancy import as_tenant

SID = "AC" + "1" * 32
NUMBER = "+447700900123"
SECRET = f"twilio/{TENANT}/auth-token"


def _number(**fields: object) -> TenantNumberRecord:
    base = {"e164": NUMBER, "account_sid": SID, "secret_ref": SECRET}
    return TenantNumberRecord(**{**base, **fields})  # type: ignore[arg-type]


def _configuration(**fields: object) -> ConfigurationFacts:
    base = {
        "config_approved": True,
        "wording_complete": True,
        "contact_kinds": frozenset(
            {ContactKind.COORDINATION_PHONE, ContactKind.CLINICAL_SAFETY_OFFICER}
        ),
        "retention_classes_set": frozenset(RetentionClass),
        "role_mappings": 1,
        "entra_binding_verified": True,
        "active_sms_channels": 1,
        "active_email_channels": 0,
    }
    return ConfigurationFacts(**{**base, **fields})  # type: ignore[arg-type]


# -- the new record ------------------------------------------------------------------------------


def test_a_new_tenant_is_in_provisioning_with_its_own_keys_and_nothing_else_set() -> None:
    tenant = new_tenant(
        tenant_id=TENANT,
        display_name="New Organisation",
        legal_name="New Organisation Ltd",
        organisation_type=OrganisationType.ICB,
        now=NOW,
    )
    assert tenant.status is TenantStatus.PROVISIONING
    assert tenant.epoch == 1 and tenant.hash_key_version == 1
    assert tenant.created_at == NOW and tenant.activated_at is None
    assert tenant.time_zone == "Europe/London" and tenant.country_code == "GB"
    assert (tenant.dsa_ref, tenant.dpia_ref, tenant.dcb0160_ref, tenant.ods_code) == (None,) * 4


@pytest.mark.parametrize(
    "field",
    [
        {"tenant_id": "platform"},
        {"tenant_id": "net-west"},
        {"display_name": ""},
        {"legal_name": "x" * 200},
        {"time_zone": "America/New_York"},  # not on the allow-list
        {"country_code": "gb"},
    ],
)
def test_the_record_refuses_what_it_refuses(field: dict[str, str]) -> None:
    base = {
        "tenant_id": TENANT,
        "display_name": "New Organisation",
        "legal_name": "New Organisation Ltd",
        "organisation_type": OrganisationType.OTHER,
        "now": NOW,
    }
    with pytest.raises(ValidationFailed):
        new_tenant(**{**base, **field})  # type: ignore[arg-type]


def test_a_stopped_creation_is_the_same_creation_only_when_every_field_agrees() -> None:
    wanted = provisioning_tenant()
    assert same_creation(provisioning_tenant(), wanted)
    # Another tenant that holds the id, or one that has moved on, is not.
    for existing in (
        provisioning_tenant(display_name="Another"),
        provisioning_tenant(legal_name="Another Ltd"),
        provisioning_tenant(organisation_type=OrganisationType.ICB),
        provisioning_tenant(ods_code="ABC12"),
        provisioning_tenant(status=TenantStatus.ACTIVE, activated_at=NOW),
    ):
        assert not same_creation(existing, wanted)


# -- the activation facts ------------------------------------------------------------------------


def test_only_an_active_number_that_has_delivered_a_test_text_counts() -> None:
    numbers = (
        _number(),
        _number(e164="+447700900124", tested_at=NOW),
        _number(e164="+447700900125", tested_at=NOW, status=NumberStatus.RETIRED),
        _number(e164="+447700900126", tested_at=NOW, status=NumberStatus.QUARANTINED),
    )
    assert count_tested_numbers(numbers) == 1
    assert count_tested_numbers(()) == 0


def test_the_references_are_the_ones_the_operator_recorded() -> None:
    assert references_recorded(provisioning_tenant()) == frozenset()
    assert references_recorded(provisioning_tenant(dsa_ref="D-1", dcb0160_ref="C-1")) == frozenset(
        {"dsa", "dcb0160"}
    )


def _facts(**fields: object) -> ActivationFacts:
    tenant = provisioning_tenant(dsa_ref="D-1", dpia_ref="P-1", dcb0160_ref="C-1")
    base = {
        "configuration": _configuration(),
        "numbers": (_number(tested_at=NOW),),
        "first_admin_invited": True,
        "area_districts_set": True,
    }
    return activation_facts(tenant, **{**base, **fields})  # type: ignore[arg-type]


def test_a_complete_tenant_has_no_blocker() -> None:
    assert activation_blockers(_facts()) == []


def test_each_fact_comes_from_its_own_source() -> None:
    assert activation_blockers(_facts(first_admin_invited=False)) == [
        "First tenant administrator invited"
    ]
    assert activation_blockers(_facts(area_districts_set=False)) == ["Area districts set"]
    assert activation_blockers(_facts(numbers=())) == [
        "At least one sender number active with a test text delivered"
    ]
    assert activation_blockers(_facts(configuration=_configuration(config_approved=False))) == [
        "Configuration version approved"
    ]
    assert activation_blockers(_facts(configuration=_configuration(wording_complete=False))) == [
        "System, referral system and coordination team names set"
    ]
    assert activation_blockers(_facts(configuration=_configuration(role_mappings=0))) == [
        "At least one role mapping"
    ]


def test_email_is_checked_only_when_the_tenant_has_an_email_channel() -> None:
    assert activation_blockers(_facts(configuration=_configuration(active_email_channels=0))) == []
    # An active email channel is a verified one: the operator makes it active once verified.
    assert activation_blockers(_facts(configuration=_configuration(active_email_channels=1))) == []


def test_a_tenant_without_references_is_blocked_and_the_zone_is_the_records() -> None:
    bare = provisioning_tenant()
    facts = activation_facts(
        bare,
        _configuration(),
        (_number(tested_at=NOW),),
        first_admin_invited=True,
        area_districts_set=True,
    )
    assert facts.time_zone == "Europe/London"
    assert activation_blockers(facts) == [
        "Data sharing, data protection and clinical safety references recorded"
    ]


def test_a_tenant_is_not_a_network_member_until_the_network_work_says_so() -> None:
    facts = _facts()
    assert facts.network_member is False and facts.agreement_accepted is False
    assert facts.registers_services is True


def test_a_tenant_with_no_host_has_the_one_extra_blocker() -> None:
    assert extra_blockers(None) == [MISSING_HOST]
    assert extra_blockers("") == [MISSING_HOST]
    assert extra_blockers("new-org.example.org") == []


# -- the scope ------------------------------------------------------------------------------------


async def test_provisioning_a_scope_gives_the_bound_tenant_its_head_and_its_list() -> None:
    heads, world = FakeHeads(), FakeWorld()
    with as_tenant(TENANT):
        provisioned = await provision_scope(heads, world.factory())  # type: ignore[arg-type]
    assert provisioned.audit_head and provisioned.scope_list
    assert [s.value for s in heads.calls if s] == [TENANT]
    assert world.lists_ensured == 1 and world.commits == 1


async def test_provisioning_twice_does_the_same_again_and_harms_nothing() -> None:
    heads, world = FakeHeads(), FakeWorld()
    with as_tenant(TENANT):
        await provision_scope(heads, world.factory())  # type: ignore[arg-type]
        await provision_scope(heads, world.factory())  # type: ignore[arg-type]
    assert world.lists_ensured == 2  # each call is `ensure`: the statements are MERGEs


@pytest.mark.parametrize("scope", [None, ScopeId.network("net-west")], ids=["none", "network"])
async def test_a_scope_that_is_not_a_tenants_is_refused_before_anything_is_made(
    scope: ScopeId | None,
) -> None:
    heads, world = FakeHeads(), FakeWorld()
    if scope is None:
        with pytest.raises(TenantNotBound):
            await provision_scope(heads, world.factory())  # type: ignore[arg-type]
    else:
        with bind_scope(scope), pytest.raises(TenantNotBound):
            await provision_scope(heads, world.factory())  # type: ignore[arg-type]
    assert heads.calls == [] and world.opened == 0


async def test_seeding_the_recurring_work_needs_a_tenant_too() -> None:
    world = FakeWorld()
    with pytest.raises(TenantNotBound):
        await seed_recurring_work(world.factory(), None, None)  # type: ignore[arg-type]
    assert world.opened == 0


def test_the_facts_are_a_value_and_replace_keeps_the_checks() -> None:
    facts = _facts()
    assert replace(facts, time_zone="Europe/London").time_zone == "Europe/London"
    assert datetime(2026, 1, 1, tzinfo=UTC) < NOW
