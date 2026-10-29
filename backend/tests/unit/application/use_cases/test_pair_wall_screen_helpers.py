"""Unit tests for the pure parts of PairWallScreen (U10): the typed code, and the attempt limiter
over the in-memory cache. The use cases themselves are tested against Neo4j in
tests/integration/application/test_pair_wall_screen.py. Values are synthetic."""

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.use_cases.pair_wall_screen import AttemptLimiter, normalise_code

NOW = datetime(2026, 10, 23, 13, 12, tzinfo=UTC)
WINDOW = timedelta(minutes=10)


@pytest.mark.parametrize(
    ("typed", "digits"),
    [
        ("482 913", "482913"),
        ("482913", "482913"),
        ("482-913", "482913"),
        ("  482 913  ", "482913"),
        ("4 8 2 9 1 3", "482913"),
        ("000 000", "000000"),
    ],
)
def test_a_typed_code_is_its_six_digits(typed: str, digits: str) -> None:
    assert normalise_code(typed) == digits


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "   ",
        "48291",
        "4829133",
        "abc def",
        "482 91x",
        "482.913",
        "٤٨٢٩١٣",
        "482\n913",
        "+482913",
    ],
)
def test_anything_that_is_not_six_ascii_digits_is_none(typed: str) -> None:
    assert normalise_code(typed) is None


def test_a_non_string_is_none() -> None:
    assert normalise_code(482913) is None  # type: ignore[arg-type]


@given(st.text(max_size=40))
def test_a_typed_code_is_never_an_error_and_never_anything_but_six_digits(typed: str) -> None:
    digits = normalise_code(typed)
    assert digits is None or (len(digits) == 6 and digits.isascii() and digits.isdigit())


@given(st.text(alphabet="0123456789 -", max_size=30))
def test_the_digits_returned_are_exactly_the_digits_typed(typed: str) -> None:
    digits = normalise_code(typed)
    typed_digits = "".join(c for c in typed if c.isdigit())
    if digits is not None:
        assert digits == typed_digits


async def test_take_allows_the_limit_and_refuses_the_next() -> None:
    limiter = AttemptLimiter(InMemoryCache(FixedClock(NOW)))
    assert [await limiter.take("k", 3, WINDOW) for _ in range(5)] == [
        True,
        True,
        True,
        False,
        False,
    ]


async def test_take_gives_the_units_back_when_their_window_has_passed() -> None:
    clock = FixedClock(NOW)
    limiter = AttemptLimiter(InMemoryCache(clock))
    for _ in range(3):
        assert await limiter.take("k", 3, WINDOW)
    clock.advance(WINDOW - timedelta(seconds=1))
    assert not await limiter.take("k", 3, WINDOW)
    clock.advance(timedelta(seconds=1))
    assert [await limiter.take("k", 3, WINDOW) for _ in range(4)] == [True, True, True, False]


async def test_the_window_is_counted_from_each_unit_not_from_the_first() -> None:
    clock = FixedClock(NOW)
    limiter = AttemptLimiter(InMemoryCache(clock))
    assert await limiter.take("k", 2, WINDOW)
    clock.advance(timedelta(minutes=6))
    assert await limiter.take("k", 2, WINDOW)
    clock.advance(timedelta(minutes=5))  # the first is 11 minutes old, the second 5
    assert await limiter.take("k", 2, WINDOW)
    assert not await limiter.take("k", 2, WINDOW)


async def test_names_do_not_share_units() -> None:
    limiter = AttemptLimiter(InMemoryCache(FixedClock(NOW)))
    assert await limiter.take("a", 1, WINDOW)
    assert not await limiter.take("a", 1, WINDOW)
    assert await limiter.take("b", 1, WINDOW)


async def test_is_full_reads_without_taking() -> None:
    limiter = AttemptLimiter(InMemoryCache(FixedClock(NOW)))
    assert not await limiter.is_full("k", 2)
    assert not await limiter.is_full("k", 2)
    await limiter.take("k", 2, WINDOW)
    assert not await limiter.is_full("k", 2)
    await limiter.take("k", 2, WINDOW)
    assert await limiter.is_full("k", 2)
    assert await limiter.is_full("k", 2)


async def test_is_full_counts_every_unit_so_an_expired_one_leaves_room() -> None:
    clock = FixedClock(NOW)
    limiter = AttemptLimiter(InMemoryCache(clock))
    await limiter.take("k", 3, WINDOW)
    clock.advance(timedelta(minutes=6))
    await limiter.take("k", 3, WINDOW)
    await limiter.take("k", 3, WINDOW)
    assert await limiter.is_full("k", 3)
    clock.advance(timedelta(minutes=5))  # the first unit has expired, the free slot is the first
    assert not await limiter.is_full("k", 3)


@pytest.mark.parametrize("limit", [0, -1])
async def test_a_limit_below_one_is_refused(limit: int) -> None:
    limiter = AttemptLimiter(InMemoryCache(FixedClock(NOW)))
    with pytest.raises(ValueError, match="limit"):
        await limiter.take("k", limit, WINDOW)
    with pytest.raises(ValueError, match="limit"):
        await limiter.is_full("k", limit)
