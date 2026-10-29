"""The pure side of registration persistence (U27): the FHIR transaction bundle a complete draft
becomes, the choice of the address, the unit label, and the lookup record kept for the review.

Every resource is checked against the R4B models (the criteria Basic is the repository's own
profile, so it is checked by reading it back as a criteria version), and every resource goes through
the pure mapper, which is what the resource store keeps. What Neo4j really holds is in
tests/integration/application/test_registration_submit.py. Sample values only: the postcode is the
specs' `DT4 8XX`, the names are samples, and no phone number or address of a real person is here.
"""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Any

import pytest
from fhir.resources.R4B.healthcareservice import HealthcareService
from fhir.resources.R4B.location import Location
from fhir.resources.R4B.organization import Organization

from diucs.adapters.outbound.graph_store import mapper
from diucs.adapters.outbound.graph_store.criteria_repository import criteria_from_fhir
from diucs.adapters.outbound.graph_store.service_repository import profile_from_fhir
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.geo import AddressCandidate, LatLon
from diucs.application.use_cases.registration_draft import (
    ApiStep,
    LocationStep,
    OrganisationStep,
    RegistrationDraft,
    ReportingStep,
    ServiceStep,
)
from diucs.application.use_cases.registration_submit import (
    DISTRICT_TYPE_CODE,
    GEOCODE_SOURCE,
    LOOKUPS_STEP,
    ODS_ORG_SYSTEM,
    UNIT_LABELS,
    Lookups,
    build_registration_bundle,
    choose_address,
    decode_lookups,
    encode_lookups,
    lookups_of,
    unit_label,
)
from diucs.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    RegistrationStatus,
    ServiceCategory,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria
from diucs.domain.model.registration import Registration
from diucs.domain.model.service import AvailableTime, ServiceProfile

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
SERVICE_ID = "svc-ucr-west"
OWNER_ROLE = "role-owner-1"
REPORTER_MOBILE = "07700 900123"
REPORTER_EMAIL = "duty.desk@example.org"
OWNER_EMAIL = "owner@example.org"
ORG = OrganisationStep(
    name="Community Response Ltd",
    ods_code="RXX01",
    org_type="nhs-trust",
    contact_name="Sam Patel",
    contact_email="sam.patel@example.org",
    contact_phone="01305 000111",
)
SITE = LocationStep(
    fixed_site=True,
    postcode="DT4 8XX",
    address="1 Sample Road, Weymouth",
    site_name="Sample Ward",
    site_type="ward",
    open_24h=False,
    opening_days="mon,tue,wed,thu,fri",
    opening_start="08:00",
    opening_end="20:00",
)
VISITING = LocationStep(fixed_site=False)
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
    no_age_limit=True,
    no_exclusions=True,
    owner_role="Clinical lead, UCR",
    owner_email=OWNER_EMAIL,
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
    contact_mobile=REPORTER_MOBILE,
    contact_email=REPORTER_EMAIL,
)
CANDIDATE = AddressCandidate(
    uprn="100012345678",
    line="1 Sample Road",
    town="Weymouth",
    postcode="DT4 8XX",
    position=LatLon(50.6144, -2.4547),
)


def _draft(**steps: Any) -> RegistrationDraft:
    values: dict[str, Any] = {
        "organisation": ORG,
        "location": SITE,
        "service": SERVICE,
        "reporting": REPORTING,
        "api": ApiStep(wanted=False),
    }
    values.update(steps)
    return RegistrationDraft(registration_id="reg-1", **values)


def _build(
    draft: RegistrationDraft | None = None,
    address: AddressCandidate | None = CANDIDATE,
    existing: dict[str, str] | None = None,
) -> dict[str, Any]:
    return build_registration_bundle(
        draft or _draft(),
        SequentialIds("id"),
        NOW,
        address,
        service_id=SERVICE_ID,
        owner_role_id=OWNER_ROLE,
        existing_districts=existing,
    )


def _by_type(bundle: dict[str, Any], resource_type: str) -> list[dict[str, Any]]:
    return [
        entry["resource"]
        for entry in bundle["entry"]
        if entry["resource"]["resourceType"] == resource_type
    ]


def _one(bundle: dict[str, Any], resource_type: str) -> dict[str, Any]:
    found = _by_type(bundle, resource_type)
    assert len(found) == 1
    return found[0]


# The fixed site


def test_a_fixed_site_draft_becomes_a_transaction_of_four_resources_in_dependency_order() -> None:
    bundle = _build()

    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "transaction"
    assert [entry["resource"]["resourceType"] for entry in bundle["entry"]] == [
        "Organization",
        "Location",
        "HealthcareService",
        "Basic",
    ]


def test_each_new_resource_is_a_post_and_the_service_replaces_its_placeholder() -> None:
    bundle = _build()

    requests = {entry["resource"]["resourceType"]: entry["request"] for entry in bundle["entry"]}
    assert requests["Organization"] == {"method": "POST", "url": "Organization"}
    assert requests["Location"] == {"method": "POST", "url": "Location"}
    assert requests["Basic"] == {"method": "POST", "url": "Basic"}
    assert requests["HealthcareService"] == {
        "method": "PUT",
        "url": f"HealthcareService/{SERVICE_ID}",
    }


def test_every_entry_is_named_by_a_urn_uuid_full_url_of_its_own_id() -> None:
    bundle = _build()

    for entry in bundle["entry"]:
        assert entry["fullUrl"] == f"urn:uuid:{entry['resource']['id']}"
    ids = [entry["resource"]["id"] for entry in bundle["entry"]]
    assert len(set(ids)) == 4
    assert SERVICE_ID in ids


def test_cross_references_between_the_resources_are_urn_uuid_full_urls() -> None:
    bundle = _build()
    org = _one(bundle, "Organization")
    location = _one(bundle, "Location")
    service = _one(bundle, "HealthcareService")

    assert location["managingOrganization"] == {"reference": f"urn:uuid:{org['id']}"}
    assert service["providedBy"] == {"reference": f"urn:uuid:{org['id']}"}
    assert service["location"] == [{"reference": f"urn:uuid:{location['id']}"}]


def test_the_organization_location_and_service_validate_as_r4b_resources() -> None:
    bundle = _build()

    Organization.model_validate(_one(bundle, "Organization"))
    Location.model_validate(_one(bundle, "Location"))
    HealthcareService.model_validate(_one(bundle, "HealthcareService"))


def test_everything_is_a_draft() -> None:
    bundle = _build()

    assert _one(bundle, "Organization")["active"] is False
    assert _one(bundle, "Location")["status"] == "inactive"
    assert _one(bundle, "HealthcareService")["active"] is False
    criteria = criteria_from_fhir(_one(bundle, "Basic"))
    assert criteria.version == 1
    assert criteria.status is CriteriaStatus.PENDING_APPROVAL


def test_the_organization_has_the_name_the_ods_code_the_type_and_the_organisation_contact() -> None:
    org = _one(_build(), "Organization")

    assert org["name"] == "Community Response Ltd"
    assert org["identifier"] == [{"system": ODS_ORG_SYSTEM, "value": "RXX01"}]
    assert org["type"][0]["coding"][0]["code"] == "nhs-trust"
    assert {"system": "email", "value": "sam.patel@example.org"} in org["telecom"]
    assert {"system": "phone", "value": "01305 000111"} in org["telecom"]


def test_the_ods_system_is_the_one_the_mapper_copies_to_odscode() -> None:
    assert ODS_ORG_SYSTEM == mapper.ODS_ORG_SYSTEM


def test_the_location_takes_its_position_address_and_uprn_from_the_chosen_candidate() -> None:
    location = _one(_build(), "Location")

    assert location["name"] == "Sample Ward"
    assert location["mode"] == "instance"
    assert location["position"] == {"latitude": 50.6144, "longitude": -2.4547}
    assert location["address"]["line"] == ["1 Sample Road"]
    assert location["address"]["city"] == "Weymouth"
    assert location["address"]["postalCode"] == "DT4 8XX"
    assert location["address"]["district"] == "DT4"
    assert {"system": "https://diucs.example/uprn", "value": "100012345678"} in location[
        "identifier"
    ]


def test_the_location_records_where_and_when_it_was_geocoded() -> None:
    location = _one(_build(), "Location")

    extensions = {entry["url"].rsplit("/", 1)[1]: entry for entry in location["extension"]}
    assert extensions["geocodeSource"]["valueString"] == GEOCODE_SOURCE == "os-places"
    assert extensions["geocodedAt"]["valueDateTime"] == "2026-10-29T10:00:00Z"


def test_the_opening_hours_are_the_days_and_times_or_all_day_when_open_round_the_clock() -> None:
    timed = _one(_build(), "Location")["hoursOfOperation"]
    assert timed == [
        {
            "daysOfWeek": ["mon", "tue", "wed", "thu", "fri"],
            "allDay": False,
            "openingTime": "08:00:00",
            "closingTime": "20:00:00",
        }
    ]
    round_the_clock = _one(_build(_draft(location=replace(SITE, open_24h=True))), "Location")[
        "hoursOfOperation"
    ]
    assert round_the_clock == [
        {
            "daysOfWeek": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "allDay": True,
        }
    ]


def test_a_site_whose_address_was_not_matched_has_no_position_and_no_geocode_record() -> None:
    location = _one(_build(address=None), "Location")

    assert "position" not in location
    assert "extension" not in location
    assert "identifier" not in location
    Location.model_validate(location)


def test_the_service_carries_the_profile_extensions_the_referral_methods_and_the_spoa_phone() -> (
    None
):
    service = _one(_build(), "HealthcareService")

    extensions = {
        entry["url"].rsplit("/", 1)[1]: next(v for k, v in entry.items() if k.startswith("value"))
        for entry in service["extension"]
    }
    assert extensions == {
        "establishedCapacity": 8,
        "canExceedEstablished": False,
        "usualRangeMin": 0,
        "usualRangeMax": 8,
        "reportCadence": "every-2-hrs",
        "limitedLevelPercent": 80,
        "smsShortName": "UCR West",
        "measure": "referrals-acceptable",
        "unitLabel": "referrals",
        "channel": "text",
    }
    assert [c["coding"][0]["code"] for c in service["referralMethod"]] == ["phone", "e-referral"]
    assert service["telecom"] == [{"system": "phone", "value": "01305 123456", "use": "work"}]


def test_the_service_reads_back_as_the_profile_the_draft_describes() -> None:
    profile = profile_from_fhir(_one(_build(), "HealthcareService"))

    assert profile == ServiceProfile(
        id=SERVICE_ID,
        name="UCR West",
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        measure=Measure.REFERRALS_ACCEPTABLE,
        unit_label="referrals",
        established_capacity=8,
        can_exceed_established=False,
        usual_range=(0, 8),
        cadence=Cadence.EVERY_2_HRS,
        available_times=(AvailableTime.weekdays(time(8, 0), time(20, 0)),),
        channel=Channel.TEXT,
        limited_level_percent=80,
        active=False,
        suspended=False,
        comment="",
    )


def test_the_established_capacity_is_the_highest_usual_number_and_never_below_one() -> None:
    quiet = _build(_draft(reporting=replace(REPORTING, usual_low=0, usual_high=0)))

    profile = profile_from_fhir(_one(quiet, "HealthcareService"))

    assert profile.established_capacity == 1
    assert profile.usual_range == (0, 0)


def test_the_first_criteria_version_is_what_the_service_step_says() -> None:
    criteria = criteria_from_fhir(_one(_build(), "Basic"))

    assert criteria == ServiceCriteria(
        id=_one(_build(), "Basic")["id"],
        service_id=SERVICE_ID,
        version=1,
        status=CriteriaStatus.PENDING_APPROVAL,
        age_min=18,
        age_max=None,
        districts=frozenset({"DT4"}),
        accepts=frozenset({NeedCategory.FRAILTY, NeedCategory.WOUND_CARE}),
        excludes=frozenset(),
        review_by=date(2027, 1, 1),
        owner_role_id=OWNER_ROLE,
    )


def test_an_age_limit_and_excluded_needs_are_kept() -> None:
    service = replace(
        SERVICE,
        no_age_limit=False,
        age_max=95,
        no_exclusions=False,
        excluded_needs="palliative",
    )

    criteria = criteria_from_fhir(_one(_build(_draft(service=service)), "Basic"))

    assert criteria.age_max == 95
    assert criteria.excludes == frozenset({NeedCategory.PALLIATIVE})


def test_a_fixed_site_with_no_districts_takes_the_district_of_its_postcode() -> None:
    criteria = criteria_from_fhir(
        _one(_build(_draft(service=replace(SERVICE, districts=""))), "Basic")
    )

    assert criteria.districts == frozenset({"DT4"})


def test_the_unit_label_follows_the_measure() -> None:
    assert set(UNIT_LABELS) == set(Measure)
    assert unit_label(Measure.FREE_BEDS) == "beds"
    assert unit_label(Measure.REFERRALS_ACCEPTABLE) == "referrals"


# A visiting service


def test_a_visiting_service_has_no_position_and_two_coverage_area_locations() -> None:
    draft = _draft(location=VISITING, service=replace(SERVICE, districts="DT3,DT4"))

    bundle = _build(draft, address=None)

    assert [e["resource"]["resourceType"] for e in bundle["entry"]] == [
        "Organization",
        "Location",
        "Location",
        "HealthcareService",
        "Basic",
    ]
    areas = _by_type(bundle, "Location")
    assert [(a["name"], a["mode"]) for a in areas] == [("DT3", "kind"), ("DT4", "kind")]
    assert all("position" not in area for area in areas)
    assert all(
        area["type"][0]["coding"][0]["code"] == DISTRICT_TYPE_CODE == "postcode-district"
        for area in areas
    )
    service = _one(bundle, "HealthcareService")
    assert "location" not in service
    assert service["coverageArea"] == [{"reference": f"urn:uuid:{a['id']}"} for a in areas]
    for area in areas:
        Location.model_validate(area)
    HealthcareService.model_validate(service)


def test_a_district_location_that_exists_is_reused_not_written_again() -> None:
    draft = _draft(location=VISITING, service=replace(SERVICE, districts="DT3,DT4"))

    bundle = _build(draft, address=None, existing={"DT3": "loc-existing-dt3"})

    areas = _by_type(bundle, "Location")
    assert [a["name"] for a in areas] == ["DT4"]
    service = _one(bundle, "HealthcareService")
    assert service["coverageArea"] == [
        {"reference": "Location/loc-existing-dt3"},
        {"reference": f"urn:uuid:{areas[0]['id']}"},
    ]


def test_a_visiting_service_with_every_district_known_writes_no_location_at_all() -> None:
    draft = _draft(location=VISITING, service=replace(SERVICE, districts="DT3"))

    bundle = _build(draft, address=None, existing={"DT3": "loc-existing-dt3"})

    assert _by_type(bundle, "Location") == []
    assert len(bundle["entry"]) == 3


# What must not be in the bundle


def test_the_reporters_phone_and_email_and_the_owners_email_are_in_no_resource() -> None:
    text = json.dumps(_build())

    for secret in (REPORTER_MOBILE, "07700900123", REPORTER_EMAIL, OWNER_EMAIL):
        assert secret not in text


def test_no_resource_carries_a_tenant() -> None:
    assert "tenantId" not in json.dumps(_build())


def test_every_resource_goes_through_the_mapper_and_back_unchanged() -> None:
    bundle = _build(_draft(location=SITE))

    for entry in bundle["entry"]:
        resource = entry["resource"]
        assert mapper.from_graph(mapper.to_graph(resource)) == resource


def test_a_draft_that_is_missing_a_step_is_refused() -> None:
    for step in ("organisation", "location", "service", "reporting"):
        with pytest.raises(ValidationFailed) as raised:
            _build(_draft(**{step: None}))
        assert raised.value.field == step


# Choosing the address


def test_the_candidate_whose_line_and_town_are_the_chosen_address_is_found() -> None:
    other = replace(CANDIDATE, uprn="100012345679", line="2 Sample Road")

    assert choose_address([other, CANDIDATE], "1 Sample Road, Weymouth") == CANDIDATE
    assert choose_address([other, CANDIDATE], "  1 sample road ,  WEYMOUTH ") == CANDIDATE
    assert choose_address([other, CANDIDATE], "1 Sample Road") == CANDIDATE


def test_no_candidate_is_guessed() -> None:
    other = replace(CANDIDATE, uprn="100012345679", line="2 Sample Road")

    assert choose_address([other], "1 Sample Road, Weymouth") is None
    assert choose_address([], "1 Sample Road, Weymouth") is None
    assert choose_address([CANDIDATE], "") is None


def test_two_candidates_that_match_are_not_chosen_between() -> None:
    twin = replace(CANDIDATE, uprn="100012345679")

    assert choose_address([CANDIDATE, twin], "1 Sample Road, Weymouth") is None


# The lookup record


def test_the_lookups_round_trip_through_the_draft_fields() -> None:
    lookups = Lookups(
        ods_found=True,
        ods_active=True,
        ods_name="PILOT SAMPLE COMMUNITY SERVICE",
        ods_type="PILOT-SAMPLE",
        address_found=True,
        address_district="DT4",
        checked_at=NOW,
    )

    values = encode_lookups(lookups)

    assert decode_lookups(values) == lookups
    assert all(isinstance(value, str | int | bool) for value in values.values())


def test_an_ods_code_that_was_not_found_keeps_no_name_and_no_type() -> None:
    lookups = Lookups(False, False, None, None, False, None, NOW)

    values = encode_lookups(lookups)

    assert "ods_name" not in values
    assert "ods_type" not in values
    assert "address_district" not in values
    assert decode_lookups(values) == lookups


def test_lookups_are_found_on_the_registration_by_their_step_name_or_not_at_all() -> None:
    lookups = Lookups(True, True, "SAMPLE", "PILOT-SAMPLE", True, "DT4", NOW)
    registration = Registration(
        id="reg-1",
        service_id=SERVICE_ID,
        status=RegistrationStatus.SUBMITTED,
        requester_role_id="role-1",
        owner_role_id=None,
        created_at=NOW,
        last_modified=NOW,
        draft={"organisation": {"name": "x"}},
    )

    assert lookups_of(registration) is None
    held = replace(
        registration, draft={**registration.draft, LOOKUPS_STEP: encode_lookups(lookups)}
    )
    assert lookups_of(held) == lookups
    assert LOOKUPS_STEP == "lookups"


def test_a_stored_lookup_with_a_field_it_does_not_have_is_refused() -> None:
    values = {**encode_lookups(Lookups(True, True, "S", "T", True, "DT4", NOW)), "extra": "x"}

    with pytest.raises(ValidationFailed):
        decode_lookups(values)
