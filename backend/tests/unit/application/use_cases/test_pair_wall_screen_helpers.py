"""Unit tests for the pure parts of PairWallScreen (U10): the typed code, and the attempt limiter
over the in-memory cache. The use cases themselves are tested against Neo4j in
tests/integration/application/test_pair_wall_screen.py. Values are synthetic."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.pair_wall_screen import AttemptLimiter, normalise_code


@pytest.fixture(autouse=True)
def _bound_tenant(request: pytest.FixtureRequest) -> Iterator[None]:
    """The cache keys every value by the bound tenant (TEN-019): each test binds one. A test marked
    `no_tenant` runs with nothing bound."""
    if request.node.get_closest_marker("no_tenant") is not None:
        yield
        return
    with bind_tenant("acme-icb"):
        yield


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
    taken = [await limiter.take("k", 3, WINDOW) for _ in range(5)]
    assert [slot is not None for slot in taken] == [True, True, True, False, False]


async def test_take_names_the_slot_it_took_and_no_two_takes_share_one() -> None:
    limiter = AttemptLimiter(InMemoryCache(FixedClock(NOW)))
    slots = [await limiter.take("k", 3, WINDOW) for _ in range(3)]
    assert slots == ["k#0", "k#1", "k#2"]


async def test_release_frees_the_slot_that_was_taken_and_only_that_one() -> None:
    limiter = AttemptLimiter(InMemoryCache(FixedClock(NOW)))
    slots = [await limiter.take("k", 2, WINDOW) for _ in range(2)]
    assert await limiter.take("k", 2, WINDOW) is None
    await limiter.release(str(slots[0]))
    assert await limiter.take("k", 2, WINDOW) == slots[0]
    assert await limiter.take("k", 2, WINDOW) is None


async def test_releasing_a_slot_that_is_free_or_unknown_does_nothing() -> None:
    limiter = AttemptLimiter(InMemoryCache(FixedClock(NOW)))
    await limiter.release("k#0")
    assert await limiter.take("k", 1, WINDOW) == "k#0"


async def test_sixty_racing_takes_of_three_units_give_exactly_three() -> None:
    limiter = AttemptLimiter(InMemoryCache(FixedClock(NOW)))
    results = await asyncio.gather(*(limiter.take("k", 3, WINDOW) for _ in range(60)))
    assert sorted(r for r in results if r is not None) == ["k#0", "k#1", "k#2"]


async def test_take_gives_the_units_back_when_their_window_has_passed() -> None:
    clock = FixedClock(NOW)
    limiter = AttemptLimiter(InMemoryCache(clock))
    for _ in range(3):
        assert await limiter.take("k", 3, WINDOW)
    clock.advance(WINDOW - timedelta(seconds=1))
    assert not await limiter.take("k", 3, WINDOW)
    clock.advance(timedelta(seconds=1))
    again = [await limiter.take("k", 3, WINDOW) for _ in range(4)]
    assert [slot is not None for slot in again] == [True, True, True, False]


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


@pytest.mark.parametrize("limit", [0, -1])
async def test_a_limit_below_one_is_refused(limit: int) -> None:
    limiter = AttemptLimiter(InMemoryCache(FixedClock(NOW)))
    with pytest.raises(ValueError, match="limit"):
        await limiter.take("k", limit, WINDOW)
