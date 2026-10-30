"""The browser's ui.* events counted into daily aggregates, and the insight tabs read back, against
real Neo4j (W9F). The run tenant is bound by the conftest; the second tenant is the one that must
see none of it. Synthetic values only: a session id is hex, an element id is an upper-case code.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.actor import Actor
from diucs.application.ports.outbound.outbox import PENDING, OutboxMessage
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.browser_insight import ReadInsightTab, RecordBrowserEvents
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from diucs.domain.rules.browser_insight import MARKER_SECRET
from tests.support.neo4j import count_nodes, node_props, read_tx
from tests.support.tenancy import RunIdentity
from tests.support.uow import tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
TODAY = NOW.date()
SESSION = "a1b2c3d4e5f60718"
SECRETS = FixedSecretStore({MARKER_SECRET: b"test-only-telemetry-marker-secret-0123"})


def actor(role: Role, tenant: str) -> Actor:
    return Actor(
        role=role,
        practitioner_id="prac-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def ui(name: str, session: str = SESSION, **attributes: Any) -> dict[str, Any]:
    common = {
        "session.id": session,
        "user.role": "advisor",
        "release": "1.4.2",
        "device.type": "desktop",
        "app.mode": "browser",
    }
    return {"name": name, "attributes": {**common, **attributes}}


def click(element: str = "ADV-X-BTN", session: str = SESSION) -> dict[str, Any]:
    return ui("ui.click", session, **{"element.id": element, "dwell_ms": 10})


def session_id(index: int) -> str:
    return f"{index:016x}"


def recorder(
    uow_factory: UnitOfWorkFactory, clock: FixedClock | None = None
) -> RecordBrowserEvents:
    return RecordBrowserEvents(uow_factory, clock or FixedClock(NOW), SECRETS)


async def usage(
    driver: AsyncDriver, element: str = "ADV-X-BTN", scope: str | None = None
) -> dict[str, Any]:
    return await node_props(
        driver, "ElementUsageDaily", scope=scope, elementId=element, date=TODAY.isoformat()
    )


# ---- counting ------------------------------------------------------------------------------------


async def test_a_session_is_counted_once_however_many_events_and_batches(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    record = recorder(uow_factory)
    caller = actor(Role.ADVISOR, run_identity.tenant_id)

    await record.execute(caller, [click(), click(), click()])
    await record.execute(caller, [click()])

    props = await usage(neo4j_driver)
    assert (props["interactions"], props["sessions"]) == (4, 1)
    assert (props["role"], props["device"]) == ("advisor", "desktop")

    await record.execute(caller, [click(session=session_id(2))])

    props = await usage(neo4j_driver)
    assert (props["interactions"], props["sessions"]) == (5, 2)


async def test_the_result_says_how_many_events_were_counted_and_how_many_were_dropped(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    caller = actor(Role.ADVISOR, run_identity.tenant_id)

    result = await recorder(uow_factory).execute(
        caller,
        [
            click(),
            ui("ui.click", **{"element.id": "Sample Patient"}),
            ui("ui.unknown"),
            {"name": "ui.click"},
        ],
    )

    assert (result.accepted, result.dropped) == (1, 3)
    assert (await usage(neo4j_driver))["interactions"] == 1


async def test_the_role_counted_is_the_callers_not_the_one_the_browser_claims(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    event = ui("ui.click", **{"element.id": "ADV-X-BTN", "user.role": "owner"})

    await recorder(uow_factory).execute(actor(Role.LEAD, run_identity.tenant_id), [event])

    assert (await usage(neo4j_driver))["role"] == "lead"


async def test_a_batch_over_the_ceiling_is_refused_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    caller = actor(Role.ADVISOR, run_identity.tenant_id)

    with pytest.raises(ValidationFailed):
        await recorder(uow_factory).execute(caller, [click()] * 51)

    assert await count_nodes(neo4j_driver, "ElementUsageDaily") == 0
    assert await count_nodes(neo4j_driver, "TallySeen") == 0


async def test_without_the_marker_secret_nothing_is_counted(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    record = RecordBrowserEvents(uow_factory, FixedClock(NOW), FixedSecretStore({}))

    with pytest.raises(NotFound):
        await record.execute(actor(Role.ADVISOR, run_identity.tenant_id), [click()])

    assert await count_nodes(neo4j_driver, "ElementUsageDaily") == 0


async def test_the_graph_holds_no_session_id_only_a_keyed_marker(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    await recorder(uow_factory).execute(
        actor(Role.ADVISOR, run_identity.tenant_id),
        [
            click(),
            ui("ui.friction", kind="rage", **{"element.id": "ADV-X-BTN", "count": 3}),
            ui("ui.page_view", **{"page.route": "/setup"}),
            ui("ui.web_vital", metric="lcp", reading=2400, **{"page.route": "/setup"}),
        ],
    )

    async def values(tx: AsyncManagedTransaction) -> list[Any]:
        rows = await (
            await tx.run(
                "MATCH (n) WHERE n.tenantId = $tenant UNWIND keys(n) AS key RETURN n[key] AS value"
            )
        ).data()
        return [row["value"] for row in rows]

    found = await read_tx(neo4j_driver, values)
    assert found
    assert not any(SESSION in str(value) for value in found)
    markers = await node_props_list(neo4j_driver, "TallySeen")
    assert markers
    assert all(len(marker["key"]) == 32 for marker in markers)


async def node_props_list(driver: AsyncDriver, label: str) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        rows = await (
            await tx.run(
                f"MATCH (n:`{label}`) WHERE n.tenantId = $tenant RETURN properties(n) AS props"
            )
        ).data()
        return [row["props"] for row in rows]

    return await read_tx(driver, work)


async def test_markers_older_than_yesterday_are_removed_and_the_counters_stay(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    clock = FixedClock(NOW)
    record = recorder(uow_factory, clock)
    caller = actor(Role.ADVISOR, run_identity.tenant_id)
    await record.execute(caller, [click()])
    first = await count_nodes(neo4j_driver, "TallySeen")

    clock.advance(timedelta(days=1))
    await record.execute(caller, [click()])
    assert await count_nodes(neo4j_driver, "TallySeen") == 2 * first

    clock.advance(timedelta(days=1))
    await record.execute(caller, [click()])

    dates = {marker["date"] for marker in await node_props_list(neo4j_driver, "TallySeen")}
    assert dates == {
        (TODAY + timedelta(days=1)).isoformat(),
        (TODAY + timedelta(days=2)).isoformat(),
    }
    assert await count_nodes(neo4j_driver, "ElementUsageDaily") == 3


async def test_a_session_on_a_new_day_is_counted_again(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    clock = FixedClock(NOW)
    record = recorder(uow_factory, clock)
    caller = actor(Role.ADVISOR, run_identity.tenant_id)
    await record.execute(caller, [click()])
    clock.advance(timedelta(days=1))
    await record.execute(caller, [click()])

    tomorrow = await node_props(
        neo4j_driver,
        "ElementUsageDaily",
        elementId="ADV-X-BTN",
        date=(TODAY + timedelta(days=1)).isoformat(),
    )
    assert (tomorrow["interactions"], tomorrow["sessions"]) == (1, 1)


async def test_friction_route_views_errors_and_releases_are_counted(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    caller = actor(Role.ADVISOR, run_identity.tenant_id)
    await recorder(uow_factory).execute(
        caller,
        [
            click(),
            ui("ui.friction", kind="rage", **{"element.id": "ADV-X-BTN", "count": 3}),
            ui(
                "ui.friction",
                kind="u-turn",
                **{"element.id": "PAGE", "page.route": "/advisor/board"},
            ),
            ui("ui.page_view", **{"page.route": "/advisor/board"}),
            ui("ui.error_shown", **{"page.route": "/advisor/board", "error.code": "NETWORK"}),
        ],
    )

    rage = await node_props(neo4j_driver, "FrictionDaily", elementId="ADV-X-BTN", kind="rage")
    assert (rage["events"], rage["sessions"], rage["route"]) == (1, 1, "")
    turn = await node_props(neo4j_driver, "FrictionDaily", elementId="PAGE", kind="u-turn")
    assert (turn["events"], turn["route"]) == (1, "/advisor/board")
    route = await node_props(neo4j_driver, "RouteDaily", route="/advisor/board")
    assert (route["sessions"], route["errors"], route["role"]) == (1, 1, "advisor")
    release = await node_props(neo4j_driver, "ReleaseDaily", release="1.4.2")
    assert (
        release["sessions"],
        release["interactions"],
        release["friction"],
        release["errors"],
        release["views"],
    ) == (1, 1, 2, 1, 1)


async def test_a_session_moves_down_a_funnel_once_per_step(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    record = recorder(uow_factory)
    caller = actor(Role.REPORTER, run_identity.tenant_id)

    async def entered(step: str) -> int | None:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            rows = await (
                await tx.run(
                    "MATCH (f:FunnelDaily {tenantId: $tenant, funnel: 'reporter-set-up', "
                    "step: $step}) "
                    "RETURN f.entered AS entered",
                    step=step,
                )
            ).data()
            return rows

        rows = await read_tx(neo4j_driver, work)
        return None if not rows else int(rows[0]["entered"])

    await record.execute(
        caller,
        [
            ui("ui.page_view", **{"page.route": "/setup"}),
            ui("ui.page_view", **{"page.route": "/setup/home-screen"}),
        ],
    )
    assert [
        await entered(s) for s in ("Set-up opened", "Home-screen guide viewed", "PIN screen viewed")
    ] == [
        1,
        1,
        None,
    ]

    await record.execute(caller, [ui("ui.page_view", **{"page.route": "/setup"})])
    assert await entered("Set-up opened") == 1

    await record.execute(caller, [ui("ui.page_view", **{"page.route": "/setup/pin"})])
    assert [
        await entered(s)
        for s in (
            "Set-up opened",
            "Home-screen guide viewed",
            "Notification screen viewed",
            "PIN screen viewed",
        )
    ] == [1, 1, 1, 1]


async def test_web_vitals_add_to_the_histogram_of_the_route_device_and_release(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    record = recorder(uow_factory)
    caller = actor(Role.ADVISOR, run_identity.tenant_id)
    vital = ui("ui.web_vital", metric="lcp", reading=2400, **{"page.route": "/advisor/board"})

    await record.execute(caller, [vital, vital])
    await record.execute(caller, [vital])
    await record.execute(
        caller,
        [
            ui(
                "ui.web_vital",
                session_id(3),
                metric="lcp",
                reading=900,
                **{"page.route": "/advisor/board"},
            )
        ],
    )

    props = await node_props(neo4j_driver, "MeasureDaily", measure="lcp", route="/advisor/board")
    assert (props["samples"], props["sessions"]) == (4, 2)
    assert sum(props["buckets"]) == 4
    assert len(props["buckets"]) == 12
    assert props["buckets"][4] == 3  # 2400 ms: the bucket up to 2500
    assert props["buckets"][1] == 1  # 900 ms: the bucket up to 1000


# ---- two tenants ---------------------------------------------------------------------------------


async def test_the_other_tenant_counts_the_same_session_and_element_separately(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    run_identity: RunIdentity,
    uow_clock: FixedClock,
) -> None:
    other_factory = tenant_uow_factory(neo4j_driver, run_identity.other_tenant_id, uow_clock)
    mine = actor(Role.ADVISOR, run_identity.tenant_id)
    theirs = actor(Role.ADVISOR, run_identity.other_tenant_id)

    await recorder(uow_factory).execute(mine, [click(), click()])
    with bind_tenant(run_identity.other_tenant_id):
        await recorder(other_factory).execute(theirs, [click()])

    assert (await usage(neo4j_driver))["interactions"] == 2
    other = await usage(neo4j_driver, scope=run_identity.other_tenant_id)
    assert (other["interactions"], other["sessions"]) == (1, 1)
    assert await count_nodes(neo4j_driver, "TallySeen", tenant=run_identity.other_tenant_id) >= 1


async def test_each_tenant_reads_only_its_own_numbers(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    run_identity: RunIdentity,
    uow_clock: FixedClock,
) -> None:
    other_factory = tenant_uow_factory(neo4j_driver, run_identity.other_tenant_id, uow_clock)
    mine = actor(Role.SUPPORT, run_identity.tenant_id)
    theirs = actor(Role.SUPPORT, run_identity.other_tenant_id)
    advisors = [session_id(index) for index in range(1, 13)]
    await recorder(uow_factory).execute(
        actor(Role.ADVISOR, run_identity.tenant_id),
        [ui("ui.friction", s, kind="rage", **{"element.id": "ADV-ONLY-MINE-BTN"}) for s in advisors]
        + [click("ADV-ONLY-MINE-BTN", s) for s in advisors]
        + [ui("ui.page_view", s, **{"page.route": "/mine-only"}) for s in advisors],
    )

    table = await ReadInsightTab(uow_factory, FixedClock(NOW)).friction(mine, "7d", None)
    paths = await ReadInsightTab(uow_factory, FixedClock(NOW)).paths(mine, "7d", None)
    their_table = await ReadInsightTab(other_factory, FixedClock(NOW)).friction(theirs, "7d", None)
    their_paths = await ReadInsightTab(other_factory, FixedClock(NOW)).paths(theirs, "7d", None)

    assert [row.element_id for row in table.rows] == ["ADV-ONLY-MINE-BTN"]
    assert [use.route for use in paths.most_common] == ["/mine-only"]
    assert their_table.rows == ()
    assert their_paths.most_common == ()


# ---- the tabs ------------------------------------------------------------------------------------


async def test_a_step_is_shown_from_ten_sessions_and_not_before(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    record = recorder(uow_factory)
    caller = actor(Role.REPORTER, run_identity.tenant_id)
    for index in range(1, 11):
        await record.execute(
            caller, [ui("ui.page_view", session_id(index), **{"page.route": "/setup"})]
        )
    for index in range(1, 10):
        await record.execute(
            caller, [ui("ui.page_view", session_id(index), **{"page.route": "/setup/home-screen"})]
        )

    views = await ReadInsightTab(uow_factory, FixedClock(NOW)).funnels(
        actor(Role.SUPPORT, run_identity.tenant_id), "7d", None
    )

    funnel = next(view for view in views if view.name == "reporter-set-up")
    assert [(s.name, s.count, s.pct, s.suppressed) for s in funnel.steps[:2]] == [
        ("Set-up opened", 10, 100, False),
        ("Home-screen guide viewed", None, None, True),
    ]
    assert [(s.channel, s.pct) for s in funnel.split] == [("browser", 100)]


async def test_a_device_filter_keeps_only_that_devices_rows(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    record = recorder(uow_factory)
    caller = actor(Role.ADVISOR, run_identity.tenant_id)
    for index in range(1, 11):
        sid = session_id(index)
        phone = ui("ui.page_view", sid, **{"page.route": "/on-phone", "device.type": "phone"})
        desk = ui("ui.page_view", sid, **{"page.route": "/on-desk"})
        await record.execute(caller, [phone, desk])

    paths = await ReadInsightTab(uow_factory, FixedClock(NOW)).paths(
        actor(Role.SUPPORT, run_identity.tenant_id), "7d", "phone"
    )

    assert [use.route for use in paths.most_common] == ["/on-phone"]


async def test_the_vitals_and_the_release_comparison_read_back_from_the_histograms(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, run_identity: RunIdentity
) -> None:
    record = recorder(uow_factory)
    caller = actor(Role.ADVISOR, run_identity.tenant_id)
    for release, lcp in (("1.4.2", 2000), ("1.4.3", 3000)):
        for index in range(1, 11):
            sid = session_id(index)
            events = [
                ui("ui.page_view", sid, release=release, **{"page.route": "/advisor/board"}),
                ui(
                    "ui.web_vital",
                    sid,
                    release=release,
                    metric="lcp",
                    reading=lcp,
                    **{"page.route": "/advisor/board"},
                ),
            ]
            await record.execute(caller, events)
    read = ReadInsightTab(uow_factory, FixedClock(NOW))
    support = actor(Role.SUPPORT, run_identity.tenant_id)

    performance = await read.performance(support, "7d", None)
    releases = await read.releases(support, "7d")

    lcp_view = next(v for v in performance.vitals if v.measure == "lcp")
    assert (lcp_view.device, lcp_view.p75, lcp_view.suppressed) == ("desktop", 3000.0, False)
    assert [(s.name, s.p95_ms) for s in performance.slowest_routes] == [("/advisor/board", 3000.0)]
    assert releases.compare is not None
    assert (releases.compare.old, releases.compare.new) == ("1.4.2", "1.4.3")
    change = next(m for m in releases.compare.measures if m.measure.startswith("Largest"))
    assert (change.old, change.new, change.review) == (2000.0, 3000.0, True)


async def test_the_pipeline_is_the_callers_own_outbox_by_topic(
    uow_factory: UnitOfWorkFactory,
    neo4j_driver: AsyncDriver,
    run_identity: RunIdentity,
    uow_clock: FixedClock,
) -> None:
    other_factory = tenant_uow_factory(neo4j_driver, run_identity.other_tenant_id, uow_clock)

    async def add(
        factory: UnitOfWorkFactory, ident: str, topic: str, status: str, age_s: int
    ) -> None:
        async with factory() as uow:
            await uow.outbox.add(
                OutboxMessage(
                    id=ident,
                    topic=topic,
                    event_type="capacity.reported",
                    payload={},
                    created_at=NOW - timedelta(seconds=age_s),
                    status=status,
                )
            )
            await uow.commit()

    await add(uow_factory, "m-1", "messages.outbound", PENDING, 90)
    await add(uow_factory, "m-2", "messages.outbound", PENDING, 30)
    await add(uow_factory, "m-3", "messages.outbound", "dead", 500)
    await add(uow_factory, "m-4", "messages.outbound", "published", 900)
    await add(other_factory, "m-1", "capacity.events", PENDING, 5000)

    mine = await ReadInsightTab(uow_factory, FixedClock(NOW)).releases(
        actor(Role.SUPPORT, run_identity.tenant_id), "7d"
    )
    theirs = await ReadInsightTab(other_factory, FixedClock(NOW)).releases(
        actor(Role.SUPPORT, run_identity.other_tenant_id), "7d"
    )

    assert [(p.name, p.active, p.dead_lettered, p.oldest_seconds) for p in mine.pipeline] == [
        ("messages.outbound", 2, 1, 90)
    ]
    assert [(p.name, p.active, p.oldest_seconds) for p in theirs.pipeline] == [
        ("capacity.events", 1, 5000)
    ]


async def test_only_the_support_role_reads_a_tab(
    uow_factory: UnitOfWorkFactory, run_identity: RunIdentity
) -> None:
    read = ReadInsightTab(uow_factory, FixedClock(NOW))
    for role in (Role.LEAD, Role.ADVISOR, Role.EXEC, Role.OWNER, Role.AUDIT, Role.TENANT_ADMIN):
        with pytest.raises(NotAllowed):
            await read.friction(actor(role, run_identity.tenant_id), "7d", None)


async def test_a_range_or_device_that_is_not_listed_is_refused(
    uow_factory: UnitOfWorkFactory, run_identity: RunIdentity
) -> None:
    read = ReadInsightTab(uow_factory, FixedClock(NOW))
    support = actor(Role.SUPPORT, run_identity.tenant_id)

    with pytest.raises(ValidationFailed):
        await read.friction(support, "1y", None)
    with pytest.raises(ValidationFailed):
        await read.friction(support, "7d", "watch")
