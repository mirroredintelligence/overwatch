"""Pure rules of the advisor's phoned figure and declines (U13).

Sample values are synthetic: UCR West, a figure of 4 and a reason. No patient data appears here.
"""

import dataclasses
from datetime import UTC, datetime

import pytest

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry, AuditRecord
from diucs.application.use_cases.advisor_phoned import phoned_figure
from diucs.application.use_cases.record_decline import (
    DeclineRecord,
    declines_from,
    number_seen,
)
from diucs.domain.codes import DeclineReason, Role
from diucs.domain.errors import ValidationFailed

ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
MORNING = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
SINCE = datetime(2026, 10, 23, 0, 0, tzinfo=UTC)


def _record(index: int, use_case: str, at: datetime, snapshot: dict[str, object]) -> AuditRecord:
    entry = AuditEntry(
        action="C",
        use_case=use_case,
        actor=ADVISOR,
        entity_ids=("case-4821", "svc-ucr-west"),
        snapshot=snapshot,
        at=at,
    )
    return AuditRecord(id=f"audit-{index}", entry=entry, chain_hash="h", previous_hash="p")


@pytest.mark.parametrize(
    ("told", "value", "figure"),
    [
        ("accepting", 3, 3),
        ("limited", 2, 2),
        ("accepting", 0, 0),
        ("not-accepting", None, 0),
    ],
)
def test_the_figure_is_what_the_advisor_was_told(told: str, value: int | None, figure: int) -> None:
    assert phoned_figure(told, value) == figure


@pytest.mark.parametrize(
    ("told", "value"),
    [
        ("accepting", None),
        ("limited", None),
        ("not-accepting", 3),
        ("accepting", True),
    ],
)
def test_a_figure_that_does_not_match_the_answer_is_refused_naming_the_value(
    told: str, value: object
) -> None:
    with pytest.raises(ValidationFailed) as refused:
        phoned_figure(told, value)  # type: ignore[arg-type]

    assert refused.value.field == "value"


def test_an_answer_that_is_not_one_of_the_three_is_refused_naming_told() -> None:
    with pytest.raises(ValidationFailed) as refused:
        phoned_figure("sometimes", 1)

    assert refused.value.field == "told"


def test_the_number_seen_is_the_effective_figure_or_the_used_count_for_occupied_services() -> None:
    assert number_seen(4, 9) == 4
    assert number_seen(None, 14) == 14
    assert number_seen(None, None) is None


def test_declines_are_listed_from_the_start_of_the_day_only_for_record_decline() -> None:
    records = [
        _record(1, "RecordDecline", MORNING, {"service_id": "svc-ucr-west", "reason": "full"}),
        _record(2, "RecordDecline", datetime(2026, 10, 22, 9, 0, tzinfo=UTC), {"reason": "full"}),
        _record(3, "ReportCapacity", MORNING, {"value": 4}),
    ]

    found = declines_from(records, SINCE)

    assert found == [DeclineRecord("svc-ucr-west", DeclineReason.FULL, MORNING)]


def test_a_decline_record_carries_no_practitioner() -> None:
    names = {field.name for field in dataclasses.fields(DeclineRecord)}

    assert names == {"service_id", "reason", "at"}
