"""The set-up's hours and unit label (DEC-1331): all day, or From to To on the days chosen. The unit
label is read from what the service counts. Sample values only."""

from typing import Any

import pytest

from overwatch.adapters.inbound.fhir_rest.routes_lead import _available_times, _index
from overwatch.domain.codes import Measure
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.service import ALL_DAYS, UNIT_LABELS, unit_label_for


def _body(*parts: tuple[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "resourceType": "Parameters",
        "parameter": [{"name": name, **value} for name, value in parts],
    }


def test_all_day_means_no_start_and_no_end_on_every_day_when_no_day_is_chosen() -> None:
    (time,) = _available_times(_index(_body(("allDay", {"valueString": "true"}))))
    assert (time.all_day, time.start, time.end, time.days) == (True, None, None, ALL_DAYS)


def test_from_and_to_on_the_days_chosen_only() -> None:
    body = _body(
        ("availableFrom", {"valueString": "08:00"}),
        ("availableTo", {"valueString": "20:00"}),
        ("day", {"valueInteger": 0}),
        ("day", {"valueInteger": 4}),
    )
    (time,) = _available_times(_index(body))
    assert (time.all_day, str(time.start), str(time.end), time.days) == (
        False,
        "08:00:00",
        "20:00:00",
        frozenset({0, 4}),
    )


def test_from_and_to_are_required_when_the_service_is_not_all_day() -> None:
    with pytest.raises(ValidationFailed):
        _available_times(_index(_body(("availableFrom", {"valueString": "08:00"}))))


@pytest.mark.parametrize("day", [7, -1])
def test_a_day_outside_monday_to_sunday_is_refused(day: int) -> None:
    body = _body(("allDay", {"valueString": "true"}), ("day", {"valueInteger": day}))
    with pytest.raises(ValidationFailed):
        _available_times(_index(body))


@pytest.mark.parametrize("measure", list(Measure))
def test_every_measure_has_a_unit_label_so_the_wizard_need_not_ask_for_one(
    measure: Measure,
) -> None:
    assert unit_label_for(measure) == UNIT_LABELS[measure]
    assert unit_label_for(measure).strip() != ""
