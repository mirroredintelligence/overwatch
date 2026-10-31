"""The network variant of the options filter, the pure part (WB11, TEN-051, TEN-053, DEC-136 item 1).

A case's age band, district and needs are compared, in memory, with the criteria another organisation
has shared into a network. Nothing of the case is written to a network scope or sent to another
organisation: the rows come from the network, the case from the advisor's own tenant, and this is the
comparison. A network row is a fact about capacity; it is never booked, and it carries no comment, no
pending count and no reporter.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from diucs.application.use_cases.filter_network_options import (
    CRITERIA_NOT_SHARED_REASON,
    PAUSED_REASON,
    NetworkCaseInputs,
    NetworkNotSuitable,
    NetworkOption,
    classify_network_row,
    network_reason_code,
)
from diucs.application.use_cases.query_network_directory import (
    NetworkCriteriaEntry,
    NetworkDirectoryEntry,
)
from diucs.domain.codes import AgeBand, NeedCategory, ServiceCategory, Status
from diucs.domain.model.network import DirectorySource
from diucs.domain.rules.listing import ListingPresentation
from diucs.domain.rules.network_board import NetworkBoardEntry
from diucs.domain.rules.projection import LocationProjection

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
TODAY = date(2026, 10, 30)
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


def criteria_entry(**changes: object) -> NetworkCriteriaEntry:
    fields: dict[str, object] = {
        "row_ref": "lst-1",
        "organisation_name": "Sample Area B",
        "service_name": "Virtual ward frailty",
        "version": 3,
        "age_min": 18,
        "age_max": None,
        "districts": ("DT1", "DT4"),
        "accepts": (NeedCategory.FRAILTY, NeedCategory.FALL_NO_INJURY),
        "excludes": (NeedCategory.IV_THERAPY,),
        "review_by": date(2027, 4, 29),
        "ended_at": None,
        "end_reason": None,
    }
    fields.update(changes)
    return NetworkCriteriaEntry(**fields)  # type: ignore[arg-type]


def site(**changes: object) -> NetworkDirectoryEntry:
    fields: dict[str, object] = {
        "row_ref": "lst-1",
        "organisation_name": "Sample Area B",
        "service_name": "Virtual ward frailty",
        "category": ServiceCategory.HOSPITAL_AT_HOME_OR_VIRTUAL_WARD,
        "active": True,
        "source": DirectorySource.MANUAL,
        "contact_label": "Service line",
        "contact_phone": "01632 960010",
        "location": LocationProjection(
            location_name="West hub",
            postal_district="DT4",
            city="Sampletown",
            latitude=52.0,
            longitude=-1.5,
        ),
        "opening_hours": (),
        "presentation": ListingPresentation.SHOWN,
        "ended_at": None,
        "end_reason": None,
    }
    fields.update(changes)
    return NetworkDirectoryEntry(**fields)  # type: ignore[arg-type]


def classify(
    entry: NetworkBoardEntry | None = None,
    criteria: NetworkCriteriaEntry | None = None,
    where: NetworkDirectoryEntry | None = None,
    case: NetworkCaseInputs = CASE,
) -> NetworkOption | NetworkNotSuitable:
    return classify_network_row(
        entry or board_entry(),
        criteria_entry() if criteria is None else criteria,
        site() if where is None else where,
        case,
        NOW,
        TODAY,
    )


def test_a_service_that_meets_the_criteria_and_is_accepting_is_an_option_with_its_facts() -> None:
    row = classify()
    assert isinstance(row, NetworkOption)
    assert (row.row_ref, row.organisation_name, row.service_name) == (
        "lst-1",
        "Sample Area B",
        "Virtual ward frailty",
    )
    assert (row.status, row.effective_available, row.unit_label) == (Status.ACCEPTING, 3, "beds")
    assert row.data_age == timedelta(minutes=20)
    assert row.criteria_version == 3
    assert row.contact_phone == "01632 960010"
    assert row.position is not None and (row.position.lat, row.position.lon) == (52.0, -1.5)
    assert row.fits[0] == "Covers this postcode"
    assert "Takes frailty, fall" in row.fits[1]
    assert row.warnings == ()


def test_limited_and_over_capacity_are_options_with_their_warnings() -> None:
    limited = classify(board_entry(status=Status.LIMITED))
    assert isinstance(limited, NetworkOption) and limited.warnings == ("Limited: phone to confirm",)
    over = classify(board_entry(status=Status.OVER_CAPACITY, over_by=2))
    assert isinstance(over, NetworkOption)
    assert over.warnings == ("Over capacity now. Phone to confirm before offering.",)


def test_a_figure_older_than_the_stale_limit_and_a_criteria_review_overdue_are_warned() -> None:
    old = classify(board_entry(reported_at=NOW - timedelta(hours=3)))
    assert isinstance(old, NetworkOption) and "Data is over 2 hrs old. Consider phoning." in old.warnings
    overdue = classify(criteria=criteria_entry(review_by=date(2026, 10, 1)))
    assert isinstance(overdue, NetworkOption) and "Criteria not reviewed" in overdue.warnings


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
    assert (row.row_ref, row.organisation_name, row.service_name) == (
        "lst-1",
        "Sample Area B",
        "Virtual ward frailty",
    )


def test_not_updated_says_for_how_long_and_to_phone() -> None:
    row = classify(board_entry(status=Status.NOT_UPDATED, reported_at=NOW - timedelta(hours=4)))
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == "not updated for 4 hrs. Phone to confirm."


def test_a_paused_listing_is_not_suitable_and_nothing_else_is_read_of_it() -> None:
    row = classify(board_entry(presentation=ListingPresentation.UNAVAILABLE, status=None))
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == PAUSED_REASON


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
    row = classify_network_row(board_entry(), None, site(), CASE, NOW, TODAY)
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == CRITERIA_NOT_SHARED_REASON


def test_a_service_that_shared_no_directory_entry_is_still_an_option_with_no_position_or_number() -> None:
    row = classify_network_row(board_entry(), criteria_entry(), None, CASE, NOW, TODAY)
    assert isinstance(row, NetworkOption)
    assert row.position is None and row.contact_phone is None and row.contact_label is None


def test_criteria_that_cannot_be_built_fail_closed() -> None:
    # A need both accepted and excluded cannot be a criteria version: not suitable, never a pass.
    broken = criteria_entry(
        accepts=(NeedCategory.FRAILTY,), excludes=(NeedCategory.FRAILTY,)
    )
    row = classify(criteria=broken)
    assert isinstance(row, NetworkNotSuitable)
    assert row.reason == CRITERIA_NOT_SHARED_REASON


def test_the_answer_has_no_comment_pending_count_reporter_or_tenant_field() -> None:
    row = classify()
    assert isinstance(row, NetworkOption)
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
