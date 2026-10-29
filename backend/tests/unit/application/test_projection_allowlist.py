"""The one allowlist, its rows and bodies, the sentinel scan and the statement check (TEN-052).

What may leave a tenant for the network is decided in `domain/rules/projection.py` and nowhere else
(DEC-132 items 4 and 7). These tests pin it three ways: the allowlist equals the DTOs and the rows
they produce; no never-shared category survives the builders (a sentinel planted in every place it
exists); and a statement that could write a field the allowlist does not name is refused before it
is registered (the check TEN-053 and TEN-062 run). Hazards H-N01, H-N14, H-09.

All values are invented. The probes that look like patient data are probes on purpose.
"""

import dataclasses
import inspect
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import fields
from datetime import UTC, date, datetime, time
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.application import projection as projection_module
from diucs.application.projection import (
    ProjectionRow,
    assert_network_write_statement,
    body_keys,
    check_network_write_statement,
    format_window,
    from_body,
    parse_window,
    to_body,
    to_rows,
)
from diucs.domain.codes import Channel, Measure, ReportSource, ReportType
from diucs.domain.errors import ValidationFailed
from diucs.domain.messages.privacy_guard import (
    FORBIDDEN_KEY_FORMS,
    find_patient_data,
    normalise_key,
)
from diucs.domain.model.network import GrantScope
from diucs.domain.rules import projection as domain_projection
from diucs.domain.rules.projection import (
    ALLOWLIST,
    NETWORK_RELATIONSHIPS,
    NEVER_SHARED,
    PROJECTION_ALLOWLIST_VERSION,
    SYSTEM_PROPERTIES,
    CapacityProjection,
    CriteriaProjection,
    OpeningHourProjection,
    ServiceProjection,
    allowlist_digest,
    build_capacity_projection,
    build_criteria_projection,
    build_service_projection,
)
from tests.support.projection_samples import (
    sample_capacity_projection,
    sample_contact,
    sample_criteria,
    sample_criteria_projection,
    sample_location,
    sample_policy,
    sample_profile,
    sample_report,
    sample_service_projection,
)

# The digest of version 1 of the allowlist. A change to a field, a property name or a source
# changes it: bump PROJECTION_ALLOWLIST_VERSION, record a decision, and update both pins together.
PINNED_VERSION = 1
PINNED_DIGEST = "0" * 64

LABELS = (
    "ProjectedService",
    "ProjectedLocation",
    "ProjectedOpeningHour",
    "ProjectedCapacity",
    "ProjectedCriteria",
)

# ---------------------------------------------------------------- helpers


def _rows_by_label(rows: Iterable[ProjectionRow]) -> dict[str, list[ProjectionRow]]:
    grouped: dict[str, list[ProjectionRow]] = {}
    for row in rows:
        grouped.setdefault(row.label, []).append(row)
    return grouped


def _all_rows() -> dict[str, list[ProjectionRow]]:
    rows = [
        *to_rows(sample_service_projection()),
        *to_rows(sample_capacity_projection()),
        *to_rows(sample_criteria_projection()),
    ]
    return _rows_by_label(rows)


def flatten(value: object) -> list[str]:
    """Every key and every value, recursively, as text: what a scan of a stored node would read."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.append(str(key))
            found.extend(flatten(item))
    elif isinstance(value, ProjectionRow):
        found.append(value.label)
        found.extend(flatten(value.params))
    elif isinstance(value, list | tuple | set | frozenset):
        for item in value:
            found.extend(flatten(item))
    elif value is not None:
        found.append(str(value))
    return found


GOOD_BODIES: dict[GrantScope, Callable[[], Any]] = {
    GrantScope.DIRECTORY: sample_service_projection,
    GrantScope.CAPACITY: sample_capacity_projection,
    GrantScope.CRITERIA: sample_criteria_projection,
}

# ---------------------------------------------------------------- 1. allowlist equality


@pytest.mark.parametrize("label", LABELS)
def test_the_allowlist_equals_the_keys_of_the_rows_for_each_label(label: str) -> None:
    rows = _all_rows()[label]

    expected = [spec.prop for spec in ALLOWLIST[label]]
    for row in rows:
        assert list(row.params) == expected  # the same keys, in table order


def test_the_allowlist_names_exactly_the_five_labels() -> None:
    assert set(ALLOWLIST) == set(LABELS)


def _dto_field_names(dto_class: type, children: set[str]) -> set[str]:
    return {field.name for field in fields(dto_class)} - children


@pytest.mark.parametrize(
    ("dto_class", "label", "children"),
    [
        (ServiceProjection, "ProjectedService", {"location", "opening_hours"}),
        (domain_projection.LocationProjection, "ProjectedLocation", set()),
        (OpeningHourProjection, "ProjectedOpeningHour", set()),
        (CapacityProjection, "ProjectedCapacity", set()),
        (CriteriaProjection, "ProjectedCriteria", set()),
    ],
)
def test_each_dto_has_exactly_the_fields_of_its_allowlist(
    dto_class: type, label: str, children: set[str]
) -> None:
    assert _dto_field_names(dto_class, children) == {spec.dto_field for spec in ALLOWLIST[label]}
    assert dto_class.label == label  # type: ignore[attr-defined]


def test_the_service_dto_keeps_the_location_and_hours_as_children() -> None:
    names = {field.name for field in fields(ServiceProjection)}

    assert {"location", "opening_hours"} <= names


def test_every_row_has_every_key_even_when_the_value_is_absent() -> None:
    service = sample_service_projection(location=None, contact=None)
    capacity = sample_capacity_projection(latest=None, valid_until=None)

    service_row = to_rows(service)[0]
    capacity_row = to_rows(capacity)[0]

    assert service_row.params["serviceContactPhone"] is None
    assert service_row.params["serviceContactLabel"] is None
    assert set(service_row.params) == {spec.prop for spec in ALLOWLIST["ProjectedService"]}
    assert capacity_row.params["effectiveDateTime"] is None
    assert capacity_row.params["validUntil"] is None
    assert set(capacity_row.params) == {spec.prop for spec in ALLOWLIST["ProjectedCapacity"]}


def test_a_service_gives_its_row_its_location_row_and_one_row_per_opening_hour() -> None:
    rows = to_rows(sample_service_projection())

    assert [row.label for row in rows] == [
        "ProjectedService",
        "ProjectedLocation",
        "ProjectedOpeningHour",
        "ProjectedOpeningHour",
    ]
    assert [row.params["position"] for row in rows[2:]] == [0, 1]


def test_a_service_with_no_location_gives_no_location_row() -> None:
    labels = [row.label for row in to_rows(sample_service_projection(location=None))]

    assert "ProjectedLocation" not in labels


def test_children_carry_no_parent_id() -> None:
    for row in to_rows(sample_service_projection())[1:]:
        assert not any("service" in key.lower() for key in row.params)


def test_row_values_are_neo4j_property_types_and_never_a_mapping() -> None:
    allowed = (str, int, float, bool, type(None), list, datetime, date, time)
    for rows in _all_rows().values():
        for row in rows:
            for value in row.params.values():
                assert isinstance(value, allowed)
                assert not isinstance(value, Mapping)
                if isinstance(value, list):
                    assert all(isinstance(item, str | int) for item in value)


def test_the_row_values_are_the_stored_forms() -> None:
    rows = _all_rows()

    service = rows["ProjectedService"][0].params
    assert service["categoryCode"] == "urgent-community-response"
    assert service["source"] == "manual"
    assert service["serviceName"] == "UCR West"
    capacity = rows["ProjectedCapacity"][0].params
    assert capacity["measureCode"] == "referrals-acceptable"
    assert capacity["cadenceCode"] == "every-2-hrs"
    assert capacity["effectiveDateTime"] == datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
    assert capacity["replyWindowMinutes"] == 30
    assert capacity["staleWarningHours"] == 2
    criteria = rows["ProjectedCriteria"][0].params
    assert criteria["postcodeDistricts"] == ["DT1", "DT4"]
    assert criteria["acceptsNeedCodes"] == ["fall-no-injury", "frailty"]
    assert criteria["excludesNeedCodes"] == ["iv-therapy"]
    assert criteria["reviewBy"] == date(2027, 4, 29)
    hour = rows["ProjectedOpeningHour"][0].params
    assert hour["days"] == [0, 1, 2, 3, 4]
    assert hour["start"] == time(8, 0)


def test_the_location_row_holds_a_district_and_no_street_or_full_postcode() -> None:
    location = _all_rows()["ProjectedLocation"][0].params

    assert location["postalDistrict"] == "DT4"
    assert "8XX" not in str(location)
    assert set(location) == {"locationName", "postalDistrict", "city", "latitude", "longitude"}


# ---------------------------------------------------------------- 2. digest and version


def test_the_allowlist_version_and_digest_are_pinned() -> None:
    assert PROJECTION_ALLOWLIST_VERSION == PINNED_VERSION, (
        "the allowlist version changed: record a decision and update the pins together"
    )
    assert allowlist_digest() == PINNED_DIGEST, (
        "the allowlist changed: bump PROJECTION_ALLOWLIST_VERSION, record a decision, "
        "and update PINNED_DIGEST in the same commit (a widening needs a new grant agreement)"
    )


def test_the_digest_is_a_sha256_hex_string() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", allowlist_digest())


def test_the_digest_changes_when_a_field_is_added(monkeypatch: pytest.MonkeyPatch) -> None:
    before = allowlist_digest()
    widened = {
        **ALLOWLIST,
        "ProjectedService": (
            *ALLOWLIST["ProjectedService"],
            domain_projection.FieldSpec("extra", "extra", "nowhere"),
        ),
    }
    monkeypatch.setattr(domain_projection, "ALLOWLIST", widened)

    assert allowlist_digest() != before


def test_the_digest_changes_when_a_source_is_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    before = allowlist_digest()
    first = ALLOWLIST["ProjectedService"][0]
    changed = {
        **ALLOWLIST,
        "ProjectedService": (
            dataclasses.replace(first, source="somewhere else"),
            *ALLOWLIST["ProjectedService"][1:],
        ),
    }
    monkeypatch.setattr(domain_projection, "ALLOWLIST", changed)

    assert allowlist_digest() != before


# ---------------------------------------------------------------- 3. property names


def test_no_stored_property_or_dto_field_is_a_forbidden_key_form() -> None:
    names = {spec.prop for specs in ALLOWLIST.values() for spec in specs}
    names |= {spec.dto_field for specs in ALLOWLIST.values() for spec in specs}
    names |= {prop for props in SYSTEM_PROPERTIES.values() for prop in props}

    clashes = [name for name in names if normalise_key(name) in FORBIDDEN_KEY_FORMS]

    assert clashes == []
    assert "serviceName" in names
    assert "serviceContactPhone" in names


def test_a_future_phone_property_would_be_caught_by_that_test() -> None:
    assert normalise_key("phone") in FORBIDDEN_KEY_FORMS
    assert normalise_key("Phone_Hash") in FORBIDDEN_KEY_FORMS


def test_every_field_has_a_named_source() -> None:
    for specs in ALLOWLIST.values():
        for spec in specs:
            assert spec.source.strip()
            assert spec.prop.strip()
            assert spec.dto_field.strip()


def test_no_property_is_named_in_never_shared_terms() -> None:
    names = [spec.prop.lower() for specs in ALLOWLIST.values() for spec in specs]
    names += [prop.lower() for props in SYSTEM_PROPERTIES.values() for prop in props]

    for term in ("token", "comment", "reason", "pin", "device", "reporter", "booking", "audit"):
        # `endReason` is a system property for ended grants, a fixed code; nothing else holds one.
        offending = [name for name in names if term in name and name != "endreason"]
        assert offending == [], term
    assert not any(name in {"phone", "phonehash"} for name in names)


def test_the_property_names_are_unique_within_a_label() -> None:
    for label, specs in ALLOWLIST.items():
        props = [spec.prop for spec in specs]
        assert len(props) == len(set(props)), label
        assert not set(props) & SYSTEM_PROPERTIES[label], label


def test_the_system_properties_are_the_documented_set() -> None:
    stamped = {
        "tenantId",
        "sourceTenantId",
        "projectedAt",
        "grantId",
        "grantVersion",
        "endedAt",
        "endReason",
    }
    for label in LABELS:
        assert SYSTEM_PROPERTIES[label] == stamped
    assert SYSTEM_PROPERTIES["ProjectionSource"] == {
        "tenantId",
        "sourceTenantId",
        "kind",
        "status",
        "endedAt",
        "endReason",
        "grantId",
    }
    assert SYSTEM_PROPERTIES["ProjectionCursor"] == {
        "tenantId",
        "sourceTenantId",
        "kind",
        "watermark",
    }


def test_no_relationship_type_is_allowed_yet() -> None:
    assert frozenset() == NETWORK_RELATIONSHIPS


def test_the_allowlist_exists_once_in_the_source_tree() -> None:
    """No second list of projected property names: another module that spelled them out would
    drift (hazard H-N01)."""
    from pathlib import Path

    source = Path(domain_projection.__file__).parents[2]
    needle = '"sourceServiceId"'
    holders = [path for path in source.rglob("*.py") if needle in path.read_text(encoding="utf-8")]

    assert [path.name for path in holders] == ["projection.py"]
    assert holders[0].parent.name == "rules"


# ---------------------------------------------------------------- 4. the sentinel scan


def _sentinel(category: str) -> str:
    return f"SENTINEL-{category.upper()}-zq7x"


def _build_all(**sources: Any) -> list[Any]:
    profile = sources.get("profile") or sample_profile()
    report = sources.get("report") or sample_report()
    criteria = sources.get("criteria") or sample_criteria()
    return [
        build_service_projection(
            profile, source_version=1, location=sample_location(), contact=sample_contact()
        ),
        build_capacity_projection(
            profile,
            report,
            confirmed_since=1,
            policy=sample_policy(),
            source_version=1,
            valid_until=None,
        ),
        build_criteria_projection(criteria),
    ]


# Where each text-bearing never-shared category lives on the inputs the builders accept.
PLANT_POINTS: dict[str, list[Callable[[str], dict[str, Any]]]] = {
    "service-comment": [lambda s: {"profile": sample_profile(comment=s)}],
    "role-reference": [
        lambda s: {"report": sample_report(performer_role_id=s)},
        lambda s: {"report": sample_report(derived_from=s)},
        lambda s: {"criteria": sample_criteria(owner_role_id=s)},
        lambda s: {"criteria": sample_criteria(supersedes_id=s)},
    ],
    "criteria-change-reason": [lambda s: {"criteria": sample_criteria(change_reason=s)}],
}

# Categories that exist as a non-text value on the inputs (an enum or a range): the output must not
# depend on it at all.
VARIATIONS: dict[str, list[list[dict[str, Any]]]] = {
    "report-channel": [
        [{"profile": sample_profile(channel=channel)} for channel in Channel],
        [{"report": sample_report(source=source)} for source in ReportSource],
        [
            {"report": sample_report(report_type=ReportType.NUMBER)},
            {"report": sample_report(report_type=ReportType.CONFIRMED, derived_from="rep-0")},
        ],
    ],
    "report-range": [
        [{"profile": sample_profile(usual_range=(0, high))} for high in (0, 3, 10, 40)],
    ],
}

# Categories no builder input can hold: no input record and no builder parameter carries the stem.
INTROSPECTED: dict[str, tuple[str, ...]] = {
    "reporter-name": ("reporter",),
    "reporter-phone": ("reporter", "phonehash"),
    "device": ("device",),
    "pin": ("pin",),
    "token": ("token",),
    "communication": ("communication",),
    "booking": ("booking",),
    "case": ("case",),
    "audit-entry": ("audit",),
    "role-contact": ("protectedcontact", "rolecontact"),
    "flag-reason": ("flag",),
    "next-due": ("nextdue",),
    "pending-bookings": ("pending",),
}


def _input_names() -> set[str]:
    names: set[str] = set()
    for builder in (
        build_service_projection,
        build_capacity_projection,
        build_criteria_projection,
    ):
        names |= {name for name in inspect.signature(builder).parameters}
    for record in (domain_projection.LocationInputs, domain_projection.ServiceContactInputs):
        names |= {field.name for field in fields(record)}
    for dto in (
        ServiceProjection,
        domain_projection.LocationProjection,
        OpeningHourProjection,
        CapacityProjection,
        CriteriaProjection,
    ):
        names |= {field.name for field in fields(dto)}
    return {normalise_key(name) for name in names}


def test_every_never_shared_category_has_a_plant_point_or_an_introspection_entry() -> None:
    covered = set(PLANT_POINTS) | set(VARIATIONS) | set(INTROSPECTED)

    assert set(NEVER_SHARED) == covered
    assert len(NEVER_SHARED) == len(set(NEVER_SHARED))


def test_the_never_shared_list_is_the_documented_eighteen() -> None:
    assert set(NEVER_SHARED) == {
        "reporter-name",
        "reporter-phone",
        "device",
        "pin",
        "token",
        "communication",
        "booking",
        "case",
        "audit-entry",
        "service-comment",
        "flag-reason",
        "criteria-change-reason",
        "role-reference",
        "role-contact",
        "report-channel",
        "report-range",
        "next-due",
        "pending-bookings",
    }


@pytest.mark.parametrize("category", sorted(PLANT_POINTS))
def test_a_planted_sentinel_appears_nowhere_in_any_row_or_body(category: str) -> None:
    sentinel = _sentinel(category)

    for plant in PLANT_POINTS[category]:
        for dto in _build_all(**plant(sentinel)):
            text = flatten(to_rows(dto)) + flatten(to_body(dto)) + [repr(dto)]
            assert not any(sentinel in item for item in text), (category, type(dto).__name__)


def test_the_sentinels_are_not_patient_shaped() -> None:
    for category in NEVER_SHARED:
        assert find_patient_data(_sentinel(category)) == []


@pytest.mark.parametrize("category", sorted(VARIATIONS))
def test_a_never_shared_value_that_is_not_text_changes_nothing_in_the_output(
    category: str,
) -> None:
    for group in VARIATIONS[category]:
        outputs = []
        for variation in group:
            built = _build_all(**variation)
            outputs.append([(to_rows(dto), to_body(dto)) for dto in built])
        assert all(output == outputs[0] for output in outputs), category


@pytest.mark.parametrize("category", sorted(INTROSPECTED))
def test_no_input_or_dto_field_carries_a_name_of_a_category_no_input_can_hold(
    category: str,
) -> None:
    names = _input_names()

    for stem in INTROSPECTED[category]:
        assert [name for name in names if stem in name] == [], (category, stem)


def test_location_and_contact_are_the_only_free_text_bearing_inputs() -> None:
    inputs = {
        name
        for name, member in inspect.getmembers(domain_projection, inspect.isclass)
        if name.endswith("Inputs")
    }

    assert inputs == {"LocationInputs", "ServiceContactInputs"}


def test_a_value_planted_in_every_place_at_once_is_still_absent() -> None:
    marker = "SENTINEL-ALL-zq7x"
    built = _build_all(
        profile=sample_profile(comment=marker),
        report=sample_report(performer_role_id=marker, derived_from=marker),
        criteria=sample_criteria(owner_role_id=marker, supersedes_id=marker, change_reason=marker),
    )

    for dto in built:
        assert marker not in "".join(flatten(to_rows(dto)) + flatten(to_body(dto)))


def test_the_completeness_test_fails_when_an_entry_is_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(INTROSPECTED, "extra-category", ("x",))

    assert set(NEVER_SHARED) != set(PLANT_POINTS) | set(VARIATIONS) | set(INTROSPECTED)


# ---------------------------------------------------------------- 5. what cannot get through


def _body(kind: GrantScope) -> dict[str, Any]:
    return dict(to_body(GOOD_BODIES[kind]()))


@pytest.mark.parametrize("kind", list(GrantScope))
def test_a_good_body_reads_back_as_the_same_dto(kind: GrantScope) -> None:
    dto = GOOD_BODIES[kind]()

    assert from_body(kind, to_body(dto)) == dto


@pytest.mark.parametrize("kind", list(GrantScope))
def test_the_body_has_exactly_the_keys_of_the_kind(kind: GrantScope) -> None:
    assert set(_body(kind)) == body_keys(kind)


def test_the_body_keys_are_the_dto_field_names_flat() -> None:
    service = {spec.dto_field for spec in ALLOWLIST["ProjectedService"]}
    location = {spec.dto_field for spec in ALLOWLIST["ProjectedLocation"]}

    assert body_keys(GrantScope.DIRECTORY) == service | location | {"opening_hours"}
    assert body_keys(GrantScope.CAPACITY) == {s.dto_field for s in ALLOWLIST["ProjectedCapacity"]}
    assert body_keys(GrantScope.CRITERIA) == {s.dto_field for s in ALLOWLIST["ProjectedCriteria"]}


def test_a_key_outside_the_allowlist_is_refused() -> None:
    body = {**_body(GrantScope.DIRECTORY), "reporter_phone": "07700 900123"}

    with pytest.raises(ValidationFailed) as refused:
        from_body(GrantScope.DIRECTORY, body)

    assert "07700" not in str(refused.value)
    assert "reporter_phone" not in str(refused.value)


@pytest.mark.parametrize("kind", list(GrantScope))
def test_a_body_missing_a_key_is_refused(kind: GrantScope) -> None:
    for key in sorted(body_keys(kind)):
        body = _body(kind)
        del body[key]
        with pytest.raises(ValidationFailed):
            from_body(kind, body)


def test_a_name_that_names_a_person_is_refused() -> None:
    body = {**_body(GrantScope.DIRECTORY), "service_name": "Seen by Mrs Smith"}

    with pytest.raises(ValidationFailed):
        from_body(GrantScope.DIRECTORY, body)


def test_a_name_that_is_a_postcode_is_refused() -> None:
    body = {**_body(GrantScope.DIRECTORY), "service_name": "DT4 8XX"}

    with pytest.raises(ValidationFailed):
        from_body(GrantScope.DIRECTORY, body)


def test_a_comment_key_is_refused() -> None:
    for kind in GrantScope:
        with pytest.raises(ValidationFailed):
            from_body(kind, {**_body(kind), "comment": "Both women only"})


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("source_version", "1"),
        ("source_version", True),
        ("active", 1),
        ("category", 5),
        ("category", "not-a-category"),
        ("source", "feed"),
        ("latitude", "52.0"),
        ("opening_hours", "0|all-day"),
        ("opening_hours", ["0|all-day"]),
        ("opening_hours", ("0|all-day", 5)),
        ("opening_hours", ()),
    ],
)
def test_a_value_of_the_wrong_type_or_set_is_refused_without_echoing_it(
    key: str, bad: object
) -> None:
    body = {**_body(GrantScope.DIRECTORY), key: bad}

    with pytest.raises(ValidationFailed) as refused:
        from_body(GrantScope.DIRECTORY, body)

    assert str(bad) not in str(refused.value) or len(str(bad)) < 3


def test_a_capacity_timestamp_that_is_not_iso_with_z_is_refused() -> None:
    for bad in ("2026-10-29 09:00:00", "yesterday", 5, "2026-10-29T09:00:00+01:00"):
        body = {**_body(GrantScope.CAPACITY), "reported_at": bad}
        with pytest.raises(ValidationFailed):
            from_body(GrantScope.CAPACITY, body)


def test_the_body_timestamps_are_iso_8601_with_z_and_dates_are_plain() -> None:
    capacity = _body(GrantScope.CAPACITY)
    criteria = _body(GrantScope.CRITERIA)

    assert capacity["reported_at"] == "2026-10-29T09:00:00Z"
    assert capacity["valid_until"] == "2026-10-29T10:30:00Z"
    assert criteria["review_by"] == "2027-04-29"


def test_the_body_holds_enums_as_their_values_and_tuples_of_text() -> None:
    directory = _body(GrantScope.DIRECTORY)
    criteria = _body(GrantScope.CRITERIA)

    assert directory["category"] == "urgent-community-response"
    assert directory["source"] == "manual"
    assert directory["postal_district"] == "DT4"
    assert directory["opening_hours"] == ("0,1,2,3,4|08:00:00|18:00:00", "5,6|all-day")
    assert criteria["districts"] == ("DT1", "DT4")
    assert criteria["accepts"] == ("fall-no-injury", "frailty")


def test_a_body_has_only_flat_values() -> None:
    for kind in GrantScope:
        for value in _body(kind).values():
            assert isinstance(value, str | int | float | bool | type(None) | tuple)
            if isinstance(value, tuple):
                assert all(isinstance(item, str) for item in value)


def test_a_service_without_location_or_contact_round_trips_with_nones() -> None:
    dto = sample_service_projection(location=None, contact=None)
    body = to_body(dto)

    assert body["location_name"] is None
    assert body["contact_phone"] is None
    assert from_body(GrantScope.DIRECTORY, body) == dto


def test_a_location_with_a_name_missing_but_other_fields_present_is_refused() -> None:
    body = {**_body(GrantScope.DIRECTORY), "location_name": None}

    with pytest.raises(ValidationFailed):
        from_body(GrantScope.DIRECTORY, body)


def test_a_capacity_with_no_report_round_trips() -> None:
    dto = sample_capacity_projection(latest=None, valid_until=None)

    assert from_body(GrantScope.CAPACITY, to_body(dto)) == dto


def test_from_body_runs_the_dto_checks_again() -> None:
    body = {**_body(GrantScope.CAPACITY), "established_capacity": 0}

    with pytest.raises(ValidationFailed):
        from_body(GrantScope.CAPACITY, body)


def test_a_kind_that_is_not_a_grant_scope_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        from_body("directory", _body(GrantScope.DIRECTORY))  # type: ignore[arg-type]


def test_a_body_that_is_not_a_mapping_is_refused() -> None:
    bad_bodies: list[Any] = [None, [], "x", 5]
    for bad in bad_bodies:
        with pytest.raises(ValidationFailed):
            from_body(GrantScope.DIRECTORY, bad)


def test_no_row_has_a_key_outside_the_allowlist_and_the_system_properties() -> None:
    for label, rows in _all_rows().items():
        permitted = {spec.prop for spec in ALLOWLIST[label]} | SYSTEM_PROPERTIES[label]
        for row in rows:
            assert set(row.params) <= permitted


# ---------------------------------------------------------------- windows


@pytest.mark.parametrize(
    ("hour", "text"),
    [
        (
            OpeningHourProjection(
                position=0, days=(0, 1, 4), all_day=False, start=time(8, 0), end=time(18, 30, 15)
            ),
            "0,1,4|08:00:00|18:30:15",
        ),
        (
            OpeningHourProjection(position=3, days=(5, 6), all_day=True, start=None, end=None),
            "5,6|all-day",
        ),
        (
            OpeningHourProjection(
                position=1, days=(0, 1, 2, 3, 4, 5, 6), all_day=False, start=time(20), end=time(8)
            ),
            "0,1,2,3,4,5,6|20:00:00|08:00:00",
        ),
    ],
)
def test_a_window_formats_and_parses_back(hour: OpeningHourProjection, text: str) -> None:
    assert format_window(hour) == text
    assert parse_window(text, hour.position) == hour


@pytest.mark.parametrize(
    "text",
    [
        "",
        "|all-day",
        "0,1|",
        "0,1|08:00:00",
        "0,1|08:00:00|18:00:00|extra",
        "0,1|8:00|18:00",
        "0,1|25:00:00|18:00:00",
        "7|all-day",
        "a|all-day",
        "0,0|all-day",
        "1,0|all-day",
        "0|ALL-DAY",
        "0,1|08:00:00|08:00:00",
        "0 |all-day",
    ],
)
def test_a_window_that_is_not_in_the_documented_form_is_refused(text: str) -> None:
    with pytest.raises(ValidationFailed):
        parse_window(text, 0)


# ---------------------------------------------------------------- 6, 7 and 9. the statement check


def _upsert(label: str) -> str:
    keys = ("tenantId", "sourceTenantId")
    others = [spec.prop for spec in ALLOWLIST.get(label, ())] + sorted(
        SYSTEM_PROPERTIES.get(label, frozenset()) - set(keys)
    )
    merge = ", ".join(f"{key}: ${key}" for key in keys)
    sets = ", ".join(f"n.{prop} = ${prop}" for prop in others)
    return f"MERGE (n:{label} {{{merge}}}) SET {sets}"


VALID_STATEMENTS: dict[str, str] = {
    **{f"upsert {label}": _upsert(label) for label in LABELS},
    "unwind rows": (
        "UNWIND $rows AS row "
        "MERGE (s:ProjectedService {tenantId: $tenant, sourceTenantId: $source, "
        "sourceServiceId: row.sourceServiceId}) "
        "SET s.serviceName = row.serviceName, s.sourceVersion = row.sourceVersion"
    ),
    "on create and on match": (
        "MERGE (s:ProjectedService {tenantId: $tenant, sourceTenantId: $source, "
        "sourceServiceId: $id}) "
        "ON CREATE SET s.serviceName = $name, s.projectedAt = $at "
        "ON MATCH SET s.serviceName = $name, s.projectedAt = $at"
    ),
    "end a source": (
        "MATCH (p:ProjectionSource {tenantId: $tenant, sourceTenantId: $source, kind: $kind}) "
        "SET p.endedAt = $at, p.endReason = $reason"
    ),
    "move a cursor": (
        "MERGE (c:ProjectionCursor {tenantId: $tenant, sourceTenantId: $source, kind: $kind}) "
        "SET c.watermark = $watermark"
    ),
    "read only": "MATCH (s:ProjectedService {tenantId: $tenant}) RETURN s.serviceName AS name",
    "read with properties": (
        "MATCH (s:ProjectedService {tenantId: $tenant}) RETURN properties(s) AS props"
    ),
    "comment hiding a plus-equals": (
        "MATCH (s:ProjectedService {tenantId: $tenant}) // SET s += $p\nSET s.serviceName = $n"
    ),
    "block comment hiding a plus-equals": (
        "MATCH (s:ProjectedService {tenantId: $tenant}) /* SET s += $p */ SET s.serviceName = $n"
    ),
    "plus-equals in a string": (
        "MATCH (s:ProjectedService {tenantId: $tenant}) SET s.serviceName = '+= $p'"
    ),
    "slashes in a string are not a comment": (
        "MATCH (s:ProjectedService {tenantId: $tenant}) SET s.serviceName = 'a//b', "
        "s.sourceVersion = 2"
    ),
    "function call in a set": (
        "MATCH (s:ProjectedService {tenantId: $tenant}) "
        "SET s.serviceName = coalesce($n, s.serviceName), s.sourceVersion = $v"
    ),
    "set after a with": (
        "MATCH (s:ProjectedService {tenantId: $tenant}) WITH s, 1 AS one SET s.sourceVersion = one"
    ),
    "list value": (
        "MATCH (c:ProjectedCriteria {tenantId: $tenant}) "
        "SET c.postcodeDistricts = [d IN $districts | d]"
    ),
    "a read matching a registry label": (
        "MATCH (g:Grant {id: $grant}) MATCH (s:ProjectedService {tenantId: $tenant}) "
        "SET s.grantId = g.id"
    ),
}


@pytest.mark.parametrize("name", sorted(VALID_STATEMENTS))
def test_a_valid_statement_has_no_problems(name: str) -> None:
    assert check_network_write_statement(VALID_STATEMENTS[name]) == []
    assert_network_write_statement(VALID_STATEMENTS[name])


_S = "MATCH (s:ProjectedService {tenantId: $tenant}) "
_ST = "MATCH (s:ProjectedService {tenantId: $tenant}), (t:ProjectedLocation {tenantId: $tenant}) "

INVALID_STATEMENTS: dict[str, tuple[str, str]] = {
    "plus-equals with a parameter": (_S + "SET s += $props", "map-assignment"),
    "equals with a parameter": (_S + "SET s = $props", "map-assignment"),
    "plus-equals with a map": (_S + "SET s += {a: 1}", "map-assignment"),
    "equals with a map": (_S + "SET s = {a: 1}", "map-assignment"),
    "on create plus-equals": (
        "MERGE (s:ProjectedService {tenantId: $tenant, sourceServiceId: $id}) "
        "ON CREATE SET s += $p",
        "map-assignment",
    ),
    "on match plus-equals": (
        "MERGE (s:ProjectedService {tenantId: $tenant, sourceServiceId: $id}) ON MATCH SET s += $p",
        "map-assignment",
    ),
    "a map after a good item": (
        _S + "SET s.serviceName = $n, s += $p",
        "map-assignment",
    ),
    "parameter as the pattern map": ("MERGE (s:ProjectedService $props)", "pattern-parameter-map"),
    "parameter as a create map": ("CREATE (s:ProjectedService $props)", "pattern-parameter-map"),
    "a comment property": (
        _S + "SET s.comment = $c",
        "property-not-allowed:ProjectedService.comment",
    ),
    "a reporter phone property": (
        _S + "SET s.reporterPhone = $p",
        "property-not-allowed:ProjectedService.reporterPhone",
    ),
    "a phone in a create map": (
        "CREATE (:ProjectedService {phone: $p})",
        "property-not-allowed:ProjectedService.phone",
    ),
    "a phone in a merge map": (
        "MERGE (s:ProjectedService {tenantId: $tenant, phone: $p})",
        "property-not-allowed:ProjectedService.phone",
    ),
    "a property of another label": (
        "MATCH (l:ProjectedLocation {tenantId: $tenant}) SET l.serviceName = $n",
        "property-not-allowed:ProjectedLocation.serviceName",
    ),
    "a source property on a cursor": (
        "MATCH (c:ProjectionCursor {tenantId: $tenant}) SET c.endReason = $r",
        "property-not-allowed:ProjectionCursor.endReason",
    ),
    "a tenant label in a merge": (
        "MERGE (x:Practitioner {id: $i})",
        "label-not-allowed:Practitioner",
    ),
    "a tenant label in a create": (
        "CREATE (x:HealthcareService {id: $i})",
        "label-not-allowed:HealthcareService",
    ),
    "a tenant label in a set": (
        "MATCH (x:HealthcareService {tenantId: $tenant}) SET x.name = $n",
        "label-not-allowed:HealthcareService",
    ),
    "a registry label written": (
        "MATCH (g:Grant {id: $grant}) SET g.status = 'ended'",
        "label-not-allowed:Grant",
    ),
    "a label assignment": (_S + "SET s:Extra", "label-assignment"),
    "a computed property name": (_S + "SET s[$k] = $v", "dynamic-property"),
    "a backticked property": (_S + "SET s.`serviceName` = $n", "dynamic-property"),
    "a backtick anywhere": (_S + "SET s.serviceName = $n RETURN s.`x`", "dynamic-property"),
    "an apoc call": (_S + "CALL apoc.create.setProperties(s, $k, $v)", "call-not-allowed"),
    "a plain call": ("CALL db.labels()", "call-not-allowed"),
    "a call subquery": (_S + "CALL { WITH s SET s.sourceVersion = 1 }", "call-not-allowed"),
    "an apoc name in an expression": (
        _S + "SET s.serviceName = apoc.text.join($a, ',')",
        "call-not-allowed",
    ),
    "a foreach over keys": (
        _S + "FOREACH (k IN keys($m) | SET s[k] = $m[k])",
        "dynamic-property",
    ),
    "keys of a node": (_S + "SET s.sourceVersion = 1 RETURN keys(s)", "dynamic-property"),
    "properties of a node": (
        _S + "SET s.sourceVersion = 1 RETURN properties(s)",
        "dynamic-property",
    ),
    "a detach delete": (_S + "DETACH DELETE s", "delete-not-allowed"),
    "a delete": (_S + "DELETE s", "delete-not-allowed"),
    "a remove": (_S + "REMOVE s.serviceName", "delete-not-allowed"),
    "a relationship with properties": (
        _ST + "MERGE (s)-[:KNOWS {x: 1}]->(t)",
        "relationship-properties",
    ),
    "a relationship that is not listed": (
        _ST + "MERGE (s)-[:UNLISTED]->(t)",
        "relationship-not-allowed:UNLISTED",
    ),
    "a created relationship that is not listed": (
        _ST + "CREATE (s)-[:UNLISTED]->(t)",
        "relationship-not-allowed:UNLISTED",
    ),
    "a set on a relationship": (
        _ST + "MATCH (s)-[r:HAS_LOCATION]->(t) SET r.x = 1",
        "relationship-properties",
    ),
    "an unbound variable": (_S + "SET z.serviceName = $n", "unknown-variable"),
    "an unbound variable in a merge": (
        "MERGE (s)-[:HAS_LOCATION]->(t)",
        "unknown-variable",
    ),
    "a variable with no label": (
        "MATCH (s {tenantId: $tenant}) SET s.serviceName = $n",
        "unlabelled-variable",
    ),
    "plus-equals after a line comment": (
        _S + "SET s.serviceName = $n // a note\nSET s += $p",
        "map-assignment",
    ),
    "plus-equals after a block comment": (
        _S + "SET s.serviceName = $n /* note \n */ , s += $p",
        "map-assignment",
    ),
    "a call after a string that looks like a comment": (
        _S + "SET s.serviceName = 'http://x' CALL db.labels()",
        "call-not-allowed",
    ),
    "a lower case set of a map": (
        "match (s:ProjectedService {tenantId: $tenant}) set s += $p",
        "map-assignment",
    ),
    "two labels on a node": (
        "MERGE (s:ProjectedService:ProjectedLocation {tenantId: $tenant})",
        "multiple-labels",
    ),
    "a truncated statement": (_S + "SET s.serviceName =", "unparseable"),
    "an open parenthesis": ("MATCH (s:ProjectedService {tenantId: $tenant", "unparseable"),
    "an unclosed string": (_S + "SET s.serviceName = 'abc", "unparseable"),
    "an unclosed block comment": (_S + "SET s.serviceName = $n /* abc", "unparseable"),
    "an empty statement": ("", "unparseable"),
    "only a comment": ("// nothing", "unparseable"),
    "an unknown first word": ("FROBNICATE (s)", "unparseable"),
    "an extra close bracket": (_S + "SET s.serviceName = $n)", "unparseable"),
}


@pytest.mark.parametrize("name", sorted(INVALID_STATEMENTS))
def test_an_invalid_statement_gets_the_named_code(name: str) -> None:
    cypher, code = INVALID_STATEMENTS[name]

    problems = check_network_write_statement(cypher)

    assert code in problems, problems


def test_the_check_fails_closed_on_an_unreadable_statement_and_says_only_that() -> None:
    assert check_network_write_statement("MATCH (s:ProjectedService {tenantId: $tenant")[:1] == [
        "unparseable"
    ]


def test_a_statement_that_is_valid_alone_is_refused_when_a_bad_clause_follows() -> None:
    problems = check_network_write_statement(
        VALID_STATEMENTS["upsert ProjectedService"] + " SET n += $p"
    )

    assert problems == ["map-assignment"]


def test_each_problem_is_reported_once_per_cause_in_a_stable_order() -> None:
    cypher = _S + "SET s += $p, s.comment = $c, s:Extra"

    first = check_network_write_statement(cypher)
    second = check_network_write_statement(cypher)

    assert first == second
    assert first == sorted(set(first), key=first.index)
    assert {
        "map-assignment",
        "property-not-allowed:ProjectedService.comment",
        "label-assignment",
    } <= set(first)


def test_a_relationship_type_that_a_later_task_lists_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(domain_projection, "NETWORK_RELATIONSHIPS", frozenset({"HAS_LOCATION"}))
    statement = _ST + "MERGE (s)-[:HAS_LOCATION]->(t)"

    assert check_network_write_statement(statement) == []
    assert check_network_write_statement(_ST + "MERGE (s)-[:OTHER]->(t)") == [
        "relationship-not-allowed:OTHER"
    ]


def test_a_relationship_type_is_matched_case_sensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(domain_projection, "NETWORK_RELATIONSHIPS", frozenset({"HAS_LOCATION"}))

    assert check_network_write_statement(_ST + "MERGE (s)-[:has_location]->(t)") == [
        "relationship-not-allowed:has_location"
    ]


def test_a_read_of_a_relationship_is_not_a_write() -> None:
    assert (
        check_network_write_statement(
            _ST + "MATCH (s)-[:UNLISTED {x: 1}]->(t) RETURN s.serviceName"
        )
        == []
    )


@pytest.mark.parametrize("name", sorted(INVALID_STATEMENTS))
def test_assert_raises_with_the_codes_and_not_the_statement_text(name: str) -> None:
    cypher, code = INVALID_STATEMENTS[name]

    with pytest.raises(ValidationFailed) as refused:
        assert_network_write_statement(cypher)

    text = str(refused.value)
    assert code in text
    assert "MATCH" not in text and "MERGE" not in text and "$tenant" not in text


def test_the_two_functions_agree_on_a_valid_statement() -> None:
    statement = VALID_STATEMENTS["upsert ProjectedCapacity"]

    assert check_network_write_statement(statement) == []
    assert_network_write_statement(statement)


def test_the_statement_check_reads_the_relationship_list_at_call_time() -> None:
    assert "NETWORK_RELATIONSHIPS" in inspect.getsource(projection_module)


# ---------------------------------------------------------------- 8. properties (Hypothesis)

_PREFIX = "ZZPLANTED"
_planted = st.text(
    alphabet=st.characters(exclude_categories=["Cs"], exclude_characters="\x00"),
    min_size=0,
    max_size=30,
).map(lambda text: f"{_PREFIX}-{text}")
_plain_name = (
    st.from_regex(r"[A-Za-z][A-Za-z ']{0,40}", fullmatch=True)
    .map(str.strip)
    .filter(lambda text: bool(text) and not find_patient_data(text))
)


@settings(max_examples=150, deadline=None)
@given(
    comment=_planted,
    reason=_planted,
    role=_planted,
    supersedes=_planted,
    derived=_planted,
    name=_plain_name,
    unit=_plain_name,
    value=st.integers(0, 40),
    confirmed=st.integers(0, 5),
    capacity=st.integers(1, 40),
    percent=st.integers(1, 100),
    version=st.integers(1, 10**12),
)
def test_planted_text_never_reaches_rows_or_bodies_and_the_keys_stay_exact(
    comment: str,
    reason: str,
    role: str,
    supersedes: str,
    derived: str,
    name: str,
    unit: str,
    value: int,
    confirmed: int,
    capacity: int,
    percent: int,
    version: int,
) -> None:
    profile = sample_profile(
        comment=comment,
        name=name,
        unit_label=unit,
        established_capacity=capacity,
        usual_range=(0, capacity),
        limited_level_percent=percent,
    )
    report = sample_report(value=value, performer_role_id=role, derived_from=derived)
    criteria = sample_criteria(change_reason=reason, owner_role_id=role, supersedes_id=supersedes)
    service = build_service_projection(
        profile, source_version=version, location=sample_location(), contact=sample_contact()
    )
    capacity_dto = build_capacity_projection(
        profile,
        report,
        confirmed_since=confirmed,
        policy=sample_policy(),
        source_version=version,
        valid_until=None,
    )
    criteria_dto = build_criteria_projection(criteria)

    for dto, kind in (
        (service, GrantScope.DIRECTORY),
        (capacity_dto, GrantScope.CAPACITY),
        (criteria_dto, GrantScope.CRITERIA),
    ):
        text = "".join(flatten(to_rows(dto)) + flatten(to_body(dto)))
        assert _PREFIX not in text
        assert set(to_body(dto)) == body_keys(kind)
        assert from_body(kind, to_body(dto)) == dto
        for row in to_rows(dto):
            assert [*row.params] == [spec.prop for spec in ALLOWLIST[row.label]]


_identifier = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,24}", fullmatch=True)


@settings(max_examples=200, deadline=None)
@given(_identifier)
def test_a_set_of_a_property_is_accepted_only_when_the_allowlist_names_it(prop: str) -> None:
    allowed = {spec.prop for spec in ALLOWLIST["ProjectedService"]} | SYSTEM_PROPERTIES[
        "ProjectedService"
    ]
    statement = f"MATCH (s:ProjectedService {{tenantId: $tenant}}) SET s.{prop} = $x"

    problems = check_network_write_statement(statement)

    if prop in allowed:
        assert problems == []
    else:
        assert f"property-not-allowed:ProjectedService.{prop}" in problems


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 1000))
def test_every_allowlisted_capacity_property_can_be_set(index: int) -> None:
    specs = ALLOWLIST["ProjectedCapacity"]
    spec = specs[index % len(specs)]
    statement = f"MATCH (c:ProjectedCapacity {{tenantId: $tenant}}) SET c.{spec.prop} = $x"

    assert check_network_write_statement(statement) == []


# ---------------------------------------------------------------- the measure of the sample


def test_the_sample_capacity_uses_a_free_count_measure() -> None:
    assert sample_capacity_projection().measure is Measure.REFERRALS_ACCEPTABLE
