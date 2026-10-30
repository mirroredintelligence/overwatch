"""Service profiles on Neo4j: ServiceProfile <-> FHIR HealthcareService (P01).

The mapping is pure. The repository saves and loads the FHIR resource through the G05 resource
store, so the graph holds the decomposed properties and relationships and no json (DEC-001).
`suspended` is not a service property: service flags hold it (P14), so save ignores it and get
returns False.

Also here: the codeable-concept helpers shared with capacity_repository.py. A code is always read
from the enum class's own code system, never from the bare value (lesson L3).
"""

from datetime import time
from enum import StrEnum
from typing import Any, Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.extensions import EXTENSIONS, by_short_name
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_scenarios import SCENARIOS
from diucs.domain.codes import (
    CODE_SYSTEM_NAMES,
    Cadence,
    Channel,
    Coding,
    Measure,
    ServiceCategory,
    code_system_url,
    coding_for,
    parse_code,
)
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.service import AvailableTime, ServiceProfile

_DAY_CODES: Final = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_NUMBERS: Final = {code: number for number, code in enumerate(_DAY_CODES)}
_TIME_FORMAT: Final = "%H:%M:%S"
_RESOURCE_TYPE: Final = "HealthcareService"

_LIST_ACTIVE: Final = NamedQuery(
    id="Q-SVC-LIST-ACTIVE",
    cypher="MATCH (s:HealthcareService {active: true, tenantId: $tenant}) "
    "RETURN s.id AS id ORDER BY s.name",
    mode="read",
    scenario=SCENARIOS["Q-SVC-LIST-ACTIVE"],
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


_register(_LIST_ACTIVE)


def codeable_to_fhir(member: StrEnum) -> dict[str, Any]:
    """A CodeableConcept with one coding for a local code (the coding's system comes from its enum
    class)."""
    coding: Coding = coding_for(member)
    return {"coding": [{"system": coding.system, "code": coding.code, "display": coding.display}]}


def codeable_from_fhir[E: StrEnum](concept: Any, enum_cls: type[E], field: str) -> E:
    """The enum member for the one coding of a CodeableConcept. The coding must be from this enum
    class's code system, or the value is refused. A list of one CodeableConcept is read as that
    concept: FHIR's HealthcareService.category is a list, and registration writes it so (U27), while
    the profile writer keeps the single form."""
    if isinstance(concept, list) and len(concept) == 1:
        concept = concept[0]
    codings = concept.get("coding") if isinstance(concept, dict) else None
    if not isinstance(codings, list) or len(codings) != 1 or not isinstance(codings[0], dict):
        raise ValidationFailed(field, "needs exactly one coding")
    coding = codings[0]
    expected = code_system_url(CODE_SYSTEM_NAMES[enum_cls])
    if coding.get("system") != expected:
        raise ValidationFailed(field, "not from the expected code system")
    code = coding.get("code")
    if not isinstance(code, str):
        raise ValidationFailed(field, "code must be text")
    return parse_code(enum_cls, code)


def _extension(short_name: str, value: Any) -> dict[str, Any]:
    defn = by_short_name(short_name)
    if defn is None:  # a programming error: the registry always holds these names
        raise LookupError(short_name)
    return {"url": defn.url, defn.value_key: value}


def _extension_values(resource: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for entry in resource.get("extension", []):
        defn = EXTENSIONS.get(entry.get("url"))
        if defn is None:
            raise ValidationFailed("extension", "not a registered extension")
        values[defn.short_name] = entry[defn.value_key]
    return values


def _required(values: dict[str, Any], name: str) -> Any:
    if name not in values:
        raise ValidationFailed(name, "required")
    return values[name]


def _window_to_fhir(window: AvailableTime) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "daysOfWeek": [_DAY_CODES[day] for day in sorted(window.days)],
        "allDay": window.all_day,
    }
    if window.start is not None and window.end is not None:
        entry["availableStartTime"] = window.start.strftime(_TIME_FORMAT)
        entry["availableEndTime"] = window.end.strftime(_TIME_FORMAT)
    return entry


def _window_from_fhir(entry: dict[str, Any]) -> AvailableTime:
    codes = _required(entry, "daysOfWeek")
    if not isinstance(codes, list):
        raise ValidationFailed("daysOfWeek", "must be a list of day codes")
    try:
        days = frozenset(_DAY_NUMBERS[code] for code in codes)
    except KeyError, TypeError:
        raise ValidationFailed("daysOfWeek", "not a day code") from None
    start = entry.get("availableStartTime")
    end = entry.get("availableEndTime")
    return AvailableTime(
        days=days,
        all_day=entry.get("allDay", False),
        start=time.fromisoformat(start) if start is not None else None,
        end=time.fromisoformat(end) if end is not None else None,
    )


def profile_to_fhir(profile: ServiceProfile) -> dict[str, Any]:
    """The HealthcareService for a profile. No meta: the store sets it."""
    resource: dict[str, Any] = {
        "resourceType": _RESOURCE_TYPE,
        "id": profile.id,
        "active": profile.active,
        "name": profile.name,
        "category": codeable_to_fhir(profile.category),
        "availableTime": [_window_to_fhir(window) for window in profile.available_times],
        "extension": [
            _extension("establishedCapacity", profile.established_capacity),
            _extension("canExceedEstablished", profile.can_exceed_established),
            _extension("usualRangeMin", profile.usual_range[0]),
            _extension("usualRangeMax", profile.usual_range[1]),
            _extension("reportCadence", profile.cadence.value),
            _extension("limitedLevelPercent", profile.limited_level_percent),
            _extension("measure", profile.measure.value),
            _extension("unitLabel", profile.unit_label),
            _extension("channel", profile.channel.value),
        ],
    }
    if profile.comment:
        resource["comment"] = profile.comment
    return resource


def profile_from_fhir(resource: dict[str, Any]) -> ServiceProfile:
    """The profile for a HealthcareService. Refuses a value it does not recognise."""
    values = _extension_values(resource)
    windows = resource.get("availableTime", [])
    if not isinstance(windows, list):
        raise ValidationFailed("availableTime", "must be a list")
    usual_min = _required(values, "usualRangeMin")
    usual_max = _required(values, "usualRangeMax")
    return ServiceProfile(
        id=_required(resource, "id"),
        name=_required(resource, "name"),
        category=codeable_from_fhir(_required(resource, "category"), ServiceCategory, "category"),
        measure=parse_code(Measure, _required(values, "measure")),
        unit_label=_required(values, "unitLabel"),
        established_capacity=_required(values, "establishedCapacity"),
        can_exceed_established=_required(values, "canExceedEstablished"),
        usual_range=(usual_min, usual_max),
        cadence=parse_code(Cadence, _required(values, "reportCadence")),
        available_times=tuple(_window_from_fhir(entry) for entry in windows),
        channel=parse_code(Channel, _required(values, "channel")),
        limited_level_percent=_required(values, "limitedLevelPercent"),
        active=_required(resource, "active"),
        suspended=False,
        comment=resource.get("comment", ""),
    )


def _references(resource: dict[str, Any], element: str) -> list[str]:
    """The reference strings of a single or a list element of a resource, in order."""
    value = resource.get(element)
    entries = value if isinstance(value, list) else [] if value is None else [value]
    return [
        str(entry["reference"])
        for entry in entries
        if isinstance(entry, dict) and "reference" in entry
    ]


def _split(reference: str) -> tuple[str, str]:
    """`Type/id` as the type and the id; anything else is NotFound (never a guess)."""
    kind, sep, identifier = reference.partition("/")
    if not sep or not kind or not identifier:
        raise NotFound("a reference of the service cannot be followed")
    return kind, identifier


class Neo4jServiceRepository:
    """Services as HealthcareService resources. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def get(self, service_id: str) -> ServiceProfile | None:
        resource = await self._store.get(_RESOURCE_TYPE, service_id)
        return None if resource is None else profile_from_fhir(resource)

    async def get_versioned(self, service_id: str) -> tuple[ServiceProfile, int] | None:
        resource = await self._store.get(_RESOURCE_TYPE, service_id)
        if resource is None:
            return None
        return profile_from_fhir(resource), int(resource["meta"]["versionId"])

    async def list_active(self) -> list[ServiceProfile]:
        rows = await run_query(self._tx, REGISTRY.get("Q-SVC-LIST-ACTIVE"))
        profiles: list[ServiceProfile] = []
        for row in rows:
            profile = await self.get(str(row["id"]))
            if profile is not None:
                profiles.append(profile)
        return profiles

    async def set_active(self, service_id: str) -> None:
        """Flip the three activation flags on the stored resources, one new version each. The rest
        of each resource is written back as it was read, so providedBy, location and coverage are
        not lost (U29; known issue U24/U27: save() rewrites the whole service from the profile)."""
        service = await self._store.get(_RESOURCE_TYPE, service_id)
        if service is None:
            raise NotFound("no service with this id")
        service["active"] = True
        await self._put_with_current(service)
        for reference in _references(service, "location"):
            location = await self._store.get(*_split(reference))
            if location is None:
                raise NotFound("a location of the service is missing")
            location["status"] = "active"
            await self._put_with_current(location)
        for reference in _references(service, "providedBy"):
            organisation = await self._store.get(*_split(reference))
            if organisation is None:
                raise NotFound("the organisation of the service is missing")
            organisation["active"] = True
            await self._put_with_current(organisation)

    async def _put_with_current(self, resource: dict[str, Any]) -> None:
        """Write the resource as a new version. The store sets `meta` itself and refuses a resource
        that carries it, so the stored meta is left out of the write."""
        current = await self._store.get(resource["resourceType"], resource["id"])
        expected = None if current is None else str(current["meta"]["versionId"])
        body = {key: value for key, value in resource.items() if key != "meta"}
        await self._store.put(body, expected)

    async def save(self, profile: ServiceProfile) -> None:
        # Replace the stored version, or create it. The store checks the version after its lock,
        # so a concurrent change between this read and the write is a Conflict, never a silent
        # overwrite (DEC-053 item 4).
        current = await self._store.get(_RESOURCE_TYPE, profile.id)
        expected = None if current is None else str(current["meta"]["versionId"])
        await self._store.put(profile_to_fhir(profile), expected)
