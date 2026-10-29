"""The daily telemetry aggregates, end to end against Neo4j (O08, the acceptance tests of the task).

The day comes from a fixture written for the run tenant (the conftest binds it), so the rows are the
caller's own. The other tenant's rows use names no run-tenant row uses, because `node_props` matches
across tenants. Synthetic values only. Written in the build wave; run in the verification stage (one
Neo4j at a time: flock /tmp/diucs-neo4j-tests.lock).
"""

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.aggregate_repository import Neo4jAggregateRepository
from diucs.adapters.testing.fixture_telemetry import FixtureTelemetryQuery
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.telemetry_aggregates import BuildDailyAggregates, ReadInsights
from diucs.domain.model.telemetry_aggregates import (
    DayAggregates,
    ElementUsageDailyRow,
    FrictionDailyRow,
    FunnelDailyRow,
    QueryStatDailyRow,
    RouteDailyRow,
)
from tests.support.neo4j import count_nodes, node_props
from tests.support.round_trip import assert_round_trip
from tests.support.tenancy import RunIdentity
from tests.support.uow import tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

DAY_TEXT = "2026-10-28"
DAY = date(2026, 10, 28)


def _daily_for(tenant: str, *, funnel_step: str, query_id: str, element: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant,
        "day": DAY_TEXT,
        "funnel": [
            {
                "funnel": "reporter-set-up",
                "step": "Invitation delivered",
                "branch": False,
                "role": "reporter",
                "channel": "text",
                "device": "phone",
                "entered": 40,
                "completed": 36,
                "median_ms": 5200.0,
            },
            {
                "funnel": "reporter-set-up",
                "step": funnel_step,
                "branch": False,
                "role": "reporter",
                "channel": "link",
                "device": "phone",
                "entered": 7,
                "completed": 5,
                "median_ms": 2400.0,
            },
        ],
        "friction": [
            {
                "element_id": element,
                "kind": "rage",
                "role": "advisor",
                "device": "desktop",
                "interactions": 312,
                "events": 41,
                "sessions": 14,
            },
            {
                "element_id": "ADV-REF-INPUT",
                "kind": "validation-loop",
                "role": "advisor",
                "device": "desktop",
                "interactions": 100,
                "events": 3,
                "sessions": 12,
            },
        ],
        "usage": [
            {
                "element_id": element,
                "role": "advisor",
                "device": "desktop",
                "interactions": 312,
                "sessions": 14,
            },
            {
                "element_id": "ADV-REF-INPUT",
                "role": "advisor",
                "device": "desktop",
                "interactions": 100,
                "sessions": 12,
            },
        ],
        "routes": [
            {
                "route": "/board",
                "role": "wall",
                "device": "desktop",
                "p50": 310.0,
                "p75": 480.0,
                "p95": 820.0,
                "lcp75": 1900.0,
                "inp75": 140.0,
                "cls75": 0.02,
                "errors": 0,
                "sessions": 22,
            }
        ],
        "queries": [{"query_id": query_id, "calls": 120, "p50": 38.0, "p95": 91.0, "errors": 1}],
    }


def _fixture(tmp_path: Path, run: RunIdentity) -> FixtureTelemetryQuery:
    payload = {
        "sessions": [],
        "timeline": [],
        "spans": [],
        "daily": [
            _daily_for(
                run.tenant_id,
                funnel_step="Welcome started",
                query_id="Q-BOARD",
                element="ADV-OPT-REQUEST-BTN",
            ),
            _daily_for(
                run.other_tenant_id,
                funnel_step="Other tenant step",
                query_id="Q-OTHER",
                element="B-ONLY-BTN",
            ),
        ],
    }
    path = tmp_path / "daily.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return FixtureTelemetryQuery(path, attributes=lambda attrs: dict(attrs))


async def test_a_fixture_day_writes_the_funnel_steps_with_entered_and_completed(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tmp_path: Path,
    run_identity: RunIdentity,
) -> None:
    with bind_tenant(run_identity.tenant_id):
        await BuildDailyAggregates(uow_factory, _fixture(tmp_path, run_identity)).execute(DAY)

    props = await node_props(neo4j_driver, "FunnelDaily", step="Welcome started", date=DAY_TEXT)
    assert props["entered"] == 7
    assert props["completed"] == 5


async def test_running_the_same_day_twice_leaves_the_same_node_count(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tmp_path: Path,
    run_identity: RunIdentity,
) -> None:
    build = BuildDailyAggregates(uow_factory, _fixture(tmp_path, run_identity))
    with bind_tenant(run_identity.tenant_id):
        await build.execute(DAY)
        first = await count_nodes(neo4j_driver, "FunnelDaily")
        await build.execute(DAY)
        second = await count_nodes(neo4j_driver, "FunnelDaily")

    assert second == first


async def test_a_funnel_step_with_seven_sessions_reads_back_suppressed(
    uow_factory: UnitOfWorkFactory, tmp_path: Path, run_identity: RunIdentity
) -> None:
    with bind_tenant(run_identity.tenant_id):
        await BuildDailyAggregates(uow_factory, _fixture(tmp_path, run_identity)).execute(DAY)
        figures = await ReadInsights(uow_factory).funnel("reporter-set-up", DAY, DAY)

    welcome = next(figure for figure in figures if figure.step == "Welcome started")
    assert welcome.suppressed is True
    assert welcome.entered is None


async def test_41_in_312_is_flagged_at_13_percent_and_3_percent_is_not(
    uow_factory: UnitOfWorkFactory, tmp_path: Path, run_identity: RunIdentity
) -> None:
    with bind_tenant(run_identity.tenant_id):
        await BuildDailyAggregates(uow_factory, _fixture(tmp_path, run_identity)).execute(DAY)
        figures = await ReadInsights(uow_factory).friction(DAY)

    by_element = {figure.element_id: figure for figure in figures}
    request = by_element["ADV-OPT-REQUEST-BTN"]
    assert request.rate == pytest.approx(41 / 312)
    assert request.for_review is True
    assert by_element["ADV-REF-INPUT"].for_review is False


async def test_a_query_statistic_holds_its_p95_and_no_cypher_text(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tmp_path: Path,
    run_identity: RunIdentity,
) -> None:
    with bind_tenant(run_identity.tenant_id):
        await BuildDailyAggregates(uow_factory, _fixture(tmp_path, run_identity)).execute(DAY)

    props = await node_props(neo4j_driver, "QueryStatDaily", queryId="Q-BOARD")
    assert props["p95"] == 91.0
    assert not {key for key in props if key in {"cypher", "statement", "text", "parameters"}}


async def test_every_aggregate_node_type_round_trips_through_the_repository(
    neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    aggregates = DayAggregates(
        funnel=(
            FunnelDailyRow(
                DAY, "reporter-set-up", "Link opened", "reporter", "link", "phone", 40, 30, 9100.0
            ),
        ),
        friction=(
            FrictionDailyRow(DAY, "ADV-REF-INPUT", "rage", "advisor", "desktop", 100, 3, 12),
        ),
        usage=(ElementUsageDailyRow(DAY, "ADV-REF-INPUT", "advisor", "desktop", 100, 12),),
        routes=(
            RouteDailyRow(
                DAY, "/board", "wall", "desktop", 310.0, 480.0, 820.0, 1900.0, 140.0, 0.02, 0, 22
            ),
        ),
        queries=(QueryStatDailyRow(DAY, "Q-BOARD", 120, 38.0, 91.0, 1),),
    )

    async def save(tx: AsyncManagedTransaction) -> None:
        await Neo4jAggregateRepository(tx).replace_day(DAY, aggregates)

    async def load(tx: AsyncManagedTransaction) -> tuple[Any, ...]:
        repo = Neo4jAggregateRepository(tx)
        return (
            await repo.funnel_rows("reporter-set-up", DAY, DAY),
            await repo.friction_rows(DAY, DAY),
            await repo.usage_rows(DAY, DAY),
            await repo.route_rows(DAY, DAY),
            await repo.query_rows(DAY, DAY),
        )

    with bind_tenant(run_identity.tenant_id):
        await assert_round_trip(
            neo4j_driver,
            save,
            load,
            (
                list(aggregates.funnel),
                list(aggregates.friction),
                list(aggregates.usage),
                list(aggregates.routes),
                list(aggregates.queries),
            ),
        )


async def test_the_other_tenant_reads_none_of_this_day(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    tmp_path: Path,
    run_identity: RunIdentity,
) -> None:
    with bind_tenant(run_identity.tenant_id):
        await BuildDailyAggregates(uow_factory, _fixture(tmp_path, run_identity)).execute(DAY)
    other = tenant_uow_factory(neo4j_driver, run_identity.other_tenant_id)

    figures = await ReadInsights(other).funnel("reporter-set-up", DAY, DAY)
    friction = await ReadInsights(other).friction(DAY)

    assert all(figure.step != "Welcome started" for figure in figures)
    assert "ADV-OPT-REQUEST-BTN" not in {figure.element_id for figure in friction}
