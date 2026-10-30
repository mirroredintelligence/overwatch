"""Network settings (TEN-051, DEC-541): the three values the network view needs that belong to no
member: the name of the system, the name of the pathway, and the time zone in which the network
board reads opening hours. Pure: nothing is read, nothing is stored here.
"""

import dataclasses

import pytest

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.network_settings import (
    NAME_MAX_LENGTH,
    NetworkSettings,
)


def _settings(**changes: object) -> NetworkSettings:
    fields: dict[str, object] = {
        "system_name": "Sample capacity board",
        "pathway_name": "Sample urgent pathway",
        "time_zone": "Europe/London",
    }
    fields.update(changes)
    return NetworkSettings(**fields)  # type: ignore[arg-type]


def test_a_settings_record_has_exactly_three_fields_and_is_frozen() -> None:
    assert [f.name for f in dataclasses.fields(NetworkSettings)] == [
        "system_name",
        "pathway_name",
        "time_zone",
    ]
    settings = _settings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.system_name = "x"  # type: ignore[misc]
    assert settings == _settings()


def test_names_are_one_to_the_maximum_characters() -> None:
    assert NAME_MAX_LENGTH == 60
    assert _settings(system_name="A", pathway_name="B" * NAME_MAX_LENGTH)
    for field in ("system_name", "pathway_name"):
        with pytest.raises(ValidationFailed) as error:
            _settings(**{field: ""})
        assert error.value.field == field
        with pytest.raises(ValidationFailed):
            _settings(**{field: "x" * (NAME_MAX_LENGTH + 1)})


@pytest.mark.parametrize("value", [None, 7, b"abc", ["abc"], "bad<name", "bad>name", "a@b.example"])
def test_a_name_that_is_not_plain_text_is_refused(value: object) -> None:
    for field in ("system_name", "pathway_name"):
        with pytest.raises(ValidationFailed):
            _settings(**{field: value})


@pytest.mark.parametrize("value", ["DT4 8XX", "07700 900123", "Ms Jane Smith", "9434765919"])
def test_a_name_with_a_patient_shape_is_refused_and_the_refusal_holds_no_value(value: str) -> None:
    with pytest.raises(ValidationFailed) as error:
        _settings(system_name=value)
    assert value not in str(error.value)


@pytest.mark.parametrize("value", ["Europe/London"])
def test_a_time_zone_on_the_allow_list_is_accepted(value: str) -> None:
    assert _settings(time_zone=value).time_zone == value


@pytest.mark.parametrize("value", ["", "London", "UTC+1", "Nowhere/Land", "../etc/passwd", None, 3])
def test_a_time_zone_off_the_allow_list_is_refused(value: object) -> None:
    with pytest.raises(ValidationFailed) as error:
        _settings(time_zone=value)
    assert error.value.field == "time_zone"
