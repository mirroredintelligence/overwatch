"""The projection repository on Neo4j: the network scope's writer and reader (TEN-053, DEC-542,
DEC-132 item 4, DEC-134 items 6 and 7).

It runs on the scoped transaction of a unit of work bound to a network scope, and every statement
is a network-only registered statement (`run_query` refuses it in a tenant scope). What is written
is a DTO of the allowlist and nothing else: the parameters of an upsert are the stored properties
`to_rows` gives for the DTO, the member the row came from (`sourceTenant`, stored as
`sourceTenantId`) and three stamps (`projectedAt`, `grantId`, `grantVersion`; the scope is the
bound one). No method takes a property bag, and the statements are written out in full, each
checked at registration by the label partition and in the tests by the allowlist's own statement
check (no map assignment, no label assignment, no delete, no property or relationship outside the
allowlist).

How a row is kept:

- A `ProjectionSource` per member and kind of grant scope says whether that member's projection of
  that kind is open. An upsert matches the active source first and takes its lock (a self-set), so
  an upsert that races a leave or a grant end finds the source ended and writes nothing.
- A service, a capacity row and a criteria row are one current row per member and service
  (DEC-542 item 1), ordered by the source's version: an equal version is a replay and writes the
  same row, an older one writes nothing (hazard H-N06). A location and an opening window hang off
  their service by `HAS_LOCATION` and `HAS_OPENING_HOUR` and are written only for the version just
  written.
- Nothing is deleted. A window or a place that a newer version no longer has is marked ended with
  the reason `replaced`; when a member leaves or a grant ends, `mark_ended` marks every live row of
  that member and kind with the date and the reason. A later projection under a new grant clears
  the marks.

A node the DTO refuses is `ProjectionRecordInvalid`, a fixed message that holds no value.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any, Final

from neo4j.time import Date, DateTime
from neo4j.time import Time as Neo4jTime

from diucs.adapters.outbound.graph_store.driver import Tx, run_query
from diucs.adapters.outbound.graph_store.projection_scenarios import PROJECTION_SCENARIOS
from diucs.adapters.outbound.graph_store.queries import (
    NETWORK_KINDS,
    REGISTRY,
    NamedQuery,
)
from diucs.application.ports.outbound.projection import (
    GrantRef,
    ProjectedRow,
    ProjectionEndReason,
    ProjectionRecordInvalid,
    SourceState,
    SourceStatus,
)
from diucs.application.projection import to_rows
from diucs.domain.codes import Cadence, Measure, NeedCategory, ServiceCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.network import DirectorySource, GrantScope
from diucs.domain.rules.projection import (
    CapacityProjection,
    CriteriaProjection,
    LocationProjection,
    OpeningHourProjection,
    ServiceProjection,
)

RECORD_MESSAGE: Final = "a projected node in the network scope is not valid"
_AWARE_MESSAGE: Final = "must be a timezone-aware datetime"

# Each statement is written out in full (no Cypher is built from pieces, DEC-142 item 1). The
# scenario of each is in `projection_scenarios.py`; the registry refuses one without it.
_REPLACED: Final = ProjectionEndReason.REPLACED.value

_STATEMENTS: Final[dict[str, tuple[str, str]]] = {
    "Q-PROJ-SOURCE-GET": (
        "read",
        "MATCH (s:ProjectionSource {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "kind: $kind}) RETURN properties(s) AS source",
    ),
    "Q-PROJ-SOURCES": (
        "read",
        "MATCH (s:ProjectionSource {tenantId: $tenant}) RETURN properties(s) AS source "
        "ORDER BY s.sourceTenantId, s.kind",
    ),
    "Q-PROJ-SOURCE-OPEN": (
        "write",
        "MERGE (s:ProjectionSource {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "kind: $kind}) ON CREATE SET s.status = 'active', s.grantId = $grantId "
        "ON MATCH SET s.status = 'active', s.grantId = $grantId, s.endedAt = null, "
        "s.endReason = null RETURN s.status AS status",
    ),
    "Q-PROJ-SOURCE-END": (
        "write",
        "MATCH (s:ProjectionSource {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "kind: $kind, status: 'active'}) SET s.status = 'ended', s.endedAt = $endedAt, "
        "s.endReason = $endReason RETURN s.kind AS kind",
    ),
    "Q-PROJ-SERVICE-UPSERT": (
        "write",
        "MATCH (s:ProjectionSource {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "kind: 'directory', status: 'active'}) SET s.status = s.status "
        "WITH s MERGE (p:ProjectedService {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "sourceServiceId: $sourceServiceId}) "
        "WITH p WHERE p.sourceVersion IS NULL OR p.sourceVersion <= $sourceVersion "
        "SET p.sourceVersion = $sourceVersion, p.serviceName = $serviceName, "
        "p.categoryCode = $categoryCode, p.active = $active, p.source = $source, "
        "p.serviceContactLabel = $serviceContactLabel, "
        "p.serviceContactPhone = $serviceContactPhone, p.projectedAt = $projectedAt, "
        "p.grantId = $grantId, p.grantVersion = $grantVersion, p.endedAt = null, "
        "p.endReason = null RETURN count(p) AS written",
    ),
    "Q-PROJ-LOCATION-UPSERT": (
        "write",
        "MATCH (s:ProjectionSource {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "kind: 'directory', status: 'active'}) SET s.status = s.status "
        "WITH s MATCH (p:ProjectedService {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "sourceServiceId: $sourceServiceId}) WHERE p.sourceVersion = $sourceVersion "
        "MERGE (p)-[:HAS_LOCATION]->(l:ProjectedLocation {tenantId: $tenant, "
        "sourceTenantId: $sourceTenant, sourceServiceId: $sourceServiceId}) "
        "SET l.locationName = $locationName, l.postalDistrict = $postalDistrict, "
        "l.city = $city, l.latitude = $latitude, l.longitude = $longitude, "
        "l.projectedAt = $projectedAt, l.grantId = $grantId, l.grantVersion = $grantVersion, "
        "l.endedAt = null, l.endReason = null RETURN count(l) AS written",
    ),
    "Q-PROJ-LOCATION-END": (
        "write",
        "MATCH (p:ProjectedService {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "sourceServiceId: $sourceServiceId})-[:HAS_LOCATION]->(l:ProjectedLocation "
        "{tenantId: $tenant, sourceTenantId: $sourceTenant}) "
        "WHERE p.sourceVersion = $sourceVersion AND l.endedAt IS NULL "
        "SET l.endedAt = $endedAt, l.endReason = $endReason RETURN count(l) AS ended",
    ),
    "Q-PROJ-HOUR-UPSERT": (
        "write",
        "MATCH (s:ProjectionSource {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "kind: 'directory', status: 'active'}) SET s.status = s.status "
        "WITH s MATCH (p:ProjectedService {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "sourceServiceId: $sourceServiceId}) WHERE p.sourceVersion = $sourceVersion "
        "MERGE (p)-[:HAS_OPENING_HOUR]->(h:ProjectedOpeningHour {tenantId: $tenant, "
        "sourceTenantId: $sourceTenant, sourceServiceId: $sourceServiceId, "
        "position: $position}) "
        "SET h.days = $days, h.allDay = $allDay, h.start = $start, h.end = $end, "
        "h.projectedAt = $projectedAt, h.grantId = $grantId, h.grantVersion = $grantVersion, "
        "h.endedAt = null, h.endReason = null RETURN count(h) AS written",
    ),
    "Q-PROJ-HOURS-END": (
        "write",
        "MATCH (p:ProjectedService {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "sourceServiceId: $sourceServiceId})-[:HAS_OPENING_HOUR]->(h:ProjectedOpeningHour "
        "{tenantId: $tenant, sourceTenantId: $sourceTenant}) "
        "WHERE p.sourceVersion = $sourceVersion AND h.position >= $fromPosition "
        "AND h.endedAt IS NULL "
        "SET h.endedAt = $endedAt, h.endReason = $endReason RETURN count(h) AS ended",
    ),
    "Q-PROJ-CAPACITY-UPSERT": (
        "write",
        "MATCH (s:ProjectionSource {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "kind: 'capacity', status: 'active'}) SET s.status = s.status "
        "WITH s MERGE (p:ProjectedCapacity {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "sourceServiceId: $sourceServiceId}) "
        "WITH p WHERE p.sourceVersion IS NULL OR p.sourceVersion <= $sourceVersion "
        "SET p.sourceVersion = $sourceVersion, p.measureCode = $measureCode, "
        "p.unitLabel = $unitLabel, p.establishedCapacity = $establishedCapacity, "
        "p.canExceedEstablished = $canExceedEstablished, "
        "p.limitedLevelPercent = $limitedLevelPercent, p.cadenceCode = $cadenceCode, "
        "p.suspended = $suspended, p.sourceReportId = $sourceReportId, "
        "p.effectiveDateTime = $effectiveDateTime, p.value = $value, "
        "p.confirmedSince = $confirmedSince, p.replyWindowMinutes = $replyWindowMinutes, "
        "p.staleWarningHours = $staleWarningHours, p.validUntil = $validUntil, "
        "p.projectedAt = $projectedAt, p.grantId = $grantId, p.grantVersion = $grantVersion, "
        "p.endedAt = null, p.endReason = null RETURN count(p) AS written",
    ),
    "Q-PROJ-CRITERIA-UPSERT": (
        "write",
        "MATCH (s:ProjectionSource {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "kind: 'criteria', status: 'active'}) SET s.status = s.status "
        "WITH s MERGE (p:ProjectedCriteria {tenantId: $tenant, sourceTenantId: $sourceTenant, "
        "sourceServiceId: $sourceServiceId}) "
        "WITH p WHERE p.version IS NULL OR p.version <= $version "
        "SET p.version = $version, p.sourceCriteriaId = $sourceCriteriaId, "
        "p.ageMin = $ageMin, p.ageMax = $ageMax, p.postcodeDistricts = $postcodeDistricts, "
        "p.acceptsNeedCodes = $acceptsNeedCodes, p.excludesNeedCodes = $excludesNeedCodes, "
        "p.reviewBy = $reviewBy, p.projectedAt = $projectedAt, p.grantId = $grantId, "
        "p.grantVersion = $grantVersion, p.endedAt = null, p.endReason = null "
        "RETURN count(p) AS written",
    ),
    "Q-PROJ-MARK-SERVICE": (
        "write",
        "MATCH (p:ProjectedService {tenantId: $tenant, sourceTenantId: $sourceTenant}) "
        "WHERE p.endedAt IS NULL SET p.endedAt = $endedAt, p.endReason = $endReason "
        "RETURN count(p) AS marked",
    ),
    "Q-PROJ-MARK-LOCATION": (
        "write",
        "MATCH (p:ProjectedLocation {tenantId: $tenant, sourceTenantId: $sourceTenant}) "
        "WHERE p.endedAt IS NULL SET p.endedAt = $endedAt, p.endReason = $endReason "
        "RETURN count(p) AS marked",
    ),
    "Q-PROJ-MARK-HOUR": (
        "write",
        "MATCH (p:ProjectedOpeningHour {tenantId: $tenant, sourceTenantId: $sourceTenant}) "
        "WHERE p.endedAt IS NULL SET p.endedAt = $endedAt, p.endReason = $endReason "
        "RETURN count(p) AS marked",
    ),
    "Q-PROJ-MARK-CAPACITY": (
        "write",
        "MATCH (p:ProjectedCapacity {tenantId: $tenant, sourceTenantId: $sourceTenant}) "
        "WHERE p.endedAt IS NULL SET p.endedAt = $endedAt, p.endReason = $endReason "
        "RETURN count(p) AS marked",
    ),
    "Q-PROJ-MARK-CRITERIA": (
        "write",
        "MATCH (p:ProjectedCriteria {tenantId: $tenant, sourceTenantId: $sourceTenant}) "
        "WHERE p.endedAt IS NULL SET p.endedAt = $endedAt, p.endReason = $endReason "
        "RETURN count(p) AS marked",
    ),
    "Q-NETVIEW-SERVICES": (
        "read",
        "MATCH (p:ProjectedService {tenantId: $tenant}) "
        "WHERE $liveOnly = false OR p.endedAt IS NULL "
        "OPTIONAL MATCH (p)-[:HAS_LOCATION]->(l:ProjectedLocation {tenantId: $tenant}) "
        "WHERE l.endedAt IS NULL OR ($liveOnly = false AND l.endReason <> 'replaced') "
        "OPTIONAL MATCH (p)-[:HAS_OPENING_HOUR]->(h:ProjectedOpeningHour {tenantId: $tenant}) "
        "WHERE h.endedAt IS NULL OR ($liveOnly = false AND h.endReason <> 'replaced') "
        "WITH p, l, h ORDER BY h.position "
        "WITH p, l, collect(properties(h)) AS hours "
        "RETURN properties(p) AS service, properties(l) AS location, hours "
        "ORDER BY p.sourceTenantId, p.sourceServiceId",
    ),
    "Q-NETVIEW-CAPACITIES": (
        "read",
        "MATCH (p:ProjectedCapacity {tenantId: $tenant}) "
        "WHERE $liveOnly = false OR p.endedAt IS NULL RETURN properties(p) AS capacity "
        "ORDER BY p.sourceTenantId, p.sourceServiceId",
    ),
    "Q-NETVIEW-CRITERIA": (
        "read",
        "MATCH (p:ProjectedCriteria {tenantId: $tenant}) "
        "WHERE $liveOnly = false OR p.endedAt IS NULL RETURN properties(p) AS criteria "
        "ORDER BY p.sourceTenantId, p.sourceServiceId",
    ),
}


def _register(query_id: str, mode: str, cypher: str) -> NamedQuery:
    query = NamedQuery(
        id=query_id,
        cypher=cypher,
        mode=mode,  # type: ignore[arg-type]
        scenario=PROJECTION_SCENARIOS[query_id],
        scope_kinds=NETWORK_KINDS,
    )
    REGISTRY.register(query)
    return query


_QUERIES: Final[dict[str, NamedQuery]] = {
    query_id: _register(query_id, mode, cypher) for query_id, (mode, cypher) in _STATEMENTS.items()
}


# ---------------------------------------------------------------- reading a node back


class _Invalid(Exception):
    """Internal: a property is missing or of the wrong type. Never leaves this module."""


def _text(props: Mapping[str, Any], key: str) -> str:
    value = props.get(key)
    if type(value) is not str:
        raise _Invalid
    return value


def _optional_text(props: Mapping[str, Any], key: str) -> str | None:
    value = props.get(key)
    if value is None:
        return None
    if type(value) is not str:
        raise _Invalid
    return value


def _count(props: Mapping[str, Any], key: str) -> int:
    value = props.get(key)
    if type(value) is not int:
        raise _Invalid
    return value


def _optional_count(props: Mapping[str, Any], key: str) -> int | None:
    return None if props.get(key) is None else _count(props, key)


def _flag(props: Mapping[str, Any], key: str) -> bool:
    value = props.get(key)
    if type(value) is not bool:
        raise _Invalid
    return value


def _optional_real(props: Mapping[str, Any], key: str) -> float | None:
    value = props.get(key)
    if value is None:
        return None
    if type(value) not in (int, float):
        raise _Invalid
    return float(value)


def _optional_instant(props: Mapping[str, Any], key: str) -> datetime | None:
    value = props.get(key)
    if value is None:
        return None
    native = value.to_native() if isinstance(value, DateTime) else value
    if not isinstance(native, datetime):
        raise _Invalid
    return native


def _instant(props: Mapping[str, Any], key: str) -> datetime:
    value = _optional_instant(props, key)
    if value is None:
        raise _Invalid
    return value


def _clock(props: Mapping[str, Any], key: str) -> time | None:
    value = props.get(key)
    if value is None:
        return None
    native = value.to_native() if isinstance(value, Neo4jTime) else value
    if not isinstance(native, time):
        raise _Invalid
    return native


def _day(props: Mapping[str, Any], key: str) -> date:
    value = props.get(key)
    native = value.to_native() if isinstance(value, Date) else value
    if not isinstance(native, date) or isinstance(native, datetime):
        raise _Invalid
    return native


def _list(props: Mapping[str, Any], key: str) -> list[Any]:
    value = props.get(key)
    if not isinstance(value, list):
        raise _Invalid
    return value


def _code[E: StrEnum](props: Mapping[str, Any], key: str, kind: type[E]) -> E:
    return kind(_text(props, key))


def _optional_end_reason(props: Mapping[str, Any]) -> ProjectionEndReason | None:
    value = _optional_text(props, "endReason")
    return None if value is None else ProjectionEndReason(value)


def _row[T](props: Mapping[str, Any], projection: T) -> ProjectedRow[T]:
    ended_at = _optional_instant(props, "endedAt")
    end_reason = _optional_end_reason(props)
    if (ended_at is None) != (end_reason is None):
        raise _Invalid
    return ProjectedRow(
        source_tenant_id=_text(props, "sourceTenantId"),
        projection=projection,
        projected_at=_instant(props, "projectedAt"),
        grant_id=_text(props, "grantId"),
        ended_at=ended_at,
        end_reason=end_reason,
    )


def _location(props: Mapping[str, Any]) -> LocationProjection:
    return LocationProjection(
        location_name=_text(props, "locationName"),
        postal_district=_optional_text(props, "postalDistrict"),
        city=_optional_text(props, "city"),
        latitude=_optional_real(props, "latitude"),
        longitude=_optional_real(props, "longitude"),
    )


def _hour(props: Mapping[str, Any]) -> OpeningHourProjection:
    return OpeningHourProjection(
        position=_count(props, "position"),
        days=tuple(_list(props, "days")),
        all_day=_flag(props, "allDay"),
        start=_clock(props, "start"),
        end=_clock(props, "end"),
    )


def _service(
    props: Mapping[str, Any], location: Mapping[str, Any] | None, hours: Sequence[Mapping[str, Any]]
) -> ProjectedRow[ServiceProjection]:
    try:
        service = ServiceProjection(
            source_service_id=_text(props, "sourceServiceId"),
            source_version=_count(props, "sourceVersion"),
            service_name=_text(props, "serviceName"),
            category=_code(props, "categoryCode", ServiceCategory),
            active=_flag(props, "active"),
            source=_code(props, "source", DirectorySource),
            contact_label=_optional_text(props, "serviceContactLabel"),
            contact_phone=_optional_text(props, "serviceContactPhone"),
            location=None if location is None else _location(location),
            opening_hours=tuple(sorted((_hour(h) for h in hours), key=lambda h: h.position)),
        )
        return _row(props, service)
    except _Invalid, ValidationFailed, ValueError, TypeError, KeyError:
        raise ProjectionRecordInvalid(RECORD_MESSAGE) from None


def _capacity(props: Mapping[str, Any]) -> ProjectedRow[CapacityProjection]:
    try:
        capacity = CapacityProjection(
            source_service_id=_text(props, "sourceServiceId"),
            source_version=_count(props, "sourceVersion"),
            measure=_code(props, "measureCode", Measure),
            unit_label=_text(props, "unitLabel"),
            established_capacity=_count(props, "establishedCapacity"),
            can_exceed_established=_flag(props, "canExceedEstablished"),
            limited_level_percent=_count(props, "limitedLevelPercent"),
            cadence=_code(props, "cadenceCode", Cadence),
            suspended=_flag(props, "suspended"),
            report_id=_optional_text(props, "sourceReportId"),
            reported_at=_optional_instant(props, "effectiveDateTime"),
            value=_optional_count(props, "value"),
            confirmed_since=_count(props, "confirmedSince"),
            reply_window_minutes=_count(props, "replyWindowMinutes"),
            stale_warning_hours=_count(props, "staleWarningHours"),
            valid_until=_optional_instant(props, "validUntil"),
        )
        return _row(props, capacity)
    except _Invalid, ValidationFailed, ValueError, TypeError, KeyError:
        raise ProjectionRecordInvalid(RECORD_MESSAGE) from None


def _criteria(props: Mapping[str, Any]) -> ProjectedRow[CriteriaProjection]:
    try:
        criteria = CriteriaProjection(
            source_criteria_id=_text(props, "sourceCriteriaId"),
            source_service_id=_text(props, "sourceServiceId"),
            version=_count(props, "version"),
            age_min=_count(props, "ageMin"),
            age_max=_optional_count(props, "ageMax"),
            districts=tuple(_list(props, "postcodeDistricts")),
            accepts=tuple(NeedCategory(code) for code in _list(props, "acceptsNeedCodes")),
            excludes=tuple(NeedCategory(code) for code in _list(props, "excludesNeedCodes")),
            review_by=_day(props, "reviewBy"),
        )
        return _row(props, criteria)
    except _Invalid, ValidationFailed, ValueError, TypeError, KeyError:
        raise ProjectionRecordInvalid(RECORD_MESSAGE) from None


def _source_state(props: Mapping[str, Any]) -> SourceState:
    try:
        return SourceState(
            source_tenant_id=_text(props, "sourceTenantId"),
            kind=_code(props, "kind", GrantScope),
            status=_code(props, "status", SourceStatus),
            grant_id=_text(props, "grantId"),
            ended_at=_optional_instant(props, "endedAt"),
            end_reason=_optional_end_reason(props),
        )
    except _Invalid, ValueError, TypeError:
        raise ProjectionRecordInvalid(RECORD_MESSAGE) from None


def _checked_instant(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed("projected_at", _AWARE_MESSAGE)
    return value


def _kind(value: object) -> GrantScope:
    if type(value) is not GrantScope:
        raise ValidationFailed("kind", "is not a valid value for this field")
    return value


# The statements that mark a kind's rows ended, in the order they run.
_MARKS: Final[dict[GrantScope, tuple[str, ...]]] = {
    GrantScope.DIRECTORY: ("Q-PROJ-MARK-SERVICE", "Q-PROJ-MARK-LOCATION", "Q-PROJ-MARK-HOUR"),
    GrantScope.CAPACITY: ("Q-PROJ-MARK-CAPACITY",),
    GrantScope.CRITERIA: ("Q-PROJ-MARK-CRITERIA",),
}


class Neo4jProjectionRepository:
    """`ProjectionWriter` and `NetworkView` on the scoped transaction of a network unit of work."""

    def __init__(self, tx: Tx) -> None:
        self._tx = tx

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, _QUERIES[query_id], **params)

    # ---- sources

    async def open_source(self, source_tenant_id: str, kind: GrantScope, grant: GrantRef) -> None:
        await self._run(
            "Q-PROJ-SOURCE-OPEN",
            sourceTenant=source_tenant_id,
            kind=_kind(kind).value,
            grantId=grant.grant_id,
        )

    async def end_source(
        self,
        source_tenant_id: str,
        kind: GrantScope,
        *,
        at: datetime,
        reason: ProjectionEndReason,
    ) -> bool:
        rows = await self._run(
            "Q-PROJ-SOURCE-END",
            sourceTenant=source_tenant_id,
            kind=_kind(kind).value,
            endedAt=_checked_instant(at),
            endReason=ProjectionEndReason(reason).value,
        )
        return bool(rows)

    async def source(self, source_tenant_id: str, kind: GrantScope) -> SourceState | None:
        rows = await self._run(
            "Q-PROJ-SOURCE-GET", sourceTenant=source_tenant_id, kind=_kind(kind).value
        )
        return _source_state(rows[0]["source"]) if rows else None

    async def sources(self) -> Sequence[SourceState]:
        return [_source_state(row["source"]) for row in await self._run("Q-PROJ-SOURCES")]

    # ---- upserts

    @staticmethod
    def _stamps(grant: GrantRef, projected_at: datetime) -> dict[str, Any]:
        return {
            "projectedAt": _checked_instant(projected_at),
            "grantId": grant.grant_id,
            "grantVersion": grant.grant_version,
        }

    async def upsert_service(
        self,
        source_tenant_id: str,
        service: ServiceProjection,
        *,
        grant: GrantRef,
        projected_at: datetime,
    ) -> bool:
        rows = to_rows(service)
        stamps = self._stamps(grant, projected_at)
        written = await self._run(
            "Q-PROJ-SERVICE-UPSERT", sourceTenant=source_tenant_id, **rows[0].params, **stamps
        )
        if not written or not written[0]["written"]:
            return False
        key = {
            "sourceTenant": source_tenant_id,
            "sourceServiceId": service.source_service_id,
            "sourceVersion": service.source_version,
        }
        location = [row for row in rows if row.label == "ProjectedLocation"]
        if location:
            await self._run("Q-PROJ-LOCATION-UPSERT", **key, **location[0].params, **stamps)
        else:
            await self._run("Q-PROJ-LOCATION-END", **key, endedAt=projected_at, endReason=_REPLACED)
        hours = [row for row in rows if row.label == "ProjectedOpeningHour"]
        for hour in hours:
            await self._run("Q-PROJ-HOUR-UPSERT", **key, **hour.params, **stamps)
        await self._run(
            "Q-PROJ-HOURS-END",
            **key,
            fromPosition=len(hours),
            endedAt=projected_at,
            endReason=_REPLACED,
        )
        return True

    async def upsert_capacity(
        self,
        source_tenant_id: str,
        capacity: CapacityProjection,
        *,
        grant: GrantRef,
        projected_at: datetime,
    ) -> bool:
        stamps = self._stamps(grant, projected_at)
        rows = await self._run(
            "Q-PROJ-CAPACITY-UPSERT",
            sourceTenant=source_tenant_id,
            **to_rows(capacity)[0].params,
            **stamps,
        )
        return bool(rows and rows[0]["written"])

    async def upsert_criteria(
        self,
        source_tenant_id: str,
        criteria: CriteriaProjection,
        *,
        grant: GrantRef,
        projected_at: datetime,
    ) -> bool:
        stamps = self._stamps(grant, projected_at)
        rows = await self._run(
            "Q-PROJ-CRITERIA-UPSERT",
            sourceTenant=source_tenant_id,
            **to_rows(criteria)[0].params,
            **stamps,
        )
        return bool(rows and rows[0]["written"])

    async def mark_ended(
        self,
        source_tenant_id: str,
        kind: GrantScope,
        *,
        at: datetime,
        reason: ProjectionEndReason,
    ) -> int:
        statements = _MARKS[_kind(kind)]
        total = 0
        for query_id in statements:
            rows = await self._run(
                query_id,
                sourceTenant=source_tenant_id,
                endedAt=_checked_instant(at),
                endReason=ProjectionEndReason(reason).value,
            )
            total += int(rows[0]["marked"])
        return total

    # ---- reads

    async def services(
        self, *, live_only: bool = True
    ) -> Sequence[ProjectedRow[ServiceProjection]]:
        rows = await self._run("Q-NETVIEW-SERVICES", liveOnly=live_only)
        return [_service(row["service"], row["location"], row["hours"]) for row in rows]

    async def capacities(
        self, *, live_only: bool = True
    ) -> Sequence[ProjectedRow[CapacityProjection]]:
        rows = await self._run("Q-NETVIEW-CAPACITIES", liveOnly=live_only)
        return [_capacity(row["capacity"]) for row in rows]

    async def criteria(
        self, *, live_only: bool = True
    ) -> Sequence[ProjectedRow[CriteriaProjection]]:
        rows = await self._run("Q-NETVIEW-CRITERIA", liveOnly=live_only)
        return [_criteria(row["criteria"]) for row in rows]
