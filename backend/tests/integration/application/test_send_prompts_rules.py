"""SendPrompts: the rows of the capacity-loop triage (KI-23, KI-24, KI-97; DEC-1100 Q3 and Q4), on
the real Neo4j.

- A race of sixteen sends on a WARM graph (lesson L77): the losers reach the idempotency guard, and
  say they lost a race (KI-23, KI-24).
- The refusal of a grouped text by the privacy guard is pinned (KI-97).
- The prompt due at the closing time is sent (Q3).
- Two daily services with a day-old figure are grouped: the figure may be as old as the service's
  own interval (Q4).

Clock: Friday 23 October 2026, London time (BST). Sample values only.
"""

import asyncio
import dataclasses
from datetime import timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases import send_prompts
from diucs.application.use_cases.send_prompts import RACED_MESSAGE
from diucs.domain.codes import Cadence
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.messages.catalogue import MessageId
from tests.integration.application.test_send_prompts import (
    _command,
    _counts,
    _london,
    _outbox,
    _rig,
    _seed_one_reporter,
    _seed_report,
    _sent,
)
from tests.integration.application.test_send_prompts_grouped import (
    EAST,
    WEST,
    Seed,
    _communications,
    _seed_phone,
)
from tests.integration.application.test_send_prompts_grouped import (
    _command as _group_command,
)
from tests.integration.application.test_send_prompts_grouped import (
    _rig as _group_rig,
)
from tests.integration.application.test_send_prompts_grouped import (
    _seed_report as _seed_group_report,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


# --- KI-23, KI-24: a race on a warm graph ---------------------------------------------------------


async def test_sixteen_racing_sends_on_a_warm_graph_record_one_send_and_the_losers_say_so(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    use_case, clock = _rig(uow_factory, neo4j_driver, now=_london(8, 1))
    # An earlier prompt warms the graph: the concepts a send merges exist already, so the losers
    # reach the idempotency guard and not the racing MERGE of a concept (L77).
    warm = await use_case.execute(_command(_london(8, 0)))
    assert warm.sent is True
    clock.set(_london(10, 0))
    before = await _counts(neo4j_driver)

    async def racer() -> tuple[str, str]:
        try:
            result = await use_case.execute(_command(_london(10, 0)))
        except Conflict as refused:
            return "refused", str(refused)
        if result.replayed:
            return "replayed", ""
        return ("sent" if result.sent else "skipped"), ""

    outcomes = await asyncio.gather(*(racer() for _ in range(16)))

    kinds = [kind for kind, _ in outcomes]
    assert kinds.count("sent") == 1
    assert set(kinds) <= {"sent", "replayed", "refused"}
    assert {message for kind, message in outcomes if kind == "refused"} <= {RACED_MESSAGE}
    after = await _counts(neo4j_driver)
    assert {label: after[label] - before[label] for label in after} == {
        "Communication": 1,
        "LinkToken": 1,
        "AuditEvent": 1,
        "OutboxMessage": 5,  # the text, three ladder steps, the next prompt
        "ScheduledWork": 4,
    }
    assert len(_sent(await _outbox(uow_factory))) == 2  # the warm-up's text and the race's one


# --- KI-97: the privacy guard refuses the grouped text -------------------------------------------


async def test_a_group_the_privacy_guard_refuses_is_not_made_and_the_service_goes_alone(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    seed_service: Seed,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_render = send_prompts.render

    def render(message_id: MessageId, channel: Any, **fields: Any) -> Any:
        if message_id is MessageId.C9:
            raise ValidationFailed("text", "a patient-data shape is not allowed in the output")
        return real_render(message_id, channel, **fields)

    monkeypatch.setattr(send_prompts, "render", render)
    await _seed_phone(uow_factory, seed_service, WEST, EAST)
    use_case, _ = _group_rig(uow_factory, neo4j_driver)

    result = await use_case.execute(_group_command("ucr-west"))

    assert result.sent is True
    assert result.grouped_service_ids == ()
    rows = await _communications(neo4j_driver)
    assert [(row["service"], row["messageId"]) for row in rows] == [("ucr-west", "C1")]


# --- Q3: the prompt due at the closing time is sent ----------------------------------------------


async def test_the_prompt_due_at_the_closing_time_is_sent_and_not_skipped_as_out_of_hours(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    due = _london(20, 0)
    use_case, _ = _rig(uow_factory, neo4j_driver, now=due + timedelta(seconds=5))

    result = await use_case.execute(_command(due))

    assert result.sent is True
    assert result.skipped_reason is None
    [message] = _sent(await _outbox(uow_factory))
    assert message.payload["message_id"] == "C1"


async def test_a_prompt_due_after_the_closing_time_is_still_skipped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    await _seed_one_reporter(uow_factory, seed_service)
    await _seed_report(uow_factory)
    due = _london(20, 0) + timedelta(minutes=1)
    use_case, _ = _rig(uow_factory, neo4j_driver, now=due + timedelta(seconds=5))

    result = await use_case.execute(_command(due))

    assert result.sent is False
    assert result.skipped_reason == send_prompts.SKIP_OUT_OF_HOURS


# --- Q4: a daily service's figure may be a day old ------------------------------------------------


async def test_two_daily_services_with_figures_a_day_old_are_grouped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    west = dataclasses.replace(WEST, cadence=Cadence.ONCE_A_DAY)
    east = dataclasses.replace(EAST, cadence=Cadence.ONCE_A_DAY)
    await _seed_phone(uow_factory, seed_service, west, east, reports=False)
    due = _london(8, 0)  # a daily service is due at its opening time
    for profile in (west, east):
        await _seed_group_report(uow_factory, profile.id, effective_at=due - timedelta(hours=20))
    use_case, _ = _group_rig(uow_factory, neo4j_driver, now=due + timedelta(seconds=30))

    result = await use_case.execute(_group_command("ucr-west", due))

    assert result.grouped_service_ids == ("ucr-east", "ucr-west")
    assert [row["messageId"] for row in await _communications(neo4j_driver)] == ["C9", "C9"]


async def test_a_daily_service_with_a_figure_past_its_day_is_not_grouped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, seed_service: Seed
) -> None:
    west = dataclasses.replace(WEST, cadence=Cadence.ONCE_A_DAY)
    east = dataclasses.replace(EAST, cadence=Cadence.ONCE_A_DAY)
    await _seed_phone(uow_factory, seed_service, west, east, reports=False)
    due = _london(8, 0)
    await _seed_group_report(uow_factory, "ucr-west", effective_at=due - timedelta(hours=20))
    await _seed_group_report(uow_factory, "ucr-east", effective_at=due - timedelta(hours=27))
    use_case, _ = _group_rig(uow_factory, neo4j_driver, now=due + timedelta(seconds=30))

    result = await use_case.execute(_group_command("ucr-west", due))

    assert result.grouped_service_ids == ()
