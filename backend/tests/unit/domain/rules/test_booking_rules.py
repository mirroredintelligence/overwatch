"""Booking rules around the state machine (D14).

Rules: docs/spec/domain-rules.md section 3.2. Names: docs/spec/contracts.md, rules/booking_rules.py row.
Decisions: DEC-016 (references match exactly, never by prefix).
"""

import ast
import random
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.domain.codes import BookingStatus
from diucs.domain.errors import Conflict
from diucs.domain.rules.booking_rules import (
    BOOKING_REPLY_WINDOW,
    PHONE_PROMPT_AFTER,
    REFERENCE_ATTEMPTS,
    AskWhichReference,
    NoOpenBooking,
    OpenBookingRef,
    booking_reply_by,
    can_request,
    match_reply,
    new_reference,
    phone_prompt_at,
)

REQUESTED_AT = datetime(2026, 10, 23, 13, 16, tzinfo=UTC)


def booking(booking_id: str, reference: str, service_id: str) -> OpenBookingRef:
    return OpenBookingRef(booking_id=booking_id, reference=reference, service_id=service_id)


# Constants: domain-rules.md 3.2 (10 minutes, phone prompt at 5 minutes) and DEC-007 (4 digits).


def test_the_reply_window_and_phone_prompt_are_the_rule_book_values() -> None:
    assert BOOKING_REPLY_WINDOW == timedelta(minutes=10)
    assert PHONE_PROMPT_AFTER == timedelta(minutes=5)
    assert REFERENCE_ATTEMPTS == 50


def test_the_phone_prompt_comes_before_the_reply_by_time() -> None:
    assert timedelta(0) < PHONE_PROMPT_AFTER < BOOKING_REPLY_WINDOW


# 1. Timers


def test_requested_at_1316_utc_has_reply_by_1326_and_phone_prompt_1321() -> None:
    assert booking_reply_by(REQUESTED_AT) == datetime(2026, 10, 23, 13, 26, tzinfo=UTC)
    assert phone_prompt_at(REQUESTED_AT) == datetime(2026, 10, 23, 13, 21, tzinfo=UTC)


def test_requested_at_1416_prompts_at_1421_and_expires_at_1426() -> None:
    requested = datetime(2026, 10, 23, 14, 16, tzinfo=UTC)
    assert phone_prompt_at(requested) == datetime(2026, 10, 23, 14, 21, tzinfo=UTC)
    assert booking_reply_by(requested) == datetime(2026, 10, 23, 14, 26, tzinfo=UTC)


@given(
    requested=st.datetimes(
        min_value=datetime(2000, 1, 1),
        max_value=datetime(2100, 1, 1),
        timezones=st.just(UTC),
    )
)
def test_timers_are_fixed_offsets_from_the_request_for_any_instant(requested: datetime) -> None:
    assert booking_reply_by(requested) - requested == BOOKING_REPLY_WINDOW
    assert phone_prompt_at(requested) - requested == PHONE_PROMPT_AFTER


def test_timers_are_instants_across_the_london_clock_change() -> None:
    # The UK clock changes at 01:00 UTC on 2026-03-29. Timers are plain instant offsets, so the
    # change must not shift them. Lesson L4: compare instants, never local wall-clock times.
    requested = datetime(2026, 3, 29, 0, 55, tzinfo=UTC)
    assert booking_reply_by(requested) == datetime(2026, 3, 29, 1, 5, tzinfo=UTC)
    assert phone_prompt_at(requested) == datetime(2026, 3, 29, 1, 0, tzinfo=UTC)


# 2. One open request per service


def test_a_service_with_no_bookings_can_take_a_request() -> None:
    assert can_request([]) is True


@pytest.mark.parametrize(
    "statuses",
    [
        [BookingStatus.CONFIRMED, BookingStatus.DECLINED],
        [BookingStatus.EXPIRED, BookingStatus.CANCELLED_BEFORE, BookingStatus.COMPLETED],
    ],
)
def test_a_service_with_only_answered_or_closed_bookings_can_take_a_request(
    statuses: list[BookingStatus],
) -> None:
    assert can_request(statuses) is True


def test_a_service_with_a_requested_booking_cannot_take_another() -> None:
    assert can_request([BookingStatus.REQUESTED]) is False


def test_one_open_booking_blocks_a_request_among_closed_ones() -> None:
    assert can_request([BookingStatus.CONFIRMED, BookingStatus.REQUESTED]) is False


# 3 and 4. References: 4 digits, seeded, retried on collision


def test_a_new_reference_is_four_digits_between_1000_and_9999() -> None:
    reference = new_reference(random.Random(42), set())
    assert len(reference) == 4
    assert reference.isdecimal()
    assert "1000" <= reference <= "9999"


def test_the_same_seed_gives_the_same_reference() -> None:
    assert new_reference(random.Random(42), set()) == new_reference(random.Random(42), set())


def test_a_taken_reference_is_not_returned_again() -> None:
    first = new_reference(random.Random(42), set())
    second = new_reference(random.Random(42), {first})
    assert second != first
    assert len(second) == 4


@given(seed=st.integers(min_value=0, max_value=2**32 - 1))
def test_any_seed_gives_a_four_digit_reference_without_a_leading_zero(seed: int) -> None:
    reference = new_reference(random.Random(seed), set())
    assert reference.isdecimal()
    assert len(reference) == 4
    assert reference[0] != "0"


def test_a_reference_is_never_one_of_the_taken_values() -> None:
    taken = {str(n) for n in range(1000, 1500)}
    for seed in range(200):
        assert new_reference(random.Random(seed), taken) not in taken


# 5. Collisions exhaust the attempts


def test_every_reference_taken_raises_conflict() -> None:
    taken = {str(n) for n in range(1000, 10000)}
    assert len(taken) == 9000
    with pytest.raises(Conflict):
        new_reference(random.Random(42), taken)


# 6 to 8. Matching a text reply


def test_no_open_booking_and_no_reference_is_no_open_booking() -> None:
    assert match_reply([], None) == NoOpenBooking()


def test_no_open_booking_and_a_reference_is_no_open_booking() -> None:
    assert match_reply([], "4821") == NoOpenBooking()


def test_one_open_booking_without_a_reference_is_that_booking() -> None:
    only = booking("b1", "4821", "ucr-west")
    assert match_reply([only], None) == only


def test_one_open_booking_with_its_reference_is_that_booking() -> None:
    only = booking("b1", "4821", "ucr-west")
    assert match_reply([only], "4821") == only


def test_one_open_booking_with_another_reference_is_no_open_booking() -> None:
    only = booking("b1", "4821", "ucr-west")
    assert match_reply([only], "9999") == NoOpenBooking()


def test_two_open_bookings_without_a_reference_ask_which_one_in_ascending_order() -> None:
    east = booking("b1", "4821", "ucr-east")
    west = booking("b2", "3170", "ucr-west")
    assert match_reply([east, west], None) == AskWhichReference(("3170", "4821"))


def test_two_open_bookings_with_a_reference_match_that_one() -> None:
    east = booking("b1", "4821", "ucr-east")
    west = booking("b2", "3170", "ucr-west")
    assert match_reply([east, west], "3170") == west


# Beyond the prompt: DEC-016 says a reference matches exactly, never by prefix.


@pytest.mark.parametrize("reply", ["482", "48", "48211"])
def test_a_reference_that_is_a_prefix_or_extension_of_an_open_one_does_not_match(
    reply: str,
) -> None:
    only = booking("b1", "4821", "ucr-west")
    assert match_reply([only], reply) == NoOpenBooking()


def test_an_exact_reference_does_not_match_when_another_open_one_shares_its_prefix() -> None:
    long_one = booking("b1", "48211", "ucr-east")
    short_one = booking("b2", "4821", "ucr-west")
    assert match_reply([long_one, short_one], "4821") == short_one
    assert match_reply([long_one], "4821") == NoOpenBooking()


def test_a_reference_matching_none_of_several_open_bookings_is_no_open_booking() -> None:
    east = booking("b1", "4821", "ucr-east")
    west = booking("b2", "3170", "ucr-west")
    assert match_reply([east, west], "9999") == NoOpenBooking()


# ---------------------------------------------------------------- TEN-064: the policy must be passed

# The thirteen functions threaded here, each with the position of its `policy` argument. A caller
# that passes neither a `policy` keyword nor an argument in that position fails the ratchet, except
# the callers named in `POLICY_NOT_YET_THREADED_064`, each with the task that converts it.
POLICY_POSITION_064: Final = {
    "booking_rules": {"booking_reply_by": 1, "phone_prompt_at": 1},
    "report_flags": {"flags_for_report": 3},
    "multi_service": {"group_due": 1, "phone_overloaded": 1},
    "criteria_workflow": {"review_reminder_due": 2},
    "alerts": {"default_preferences": 0, "alerts_for_change": 5, "alert_for_pressure": 3},
    "clinical_queue": {"take": 3, "return_if_idle": 2, "give_advice": 3},
    "identity_policy": {"needs_reverification": 3},
}
_SOURCE_ROOT_064: Final = Path(__file__).resolve().parents[4] / "src" / "diucs"
_RULES_PACKAGE: Final = "diucs.domain.rules"

# Callers that do not yet pass the tenant's policy. Each entry must still offend: a converted
# caller is removed, so the list can only shrink. The owners are the builder's reading of the
# tenancy plan (DEC-233 item 4 did the same for TEN-021's list).
POLICY_NOT_YET_THREADED_064: dict[str, str] = {
    "application/use_cases/criteria_reviews.py": "TEN-026",
    "application/use_cases/move_service.py": "TEN-026",
    "application/use_cases/pin.py": "TEN-026",
    "application/use_cases/request_booking.py": "TEN-026",
    "application/use_cases/send_prompts.py": "TEN-027",
    "application/use_cases/subscribe_alert.py": "TEN-026",
}


def _imports_from_rules(tree: ast.Module) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """The threaded functions a file imports by name (local name to module and function), and the
    local names it gives to a threaded rule module."""
    functions: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module.startswith(f"{_RULES_PACKAGE}."):
                module = node.module.removeprefix(f"{_RULES_PACKAGE}.")
                for alias in node.names:
                    if alias.name in POLICY_POSITION_064.get(module, {}):
                        functions[alias.asname or alias.name] = (module, alias.name)
            elif node.module == _RULES_PACKAGE:
                for alias in node.names:
                    if alias.name in POLICY_POSITION_064:
                        modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{_RULES_PACKAGE}.") and alias.asname:
                    module = alias.name.removeprefix(f"{_RULES_PACKAGE}.")
                    if module in POLICY_POSITION_064:
                        modules[alias.asname] = module
    return functions, modules


def _policy_missing_064(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions, modules = _imports_from_rules(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target: tuple[str, str] | None = None
        if isinstance(node.func, ast.Name) and node.func.id in functions:
            target = functions[node.func.id]
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in modules
            and node.func.attr in POLICY_POSITION_064[modules[node.func.value.id]]
        ):
            target = (modules[node.func.value.id], node.func.attr)
        if target is None:
            continue
        if any(keyword.arg == "policy" for keyword in node.keywords):
            continue
        unpacked = any(isinstance(arg, ast.Starred) for arg in node.args) or any(
            keyword.arg is None for keyword in node.keywords
        )
        if not unpacked and len(node.args) > POLICY_POSITION_064[target[0]][target[1]]:
            continue
        found.append(f"{target[1]}:{node.lineno}")
    return found


def test_remaining_rules_are_called_with_a_policy() -> None:
    offending = {}
    for path in sorted(_SOURCE_ROOT_064.rglob("*.py")):
        relative = path.relative_to(_SOURCE_ROOT_064).as_posix()
        if relative.startswith("domain/rules/") and path.stem in POLICY_POSITION_064:
            continue  # the defining modules
        if calls := _policy_missing_064(path):
            offending[relative] = calls

    assert set(offending) <= set(POLICY_NOT_YET_THREADED_064), offending


def test_every_policy_ratchet_entry_still_offends_and_names_its_task() -> None:
    for relative, owner in POLICY_NOT_YET_THREADED_064.items():
        assert re.fullmatch(r"TEN-\d{3}", owner), (relative, owner)
        path = _SOURCE_ROOT_064 / relative
        assert path.is_file(), relative
        assert _policy_missing_064(path), f"{relative} passes its policy now: remove it"


def test_the_ratchet_sees_every_way_a_function_is_called(tmp_path: Path) -> None:
    sample = tmp_path / "caller.py"
    sample.write_text(
        "from diucs.domain.rules.booking_rules import booking_reply_by, phone_prompt_at as later\n"
        "from diucs.domain.rules import clinical_queue as queue\n"
        "from diucs.domain.rules.multi_service import group_due\n"
        "import diucs.domain.rules.alerts as alert_rules\n"
        "booking_reply_by(t)\n"  # missing
        "booking_reply_by(t, p)\n"  # positional
        "later(t, policy=p)\n"  # keyword
        "later(t)\n"  # missing, through an alias
        "queue.take(r, c, now)\n"  # missing, through the module
        "queue.take(r, c, now, p)\n"
        "group_due(*args)\n"  # unpacked: cannot be seen, so missing
        "alert_rules.default_preferences()\n"  # missing at position 0
        "alert_rules.default_preferences(p)\n"
        "other.take(1, 2, 3)\n"  # not a rule module: never matched
        "take(1, 2, 3)\n",  # a bare `take` that was not imported from a rule module
        encoding="utf-8",
    )

    assert _policy_missing_064(sample) == [
        "booking_reply_by:5",
        "phone_prompt_at:8",
        "take:9",
        "group_due:11",
        "default_preferences:12",
    ]
