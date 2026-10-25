"""Clinical advice queue and presence rules (D23).

Rules: docs/spec/domain-rules.md section 5 and the D23 prompt. Names: docs/spec/contracts.md.
Decision DEC-036 records the choices the prompt leaves open. Every instant is timezone-aware UTC.
"""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.rules.clinical_queue import (
    NOTE_MAX,
    TAKE_TIMEOUT,
    ClinicalRequest,
    Presence,
    advice_shown_as_available,
    available_count,
    give_advice,
    queue_order,
    release_for_away,
    return_if_idle,
    take,
    validate_note,
)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 6, 1, hour, minute, second, tzinfo=UTC)


def request(
    request_id: str,
    urgency: str = "now",
    requested_at: datetime | None = None,
    taken_by: str | None = None,
    taken_at: datetime | None = None,
    advised_at: datetime | None = None,
) -> ClinicalRequest:
    return ClinicalRequest(
        id=request_id,
        case_id=f"case-{request_id}",
        urgency=urgency,
        requested_at=requested_at or at(14, 0),
        taken_by=taken_by,
        taken_at=taken_at,
        advised_at=advised_at,
    )


def test_timeout_and_note_limit_are_the_rule_book_values() -> None:
    assert TAKE_TIMEOUT == timedelta(minutes=10)
    assert NOTE_MAX == 280


def test_take_locks_the_request_to_the_clinician() -> None:
    taken = take(request("r1"), "c1", at(14, 13))

    assert taken.taken_by == "c1"
    assert taken.taken_at == at(14, 13)


def test_second_take_conflicts_while_locked_and_succeeds_after_ten_idle_minutes() -> None:
    locked = take(request("r1"), "c1", at(14, 13))

    with pytest.raises(Conflict):
        take(locked, "c2", at(14, 15))

    taken_by_c2 = take(locked, "c2", at(14, 23))
    assert taken_by_c2.taken_by == "c2"
    assert taken_by_c2.taken_at == at(14, 23)


def test_return_if_idle_keeps_the_lock_just_before_ten_minutes() -> None:
    locked = take(request("r1"), "c1", at(14, 13))

    kept = return_if_idle(locked, at(14, 22, 59))

    assert kept.taken_by == "c1"
    assert kept.taken_at == at(14, 13)


def test_return_if_idle_clears_the_lock_at_ten_minutes() -> None:
    locked = take(request("r1"), "c1", at(14, 13))

    released = return_if_idle(locked, at(14, 23, 0))

    assert released.taken_by is None
    assert released.taken_at is None
    assert released.advised_at is None


def test_only_the_taker_can_give_advice_and_only_once() -> None:
    locked = take(request("r1"), "c1", at(14, 13))

    with pytest.raises(NotAllowed):
        give_advice(locked, "c2", at(14, 14))

    advised = give_advice(locked, "c1", at(14, 14))
    assert advised.advised_at == at(14, 14)

    with pytest.raises(InvalidTransition):
        give_advice(advised, "c1", at(14, 15))


def test_advice_is_still_allowed_on_the_last_second_of_the_lock() -> None:
    locked = take(request("r1"), "c1", at(14, 13))

    advised = give_advice(locked, "c1", at(14, 22, 59))

    assert advised.advised_at == at(14, 22, 59)


def test_advice_after_the_lock_has_lapsed_is_refused() -> None:
    locked = take(request("r1"), "c1", at(14, 13))

    with pytest.raises(NotAllowed):
        give_advice(locked, "c1", at(14, 23))


def test_an_advised_request_cannot_be_taken_again() -> None:
    advised = give_advice(take(request("r1"), "c1", at(14, 13)), "c1", at(14, 14))

    with pytest.raises(InvalidTransition):
        take(advised, "c2", at(14, 40))


def test_return_if_idle_never_releases_an_advised_request() -> None:
    advised = give_advice(take(request("r1"), "c1", at(14, 13)), "c1", at(14, 14))

    kept = return_if_idle(advised, at(14, 40))

    assert kept.taken_by == "c1"
    assert kept.advised_at == at(14, 14)


def test_the_taker_taking_again_keeps_the_original_lock_time() -> None:
    locked = take(request("r1"), "c1", at(14, 13))

    again = take(locked, "c1", at(14, 15))

    assert again.taken_by == "c1"
    assert again.taken_at == at(14, 13)


def test_release_for_away_returns_only_that_clinicians_unadvised_requests_cleared() -> None:
    a = take(request("a"), "c1", at(14, 10))
    b = take(request("b"), "c1", at(14, 11))
    c = give_advice(take(request("c"), "c1", at(14, 12)), "c1", at(14, 13))
    d = take(request("d"), "c2", at(14, 12))

    released = release_for_away([a, b, c, d], "c1")

    assert [r.id for r in released] == ["a", "b"]
    for r in released:
        assert r.taken_by is None
        assert r.taken_at is None
        assert r.advised_at is None


def test_queue_order_puts_now_first_then_oldest_first_within_each_urgency() -> None:
    within_15 = request("w", urgency="within-15-min", requested_at=at(14, 0))
    now_later = request("n2", urgency="now", requested_at=at(14, 5))
    now_earlier = request("n1", urgency="now", requested_at=at(14, 1))

    ordered = queue_order([within_15, now_later, now_earlier])

    assert [r.id for r in ordered] == ["n1", "n2", "w"]


def test_queue_order_leaves_out_locked_and_advised_requests() -> None:
    locked = take(request("locked"), "c1", at(14, 0))
    advised = give_advice(take(request("advised"), "c1", at(14, 0)), "c1", at(14, 1))
    free = request("free", requested_at=at(14, 2))

    ordered = queue_order([locked, advised, free])

    assert [r.id for r in ordered] == ["free"]


def test_available_count_counts_only_available_presence() -> None:
    assert available_count([Presence.AVAILABLE, Presence.BUSY, Presence.AVAILABLE, Presence.AWAY]) == 2


def test_available_count_does_not_count_plain_strings_or_unknown_presence() -> None:
    # A plain string with the same value is not a Presence member (lessons L3, L38).
    assert available_count(["available", "available"]) == 0
    assert available_count([Presence.AVAILABLE, "busy", None]) == 1  # type: ignore[list-item]


def test_available_count_of_nobody_is_zero() -> None:
    assert available_count([]) == 0


@pytest.mark.parametrize(
    ("count", "queue_known", "expected"),
    [
        (1, True, True),
        (3, True, True),
        (0, True, False),
        (None, True, False),
        (2, False, False),
        (None, False, False),
        (True, True, False),
    ],
)
def test_advice_is_shown_as_available_only_when_presence_and_queue_are_known(
    count: int | None, queue_known: bool, expected: bool
) -> None:
    assert advice_shown_as_available(count, queue_known) is expected


def test_validate_note_accepts_up_to_280_characters() -> None:
    validate_note("")
    validate_note("x" * NOTE_MAX)


def test_validate_note_refuses_281_characters() -> None:
    with pytest.raises(ValidationFailed):
        validate_note("x" * (NOTE_MAX + 1))


@pytest.mark.parametrize("urgency", ["today", "NOW", "", "within-2-hrs"])
def test_urgency_must_be_now_or_within_15_min(urgency: str) -> None:
    with pytest.raises(ValidationFailed):
        request("r1", urgency=urgency)


def test_taken_by_and_taken_at_are_set_together() -> None:
    with pytest.raises(ValidationFailed):
        request("r1", taken_by="c1", taken_at=None)
    with pytest.raises(ValidationFailed):
        request("r1", taken_by=None, taken_at=at(14, 13))


def test_naive_datetimes_are_refused() -> None:
    naive = datetime(2026, 6, 1, 14, 13)  # noqa: DTZ001 - the point of the test

    with pytest.raises(ValidationFailed):
        take(request("r1"), "c1", naive)


def test_a_blank_clinician_id_is_refused() -> None:
    with pytest.raises(ValidationFailed):
        take(request("r1"), "", at(14, 13))
