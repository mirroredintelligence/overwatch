"""The hourly samples of a network board on Neo4j (TEN-082, DEC-132 item 4).

`(:NetworkSample {tenantId: <network scope>, hour})`, one per hour, key unique (migration 0185).
Counts per status, the number of organisations shown and the highest pressure of the hour. It runs
on the scoped transaction of a unit of work bound to a network scope; both statements are
network-only and registered with a scenario, so a tenant scope cannot run them and the generated
test proves the isolation. Nothing in a sample names a member, a service or a grant.

A later sample of an hour replaces the counts (the last board of the hour wins) and the highest
pressure is kept (`peak`: normal, watch or high). A sample older than the one the hour holds
changes the peak only, so a late message cannot turn the counts back.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from diucs.adapters.outbound.graph_store.driver import Tx, run_query
from diucs.adapters.outbound.graph_store.queries import NETWORK_KINDS, REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    TenantSeed,
)
from diucs.domain.codes import Status
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.network_sample import READINGS, NetworkSample
from diucs.domain.rules.pressure import Pressure

_HOUR: Final = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)
_LATER_HOUR: Final = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)
_AT: Final = datetime(2026, 10, 26, 9, 40, tzinfo=UTC)
_OUTSIDE: Final = datetime(2026, 10, 27, 9, 0, tzinfo=UTC)

_COLUMNS: Final = (
    "s.hour AS hour, s.lastAt AS lastAt, s.accepting AS accepting, s.limited AS limited, "
    "s.notAccepting AS notAccepting, s.overCapacity AS overCapacity, "
    "s.notUpdated AS notUpdated, s.outOfHours AS outOfHours, s.unavailable AS unavailable, "
    "s.organisations AS organisations, s.peak AS peak"
)
_COUNT_PROPERTIES: Final = {
    Status.ACCEPTING: "accepting",
    Status.LIMITED: "limited",
    Status.NOT_ACCEPTING: "notAccepting",
    Status.OVER_CAPACITY: "overCapacity",
    Status.NOT_UPDATED: "notUpdated",
    Status.OUT_OF_HOURS: "outOfHours",
}


def _sample_node(hour: datetime, **extra: object) -> SeedNode:
    return SeedNode(
        f"sample-{hour.hour}-{hour.day}",
        ("NetworkSample",),
        {
            "hour": hour,
            "lastAt": hour.replace(minute=30),
            "accepting": 3,
            "limited": 1,
            "notAccepting": 0,
            "overCapacity": 0,
            "notUpdated": 1,
            "outOfHours": 0,
            "unavailable": 0,
            "organisations": 3,
            "peak": "normal",
            **extra,
        },
    )


_RECORD_SCENARIO: Final = Scenario(
    "file a later sample under its hour, keep the highest pressure, change no other hour",
    seed=TenantSeed(
        nodes=(
            _sample_node(_HOUR),
            _sample_node(_LATER_HOUR, peak=Marked("watch")),
        )
    ),
    params={
        "hour": _HOUR,
        "at": _AT,
        "accepting": 2,
        "limited": 2,
        "notAccepting": 1,
        "overCapacity": 0,
        "notUpdated": 0,
        "outOfHours": 0,
        "unavailable": 0,
        "organisations": 3,
        "peak": "high",
    },
    lookup=("hour",),
    new=(
        "at",
        "accepting",
        "limited",
        "notAccepting",
        "overCapacity",
        "notUpdated",
        "outOfHours",
        "unavailable",
        "organisations",
        "peak",
    ),
    expect=Expect(
        rows=({"written": 1},),
        after=(
            NodeSpec(
                ("NetworkSample",),
                {"hour": _HOUR, "accepting": 2, "limited": 2, "notAccepting": 1, "peak": "high"},
            ),
            NodeSpec(("NetworkSample",), {"hour": _LATER_HOUR, "accepting": 3}),
        ),
    ),
)
_RANGE_SCENARIO: Final = Scenario(
    "read the samples of the hours in a range, oldest first",
    seed=TenantSeed(
        nodes=(
            _sample_node(_HOUR, peak=Marked("high")),
            _sample_node(_LATER_HOUR, peak=Marked("watch")),
            _sample_node(_OUTSIDE, peak=Marked("normal")),
        )
    ),
    params={"from": _HOUR, "to": _OUTSIDE},
    new=("from", "to"),
    expect=Expect(
        rows=(
            {"accepting": 3, "peak": Marked("high")},
            {"accepting": 3, "peak": Marked("watch")},
        )
    ),
)

_STATEMENTS: Final[dict[str, tuple[str, str, Scenario]]] = {
    "Q-NETSAMPLE-RECORD": (
        "write",
        "MERGE (s:NetworkSample {tenantId: $tenant, hour: $hour}) "
        "ON CREATE SET s.lastAt = $at, s.peak = $peak "
        "ON MATCH SET s.peak = CASE WHEN s.peak = 'high' OR $peak = 'high' THEN 'high' "
        "WHEN s.peak = 'watch' OR $peak = 'watch' THEN 'watch' ELSE 'normal' END "
        "WITH s WHERE s.lastAt <= $at "
        "SET s.lastAt = $at, s.accepting = $accepting, s.limited = $limited, "
        "s.notAccepting = $notAccepting, s.overCapacity = $overCapacity, "
        "s.notUpdated = $notUpdated, s.outOfHours = $outOfHours, s.unavailable = $unavailable, "
        "s.organisations = $organisations RETURN count(s) AS written",
        _RECORD_SCENARIO,
    ),
    "Q-NETSAMPLE-RANGE": (
        "read",
        "MATCH (s:NetworkSample {tenantId: $tenant}) WHERE s.hour >= $from AND s.hour < $to "
        f"RETURN {_COLUMNS} ORDER BY s.hour",
        _RANGE_SCENARIO,
    ),
}

QUERIES: Final[dict[str, NamedQuery]] = {}
for _id, (_mode, _cypher, _scenario) in _STATEMENTS.items():
    _query = NamedQuery(
        id=_id,
        cypher=_cypher,
        mode=_mode,  # type: ignore[arg-type]
        scenario=_scenario,
        scope_kinds=NETWORK_KINDS,
    )
    REGISTRY.register(_query)
    QUERIES[_id] = _query


def _aware(value: Any) -> datetime:
    native: datetime = value.to_native() if hasattr(value, "to_native") else value
    return native.astimezone(UTC)


def _sample(row: dict[str, Any]) -> NetworkSample:
    return NetworkSample(
        hour=_aware(row["hour"]),
        at=_aware(row["lastAt"]),
        counts=tuple((status, int(row[_COUNT_PROPERTIES[status]])) for status in READINGS),
        unavailable=int(row["unavailable"]),
        organisations=int(row["organisations"]),
        pressure=Pressure(row["peak"]),
    )


class Neo4jNetworkSampleRepository:
    def __init__(self, tx: Tx) -> None:
        self._tx = tx

    async def record(self, sample: NetworkSample) -> bool:
        if type(sample) is not NetworkSample:
            raise ValidationFailed("sample", "is not a network sample")
        params: dict[str, Any] = {
            _COUNT_PROPERTIES[status]: count for status, count in sample.counts
        }
        params.update(
            hour=sample.hour,
            at=sample.at,
            peak=sample.pressure.value,
            unavailable=sample.unavailable,
            organisations=sample.organisations,
        )
        rows = await run_query(self._tx, QUERIES["Q-NETSAMPLE-RECORD"], **params)
        return bool(rows and rows[0]["written"])

    async def between(self, start: datetime, end: datetime) -> Sequence[NetworkSample]:
        for field, value in (("start", start), ("end", end)):
            if type(value) is not datetime or value.utcoffset() is None:
                raise ValidationFailed(field, "must be a timezone-aware datetime")
        window: dict[str, Any] = {"from": start, "to": end}
        rows = await run_query(self._tx, QUERIES["Q-NETSAMPLE-RANGE"], **window)
        return [_sample(row) for row in rows]
