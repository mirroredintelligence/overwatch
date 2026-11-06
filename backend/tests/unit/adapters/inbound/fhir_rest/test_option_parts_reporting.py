"""The reporting parts of an option (DEC-1343): what the service promised, when it last reported,
when it is next due, whether it is late, and its last figure. No Neo4j, no network."""

from datetime import UTC, datetime, timedelta
from typing import Any

from overwatch.adapters.inbound.fhir_rest.case_mapping import filter_result_to_fhir
from overwatch.application.use_cases.filter_options import FilterOptionsResult, Option
from overwatch.domain.codes import Cadence, Status

NOW = datetime(2026, 11, 6, 14, 0, tzinfo=UTC)


def _option(**changes: Any) -> Option:
    base: dict[str, Any] = {
        "service_id": "svc-1",
        "name": "UCR West",
        "status": Status.NOT_UPDATED,
        "effective_available": None,
        "over_by": None,
        "unit_label": "beds free",
        "data_age": timedelta(hours=3),
        "travel": None,
        "fits": (),
        "warnings": (),
        "criteria_id": "crit-1",
        "criteria_version": 1,
    }
    base.update(changes)
    return Option(**base)


def _parts(option: Option) -> dict[str, Any]:
    body = filter_result_to_fhir(
        FilterOptionsResult(options=(option,), not_suitable=(), generated_at=NOW)
    )
    entry = next(item for item in body["parameter"] if item["name"] == "option")
    return {part["name"]: part for part in entry["part"]}


def test_a_late_option_says_when_it_reported_when_it_is_due_and_that_it_is_overdue() -> None:
    parts = _parts(
        _option(
            reported_at=NOW - timedelta(hours=3),
            next_due_at=NOW + timedelta(hours=1),
            cadence=Cadence.EVERY_2_HRS,
            overdue=True,
            stale_warning=True,
            last_figure=3,
        )
    )

    assert parts["reportedAt"]["valueDateTime"] == "2026-11-06T11:00:00Z"
    assert parts["nextDueAt"]["valueDateTime"] == "2026-11-06T15:00:00Z"
    assert parts["cadence"]["valueCode"] == "every-2-hrs"
    assert parts["lastFigure"]["valueInteger"] == 3
    assert parts["overdue"]["valueBoolean"] is True
    assert parts["staleFigure"]["valueBoolean"] is True


def test_an_option_with_no_report_has_no_times_and_is_not_overdue_by_default() -> None:
    parts = _parts(_option(data_age=None))

    assert "reportedAt" not in parts
    assert "nextDueAt" not in parts
    assert "lastFigure" not in parts
    assert parts["overdue"]["valueBoolean"] is False
