"""The scenarios of the projection statements of `projection_repository.py` (TEN-053, DEC-142
item 5, DEC-542).

One scenario per statement. The generated test (TEN-060) runs each one in a network scope A and in
a network scope B on a private container: both scopes get the same member, the same services and
the same keys, so a statement that forgets `tenantId: $tenant` finds the other scope's node by key.
The text that should differ between the two scopes (a service name, a grant id) is `Marked`.

A scope's seed is written the way the statements write a network scope: a `ProjectionSource` for
each kind of grant scope, a projected service with its location and opening windows on the two
child relationships, a capacity row and a criteria row, each keyed by the member (`tenant-x`) and
the service (`svc-1`). Values the seed writes as text (times, dates) are text, because a scenario
is data and the statements compare none of them.

This module is pure data: no Neo4j, no scope, no Cypher.
"""

from datetime import UTC, datetime
from typing import Final

from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)

SOURCE: Final = "tenant-x"
_STAMP: Final = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
_LATER: Final = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
_OLD: Final = "2026-10-01T09:00:00Z"
_KEYS: Final = ("sourceTenant", "sourceServiceId")
_ENDED: Final = {"endedAt": "2026-09-01T00:00:00Z", "endReason": "grant-ended"}
_STAMPS: Final = {"projectedAt": _STAMP, "grantId": "grant-new", "grantVersion": 7}
_STAMP_NAMES: Final = ("projectedAt", "grantId", "grantVersion")


def _source(kind: str, status: str = "active", **extra: object) -> SeedNode:
    return SeedNode(
        f"source-{kind}",
        ("ProjectionSource",),
        {
            "sourceTenantId": SOURCE,
            "kind": kind,
            "status": status,
            "grantId": Marked("grant"),
            **extra,
        },
    )


def _service(version: int = 2, ref: str = "service", **extra: object) -> SeedNode:
    return SeedNode(
        ref,
        ("ProjectedService",),
        {
            "sourceTenantId": SOURCE,
            "sourceServiceId": "svc-1",
            "sourceVersion": version,
            "serviceName": Marked("Old name"),
            "categoryCode": "reablement",
            "active": True,
            "source": "manual",
            "projectedAt": _OLD,
            **extra,
        },
    )


def _location(ref: str = "location", **extra: object) -> SeedNode:
    return SeedNode(
        ref,
        ("ProjectedLocation",),
        {
            "sourceTenantId": SOURCE,
            "sourceServiceId": "svc-1",
            "locationName": Marked("Old base"),
            "postalDistrict": "DT1",
            **extra,
        },
    )


def _hour(position: int, **extra: object) -> SeedNode:
    return SeedNode(
        f"hour-{position}",
        ("ProjectedOpeningHour",),
        {
            "sourceTenantId": SOURCE,
            "sourceServiceId": "svc-1",
            "position": position,
            "days": [1, 2],
            "allDay": False,
            "start": "08:00:00",
            "end": "18:00:00",
            "note": Marked("hour"),
            **extra,
        },
    )


def _capacity(ref: str = "capacity", **extra: object) -> SeedNode:
    return SeedNode(
        ref,
        ("ProjectedCapacity",),
        {
            "sourceTenantId": SOURCE,
            "sourceServiceId": "svc-1",
            "sourceVersion": 1000,
            "sourceReportId": Marked("report"),
            "unitLabel": "slots",
            **extra,
        },
    )


def _criteria(ref: str = "criteria", **extra: object) -> SeedNode:
    return SeedNode(
        ref,
        ("ProjectedCriteria",),
        {
            "sourceTenantId": SOURCE,
            "sourceServiceId": "svc-1",
            "sourceCriteriaId": Marked("crit"),
            "version": 1,
            "reviewBy": "2027-01-01",
            **extra,
        },
    )


def _ended(node: SeedNode, **props: object) -> SeedNode:
    """A row of another service that an earlier end already marked: a statement must leave it as
    it is, and a live read must not return it."""
    return SeedNode(
        "ended-row", node.labels, {**node.props, "sourceServiceId": "svc-2", **_ENDED, **props}
    )


def _scenario(
    description: str,
    nodes: tuple[SeedNode, ...],
    params: dict[str, object],
    expect: Expect,
    *,
    rels: tuple[SeedRel, ...] = (),
    lookup: tuple[str, ...] = _KEYS,
    new: tuple[str, ...] = (),
) -> Scenario:
    return Scenario(
        description,
        seed=TenantSeed(nodes=nodes, rels=rels),
        params=params,
        lookup=lookup,
        new=new,
        expect=expect,
    )


def _mark(label: str, node: SeedNode, ended: SeedNode) -> Scenario:
    return _scenario(
        f"mark the live {label} rows of one member as ended and leave the ended ones",
        (node, ended),
        {"sourceTenant": SOURCE, "endedAt": _LATER, "endReason": "left"},
        Expect(
            rows=({"marked": 1},),
            after=(NodeSpec((label,), {"sourceServiceId": "svc-1", "endReason": "left"}),),
        ),
        lookup=("sourceTenant",),
        new=("endedAt", "endReason"),
    )


def _children(*hours: int, location: bool = True) -> tuple[SeedRel, ...]:
    rels = [SeedRel("service", "HAS_OPENING_HOUR", f"hour-{n}") for n in hours]
    return (SeedRel("service", "HAS_LOCATION", "location"), *rels) if location else tuple(rels)


_SOURCES: Final = (_source("directory"), _source("capacity"), _source("criteria"))

_CAPACITY_PARAMS: Final[dict[str, object]] = {
    "sourceTenant": SOURCE,
    "sourceServiceId": "svc-1",
    "sourceVersion": 2000,
    "measureCode": "free-beds",
    "unitLabel": "beds",
    "establishedCapacity": 20,
    "canExceedEstablished": True,
    "limitedLevelPercent": 30,
    "cadenceCode": "once-a-day",
    "suspended": False,
    "sourceReportId": "rep-9",
    "effectiveDateTime": _STAMP,
    "value": 11,
    "confirmedSince": 3,
    "replyWindowMinutes": 45,
    "staleWarningHours": 4,
    "validUntil": _LATER,
    **_STAMPS,
}


PROJECTION_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-PROJ-SOURCE-GET": _scenario(
        "read the source of one member and kind",
        (
            *_SOURCES,
            SeedNode(
                "other-member",
                ("ProjectionSource",),
                {
                    "sourceTenantId": "tenant-y",
                    "kind": "directory",
                    "status": "ended",
                    "grantId": Marked("other"),
                },
            ),
        ),
        {"sourceTenant": SOURCE, "kind": "directory"},
        Expect(rows=({"source": {"status": "active", "grantId": Marked("grant")}},)),
        lookup=("sourceTenant", "kind"),
    ),
    "Q-PROJ-SOURCES": _scenario(
        "list every source of the network",
        _SOURCES,
        {},
        Expect(
            rows=(
                {"source": {"kind": "capacity"}},
                {"source": {"kind": "criteria"}},
                {"source": {"kind": "directory"}},
            )
        ),
        lookup=(),
    ),
    "Q-PROJ-SOURCE-OPEN": _scenario(
        "open a source, and reopen an ended one under a new grant",
        (_source("capacity", "ended", **_ENDED),),
        {"sourceTenant": SOURCE, "kind": "capacity", "grantId": "grant-new"},
        Expect(
            rows=({"status": "active"},),
            after=(
                NodeSpec(
                    ("ProjectionSource",),
                    {"kind": "capacity", "status": "active", "grantId": "grant-new"},
                ),
            ),
        ),
        lookup=("sourceTenant", "kind"),
        new=("grantId",),
    ),
    "Q-PROJ-SOURCE-END": _scenario(
        "end an active source",
        (_source("capacity"),),
        {"sourceTenant": SOURCE, "kind": "capacity", "endedAt": _LATER, "endReason": "left"},
        Expect(
            rows=({"kind": "capacity"},),
            after=(NodeSpec(("ProjectionSource",), {"status": "ended", "endReason": "left"}),),
        ),
        lookup=("sourceTenant", "kind"),
        new=("endedAt", "endReason"),
    ),
    "Q-PROJ-SERVICE-UPSERT": _scenario(
        "write a newer version of a service under an active directory source",
        (_source("directory"), _service(version=1)),
        {
            "sourceTenant": SOURCE,
            "sourceServiceId": "svc-1",
            "sourceVersion": 2,
            "serviceName": "New name",
            "categoryCode": "urgent-treatment",
            "active": True,
            "source": "manual",
            "serviceContactLabel": "Duty desk",
            "serviceContactPhone": "0300 123 4567",
            **_STAMPS,
        },
        Expect(
            rows=({"written": 1},),
            after=(
                NodeSpec(
                    ("ProjectedService",),
                    {"sourceServiceId": "svc-1", "sourceVersion": 2, "serviceName": "New name"},
                ),
            ),
        ),
        new=(
            "sourceVersion",
            "serviceName",
            "categoryCode",
            "serviceContactLabel",
            "serviceContactPhone",
            *_STAMP_NAMES,
        ),
    ),
    "Q-PROJ-LOCATION-UPSERT": _scenario(
        "write the location of the version just written",
        (_source("directory"), _service()),
        {
            "sourceTenant": SOURCE,
            "sourceServiceId": "svc-1",
            "sourceVersion": 2,
            "locationName": "New base",
            "postalDistrict": "DT4",
            "city": "Sampletown",
            "latitude": 52.5,
            "longitude": -1.5,
            **_STAMPS,
        },
        Expect(
            rows=({"written": 1},),
            nodes={"ProjectedLocation": 1},
            rels={"HAS_LOCATION": 1},
            after=(NodeSpec(("ProjectedLocation",), {"locationName": "New base"}),),
        ),
        lookup=(*_KEYS, "sourceVersion"),
        new=("locationName", "postalDistrict", "city", "latitude", "longitude", *_STAMP_NAMES),
    ),
    "Q-PROJ-LOCATION-END": _scenario(
        "end the location a newer version no longer has",
        (_service(), _location()),
        {
            "sourceTenant": SOURCE,
            "sourceServiceId": "svc-1",
            "sourceVersion": 2,
            "endedAt": _LATER,
            "endReason": "replaced",
        },
        Expect(
            rows=({"ended": 1},),
            after=(NodeSpec(("ProjectedLocation",), {"endReason": "replaced"}),),
        ),
        rels=(SeedRel("service", "HAS_LOCATION", "location"),),
        lookup=(*_KEYS, "sourceVersion"),
        new=("endedAt", "endReason"),
    ),
    "Q-PROJ-HOUR-UPSERT": _scenario(
        "write an opening window of the version just written",
        (_source("directory"), _service(), _hour(0)),
        {
            "sourceTenant": SOURCE,
            "sourceServiceId": "svc-1",
            "sourceVersion": 2,
            "position": 0,
            "days": [3, 4, 5],
            "allDay": False,
            "start": "09:00:00",
            "end": "17:00:00",
            **_STAMPS,
        },
        Expect(
            rows=({"written": 1},),
            after=(NodeSpec(("ProjectedOpeningHour",), {"position": 0, "start": "09:00:00"}),),
        ),
        rels=_children(0, location=False),
        lookup=(*_KEYS, "sourceVersion", "position"),
        new=("days", "start", "end", *_STAMP_NAMES),
    ),
    "Q-PROJ-HOURS-END": _scenario(
        "end the opening windows from a position on",
        (_service(), _hour(0), _hour(1), _hour(2)),
        {
            "sourceTenant": SOURCE,
            "sourceServiceId": "svc-1",
            "sourceVersion": 2,
            "fromPosition": 1,
            "endedAt": _LATER,
            "endReason": "replaced",
        },
        Expect(
            rows=({"ended": 2},),
            after=(NodeSpec(("ProjectedOpeningHour",), {"position": 2, "endReason": "replaced"}),),
        ),
        rels=_children(0, 1, 2, location=False),
        lookup=(*_KEYS, "sourceVersion"),
        new=("endedAt", "endReason"),
    ),
    "Q-PROJ-CAPACITY-UPSERT": _scenario(
        "write a newer capacity row under an active capacity source",
        (_source("capacity"), _capacity()),
        dict(_CAPACITY_PARAMS),
        Expect(
            rows=({"written": 1},),
            after=(
                NodeSpec(
                    ("ProjectedCapacity",),
                    {"sourceServiceId": "svc-1", "sourceVersion": 2000, "value": 11},
                ),
            ),
        ),
        new=tuple(name for name in _CAPACITY_PARAMS if name not in _KEYS),
    ),
    "Q-PROJ-CRITERIA-UPSERT": _scenario(
        "write a newer criteria version under an active criteria source",
        (_source("criteria"), _criteria()),
        {
            "sourceTenant": SOURCE,
            "sourceServiceId": "svc-1",
            "sourceCriteriaId": "crit-2",
            "version": 2,
            "ageMin": 18,
            "ageMax": 90,
            "postcodeDistricts": ["DT4"],
            "acceptsNeedCodes": ["frailty"],
            "excludesNeedCodes": ["palliative"],
            "reviewBy": "2027-06-01",
            **_STAMPS,
        },
        Expect(
            rows=({"written": 1},),
            after=(
                NodeSpec(
                    ("ProjectedCriteria",), {"sourceServiceId": "svc-1", "version": 2, "ageMin": 18}
                ),
            ),
        ),
        new=(
            "sourceCriteriaId",
            "version",
            "ageMin",
            "ageMax",
            "postcodeDistricts",
            "acceptsNeedCodes",
            "excludesNeedCodes",
            "reviewBy",
            *_STAMP_NAMES,
        ),
    ),
    "Q-PROJ-MARK-SERVICE": _mark("ProjectedService", _service(), _ended(_service())),
    "Q-PROJ-MARK-LOCATION": _mark("ProjectedLocation", _location(), _ended(_location())),
    "Q-PROJ-MARK-HOUR": _mark("ProjectedOpeningHour", _hour(0), _ended(_hour(0), position=5)),
    "Q-PROJ-MARK-CAPACITY": _mark("ProjectedCapacity", _capacity(), _ended(_capacity())),
    "Q-PROJ-MARK-CRITERIA": _mark("ProjectedCriteria", _criteria(), _ended(_criteria())),
    "Q-NETVIEW-SERVICES": _scenario(
        "read the live services with their location and opening windows",
        (_service(), _location(), _hour(0), _hour(1), _hour(2), _ended(_service())),
        {"liveOnly": True},
        Expect(
            rows=({"service": {"sourceServiceId": "svc-1", "serviceName": Marked("Old name")}},)
        ),
        rels=_children(0, 1, 2),
        lookup=(),
    ),
    "Q-NETVIEW-CAPACITIES": _scenario(
        "read the live capacity rows",
        (_capacity(), _ended(_capacity())),
        {"liveOnly": True},
        Expect(
            rows=({"capacity": {"sourceServiceId": "svc-1", "sourceReportId": Marked("report")}},)
        ),
        lookup=(),
    ),
    "Q-NETVIEW-CRITERIA": _scenario(
        "read the live criteria rows",
        (_criteria(), _ended(_criteria())),
        {"liveOnly": True},
        Expect(rows=({"criteria": {"sourceServiceId": "svc-1", "version": 1}},)),
        lookup=(),
    ),
}
