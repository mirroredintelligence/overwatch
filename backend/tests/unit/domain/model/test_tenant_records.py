"""A tenant's channels, retention rules, directory binding and role mappings (TEN-026).

Rules: audit F section 2.3 (the records), DEC-131 (secrets are references), DEC-136 item 10
(retention is set before activation), DEC-155 (fail closed: an enum is checked by exact type,
lessons L3 and L38; no refusal repeats a value). Every value is invented. The retention defaults
are [ASSUMED] (DEC-271) and pinned here, so a change is a decision and not an edit.
"""

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import NumberStatus, RetentionClass
from diucs.domain.model.tenant_records import (
    ENTRA_MAPPABLE_ROLES,
    KEPT_UNTIL_PURGE,
    MAX_KEEP_DAYS,
    BindingStatus,
    ChannelKind,
    ChannelProvider,
    EntraBinding,
    MappingStatus,
    RetentionAction,
    RoleMapping,
    TenantChannel,
    TenantRetention,
    default_retention,
)

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
SID = "AC" + "0" * 32
GUID = "11111111-2222-3333-4444-555555555555"
OTHER_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

# ---------------------------------------------------------------- channels


def sms(**changes: Any) -> TenantChannel:
    fields: dict[str, Any] = {
        "id": "ch-sms-1",
        "kind": ChannelKind.SMS,
        "provider": ChannelProvider.TWILIO,
        "status": NumberStatus.ACTIVE,
        "sender_label": "Example capacity",
        "account_sid": SID,
        "secret_ref": "twilio/example-icb/auth-token",
    }
    fields.update(changes)
    return TenantChannel(**fields)


def email(**changes: Any) -> TenantChannel:
    fields: dict[str, Any] = {
        "id": "ch-mail-1",
        "kind": ChannelKind.EMAIL,
        "provider": ChannelProvider.SMTP,
        "status": NumberStatus.ACTIVE,
        "sender_label": "Example capacity",
        "from_address": "capacity@example.test",
        "from_display_name": "Example capacity",
    }
    fields.update(changes)
    return TenantChannel(**fields)


def test_a_text_channel_names_a_twilio_account_and_the_reference_of_its_token() -> None:
    channel = sms()

    assert channel.account_sid == SID
    assert channel.secret_ref == "twilio/example-icb/auth-token"
    assert channel.from_address is None


def test_an_email_channel_names_a_sender_address() -> None:
    channel = email()

    assert channel.from_address == "capacity@example.test"
    assert channel.secret_ref is None
    assert channel.account_sid is None


def test_an_email_channel_may_hold_the_reference_of_its_smtp_secret() -> None:
    assert email(secret_ref="smtp/example-icb/password").secret_ref == "smtp/example-icb/password"


def test_the_provider_must_be_the_one_the_kind_uses() -> None:
    with pytest.raises(ValidationFailed):
        sms(provider=ChannelProvider.SMTP)
    with pytest.raises(ValidationFailed):
        email(provider=ChannelProvider.TWILIO)


@pytest.mark.parametrize(
    "changes",
    [
        {"account_sid": None},
        {"secret_ref": None},
        {"account_sid": "AC123"},
        {"account_sid": "ac" + "0" * 32},
        {"account_sid": "AC" + "G" * 32},
        {"from_address": "capacity@example.test"},
        {"from_display_name": "Example"},
        {"secret_ref": "just-a-name"},
        {"secret_ref": "twilio/example-icb"},
        {"secret_ref": "Twilio/example-icb/auth-token"},
        {"secret_ref": "twilio/example-icb/auth-token/extra"},
        {"secret_ref": "twilio//auth-token"},
        {"secret_ref": "twilio/example-icb/"},
        {"secret_ref": "twilio/Example/auth-token"},
        {"secret_ref": " twilio/example-icb/auth-token"},
    ],
)
def test_a_text_channel_that_breaks_a_rule_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed):
        sms(**changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"from_address": None},
        {"from_address": "no-at-sign"},
        {"from_address": "a@b"},
        {"from_address": "two@@example.test"},
        {"from_address": "a b@example.test"},
        {"from_address": "x" * 250 + "@example.test"},
        {"account_sid": SID},
        {"from_display_name": "<script>"},
        {"secret_ref": "bad ref"},
    ],
)
def test_an_email_channel_that_breaks_a_rule_is_refused(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed):
        email(**changes)


@pytest.mark.parametrize(
    "label",
    ["", "  ", "Mrs Smith", "DT4 8XX", "943 476 5919", "<b>x</b>", "{system}", "a" * 41, "a\nb"],
)
def test_a_sender_label_that_is_empty_markup_or_patient_shaped_is_refused(label: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        sms(sender_label=label)

    assert label.strip() not in str(refused.value) or label.strip() == ""


@pytest.mark.parametrize("bad", ["", "a b", "x" * 65, "-x", "a/b"])
def test_a_channel_id_must_be_a_short_plain_id(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        sms(id=bad)


def test_the_status_kind_and_provider_are_checked_by_exact_type() -> None:
    for bad_status in ("active", BindingStatus.PENDING, MappingStatus.ACTIVE, None):
        with pytest.raises(ValidationFailed):
            sms(status=bad_status)
    with pytest.raises(ValidationFailed):
        sms(kind="sms")
    with pytest.raises(ValidationFailed):
        sms(provider="twilio")


def test_a_channel_is_frozen_and_replace_runs_the_checks_again() -> None:
    channel = sms()

    with pytest.raises(dataclasses.FrozenInstanceError):
        channel.status = NumberStatus.RETIRED  # type: ignore[misc]
    with pytest.raises(ValidationFailed):
        dataclasses.replace(channel, account_sid=None)
    retired = dataclasses.replace(channel, status=NumberStatus.RETIRED)
    assert retired.status is NumberStatus.RETIRED


def test_no_channel_field_can_hold_a_token() -> None:
    names = {field.name for field in dataclasses.fields(TenantChannel)}

    assert not {"auth_token", "token", "password", "secret"} & names
    assert "secret_ref" in names


# ---------------------------------------------------------------- retention


def test_the_two_safety_classes_are_kept_until_purge() -> None:
    assert (
        frozenset({RetentionClass.AUDIT_CHAIN, RetentionClass.SAFETY_CONCERNS}) == KEPT_UNTIL_PURGE
    )


def test_a_keep_rule_has_no_days_and_only_the_kept_classes_may_have_one() -> None:
    for data_class in KEPT_UNTIL_PURGE:
        rule = TenantRetention(data_class, None, RetentionAction.KEEP)
        assert rule.keep_days is None
    with pytest.raises(ValidationFailed):
        TenantRetention(RetentionClass.BOOKINGS, None, RetentionAction.KEEP)


@pytest.mark.parametrize("data_class", sorted(KEPT_UNTIL_PURGE))
def test_a_kept_class_may_not_be_given_a_deletion(data_class: RetentionClass) -> None:
    with pytest.raises(ValidationFailed):
        TenantRetention(data_class, 365, RetentionAction.DELETE)
    with pytest.raises(ValidationFailed):
        TenantRetention(data_class, 365, RetentionAction.SUMMARISE)
    with pytest.raises(ValidationFailed):
        TenantRetention(data_class, 365, RetentionAction.KEEP)


@pytest.mark.parametrize("days", [0, -1, MAX_KEEP_DAYS + 1, True, 1.5, "30", None])
def test_a_deletion_needs_a_whole_number_of_days_in_range(days: object) -> None:
    with pytest.raises(ValidationFailed):
        TenantRetention(RetentionClass.COMMUNICATIONS, days, RetentionAction.DELETE)  # type: ignore[arg-type]


@pytest.mark.parametrize("days", [1, 90, 730, MAX_KEEP_DAYS])
def test_a_deletion_or_summary_accepts_a_day_count_in_range(days: int) -> None:
    for action in (RetentionAction.DELETE, RetentionAction.SUMMARISE):
        assert TenantRetention(RetentionClass.COMMUNICATIONS, days, action).keep_days == days


def test_the_largest_keep_period_is_ten_years() -> None:
    assert MAX_KEEP_DAYS == 3650


def test_the_data_class_and_the_action_are_checked_by_exact_type() -> None:
    with pytest.raises(ValidationFailed):
        TenantRetention("bookings", 30, RetentionAction.DELETE)  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        TenantRetention(RetentionClass.BOOKINGS, 30, "delete")  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        TenantRetention(RetentionClass.BOOKINGS, 30, BindingStatus.PENDING)  # type: ignore[arg-type]


def test_the_defaults_cover_every_class_once_in_declaration_order() -> None:
    rules = default_retention()

    assert [rule.data_class for rule in rules] == list(RetentionClass)


def test_the_defaults_are_the_assumed_schedule() -> None:
    """[ASSUMED] (DEC-271): the audit chain and the safety concerns are kept until purge; the
    postcode and needs of a case are cleared at close by the rule book whatever the case-audit
    row says; communications metadata two years; raw telemetry 90 days and aggregates two years."""
    by_class = {rule.data_class: (rule.keep_days, rule.action) for rule in default_retention()}

    assert by_class == {
        RetentionClass.CAPACITY_REPORTS: (730, RetentionAction.SUMMARISE),
        RetentionClass.BOOKINGS: (730, RetentionAction.DELETE),
        RetentionClass.CASE_AUDIT: (2555, RetentionAction.DELETE),
        RetentionClass.COMMUNICATIONS: (730, RetentionAction.DELETE),
        RetentionClass.TELEMETRY_RAW: (90, RetentionAction.DELETE),
        RetentionClass.TELEMETRY_AGGREGATES: (730, RetentionAction.DELETE),
        RetentionClass.AUDIT_CHAIN: (None, RetentionAction.KEEP),
        RetentionClass.SAFETY_CONCERNS: (None, RetentionAction.KEEP),
    }


def test_the_defaults_return_a_new_tuple_of_frozen_rules_each_time() -> None:
    first, second = default_retention(), default_retention()

    assert first == second
    assert isinstance(first, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        first[0].keep_days = 1  # type: ignore[misc]


# ---------------------------------------------------------------- directory binding


def test_a_pending_binding_has_no_verifier() -> None:
    binding = EntraBinding(GUID, BindingStatus.PENDING)

    assert binding.verified_at is None
    assert binding.verified_by_ref is None


def test_a_verified_binding_names_when_and_by_whom() -> None:
    binding = EntraBinding(GUID, BindingStatus.VERIFIED, T0, "operator-1")

    assert (binding.verified_at, binding.verified_by_ref) == (T0, "operator-1")


@pytest.mark.parametrize(
    "args",
    [
        (GUID, BindingStatus.VERIFIED, None, "operator-1"),
        (GUID, BindingStatus.VERIFIED, T0, None),
        (GUID, BindingStatus.VERIFIED, None, None),
        (GUID, BindingStatus.PENDING, T0, None),
        (GUID, BindingStatus.PENDING, None, "operator-1"),
        (GUID, BindingStatus.REVOKED, T0, "operator-1"),
        (GUID, BindingStatus.VERIFIED, datetime(2026, 10, 29, 9, 0), "operator-1"),
        (GUID, BindingStatus.VERIFIED, T0, "bad ref!"),
        (GUID, BindingStatus.VERIFIED, T0, ""),
    ],
)
def test_a_binding_whose_status_and_verifier_disagree_is_refused(args: tuple[Any, ...]) -> None:
    with pytest.raises(ValidationFailed):
        EntraBinding(*args)


@pytest.mark.parametrize(
    "directory",
    [
        "",
        "not-a-guid",
        GUID.upper(),
        GUID + "0",
        GUID[:-1],
        "11111111-2222-3333-4444-55555555555g",
        "11111111222233334444555555555555",
        " " + GUID,
        5,
        None,
    ],
)
def test_a_directory_id_must_be_a_lower_case_guid(directory: object) -> None:
    with pytest.raises(ValidationFailed):
        EntraBinding(directory, BindingStatus.PENDING)  # type: ignore[arg-type]


def test_a_binding_status_is_checked_by_exact_type() -> None:
    for bad in ("pending", MappingStatus.ACTIVE, None):
        with pytest.raises(ValidationFailed):
            EntraBinding(GUID, bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------- role mappings


def test_the_roles_a_group_may_map_to_are_the_staff_roles() -> None:
    assert (
        frozenset({Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.OWNER, Role.EXEC, Role.AUDIT})
        == ENTRA_MAPPABLE_ROLES
    )


@pytest.mark.parametrize("role", sorted(ENTRA_MAPPABLE_ROLES))
def test_a_group_maps_to_a_staff_role(role: Role) -> None:
    assert RoleMapping(GUID, role, MappingStatus.ACTIVE).role is role


@pytest.mark.parametrize(
    "role", [Role.REPORTER, Role.WALL, Role.ANONYMOUS_LINK, Role.SUPPORT, "advisor", None]
)
def test_a_group_may_not_map_to_a_role_that_does_not_come_from_the_directory(
    role: object,
) -> None:
    with pytest.raises(ValidationFailed):
        RoleMapping(GUID, role, MappingStatus.ACTIVE)  # type: ignore[arg-type]


def test_a_mapping_checks_its_group_id_and_its_status() -> None:
    with pytest.raises(ValidationFailed):
        RoleMapping("not-a-guid", Role.LEAD, MappingStatus.ACTIVE)
    with pytest.raises(ValidationFailed):
        RoleMapping(GUID, Role.LEAD, "active")  # type: ignore[arg-type]
    with pytest.raises(ValidationFailed):
        RoleMapping(GUID, Role.LEAD, BindingStatus.PENDING)  # type: ignore[arg-type]
    assert RoleMapping(OTHER_GUID, Role.LEAD, MappingStatus.RETIRED).status is MappingStatus.RETIRED


def test_the_enums_do_not_share_members() -> None:
    assert {s.value for s in MappingStatus} == {"active", "retired"}
    assert {s.value for s in BindingStatus} == {"pending", "verified", "revoked"}
    assert {a.value for a in RetentionAction} == {"delete", "summarise", "keep"}
    assert {k.value for k in ChannelKind} == {"sms", "email"}
    assert {p.value for p in ChannelProvider} == {"twilio", "smtp"}
