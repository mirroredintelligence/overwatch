"""The projection allowlist's DTOs, builders and the read-time status (TEN-052).

Rules: DEC-132 items 4 and 7, DEC-134 items 6 to 8, DEC-136 item 3, hazards H-N01, H-N06, H-N07.
Every value is invented (`UCR West`, `DT4 8XX`, `Sampletown`); the probes that look like patient
data are probes on purpose, so the guard can be seen to refuse them. The statement check and the
sentinel scan are in tests/unit/application/test_projection_allowlist.py; the board is in
test_network_board.py.
"""

from collections.abc import Callable
from dataclasses import fields, replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from diucs.domain.codes import (
    Cadence,
    Channel,
    CriteriaStatus,
    Measure,
    NeedCategory,
    ReportSource,
    ReportType,
    ServiceCategory,
    Status,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.capacity import CapacityReport
from diucs.domain.model.network import DirectorySource, GrantScope, ListingStatus
from diucs.domain.model.service import AvailableTime
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.rules.network_board import compute_network_state, status_inputs
from diucs.domain.rules.projection import (
    CapacityProjection,
    CriteriaProjection,
    LocationInputs,
    LocationProjection,
    OpeningHourProjection,
    ServiceContactInputs,
    ServiceProjection,
    build_capacity_projection,
    build_criteria_projection,
    build_service_projection,
    supersedes,
)
from diucs.domain.rules.status import compute_status
from tests.support.projection_samples import (
    NOW,
    REPORTED_AT,
    SERVICE_ID,
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

# ---------------------------------------------------------------- the service builder (test 10)


def test_a_service_comment_leaves_no_trace_in_the_projection() -> None:
    dto = sample_service_projection(profile=sample_profile(comment="Both women only"))

    assert "Both women" not in repr(dto)
    assert dto.service_name == "UCR West"
    assert dto.category is ServiceCategory.URGENT_COMMUNITY_RESPONSE


def test_the_source_is_manual_when_it_is_left_out() -> None:
    dto = build_service_projection(sample_profile(), source_version=1, location=None, contact=None)

    assert dto.source is DirectorySource.MANUAL


def test_the_directory_of_services_source_round_trips() -> None:
    dto = sample_service_projection(source=DirectorySource.DIRECTORY_OF_SERVICES)

    assert dto.source is DirectorySource.DIRECTORY_OF_SERVICES


@pytest.mark.parametrize("bad", ["manual", ListingStatus.PENDING, ReportSource.TEXT, None, 1])
def test_a_source_that_is_not_a_directory_source_is_refused(bad: object) -> None:
    with pytest.raises(ValidationFailed):
        sample_service_projection(source=bad)


def test_a_service_category_of_another_enum_is_refused() -> None:
    dto = sample_service_projection()

    with pytest.raises(ValidationFailed):
        replace(dto, category=CriteriaStatus.CURRENT)
    with pytest.raises(ValidationFailed):
        replace(dto, category="urgent-community-response")


def test_the_source_version_is_a_whole_number_of_at_least_one() -> None:
    for bad in (0, -1, True, 1.0, None):
        with pytest.raises(ValidationFailed):
            sample_service_projection(source_version=bad)
    assert sample_service_projection(source_version=1).source_version == 1


def test_the_active_flag_is_carried() -> None:
    assert sample_service_projection(profile=sample_profile(active=False)).active is False
    assert sample_service_projection(profile=sample_profile(active=True)).active is True


def test_opening_hours_are_one_per_window_in_order() -> None:
    dto = sample_service_projection()

    assert [hour.position for hour in dto.opening_hours] == [0, 1]
    assert dto.opening_hours[0] == OpeningHourProjection(
        position=0, days=(0, 1, 2, 3, 4), all_day=False, start=time(8, 0), end=time(18, 0)
    )
    assert dto.opening_hours[1] == OpeningHourProjection(
        position=1, days=(5, 6), all_day=True, start=None, end=None
    )


def test_opening_hours_that_skip_a_position_are_refused() -> None:
    dto = sample_service_projection()
    skipped = (replace(dto.opening_hours[0], position=1),)

    with pytest.raises(ValidationFailed):
        replace(dto, opening_hours=skipped)


def test_a_service_with_no_opening_hours_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        replace(sample_service_projection(), opening_hours=())


@pytest.mark.parametrize(
    "bad",
    [
        {"days": ()},
        {"days": (7,)},
        {"days": (-1,)},
        {"days": (True,)},
        {"days": "01"},
        {"all_day": True},  # all-day with a start and an end
        {"start": None},  # timed with no start
        {"end": None},
        {"end": time(8, 0)},  # end equals start
        {"start": datetime(2026, 1, 1, 8, 0)},
        {"start": time(8, 0, tzinfo=UTC)},
        {"position": -1},
        {"position": True},
    ],
)
def test_an_opening_hour_that_breaks_a_rule_is_refused(bad: dict[str, Any]) -> None:
    good = OpeningHourProjection(
        position=0, days=(0, 1), all_day=False, start=time(8, 0), end=time(18, 0)
    )

    with pytest.raises(ValidationFailed):
        replace(good, **bad)


def test_opening_hour_days_are_sorted_and_deduplicated_into_a_tuple() -> None:
    hour = OpeningHourProjection(
        position=0,
        days=[4, 0, 2, 2],
        all_day=True,
        start=None,
        end=None,  # type: ignore[arg-type]
    )

    assert hour.days == (0, 2, 4)


# ---------------------------------------------------------------- location (test 11)


def test_the_full_postcode_becomes_its_district_and_appears_nowhere() -> None:
    dto = sample_service_projection()

    assert dto.location is not None
    assert dto.location.postal_district == "DT4"
    assert "8XX" not in repr(dto)


@pytest.mark.parametrize("raw", ["not a postcode", "", "12345", "DT4 8", "Mrs Smith"])
def test_a_postcode_that_is_not_one_gives_no_district_and_is_never_copied(raw: str) -> None:
    location = LocationInputs("UCR West base", raw, "Sampletown", None, None)

    dto = sample_service_projection(location=location)

    assert dto.location is not None
    assert dto.location.postal_district is None
    assert raw not in repr(dto) or raw == ""


def test_a_bare_district_is_accepted_as_it_is() -> None:
    location = LocationInputs("UCR West base", " dt4 ", None, None, None)

    dto = sample_service_projection(location=location)

    assert dto.location is not None
    assert dto.location.postal_district == "DT4"


@pytest.mark.parametrize(
    ("latitude", "longitude"), [(91.0, 0.0), (-91.0, 0.0), (0.0, 181.0), (0.0, -181.0)]
)
def test_a_position_out_of_range_is_refused(latitude: float, longitude: float) -> None:
    location = LocationInputs("UCR West base", "DT4 8XX", None, latitude, longitude)

    with pytest.raises(ValidationFailed):
        sample_service_projection(location=location)


def test_a_position_with_only_one_coordinate_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        sample_service_projection(
            location=LocationInputs("UCR West base", "DT4 8XX", None, 52.0, None)
        )


def test_a_position_that_is_not_a_float_is_refused() -> None:
    for bad in ("52.0", True, float("nan"), float("inf")):
        with pytest.raises(ValidationFailed):
            sample_service_projection(
                location=LocationInputs("UCR West base", "DT4 8XX", None, bad, 1.0)  # type: ignore[arg-type]
            )


def test_a_location_has_no_street_line_input() -> None:
    names = {field.name for field in fields(LocationInputs)}

    assert names == {"name", "postcode", "city", "latitude", "longitude"}
    assert {field.name for field in fields(LocationProjection)} == {
        "location_name",
        "postal_district",
        "city",
        "latitude",
        "longitude",
    }


def test_no_location_is_allowed() -> None:
    assert sample_service_projection(location=None).location is None


# ---------------------------------------------------------------- contact (test 12)


@pytest.mark.parametrize(
    "label", ["Mrs Smith", "Duty <desk>", "desk@example.test", "943 476 5919", "DT4 8XX", "a" * 61]
)
def test_a_contact_label_with_patient_or_markup_shape_is_refused(label: str) -> None:
    with pytest.raises(ValidationFailed):
        sample_service_projection(contact=ServiceContactInputs(label, "0300 123 4567"))


@pytest.mark.parametrize(
    "phone",
    ["943 476 5919", "9434765919", "abc", "03", "0300 123 4567 8901 2345", "+", "0300-123-4567"],
)
def test_a_contact_phone_with_the_wrong_shape_is_refused(phone: str) -> None:
    with pytest.raises(ValidationFailed):
        sample_service_projection(contact=ServiceContactInputs("Duty desk", phone))


@pytest.mark.parametrize("phone", ["0300 123 4567", "+44 1234 567890", "01234 567890"])
def test_a_switchboard_style_phone_builds(phone: str) -> None:
    dto = sample_service_projection(contact=ServiceContactInputs("Duty desk", phone))

    assert dto.contact_phone == phone
    assert dto.contact_label == "Duty desk"


def test_no_contact_gives_two_nones() -> None:
    dto = sample_service_projection(contact=None)

    assert (dto.contact_label, dto.contact_phone) == (None, None)


# ---------------------------------------------------------------- every str field (test 13)

PROBES = ["DT4 8XX", "943 476 5919", "Mrs Smith", "a@b.example", "<b>x</b>", "x" * 500, "", "a\nb"]


def _service(**changes: Any) -> Any:
    return replace(sample_service_projection(), **changes)


def _location(**changes: Any) -> Any:
    location = sample_service_projection().location
    assert location is not None
    return replace(location, **changes)


STRING_FIELDS: list[tuple[str, Callable[..., Any]]] = [
    ("source_service_id", _service),
    ("service_name", _service),
    ("contact_label", _service),
    ("contact_phone", _service),
    ("location_name", _location),
    ("city", _location),
    ("unit_label", lambda **c: replace(sample_capacity_projection(), **c)),
    ("source_service_id", lambda **c: replace(sample_capacity_projection(), **c)),
    ("report_id", lambda **c: replace(sample_capacity_projection(), **c)),
    ("source_criteria_id", lambda **c: replace(sample_criteria_projection(), **c)),
    ("source_service_id", lambda **c: replace(sample_criteria_projection(), **c)),
]


@pytest.mark.parametrize(("field", "make"), STRING_FIELDS)
@pytest.mark.parametrize("probe", PROBES)
def test_every_text_field_refuses_each_probe(
    field: str, make: Callable[..., Any], probe: str
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        make(**{field: probe})

    assert probe not in str(refused.value) or probe == ""


@pytest.mark.parametrize(("field", "make"), STRING_FIELDS)
def test_every_text_field_refuses_a_value_that_is_not_text(
    field: str, make: Callable[..., Any]
) -> None:
    for bad in (1, b"x", ["x"], object()):
        with pytest.raises(ValidationFailed):
            make(**{field: bad})


def test_a_text_field_may_hold_the_plain_characters_of_a_name() -> None:
    dto = sample_service_projection(profile=sample_profile(name="St Mary's (West) & Co. 24/7"))

    assert dto.service_name == "St Mary's (West) & Co. 24/7"


def test_a_district_that_is_not_a_district_is_refused() -> None:
    dto = sample_criteria_projection()

    for bad in (("DT4 8XX",), ("dt4",), ("",), (" DT4",), ("Mrs Smith",), "DT4"):
        with pytest.raises(ValidationFailed):
            replace(dto, districts=bad)


# ---------------------------------------------------------------- capacity (test 14)


def test_no_report_gives_three_nones() -> None:
    dto = build_capacity_projection(
        sample_profile(),
        None,
        confirmed_since=0,
        policy=DEFAULT_POLICY,
        source_version=5,
        valid_until=None,
    )

    assert (dto.report_id, dto.reported_at, dto.value) == (None, None, None)
    assert dto.valid_until is None


def test_a_report_for_another_service_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        sample_capacity_projection(latest=sample_report(service_id="svc-2"))


def test_a_report_with_another_measure_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        sample_capacity_projection(latest=sample_report(measure=Measure.FREE_BEDS))


@pytest.mark.parametrize("bad", [-1, True, 1.5, None, "1"])
def test_confirmed_since_is_a_whole_count(bad: object) -> None:
    with pytest.raises(ValidationFailed):
        sample_capacity_projection(confirmed_since=bad)


def test_the_capacity_projection_has_no_status_and_no_booking_or_comment_field() -> None:
    names = {field.name for field in fields(CapacityProjection)}

    for absent in (
        "status",
        "effective_available",
        "pending",
        "pending_count",
        "comment",
        "next_due",
        "performer_role_id",
        "derived_from",
        "source",
        "report_type",
        "usual_range",
        "channel",
    ):
        assert absent not in names


def test_the_capacity_inputs_come_from_the_profile_report_and_policy() -> None:
    policy = sample_policy(
        reply_window=timedelta(minutes=45),
        reminder_after=timedelta(minutes=45),
        phone_task_after=timedelta(minutes=75),
        escalate_after=timedelta(minutes=105),
        stale_warning_after=timedelta(hours=3),
    )

    dto = sample_capacity_projection(policy=policy, confirmed_since=2)

    assert dto.source_service_id == SERVICE_ID
    assert dto.measure is Measure.REFERRALS_ACCEPTABLE
    assert dto.unit_label == "referrals in the next 2 hrs"
    assert dto.established_capacity == 10
    assert dto.can_exceed_established is False
    assert dto.limited_level_percent == 80
    assert dto.cadence is Cadence.EVERY_2_HRS
    assert dto.suspended is False
    assert (dto.report_id, dto.reported_at, dto.value) == ("rep-1", REPORTED_AT, 4)
    assert dto.confirmed_since == 2
    assert dto.reply_window_minutes == 45
    assert dto.stale_warning_hours == 3


def test_a_suspended_profile_is_carried_as_the_flag_only() -> None:
    assert sample_capacity_projection(profile=sample_profile(suspended=True)).suspended is True


def test_a_policy_that_is_not_a_policy_is_refused() -> None:
    for bad in (None, {"reply_window": 30}, "default"):
        with pytest.raises(ValidationFailed):
            sample_capacity_projection(policy=bad)


def test_a_reply_window_that_is_not_whole_minutes_is_refused() -> None:
    """TenantPolicy already refuses it; the builder does not rely on that (defence in depth)."""
    policy = sample_policy()
    object.__setattr__(policy, "reply_window", timedelta(minutes=30, seconds=30))

    with pytest.raises(ValidationFailed):
        sample_capacity_projection(policy=policy)


def test_a_stale_limit_that_is_not_whole_hours_is_refused() -> None:
    policy = sample_policy()
    object.__setattr__(policy, "stale_warning_after", timedelta(hours=2, minutes=30))

    with pytest.raises(ValidationFailed):
        sample_capacity_projection(policy=policy)


@pytest.mark.parametrize("minutes", [14, 61, 0, -15])
def test_a_reply_window_outside_the_policy_bounds_is_refused_on_the_dto(minutes: int) -> None:
    with pytest.raises(ValidationFailed):
        replace(sample_capacity_projection(), reply_window_minutes=minutes)


@pytest.mark.parametrize("hours", [0, 5, -1])
def test_a_stale_limit_outside_the_policy_bounds_is_refused_on_the_dto(hours: int) -> None:
    with pytest.raises(ValidationFailed):
        replace(sample_capacity_projection(), stale_warning_hours=hours)


@pytest.mark.parametrize(
    "changes",
    [
        {"report_id": None},  # a report id with no time or value
        {"reported_at": None},
        {"value": None},
        {"report_id": None, "reported_at": None},
    ],
)
def test_a_report_is_all_there_or_all_absent(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed):
        replace(sample_capacity_projection(), **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"established_capacity": 0},
        {"limited_level_percent": 0},
        {"limited_level_percent": 101},
        {"value": -1},
        {"confirmed_since": -1},
        {"source_version": 0},
        {"measure": "free-slots"},
        {"cadence": Measure.FREE_BEDS},
        {"suspended": 1},
        {"can_exceed_established": "no"},
        {"reported_at": datetime(2026, 10, 29, 9, 0)},
        {"valid_until": datetime(2026, 10, 29, 9, 0)},
    ],
)
def test_a_capacity_value_out_of_range_or_of_the_wrong_type_is_refused(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationFailed):
        replace(sample_capacity_projection(), **changes)


def test_instants_are_held_in_utc() -> None:
    reported = datetime(2026, 10, 29, 10, 0, tzinfo=timezone(timedelta(hours=1)))

    dto = sample_capacity_projection(latest=sample_report(effective_at=reported))

    assert dto.reported_at == REPORTED_AT
    assert dto.reported_at is not None
    assert dto.reported_at.utcoffset() == timedelta(0)


# ---------------------------------------------------------------- criteria (test 15)


def test_a_current_version_builds_with_sorted_tuples() -> None:
    dto = sample_criteria_projection()

    assert dto.districts == ("DT1", "DT4")
    assert dto.accepts == (NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY)
    assert dto.excludes == (NeedCategory.IV_THERAPY,)
    assert dto.version == 3
    assert dto.source_criteria_id == "crit-1"
    assert dto.source_service_id == SERVICE_ID
    assert dto.age_min == 18
    assert dto.age_max is None
    assert dto.review_by == date(2027, 4, 29)


@pytest.mark.parametrize(
    "status",
    [
        CriteriaStatus.PENDING_APPROVAL,
        CriteriaStatus.DRAFT,
        CriteriaStatus.SUPERSEDED,
        CriteriaStatus.RETIRED,
    ],
)
def test_a_version_that_is_not_current_is_refused(status: CriteriaStatus) -> None:
    with pytest.raises(ValidationFailed):
        build_criteria_projection(sample_criteria(status=status))


def test_a_status_from_another_enum_with_the_value_current_is_refused() -> None:
    criteria = sample_criteria()
    object.__setattr__(criteria, "status", ListingStatus.ADMITTED)
    with pytest.raises(ValidationFailed):
        build_criteria_projection(criteria)

    object.__setattr__(criteria, "status", "current")
    with pytest.raises(ValidationFailed):
        build_criteria_projection(criteria)


def test_the_workflow_fields_never_reach_the_criteria_projection() -> None:
    names = {field.name for field in fields(CriteriaProjection)}

    for absent in ("change_reason", "owner_role_id", "supersedes_id", "status", "review_months"):
        assert absent not in names
    dto = sample_criteria_projection()
    assert "Added frailty" not in repr(dto)
    assert "role-2" not in repr(dto)
    assert "crit-0" not in repr(dto)


def test_the_ordering_value_of_criteria_is_its_version() -> None:
    assert sample_criteria_projection(criteria=sample_criteria(version=9)).version == 9


def test_accepted_and_excluded_needs_are_exact_need_categories() -> None:
    dto = sample_criteria_projection()

    for bad in (("frailty",), (GrantScope.CAPACITY,), "frailty", (1,)):
        with pytest.raises(ValidationFailed):
            replace(dto, accepts=bad)
    with pytest.raises(ValidationFailed):
        replace(dto, excludes=dto.accepts)


@pytest.mark.parametrize(
    "changes",
    [{"age_min": -1}, {"age_max": 5}, {"version": 0}, {"review_by": datetime(2027, 1, 1)}],
)
def test_criteria_numbers_and_dates_are_range_checked(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationFailed):
        replace(sample_criteria_projection(), **changes)


def test_a_datetime_does_not_pass_as_a_review_date() -> None:
    with pytest.raises(ValidationFailed):
        replace(sample_criteria_projection(), review_by=datetime(2027, 1, 1, 9, 0, tzinfo=UTC))


# ---------------------------------------------------------------- immutability


def test_a_dto_is_frozen_and_holds_no_mutable_value() -> None:
    for dto in (
        sample_service_projection(),
        sample_capacity_projection(),
        sample_criteria_projection(),
    ):
        with pytest.raises((AttributeError, TypeError)):
            dto.__dict__  # slots: there is no instance dict  # noqa: B018
        for value in (getattr(dto, field.name) for field in fields(dto)):
            assert not isinstance(value, list | set | dict)


def test_a_list_given_to_a_dto_is_copied_into_a_sorted_tuple() -> None:
    dto = replace(
        sample_criteria_projection(),
        districts=["DT4", "DT1"],  # type: ignore[arg-type]
        accepts=[NeedCategory.FRAILTY, NeedCategory.DEMENTIA],  # type: ignore[arg-type]
    )

    assert dto.districts == ("DT1", "DT4")
    assert dto.accepts == (NeedCategory.DEMENTIA, NeedCategory.FRAILTY)


# ---------------------------------------------------------------- supersedes (test 16)


def test_a_first_write_is_accepted() -> None:
    assert supersedes(None, 1) is True


def test_an_equal_version_is_accepted_so_a_replay_is_idempotent() -> None:
    assert supersedes(7, 7) is True


def test_an_older_version_never_replaces_a_newer_one() -> None:
    assert supersedes(7, 6) is False


def test_a_newer_version_replaces() -> None:
    assert supersedes(7, 8) is True


@given(st.one_of(st.none(), st.integers(1, 10**13)), st.integers(1, 10**13))
def test_supersedes_is_incoming_not_below_stored(stored: int | None, incoming: int) -> None:
    assert supersedes(stored, incoming) is (stored is None or incoming >= stored)


@pytest.mark.parametrize("bad", [(True, 1), (1, True), ("1", 1), (1, 1.5), (1, 0), (0, 1)])
def test_supersedes_refuses_versions_that_are_not_whole_numbers_of_one_or_more(
    bad: tuple[object, object],
) -> None:
    with pytest.raises(ValidationFailed):
        supersedes(*bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------- equivalence (tests 17 and 18)

_BASES = (
    datetime(2026, 3, 28, 22, 0, tzinfo=UTC),  # the day before the spring change
    datetime(2026, 3, 29, 0, 0, tzinfo=UTC),  # the change day
    datetime(2026, 10, 24, 22, 0, tzinfo=UTC),
    datetime(2026, 10, 25, 0, 0, tzinfo=UTC),  # the autumn change
    datetime(2026, 10, 29, 6, 0, tzinfo=UTC),
    datetime(2026, 11, 2, 21, 0, tzinfo=UTC),
)
_WINDOWS = (
    (AvailableTime.weekdays(time(8, 0), time(18, 0)), AvailableTime.every_day_all_day()),
    (AvailableTime.every_day_all_day(),),
    (AvailableTime.every_day(time(20, 0), time(8, 0)),),
    (
        AvailableTime.weekdays(time(8, 0), time(12, 0)),
        AvailableTime.weekdays(time(13, 0), time(20, 0)),
        AvailableTime(days=frozenset({5}), all_day=True, start=None, end=None),
    ),
)
_MEASURES = (Measure.REFERRALS_ACCEPTABLE, Measure.OCCUPIED_PATIENTS, Measure.FREE_BEDS)


def _ladder(policy_reply: int, shift: int) -> dict[str, timedelta]:
    reply = timedelta(minutes=policy_reply)
    reminder = max(DEFAULT_POLICY.reminder_after, reply) + timedelta(minutes=shift)
    return {
        "reminder_after": reminder,
        "phone_task_after": reminder + timedelta(minutes=30),
        "escalate_after": reminder + timedelta(minutes=60),
    }


@st.composite
def _scenarios(draw: st.DrawFn) -> dict[str, Any]:
    measure = draw(st.sampled_from(_MEASURES))
    established = draw(st.integers(1, 20))
    now = draw(st.sampled_from(_BASES)) + timedelta(minutes=draw(st.integers(0, 1700)))
    has_report = draw(st.booleans())
    age = timedelta(minutes=draw(st.integers(0, 900)))
    confirmed = draw(st.integers(0, 4)) if has_report else 0
    return {
        "measure": measure,
        "established": established,
        "can_exceed": draw(st.booleans()),
        "limited": draw(st.integers(1, 100)),
        "cadence": draw(st.sampled_from(list(Cadence))),
        "windows": draw(st.sampled_from(_WINDOWS)),
        "suspended": draw(st.integers(0, 9)) == 0,
        "now": now,
        "report": ({"value": draw(st.integers(0, 30)), "at": now - age} if has_report else None),
        "confirmed": confirmed,
        "reply": draw(st.integers(15, 60)),
        "stale": draw(st.integers(1, 4)),
        "ladder_shift": draw(st.integers(0, 20)),
        "usual_high": draw(st.integers(0, 50)),
        "channel": draw(st.sampled_from(list(Channel))),
        "comment": draw(st.text(max_size=12)),
        "source": draw(st.sampled_from(list(ReportSource))),
    }


def _source_side(scenario: dict[str, Any]) -> tuple[Any, Any, list[datetime], Any]:
    profile = sample_profile(
        measure=scenario["measure"],
        established_capacity=scenario["established"],
        can_exceed_established=scenario["can_exceed"],
        limited_level_percent=scenario["limited"],
        cadence=scenario["cadence"],
        available_times=scenario["windows"],
        suspended=scenario["suspended"],
        usual_range=(0, scenario["usual_high"]),
        channel=scenario["channel"],
        comment=scenario["comment"],
    )
    report = None
    confirmed_at: list[datetime] = []
    if scenario["report"] is not None:
        report = sample_report(
            measure=scenario["measure"],
            value=scenario["report"]["value"],
            effective_at=scenario["report"]["at"],
            source=scenario["source"],
            report_type=ReportType.NUMBER,
        )
        confirmed_at = [scenario["report"]["at"] + timedelta(minutes=1)] * scenario["confirmed"]
    policy = sample_policy(
        reply_window=timedelta(minutes=scenario["reply"]),
        stale_warning_after=timedelta(hours=scenario["stale"]),
        **_ladder(scenario["reply"], scenario["ladder_shift"]),
    )
    return profile, report, confirmed_at, policy


@settings(max_examples=300, deadline=None)
@given(_scenarios())
def test_the_network_state_equals_the_status_computed_on_the_source(
    scenario: dict[str, Any],
) -> None:
    profile, report, confirmed_at, policy = _source_side(scenario)
    capacity = build_capacity_projection(
        profile,
        report,
        confirmed_since=len(confirmed_at),
        policy=policy,
        source_version=1,
        valid_until=None,
    )
    service = build_service_projection(profile, source_version=1, location=None, contact=None)

    expected = compute_status(profile, report, confirmed_at, scenario["now"], policy)
    actual = compute_network_state(status_inputs(capacity, service), scenario["now"])

    assert actual.status is expected.status
    assert actual.effective_available == expected.effective_available
    assert actual.used == expected.used
    assert actual.over_by == expected.over_by
    assert actual.freshness == expected.freshness


def test_an_overdue_report_reads_not_updated_on_both_sides() -> None:
    profile = sample_profile(available_times=(AvailableTime.every_day_all_day(),))
    report = sample_report(effective_at=REPORTED_AT)
    capacity = sample_capacity_projection(profile=profile, latest=report, confirmed_since=0)
    service = sample_service_projection(profile=profile)
    late = REPORTED_AT + timedelta(hours=3)

    state = compute_network_state(status_inputs(capacity, service), late)

    assert state.status is Status.NOT_UPDATED
    assert state.freshness.overdue is True
    assert compute_status(profile, report, [], late).status is Status.NOT_UPDATED


def test_the_same_report_reads_live_before_the_next_report_is_due() -> None:
    profile = sample_profile(available_times=(AvailableTime.every_day_all_day(),))
    capacity = sample_capacity_projection(profile=profile, confirmed_since=0)
    service = sample_service_projection(profile=profile)

    state = compute_network_state(status_inputs(capacity, service), NOW)

    assert state.status is Status.ACCEPTING
    assert state.effective_available == 4


def test_a_report_past_its_due_time_and_reply_window_reads_not_updated_with_no_new_event() -> None:
    """Hazard H-N07 and H-N03: nothing is stored that says accepting; the read decides."""
    profile = sample_profile(available_times=(AvailableTime.every_day_all_day(),))
    capacity = sample_capacity_projection(profile=profile, confirmed_since=0)
    service = sample_service_projection(profile=profile)
    inputs = status_inputs(capacity, service)

    before = compute_network_state(inputs, REPORTED_AT + timedelta(minutes=89))
    after = compute_network_state(inputs, REPORTED_AT + timedelta(minutes=91))

    assert before.status is Status.ACCEPTING
    assert after.status is Status.NOT_UPDATED


def test_a_suspended_projection_reads_not_updated() -> None:
    profile = sample_profile(available_times=(AvailableTime.every_day_all_day(),), suspended=True)
    capacity = sample_capacity_projection(profile=profile, confirmed_since=0)
    service = sample_service_projection(profile=profile)

    assert compute_network_state(status_inputs(capacity, service), NOW).status is Status.NOT_UPDATED


def test_a_confirmed_count_reduces_what_is_available() -> None:
    profile = sample_profile(available_times=(AvailableTime.every_day_all_day(),))
    service = sample_service_projection(profile=profile)

    none = compute_network_state(
        status_inputs(sample_capacity_projection(profile=profile, confirmed_since=0), service), NOW
    )
    three = compute_network_state(
        status_inputs(sample_capacity_projection(profile=profile, confirmed_since=3), service), NOW
    )

    assert (none.effective_available, three.effective_available) == (4, 1)


def test_the_projected_reply_window_is_used_and_not_the_default() -> None:
    profile = sample_profile(available_times=(AvailableTime.every_day_all_day(),))
    service = sample_service_projection(profile=profile)
    long_window = sample_policy(
        reply_window=timedelta(minutes=60),
        reminder_after=timedelta(minutes=60),
        phone_task_after=timedelta(minutes=90),
        escalate_after=timedelta(minutes=120),
    )
    # Due at 10:00 after a 09:00 report: 10:45 is past the default reply-by (10:30), before 11:00.
    at = REPORTED_AT + timedelta(hours=1, minutes=45)

    default = compute_network_state(
        status_inputs(sample_capacity_projection(profile=profile), service), at
    )
    long = compute_network_state(
        status_inputs(sample_capacity_projection(profile=profile, policy=long_window), service), at
    )

    assert default.status is Status.NOT_UPDATED
    assert long.status is Status.ACCEPTING


def test_the_projected_stale_limit_is_used() -> None:
    profile = sample_profile(
        available_times=(AvailableTime.every_day_all_day(),), cadence=Cadence.ONCE_A_DAY
    )
    service = sample_service_projection(profile=profile)
    short = sample_policy(stale_warning_after=timedelta(hours=1))
    at = REPORTED_AT + timedelta(minutes=90)

    state_default = compute_network_state(
        status_inputs(sample_capacity_projection(profile=profile), service), at
    )
    state_short = compute_network_state(
        status_inputs(sample_capacity_projection(profile=profile, policy=short), service), at
    )

    assert state_default.freshness.stale_warning is False
    assert state_short.freshness.stale_warning is True


def test_the_ladder_values_of_the_replica_policy_never_change_the_result() -> None:
    profile = sample_profile(available_times=(AvailableTime.every_day_all_day(),))
    service = sample_service_projection(profile=profile)
    results = []
    for shift in (0, 7, 30, 59):
        policy = sample_policy(**_ladder(30, shift))
        capacity = sample_capacity_projection(profile=profile, policy=policy)
        state = compute_network_state(
            status_inputs(capacity, service), REPORTED_AT + timedelta(hours=2, minutes=40)
        )
        results.append((state.status, state.freshness))

    assert len(set(results)) == 1


@given(
    st.integers(0, 50),
    st.sampled_from(list(Channel)),
    st.text(max_size=20),
    st.sampled_from(list(ReportSource)),
)
@settings(max_examples=50, deadline=None)
def test_the_placeholders_the_allowlist_does_not_carry_do_not_change_the_result(
    usual_high: int, channel: Channel, comment: str, source: ReportSource
) -> None:
    profile = sample_profile(
        available_times=(AvailableTime.every_day_all_day(),),
        usual_range=(0, usual_high),
        channel=channel,
        comment=comment,
    )
    report = sample_report(source=source, report_type=ReportType.NUMBER)
    capacity = sample_capacity_projection(profile=profile, latest=report, confirmed_since=1)
    service = sample_service_projection(profile=profile)

    actual = compute_network_state(status_inputs(capacity, service), NOW)
    expected = compute_status(profile, report, [REPORTED_AT], NOW)

    assert actual.status is expected.status
    assert actual.effective_available == expected.effective_available
    assert actual.freshness == expected.freshness


def test_a_capacity_and_a_service_of_different_services_are_refused() -> None:
    capacity = sample_capacity_projection()
    other = sample_service_projection(profile=sample_profile(id="svc-2"))

    with pytest.raises(ValidationFailed):
        status_inputs(capacity, other)


def test_a_longer_projected_reply_window_is_not_refused_by_the_ladder_rule() -> None:
    """TEN-006 needs reply_window <= reminder_after < phone_task_after < escalate_after. The
    replica builds a ladder that satisfies it for any projected reply window of 15 to 60."""
    profile = sample_profile(available_times=(AvailableTime.every_day_all_day(),))
    service = sample_service_projection(profile=profile)
    for minutes in (15, 30, 31, 45, 60):
        policy = sample_policy(reply_window=timedelta(minutes=minutes), **_ladder(minutes, 0))
        capacity = sample_capacity_projection(profile=profile, policy=policy)

        compute_network_state(status_inputs(capacity, service), NOW)


def test_a_capacity_report_type_confirmed_is_projected_as_its_figure_only() -> None:
    profile = sample_profile()
    report = CapacityReport(
        id="rep-2",
        service_id=SERVICE_ID,
        value=4,
        measure=Measure.REFERRALS_ACCEPTABLE,
        effective_at=REPORTED_AT,
        source=ReportSource.TEXT,
        report_type=ReportType.CONFIRMED,
        derived_from="rep-1",
    )

    dto = sample_capacity_projection(profile=profile, latest=report)

    assert dto.report_id == "rep-2"
    assert "rep-1" not in repr(dto)


def test_the_sample_helpers_match_the_documented_inputs() -> None:
    assert sample_location().postcode == "DT4 8XX"
    assert sample_contact().phone == "0300 123 4567"
    assert isinstance(sample_service_projection(), ServiceProjection)
