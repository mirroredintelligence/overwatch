"""Pure rules of the audit replay (U42): status wording, data age wording, rows from an options
snapshot, timeline labels, the choice of the options display, and the role check. No I/O."""

import dataclasses
import json
from datetime import UTC, datetime

import pytest

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry, AuditRecord
from diucs.application.use_cases.audit_replay import (
    REPLAY_USE_CASE,
    ReplayRow,
    age_words,
    check_replay_role,
    options_display,
    replay_rows,
    status_word,
    timeline_item,
)
from diucs.domain.codes import Role, Status
from diucs.domain.errors import NotAllowed
from tests.support.actors import ACTOR_TENANT

T = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)


def _actor(role: Role) -> Actor:
    return Actor(
        role=role,
        practitioner_id="prac-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=ACTOR_TENANT,
    )


def _record(record_id: str, at: datetime, use_case: str, action: str, **kw: object) -> AuditRecord:
    entry = AuditEntry(
        action=action,
        use_case=use_case,
        actor=_actor(Role.ADVISOR),
        entity_ids=("case-4821",),
        snapshot=kw.get("snapshot"),  # type: ignore[arg-type]
        at=at,
    )
    return AuditRecord(id=record_id, entry=entry, chain_hash="h", previous_hash="p")


@pytest.mark.parametrize(
    ("status", "word"),
    [
        (Status.ACCEPTING, "Accepting"),
        (Status.LIMITED, "Limited"),
        (Status.NOT_ACCEPTING, "Not accepting"),
        (Status.OVER_CAPACITY, "Over capacity"),
        (Status.NOT_UPDATED, "Not updated"),
        (Status.OUT_OF_HOURS, "Out of hours"),
    ],
)
def test_every_status_has_its_advisor_word(status: Status, word: str) -> None:
    assert status_word(status) == word


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "just now"),
        (9 * 60, "9 min old"),
        (2 * 3600 + 10 * 60, "2 hrs 10 min old"),
        (3600, "1 hr old"),
    ],
)
def test_data_age_reads_as_it_was_shown(seconds: int, text: str) -> None:
    assert age_words(seconds) == text


def test_a_missing_data_age_is_not_shown_as_zero() -> None:
    assert age_words(None) == "no time given"


def test_rows_come_from_the_snapshot_with_the_current_service_name() -> None:
    snapshot = [
        {
            "id": "svc-ucr-west",
            "status": "accepting",
            "number": 4,
            "data_age_seconds": 9 * 60,
            "criteria_version": 3,
            "shown_as": "option",
        },
        {
            "id": "svc-ward-b",
            "status": "accepting",
            "number": 5,
            "data_age_seconds": 2 * 3600 + 10 * 60,
            "criteria_version": 3,
            "shown_as": "option",
        },
    ]
    rows = replay_rows(snapshot, {"svc-ucr-west": "UCR West", "svc-ward-b": "Community hospital"})
    assert rows == (
        ReplayRow("UCR West", "Accepting", "4", "9 min old", 3),
        ReplayRow("Community hospital", "Accepting", "5", "2 hrs 10 min old", 3),
    )


def test_a_service_no_longer_named_falls_back_to_its_id_and_no_figure_is_not_zero() -> None:
    snapshot = [
        {
            "id": "svc-gone",
            "status": "not-updated",
            "number": None,
            "data_age_seconds": None,
            "criteria_version": None,
            "shown_as": "not-suitable",
        }
    ]
    (row,) = replay_rows(snapshot, {})
    assert row.service_name == "svc-gone"
    assert row.value_text == "no figure"
    assert row.data_age_text == "no time given"
    assert row.criteria_version is None


def test_rows_never_carry_a_postcode_or_needs() -> None:
    snapshot = [
        {
            "id": "svc-a",
            "status": "accepting",
            "number": 1,
            "data_age_seconds": 60,
            "criteria_version": 1,
            "shown_as": "option",
            "postcode": "DT4 8XX",
            "needs": ["frailty"],
        }
    ]
    (row,) = replay_rows(snapshot, {"svc-a": "A"})
    text = json.dumps(dataclasses.asdict(row))
    assert "DT4" not in text and "frailty" not in text


@pytest.mark.parametrize(
    ("use_case", "action", "label"),
    [
        ("OpenCase", "C", "case opened"),
        ("UpdateCase", "U", "case updated"),
        ("RequestBooking", "C", "booking request sent"),
        ("RecordDecline", "C", "declined despite capacity"),
        ("RecordOutcome", "U", "outcome recorded"),
    ],
)
def test_timeline_labels_for_case_events(use_case: str, action: str, label: str) -> None:
    record = _record("r", T, use_case, action)
    assert timeline_item(record) is not None
    assert timeline_item(record).label == label  # type: ignore[union-attr]


def test_options_shown_counts_only_the_options_not_the_not_suitable_rows() -> None:
    snapshot = {
        "reference": "4821",
        "services": [
            {
                "id": "a",
                "status": "accepting",
                "number": 4,
                "data_age_seconds": 0,
                "criteria_version": 3,
                "shown_as": "option",
            },
            {
                "id": "b",
                "status": "accepting",
                "number": 5,
                "data_age_seconds": 0,
                "criteria_version": 3,
                "shown_as": "option",
            },
            {
                "id": "c",
                "status": "accepting",
                "number": 2,
                "data_age_seconds": 0,
                "criteria_version": 3,
                "shown_as": "option",
            },
            {
                "id": "d",
                "status": "not-accepting",
                "number": 0,
                "data_age_seconds": 0,
                "criteria_version": 3,
                "shown_as": "not-suitable",
            },
        ],
    }
    record = _record("r", T, "FilterOptions", "R", snapshot=snapshot)
    item = timeline_item(record)
    assert item is not None and item.label == "3 options shown"


def test_booking_answers_by_text_are_labelled_by_their_status() -> None:
    confirmed = _record("c", T, "RespondToBooking", "U", snapshot={"status": "confirmed"})
    declined = _record("d", T, "RespondToBooking", "U", snapshot={"status": "declined"})
    assert timeline_item(confirmed).label == "confirmed by text"  # type: ignore[union-attr]
    assert timeline_item(declined).label == "declined by text"  # type: ignore[union-attr]


def test_a_replay_is_not_a_timeline_item() -> None:
    assert timeline_item(_record("r", T, REPLAY_USE_CASE, "R")) is None


def test_the_shown_options_are_the_last_display_before_the_first_request() -> None:
    first = _record("f1", T, "FilterOptions", "R", snapshot={"reference": "4821", "services": []})
    second = _record("f2", T, "FilterOptions", "R", snapshot={"reference": "4821", "services": []})
    request = _record("q", T, "RequestBooking", "C")
    later = _record("f3", T, "FilterOptions", "R", snapshot={"reference": "4821", "services": []})
    chosen = options_display([first, second, request, later])
    assert chosen is not None and chosen.id == "f2"


def test_with_no_request_the_last_display_is_the_one_shown() -> None:
    first = _record("f1", T, "FilterOptions", "R", snapshot={"reference": "4821", "services": []})
    last = _record("f2", T, "FilterOptions", "R", snapshot={"reference": "4821", "services": []})
    chosen = options_display([first, last])
    assert chosen is not None and chosen.id == "f2"


def test_no_display_gives_no_choice() -> None:
    assert options_display([_record("q", T, "RequestBooking", "C")]) is None


@pytest.mark.parametrize("role", [Role.LEAD, Role.AUDIT])
def test_lead_and_audit_may_open_a_replay(role: Role) -> None:
    check_replay_role(_actor(role))


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.CLINICAL, Role.EXEC, Role.REPORTER])
def test_other_roles_are_refused(role: Role) -> None:
    with pytest.raises(NotAllowed):
        check_replay_role(_actor(role))


# KI-474, KI-475, H-190: the replay shows what the advisor saw, in the words they saw.


def _row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "svc-a",
        "status": "accepting",
        "number": 3,
        "data_age_seconds": 60,
        "criteria_version": 1,
        "shown_as": "option",
    }
    row.update(changes)
    return row


def test_the_name_the_advisor_saw_is_shown_even_when_the_service_has_been_renamed() -> None:
    (row,) = replay_rows([_row(name="UCR West (old name)")], {"svc-a": "UCR West"})

    assert row.service_name == "UCR West (old name)"
    assert row.name_as_shown is True


def test_a_row_written_before_names_were_kept_shows_the_current_name_and_says_so() -> None:
    (row,) = replay_rows([_row()], {"svc-a": "UCR West"})

    assert row.service_name == "UCR West"
    assert row.name_as_shown is False


def test_a_blank_name_in_the_snapshot_is_not_a_name() -> None:
    (row,) = replay_rows([_row(name="  ")], {"svc-a": "UCR West"})

    assert row.service_name == "UCR West"
    assert row.name_as_shown is False


def test_an_over_capacity_service_shows_how_far_over_it_was() -> None:
    (row,) = replay_rows(
        [_row(status="over-capacity", number=14, over_by=2)], {"svc-a": "Hospital at home"}
    )

    assert row.value_text == "+2"


def test_an_over_capacity_row_from_before_over_by_was_kept_shows_no_figure_never_the_used_count() -> (
    None
):
    (row,) = replay_rows([_row(status="over-capacity", number=14)], {"svc-a": "A"})

    assert row.value_text == "no figure"


@pytest.mark.parametrize("status", ["not-accepting", "not-updated", "out-of-hours"])
def test_a_status_that_offers_no_figure_shows_none_even_when_the_snapshot_holds_a_number(
    status: str,
) -> None:
    (row,) = replay_rows([_row(status=status, number=7)], {"svc-a": "A"})

    assert row.value_text == "no figure"


def test_an_accepting_or_limited_service_shows_what_it_could_take() -> None:
    accepting, limited = replay_rows(
        [_row(status="accepting", number=4), _row(status="limited", number=1)], {"svc-a": "A"}
    )

    assert (accepting.value_text, limited.value_text) == ("4", "1")


# H-193: the replay lists the options in the order the advisor was shown them (nearest first).


def test_the_options_are_listed_in_the_order_they_were_shown_then_the_services_not_suitable() -> (
    None
):
    rows = replay_rows(
        [
            _row(id="far", order=2, name="Far"),
            {**_row(id="no", name="Closed", status="not-accepting"), "shown_as": "not-suitable"},
            _row(id="near", order=1, name="Near"),
        ],
        {},
    )

    assert [row.service_name for row in rows] == ["Near", "Far", "Closed"]


def test_rows_with_no_order_stay_in_the_order_written() -> None:
    rows = replay_rows([_row(id="b", name="B"), _row(id="a", name="A")], {})

    assert [row.service_name for row in rows] == ["B", "A"]
