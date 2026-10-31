"""Neo4j counters for the browser insight, and the live pipeline read (W9F).

The browser's ui.* events are counted into daily nodes, one add per label, never stored as events.
Every node carries `tenantId`, and every statement writes `tenantId: $tenant` on each node it
matches, merges or creates (DEC-130, DEC-132). `date` is the ISO text YYYY-MM-DD.

Counters that exist already (O08): `ElementUsageDaily`, `FrictionDaily`, `RouteDaily` and
`FunnelDaily`. New here:

(:MeasureDaily {tenantId, date, measure, route, device, release, sessions, samples, buckets})
    a web vital's histogram of the day: `buckets` is a fixed list of counts (see BUCKET_COUNT in
    domain/rules/browser_insight), so a percentile is read from it and no value is kept.
(:ReleaseDaily {tenantId, date, release, sessions, interactions, friction, errors, views})
    what one release did on the day, for the release comparison.
(:TallySeen {tenantId, key, date, hits | reached})
    a pseudonymous marker: the keyed hash of a session, a group and a day (`marker_key`). It lets a
    counter tell a session it has seen from a new one; it holds no session id and is removed two
    days on. `hits` counts the events of a plain group; `reached` is the furthest funnel step.

Each add is a MERGE on the composite key (migration 0195), then a lock on the node (a self-SET,
lesson L73), then an increment: two batches that meet wait for each other, so no count is lost.
The rows of one call have distinct keys, and the caller sorts them, so two calls that overlap take
their locks in one order.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, Final

from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    TenantSeed,
)
from diucs.domain.model.insight import (
    FrictionAdd,
    FunnelAdd,
    FunnelMark,
    MeasureAdd,
    MeasureRow,
    PipelineRow,
    ReleaseAdd,
    ReleaseRow,
    RouteAdd,
    UsageAdd,
)

_DAY: Final = "2026-10-29"
_OLD: Final = "2026-10-20"
_AT: Final = datetime(2026, 10, 29, 8, 0, tzinfo=UTC)
_WINDOW: Final = {"start": _DAY, "end": _DAY}
_ZEROS: Final = [0] * 12


def _buckets(**at: int) -> list[int]:
    """A bucket list with counts at some indexes: `_buckets(i4=6)`."""
    counts = list(_ZEROS)
    for name, value in at.items():
        counts[int(name[1:])] = value
    return counts


def _seed(*nodes: SeedNode) -> TenantSeed:
    return TenantSeed(nodes=nodes)


def _scenario(
    description: str,
    seed: TenantSeed,
    params: dict[str, Any],
    expect: Expect,
    *,
    lookup: tuple[str, ...] = (),
    new: tuple[str, ...] = (),
) -> Scenario:
    return Scenario(description, seed=seed, params=params, lookup=lookup, new=new, expect=expect)


# ---- seeds: a node both tenants hold under one key (so a leak finds it), and one only by text ----

_SEEN_SEED: Final = _seed(
    SeedNode("shared", ("TallySeen",), {"key": "k-shared", "date": _DAY, "hits": 1}),
    SeedNode("own", ("TallySeen",), {"key": Marked("k-own"), "date": _DAY, "hits": 1}),
)
_FUNNEL_MARK_SEED: Final = _seed(
    SeedNode("shared", ("TallySeen",), {"key": "f-shared", "date": _DAY, "reached": 1}),
    SeedNode("own", ("TallySeen",), {"key": Marked("f-own"), "date": _DAY, "reached": 1}),
)
_PURGE_SEED: Final = _seed(
    SeedNode("old", ("TallySeen",), {"key": Marked("old"), "date": _OLD, "hits": 1}),
    SeedNode("recent", ("TallySeen",), {"key": Marked("recent"), "date": _DAY, "hits": 1}),
)
_USAGE_SEED: Final = _seed(
    SeedNode(
        "shared",
        ("ElementUsageDaily",),
        {
            "date": _DAY,
            "elementId": "ADV-X-BTN",
            "role": "advisor",
            "device": "desktop",
            "interactions": 10,
            "sessions": 3,
        },
    ),
    SeedNode(
        "own",
        ("ElementUsageDaily",),
        {
            "date": _DAY,
            "elementId": Marked("el"),
            "role": "advisor",
            "device": "desktop",
            "interactions": 7,
            "sessions": 2,
        },
    ),
)
_FRICTION_SEED: Final = _seed(
    SeedNode(
        "shared",
        ("FrictionDaily",),
        {
            "date": _DAY,
            "elementId": "ADV-X-BTN",
            "kind": "rage",
            "role": "advisor",
            "device": "desktop",
            "route": "",
            "interactions": 0,
            "events": 4,
            "sessions": 2,
        },
    ),
    SeedNode(
        "own",
        ("FrictionDaily",),
        {
            "date": _DAY,
            "elementId": Marked("el"),
            "kind": "rage",
            "role": "advisor",
            "device": "desktop",
            "route": "",
            "interactions": 0,
            "events": 9,
            "sessions": 5,
        },
    ),
)
_ROUTE_SEED: Final = _seed(
    SeedNode(
        "shared",
        ("RouteDaily",),
        {
            "date": _DAY,
            "route": "/advisor/board",
            "role": "advisor",
            "device": "desktop",
            "errors": 1,
            "sessions": 5,
        },
    ),
    SeedNode(
        "own",
        ("RouteDaily",),
        {
            "date": _DAY,
            "route": Marked("route"),
            "role": "advisor",
            "device": "desktop",
            "errors": 0,
            "sessions": 8,
        },
    ),
)
_FUNNEL_SEED: Final = _seed(
    SeedNode(
        "shared",
        ("FunnelDaily",),
        {
            "funnel": "reporter-set-up",
            "step": "Set-up opened",
            "date": _DAY,
            "role": "reporter",
            "channel": "browser",
            "device": "phone",
            "branch": False,
            "entered": 8,
            "completed": 0,
        },
    ),
    SeedNode(
        "own",
        ("FunnelDaily",),
        {
            "funnel": "reporter-set-up",
            "step": Marked("step"),
            "date": _DAY,
            "role": "reporter",
            "channel": "browser",
            "device": "phone",
            "branch": False,
            "entered": 6,
            "completed": 0,
        },
    ),
)
_MEASURE_SEED: Final = _seed(
    SeedNode(
        "shared",
        ("MeasureDaily",),
        {
            "date": _DAY,
            "measure": "lcp",
            "route": "/advisor/board",
            "device": "desktop",
            "release": "1.4.2",
            "sessions": 5,
            "samples": 6,
            "buckets": _buckets(i4=6),
        },
    ),
    SeedNode(
        "own",
        ("MeasureDaily",),
        {
            "date": _DAY,
            "measure": "lcp",
            "route": Marked("route"),
            "device": "desktop",
            "release": "1.4.2",
            "sessions": 2,
            "samples": 2,
            "buckets": _buckets(i1=2),
        },
    ),
)
_RELEASE_SEED: Final = _seed(
    SeedNode(
        "shared",
        ("ReleaseDaily",),
        {
            "date": _DAY,
            "release": "1.4.2",
            "sessions": 5,
            "interactions": 100,
            "friction": 4,
            "errors": 2,
            "views": 50,
        },
    ),
    SeedNode(
        "own",
        ("ReleaseDaily",),
        {
            "date": _DAY,
            "release": Marked("1.9.0"),
            "sessions": 3,
            "interactions": 30,
            "friction": 1,
            "errors": 0,
            "views": 12,
        },
    ),
)
_OUTBOX_SEED: Final = _seed(
    SeedNode(
        "pending",
        ("OutboxMessage",),
        {
            "id": "m-1",
            "topic": "messages.outbound",
            "eventType": "capacity.reported",
            "status": "pending",
            "attempts": 0,
            "createdAt": _AT,
        },
    ),
    SeedNode(
        "dead",
        ("OutboxMessage",),
        {
            "id": "m-2",
            "topic": "messages.outbound",
            "eventType": "capacity.reported",
            "status": "dead",
            "attempts": 10,
            "createdAt": _AT,
        },
    ),
    SeedNode(
        "published",
        ("OutboxMessage",),
        {
            "id": "m-3",
            "topic": "messages.outbound",
            "eventType": "capacity.reported",
            "status": "published",
            "attempts": 1,
            "createdAt": _AT,
        },
    ),
    SeedNode(
        "own",
        ("OutboxMessage",),
        {
            "id": "m-4",
            "topic": Marked("topic"),
            "eventType": "capacity.reported",
            "status": "pending",
            "attempts": 0,
            "createdAt": _AT,
        },
    ),
)

_ROW_DAY: Final = {"date": _DAY, "role": "advisor", "device": "desktop"}

_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-INSIGHT-SEEN": _scenario(
        "mark two sessions' groups for the day: the one the tenant has seen is not new, the "
        "other is, and the other tenant's identical marker is not touched",
        _SEEN_SEED,
        {
            "markers": [{"key": "k-shared", "date": _DAY}, {"key": "k-new", "date": _DAY}],
        },
        Expect(
            rows=({"key": "k-shared", "fresh": False}, {"key": "k-new", "fresh": True}),
            nodes={"TallySeen": 1},
            after=(
                NodeSpec(("TallySeen",), {"key": "k-shared", "hits": 2}),
                NodeSpec(("TallySeen",), {"key": "k-new", "hits": 1}),
            ),
        ),
        new=("markers",),
    ),
    "Q-INSIGHT-FUNNEL-ADVANCE": _scenario(
        "move the tenant's session marker to a later funnel step, and leave the other tenant's "
        "marker of the same key where it is",
        _FUNNEL_MARK_SEED,
        {"rows": [{"marker": "f-shared", "date": _DAY, "top": 3}]},
        Expect(
            rows=({"marker": "f-shared", "before": 1, "after": 3},),
            after=(NodeSpec(("TallySeen",), {"key": "f-shared", "reached": 3}),),
        ),
        new=("rows",),
    ),
    "Q-INSIGHT-PURGE-SEEN": _scenario(
        "remove the tenant's markers of days before the cut-off, and no other tenant's",
        _PURGE_SEED,
        {"before": "2026-10-28", "limit": 100},
        Expect(
            rows=({"removed": 1},),
            nodes={"TallySeen": -1},
            gone=(NodeSpec(("TallySeen",), {"key": Marked("old")}),),
        ),
        new=("before", "limit"),
    ),
    "Q-INSIGHT-ADD-USAGE": _scenario(
        "add to the tenant's element-use counter of the day, beside the other tenant's of the "
        "same key",
        _USAGE_SEED,
        {"rows": [{**_ROW_DAY, "elementId": "ADV-X-BTN", "count": 5, "sessions": 1}]},
        Expect(
            rows=({"written": 1},),
            after=(
                NodeSpec(
                    ("ElementUsageDaily",),
                    {"elementId": "ADV-X-BTN", "interactions": 15, "sessions": 4},
                ),
            ),
        ),
        new=("rows",),
    ),
    "Q-INSIGHT-ADD-FRICTION": _scenario(
        "add to the tenant's friction counter of the day, beside the other tenant's of the same "
        "key",
        _FRICTION_SEED,
        {
            "rows": [
                {
                    **_ROW_DAY,
                    "elementId": "ADV-X-BTN",
                    "kind": "rage",
                    "route": "",
                    "count": 3,
                    "sessions": 1,
                }
            ]
        },
        Expect(
            rows=({"written": 1},),
            after=(
                NodeSpec(
                    ("FrictionDaily",), {"elementId": "ADV-X-BTN", "events": 7, "sessions": 3}
                ),
            ),
        ),
        new=("rows",),
    ),
    "Q-INSIGHT-ADD-ROUTE": _scenario(
        "add to the tenant's route counter of the day, beside the other tenant's of the same key",
        _ROUTE_SEED,
        {"rows": [{**_ROW_DAY, "route": "/advisor/board", "errors": 2, "sessions": 1}]},
        Expect(
            rows=({"written": 1},),
            after=(
                NodeSpec(("RouteDaily",), {"route": "/advisor/board", "errors": 3, "sessions": 6}),
            ),
        ),
        new=("rows",),
    ),
    "Q-INSIGHT-ADD-FUNNEL": _scenario(
        "add to the tenant's funnel step of the day, beside the other tenant's of the same key",
        _FUNNEL_SEED,
        {
            "rows": [
                {
                    "date": _DAY,
                    "funnel": "reporter-set-up",
                    "step": "Set-up opened",
                    "role": "reporter",
                    "channel": "browser",
                    "device": "phone",
                    "count": 4,
                }
            ]
        },
        Expect(
            rows=({"written": 1},),
            after=(
                NodeSpec(
                    ("FunnelDaily",),
                    {"funnel": "reporter-set-up", "step": "Set-up opened", "entered": 12},
                ),
            ),
        ),
        new=("rows",),
    ),
    "Q-INSIGHT-ADD-MEASURE": _scenario(
        "add to the tenant's histogram of a web vital for the day, beside the other tenant's of "
        "the same key",
        _MEASURE_SEED,
        {
            "rows": [
                {
                    "date": _DAY,
                    "measure": "lcp",
                    "route": "/advisor/board",
                    "device": "desktop",
                    "release": "1.4.2",
                    "buckets": _buckets(i1=1, i4=2),
                    "samples": 3,
                    "sessions": 1,
                }
            ]
        },
        Expect(
            rows=({"written": 1},),
            after=(
                NodeSpec(
                    ("MeasureDaily",),
                    {
                        "route": "/advisor/board",
                        "samples": 9,
                        "sessions": 6,
                        "buckets": _buckets(i1=1, i4=8),
                    },
                ),
            ),
        ),
        new=("rows",),
    ),
    "Q-INSIGHT-ADD-RELEASE": _scenario(
        "add to the tenant's counters of a release for the day, beside the other tenant's of the "
        "same key",
        _RELEASE_SEED,
        {
            "rows": [
                {
                    "date": _DAY,
                    "release": "1.4.2",
                    "interactions": 20,
                    "friction": 3,
                    "errors": 1,
                    "views": 9,
                    "sessions": 1,
                }
            ]
        },
        Expect(
            rows=({"written": 1},),
            after=(
                NodeSpec(
                    ("ReleaseDaily",),
                    {
                        "release": "1.4.2",
                        "interactions": 120,
                        "friction": 7,
                        "errors": 3,
                        "views": 59,
                        "sessions": 6,
                    },
                ),
            ),
        ),
        new=("rows",),
    ),
    "Q-INSIGHT-READ-MEASURE": _scenario(
        "read the tenant's web-vital histograms in the day range, and no other tenant's",
        _MEASURE_SEED,
        dict(_WINDOW),
        Expect(
            rows=(
                {"day": _DAY, "route": "/advisor/board", "samples": 6, "sessions": 5},
                {"day": _DAY, "route": Marked("route"), "samples": 2, "sessions": 2},
            )
        ),
        lookup=("start", "end"),
    ),
    "Q-INSIGHT-READ-RELEASE": _scenario(
        "read the tenant's release counters in the day range, and no other tenant's",
        _RELEASE_SEED,
        dict(_WINDOW),
        Expect(
            rows=(
                {"day": _DAY, "release": "1.4.2", "sessions": 5, "views": 50},
                {"day": _DAY, "release": Marked("1.9.0"), "sessions": 3, "views": 12},
            )
        ),
        lookup=("start", "end"),
    ),
    "Q-INSIGHT-READ-PIPELINE": _scenario(
        "count the tenant's own pending and dead outbox messages by topic, and no other tenant's",
        _OUTBOX_SEED,
        {},
        Expect(
            rows=(
                {"topic": "messages.outbound", "active": 1, "dead": 1},
                {"topic": Marked("topic"), "active": 1, "dead": 0},
            )
        ),
    ),
}

_CYPHER: Final[dict[str, str]] = {
    "Q-INSIGHT-SEEN": "UNWIND $markers AS marker "
    "MERGE (s:TallySeen {tenantId: $tenant, key: marker.key}) "
    "ON CREATE SET s.date = marker.date, s.hits = 0 "
    "SET s.date = s.date "
    "WITH s, marker SET s.hits = s.hits + 1 "
    "RETURN marker.key AS key, s.hits = 1 AS fresh",
    "Q-INSIGHT-FUNNEL-ADVANCE": "UNWIND $rows AS row "
    "MERGE (s:TallySeen {tenantId: $tenant, key: row.marker}) "
    "ON CREATE SET s.date = row.date, s.reached = -1 "
    "SET s.date = s.date "
    "WITH s, row, s.reached AS before "
    "SET s.reached = CASE WHEN row.top > before THEN row.top ELSE before END "
    "RETURN row.marker AS marker, before AS before, s.reached AS after",
    "Q-INSIGHT-PURGE-SEEN": "MATCH (s:TallySeen {tenantId: $tenant}) WHERE s.date < $before "
    "WITH s LIMIT $limit DETACH DELETE s RETURN count(*) AS removed",
    "Q-INSIGHT-ADD-USAGE": "UNWIND $rows AS row "
    "MERGE (u:ElementUsageDaily {tenantId: $tenant, date: row.date, elementId: row.elementId, "
    "role: row.role, device: row.device}) "
    "ON CREATE SET u.interactions = 0, u.sessions = 0 "
    "SET u.date = u.date WITH u, row "
    "SET u.interactions = u.interactions + row.count, u.sessions = u.sessions + row.sessions "
    "RETURN count(u) AS written",
    "Q-INSIGHT-ADD-FRICTION": "UNWIND $rows AS row "
    "MERGE (f:FrictionDaily {tenantId: $tenant, date: row.date, elementId: row.elementId, "
    "kind: row.kind, role: row.role, device: row.device, route: row.route}) "
    "ON CREATE SET f.interactions = 0, f.events = 0, f.sessions = 0 "
    "SET f.date = f.date WITH f, row "
    "SET f.events = f.events + row.count, f.sessions = f.sessions + row.sessions "
    "RETURN count(f) AS written",
    "Q-INSIGHT-ADD-ROUTE": "UNWIND $rows AS row "
    "MERGE (r:RouteDaily {tenantId: $tenant, date: row.date, route: row.route, role: row.role, "
    "device: row.device}) "
    "ON CREATE SET r.errors = 0, r.sessions = 0 "
    "SET r.date = r.date WITH r, row "
    "SET r.errors = r.errors + row.errors, r.sessions = r.sessions + row.sessions "
    "RETURN count(r) AS written",
    "Q-INSIGHT-ADD-FUNNEL": "UNWIND $rows AS row "
    "MERGE (f:FunnelDaily {tenantId: $tenant, funnel: row.funnel, step: row.step, "
    "date: row.date, role: row.role, channel: row.channel, device: row.device}) "
    "ON CREATE SET f.branch = false, f.entered = 0, f.completed = 0 "
    "SET f.date = f.date WITH f, row "
    "SET f.entered = f.entered + row.count "
    "RETURN count(f) AS written",
    "Q-INSIGHT-ADD-MEASURE": "UNWIND $rows AS row "
    "MERGE (m:MeasureDaily {tenantId: $tenant, date: row.date, measure: row.measure, "
    "route: row.route, device: row.device, release: row.release}) "
    "ON CREATE SET m.buckets = [bucket IN row.buckets | 0], m.samples = 0, m.sessions = 0 "
    "SET m.date = m.date WITH m, row "
    "SET m.buckets = [i IN range(0, size(m.buckets) - 1) | m.buckets[i] + row.buckets[i]], "
    "m.samples = m.samples + row.samples, m.sessions = m.sessions + row.sessions "
    "RETURN count(m) AS written",
    "Q-INSIGHT-ADD-RELEASE": "UNWIND $rows AS row "
    "MERGE (r:ReleaseDaily {tenantId: $tenant, date: row.date, release: row.release}) "
    "ON CREATE SET r.sessions = 0, r.interactions = 0, r.friction = 0, r.errors = 0, "
    "r.views = 0 "
    "SET r.date = r.date WITH r, row "
    "SET r.sessions = r.sessions + row.sessions, r.interactions = r.interactions + "
    "row.interactions, r.friction = r.friction + row.friction, r.errors = r.errors + "
    "row.errors, r.views = r.views + row.views "
    "RETURN count(r) AS written",
    "Q-INSIGHT-READ-MEASURE": "MATCH (m:MeasureDaily {tenantId: $tenant}) "
    "WHERE m.date >= $start AND m.date <= $end "
    "RETURN m.date AS day, m.measure AS measure, m.route AS route, m.device AS device, "
    "m.release AS release, m.sessions AS sessions, m.samples AS samples, "
    "m.buckets AS buckets ORDER BY day, measure, route, device, release",
    "Q-INSIGHT-READ-RELEASE": "MATCH (r:ReleaseDaily {tenantId: $tenant}) "
    "WHERE r.date >= $start AND r.date <= $end "
    "RETURN r.date AS day, r.release AS release, r.sessions AS sessions, "
    "r.interactions AS interactions, r.friction AS friction, r.errors AS errors, "
    "r.views AS views ORDER BY day, release",
    "Q-INSIGHT-READ-PIPELINE": "MATCH (m:OutboxMessage {tenantId: $tenant}) "
    "WHERE m.status = 'pending' OR m.status = 'dead' "
    "RETURN m.topic AS topic, "
    "sum(CASE WHEN m.status = 'pending' THEN 1 ELSE 0 END) AS active, "
    "sum(CASE WHEN m.status = 'dead' THEN 1 ELSE 0 END) AS dead, "
    "min(CASE WHEN m.status = 'pending' THEN m.createdAt END) AS oldest ORDER BY topic",
}

for _query_id, _text in _CYPHER.items():
    REGISTRY.register(
        NamedQuery(
            id=_query_id,
            cypher=_text,
            mode="read" if "-READ-" in _query_id else "write",
            scenario=_SCENARIOS[_query_id],
        )
    )

_PURGE_LIMIT: Final = 5000


def _instant(value: Any) -> datetime | None:
    if value is None:
        return None
    native: datetime = value.to_native() if hasattr(value, "to_native") else value
    return native.astimezone(UTC)


class Neo4jInsightRepository:
    def __init__(self, tx: ScopedTx) -> None:
        self._tx = tx

    async def mark_seen(self, day: date, keys: Sequence[str]) -> set[str]:
        """Record these markers for the day and say which were not there before (a new session
        in the group). The keys must be distinct."""
        if not keys:
            return set()
        rows = await self._run(
            "Q-INSIGHT-SEEN", markers=[{"key": key, "date": day.isoformat()} for key in keys]
        )
        return {str(row["key"]) for row in rows if row["fresh"]}

    async def advance_funnels(
        self, day: date, marks: Sequence[FunnelMark]
    ) -> dict[str, tuple[int, int]]:
        """Move each marker to its furthest step: the step it was at (-1 for a new one) and the
        step it is at now. The markers must be distinct."""
        if not marks:
            return {}
        rows = await self._run(
            "Q-INSIGHT-FUNNEL-ADVANCE",
            rows=[
                {"marker": mark.marker, "date": day.isoformat(), "top": mark.top} for mark in marks
            ],
        )
        return {str(row["marker"]): (int(row["before"]), int(row["after"])) for row in rows}

    async def purge_seen(self, before: date) -> int:
        rows = await self._run(
            "Q-INSIGHT-PURGE-SEEN", before=before.isoformat(), limit=_PURGE_LIMIT
        )
        return int(rows[0]["removed"]) if rows else 0

    async def add_usage(self, day: date, rows: Sequence[UsageAdd]) -> None:
        if rows:
            await self._run(
                "Q-INSIGHT-ADD-USAGE",
                rows=[
                    {
                        "date": day.isoformat(),
                        "elementId": row.element_id,
                        "role": row.role,
                        "device": row.device,
                        "count": row.count,
                        "sessions": row.sessions,
                    }
                    for row in rows
                ],
            )

    async def add_friction(self, day: date, rows: Sequence[FrictionAdd]) -> None:
        if rows:
            await self._run(
                "Q-INSIGHT-ADD-FRICTION",
                rows=[
                    {
                        "date": day.isoformat(),
                        "elementId": row.element_id,
                        "kind": row.kind,
                        "route": row.route,
                        "role": row.role,
                        "device": row.device,
                        "count": row.count,
                        "sessions": row.sessions,
                    }
                    for row in rows
                ],
            )

    async def add_routes(self, day: date, rows: Sequence[RouteAdd]) -> None:
        if rows:
            await self._run(
                "Q-INSIGHT-ADD-ROUTE",
                rows=[
                    {
                        "date": day.isoformat(),
                        "route": row.route,
                        "role": row.role,
                        "device": row.device,
                        "errors": row.errors,
                        "sessions": row.sessions,
                    }
                    for row in rows
                ],
            )

    async def add_funnel(self, day: date, rows: Sequence[FunnelAdd]) -> None:
        if rows:
            await self._run(
                "Q-INSIGHT-ADD-FUNNEL",
                rows=[
                    {
                        "date": day.isoformat(),
                        "funnel": row.funnel,
                        "step": row.step,
                        "role": row.role,
                        "channel": row.channel,
                        "device": row.device,
                        "count": row.count,
                    }
                    for row in rows
                ],
            )

    async def add_measures(self, day: date, rows: Sequence[MeasureAdd]) -> None:
        if rows:
            await self._run(
                "Q-INSIGHT-ADD-MEASURE",
                rows=[
                    {
                        "date": day.isoformat(),
                        "measure": row.measure,
                        "route": row.route,
                        "device": row.device,
                        "release": row.release,
                        "buckets": list(row.buckets),
                        "samples": row.samples,
                        "sessions": row.sessions,
                    }
                    for row in rows
                ],
            )

    async def add_releases(self, day: date, rows: Sequence[ReleaseAdd]) -> None:
        if rows:
            await self._run(
                "Q-INSIGHT-ADD-RELEASE",
                rows=[
                    {
                        "date": day.isoformat(),
                        "release": row.release,
                        "interactions": row.interactions,
                        "friction": row.friction,
                        "errors": row.errors,
                        "views": row.views,
                        "sessions": row.sessions,
                    }
                    for row in rows
                ],
            )

    async def measure_rows(self, start: date, end: date) -> list[MeasureRow]:
        rows = await self._run(
            "Q-INSIGHT-READ-MEASURE", start=start.isoformat(), end=end.isoformat()
        )
        return [
            MeasureRow(
                day=date.fromisoformat(str(row["day"])),
                measure=str(row["measure"]),
                route=str(row["route"]),
                device=str(row["device"]),
                release=str(row["release"]),
                sessions=int(row["sessions"]),
                samples=int(row["samples"]),
                buckets=tuple(int(count) for count in row["buckets"]),
            )
            for row in rows
        ]

    async def release_rows(self, start: date, end: date) -> list[ReleaseRow]:
        rows = await self._run(
            "Q-INSIGHT-READ-RELEASE", start=start.isoformat(), end=end.isoformat()
        )
        return [
            ReleaseRow(
                day=date.fromisoformat(str(row["day"])),
                release=str(row["release"]),
                sessions=int(row["sessions"]),
                interactions=int(row["interactions"]),
                friction=int(row["friction"]),
                errors=int(row["errors"]),
                views=int(row["views"]),
            )
            for row in rows
        ]

    async def pipeline_rows(self) -> list[PipelineRow]:
        rows = await self._run("Q-INSIGHT-READ-PIPELINE")
        return [
            PipelineRow(
                topic=str(row["topic"]),
                active=int(row["active"]),
                dead=int(row["dead"]),
                oldest_pending=_instant(row["oldest"]),
            )
            for row in rows
        ]

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        query: NamedQuery = REGISTRY.get(query_id)
        return await run_query(self._tx, query, **params)
