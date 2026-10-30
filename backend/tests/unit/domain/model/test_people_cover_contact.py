"""Which protected contact holds the number a message for a post goes to (F6B). Sample values."""

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest

from diucs.domain.codes import Channel, PractitionerRoleCode
from diucs.domain.model.people import (
    COVER_CONTACT_PREFIX,
    PractitionerRole,
    cover_in_force,
    phone_contact_key,
)

NOW = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
POST = PractitionerRole(
    id="r-1",
    practitioner_id="p-own",
    service_id="svc-ucr-west",
    code=PractitionerRoleCode.DUTY_MANAGER,
    active=True,
    channel=Channel.TEXT,
    period_start=datetime(2026, 10, 1, tzinfo=UTC),
)


def _covered(until: datetime) -> PractitionerRole:
    return dataclasses.replace(POST, covered_by_practitioner_id="p-cover", covered_until=until)


def test_the_cover_prefix_is_the_one_the_cover_use_cases_store_under() -> None:
    assert COVER_CONTACT_PREFIX == "cover-"


def test_a_post_with_no_cover_uses_its_own_contact() -> None:
    assert cover_in_force(POST, NOW) is False
    assert phone_contact_key(POST, NOW) == "r-1"


def test_a_running_cover_uses_the_cover_contact() -> None:
    role = _covered(NOW + timedelta(hours=1))

    assert cover_in_force(role, NOW) is True
    assert phone_contact_key(role, NOW) == "cover-r-1"


def test_a_cover_is_over_at_its_end_instant_and_after() -> None:
    role = _covered(NOW)

    assert phone_contact_key(role, NOW) == "r-1"
    assert phone_contact_key(role, NOW + timedelta(seconds=1)) == "r-1"


def test_the_end_is_compared_as_an_instant_whatever_the_zone() -> None:
    plus_one = timezone(timedelta(hours=1))
    role = _covered(datetime(2026, 10, 26, 11, 30, tzinfo=plus_one))  # 10:30 UTC

    assert phone_contact_key(role, NOW) == "cover-r-1"
    assert phone_contact_key(role, NOW + timedelta(minutes=30)) == "r-1"


def test_a_naive_time_is_refused() -> None:
    with pytest.raises(Exception, match="now"):
        cover_in_force(POST, datetime(2026, 10, 26, 10, 0))  # noqa: DTZ001
