"""A grouped prompt from SendPrompts (U04) is read correctly by HandleInboundText (U05).

U05 works out which service a letter means from what U04 stored (lesson L153): one C9
Communication for each service, with the same send time and text. This runs the two use cases
against each other on the real Neo4j, so a change to either side that breaks the seam fails here
and not in the field, where a reply would land on the wrong service.
"""

from datetime import UTC, datetime

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.confirm_capacity import ConfirmCapacity
from diucs.application.use_cases.handle_inbound_text import (
    CONFIRMED,
    RECORDED,
    HandleInboundText,
    HandleInboundTextCommand,
    HandleInboundTextResult,
)
from diucs.application.use_cases.report_capacity import ReportCapacity
from tests.integration.application.test_send_prompts_grouped import (
    EAST,
    PHONE,
    WEST,
    Seed,
    _command,
    _london,
    _rig,
    _seed_phone,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def uow_clock() -> FixedClock:
    """The clock the store stamps writes with: long before the prompt, so a seeded figure was
    reported before it (hazard H-32 turns on the write time)."""
    return FixedClock(datetime(2026, 1, 1, tzinfo=UTC))


def _handler(
    factory: UnitOfWorkFactory, driver: AsyncDriver, clock: FixedClock
) -> HandleInboundText:
    ids = SequentialIds("in")
    store = DriverIdempotencyStore(driver)
    return HandleInboundText(
        factory,
        clock,
        ids,
        store,
        InMemoryCache(clock),
        ReportCapacity(factory, clock, ids, store),
        ConfirmCapacity(factory, clock, ids, store),
    )


def _text(key: str, text: str, at: datetime) -> HandleInboundTextCommand:
    return HandleInboundTextCommand(
        idempotency_key=key, from_phone_hash=PHONE, text=text, received_at=at
    )


async def test_a_lettered_reply_lands_on_the_service_the_letter_was_sent_for(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    prompts, clock = _rig(uow_factory, neo4j_driver)
    await prompts.execute(_command("ucr-west"))
    clock.set(_london(10, 12))
    handler = _handler(uow_factory, neo4j_driver, clock)

    # B is UCR West, A is UCR East (name order), whichever service's job sent the prompt.
    first = await handler.execute(_text("SM1", "B 2", _london(10, 12)))
    second = await handler.execute(_text("SM2", "Y A", _london(10, 13)))

    assert first == HandleInboundTextResult(RECORDED, ("ucr-west",))
    assert second == HandleInboundTextResult(CONFIRMED, ("ucr-east",))
    async with uow_factory() as uow:
        west = await uow.capacity.latest("ucr-west")
        east_reports = await uow.capacity.reports_since(
            "ucr-east", datetime(2026, 1, 1, tzinfo=UTC)
        )
    assert west is not None and west.value == 2
    assert [report.value for report in east_reports] == [1, 1]
