"""The pure part of the network variant of the options filter (KI-349, WB11, TEN-051, TEN-053,
DEC-136 item 1, DEC-1176): a projected criteria version as the hard filter reads it, and the
classification of one row of the network board as an option, not suitable with its reason, or
nothing at all. The storage and the registry are in
tests/integration/application/test_filter_network_options.py.

A case's age band, district and needs are compared, in memory, with the criteria another
organisation has shared into a network. Nothing of the case is written to a network scope or sent
to another organisation. A network row is a fact about capacity; it is never booked, and it carries
no comment, no pending count and no reporter.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from diucs.application.use_cases.filter_network_options import (
    CRITERIA_NOT_SHARED_REASON,
    PAUSED_REASON,
    NetworkCaseInputs,
    NetworkNotSuitable,
    NetworkOption,
    _Candidate,
    classify_network_row,
    criteria_of,
    network_reason_code,
)
from diucs.domain.codes import (
    AgeBand,
    CriteriaStatus,
    NeedCategory,
    ServiceCategory,
    Status,
)
from diucs.domain.model.network import DirectorySource, GrantScope, ListingStatus
from diucs.domain.rules.criteria_filter import check_hard_criteria
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.network_board import NetworkBoardEntry, NetworkServiceInput
from diucs.domain.rules.projection import CriteriaProjection, LocationProjection
from tests.support.projection_samples import sample_service_projection

PROJECTION = CriteriaProjection(
    source_criteria_id="crit-secret-1",
    source_service_id="svc-secret-1",
    version=4,
    age_min=18,
    age_max=None,
    districts=("DT1", "DT4"),
    accepts=(NeedCategory.FALL_NO_INJURY, NeedCategory.FRAILTY),
    excludes=(NeedCategory.IV_THERAPY,),
    review_by=date(2027, 4, 29),
)


def test_the_criteria_are_named_by_the_listing_and_never_by_the_members_own_ids() -> None:
    criteria = criteria_of("lst-abc-1", PROJECTION)

    assert criteria.service_id == "lst-abc-1"
    assert criteria.id == "lst-abc-1-v4"
    assert "secret" not in repr(criteria)


def test_a_projected_version_is_current_and_keeps_its_ages_districts_and_needs() -> None:
    criteria = criteria_of("lst-abc-1", PROJECTION)

    assert criteria.status is CriteriaStatus.CURRENT
    assert criteria.version == 4
    assert criteria.districts == frozenset({"DT1", "DT4"})
    assert criteria.excludes == frozenset({NeedCategory.IV_THERAPY})


def test_the_filter_passes_a_case_the_projection_covers_and_refuses_one_it_does_not() -> None:
    criteria = criteria_of("lst-abc-1", PROJECTION)

    covered = check_hard_criteria(criteria, AgeBand.A80_PLUS, "DT4", (NeedCategory.FRAILTY,))
    elsewhere = check_hard_criteria(criteria, AgeBand.A80_PLUS, "BH1", (NeedCategory.FRAILTY,))
    excluded = check_hard_criteria(criteria, AgeBand.A80_PLUS, "DT4", (NeedCategory.IV_THERAPY,))

    assert covered.passes
    assert not elsewhere.passes
    assert not excluded.passes


# ---------------------------------------------------------------- the classification of a row

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
TODAY = date(2026, 10, 30)
ALL_SCOPES = frozenset({GrantScope.DIRECTORY, GrantScope.CAPACITY, GrantScope.CRITERIA})
CASE = NetworkCaseInputs(
    age_band=AgeBand.A80_PLUS,
    district="DT4",
    needs=(NeedCategory.FRAILTY, NeedCategory.FALL_NO_INJURY),
)


def board_entry(**changes: object) -> NetworkBoardEntry:
    fields: dict[str, object] = {
        "row_ref": "lst-1",
        "organisation_name": "Sample Area B",
        "service_name": "Virtual ward frailty",
        "category": ServiceCategory.HOSPITAL_AT_HOME_OR_VIRTUAL_WARD,
        "presentation": ListingPresentation.SHOWN,
        "status": Status.ACCEPTING,
        "unit_label": "beds",
        "effective_available": 3,
        "over_by": None,
        "used": 7,
        "established": 10,
        "reported_at": NOW - timedelta(minutes=20),
        "stale_warning": False,
        "was_due_at": None,
        "source": DirectorySource.MANUAL,
    }
    fields.update(changes)
    return NetworkBoardEntry(**fields)  # type: ignore[arg-type]


def criteria_projection(**changes: object) -> CriteriaProjection:
    return replace(PROJECTION, **changes)  # type: ignore[arg-type]


def service_input(
    scopes: frozenset[GrantScope] = ALL_SCOPES, **service_changes: object
) -> NetworkServiceInput:
    fields: dict[str, object] = {
        "contact_label": "Service line",
        "contact_phone": "01632 960010",
        "location": LocationProjection(
            location_name="West hub",
            postal_district="DT4",
            city="Sampletown",
            latitude=52.0,
            longitude=-1.5,
        ),
    }
    fields.update(service_changes)
    service = replace(sample_service_projection(), **fields)  # type: ignore[arg-type]
    return NetworkServiceInput(
        row_ref="lst-1",
        organisation_name="Sample Area B",
        service=service,
        capacity=None,
        listing=ListingStatus.ADMITTED,
        visible_scopes=scopes,
    )


def classify(
    entry: NetworkBoardEntry | None = None,
    projection: CriteriaProjection | None | str = "default",
    item: NetworkServiceInput | None = None,
    case: NetworkCaseInputs = CASE,
) -> _Candidate | NetworkNotSuitable | None:
    return classify_network_row(
        entry or board_entry(),
        item or service_input(),
        criteria_projection() if projection == "default" else projection,  # type: ignore[arg-type]
        case,
        NOW,
        TODAY,
    )


def option_of(row: _Candidate | NetworkNotSuitable | None) -> NetworkOption:
    assert isinstance(row, _Candidate)
    assert isinstance(row.option, NetworkOption)
    return row.option


def test_a_service_that_meets_the_criteria_and_is_accepting_is_an_option_with_its_facts() -> None:
    row = option_of(classify())
    assert (row.service_id, row.organisation, row.name) == (
        "lst-1",
        "Sample Area B",
        "Virtual ward frailty",
    )
    assert (row.status, row.effective_available, row.unit_label) == (Status.ACCEPTING, 3, "beds")
    assert row.data_age == timedelta(minutes=20)
    assert row.criteria_version == 4
    assert row.review_by == date(2027, 4, 29)
    assert (row.contact_label, row.phone) == ("Service line", "01632 960010")
    assert row.position is not None and (row.position.lat, row.position.lon) == (52.0, -1.5)
    assert row.fits[0] == "Covers this postcode"
    assert row.fits[1] == "Takes frailty and fall, no injury"
    assert row.warnings == ()


def test_limited_and_over_capacity_are_options_with_their_warnings() -> None:
    limited = option_of(classify(board_entry(status=Status.LIMITED)))
    assert limited.warnings == ("Limited: phone to confirm",)
    over = option_of(classify(board_entry(status=Status.OVER_CAPACITY, over_by=2)))
    assert over.warnings == ("Over capacity now. Phone to confirm before offering.",)


def test_a_figure_older_than_the_stale_limit_and_a_criteria_review_overdue_are_warned() -> None:
    old = option_of(classify(board_entry(reported_at=NOW - timedelta(hours=3))))
    assert "Data is over 2 hrs old. Consider phoning." in old.warnings
    overdue = option_of(classify(projection=criteria_projection(review_by=date(2026, 10, 1))))
    assert "Criteria not reviewed" in overdue.warnings


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (Status.NOT_ACCEPTING, "not accepting"),
        (Status.OUT_OF_HOURS, "out of hours"),
    ],
)
def test_a_service_that_cannot_take_the_case_now_is_not_suitable_with_the_reason(
    status: Status, reason: str
) -> None:
    row = classify(board_entry(status=status))
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == reason
    assert (row.service_id, row.organisation, row.name) == (
        "lst-1",
        "Sample Area B",
        "Virtual ward frailty",
    )


def test_not_updated_says_for_how_long_and_to_phone() -> None:
    row = classify(board_entry(status=Status.NOT_UPDATED, reported_at=NOW - timedelta(hours=4)))
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == "not updated for 4 hrs. Phone to confirm."


def test_a_paused_listing_is_not_suitable_and_nothing_else_is_read_of_it() -> None:
    row = classify(
        board_entry(presentation=ListingPresentation.UNAVAILABLE, status=None),
        projection=None,
        item=service_input(frozenset()),
    )
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == PAUSED_REASON


@pytest.mark.parametrize(
    "presentation_and_scopes",
    [
        (ListingPresentation.HIDDEN, ALL_SCOPES),
        (ListingPresentation.SHOWN, frozenset({GrantScope.CAPACITY, GrantScope.CRITERIA})),
        (ListingPresentation.SHOWN, frozenset({GrantScope.DIRECTORY, GrantScope.CRITERIA})),
    ],
)
def test_a_hidden_listing_or_a_missing_directory_or_capacity_grant_shows_nothing_at_all(
    presentation_and_scopes: tuple[ListingPresentation, frozenset[GrantScope]],
) -> None:
    presentation, scopes = presentation_and_scopes
    row = classify(board_entry(presentation=presentation), item=service_input(scopes))
    assert row is None


def test_a_closed_service_shows_nothing_at_all() -> None:
    assert classify(item=service_input(active=False)) is None


@pytest.mark.parametrize(
    "case",
    [
        NetworkCaseInputs(AgeBand.A80_PLUS, "DT9", (NeedCategory.FRAILTY,)),
        NetworkCaseInputs(AgeBand.A80_PLUS, "DT4", (NeedCategory.IV_THERAPY,)),
        NetworkCaseInputs(AgeBand.A80_PLUS, "DT4", (NeedCategory.DEMENTIA,)),
        NetworkCaseInputs(AgeBand.A0_15, "DT4", (NeedCategory.FRAILTY,)),
    ],
)
def test_a_case_outside_the_shared_criteria_is_not_suitable_and_no_case_value_is_in_the_reason(
    case: NetworkCaseInputs,
) -> None:
    row = classify(case=case)
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == "outside criteria"
    assert "DT9" not in row.reason and "iv-therapy" not in row.reason


def test_a_service_that_shared_no_criteria_cannot_be_checked_and_fails_closed() -> None:
    row = classify(projection=None)
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == CRITERIA_NOT_SHARED_REASON


def test_a_criteria_grant_that_is_not_in_force_fails_closed_even_with_a_row_held() -> None:
    no_criteria_grant = frozenset({GrantScope.DIRECTORY, GrantScope.CAPACITY})
    row = classify(item=service_input(no_criteria_grant))
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == CRITERIA_NOT_SHARED_REASON


def test_a_service_with_no_place_and_no_service_line_is_an_option_with_neither() -> None:
    row = option_of(
        classify(item=service_input(location=None, contact_label=None, contact_phone=None))
    )
    assert row.position is None and row.phone is None and row.contact_label is None


def test_criteria_that_cannot_be_built_fail_closed() -> None:
    # A need both accepted and excluded cannot be a criteria version: not suitable, never a pass.
    # (A projection refuses that itself; this is a row that got past it.)
    broken = criteria_projection()
    object.__setattr__(broken, "accepts", (NeedCategory.FRAILTY,))
    object.__setattr__(broken, "excludes", (NeedCategory.FRAILTY,))
    row = classify(projection=broken)
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == CRITERIA_NOT_SHARED_REASON


def test_a_criteria_entry_with_no_upper_age_limit_is_read_and_covers_any_older_age() -> None:
    assert PROJECTION.age_max is None
    option_of(classify(case=NetworkCaseInputs(AgeBand.A80_PLUS, "DT4", (NeedCategory.FRAILTY,))))


def test_the_answer_has_no_comment_pending_count_reporter_or_tenant_field() -> None:
    names = set(NetworkOption.__dataclass_fields__)
    assert not names & {"comment", "pending", "reporter", "tenant_id", "source_tenant_id", "grant"}


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("not accepting", "not-accepting"),
        ("out of hours", "out-of-hours"),
        ("outside criteria", "outside-criteria"),
        ("not updated for 4 hrs. Phone to confirm.", "not-updated"),
        (PAUSED_REASON, "paused"),
        (CRITERIA_NOT_SHARED_REASON, "criteria-not-shared"),
    ],
)
def test_a_reason_has_a_code_for_the_audit_and_never_an_age(reason: str, code: str) -> None:
    assert network_reason_code(reason) == code


def test_a_reason_that_is_not_one_is_refused() -> None:
    with pytest.raises(ValueError):
        network_reason_code("whatever else")
