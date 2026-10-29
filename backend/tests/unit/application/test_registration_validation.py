"""Validation of the registration wizard's five steps (U26) and the draft's typed encoding. Pure:
no Neo4j. The wording of the messages named in the prompt is pinned exactly."""

from dataclasses import replace
from datetime import date

import pytest

from diucs.application.use_cases.registration_draft import (
    ApiStep,
    FieldError,
    LocationStep,
    OrganisationStep,
    ReportingStep,
    ServiceStep,
    decode_step,
    encode_step,
    is_full_uk_phone,
    validate_step,
)

ORG = OrganisationStep(
    name="Community Response Ltd",
    ods_code="RXX01",
    org_type="nhs-trust",
    contact_name="Sam Patel",
    contact_email="sam.patel@example.org",
)
SITE = LocationStep(
    fixed_site=True,
    postcode="DT4 8XX",
    address="1 Sample Road, Weymouth",
    site_name="Sample Ward",
    site_type="ward",
    open_24h=True,
)
SERVICE = ServiceStep(
    service_name="UCR West",
    category="urgent-community-response",
    referral_methods="phone,e-referral",
    spoa_phone="01305 123456",
    accepting_days="mon,tue,wed,thu,fri",
    accepting_start="08:00",
    accepting_end="20:00",
    needs="frailty,wound-care",
    age_min=18,
    age_max=None,
    no_age_limit=True,
    excluded_needs="",
    no_exclusions=True,
    owner_role="Clinical lead, UCR",
    owner_email="owner@example.org",
    review_by=date(2027, 1, 1),
    districts="DT4",
)
REPORTING = ReportingStep(
    measure="referrals-acceptable",
    usual_low=0,
    usual_high=8,
    cadence="every-2-hrs",
    channel="text",
    holder_name="Duty coordinator",
    contact_mobile="07700 900123",
)
API = ApiStep(wanted=False)


def _messages(errors: list[FieldError]) -> list[tuple[str, str]]:
    return [(error.field, error.message) for error in errors]


def test_the_complete_sample_steps_have_no_errors() -> None:
    assert validate_step(ORG) == []
    assert validate_step(SITE) == []
    assert validate_step(SERVICE, fixed_site=True) == []
    assert validate_step(REPORTING) == []
    assert validate_step(API) == []


# --- organisation ------------------------------------------------------------------------------


def test_an_organisation_needs_a_name_an_ods_code_a_type_and_a_contact_name() -> None:
    errors = validate_step(replace(ORG, name="", ods_code="", org_type="", contact_name=""))
    assert {error.field for error in errors} == {"name", "ods_code", "org_type", "contact_name"}


def test_an_organisation_needs_a_contact_email_or_a_phone() -> None:
    errors = validate_step(replace(ORG, contact_email="", contact_phone=""))
    assert [error.field for error in errors] == ["contact"]


def test_an_organisation_type_outside_the_five_listed_is_refused() -> None:
    assert [e.field for e in validate_step(replace(ORG, org_type="charity"))] == ["org_type"]


def test_an_organisation_phone_must_be_a_full_uk_number_when_given() -> None:
    errors = validate_step(replace(ORG, contact_email="", contact_phone="0123"))
    assert _messages(errors) == [
        ("contact_phone", "Enter a full phone number, for example 01305 123456")
    ]


# --- location ----------------------------------------------------------------------------------


def test_a_fixed_site_needs_a_postcode_address_site_name_and_type() -> None:
    errors = validate_step(replace(SITE, fixed_site=True, postcode="", address="", site_name=""))
    assert {e.field for e in errors} >= {"postcode", "address", "site_name"}


def test_a_fixed_site_with_a_bad_postcode_is_refused() -> None:
    assert [e.field for e in validate_step(replace(SITE, postcode="DT4"))] == ["postcode"]


def test_a_site_needs_opening_days_and_times_or_twenty_four_hours() -> None:
    errors = validate_step(replace(SITE, open_24h=False, opening_days="", opening_start=""))
    assert [e.field for e in errors] == ["opening"]


def test_a_site_type_outside_the_listed_five_is_refused() -> None:
    assert [e.field for e in validate_step(replace(SITE, site_type="shed"))] == ["site_type"]


def test_opening_hours_that_end_before_they_start_are_refused() -> None:
    errors = validate_step(
        replace(
            SITE, open_24h=False, opening_days="mon", opening_start="20:00", opening_end="08:00"
        )
    )
    assert [e.field for e in errors] == ["opening"]


# --- service -----------------------------------------------------------------------------------


def test_a_service_with_no_category_and_a_short_phone_gives_the_two_screen_messages() -> None:
    errors = validate_step(replace(SERVICE, category="", spoa_phone="0123"), fixed_site=True)
    assert _messages(errors) == [
        ("category", "Choose a category"),
        ("spoa_phone", "Enter a full phone number, for example 01305 123456"),
    ]


def test_a_blank_spoa_phone_asks_for_a_number_the_spoa_can_call() -> None:
    errors = validate_step(replace(SERVICE, spoa_phone=""), fixed_site=True)
    assert _messages(errors) == [("spoa_phone", "Enter a phone number the SPOA can call")]


def test_a_visiting_service_with_no_districts_needs_at_least_one() -> None:
    errors = validate_step(replace(SERVICE, districts=""), fixed_site=False)
    assert [e.field for e in errors] == ["districts"]


def test_a_service_with_a_fixed_site_does_not_need_districts() -> None:
    assert validate_step(replace(SERVICE, districts=""), fixed_site=True) == []


def test_districts_must_be_district_codes_as_written_by_the_postcode_rules() -> None:
    assert [
        e.field for e in validate_step(replace(SERVICE, districts="dt4 8"), fixed_site=True)
    ] == ["districts"]


def test_the_criteria_owner_is_required_and_the_owner_email_must_look_like_an_email() -> None:
    errors = validate_step(
        replace(SERVICE, owner_role="", owner_email="owner.example"), fixed_site=True
    )
    assert _messages(errors) == [
        ("owner_role", "Enter who owns the criteria"),
        ("owner_email", "Enter an email address for the criteria owner"),
    ]


def test_a_review_by_date_is_required() -> None:
    assert [e.field for e in validate_step(replace(SERVICE, review_by=None), fixed_site=True)] == [
        "review_by"
    ]


def test_a_service_needs_at_least_one_referral_method_and_one_accepted_need() -> None:
    errors = validate_step(replace(SERVICE, referral_methods="", needs=""), fixed_site=True)
    assert {e.field for e in errors} == {"referral_methods", "needs"}


def test_a_referral_method_outside_the_four_listed_is_refused() -> None:
    errors = validate_step(replace(SERVICE, referral_methods="fax"), fixed_site=True)
    assert [e.field for e in errors] == ["referral_methods"]


def test_a_need_outside_the_listed_categories_is_refused() -> None:
    errors = validate_step(replace(SERVICE, needs="frailty,yoga"), fixed_site=True)
    assert [e.field for e in errors] == ["needs"]


def test_an_age_range_of_one_year_is_valid_and_an_upper_age_below_the_lower_is_not() -> None:
    same = replace(SERVICE, age_min=18, age_max=18, no_age_limit=False)
    assert validate_step(same, fixed_site=True) == []
    below = replace(SERVICE, age_min=18, age_max=17, no_age_limit=False)
    assert [e.field for e in validate_step(below, fixed_site=True)] == ["age_max"]


def test_no_oldest_age_must_say_no_limit_or_give_an_age() -> None:
    errors = validate_step(replace(SERVICE, age_max=None, no_age_limit=False), fixed_site=True)
    assert [e.field for e in errors] == ["age_max"]


def test_a_youngest_age_is_required_and_cannot_be_negative() -> None:
    assert [e.field for e in validate_step(replace(SERVICE, age_min=None), fixed_site=True)] == [
        "age_min"
    ]
    assert [e.field for e in validate_step(replace(SERVICE, age_min=-1), fixed_site=True)] == [
        "age_min"
    ]


def test_excluded_needs_or_no_exclusions_must_be_given() -> None:
    errors = validate_step(
        replace(SERVICE, excluded_needs="", no_exclusions=False), fixed_site=True
    )
    assert [e.field for e in errors] == ["excluded_needs"]


# --- the UK phone rule (the boundaries) ----------------------------------------------------------


@pytest.mark.parametrize(
    "number",
    [
        "01305 123456",
        "01305123456",
        "01305-123-456",
        "07700 900123",
        "+44 1305 123456",
        "+447700900123",
    ],
)
def test_a_full_uk_number_in_any_usual_spacing_is_accepted(number: str) -> None:
    assert is_full_uk_phone(number)


@pytest.mark.parametrize(
    "number",
    ["", "0123", "0130512345", "013051234567", "1305 123456", "+1 555 123456", "01305 12345a"],
)
def test_a_short_long_or_foreign_or_non_numeric_number_is_refused(number: str) -> None:
    assert not is_full_uk_phone(number)


# --- reporting ---------------------------------------------------------------------------------


def test_a_reporting_range_must_run_from_low_to_high() -> None:
    assert validate_step(replace(REPORTING, usual_low=4, usual_high=4)) == []
    assert [e.field for e in validate_step(replace(REPORTING, usual_low=5, usual_high=4))] == [
        "usual_high"
    ]


@pytest.mark.parametrize(("low", "high"), [(-1, 8), (0, 1000)])
def test_a_usual_number_outside_zero_to_999_is_refused(low: int, high: int) -> None:
    errors = validate_step(replace(REPORTING, usual_low=low, usual_high=high))
    assert errors


def test_a_usual_number_of_zero_and_of_999_are_accepted() -> None:
    assert validate_step(replace(REPORTING, usual_low=0, usual_high=999)) == []


def test_a_text_or_push_channel_needs_a_full_mobile_number() -> None:
    assert [
        e.field for e in validate_step(replace(REPORTING, channel="text", contact_mobile=""))
    ] == ["contact_mobile"]
    assert [
        e.field for e in validate_step(replace(REPORTING, channel="push", contact_mobile="0123"))
    ] == ["contact_mobile"]


def test_an_email_channel_needs_an_email_address_and_no_mobile() -> None:
    ok = replace(REPORTING, channel="email", contact_mobile="", contact_email="reports@example.org")
    assert validate_step(ok) == []
    missing = replace(REPORTING, channel="email", contact_mobile="", contact_email="")
    assert [e.field for e in validate_step(missing)] == ["contact_email"]


def test_the_holder_of_the_phone_is_required() -> None:
    assert [e.field for e in validate_step(replace(REPORTING, holder_name=""))] == ["holder_name"]


# --- API -----------------------------------------------------------------------------------------


def test_an_api_that_is_not_wanted_needs_nothing_else() -> None:
    assert validate_step(ApiStep(wanted=False)) == []


def test_a_wanted_api_needs_a_name_an_https_address_a_connection_and_a_data_type() -> None:
    errors = validate_step(ApiStep(wanted=True))
    assert {e.field for e in errors} == {"name", "address", "connection", "data_type"}


def test_an_api_address_must_be_https() -> None:
    api = ApiStep(
        wanted=True,
        name="Feed",
        address="http://example.org/feed",
        connection="pull",
        data_type="capacity",
    )
    assert [e.field for e in validate_step(api)] == ["address"]


# --- the draft encoding (typed rows, never JSON; DEC-001) -----------------------------------------


@pytest.mark.parametrize("step", [ORG, SITE, SERVICE, API])
def test_a_step_round_trips_through_its_typed_encoding(step: object) -> None:
    fields = encode_step(step)
    assert all(isinstance(value, str | int | bool) for value in fields.values())
    assert decode_step(type(step).__name__, fields) == step


def test_the_reporting_step_round_trips_but_never_holds_a_contact_number_or_email() -> None:
    fields = encode_step(REPORTING)
    assert "contact_mobile" not in fields
    assert "contact_email" not in fields
    assert decode_step("ReportingStep", fields) == replace(
        REPORTING, contact_mobile="", contact_email=""
    )


def test_an_unset_value_is_left_out_of_the_encoding_not_stored_as_null() -> None:
    fields = encode_step(replace(SERVICE, review_by=None, age_max=None))
    assert "review_by" not in fields
    assert "age_max" not in fields
