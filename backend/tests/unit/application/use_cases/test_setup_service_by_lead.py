"""Unit tests for SetupServiceByLead (U15): the pure rules the use case applies before it writes.

The flow (what is stored, read back from Neo4j) is tested in
tests/integration/application/test_setup_service_by_lead.py. Sample values only; no patient data.
"""

import dataclasses
from datetime import UTC, date, datetime, time

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.setup_service_by_lead import (
    ReporterContact,
    SetupServiceCommand,
    build_criteria,
    build_profile,
    check_may_set_up,
    check_role_name,
    command_fingerprint,
    first_prompt_at,
    international,
    reporter_contact,
    setup_snapshot,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    ReferrerType,
    Role,
    ServiceCategory,
)
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.service import AvailableTime

NOW = datetime(2026, 10, 29, 9, 10, tzinfo=UTC)  # London is on GMT: local time equals UTC

LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)

BASE = SetupServiceCommand(
    idempotency_key="setup-ucr-west-1",
    actor=LEAD,
    name="UCR West",
    category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
    measure=Measure.REFERRALS_ACCEPTABLE,
    unit_label="referrals",
    established_capacity=8,
    usual_range=(0, 8),
    cadence=Cadence.EVERY_2_HRS,
    available_times=(AvailableTime.every_day(time(8, 0), time(20, 0)),),
    channel=Channel.TEXT,
    reporter_role_name="Duty manager",
    age_min=18,
    districts=frozenset({"DT1", "DT2", "DT3", "DT4"}),
    accepts=frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY}),
    review_by=date(2027, 1, 31),
    owner_role_name="Shift lead",
    phone="07700 900123",
)


def _with(**changes: object) -> SetupServiceCommand:
    return dataclasses.replace(BASE, **changes)  # type: ignore[arg-type]


# Who may set up a service.


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.LEAD])
def test_only_a_shift_lead_may_set_up_a_service(role: Role) -> None:
    with pytest.raises(NotAllowed):
        check_may_set_up(dataclasses.replace(LEAD, role=role))


def test_a_shift_lead_may_set_up_a_service() -> None:
    check_may_set_up(LEAD)


def test_the_lead_must_act_as_a_named_practitioner() -> None:
    with pytest.raises(NotAllowed):
        check_may_set_up(dataclasses.replace(LEAD, practitioner_id=None))


# The reporter's contact: a UK mobile for text, a role inbox for email.


@pytest.mark.parametrize(
    "typed",
    [
        "07700 900123",
        "07700900123",
        "+44 7700 900123",
        "+44 (0)7700 900123",
        "0044 7700 900123",
    ],
)
def test_a_uk_mobile_is_kept_as_eleven_digits_from_any_common_form(typed: str) -> None:
    assert reporter_contact(Channel.TEXT, typed, None).phone == "07700900123"


@pytest.mark.parametrize(
    "typed",
    ["0123", "07700 90012", "07700 9001234", "020 7946 0000", "+44 20 7946 0000", "", "not a number"],
)
def test_a_text_number_that_is_not_a_uk_mobile_is_refused_naming_phone(typed: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        reporter_contact(Channel.TEXT, typed, None)
    assert refused.value.field == "phone"


def test_a_text_channel_without_a_number_is_refused_naming_phone() -> None:
    with pytest.raises(ValidationFailed) as refused:
        reporter_contact(Channel.TEXT, None, None)
    assert refused.value.field == "phone"


def test_the_stored_form_of_a_mobile_is_plus_44_without_the_trunk_zero() -> None:
    assert international("07700900123") == "+447700900123"


def test_a_text_reporter_has_no_email_address() -> None:
    assert reporter_contact(Channel.TEXT, "07700 900123", None) == ReporterContact(
        channel=Channel.TEXT, phone="07700900123", email=None
    )


def test_an_email_reporter_keeps_the_role_inbox_with_a_lower_case_domain() -> None:
    assert reporter_contact(Channel.EMAIL, None, "Rota@NHS.example") == ReporterContact(
        channel=Channel.EMAIL, phone=None, email="Rota@nhs.example"
    )


@pytest.mark.parametrize(
    "address",
    ["", "rota.nhs.example", "rota@", "@nhs.example", "a b@nhs.example", "a@b@nhs.example", "a@localhost"],
)
def test_an_email_reporter_refuses_what_is_not_a_role_inbox(address: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        reporter_contact(Channel.EMAIL, None, address)
    assert refused.value.field == "email"


def test_an_email_channel_without_an_address_is_refused_even_with_a_phone() -> None:
    with pytest.raises(ValidationFailed) as refused:
        reporter_contact(Channel.EMAIL, "07700 900123", None)
    assert refused.value.field == "email"


def test_push_is_outside_the_mvp() -> None:
    with pytest.raises(ValidationFailed) as refused:
        reporter_contact(Channel.PUSH, None, None)
    assert refused.value.field == "channel"


# The service profile.


def test_a_valid_command_builds_an_active_text_service_that_does_not_exceed_its_capacity() -> None:
    profile = build_profile(BASE, "svc-1")
    assert profile.id == "svc-1"
    assert profile.name == "UCR West"
    assert profile.established_capacity == 8
    assert profile.usual_range == (0, 8)
    assert profile.channel is Channel.TEXT
    assert profile.active is True
    assert profile.can_exceed_established is False


@pytest.mark.parametrize("established", [0, -1])
def test_established_capacity_must_be_at_least_one(established: int) -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_profile(_with(established_capacity=established), "svc-1")
    assert refused.value.field == "established_capacity"


def test_established_capacity_of_one_is_the_smallest_valid_value() -> None:
    assert build_profile(_with(established_capacity=1), "svc-1").established_capacity == 1


@pytest.mark.parametrize("usual_range", [(5, 2), (0, -1), (-1, 3)])
def test_the_usual_range_runs_from_zero_or_more_with_the_minimum_first(
    usual_range: tuple[int, int],
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_profile(_with(usual_range=usual_range), "svc-1")
    assert refused.value.field == "usual_range"


@pytest.mark.parametrize("usual_range", [(0, 0), (0, 8), (8, 8)])
def test_a_usual_range_with_equal_or_zero_bounds_is_accepted(usual_range: tuple[int, int]) -> None:
    assert build_profile(_with(usual_range=usual_range), "svc-1").usual_range == usual_range


@pytest.mark.parametrize("field", ["name", "unit_label"])
def test_a_blank_name_or_unit_label_is_refused(field: str) -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_profile(_with(**{field: "   "}), "svc-1")
    assert refused.value.field == field


def test_a_category_must_be_its_own_enum_not_a_string_or_another_enum_with_the_same_value() -> None:
    for bad in ("urgent-community-response", ReferrerType.OTHER):
        with pytest.raises(ValidationFailed) as refused:
            build_profile(_with(category=bad), "svc-1")
        assert refused.value.field == "category"


def test_measure_and_cadence_must_be_their_enums() -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_profile(_with(measure="referrals-acceptable"), "svc-1")
    assert refused.value.field == "measure"
    with pytest.raises(ValidationFailed) as refused:
        build_profile(_with(cadence="every-2-hrs"), "svc-1")
    assert refused.value.field == "cadence"


def test_a_service_needs_at_least_one_available_time() -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_profile(_with(available_times=()), "svc-1")
    assert refused.value.field == "available_times"


# Role names: staff text, never a postcode.


def test_a_role_name_with_a_postcode_is_refused_naming_its_field() -> None:
    with pytest.raises(ValidationFailed) as refused:
        check_role_name("owner_role_name", "Shift lead DT4 8XX")
    assert refused.value.field == "owner_role_name"


def test_a_plain_role_name_is_accepted() -> None:
    check_role_name("owner_role_name", "Shift lead")


# The first criteria version.


def test_criteria_version_one_is_current_and_carries_the_command() -> None:
    criteria = build_criteria(BASE, "crit-1", "svc-1", "role-owner-1")
    assert isinstance(criteria, ServiceCriteria)
    assert criteria.version == 1
    assert criteria.status is CriteriaStatus.CURRENT
    assert criteria.service_id == "svc-1"
    assert criteria.owner_role_id == "role-owner-1"
    assert criteria.age_min == 18
    assert criteria.age_max is None
    assert criteria.accepts == frozenset({NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY})
    assert criteria.excludes == frozenset()
    assert criteria.review_by == date(2027, 1, 31)


def test_districts_are_stored_as_upper_case_outward_codes() -> None:
    criteria = build_criteria(
        _with(districts=frozenset({" dt4 ", "DT1"})), "crit-1", "svc-1", "role-owner-1"
    )
    assert criteria.districts == frozenset({"DT4", "DT1"})


@pytest.mark.parametrize(
    "districts",
    [frozenset(), frozenset({"DT4 8"}), frozenset({"Dorset"}), frozenset({"DT48XX"})],
)
def test_at_least_one_district_code_is_required(districts: frozenset[str]) -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_criteria(_with(districts=districts), "crit-1", "svc-1", "role-owner-1")
    assert refused.value.field == "districts"


@pytest.mark.parametrize(("age_min", "age_max"), [(-1, None), (16, 15)])
def test_the_age_limits_run_from_zero_and_the_maximum_is_not_below_the_minimum(
    age_min: int, age_max: int | None
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_criteria(_with(age_min=age_min, age_max=age_max), "crit-1", "svc-1", "role-owner-1")
    assert refused.value.field in {"age_min", "age_max"}


@pytest.mark.parametrize(("age_min", "age_max"), [(0, None), (16, 16), (16, 64)])
def test_the_smallest_and_equal_age_limits_are_accepted(age_min: int, age_max: int | None) -> None:
    criteria = build_criteria(
        _with(age_min=age_min, age_max=age_max), "crit-1", "svc-1", "role-owner-1"
    )
    assert (criteria.age_min, criteria.age_max) == (age_min, age_max)


def test_at_least_one_accepted_need_is_required() -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_criteria(_with(accepts=frozenset()), "crit-1", "svc-1", "role-owner-1")
    assert refused.value.field == "accepts"


def test_a_need_cannot_be_both_accepted_and_excluded() -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_criteria(
            _with(excludes=frozenset({NeedCategory.FRAILTY})), "crit-1", "svc-1", "role-owner-1"
        )
    assert refused.value.field == "excludes"


def test_needs_must_be_need_categories_not_plain_strings() -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_criteria(_with(accepts=frozenset({"frailty"})), "crit-1", "svc-1", "role-owner-1")
    assert refused.value.field == "accepts"


def test_the_review_date_is_a_calendar_date_not_a_datetime() -> None:
    with pytest.raises(ValidationFailed) as refused:
        build_criteria(
            _with(review_by=datetime(2027, 1, 31, 9, 0, tzinfo=UTC)),
            "crit-1",
            "svc-1",
            "role-owner-1",
        )
    assert refused.value.field == "review_by"


# The first prompt: the next two-hourly slot strictly after now.


def test_the_first_prompt_is_the_next_slot_after_the_set_up_time() -> None:
    profile = build_profile(BASE, "svc-1")
    assert first_prompt_at(profile, NOW) == datetime(2026, 10, 29, 10, 0, tzinfo=UTC)


def test_a_slot_due_exactly_now_is_not_the_first_prompt() -> None:
    profile = build_profile(BASE, "svc-1")
    assert first_prompt_at(profile, datetime(2026, 10, 29, 10, 0, tzinfo=UTC)) == datetime(
        2026, 10, 29, 12, 0, tzinfo=UTC
    )


def test_after_the_last_slot_of_the_day_the_first_prompt_is_the_next_morning() -> None:
    profile = build_profile(BASE, "svc-1")
    assert first_prompt_at(profile, datetime(2026, 10, 29, 20, 0, tzinfo=UTC)) == datetime(
        2026, 10, 30, 8, 0, tzinfo=UTC
    )


def test_one_minute_before_the_first_slot_the_first_prompt_is_that_slot() -> None:
    profile = build_profile(BASE, "svc-1")
    assert first_prompt_at(profile, datetime(2026, 10, 29, 7, 59, tzinfo=UTC)) == datetime(
        2026, 10, 29, 8, 0, tzinfo=UTC
    )


# Replay and audit.


def test_the_same_command_has_the_same_fingerprint() -> None:
    assert command_fingerprint(BASE, "key-1") == command_fingerprint(BASE, "key-1")


@pytest.mark.parametrize(
    "changed",
    [
        _with(name="UCR East"),
        _with(established_capacity=9),
        dataclasses.replace(BASE, actor=dataclasses.replace(LEAD, practitioner_id="prac-lead-2")),
    ],
)
def test_a_different_body_or_actor_has_a_different_fingerprint(changed: SetupServiceCommand) -> None:
    assert command_fingerprint(changed, "key-1") != command_fingerprint(BASE, "key-1")


def test_a_different_contact_key_has_a_different_fingerprint() -> None:
    assert command_fingerprint(BASE, "key-1") != command_fingerprint(BASE, "key-2")


def test_the_audit_snapshot_holds_no_phone_number_and_no_email() -> None:
    snapshot = setup_snapshot(
        BASE,
        service_id="svc-1",
        practitioner_id="prac-1",
        role_id="role-1",
        owner_role_id="role-owner-1",
        criteria_id="crit-1",
        first_prompt=datetime(2026, 10, 29, 10, 0, tzinfo=UTC),
    )
    text = repr(snapshot)
    assert "07700" not in text
    assert "+44" not in text
    assert "phone" not in snapshot
    assert "email" not in snapshot
    assert snapshot["service_id"] == "svc-1"
    assert snapshot["criteria_version"] == 1
    assert snapshot["reporter_role_name"] == "Duty manager"
    assert snapshot["owner_role_name"] == "Shift lead"
