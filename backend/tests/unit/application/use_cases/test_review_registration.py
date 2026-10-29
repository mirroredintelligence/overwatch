"""The pure rules of reviewing a registration (U28): who may review, the five automatic checks and
their wording, the explanation that makes a failed check count as ok, how names, emails and numbers
are compared, and the area. The flow (what is stored, read back from Neo4j) is in
tests/integration/application/test_review_registration.py. Sample values only: the postcode is the
specs' `DT4 8XX` and the people are samples."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from diucs.application.actor import Actor
from diucs.application.use_cases.registration_draft import (
    ApiStep,
    LocationStep,
    OrganisationStep,
    ReportingStep,
    ServiceStep,
    encode_step,
)
from diucs.application.use_cases.registration_submit import LOOKUPS_STEP, Lookups, encode_lookups
from diucs.application.use_cases.review_registration import (
    CHECK_ADDRESS,
    CHECK_EMAIL,
    CHECK_NAME,
    CHECK_ODS,
    CHECK_PHONE,
    FREE_MAIL_DOMAINS,
    NHS_MAIL_DOMAIN,
    NHS_ORGANISATION_TYPES,
    NOTES_STEP,
    AutomaticCheck,
    automatic_ok,
    callback_number_hash,
    check_may_review,
    districts_in_ranges,
    name_key,
    number_digits,
    organisation_email_ok,
    run_automatic_checks,
)
from diucs.domain.codes import RegistrationStatus, Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.registration import Registration

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
AREA = districts_in_ranges(("DT", 1, 11), ("BH", 1, 31))
INVITED = "a" * 64
OTHER = "b" * 64
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
    referral_methods="phone",
    spoa_phone="01305 123456",
    accepting_days="mon,tue",
    accepting_start="08:00",
    accepting_end="20:00",
    needs="frailty",
    age_min=18,
    no_age_limit=True,
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
)
GOOD = Lookups(
    ods_found=True,
    ods_active=True,
    ods_name="COMMUNITY RESPONSE LTD",
    ods_type="PILOT-SAMPLE",
    address_found=True,
    address_district="DT4",
    checked_at=NOW,
)


def _registration(**steps: object) -> Registration:
    values: dict[str, object] = {
        "organisation": ORG,
        "location": SITE,
        "service": SERVICE,
        "reporting": REPORTING,
        "api": ApiStep(wanted=False),
    }
    values.update(steps)
    return Registration(
        id="reg-1",
        service_id="svc-ucr-west",
        status=RegistrationStatus.IN_REVIEW,
        requester_role_id="role-applicant",
        owner_role_id="role-lead",
        created_at=NOW,
        last_modified=NOW,
        draft={key: encode_step(step) for key, step in values.items()},
    )


def _checks(
    registration: Registration | None = None,
    *,
    lookups: Lookups | None = GOOD,
    invited: str | None = INVITED,
    reporting: str | None = INVITED,
    area: frozenset[str] = AREA,
    notes: dict[str, str] | None = None,
) -> dict[str, AutomaticCheck]:
    found = run_automatic_checks(
        registration or _registration(),
        lookups=lookups,
        invited_phone_hash=invited,
        reporting_phone_hash=reporting,
        area_districts=area,
        notes=notes,
    )
    return {check.name: check for check in found}


# Who may review


def test_the_shift_lead_may_review_and_the_lead_practitioner_is_returned() -> None:
    actor = Actor(Role.LEAD, "prac-lead", None, "web", frozenset())
    assert check_may_review(actor) == "prac-lead"


@pytest.mark.parametrize("role", [role for role in Role if role is not Role.LEAD])
def test_every_other_role_is_refused(role: Role) -> None:
    with pytest.raises(NotAllowed):
        check_may_review(Actor(role, "prac-lead", None, "web", frozenset()))


def test_a_lead_with_no_named_practitioner_is_refused() -> None:
    with pytest.raises(NotAllowed):
        check_may_review(Actor(Role.LEAD, None, None, "web", frozenset()))


# The five checks, all passing


def test_a_good_registration_passes_all_five_checks_in_screen_order() -> None:
    found = run_automatic_checks(
        _registration(),
        lookups=GOOD,
        invited_phone_hash=INVITED,
        reporting_phone_hash=INVITED,
        area_districts=AREA,
    )

    assert [check.name for check in found] == [
        CHECK_ODS,
        CHECK_NAME,
        CHECK_ADDRESS,
        CHECK_PHONE,
        CHECK_EMAIL,
    ]
    assert all(check.passed and check.ok for check in found)
    assert all(check.explained_note is None for check in found)
    assert automatic_ok(found) is True


# ODS


@pytest.mark.parametrize(
    ("lookups", "message"),
    [
        (None, "ODS code has not been checked"),
        (replace(GOOD, ods_found=False, ods_name=None, ods_type=None), "ODS code not found"),
        (replace(GOOD, ods_active=False), "ODS code is not active"),
        (replace(GOOD, ods_type="PRIVATE LIMITED COMPANY"), "ODS code is not an NHS organisation"),
        (replace(GOOD, ods_type=None), "ODS code is not an NHS organisation"),
    ],
)
def test_an_ods_code_that_is_not_found_active_and_an_nhs_organisation_fails_with_its_reason(
    lookups: Lookups | None, message: str
) -> None:
    check = _checks(lookups=lookups)[CHECK_ODS]

    assert check.passed is False
    assert check.ok is False
    assert check.message == message


def test_the_nhs_organisation_types_are_compared_ignoring_case_and_punctuation() -> None:
    assert "pilot sample" in {name_key(item) for item in NHS_ORGANISATION_TYPES}
    for written in ("pilot-sample", "NHS Trust", "Gp  practice"):
        assert _checks(lookups=replace(GOOD, ods_type=written))[CHECK_ODS].passed is True


# The name


@pytest.mark.parametrize(
    "ods_name",
    ["COMMUNITY RESPONSE LTD", "community response ltd.", "Community-Response  Ltd"],
)
def test_the_name_matches_the_ods_name_ignoring_case_spacing_and_punctuation(
    ods_name: str,
) -> None:
    assert _checks(lookups=replace(GOOD, ods_name=ods_name))[CHECK_NAME].passed is True


def test_a_different_name_fails() -> None:
    check = _checks(lookups=replace(GOOD, ods_name="ANOTHER TRUST"))[CHECK_NAME]

    assert check.passed is False
    assert check.message == "Organisation name does not match the ODS name"


def test_a_name_cannot_be_checked_without_an_ods_record() -> None:
    for lookups in (None, replace(GOOD, ods_found=False, ods_name=None, ods_type=None)):
        check = _checks(lookups=lookups)[CHECK_NAME]
        assert check.passed is False
        assert check.message == "Organisation name cannot be checked without an ODS record"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Community Response Ltd.", "COMMUNITY RESPONSE LTD"),
        ("St. Mary's Ward", "ST MARYS WARD"),
        ("Dorset-Health  Care", "dorset health care"),
    ],
)
def test_name_key_ignores_case_spacing_and_punctuation(first: str, second: str) -> None:
    assert name_key(first) == name_key(second)


def test_name_key_keeps_the_words_apart() -> None:
    assert name_key("Community Response") != name_key("Communityresponse")


# The address and the area


def test_a_fixed_site_whose_address_was_not_found_fails() -> None:
    check = _checks(lookups=replace(GOOD, address_found=False, address_district=None))[
        CHECK_ADDRESS
    ]

    assert check.passed is False
    assert check.message == "Address not found"


def test_a_fixed_site_outside_the_area_fails() -> None:
    check = _checks(lookups=replace(GOOD, address_district="EX1"))[CHECK_ADDRESS]

    assert check.passed is False
    assert check.message == "Address district is outside the area"


def test_the_area_is_the_districts_given_to_the_check_and_not_a_built_in_default() -> None:
    assert _checks(area=frozenset({"DT4"}))[CHECK_ADDRESS].passed is True
    assert _checks(area=frozenset({"DT5"}))[CHECK_ADDRESS].passed is False
    assert _checks(area=frozenset())[CHECK_ADDRESS].passed is False


def test_a_visiting_service_passes_when_every_district_is_in_the_area() -> None:
    registration = _registration(
        location=LocationStep(fixed_site=False), service=replace(SERVICE, districts="DT3,BH10")
    )
    lookups = replace(GOOD, address_found=False, address_district=None)

    check = _checks(registration, lookups=lookups)[CHECK_ADDRESS]

    assert check.passed is True
    assert check.message == "Every district is in the area"


@pytest.mark.parametrize("districts", ["DT3,EX1", ""])
def test_a_visiting_service_fails_when_a_district_is_outside_or_none_is_given(
    districts: str,
) -> None:
    registration = _registration(
        location=LocationStep(fixed_site=False), service=replace(SERVICE, districts=districts)
    )

    check = _checks(registration, lookups=replace(GOOD, address_found=False))[CHECK_ADDRESS]

    assert check.passed is False


def test_the_district_ranges_are_expanded_and_their_edges_are_exact() -> None:
    assert {"DT1", "DT11", "BH1", "BH31"} <= AREA
    assert not {"DT0", "DT12", "BH0", "BH32", "DT"} & AREA
    assert len(AREA) == 11 + 31


@pytest.mark.parametrize(
    "bad", [("DT", 5, 4), ("dt", 1, 2), ("", 1, 2), ("DT1", 1, 2), ("DT", 0, 2), ("DTX", 1, 2)]
)
def test_a_district_range_that_is_not_a_prefix_and_an_ordered_pair_from_one_is_refused(
    bad: tuple[str, int, int],
) -> None:
    with pytest.raises(ValidationFailed):
        districts_in_ranges(bad)


# The reporting phone


def test_the_reporting_phone_must_be_the_one_invited() -> None:
    assert _checks(reporting=INVITED)[CHECK_PHONE].passed is True
    different = _checks(reporting=OTHER)[CHECK_PHONE]
    assert different.passed is False
    assert different.message == "Reporting phone is not the invited number"


@pytest.mark.parametrize(("invited", "reporting"), [(None, INVITED), (INVITED, None), (None, None)])
def test_a_missing_hash_never_passes_the_phone_check(
    invited: str | None, reporting: str | None
) -> None:
    assert _checks(invited=invited, reporting=reporting)[CHECK_PHONE].passed is False


# The owner's email


@pytest.mark.parametrize(
    ("owner", "organisation", "expected"),
    [
        ("lead@nhs.net", "contact@example.org", True),
        ("lead@NHS.NET", "contact@example.org", True),
        ("lead@example.org", "contact@example.org", True),
        ("lead@Example.ORG", "contact@example.org", True),
        ("lead@other.org", "contact@example.org", False),
        ("lead@sub.nhs.net.evil.com", "contact@example.org", False),
        ("lead@gmail.com", "contact@example.org", False),
        ("lead@gmail.com", "contact@gmail.com", False),
        ("lead@HOTMAIL.com", "contact@hotmail.com", False),
        ("lead@outlook.com", "x@outlook.com", False),
        ("lead@yahoo.com", "x@yahoo.com", False),
        ("not an email", "contact@example.org", False),
        ("lead@", "contact@example.org", False),
        ("lead@example.org", "", False),
        ("lead@example.org", "not an email", False),
    ],
)
def test_the_owner_email_is_nhs_net_or_the_organisations_own_domain_and_never_free_mail(
    owner: str, organisation: str, expected: bool
) -> None:
    assert organisation_email_ok(owner, organisation) is expected


def test_the_domains_the_rule_names_are_the_four_free_mail_domains_and_nhs_net() -> None:
    assert {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com"} == FREE_MAIL_DOMAINS
    assert FREE_MAIL_DOMAINS.isdisjoint({NHS_MAIL_DOMAIN})
    assert organisation_email_ok(f"lead@{NHS_MAIL_DOMAIN}", "x@example.org")


def test_a_free_mail_owner_fails_with_the_screen_wording() -> None:
    registration = _registration(service=replace(SERVICE, owner_email="owner@gmail.com"))

    check = _checks(registration)[CHECK_EMAIL]

    assert check.passed is False
    assert check.message == "Criteria owner email is not an organisation address"


# Explaining a failed check


def test_an_explained_failure_counts_as_ok_and_keeps_its_note() -> None:
    registration = _registration(service=replace(SERVICE, owner_email="owner@gmail.com"))

    checks = _checks(registration, notes={CHECK_EMAIL: "The owner uses a shared trust mailbox"})

    check = checks[CHECK_EMAIL]
    assert check.passed is False
    assert check.ok is True
    assert check.explained_note == "The owner uses a shared trust mailbox"
    assert automatic_ok(tuple(checks.values())) is True


def test_a_failure_that_is_not_explained_keeps_the_whole_set_not_ok() -> None:
    registration = _registration(service=replace(SERVICE, owner_email="owner@gmail.com"))

    checks = _checks(registration, reporting=OTHER, notes={CHECK_EMAIL: "Shared mailbox"})

    assert checks[CHECK_PHONE].ok is False
    assert automatic_ok(tuple(checks.values())) is False


def test_a_blank_note_explains_nothing_and_a_note_on_a_passed_check_changes_nothing() -> None:
    registration = _registration(service=replace(SERVICE, owner_email="owner@gmail.com"))

    blank = _checks(registration, notes={CHECK_EMAIL: "   "})[CHECK_EMAIL]
    passed = _checks(notes={CHECK_NAME: "unneeded"})[CHECK_NAME]

    assert blank.ok is False
    assert blank.explained_note is None
    assert passed.passed is True
    assert passed.explained_note is None


def test_the_notes_are_read_from_the_registrations_check_notes_step() -> None:
    assert NOTES_STEP == "check_notes"
    assert LOOKUPS_STEP != NOTES_STEP
    assert encode_lookups(GOOD)  # the lookup record is a separate step of the same draft


def test_an_empty_set_of_checks_is_not_ok() -> None:
    assert automatic_ok(()) is False


# Numbers


def test_a_number_is_compared_by_its_digits_in_any_common_form() -> None:
    assert number_digits("01305 123456") == "01305123456"
    assert number_digits("+44 1305 123456") == "01305123456"
    assert number_digits("01305-123456") == "01305123456"
    assert number_digits("0044 1305 123456") == "01305123456"


@pytest.mark.parametrize("bad", ["", "abc", "01305 12345", "0130512345678", "+1 202 555 0100"])
def test_a_number_that_is_not_a_full_uk_number_is_refused_without_being_echoed(bad: str) -> None:
    with pytest.raises(ValidationFailed) as raised:
        number_digits(bad)
    assert raised.value.field == "number_called"
    assert "0100" not in str(raised.value)


def test_the_number_called_is_kept_only_as_a_keyed_hash() -> None:
    secret = b"phone-hash-test-secret-0123456789ab"

    stored = callback_number_hash(secret, "01305 123456")

    assert len(stored) == 64
    assert "01305" not in stored
    assert stored == callback_number_hash(secret, "+44 1305 123456")
    assert stored != callback_number_hash(b"another-secret-0123456789abcdef-0", "01305 123456")
    assert stored != callback_number_hash(secret, "01305 123457")
