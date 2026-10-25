"""Unit tests for domain/model/people.py (P03): practitioners, posts, cover and reporter roles.

Cover is judged on instants: a role covered until 19:00Z is covered at 18:59:59Z and not at 19:00Z
(domain-rules 2.4; fhir-data-model "People, devices and consent"). Same-zone London datetimes are
compared on the instant too (lesson L52), which the clock-change tests below pin.
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from diucs.domain.codes import Channel, PractitionerRoleCode, ReferrerType
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import (
    REPORTER_ROLE_CODES,
    Practitioner,
    PractitionerRole,
    is_in_effect,
    role_holder,
)

H1 = "a" * 64
H2 = "b" * 64
H_UNKNOWN = "d" * 64
LONDON = ZoneInfo("Europe/London")
PERIOD_START = datetime(2026, 10, 1, tzinfo=UTC)
COVER_UNTIL = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)
AT_13 = datetime(2026, 10, 25, 13, 0, tzinfo=UTC)


def _role(**changes: object) -> PractitionerRole:
    fields: dict[str, object] = {
        "id": "r-east",
        "practitioner_id": "p1",
        "service_id": "svc-ucr-east",
        "code": PractitionerRoleCode.DUTY_MANAGER,
        "active": True,
        "channel": Channel.TEXT,
        "period_start": PERIOD_START,
        "period_end": None,
        "covered_by_practitioner_id": "p2",
        "covered_until": COVER_UNTIL,
    }
    fields.update(changes)
    return PractitionerRole(**fields)  # type: ignore[arg-type]


def test_a_practitioner_is_a_person_with_no_telecom_field() -> None:
    person = Practitioner(id="p1", active=True, display_name="Duty Manager One", phone_hash=H1)

    assert person.phone_hash == H1
    assert person.email_domain is None
    assert not hasattr(person, "telecom")


@pytest.mark.parametrize(
    ("at", "holder"),
    [
        (AT_13, "p2"),
        (COVER_UNTIL - timedelta(seconds=1), "p2"),
        (COVER_UNTIL, "p1"),
        (datetime(2026, 10, 25, 20, 0, tzinfo=UTC), "p1"),
    ],
    ids=["during", "one-second-before", "at-covered-until", "after"],
)
def test_role_holder_before_at_and_after_covered_until(at: datetime, holder: str) -> None:
    assert role_holder(_role(), at) == holder


def test_role_holder_is_the_usual_holder_when_there_is_no_cover() -> None:
    role = _role(covered_by_practitioner_id=None, covered_until=None)

    assert role_holder(role, AT_13) == "p1"


def test_cover_is_compared_on_the_instant_not_the_wall_clock_across_the_clock_change() -> None:
    # 01:55 fold=0 is BST, 00:55Z. 01:30 fold=1 is GMT, 01:30Z. The instant 01:30Z is after
    # 00:55Z, so the cover has ended. A wall-clock comparison would say 01:30 is before 01:55.
    covered_until = datetime(2026, 10, 25, 1, 55, tzinfo=LONDON, fold=0)
    at = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=1)
    role = _role(covered_until=covered_until)

    assert role_holder(role, at) == "p1"


def test_is_in_effect_from_the_start_until_the_end() -> None:
    ended = dataclasses.replace(_role(), period_end=datetime(2026, 10, 24, tzinfo=UTC))

    assert is_in_effect(_role(), AT_13) is True
    assert is_in_effect(_role(), PERIOD_START - timedelta(seconds=1)) is False
    assert is_in_effect(ended, AT_13) is False


def test_reporter_roles_are_duty_manager_and_coordinator_only() -> None:
    assert frozenset({PractitionerRoleCode.DUTY_MANAGER, PractitionerRoleCode.COORDINATOR}) == (
        REPORTER_ROLE_CODES
    )


def test_a_plain_string_is_not_a_role_code() -> None:
    with pytest.raises(ValidationFailed):
        _role(code="duty-manager")


def test_a_member_of_another_enum_is_not_a_role_code() -> None:
    with pytest.raises(ValidationFailed):
        _role(code=ReferrerType.OTHER)


def test_a_plain_string_is_not_a_channel() -> None:
    with pytest.raises(ValidationFailed):
        _role(channel="text")


def test_cover_needs_both_the_covering_practitioner_and_the_end_time() -> None:
    with pytest.raises(ValidationFailed):
        _role(covered_until=None)
    with pytest.raises(ValidationFailed):
        _role(covered_by_practitioner_id=None)


def test_a_naive_datetime_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        _role(period_start=datetime(2026, 10, 1))
