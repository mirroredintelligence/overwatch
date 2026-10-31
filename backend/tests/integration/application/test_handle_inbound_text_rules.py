"""HandleInboundText: the rows of the capacity-loop triage (KI-26, KI-30, KI-31, KI-33, KI-102,
KI-104, KI-141), on the real Neo4j and an InMemoryCache.

Same world as test_handle_inbound_text.py (Friday 23 October 2026, London time; UCR West and UCR
East on one phone, prompted together by one C9 at 10:00, reply-by 10:30). Sample values only.
"""

import asyncio
import dataclasses
from datetime import timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.handle_inbound_text import (
    CONFIRMED,
    LATE,
    NEED_NUMBER,
    RECHECK,
    RECORDED,
    STALE_FIGURE,
    HandleInboundTextResult,
)
from diucs.domain.codes import Cadence, ReportType
from diucs.domain.errors import Conflict
from tests.integration.application.test_handle_inbound_text import (
    EARLY,
    LONG_AGO,
    PHONE,
    ROLE_EAST,
    ROLE_WEST,
    STORE_CLOCK,
    UCR_EAST,
    UCR_WEST,
    Rig,
    Seed,
    _c9_text,
    _handle_audits,
    _latest,
    _one_reporter_one_prompt,
    _replies,
    _reports,
    _seed_figure,
    _seed_group,
    _seed_people,
    _seed_prompt,
    _Switch,
    _UnitOfWorkWithFlakyAudit,
    bst,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def uow_clock() -> FixedClock:
    """The clock the graph store stamps writes with, as in test_handle_inbound_text.py: hazard H-32
    turns on the write time, so a seeded figure was written long before the prompt."""
    STORE_CLOCK.set(EARLY)
    return STORE_CLOCK


# --- KI-26: a refusal on a grouped prompt names the letter and keeps the group -------------------


async def test_a_grouped_out_of_range_figure_is_asked_again_with_its_letter(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("A 40", bst(10, 12))

    assert result == HandleInboundTextResult(RECHECK, ("ucr-east",))
    [ask] = await _replies(neo4j_driver)
    assert ask["messageId"] == "C7"
    assert ask["text"].endswith("If it is right, send A 40 again.")


async def test_a_grouped_third_y_is_refused_with_the_letter_to_send(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("Y A", bst(10, 5))
    await rig.say("Y A", bst(10, 6))

    await rig.say("Y A", bst(10, 7))

    c6 = [r for r in await _replies(neo4j_driver) if r["messageId"] == "C6"]
    assert [r["text"] for r in c6] == [
        "Y was used twice already. Please send A and the number for UCR East."
    ]


async def test_a_late_grouped_number_is_refused_with_the_lettered_replies(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    await rig.say("B 5", bst(10, 31))

    [refusal] = await _replies(neo4j_driver)
    assert refusal["messageId"] == "C5"
    assert refusal["text"].endswith("Reply Y B if right, or send B and the new number, by 11:01.")


async def test_a_grouped_service_with_no_figure_is_asked_for_a_lettered_number(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_people(uow_factory, (ROLE_WEST, ROLE_EAST))
    await _seed_figure(uow_factory, 3, bst(8, 15), "ucr-west")
    for service_id, role_id in (("ucr-east", "role-east"), ("ucr-west", "role-west")):
        await _seed_prompt(
            uow_factory,
            bst(10, 0),
            message_id="C9",
            role_id=role_id,
            service_id=service_id,
            prompt_id=f"c9-{service_id}",
            text=_c9_text(),
        )
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y A", bst(10, 5))

    assert result == HandleInboundTextResult(NEED_NUMBER, ("ucr-east",))
    c2 = [r for r in await _replies(neo4j_driver) if r["messageId"] == "C2"]
    assert len(c2) == 1
    assert "Send A and a number (0 = closed)." in c2[0]["text"]


async def test_a_refusal_for_one_service_does_not_end_the_group(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """The C5 for East is sent as a reply to the group's C9. It must not become the phone's
    prompt: a lettered reply for West is still read against the group (and refused for its own
    window, which is the C9's), and East's own window runs from its C5."""
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    first = await rig.say("A 5", bst(10, 40))  # late: East gets a C5, reply-by 11:10
    second = await rig.say("B 4", bst(10, 41))  # West is judged on the C9's window: late too
    third = await rig.say("A 5", bst(10, 42))  # East answers its C5 inside its new window

    assert first == HandleInboundTextResult(LATE, ("ucr-east",))
    assert second == HandleInboundTextResult(LATE, ("ucr-west",))
    assert third == HandleInboundTextResult(RECORDED, ("ucr-east",))
    assert [r.value for r in await _reports(uow_factory, "ucr-east")] == [1, 5]
    assert [r.value for r in await _reports(uow_factory, "ucr-west")] == [3]
    refusals = [r for r in await _replies(neo4j_driver) if r["messageId"] == "C5"]
    assert [r["about"] for r in refusals] == ["ucr-east", "ucr-west"]
    # Both are replies to the group's one C9 (as stored: one comm per service, same text).
    assert len({r["inResponseTo"] for r in refusals}) == 1
    assert refusals[0]["inResponseTo"].startswith("c9-")


async def test_a_grouped_stale_refusal_is_answered_by_a_lettered_number_in_its_own_window(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_people(uow_factory, (ROLE_WEST, ROLE_EAST))
    await _seed_figure(uow_factory, 3, bst(8, 15), "ucr-west")
    await _seed_figure(uow_factory, 1, LONG_AGO, "ucr-east")
    for service_id, role_id in (("ucr-east", "role-east"), ("ucr-west", "role-west")):
        await _seed_prompt(
            uow_factory,
            bst(10, 0),
            message_id="C9",
            role_id=role_id,
            service_id=service_id,
            prompt_id=f"c9-{service_id}",
            text=_c9_text(),
        )
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("Y", bst(10, 25))  # East's figure is stale: C12 until 10:55; West confirmed

    result = await rig.say("A 2", bst(10, 40))  # past the C9's 10:30, inside the C12's window

    assert result == HandleInboundTextResult(RECORDED, ("ucr-east",))
    assert (await _latest(uow_factory, "ucr-east")).value == 2


# --- KI-30: waiting means nothing was written since the prompt ------------------------------------


async def test_a_figure_recorded_after_the_prompt_for_an_earlier_time_is_not_waiting(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    # A lead recorded West's figure at 10:05 for 09:50: it is the latest figure, written after the
    # prompt, and carries a time before it.
    await _seed_figure(
        uow_factory, 4, bst(9, 50), "ucr-west", report_id="lead-phoned", written_at=bst(10, 5)
    )
    rig = Rig(uow_factory, neo4j_driver)

    await rig.say("A 2", bst(10, 12))

    [thanks] = await _replies(neo4j_driver)
    assert thanks["messageId"] == "C10"
    assert thanks["text"] == "Thanks. A) UCR East updated to 2."


async def test_a_service_nothing_has_answered_since_the_prompt_is_still_waiting(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST, UCR_EAST)
    await _seed_group(uow_factory)
    rig = Rig(uow_factory, neo4j_driver)

    await rig.say("A 2", bst(10, 12))

    [thanks] = await _replies(neo4j_driver)
    assert "B) UCR West still needs a reply" in thanks["text"]


# --- KI-31: a figure dated after the clock does not stop a reply ----------------------------------


async def test_a_number_is_recorded_when_the_latest_figure_is_dated_after_the_clock(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    await _seed_figure(uow_factory, 3, bst(10, 20), report_id="ahead", written_at=bst(9, 0))
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("4", bst(10, 12))

    assert result == HandleInboundTextResult(RECORDED, ("ucr-west",))
    latest = await _latest(uow_factory)
    assert latest.value == 4
    assert latest.effective_at == bst(10, 20) + timedelta(microseconds=1)


async def test_a_y_is_answered_when_the_latest_figure_is_dated_after_the_clock(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    await _seed_figure(uow_factory, 3, bst(10, 20), report_id="ahead", written_at=bst(9, 0))
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(10, 12))

    assert result == HandleInboundTextResult(CONFIRMED, ("ucr-west",))
    latest = await _latest(uow_factory)
    assert latest.report_type is ReportType.CONFIRMED
    assert latest.effective_at == bst(10, 20) + timedelta(microseconds=1)


# --- Q4, KI-27: a daily service may confirm a figure a day old -------------------------------------


async def _daily_service_with_figure(
    uow_factory: UnitOfWorkFactory, seed_service: Seed, figure_age: timedelta
) -> None:
    daily = dataclasses.replace(UCR_WEST, cadence=Cadence.ONCE_A_DAY)
    await seed_service(daily)
    await _seed_people(uow_factory)
    await _seed_figure(uow_factory, 3, bst(10, 0) - figure_age)
    await _seed_prompt(uow_factory, bst(10, 0))


async def test_a_y_confirms_a_daily_services_figure_twenty_hours_old(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _daily_service_with_figure(uow_factory, seed_service, timedelta(hours=20))
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(10, 5))

    assert result == HandleInboundTextResult(CONFIRMED, ("ucr-west",))


async def test_a_y_does_not_confirm_a_daily_services_figure_past_its_day(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _daily_service_with_figure(uow_factory, seed_service, timedelta(hours=24, microseconds=1))
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(10, 5))

    assert result == HandleInboundTextResult(STALE_FIGURE, ("ucr-west",))


async def test_a_y_for_a_two_hourly_service_keeps_the_two_hours(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory)
    await _seed_figure(uow_factory, 3, bst(10, 0) - timedelta(hours=2, microseconds=1))
    await _seed_prompt(uow_factory, bst(10, 0))
    rig = Rig(uow_factory, neo4j_driver)

    result = await rig.say("Y", bst(10, 5))

    assert result == HandleInboundTextResult(STALE_FIGURE, ("ucr-west",))


# --- KI-33: the recheck key is written before the commit ------------------------------------------


class _CacheFailingOnSet(InMemoryCache):
    """A cache whose writes fail, as Redis can."""

    fail_set = False

    async def set(self, key: str, value: str, ttl: timedelta) -> None:
        if self.fail_set:
            raise ConnectionError("the cache is down")
        await super().set(key, value, ttl)


async def test_a_failed_cache_write_stops_the_message_before_anything_is_committed(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    cache = _CacheFailingOnSet(rig.clock)
    cache.fail_set = True
    rig.use_case._cache = cache  # type: ignore[assignment]
    before = await _replies(neo4j_driver)

    with pytest.raises(ConnectionError):
        await rig.say("40", bst(10, 12), key="SM-ask")

    # Nothing was committed: no reply, no audit entry, no stored result. The redelivery asks again.
    assert await _replies(neo4j_driver) == before
    assert await _handle_audits(uow_factory) == []
    cache.fail_set = False

    result = await rig.say("40", bst(10, 13), key="SM-ask")

    assert result == HandleInboundTextResult(RECHECK, ("ucr-west",))
    assert await cache.get(f"recheck:{PHONE}:ucr-west") == "40"
    assert len(await _handle_audits(uow_factory)) == 1


async def test_a_message_retried_after_its_commit_failed_asks_again_and_does_not_record(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    """The key is written before the commit, so a failed commit leaves it behind. The redelivery of
    the same message must not read its own first attempt as the repeat that records the figure."""
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    switch = _Switch()

    def flaky() -> Any:
        return _UnitOfWorkWithFlakyAudit(uow_factory(), switch)

    rig = Rig(uow_factory, neo4j_driver, use_case_factory=flaky)
    with pytest.raises(RuntimeError):
        await rig.say("40", bst(10, 12), key="SM-ask-2")

    result = await rig.say("40", bst(10, 13), key="SM-ask-2")

    assert result == HandleInboundTextResult(RECHECK, ("ucr-west",))
    assert [r.value for r in await _reports(uow_factory)] == [3]
    assert await rig.cache.get(f"recheck:{PHONE}:ucr-west") == "40"


async def test_a_different_message_with_the_same_figure_is_still_the_repeat_that_records(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("40", bst(10, 12), key="SM-first")

    result = await rig.say("40", bst(10, 13), key="SM-second")

    assert result == HandleInboundTextResult(RECORDED, ("ucr-west",))
    assert (await _latest(uow_factory)).value == 40


# --- KI-102, KI-104: a Y while a figure is pending, and when the key is lost ----------------------


async def test_a_y_after_an_out_of_range_figure_asks_again_and_does_not_confirm(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("40", bst(10, 12))

    result = await rig.say("Y", bst(10, 13))

    assert result == HandleInboundTextResult(RECHECK, ("ucr-west",))
    assert [r.report_type for r in await _reports(uow_factory)] == [ReportType.NUMBER]


async def test_a_y_after_the_pending_key_is_lost_is_an_ordinary_y(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("40", bst(10, 12))
    await rig.cache.delete(f"recheck:{PHONE}:ucr-west")  # evicted, or lost with the cache

    result = await rig.say("Y", bst(10, 13))

    assert result == HandleInboundTextResult(CONFIRMED, ("ucr-west",))
    assert [r.report_type for r in await _reports(uow_factory)] == [
        ReportType.NUMBER,
        ReportType.CONFIRMED,
    ]


async def test_a_y_after_the_pending_key_is_lost_is_still_judged_for_a_stale_figure(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await seed_service(UCR_WEST)
    await _seed_people(uow_factory)
    await _seed_figure(uow_factory, 3, LONG_AGO)
    await _seed_prompt(uow_factory, bst(10, 0))
    rig = Rig(uow_factory, neo4j_driver)
    await rig.say("40", bst(10, 12))
    await rig.cache.delete(f"recheck:{PHONE}:ucr-west")

    result = await rig.say("Y", bst(10, 13))

    assert result == HandleInboundTextResult(STALE_FIGURE, ("ucr-west",))
    assert len(await _reports(uow_factory)) == 1


# --- KI-141: a duplicate delivered at the same moment writes one record --------------------------


async def test_two_deliveries_of_one_message_at_the_same_moment_write_one_audit_entry(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _one_reporter_one_prompt(uow_factory, neo4j_driver, seed_service)
    rig = Rig(uow_factory, neo4j_driver)

    outcomes = await asyncio.gather(
        rig.say("4", bst(10, 12), key="SM-same"),
        rig.say("4", bst(10, 12), key="SM-same"),
        return_exceptions=True,
    )

    # A loser may be refused as a Conflict (the provider redelivers it); nothing else may fail.
    assert [
        o for o in outcomes if isinstance(o, BaseException) and not isinstance(o, Conflict)
    ] == []
    assert any(isinstance(o, HandleInboundTextResult) for o in outcomes)
    assert len(await _handle_audits(uow_factory)) == 1
    assert [r["messageId"] for r in await _replies(neo4j_driver)] == ["C3"]
    assert len(await _reports(uow_factory)) == 2
