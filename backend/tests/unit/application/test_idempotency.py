"""The command-result codec (P15, DEC-090). Pure: no Neo4j, no clock."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from diucs.application.actor import Actor
from diucs.application.idempotency import decode_result, encode_result
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.use_cases.criteria import ConfirmCriteriaResult
from diucs.domain.codes import Role
from tests.support.actors import ACTOR_TENANT

AT = datetime(2026, 10, 23, 13, 0, tzinfo=UTC)


def _entry(at: datetime = AT) -> AuditEntry:
    return AuditEntry(
        action="report-capacity",
        use_case="ReportCapacity",
        actor=Actor(
            role=Role.REPORTER,
            practitioner_id=None,
            device_id="dev-sms-1",
            channel="text",
            service_ids=frozenset({"svc-ucr-west"}),
            tenant_id=ACTOR_TENANT,
        ),
        entity_ids=("obs-1", "obs-2"),
        snapshot=None,
        at=at,
    )


def test_a_result_with_a_datetime_an_enum_a_tuple_and_a_nested_dataclass_round_trips() -> None:
    result = _entry()
    type_name, json_text = encode_result(result)
    assert decode_result(type_name, json_text) == result


def test_the_result_type_name_is_module_and_qualname() -> None:
    type_name, _ = encode_result(_entry())
    assert type_name == "diucs.application.ports.outbound.audit:AuditEntry"


def test_a_london_datetime_comes_back_as_the_same_instant_in_utc() -> None:
    london = datetime(2026, 10, 25, 1, 55, tzinfo=ZoneInfo("Europe/London"))
    type_name, json_text = encode_result(_entry(at=london))
    decoded = decode_result(type_name, json_text)
    assert getattr(decoded, "at", None) == london.astimezone(UTC)
    assert isinstance(decoded, AuditEntry)
    assert decoded.at.utcoffset() == timedelta(0)


def test_a_timezone_other_than_utc_is_stored_as_the_same_instant() -> None:
    plus_two = timezone(timedelta(hours=2))
    at = datetime(2026, 10, 23, 15, 0, tzinfo=plus_two)
    type_name, json_text = encode_result(_entry(at=at))
    decoded = decode_result(type_name, json_text)
    assert isinstance(decoded, AuditEntry)
    assert decoded.at == at


@pytest.mark.parametrize("type_name", ["os:system", "subprocess:Popen", "builtins:dict"])
def test_decoding_a_type_outside_the_allowed_packages_raises_value_error(type_name: str) -> None:
    _, json_text = encode_result(_entry())
    with pytest.raises(ValueError):
        decode_result(type_name, json_text)


def test_a_domain_enum_nested_in_a_result_decodes_as_itself() -> None:
    """A deviation from the P15 prompt, recorded in DEC-090: results carry domain enums."""
    type_name, json_text = encode_result(_entry())
    assert "diucs.domain.codes:Role" in json_text
    assert decode_result(type_name, json_text) == _entry()


def test_a_naive_datetime_is_refused_on_encode() -> None:
    with pytest.raises(ValueError):
        encode_result(_entry(at=datetime(2026, 10, 23, 13, 0)))


def test_a_plain_dict_result_is_refused_on_encode() -> None:
    with pytest.raises(ValueError):
        encode_result({"reference": "4821"})


def test_a_datetime_is_encoded_as_utc_text_with_a_z_suffix() -> None:
    local = datetime(2026, 10, 23, 14, 0, 0, 5, tzinfo=timezone(timedelta(hours=1)))
    _, json_text = encode_result(_entry(at=local))
    assert "2026-10-23T13:00:00.000005Z" in json_text


@dataclass(frozen=True, slots=True)
class Outside:
    """A dataclass that is importable but lives outside the allowed packages."""

    count: int


def test_a_dataclass_outside_the_allowed_packages_is_refused_on_decode_and_encode() -> None:
    type_name = f"{Outside.__module__}:{Outside.__qualname__}"
    stored = '{"$type":"' + type_name + '","fields":{"count":1}}'
    with pytest.raises(ValueError):
        decode_result(type_name, stored)
    with pytest.raises(ValueError):
        encode_result(Outside(count=1))


def test_a_calendar_date_in_a_result_round_trips_as_the_same_date() -> None:
    result = ConfirmCriteriaResult(criteria_id="crit-ucr-west-4", review_by=date(2027, 4, 23))
    type_name, text = encode_result(result)
    decoded = decode_result(type_name, text)
    assert decoded == result
    assert type(decoded.review_by) is date


def test_a_calendar_date_is_stored_as_its_own_text_not_as_an_instant() -> None:
    _, text = encode_result(ConfirmCriteriaResult(criteria_id="c", review_by=date(2027, 4, 23)))
    assert '"review_by":{"$date":"2027-04-23"}' in text


@pytest.mark.parametrize(
    "stored_day",
    ["2027-02-30", "2027-1-5", "27-01-05", "2027-01-31T00:00:00Z", "2027-01-31 "],
)
def test_a_stored_day_that_is_not_a_calendar_date_in_canonical_form_is_refused(
    stored_day: str,
) -> None:
    type_name = "diucs.application.use_cases.criteria:ConfirmCriteriaResult"
    stored = (
        '{"$type":"' + type_name + '","fields":{"criteria_id":"c",'
        '"review_by":{"$date":"' + stored_day + '"},"replayed":false}}'
    )
    with pytest.raises(ValueError):
        decode_result(type_name, stored)
