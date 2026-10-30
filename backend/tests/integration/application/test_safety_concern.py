"""Integration tests for the safety concern and the problem report (U41), against the real Neo4j.

A concern is stored as a Task with its SC- reference; its text is only in the protected store,
and no
other node, property, audit entry or outbox message holds any part of it. The safety officer is told
by a K3 message that names the reference and nothing else. The counter that numbers the concerns is
per tenant, so each tenant's first concern is SC-0001. Sample values only.
"""

import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.outbound.graph_store.idempotency_store import DriverIdempotencyStore
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.safety_concern import (
    ReportProblem,
    ReportProblemCommand,
    ReportSafetyConcern,
    ReportSafetyConcernCommand,
    ReportSafetyConcernResult,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.safety_report import ProblemCategory, SafetyConcernCategory
from tests.support.booking_rig import ADVISOR, at, sealer, seed_world
from tests.support.neo4j import count_nodes, node_props, wipe
from tests.support.tenant_seed import contracted_container

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def two_tenant_driver() -> AsyncIterator[AsyncDriver]:
    """The contracted schema (superseded global keys dropped, DEC-159): the two-tenant tests run on
    it, not on the root driver, which still holds the global Concept and Communication keys."""
    async with contracted_container() as driver:
        yield driver


@pytest_asyncio.fixture(loop_scope="session")
async def neo4j_driver(two_tenant_driver: AsyncDriver) -> AsyncDriver:
    await wipe(two_tenant_driver)
    return two_tenant_driver


CONCERN_TEXT = "The board showed accepting for the day, but the service had closed at noon."
NOW = at(14, 20)


def concern_use_case(uow_factory: UnitOfWorkFactory, driver: AsyncDriver) -> ReportSafetyConcern:
    return ReportSafetyConcern(
        uow_factory,
        DriverIdempotencyStore(driver),
        SequentialIds("sc"),
        FixedClock(NOW),
        sealer(),
    )


def concern(key: str, text: str = CONCERN_TEXT) -> ReportSafetyConcernCommand:
    return ReportSafetyConcernCommand(
        idempotency_key=key,
        actor=ADVISOR,
        category=SafetyConcernCategory.WRONG_STATUS_ON_BOARD,
        reference=None,
        text=text,
    )


async def mentions_outside_protected_text(driver: AsyncDriver, probe: str) -> int:
    """How many properties of nodes that are not protected text contain the probe."""
    query = (
        "MATCH (n) WHERE NOT n:ProtectedText UNWIND keys(n) AS k "
        "WITH n[k] AS value WHERE valueType(value) STARTS WITH 'STRING' "
        "AND value CONTAINS $probe "
        "RETURN count(*) AS total"
    )
    async with driver.session() as session:
        result = await session.run(query, {"probe": probe})
        record = await result.single()
    assert record is not None
    return int(record["total"])


async def officer_notice_text(uow_factory: UnitOfWorkFactory, tenant: str) -> str:
    """The K3 notice to the safety officer, unsealed with the message's own id and the tenant."""
    async with uow_factory() as uow:
        messages = await uow.outbox.pending(500)
    k3 = [m for m in messages if m.event_type == "SendMessage" and m.payload["message_id"] == "K3"]
    assert len(k3) == 1
    body = json.loads(
        sealer().unseal(
            k3[0].payload["sealed_content"],
            message_id=k3[0].id,
            tenant_id=tenant,
            recipient_role_id=k3[0].payload["recipient_role_id"],
        )
    )
    return f"{body['subject']}\n{body['text']}"


async def test_a_concern_is_sc0001_and_its_text_is_only_in_the_protected_store(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    result = await concern_use_case(uow_factory, neo4j_driver).execute(concern("sc-1"))
    assert isinstance(result, ReportSafetyConcernResult)
    assert result.reference == "SC-0001"
    task = await node_props(neo4j_driver, "Task", reference="SC-0001")
    assert task["code"] == "safety-concern"
    assert task["ownerRoleId"] == "clinical-safety-officer"
    async with uow_factory() as uow:
        assert await uow.protected_text.get(task["textHandle"]) == CONCERN_TEXT
    probe = CONCERN_TEXT[:30]
    assert await mentions_outside_protected_text(neo4j_driver, probe) == 0


async def test_a_text_of_281_characters_or_no_text_is_refused_and_nothing_is_written(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    before = await count_nodes(neo4j_driver, "Task")
    for text in ("x" * 281, ""):
        with pytest.raises(ValidationFailed):
            await concern_use_case(uow_factory, neo4j_driver).execute(
                concern(f"sc-2-{len(text)}", text=text)
            )
    assert await count_nodes(neo4j_driver, "Task") == before


async def test_the_officer_is_told_by_a_k3_that_names_the_reference_only(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, tenant_id: str, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    await concern_use_case(uow_factory, neo4j_driver).execute(concern("sc-3"))
    notice = await officer_notice_text(uow_factory, tenant_id)
    assert "SC-0001" in notice
    assert CONCERN_TEXT[:30] not in notice


async def test_a_problem_report_with_the_session_shared_reads_back_with_its_flag(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    result = await ReportProblem(
        uow_factory, DriverIdempotencyStore(neo4j_driver), SequentialIds("pr"), FixedClock(NOW)
    ).execute(
        ReportProblemCommand(
            idempotency_key="pr-1",
            actor=ADVISOR,
            category=ProblemCategory.SCREEN_SLOW,
            text="The board takes a while to load.",
            session_shared=True,
        )
    )
    task = await node_props(neo4j_driver, "Task", id=result.report_id)
    assert task["code"] == "problem-report"
    assert task["sessionShared"] is True


async def test_a_second_concern_is_sc0002_in_its_own_unit_of_work(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> None:
    await seed_world(uow_factory, neo4j_driver)
    use_case = concern_use_case(uow_factory, neo4j_driver)
    first = await use_case.execute(concern("sc-5a"))
    second = await use_case.execute(concern("sc-5b"))
    assert (first.reference, second.reference) == ("SC-0001", "SC-0002")


async def test_each_tenant_numbers_its_own_concerns_from_sc0001(
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tenant_id: str,
    other_tenant_id: str,
    clean_graph: None,
) -> None:
    await seed_world(uow_factory_a, neo4j_driver)
    first_a = await concern_use_case(uow_factory_a, neo4j_driver).execute(concern("sc-6a"))
    first_b = await concern_use_case(uow_factory_b, neo4j_driver).execute(concern("sc-6b"))
    assert (first_a.reference, first_b.reference) == ("SC-0001", "SC-0001")
