"""Tenant record, identifiers, time zone, contacts, wording and configuration versions (TEN-006).

Rules: docs/delivery/decisions.md DEC-155 and the task prompt rules 1 to 4, 7 and 10.
"""

import dataclasses
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.domain.errors import ValidationFailed
from diucs.domain.model import tenant as tenant_module
from diucs.domain.model.tenant import (
    ALLOWED_TIME_ZONES,
    DEFAULT_TIME_ZONE,
    REQUIRED_RETENTION_CLASSES,
    RESERVED_TENANT_IDS,
    RESERVED_TENANT_PREFIX,
    TENANT_ID_PATTERN,
    ConfigStatus,
    ContactKind,
    NumberStatus,
    OrganisationType,
    RetentionClass,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantConfig,
    TenantContact,
    TenantStatus,
    TenantWording,
    check_tenant_id,
    check_time_zone,
)
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.tenant_settings import policy_from_settings
from tests.support.tenant_samples import SAMPLE_WORDING, T0, make_tenant

CANARY = "canary-tenant-ref"
S = TenantStatus


# ---------------------------------------------------------------- 1. tenant id


def test_the_identifier_constants_are_as_decided() -> None:
    assert TENANT_ID_PATTERN.pattern == r"[a-z0-9][a-z0-9-]{1,30}"
    assert frozenset({"platform"}) == RESERVED_TENANT_IDS
    assert RESERVED_TENANT_PREFIX == "net-"


@pytest.mark.parametrize("good", ["dorset-icb", "a1", "ab", "a" * 31, "0-9", "a--b", "9" * 31])
def test_check_tenant_id_accepts_and_returns_the_value_unchanged(good: str) -> None:
    assert check_tenant_id(good) is good


class _TextSubclass(str):
    pass


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "a",
        "a" * 32,
        "Dorset",
        "-ab",
        "_net-x",
        "_ab",
        "a:b",
        "a*",
        "a b",
        "a/b",
        "ab\n",
        "éa",
        "platform",
        "net-abc",
        "net-",
        _TextSubclass("dorset-icb"),
        None,
        b"ab",
        5,
        ["ab"],
    ],
    ids=lambda v: repr(v)[:24],
)
def test_check_tenant_id_refuses(bad: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_tenant_id(bad)
    assert refused.value.field == "tenant_id"


def test_the_refusal_names_no_value() -> None:
    for bad in (CANARY + "!", "net-" + CANARY, "platform"):
        with pytest.raises(ValidationFailed) as refused:
            check_tenant_id(bad)
        assert "canary" not in str(refused.value)
    with pytest.raises(ValidationFailed) as refused:
        check_tenant_id("platform")
    assert "platform" not in str(refused.value)


# the oracle is typed out here, not read from the module
_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,30}")


@settings(max_examples=500, deadline=None)
@given(st.one_of(st.text(), st.from_regex(_ID, fullmatch=True), st.text("ab-9_N:", max_size=33)))
def test_property_check_tenant_id_accepts_exactly_the_valid_ids(text: str) -> None:
    valid = _ID.fullmatch(text) is not None and text != "platform" and not text.startswith("net-")
    if valid:
        assert check_tenant_id(text) == text
    else:
        with pytest.raises(ValidationFailed):
            check_tenant_id(text)


# ---------------------------------------------------------------- the enums


def test_the_enums_hold_the_decided_members() -> None:
    assert [m.value for m in OrganisationType] == [
        "nhs-trust",
        "icb",
        "gp-practice",
        "local-authority",
        "voluntary-independent",
        "other",
    ]
    assert [m.value for m in TenantStatus] == [
        "provisioning",
        "active",
        "suspended",
        "offboarding",
        "offboarded",
        "purged",
    ]
    assert [m.value for m in SuspendMode] == ["read-only", "blocked"]
    assert [m.value for m in SuspendReason] == [
        "security-incident",
        "information-governance",
        "clinical-safety",
        "contract",
        "operator-request",
    ]
    assert [m.value for m in ContactKind] == [
        "coordination-phone",
        "support-email",
        "shift-lead-escalation",
        "clinical-safety-officer",
    ]
    assert [m.value for m in ConfigStatus] == ["draft", "pending-approval", "current", "superseded"]
    assert [m.value for m in NumberStatus] == ["active", "retired", "quarantined"]
    assert {m.value for m in RetentionClass} == {
        "capacity-reports",
        "bookings",
        "case-audit",
        "communications",
        "telemetry-raw",
        "telemetry-aggregates",
        "audit-chain",
        "safety-concerns",
    }
    assert frozenset(RetentionClass) == REQUIRED_RETENTION_CLASSES


# ---------------------------------------------------------------- 3. the Tenant record


def test_a_tenant_has_its_fields_in_order_with_the_decided_defaults() -> None:
    assert [f.name for f in dataclasses.fields(Tenant)] == [
        "id",
        "display_name",
        "legal_name",
        "organisation_type",
        "country_code",
        "time_zone",
        "status",
        "created_at",
        "activated_at",
        "suspended_at",
        "offboarding_started_at",
        "offboarded_at",
        "purged_at",
        "suspend_mode",
        "suspend_reason",
        "retention_hold_until",
        "ods_code",
        "epoch",
        "hash_key_version",
        "current_config_version",
        "dsa_ref",
        "dpia_ref",
        "dcb0160_ref",
    ]
    tenant = make_tenant(S.PROVISIONING)
    assert tenant.country_code == "GB"
    assert tenant.time_zone == DEFAULT_TIME_ZONE == "Europe/London"
    assert (tenant.epoch, tenant.hash_key_version) == (1, 1)
    assert tenant.ods_code is None and tenant.current_config_version is None
    assert (tenant.dsa_ref, tenant.dpia_ref, tenant.dcb0160_ref) == (None, None, None)


def test_a_valid_tenant_of_each_status_is_built_and_is_frozen() -> None:
    for status in TenantStatus:
        tenant = make_tenant(status)
        assert tenant.status is status
    with pytest.raises(dataclasses.FrozenInstanceError):
        make_tenant().epoch = 2  # type: ignore[misc]


def test_a_bad_id_is_refused_by_the_record() -> None:
    with pytest.raises(ValidationFailed) as refused:
        make_tenant(id="Bad Id")
    assert refused.value.field == "tenant_id"


def test_provisioning_may_carry_an_activation_time() -> None:
    assert make_tenant(S.PROVISIONING, activated_at=T0 + timedelta(days=1))


STATUS_FIELD_REFUSALS = [
    ("suspended without a mode", S.SUSPENDED, {"suspend_mode": None}),
    ("suspended without a reason", S.SUSPENDED, {"suspend_reason": None}),
    ("suspended without a time", S.SUSPENDED, {"suspended_at": None}),
    ("active with a mode", S.ACTIVE, {"suspend_mode": SuspendMode.BLOCKED}),
    ("active with a reason", S.ACTIVE, {"suspend_reason": SuspendReason.CONTRACT}),
    ("active with a suspend time", S.ACTIVE, {"suspended_at": T0 + timedelta(days=2)}),
    ("offboarding with a mode", S.OFFBOARDING, {"suspend_mode": SuspendMode.READ_ONLY}),
    ("active with no activation", S.ACTIVE, {"activated_at": None}),
    ("suspended with no activation", S.SUSPENDED, {"activated_at": None}),
    ("offboarding with no activation", S.OFFBOARDING, {"activated_at": None}),
    ("purged with no activation", S.PURGED, {"activated_at": None}),
    ("offboarding with no start", S.OFFBOARDING, {"offboarding_started_at": None}),
    ("offboarded with no start", S.OFFBOARDED, {"offboarding_started_at": None}),
    ("purged with no start", S.PURGED, {"offboarding_started_at": None}),
    ("offboarded with no end", S.OFFBOARDED, {"offboarded_at": None}),
    ("purged with no end", S.PURGED, {"offboarded_at": None}),
    ("purged with no purge time", S.PURGED, {"purged_at": None}),
    ("active with a purge time", S.ACTIVE, {"purged_at": T0 + timedelta(days=2)}),
    ("offboarded with a purge time", S.OFFBOARDED, {"purged_at": T0 + timedelta(days=60)}),
    ("active with a start", S.ACTIVE, {"offboarding_started_at": T0 + timedelta(days=2)}),
    (
        "offboarding with an end",
        S.OFFBOARDING,
        {"offboarded_at": T0 + timedelta(days=45)},
    ),
]


@pytest.mark.parametrize(
    ("status", "overrides"),
    [case[1:] for case in STATUS_FIELD_REFUSALS],
    ids=[case[0] for case in STATUS_FIELD_REFUSALS],
)
def test_the_status_and_its_timestamps_must_agree(status: TenantStatus, overrides: Any) -> None:
    with pytest.raises(ValidationFailed):
        make_tenant(status, **overrides)


def test_the_set_timestamps_must_be_in_order() -> None:
    day = timedelta(days=1)
    cases: list[tuple[TenantStatus, dict[str, Any]]] = [
        (S.ACTIVE, {"activated_at": T0 - day}),
        (S.OFFBOARDING, {"offboarding_started_at": T0}),
        (S.OFFBOARDED, {"offboarded_at": T0 + day * 5}),
        (S.PURGED, {"purged_at": T0 + day * 20}),
        (S.SUSPENDED, {"suspended_at": T0}),
    ]
    for status, overrides in cases:
        with pytest.raises(ValidationFailed):
            make_tenant(status, **overrides)


def test_equal_timestamps_are_in_order() -> None:
    assert make_tenant(S.ACTIVE, activated_at=T0)
    assert make_tenant(S.SUSPENDED, activated_at=T0, suspended_at=T0)
    assert make_tenant(S.OFFBOARDING, activated_at=T0, offboarding_started_at=T0)
    assert make_tenant(
        S.PURGED,
        activated_at=T0,
        offboarding_started_at=T0,
        offboarded_at=T0,
        purged_at=T0,
    )


def test_a_suspend_time_may_fall_anywhere_after_activation() -> None:
    assert make_tenant(S.SUSPENDED, suspended_at=T0 + timedelta(days=400))


def test_a_naive_datetime_is_refused_in_every_field() -> None:
    naive = datetime(2026, 1, 6, 9, 0)
    cases: list[tuple[TenantStatus, dict[str, Any]]] = [
        (S.ACTIVE, {"created_at": naive}),
        (S.ACTIVE, {"activated_at": naive}),
        (S.SUSPENDED, {"suspended_at": naive}),
        (S.OFFBOARDING, {"offboarding_started_at": naive}),
        (S.OFFBOARDED, {"offboarded_at": naive}),
        (S.PURGED, {"purged_at": naive}),
        (S.ACTIVE, {"retention_hold_until": naive}),
    ]
    for status, overrides in cases:
        with pytest.raises(ValidationFailed):
            make_tenant(status, **overrides)
    for not_a_datetime in ("2026-01-05", 5, None):
        with pytest.raises(ValidationFailed):
            make_tenant(S.ACTIVE, created_at=not_a_datetime)


def test_an_aware_retention_hold_is_kept() -> None:
    hold = T0 + timedelta(days=500)
    assert make_tenant(S.ACTIVE, retention_hold_until=hold).retention_hold_until == hold


def test_an_enum_is_checked_by_type_not_by_value() -> None:
    # "active" == TenantStatus.ACTIVE, and NumberStatus.ACTIVE == TenantStatus.ACTIVE (lesson L3).
    assert S.ACTIVE == "active"
    assert NumberStatus.ACTIVE == S.ACTIVE
    for bad_status in ("active", NumberStatus.ACTIVE, None, 1):
        with pytest.raises(ValidationFailed) as refused:
            make_tenant(status=bad_status)
        assert refused.value.field == "status"
    for bad_type in ("icb", ConfigStatus.DRAFT, None):
        with pytest.raises(ValidationFailed) as refused:
            make_tenant(organisation_type=bad_type)
        assert refused.value.field == "organisation_type"
    for bad_mode in ("read-only", None, SuspendReason.CONTRACT):
        with pytest.raises(ValidationFailed) as refused:
            make_tenant(S.SUSPENDED, suspend_mode=bad_mode)
        assert refused.value.field == "suspend_mode"
    for bad_reason in ("contract", SuspendMode.BLOCKED, 3):
        with pytest.raises(ValidationFailed) as refused:
            make_tenant(S.SUSPENDED, suspend_reason=bad_reason)
        assert refused.value.field == "suspend_reason"
    with pytest.raises(ValidationFailed):
        make_tenant(S.ACTIVE, suspend_mode="read-only")
    with pytest.raises(ValidationFailed):
        make_tenant(S.ACTIVE, suspend_reason="contract")


def test_dataclasses_replace_runs_the_checks_again() -> None:
    tenant = make_tenant(S.ACTIVE)
    with pytest.raises(ValidationFailed):
        dataclasses.replace(tenant, status="suspended")
    with pytest.raises(ValidationFailed):
        dataclasses.replace(tenant, status=S.SUSPENDED)
    with pytest.raises(ValidationFailed):
        dataclasses.replace(tenant, epoch=0)


@pytest.mark.parametrize("epoch", [0, -1, True, 1.0, "1", None])
def test_the_epoch_is_a_whole_number_of_at_least_one(epoch: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        make_tenant(epoch=epoch)
    assert refused.value.field == "epoch"


def test_the_epoch_accepts_one_and_more() -> None:
    assert make_tenant(epoch=1).epoch == 1
    assert make_tenant(epoch=500).epoch == 500


@pytest.mark.parametrize("version", [2, -1, 3, True, 1.0, "1", None])
def test_the_hash_key_version_is_zero_or_one(version: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        make_tenant(hash_key_version=version)
    assert refused.value.field == "hash_key_version"


def test_hash_key_version_zero_and_one_are_allowed() -> None:
    assert make_tenant(hash_key_version=0).hash_key_version == 0
    assert make_tenant(hash_key_version=1).hash_key_version == 1


@pytest.mark.parametrize("version", [0, -1, True, 1.0, "1"])
def test_the_current_config_version_is_none_or_at_least_one(version: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        make_tenant(current_config_version=version)
    assert refused.value.field == "current_config_version"
    assert make_tenant(current_config_version=1).current_config_version == 1
    assert make_tenant(current_config_version=None).current_config_version is None


@pytest.mark.parametrize("ods", ["dt4", "AB", "ABCDEFGHI", "A B", "A-B", "AB\n", "ÉAB", 5, ""])
def test_an_ods_code_is_three_to_eight_upper_case_letters_or_digits(ods: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        make_tenant(ods_code=ods)
    assert refused.value.field == "ods_code"


@pytest.mark.parametrize("ods", ["DT4", "R1A", "ABCDEFGH", "12345678", None])
def test_a_good_ods_code_is_kept(ods: str | None) -> None:
    assert make_tenant(ods_code=ods).ods_code == ods


@pytest.mark.parametrize("country", ["gb", "GBR", "G", "", "G1", "GÉ", None, 5])
def test_the_country_code_is_two_upper_case_letters(country: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        make_tenant(country_code=country)
    assert refused.value.field == "country_code"
    assert make_tenant(country_code="IE").country_code == "IE"


REFERENCE_FIELDS = ("dsa_ref", "dpia_ref", "dcb0160_ref")


@pytest.mark.parametrize("field", REFERENCE_FIELDS)
@pytest.mark.parametrize(
    "bad",
    ["DSA{1}", "a" * 81, "a;b", "a\nb", "a'b", "", 5, "<x>", "a,b", "aé"],
    ids=lambda v: repr(v)[:20],
)
def test_a_reference_is_a_short_id_never_free_text(field: str, bad: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        make_tenant(**{field: bad})
    assert refused.value.field == field


@pytest.mark.parametrize("field", REFERENCE_FIELDS)
def test_a_good_reference_is_kept(field: str) -> None:
    for good in ("DSA 2026/001 v2.1:final", "a" * 80, "x-1", "dsa_2026", None):
        assert getattr(make_tenant(**{field: good}), field) == good


# ---------------------------------------------------------------- 4. time zone


def test_the_allow_list_holds_only_europe_london() -> None:
    assert frozenset({"Europe/London"}) == ALLOWED_TIME_ZONES
    assert check_time_zone("Europe/London") == "Europe/London"


@pytest.mark.parametrize(
    "bad",
    ["Europe/Paris", "UTC", "europe/london", "", None, "Europe/London ", " Europe/London", 5, b"x"],
)
def test_check_time_zone_refuses_anything_off_the_allow_list(bad: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_time_zone(bad)
    assert refused.value.field == "time_zone"


def test_check_time_zone_refuses_a_str_subclass() -> None:
    with pytest.raises(ValidationFailed):
        check_time_zone(_TextSubclass("Europe/London"))


def test_a_tenant_refuses_a_zone_off_the_allow_list() -> None:
    with pytest.raises(ValidationFailed) as refused:
        make_tenant(time_zone="UTC")
    assert refused.value.field == "time_zone"


def test_a_name_on_the_list_that_the_zone_database_cannot_load_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An allow-list, not "any name zoneinfo can load", and also a name zoneinfo can load.
    monkeypatch.setattr(tenant_module, "ALLOWED_TIME_ZONES", frozenset({"Not/AZone"}))
    with pytest.raises(ValidationFailed) as refused:
        check_time_zone("Not/AZone")
    assert refused.value.field == "time_zone"
    monkeypatch.setattr(tenant_module, "ALLOWED_TIME_ZONES", frozenset({"../etc/passwd"}))
    with pytest.raises(ValidationFailed):
        check_time_zone("../etc/passwd")


# ---------------------------------------------------------------- 5. names

NAME_FIELDS = ("display_name", "legal_name")


@pytest.mark.parametrize("field", NAME_FIELDS)
@pytest.mark.parametrize(
    "bad",
    ["", "a" * 121, "Mrs Smith", "Dr. Jones", "DT4 8XX", "943 476 5919", "a\nb", "a\x00b", None, 5],
    ids=lambda v: repr(v)[:20],
)
def test_a_name_is_refused(field: str, bad: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        make_tenant(**{field: bad})
    assert refused.value.field == field


@pytest.mark.parametrize("field", NAME_FIELDS)
def test_a_name_of_one_to_120_characters_is_kept(field: str) -> None:
    for good in ("A", "a" * 120, "Example Health Care NHS Foundation Trust & Partners (East)"):
        assert getattr(make_tenant(**{field: good}), field) == good


def test_a_name_that_is_not_exactly_text_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        make_tenant(display_name=_TextSubclass("Example"))


# ---------------------------------------------------------------- 6. contacts


def test_a_phone_contact_is_a_telephone_number() -> None:
    for kind in (ContactKind.COORDINATION_PHONE, ContactKind.SHIFT_LEAD_ESCALATION):
        for good in ("01305 000000", "+44 1305 000000", "0300 123 4567", "0200000"):
            assert TenantContact(kind, "Switchboard", good).value == good


def test_an_email_contact_is_an_address() -> None:
    for kind in (ContactKind.SUPPORT_EMAIL, ContactKind.CLINICAL_SAFETY_OFFICER):
        assert TenantContact(kind, "Team", "capacity-support@example.org").kind is kind


@pytest.mark.parametrize(
    "value",
    [
        "call me",
        "0300 123 4567 {x}",
        "943 476 5919",
        "9434765919",
        "12345",
        "+",
        "0130 5000 000 0000 0000 000",
        "01305-000000",
        "01305 000000\n",
        "",
        "capacity-support@example.org",
    ],
)
def test_a_phone_contact_refuses(value: str) -> None:
    for kind in (ContactKind.COORDINATION_PHONE, ContactKind.SHIFT_LEAD_ESCALATION):
        with pytest.raises(ValidationFailed) as refused:
            TenantContact(kind, "Switchboard", value)
        assert refused.value.field == "value"


@pytest.mark.parametrize(
    "value",
    [
        "no-dot@example",
        "a@b",
        "@example.org",
        "a b@example.org",
        "a@b.c\n",
        "a@@b.c",
        "01305 000000",
        "a{b}@example.org",
        "a<b>@example.org",
        "a\x00@example.org",
        "a" * 250 + "@example.org",
        "",
    ],
)
def test_an_email_contact_refuses(value: str) -> None:
    for kind in (ContactKind.SUPPORT_EMAIL, ContactKind.CLINICAL_SAFETY_OFFICER):
        with pytest.raises(ValidationFailed) as refused:
            TenantContact(kind, "Team", value)
        assert refused.value.field == "value"


@pytest.mark.parametrize(
    "label",
    ["", "a" * 61, "Mrs Smith", "DT4 8XX", "a{b}", "a<b>", "a}b", "a>b", "a\nb", "a\x7fb", None, 5],
    ids=lambda v: repr(v)[:20],
)
def test_a_contact_label_is_refused(label: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        TenantContact(ContactKind.COORDINATION_PHONE, label, "01305 000000")
    assert refused.value.field == "label"


def test_a_contact_label_of_one_to_60_characters_is_kept() -> None:
    for label in ("A", "a" * 60, "Urgent care coordination desk"):
        assert TenantContact(ContactKind.COORDINATION_PHONE, label, "01305 000000").label == label


def test_a_contact_value_that_is_not_text_is_refused() -> None:
    for bad in (None, 5, _TextSubclass("01305 000000")):
        with pytest.raises(ValidationFailed) as refused:
            TenantContact(ContactKind.COORDINATION_PHONE, "Desk", bad)  # type: ignore[arg-type]
        assert refused.value.field == "value"


def test_a_contact_kind_is_checked_by_type() -> None:
    for bad in ("coordination-phone", None, SuspendMode.BLOCKED):
        with pytest.raises(ValidationFailed) as refused:
            TenantContact(bad, "Desk", "01305 000000")  # type: ignore[arg-type]
        assert refused.value.field == "kind"


def test_a_contact_is_frozen() -> None:
    contact = TenantContact(ContactKind.COORDINATION_PHONE, "Desk", "01305 000000")
    with pytest.raises(dataclasses.FrozenInstanceError):
        contact.value = "x"  # type: ignore[misc]


def test_a_contact_refusal_names_no_value() -> None:
    for kind, label, value in (
        (ContactKind.COORDINATION_PHONE, "Desk", CANARY),
        (ContactKind.SUPPORT_EMAIL, "Desk", CANARY + "{@example.org"),
        (ContactKind.SUPPORT_EMAIL, CANARY + " Mrs Smith", "a@example.org"),
    ):
        with pytest.raises(ValidationFailed) as refused:
            TenantContact(kind, label, value)
        assert "canary" not in str(refused.value)


# ---------------------------------------------------------------- 7. wording

WORDING_FIELDS = (
    ("system_name", 60),
    ("referral_system_name", 40),
    ("coordination_team_name", 60),
)


def _wording(**overrides: str) -> TenantWording:
    values = {
        "system_name": SAMPLE_WORDING["systemName"],
        "referral_system_name": SAMPLE_WORDING["referralSystemName"],
        "coordination_team_name": SAMPLE_WORDING["coordinationTeamName"],
    }
    values.update(overrides)
    return TenantWording(**values)


def test_wording_accepts_the_three_sample_values() -> None:
    wording = _wording()
    assert wording.system_name == "Dorset urgent care capacity"
    assert wording.referral_system_name == "SystmOne"
    assert wording.coordination_team_name == "The SPOA shift lead"
    assert [f.name for f in dataclasses.fields(TenantWording)] == [f for f, _ in WORDING_FIELDS]


@pytest.mark.parametrize(("field", "limit"), WORDING_FIELDS)
@pytest.mark.parametrize(
    "bad",
    ["", " x", "x ", "a  b", "a/b", "a{b}", "<b>", "DT4 8XX", "1234567890", "Mrs Smith"],
)
def test_wording_refuses(field: str, limit: int, bad: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _wording(**{field: bad})
    assert refused.value.field == field


@pytest.mark.parametrize(("field", "limit"), WORDING_FIELDS)
def test_wording_has_a_length_limit_per_field(field: str, limit: int) -> None:
    assert getattr(_wording(**{field: "a" * limit}), field) == "a" * limit
    with pytest.raises(ValidationFailed):
        _wording(**{field: "a" * (limit + 1)})


def test_wording_is_frozen_and_needs_all_three() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _wording().system_name = "x"  # type: ignore[misc]
    with pytest.raises(TypeError):
        TenantWording(system_name="x")  # type: ignore[call-arg]


# ---------------------------------------------------------------- 8. configuration versions


def _config(**overrides: Any) -> TenantConfig:
    fields: dict[str, Any] = {
        "version": 1,
        "status": ConfigStatus.DRAFT,
        "values": {},
        "created_at": T0,
        "created_by_ref": "operator-1",
    }
    fields.update(overrides)
    return TenantConfig(**fields)


def test_the_config_fields_are_in_order_with_their_defaults() -> None:
    assert [f.name for f in dataclasses.fields(TenantConfig)] == [
        "version",
        "status",
        "values",
        "created_at",
        "created_by_ref",
        "effective_from",
        "approved_by_refs",
        "reason_code",
    ]
    config = _config()
    assert config.effective_from is None
    assert config.approved_by_refs == ()
    assert config.reason_code == ""


def test_config_values_are_stored_read_only_and_copied() -> None:
    source: dict[str, Any] = {"replyWindowMinutes": 20}
    config = _config(values=source)
    with pytest.raises(TypeError):
        config.values["x"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        del config.values["replyWindowMinutes"]  # type: ignore[attr-defined]
    source["replyWindowMinutes"] = 25
    assert config.values["replyWindowMinutes"] == 20
    assert dict(config.values) == {"replyWindowMinutes": 20}


def test_a_current_version_needs_an_aware_effective_from() -> None:
    with pytest.raises(ValidationFailed) as refused:
        _config(status=ConfigStatus.CURRENT)
    assert refused.value.field == "effective_from"
    with pytest.raises(ValidationFailed):
        _config(status=ConfigStatus.CURRENT, effective_from=datetime(2026, 1, 6))
    current = _config(status=ConfigStatus.CURRENT, effective_from=T0)
    assert current.effective_from == T0


def test_effective_from_may_be_absent_for_the_other_statuses_but_never_naive() -> None:
    for status in (ConfigStatus.DRAFT, ConfigStatus.PENDING_APPROVAL, ConfigStatus.SUPERSEDED):
        assert _config(status=status).effective_from is None
        assert _config(status=status, effective_from=T0).effective_from == T0
        with pytest.raises(ValidationFailed):
            _config(status=status, effective_from=datetime(2026, 1, 6))


def test_the_policy_of_a_config_with_no_overrides_is_the_default_policy() -> None:
    assert _config().policy == DEFAULT_POLICY


def test_the_policy_of_a_config_applies_its_overrides() -> None:
    config = _config(values={"replyWindowMinutes": 20, "reminderAfterMinutes": 25})
    assert config.policy == policy_from_settings(dict(config.values))
    assert config.policy.reply_window == timedelta(minutes=20)


def test_wording_is_none_unless_all_three_wording_keys_are_set() -> None:
    assert _config().wording is None
    for missing in SAMPLE_WORDING:
        partial = {k: v for k, v in SAMPLE_WORDING.items() if k != missing}
        assert _config(values=partial).wording is None
    assert _config(values={"replyWindowMinutes": 20}).wording is None
    full = _config(values=dict(SAMPLE_WORDING))
    assert full.wording == _wording()
    assert full.policy == DEFAULT_POLICY


def test_a_config_refuses_an_unknown_or_out_of_bounds_value() -> None:
    for values in (
        {"replyWindowMinute": 20},
        {"replyWindowMinutes": 61},
        {"replyWindowMinutes": 60},
        {"systemName": "a/b"},
        {CANARY: 1},
    ):
        with pytest.raises(ValidationFailed) as refused:
            _config(values=values)
        assert "canary" not in str(refused.value)


@pytest.mark.parametrize("values", [None, [("replyWindowMinutes", 20)], "x", 5])
def test_config_values_must_be_a_mapping(values: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _config(values=values)
    assert refused.value.field in {"values", "key"}


@pytest.mark.parametrize("version", [0, -1, True, 1.0, "1", None])
def test_a_config_version_is_a_whole_number_of_at_least_one(version: Any) -> None:
    with pytest.raises(ValidationFailed) as refused:
        _config(version=version)
    assert refused.value.field == "version"


def test_a_config_status_is_checked_by_type() -> None:
    for bad in ("draft", TenantStatus.ACTIVE, None):
        with pytest.raises(ValidationFailed) as refused:
            _config(status=bad)
        assert refused.value.field == "status"


def test_a_config_needs_an_aware_creation_time_and_a_named_author() -> None:
    with pytest.raises(ValidationFailed):
        _config(created_at=datetime(2026, 1, 5))
    for bad in ("", " ", None, 5, "a" * 81, "a{b}", "a;b"):
        with pytest.raises(ValidationFailed) as refused:
            _config(created_by_ref=bad)
        assert refused.value.field == "created_by_ref"


def test_approvals_are_a_tuple_of_distinct_named_refs() -> None:
    assert _config(approved_by_refs=("a-1", "b-2")).approved_by_refs == ("a-1", "b-2")
    for bad in (["a-1"], {"a-1"}, "a-1", ("a-1", "a-1"), ("",), (5,), ("a{b}",), None):
        with pytest.raises(ValidationFailed) as refused:
            _config(approved_by_refs=bad)
        assert refused.value.field == "approved_by_refs"


def test_a_reason_code_is_short_letters_digits_and_hyphens() -> None:
    for good in ("", "ref-123", "a" * 40, "A-b-9"):
        assert _config(reason_code=good).reason_code == good
    for bad in ("a" * 41, "bad code!", "a_b", "a\nb", None, 5, "café"):
        with pytest.raises(ValidationFailed) as refused:
            _config(reason_code=bad)
        assert refused.value.field == "reason_code"


def test_a_config_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _config().version = 2  # type: ignore[misc]


def test_two_configs_with_equal_content_are_equal() -> None:
    assert _config(values={"staleWarningHours": 3}) == _config(values={"staleWarningHours": 3})
    assert _config(values={"staleWarningHours": 3}) != _config(values={"staleWarningHours": 4})


# ---------------------------------------------------------------- the sources carry no place names


def test_no_tenant_source_file_names_the_original_deployment() -> None:
    root = Path(__file__).resolve().parents[4] / "src" / "diucs" / "domain"
    files = sorted([*root.glob("model/tenant*.py"), *root.glob("rules/tenant_*.py")])
    # A glob that matched nothing would make the search below vacuous.
    assert {f.name for f in files} == {
        "tenant.py",
        "tenant_policy.py",
        "tenant_records.py",
        "tenant_lifecycle.py",
        "tenant_settings.py",
        "tenant_keys.py",
    }
    pattern = re.compile("dorset|spoa|systmone", re.IGNORECASE)
    for file in files:
        assert pattern.search(file.read_text(encoding="utf-8")) is None, file.name
