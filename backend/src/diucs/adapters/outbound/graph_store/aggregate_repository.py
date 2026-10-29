"""Neo4j store for the daily telemetry aggregates (O08, docs/spec/fhir-data-model.md "Platform
nodes").

Five node labels, one per aggregate table. Every node carries `tenantId`, and every statement
writes `tenantId: $tenant` on each node it matches, merges or creates (DEC-130, DEC-132). `date`
is held as the ISO text YYYY-MM-DD, which sorts in day order, so a range is a text comparison.

(:FunnelDaily {tenantId, funnel, step, date, role, channel, device, branch, entered, completed,
medianMs}) (:FrictionDaily {tenantId, date, elementId, kind, role, device, interactions, events,
sessions}) (:ElementUsageDaily {tenantId, date, elementId, role, device, interactions,
sessions}) (:RouteDaily {tenantId, date, route, role, device, p50, p75, p95, lcp75, inp75,
cls75, errors, sessions}) (:QueryStatDaily {tenantId, date, queryId, calls, p50, p95, errors})

A day is replaced in one unit of work: its rows are removed first, then written, so a second run
of the same day leaves the same node count. There is no uniqueness constraint on these labels
(no migration in this build): two runs for one tenant and day at once could both write. The job
is scheduled once a day, and the known-issues entry records the gap.
"""

from datetime import date
from typing import Any, Final, Literal

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    Scenario,
    SeedNode,
    TenantSeed,
)
from diucs.application.ports.outbound.aggregates import check_one_day
from diucs.domain.model.telemetry_aggregates import (
    DayAggregates,
    ElementUsageDailyRow,
    FrictionDailyRow,
    FunnelDailyRow,
    QueryStatDailyRow,
    RouteDailyRow,
)

_DAY: Final = "2026-10-28"

# The seed: one row of each label, for each tenant, on the same day. Text that differs between the
# tenants is Marked, so a row read from the other tenant shows its marker.
_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "funnel",
            ("FunnelDaily",),
            {
                "funnel": "reporter-set-up",
                "step": Marked("step"),
                "date": _DAY,
                "role": "reporter",
                "channel": "text",
                "device": "phone",
                "branch": False,
                "entered": 40,
                "completed": 36,
                "medianMs": 5200.0,
            },
        ),
        SeedNode(
            "friction",
            ("FrictionDaily",),
            {
                "date": _DAY,
                "elementId": Marked("el"),
                "kind": "rage",
                "role": "advisor",
                "device": "desktop",
                "interactions": 312,
                "events": 41,
                "sessions": 14,
            },
        ),
        SeedNode(
            "usage",
            ("ElementUsageDaily",),
            {
                "date": _DAY,
                "elementId": Marked("el"),
                "role": "advisor",
                "device": "desktop",
                "interactions": 312,
                "sessions": 14,
            },
        ),
        SeedNode(
            "route",
            ("RouteDaily",),
            {
                "date": _DAY,
                "route": Marked("route"),
                "role": "advisor",
                "device": "desktop",
                "p50": 420.0,
                "p75": 700.0,
                "p95": 1300.0,
                "errors": 2,
                "sessions": 22,
            },
        ),
        SeedNode(
            "query",
            ("QueryStatDaily",),
            {
                "date": _DAY,
                "queryId": Marked("board-query"),
                "calls": 120,
                "p50": 38.0,
                "p95": 91.0,
                "errors": 1,
            },
        ),
    ),
)

_WINDOW: Final = {"start": _DAY, "end": _DAY}


def _clear_scenario(label: str) -> Scenario:
    return Scenario(
        f"remove the tenant's {label} rows of the day, and no other day",
        seed=_SEED,
        params={"date": _DAY},
        lookup=("date",),
        expect=Expect(rows=({"removed": 1},), nodes={label: -1}),
    )


def _read_scenario(
    label: str, params: dict[str, Any], expect_rows: tuple[dict[str, Any], ...]
) -> Scenario:
    return Scenario(
        f"read the tenant's {label} rows in the day range",
        seed=_SEED,
        params=params,
        lookup=tuple(params),
        expect=Expect(rows=expect_rows),
    )


_FUNNEL_ROW: Final = {
    "funnel": "reporter-set-up",
    "step": "Welcome started",
    "role": "reporter",
    "channel": "link",
    "device": "phone",
    "date": _DAY,
    "branch": False,
    "entered": 7,
    "completed": 5,
    "medianMs": 2400.0,
}
_FRICTION_ROW: Final = {
    "date": _DAY,
    "elementId": "ADV-REF-INPUT",
    "kind": "validation-loop",
    "role": "advisor",
    "device": "desktop",
    "interactions": 100,
    "events": 3,
    "sessions": 12,
}
_USAGE_ROW: Final = {
    "date": _DAY,
    "elementId": "ADV-REF-INPUT",
    "role": "advisor",
    "device": "desktop",
    "interactions": 100,
    "sessions": 12,
}
_ROUTE_ROW: Final = {
    "date": _DAY,
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
_QUERY_ROW: Final = {
    "date": _DAY,
    "queryId": "board-query",
    "calls": 10,
    "p50": 20.0,
    "p95": 30.0,
    "errors": 0,
}


def _write_scenario(label: str, row: dict[str, Any]) -> Scenario:
    return Scenario(
        f"write one {label} row for the day, beside the tenant's own",
        seed=_SEED,
        params={"rows": [row]},
        new=("rows",),
        expect=Expect(rows=({"written": 1},), nodes={label: 1}),
    )


_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-AGG-CLEAR-FUNNEL": _clear_scenario("FunnelDaily"),
    "Q-AGG-CLEAR-FRICTION": _clear_scenario("FrictionDaily"),
    "Q-AGG-CLEAR-USAGE": _clear_scenario("ElementUsageDaily"),
    "Q-AGG-CLEAR-ROUTE": _clear_scenario("RouteDaily"),
    "Q-AGG-CLEAR-QUERY": _clear_scenario("QueryStatDaily"),
    "Q-AGG-WRITE-FUNNEL": _write_scenario("FunnelDaily", _FUNNEL_ROW),
    "Q-AGG-WRITE-FRICTION": _write_scenario("FrictionDaily", _FRICTION_ROW),
    "Q-AGG-WRITE-USAGE": _write_scenario("ElementUsageDaily", _USAGE_ROW),
    "Q-AGG-WRITE-ROUTE": _write_scenario("RouteDaily", _ROUTE_ROW),
    "Q-AGG-WRITE-QUERY": _write_scenario("QueryStatDaily", _QUERY_ROW),
    "Q-AGG-READ-FUNNEL": _read_scenario(
        "FunnelDaily",
        {"funnel": "reporter-set-up", **_WINDOW},
        ({"day": _DAY, "step": Marked("step"), "entered": 40, "completed": 36},),
    ),
    "Q-AGG-READ-FRICTION": _read_scenario(
        "FrictionDaily",
        dict(_WINDOW),
        ({"day": _DAY, "elementId": Marked("el"), "kind": "rage", "events": 41},),
    ),
    "Q-AGG-READ-USAGE": _read_scenario(
        "ElementUsageDaily",
        dict(_WINDOW),
        ({"day": _DAY, "elementId": Marked("el"), "interactions": 312, "sessions": 14},),
    ),
    "Q-AGG-READ-ROUTE": _read_scenario(
        "RouteDaily",
        dict(_WINDOW),
        ({"day": _DAY, "route": Marked("route"), "p95": 1300.0, "errors": 2},),
    ),
    "Q-AGG-READ-QUERY": _read_scenario(
        "QueryStatDaily",
        dict(_WINDOW),
        ({"day": _DAY, "queryId": Marked("board-query"), "p95": 91.0},),
    ),
}

_CYPHER: Final[dict[str, str]] = {
    "Q-AGG-CLEAR-FUNNEL": "MATCH (n:FunnelDaily {tenantId: $tenant, date: $date}) "
    "WITH collect(n) AS nodes FOREACH (x IN nodes | DETACH DELETE x) RETURN size(nodes) AS removed",
    "Q-AGG-CLEAR-FRICTION": "MATCH (n:FrictionDaily {tenantId: $tenant, date: $date}) "
    "WITH collect(n) AS nodes FOREACH (x IN nodes | DETACH DELETE x) RETURN size(nodes) AS removed",
    "Q-AGG-CLEAR-USAGE": "MATCH (n:ElementUsageDaily {tenantId: $tenant, date: $date}) "
    "WITH collect(n) AS nodes FOREACH (x IN nodes | DETACH DELETE x) RETURN size(nodes) AS removed",
    "Q-AGG-CLEAR-ROUTE": "MATCH (n:RouteDaily {tenantId: $tenant, date: $date}) "
    "WITH collect(n) AS nodes FOREACH (x IN nodes | DETACH DELETE x) RETURN size(nodes) AS removed",
    "Q-AGG-CLEAR-QUERY": "MATCH (n:QueryStatDaily {tenantId: $tenant, date: $date}) "
    "WITH collect(n) AS nodes FOREACH (x IN nodes | DETACH DELETE x) RETURN size(nodes) AS removed",
    "Q-AGG-WRITE-FUNNEL": "UNWIND $rows AS row "
    "MERGE (f:FunnelDaily {tenantId: $tenant, funnel: row.funnel, step: row.step, date: row.date, "
    "role: row.role, channel: row.channel, device: row.device}) "
    "SET f.branch = row.branch, f.entered = row.entered, f.completed = row.completed, "
    "f.medianMs = row.medianMs RETURN count(f) AS written",
    "Q-AGG-WRITE-FRICTION": "UNWIND $rows AS row "
    "MERGE (f:FrictionDaily {tenantId: $tenant, date: row.date, elementId: row.elementId, "
    "kind: row.kind, role: row.role, device: row.device}) "
    "SET f.interactions = row.interactions, f.events = row.events, f.sessions = row.sessions "
    "RETURN count(f) AS written",
    "Q-AGG-WRITE-USAGE": "UNWIND $rows AS row "
    "MERGE (u:ElementUsageDaily {tenantId: $tenant, date: row.date, elementId: row.elementId, "
    "role: row.role, device: row.device}) "
    "SET u.interactions = row.interactions, u.sessions = row.sessions RETURN count(u) AS written",
    "Q-AGG-WRITE-ROUTE": "UNWIND $rows AS row "
    "MERGE (r:RouteDaily {tenantId: $tenant, date: row.date, route: row.route, role: row.role, "
    "device: row.device}) "
    "SET r.p50 = row.p50, r.p75 = row.p75, r.p95 = row.p95, r.lcp75 = row.lcp75, "
    "r.inp75 = row.inp75, r.cls75 = row.cls75, r.errors = row.errors, r.sessions = row.sessions "
    "RETURN count(r) AS written",
    "Q-AGG-WRITE-QUERY": "UNWIND $rows AS row "
    "MERGE (q:QueryStatDaily {tenantId: $tenant, date: row.date, queryId: row.queryId}) "
    "SET q.calls = row.calls, q.p50 = row.p50, q.p95 = row.p95, q.errors = row.errors "
    "RETURN count(q) AS written",
    "Q-AGG-READ-FUNNEL": "MATCH (f:FunnelDaily {tenantId: $tenant, funnel: $funnel}) "
    "WHERE f.date >= $start AND f.date <= $end "
    "RETURN f.date AS day, f.step AS step, f.role AS role, f.channel AS channel, "
    "f.device AS device, f.branch AS branch, f.entered AS entered, f.completed AS completed, "
    "f.medianMs AS medianMs ORDER BY day, step, role, channel, device",
    "Q-AGG-READ-FRICTION": "MATCH (f:FrictionDaily {tenantId: $tenant}) "
    "WHERE f.date >= $start AND f.date <= $end "
    "RETURN f.date AS day, f.elementId AS elementId, f.kind AS kind, f.role AS role, "
    "f.device AS device, f.interactions AS interactions, f.events AS events, "
    "f.sessions AS sessions ORDER BY day, elementId, kind",
    "Q-AGG-READ-USAGE": "MATCH (u:ElementUsageDaily {tenantId: $tenant}) "
    "WHERE u.date >= $start AND u.date <= $end "
    "RETURN u.date AS day, u.elementId AS elementId, u.role AS role, u.device AS device, "
    "u.interactions AS interactions, u.sessions AS sessions ORDER BY day, elementId",
    "Q-AGG-READ-ROUTE": "MATCH (r:RouteDaily {tenantId: $tenant}) "
    "WHERE r.date >= $start AND r.date <= $end "
    "RETURN r.date AS day, r.route AS route, r.role AS role, r.device AS device, r.p50 AS p50, "
    "r.p75 AS p75, r.p95 AS p95, r.lcp75 AS lcp75, r.inp75 AS inp75, r.cls75 AS cls75, "
    "r.errors AS errors, r.sessions AS sessions ORDER BY day, route",
    "Q-AGG-READ-QUERY": "MATCH (q:QueryStatDaily {tenantId: $tenant}) "
    "WHERE q.date >= $start AND q.date <= $end "
    "RETURN q.date AS day, q.queryId AS queryId, q.calls AS calls, q.p50 AS p50, q.p95 AS p95, "
    "q.errors AS errors ORDER BY day, queryId",
}

_CLEAR_IDS: Final = (
    "Q-AGG-CLEAR-FUNNEL",
    "Q-AGG-CLEAR-FRICTION",
    "Q-AGG-CLEAR-USAGE",
    "Q-AGG-CLEAR-ROUTE",
    "Q-AGG-CLEAR-QUERY",
)

for _query_id, _text in _CYPHER.items():
    _mode: Literal["read", "write"] = "read" if "-READ-" in _query_id else "write"
    REGISTRY.register(
        NamedQuery(id=_query_id, cypher=_text, mode=_mode, scenario=_SCENARIOS[_query_id])
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _funnel_params(row: FunnelDailyRow) -> dict[str, Any]:
    return {
        "funnel": row.funnel,
        "step": row.step,
        "date": row.day.isoformat(),
        "role": row.role,
        "channel": row.channel,
        "device": row.device,
        "branch": row.branch,
        "entered": row.entered,
        "completed": row.completed,
        "medianMs": row.median_ms,
    }


def _friction_params(row: FrictionDailyRow) -> dict[str, Any]:
    return {
        "date": row.day.isoformat(),
        "elementId": row.element_id,
        "kind": row.kind,
        "role": row.role,
        "device": row.device,
        "interactions": row.interactions,
        "events": row.events,
        "sessions": row.sessions,
    }


def _usage_params(row: ElementUsageDailyRow) -> dict[str, Any]:
    return {
        "date": row.day.isoformat(),
        "elementId": row.element_id,
        "role": row.role,
        "device": row.device,
        "interactions": row.interactions,
        "sessions": row.sessions,
    }


def _route_params(row: RouteDailyRow) -> dict[str, Any]:
    return {
        "date": row.day.isoformat(),
        "route": row.route,
        "role": row.role,
        "device": row.device,
        "p50": row.p50,
        "p75": row.p75,
        "p95": row.p95,
        "lcp75": row.lcp75,
        "inp75": row.inp75,
        "cls75": row.cls75,
        "errors": row.errors,
        "sessions": row.sessions,
    }


def _query_params(row: QueryStatDailyRow) -> dict[str, Any]:
    return {
        "date": row.day.isoformat(),
        "queryId": row.query_id,
        "calls": row.calls,
        "p50": row.p50,
        "p95": row.p95,
        "errors": row.errors,
    }


class Neo4jAggregateRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def replace_day(self, day: date, aggregates: DayAggregates) -> None:
        check_one_day(
            day,
            [
                *aggregates.funnel,
                *aggregates.friction,
                *aggregates.usage,
                *aggregates.routes,
                *aggregates.queries,
            ],
        )
        text = day.isoformat()
        for query_id in _CLEAR_IDS:
            await self._run(query_id, date=text)
        if aggregates.funnel:
            await self._run(
                "Q-AGG-WRITE-FUNNEL", rows=[_funnel_params(row) for row in aggregates.funnel]
            )
        if aggregates.friction:
            await self._run(
                "Q-AGG-WRITE-FRICTION", rows=[_friction_params(row) for row in aggregates.friction]
            )
        if aggregates.usage:
            await self._run(
                "Q-AGG-WRITE-USAGE", rows=[_usage_params(row) for row in aggregates.usage]
            )
        if aggregates.routes:
            await self._run(
                "Q-AGG-WRITE-ROUTE", rows=[_route_params(row) for row in aggregates.routes]
            )
        if aggregates.queries:
            await self._run(
                "Q-AGG-WRITE-QUERY", rows=[_query_params(row) for row in aggregates.queries]
            )

    async def funnel_rows(self, funnel: str, start: date, end: date) -> list[FunnelDailyRow]:
        rows = await self._run(
            "Q-AGG-READ-FUNNEL", funnel=funnel, start=start.isoformat(), end=end.isoformat()
        )
        return [
            FunnelDailyRow(
                day=date.fromisoformat(str(row["day"])),
                funnel=funnel,
                step=str(row["step"]),
                role=str(row["role"]),
                channel=str(row["channel"]),
                device=str(row["device"]),
                entered=int(row["entered"]),
                completed=int(row["completed"]),
                median_ms=_optional_float(row["medianMs"]),
                branch=bool(row["branch"]),
            )
            for row in rows
        ]

    async def friction_rows(self, start: date, end: date) -> list[FrictionDailyRow]:
        rows = await self._run("Q-AGG-READ-FRICTION", start=start.isoformat(), end=end.isoformat())
        return [
            FrictionDailyRow(
                day=date.fromisoformat(str(row["day"])),
                element_id=str(row["elementId"]),
                kind=str(row["kind"]),
                role=str(row["role"]),
                device=str(row["device"]),
                interactions=int(row["interactions"]),
                events=int(row["events"]),
                sessions=int(row["sessions"]),
            )
            for row in rows
        ]

    async def usage_rows(self, start: date, end: date) -> list[ElementUsageDailyRow]:
        rows = await self._run("Q-AGG-READ-USAGE", start=start.isoformat(), end=end.isoformat())
        return [
            ElementUsageDailyRow(
                day=date.fromisoformat(str(row["day"])),
                element_id=str(row["elementId"]),
                role=str(row["role"]),
                device=str(row["device"]),
                interactions=int(row["interactions"]),
                sessions=int(row["sessions"]),
            )
            for row in rows
        ]

    async def route_rows(self, start: date, end: date) -> list[RouteDailyRow]:
        rows = await self._run("Q-AGG-READ-ROUTE", start=start.isoformat(), end=end.isoformat())
        return [
            RouteDailyRow(
                day=date.fromisoformat(str(row["day"])),
                route=str(row["route"]),
                role=str(row["role"]),
                device=str(row["device"]),
                p50=_optional_float(row["p50"]),
                p75=_optional_float(row["p75"]),
                p95=_optional_float(row["p95"]),
                lcp75=_optional_float(row["lcp75"]),
                inp75=_optional_float(row["inp75"]),
                cls75=_optional_float(row["cls75"]),
                errors=int(row["errors"]),
                sessions=int(row["sessions"]),
            )
            for row in rows
        ]

    async def query_rows(self, start: date, end: date) -> list[QueryStatDailyRow]:
        rows = await self._run("Q-AGG-READ-QUERY", start=start.isoformat(), end=end.isoformat())
        return [
            QueryStatDailyRow(
                day=date.fromisoformat(str(row["day"])),
                query_id=str(row["queryId"]),
                calls=int(row["calls"]),
                p50=_optional_float(row["p50"]),
                p95=_optional_float(row["p95"]),
                errors=int(row["errors"]),
            )
            for row in rows
        ]

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        query: NamedQuery = REGISTRY.get(query_id)
        return await run_query(self._tx, query, **params)
