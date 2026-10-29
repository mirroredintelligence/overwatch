"""The idempotency key of a prompt (U04).

A grouped prompt stores a result under the other services' keys, so that their own jobs do nothing
when they run. The job that runs them builds its key the same way, so the form is one function.
"""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from diucs.application.use_cases.send_prompts import prompt_key

DUE = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


def test_the_key_is_the_service_and_the_due_instant_in_utc() -> None:
    assert prompt_key("ucr-west", DUE) == "prompt:ucr-west:2026-10-23T09:00:00+00:00"


def test_the_same_instant_in_another_zone_gives_the_same_key() -> None:
    london = DUE.astimezone(ZoneInfo("Europe/London"))
    odd = DUE.astimezone(timezone(timedelta(hours=-5)))
    assert prompt_key("ucr-west", london) == prompt_key("ucr-west", DUE)
    assert prompt_key("ucr-west", odd) == prompt_key("ucr-west", DUE)


def test_another_service_or_another_instant_gives_another_key() -> None:
    assert prompt_key("ucr-east", DUE) != prompt_key("ucr-west", DUE)
    assert prompt_key("ucr-west", DUE + timedelta(hours=2)) != prompt_key("ucr-west", DUE)
