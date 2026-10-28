"""Service criteria on Neo4j: ServiceCriteria <-> FHIR Basic with the ServiceCriteria profile (P04).

The mapping is pure (criteria_to_fhir and criteria_from_fhir). The repository writes each version
as a Basic through the G05 resource store (DEC-001: no json), then sets what the generic mapper
cannot hold, in the same transaction:

- the ServiceCriteria label (the profile), set after the put (DEC-064 item 1 pattern);
- CURRENT_CRITERIA from the service, moved when a current version is written. A service put
  deletes the service's outgoing relationships (DEC-053 item 6), so the link is written again on
  every change here. Reads do not depend on it: `current_for_service` finds the current version by
  its status, so a link that a service write removed cannot make a current version invisible.

Writes take the service's write lock first (a SET of its id to itself, lesson L73), then check,
then write. Every refusal is decided before the first change. The lock is what makes two racing
writers serialise (lesson L90; DEC-073 item 3 pattern), so a second current version or a second
version number is refused rather than stored.

Decisions: DEC-076 (the choices the prompt leaves open, and the local-relationship rule).
"""

from collections.abc import Sequence
from datetime import date
from typing import Any, Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import (
    codeable_from_fhir,
    codeable_to_fhir,
)
from diucs.domain.codes import CriteriaStatus, NeedCategory, parse_code
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.criteria import ServiceCriteria

_BASIC: Final = "Basic"
_SERVICE: Final = "HealthcareService"
_PRACTITIONER_ROLE: Final = "PractitionerRole"
_RESOURCE_TYPE: Final = _BASIC

# The elements a criteria Basic holds. Anything else is refused, never dropped (DEC-053).
_KEYS: Final = frozenset(
    {
        "resourceType",
        "id",
        "meta",
        "subject",
        "author",
        "version",
        "status",
        "ageMin",
        "ageMax",
        "reviewBy",
        "postcodeDistricts",
        "acceptsNeed",
        "excludesNeed",
        "changeReason",
        "supersedes",
    }
)

_LOCK_SERVICE: Final = NamedQuery(
    id="Q-CRIT-LOCK-SERVICE",
    cypher=(
        "MATCH (s:HealthcareService {id: $serviceId}) SET s.id = s.id RETURN count(s) AS locked"
    ),
    mode="write",
)
_LABEL: Final = NamedQuery(
    id="Q-CRIT-LABEL",
    cypher="MATCH (c:Basic {key: $key}) SET c:ServiceCriteria RETURN count(c) AS labelled",
    mode="write",
)
_SUBJECT: Final = NamedQuery(
    id="Q-CRIT-SUBJECT",
    cypher=(
        "MATCH (c:ServiceCriteria {key: $key})-[:SUBJECT]->(s:HealthcareService) "
        "RETURN s.id AS serviceId"
    ),
    mode="read",
)
_CURRENT: Final = NamedQuery(
    id="Q-CRIT-CURRENT",
    cypher=(
        "MATCH (c:ServiceCriteria {status: 'current'})"
        "-[:SUBJECT]->(:HealthcareService {id: $serviceId}) "
        "RETURN c.id AS id ORDER BY c.id"
    ),
    mode="read",
)
_CURRENT_FOR: Final = NamedQuery(
    id="Q-CRIT-CURRENT-FOR",
    cypher=(
        "MATCH (c:ServiceCriteria {status: 'current'})-[:SUBJECT]->(s:HealthcareService) "
        "WHERE s.id IN $serviceIds RETURN s.id AS serviceId, c.id AS id ORDER BY s.id, c.id"
    ),
    mode="read",
)
_VERSIONS: Final = NamedQuery(
    id="Q-CRIT-VERSIONS",
    cypher=(
        "MATCH (c:ServiceCriteria)-[:SUBJECT]->(:HealthcareService {id: $serviceId}) "
        "RETURN c.id AS id, c.version AS version ORDER BY c.version DESC, c.id"
    ),
    mode="read",
)
_SET_CURRENT: Final = NamedQuery(
    id="Q-CRIT-SET-CURRENT",
    cypher=(
        "MATCH (s:HealthcareService {id: $serviceId}) "
        "OPTIONAL MATCH (s)-[old:CURRENT_CRITERIA]->() "
        "DELETE old "
        "WITH DISTINCT s "
        "MATCH (c:Basic {key: $key}) "
        "MERGE (s)-[:CURRENT_CRITERIA]->(c) "
        "RETURN count(c) AS linked"
    ),
    mode="write",
)
_CLEAR_CURRENT: Final = NamedQuery(
    id="Q-CRIT-CLEAR-CURRENT",
    cypher=(
        "MATCH (:HealthcareService {id: $serviceId})"
        "-[link:CURRENT_CRITERIA]->(c:Basic {key: $key}) "
        "DELETE link RETURN count(link) AS cleared"
    ),
    mode="write",
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in (
    _LOCK_SERVICE,
    _LABEL,
    _SUBJECT,
    _CURRENT,
    _CURRENT_FOR,
    _VERSIONS,
    _SET_CURRENT,
    _CLEAR_CURRENT,
):
    _register(_query)


def _key(criteria_id: str) -> str:
    return f"{_RESOURCE_TYPE}/{criteria_id}"


def _reference(resource: dict[str, Any], element: str, target: str) -> str:
    """The id a reference points at, refusing any reference to another type."""
    ref = resource.get(element)
    text = ref.get("reference") if isinstance(ref, dict) else None
    prefix = f"{target}/"
    if not isinstance(text, str) or not text.startswith(prefix) or len(text) == len(prefix):
        raise ValidationFailed(element, f"must refer to a {target}")
    return text[len(prefix) :]


def _text(resource: dict[str, Any], element: str) -> str:
    value = resource.get(element)
    if not isinstance(value, str) or not value:
        raise ValidationFailed(element, "must be text")
    return value


def _int(resource: dict[str, Any], element: str, minimum: int) -> int:
    value = resource.get(element)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationFailed(element, f"must be a whole number of at least {minimum}")
    return value


def _status(resource: dict[str, Any]) -> CriteriaStatus:
    value = resource.get("status")
    if not isinstance(value, str):
        raise ValidationFailed("status", "must be a criteria status")
    try:
        return parse_code(CriteriaStatus, value)
    except ValidationFailed:
        raise ValidationFailed("status", "not a known criteria status code") from None


def _review_by(resource: dict[str, Any]) -> date:
    value = resource.get("reviewBy")
    if not isinstance(value, str):
        raise ValidationFailed("reviewBy", "must be a calendar date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationFailed("reviewBy", "must be a calendar date, YYYY-MM-DD") from None


def _needs(resource: dict[str, Any], element: str) -> frozenset[NeedCategory]:
    concepts = resource.get(element, [])
    if not isinstance(concepts, list):
        raise ValidationFailed(element, "must be a list of needs")
    return frozenset(codeable_from_fhir(concept, NeedCategory, element) for concept in concepts)


def criteria_to_fhir(criteria: ServiceCriteria) -> dict[str, Any]:
    """The Basic for a criteria version. Empty lists and absent values are left out: the store
    refuses an empty list and does not keep a null (lesson L74). No meta: the store sets it."""
    resource: dict[str, Any] = {
        "resourceType": _BASIC,
        "id": criteria.id,
        "subject": {"reference": f"{_SERVICE}/{criteria.service_id}"},
        "author": {"reference": f"{_PRACTITIONER_ROLE}/{criteria.owner_role_id}"},
        "version": criteria.version,
        "status": criteria.status.value,
        "ageMin": criteria.age_min,
        "reviewBy": criteria.review_by.isoformat(),
    }
    if criteria.age_max is not None:
        resource["ageMax"] = criteria.age_max
    if criteria.districts:
        resource["postcodeDistricts"] = sorted(criteria.districts)
    if criteria.accepts:
        resource["acceptsNeed"] = [codeable_to_fhir(need) for need in sorted(criteria.accepts)]
    if criteria.excludes:
        resource["excludesNeed"] = [codeable_to_fhir(need) for need in sorted(criteria.excludes)]
    if criteria.change_reason:
        resource["changeReason"] = criteria.change_reason
    if criteria.supersedes_id is not None:
        resource["supersedes"] = {"reference": f"{_BASIC}/{criteria.supersedes_id}"}
    return resource


def criteria_from_fhir(resource: dict[str, Any]) -> ServiceCriteria:
    """The criteria version for a Basic. Refuses an element it does not hold and a value it does
    not recognise, naming the field only."""
    unknown = set(resource) - _KEYS
    if unknown:
        raise ValidationFailed("resource", "holds an element the criteria profile does not have")
    supersedes = resource.get("supersedes")
    districts = resource.get("postcodeDistricts", [])
    if not isinstance(districts, list):
        raise ValidationFailed("postcodeDistricts", "must be a list of district codes")
    age_max = resource.get("ageMax")
    if age_max is not None:
        age_max = _int(resource, "ageMax", minimum=0)
    return ServiceCriteria(
        id=_text(resource, "id"),
        service_id=_reference(resource, "subject", _SERVICE),
        version=_int(resource, "version", minimum=1),
        status=_status(resource),
        age_min=_int(resource, "ageMin", minimum=0),
        age_max=age_max,
        districts=frozenset(districts),
        accepts=_needs(resource, "acceptsNeed"),
        excludes=_needs(resource, "excludesNeed"),
        review_by=_review_by(resource),
        owner_role_id=_reference(resource, "author", _PRACTITIONER_ROLE),
        change_reason=resource.get("changeReason", ""),
        supersedes_id=(None if supersedes is None else _reference(resource, "supersedes", _BASIC)),
    )


class Neo4jCriteriaRepository:
    """Criteria versions as Basic resources. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def current_for_service(self, service_id: str) -> ServiceCriteria | None:
        rows = await run_query(self._tx, REGISTRY.get("Q-CRIT-CURRENT"), serviceId=service_id)
        if len(rows) > 1:
            raise Conflict("a service has more than one current criteria version")
        if not rows:
            return None
        return await self.get(str(rows[0]["id"]))

    async def current_for_services(self, service_ids: Sequence[str]) -> dict[str, ServiceCriteria]:
        rows = await run_query(
            self._tx, REGISTRY.get("Q-CRIT-CURRENT-FOR"), serviceIds=list(service_ids)
        )
        ids: dict[str, str] = {}
        for row in rows:
            service = str(row["serviceId"])
            if service in ids:
                raise Conflict("a service has more than one current criteria version")
            ids[service] = str(row["id"])
        found: dict[str, ServiceCriteria] = {}
        for service, criteria_id in ids.items():
            criteria = await self.get(criteria_id)
            if criteria is not None:
                found[service] = criteria
        return found

    async def get(self, criteria_id: str) -> ServiceCriteria | None:
        if not await self._is_criteria(criteria_id):
            return None
        resource = await self._store.get(_RESOURCE_TYPE, criteria_id)
        return None if resource is None else criteria_from_fhir(resource)

    async def add(self, criteria: ServiceCriteria) -> None:
        await self._lock_service(criteria.service_id)
        if await self._store.exists(_RESOURCE_TYPE, criteria.id):
            raise Conflict("a criteria version with this id already exists")
        await self._check_slot(criteria)
        await self._store.put(criteria_to_fhir(criteria), None)
        await self._finish(criteria)

    async def save(self, criteria: ServiceCriteria) -> None:
        stored = await self.get(criteria.id)
        if stored is None:
            raise NotFound("criteria version")
        if (stored.service_id, stored.version, stored.supersedes_id) != (
            criteria.service_id,
            criteria.version,
            criteria.supersedes_id,
        ):
            raise ValidationFailed("criteria", "service, version and supersedes are fixed")
        await self._lock_service(criteria.service_id)
        current = await self._store.get(_RESOURCE_TYPE, criteria.id)
        if current is None:
            raise NotFound("criteria version")
        await self._check_slot(criteria)
        await self._store.put(criteria_to_fhir(criteria), str(current["meta"]["versionId"]))
        await self._finish(criteria)

    async def history(self, service_id: str) -> list[ServiceCriteria]:
        rows = await run_query(self._tx, REGISTRY.get("Q-CRIT-VERSIONS"), serviceId=service_id)
        found: list[ServiceCriteria] = []
        for row in rows:
            criteria = await self.get(str(row["id"]))
            if criteria is not None:
                found.append(criteria)
        return found

    async def _is_criteria(self, criteria_id: str) -> bool:
        rows = await run_query(self._tx, REGISTRY.get("Q-CRIT-SUBJECT"), key=_key(criteria_id))
        return bool(rows)

    async def _lock_service(self, service_id: str) -> None:
        rows = await run_query(self._tx, REGISTRY.get("Q-CRIT-LOCK-SERVICE"), serviceId=service_id)
        if not rows or int(rows[0]["locked"]) == 0:
            raise NotFound("service")

    async def _check_slot(self, criteria: ServiceCriteria) -> None:
        """Refuse before anything is written: a version number used by another version of the
        service, a second current version, or a superseded version that is missing or belongs to
        another service."""
        for row in await run_query(
            self._tx, REGISTRY.get("Q-CRIT-VERSIONS"), serviceId=criteria.service_id
        ):
            if str(row["id"]) != criteria.id and int(row["version"]) == criteria.version:
                raise Conflict("this version number is already used for the service")
        if criteria.status is CriteriaStatus.CURRENT:
            currents = await run_query(
                self._tx, REGISTRY.get("Q-CRIT-CURRENT"), serviceId=criteria.service_id
            )
            if any(str(row["id"]) != criteria.id for row in currents):
                raise Conflict("another criteria version is already current")
        if criteria.supersedes_id is not None:
            subject = await run_query(
                self._tx, REGISTRY.get("Q-CRIT-SUBJECT"), key=_key(criteria.supersedes_id)
            )
            if not subject:
                raise NotFound("superseded criteria version")
            if str(subject[0]["serviceId"]) != criteria.service_id:
                raise ValidationFailed("supersedes", "belongs to another service")

    async def _finish(self, criteria: ServiceCriteria) -> None:
        """The profile label, then the service's link: moved when the version is current, removed
        when it is not, so the link never names a version that is no longer current."""
        await run_query(self._tx, REGISTRY.get("Q-CRIT-LABEL"), key=_key(criteria.id))
        if criteria.status is CriteriaStatus.CURRENT:
            await run_query(
                self._tx,
                REGISTRY.get("Q-CRIT-SET-CURRENT"),
                serviceId=criteria.service_id,
                key=_key(criteria.id),
            )
        else:
            await run_query(
                self._tx,
                REGISTRY.get("Q-CRIT-CLEAR-CURRENT"),
                serviceId=criteria.service_id,
                key=_key(criteria.id),
            )
