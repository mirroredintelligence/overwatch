"""What the advisor saw, as a clinician reads it (W9G): the pure rules.

A line is one service of the display the advisor had when they asked: its status, its figure, how
old the figure was and, for a service that was not suitable, why. The figure is capacity-derived and
is never a count that could be read as free places: an over-capacity service shows how far over it
was ("+2") or nothing (the old snapshot held the used count, DEC-391, H-190), and a status that has
no figure shows none. Sample values only.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry, AuditRecord
from diucs.application.use_cases.clinical_context import (
    NO_NAME,
    SeenLine,
    figure_text,
    pinned_display,
    seen_lines,
    why_text,
)
from diucs.application.use_cases.filter_options import reason_code
from diucs.domain.codes import Role, Status
from tests.support.actors import ACTOR_TENANT

ASKED = datetime(2026, 10, 23, 13, 16, tzinfo=UTC)
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="adv-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
    tenant_id=ACTOR_TENANT,
)
OTHER_ADVISOR = replace(ADVISOR, practitioner_id="adv-2")


def row(**changes: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "id": "svc-1",
        "status": "accepting",
        "number": 4,
        "data_age_seconds": 9 * 60,
        "criteria_version": 3,
        "shown_as": "option",
        "over_by": None,
    }
    fields.update(changes)
    return fields


def record(record_id: str, use_case: str, at: datetime, actor: Actor = ADVISOR) -> AuditRecord:
    return AuditRecord(
        id=record_id,
        entry=AuditEntry(
            action="R",
            use_case=use_case,
            actor=actor,
            entity_ids=("case-1",),
            snapshot={"reference": "4821", "services": []},
            at=at,
        ),
        chain_hash="a" * 64,
        previous_hash="b" * 64,
    )


# The figure.


@pytest.mark.parametrize(
    ("status", "number", "over_by", "text"),
    [
        (Status.ACCEPTING, 4, None, "4"),
        (Status.LIMITED, 1, None, "1"),
        (Status.ACCEPTING, 0, None, "0"),
        (Status.OVER_CAPACITY, 14, 2, "+2"),
        # The used count the old snapshot kept for an over-capacity service is not a figure.
        (Status.OVER_CAPACITY, 14, None, None),
        (Status.OVER_CAPACITY, 14, 0, None),
        (Status.NOT_ACCEPTING, 0, None, None),
        (Status.NOT_UPDATED, 6, None, None),
        (Status.OUT_OF_HOURS, 3, None, None),
        (Status.ACCEPTING, None, None, None),
        (Status.ACCEPTING, -1, None, None),
        (Status.ACCEPTING, True, None, None),
    ],
)
def test_the_figure_is_what_the_service_could_take_and_never_a_used_count(
    status: Status, number: Any, over_by: Any, text: str | None
) -> None:
    assert figure_text(status, number, over_by) == text


# Why a service was not suitable.


@pytest.mark.parametrize(
    ("given", "code"),
    [
        ("not accepting", "not-accepting"),
        ("out of hours", "out-of-hours"),
        ("outside criteria", "outside-criteria"),
        ("criteria not current", "criteria-not-current"),
        ("suspended. Phone to confirm.", "suspended"),
        ("not updated. Phone to confirm.", "not-updated"),
        ("not updated for 2 hrs 10 min. Phone to confirm.", "not-updated"),
    ],
)
def test_each_reason_a_service_was_not_suitable_has_a_code_with_no_age_in_it(
    given: str, code: str
) -> None:
    assert reason_code(given) == code


def test_a_reason_that_is_not_known_is_refused() -> None:
    with pytest.raises(ValueError, match="reason"):
        reason_code("a sentence nobody wrote")


@pytest.mark.parametrize(
    ("shown", "reason", "status", "text"),
    [
        ("option", None, "accepting", None),
        ("not-suitable", "not-accepting", "not-accepting", "Not accepting"),
        ("not-suitable", "out-of-hours", "out-of-hours", "Out of hours"),
        ("not-suitable", "not-updated", "not-updated", "Not updated"),
        ("not-suitable", "suspended", "accepting", "Suspended"),
        ("not-suitable", "outside-criteria", "accepting", "Outside its criteria"),
        ("not-suitable", "criteria-not-current", "accepting", "Criteria not current"),
        # A snapshot written before the reason was kept: said from the status, else not said.
        ("not-suitable", None, "not-accepting", "Not accepting"),
        ("not-suitable", None, "accepting", "Not suitable"),
    ],
)
def test_why_a_service_was_not_suitable(
    shown: str, reason: str | None, status: str, text: str | None
) -> None:
    assert why_text(row(shown_as=shown, reason=reason, status=status)) == text


# The lines.


def test_a_line_reads_as_the_advisor_saw_it() -> None:
    lines = seen_lines(
        [
            row(id="svc-1"),
            row(id="svc-2", status="over-capacity", number=14, over_by=2, data_age_seconds=14 * 60),
            row(id="svc-3", number=5, data_age_seconds=2 * 3600 + 10 * 60),
        ],
        {"svc-1": "UCR West", "svc-2": "Hospital at home", "svc-3": "Ward B"},
    )

    assert lines == (
        SeenLine("UCR West", "option", "accepting", "Accepting", "4", "9 min old", False, None, 3),
        SeenLine(
            "Hospital at home",
            "option",
            "over-capacity",
            "Over capacity",
            "+2",
            "14 min old",
            False,
            None,
            3,
        ),
        SeenLine(
            "Ward B", "option", "accepting", "Accepting", "5", "2 hrs 10 min old", True, None, 3
        ),
    )


def test_a_figure_older_than_the_stale_limit_is_marked_stale_and_two_hours_exactly_is_not() -> None:
    lines = seen_lines(
        [row(data_age_seconds=2 * 3600), row(data_age_seconds=2 * 3600 + 1)], {"svc-1": "A"}
    )

    assert [line.stale for line in lines] == [False, True]


def test_a_service_never_reported_has_no_age_and_is_not_marked_stale() -> None:
    (line,) = seen_lines([row(data_age_seconds=None, status="not-updated", number=None)], {})

    assert line.age == "no time given"
    assert line.stale is False
    assert line.figure is None


def test_a_service_that_is_no_longer_named_is_not_named_by_its_id() -> None:
    (line,) = seen_lines([row(id="svc-gone-0001")], {})

    assert line.service == NO_NAME
    assert "svc-gone-0001" not in repr(line)


def test_a_service_that_was_not_suitable_says_why_and_keeps_its_status() -> None:
    (line,) = seen_lines(
        [row(shown_as="not-suitable", status="not-accepting", number=0, reason="not-accepting")],
        {"svc-1": "UCR East"},
    )

    assert (line.shown_as, line.status_text, line.why, line.figure) == (
        "not-suitable",
        "Not accepting",
        "Not accepting",
        None,
    )


@pytest.mark.parametrize(
    "bad",
    [
        row(status="made-up"),
        row(shown_as="something"),
        row(data_age_seconds="9"),
        row(criteria_version="3"),
        {"id": "svc-1"},
    ],
)
def test_a_row_that_cannot_be_read_refuses_the_whole_display(bad: dict[str, Any]) -> None:
    with pytest.raises((KeyError, ValueError, TypeError)):
        seen_lines([row(), bad], {})


# The display a request pins.


def test_the_display_pinned_is_the_last_one_the_asking_advisor_had_before_asking() -> None:
    records = [
        record("a1", "FilterOptions", datetime(2026, 10, 23, 13, 10, tzinfo=UTC)),
        record("a2", "OpenCase", datetime(2026, 10, 23, 13, 11, tzinfo=UTC)),
        record("a3", "FilterOptions", datetime(2026, 10, 23, 13, 13, tzinfo=UTC)),
        record("a4", "FilterOptions", datetime(2026, 10, 23, 13, 14, tzinfo=UTC), OTHER_ADVISOR),
        record("a5", "FilterOptions", datetime(2026, 10, 23, 13, 17, tzinfo=UTC)),
    ]

    pinned = pinned_display(records, "adv-1", ASKED)

    assert pinned is not None
    assert pinned.id == "a3"


def test_no_display_by_the_asking_advisor_pins_nothing() -> None:
    records = [
        record("a1", "FilterOptions", datetime(2026, 10, 23, 13, 10, tzinfo=UTC), OTHER_ADVISOR),
        record("a2", "OpenCase", datetime(2026, 10, 23, 13, 11, tzinfo=UTC)),
    ]

    assert pinned_display(records, "adv-1", ASKED) is None
    assert pinned_display([], "adv-1", ASKED) is None


def test_a_display_at_the_moment_of_asking_is_the_one_the_advisor_had() -> None:
    records = [record("a1", "FilterOptions", ASKED)]

    pinned = pinned_display(records, "adv-1", ASKED)

    assert pinned is not None
    assert pinned.id == "a1"
