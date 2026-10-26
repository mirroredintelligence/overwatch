"""People on Neo4j: Practitioner and PractitionerRole <-> FHIR (P03, DEC-064).

The mapping is pure (practitioner_to_fhir, role_to_fhir and their from_fhir). The repository stores
the resources through the G05 store, so the graph holds the decomposed properties and relationships
and no json (DEC-001).

Three things are not FHIR and are written beside the resource, in the same transaction:
- Practitioner.phoneHash and Practitioner.emailDomain are node properties, set after the put and
  taken out of the FHIR form when read. The phone number is never stored. A missing hash is no
  property at all (lesson L74), so an absent value removes the key.
- CHANNEL: a role's text, email or push channel, as a relationship to a Concept.
- COVERED_BY {until}: a role covered by another practitioner until an instant.
The store clears a resource's outgoing relationships on every put (Q-RES-CLEAR-ROOT-RELS), except
HAS_VERSION, which links the resource to its version snapshots and is kept. So a cover removed by
a save is gone with no extra step. When a resource is read, resource_store._load skips a
relationship with no fhirPath only if its type is CHANNEL or COVERED_BY (LOCAL_RELATIONSHIP_TYPES,
DEC-065 item 5); any other relationship without a fhirPath is kept, and reading it raises KeyError.

Filters, by function:
- services_for_phone_hash: the cover filter is in Cypher (Q-PHONE-SERVICES-HELD excludes a role
  covered past `now`; Q-PHONE-SERVICES-AT takes the roles covered until after `now`). The reporter
  code and the period (`is_in_effect`) are applied in Python after each role is loaded.
- reporter_roles_for_service: no cover filter. It returns covered roles as stored, and the caller
  resolves the holder with role_holder. The reporter code and the period are applied in Python.
- roles_for_practitioner: active roles only, in Cypher; no code or period filter.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.extensions import EXTENSIONS, by_short_name
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.service_repository import (
    codeable_from_fhir,
    codeable_to_fhir,
)
from diucs.domain.codes import Channel, PractitionerRoleCode, coding_for, parse_code
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.people import (
    REPORTER_ROLE_CODES,
    Practitioner,
    PractitionerRole,
    check_aware,
    check_phone_hash,
    is_in_effect,
)

_PRACTITIONER: Final = "Practitioner"
_ROLE: Final = "PractitionerRole"
_SERVICE: Final = "HealthcareService"
_PHONE_HASH: Final = "phoneHash"
_EMAIL_DOMAIN: Final = "emailDomain"
_CONCEPT_PREFIX: Final = "Concept|"  # the mapper's key for a shared Concept (mapper.py)
_KEY_SEPARATOR: Final = "|"


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


_PERSON_PHONE_FIND: Final = NamedQuery(
    id="Q-PERSON-PHONE-FIND",
    cypher=(
        "MATCH (p:Practitioner {phoneHash: $hash, active: true}) RETURN p.id AS id ORDER BY p.id"
    ),
    mode="read",
)
_PERSON_ROLES_OF: Final = NamedQuery(
    id="Q-PERSON-ROLES-OF",
    cypher=(
        "MATCH (r:PractitionerRole {active: true})-[:PRACTITIONER]->(:Practitioner {key: $key}) "
        "RETURN r.id AS id ORDER BY r.id"
    ),
    mode="read",
)
# Query #3 (fhir-data-model): the roles a phone holds and is not covered out of at $now.
_PHONE_SERVICES_HELD: Final = NamedQuery(
    id="Q-PHONE-SERVICES-HELD",
    cypher=(
        "MATCH (p:Practitioner {phoneHash: $hash, active: true})"
        "<-[:PRACTITIONER]-(r:PractitionerRole {active: true})"
        "-[:HEALTHCARE_SERVICE]->(s:HealthcareService) "
        "WHERE NOT EXISTS { MATCH (r)-[c:COVERED_BY]->(:Practitioner) WHERE c.until > $now } "
        "RETURN r.id AS roleId, s.name AS name"
    ),
    mode="read",
)
# Query #3 extended with cover (Q-PHONE-SERVICES-AT): the roles this phone covers until after $now.
_PHONE_SERVICES_AT: Final = NamedQuery(
    id="Q-PHONE-SERVICES-AT",
    cypher=(
        "MATCH (p:Practitioner {phoneHash: $hash, active: true})"
        "<-[c:COVERED_BY]-(r:PractitionerRole {active: true})"
        "-[:HEALTHCARE_SERVICE]->(s:HealthcareService) "
        "WHERE c.until > $now "
        "RETURN r.id AS roleId, s.name AS name"
    ),
    mode="read",
)
_SERVICE_ROLES: Final = NamedQuery(
    id="Q-SERVICE-REPORTER-ROLES",
    cypher=(
        "MATCH (r:PractitionerRole {active: true})-[:HEALTHCARE_SERVICE]->"
        "(:HealthcareService {key: $key}) RETURN r.id AS id ORDER BY r.id"
    ),
    mode="read",
)
_PERSON_SET_PROPS: Final = NamedQuery(
    id="Q-PERSON-SET-PROPS",
    cypher=(
        "MATCH (p:Practitioner {key: $key}) "
        "SET p.phoneHash = $phoneHash, p.emailDomain = $emailDomain "
        "RETURN count(p) AS set"
    ),
    mode="write",
)
_ROLE_CHANNEL: Final = NamedQuery(
    id="Q-ROLE-CHANNEL",
    cypher=(
        "MERGE (c:Concept {system: $system, code: $code}) "
        "ON CREATE SET c.key = $conceptKey, c.display = $display "
        "WITH c MATCH (r:PractitionerRole {key: $roleKey}) "
        "CREATE (r)-[:CHANNEL]->(c) RETURN count(r) AS linked"
    ),
    mode="write",
)
_ROLE_COVER: Final = NamedQuery(
    id="Q-ROLE-COVER",
    cypher=(
        "MATCH (r:PractitionerRole {key: $roleKey}) MATCH (p:Practitioner {key: $coverKey}) "
        "CREATE (r)-[:COVERED_BY {until: $until}]->(p) RETURN count(*) AS linked"
    ),
    mode="write",
)
for _query in (
    _PERSON_PHONE_FIND,
    _PERSON_ROLES_OF,
    _PHONE_SERVICES_HELD,
    _PHONE_SERVICES_AT,
    _SERVICE_ROLES,
    _PERSON_SET_PROPS,
    _ROLE_CHANNEL,
    _ROLE_COVER,
):
    _register(_query)


def _instant_text(value: datetime) -> str:
    """UTC with Z. Fractions keep only their significant digits, so the store reads back the same
    text (DEC-053 item 2)."""
    utc = value.astimezone(UTC)
    text = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        text += f".{utc.microsecond:06d}".rstrip("0")
    return f"{text}Z"


def _instant(field: str, text: Any) -> datetime:
    if not isinstance(text, str):
        raise ValidationFailed(field, "must be a FHIR datetime")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationFailed(field, "not a FHIR datetime") from None
    if parsed.tzinfo is None:
        raise ValidationFailed(field, "must carry a zone")
    return parsed.astimezone(UTC)


def _required(resource: dict[str, Any], name: str) -> Any:
    if name not in resource:
        raise ValidationFailed(name, "required")
    return resource[name]


def _reference_id(reference: Any, resource_type: str, field: str) -> str:
    text = reference.get("reference") if isinstance(reference, dict) else None
    prefix = f"{resource_type}/"
    if not isinstance(text, str) or not text.startswith(prefix) or len(text) == len(prefix):
        raise ValidationFailed(field, f"must reference a {resource_type}")
    return text[len(prefix) :]


def _extension(short_name: str, value: str) -> dict[str, Any]:
    defn = by_short_name(short_name)
    if defn is None:  # a programming error: the registry holds these names
        raise LookupError(short_name)
    return {"url": defn.url, defn.value_key: value}


def _extension_values(resource: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for entry in resource.get("extension", []):
        defn = EXTENSIONS.get(entry.get("url"))
        if defn is None:
            raise ValidationFailed("extension", "not a registered extension")
        value = entry.get(defn.value_key)
        if value is None:
            raise ValidationFailed(defn.short_name, "missing its value")
        values[defn.short_name] = value
    return values


def practitioner_to_fhir(practitioner: Practitioner) -> dict[str, Any]:
    """The FHIR Practitioner. No telecom, and no phone hash or email domain: those are graph
    properties the repository writes beside it."""
    return {
        "resourceType": _PRACTITIONER,
        "id": practitioner.id,
        "active": practitioner.active,
        "name": [{"text": practitioner.display_name}],
    }


def practitioner_from_fhir(
    resource: dict[str, Any], phone_hash: str | None = None, email_domain: str | None = None
) -> Practitioner:
    """The practitioner for a FHIR Practitioner and its graph properties. Refuses a name it cannot
    read as exactly one text."""
    names = _required(resource, "name")
    if not isinstance(names, list) or len(names) != 1 or not isinstance(names[0], dict):
        raise ValidationFailed("name", "needs exactly one name")
    text = names[0].get("text")
    if not isinstance(text, str):
        raise ValidationFailed("name", "needs text")
    active = _required(resource, "active")
    if not isinstance(active, bool):
        raise ValidationFailed("active", "must be a boolean")
    return Practitioner(
        id=str(_required(resource, "id")),
        active=active,
        display_name=text,
        phone_hash=phone_hash,
        email_domain=email_domain,
    )


def role_to_fhir(role: PractitionerRole) -> dict[str, Any]:
    """The FHIR PractitionerRole. Its channel and cover are extensions, so the FHIR form round
    trips; the graph also carries them as CHANNEL and COVERED_BY (DEC-064)."""
    period: dict[str, Any] = {"start": _instant_text(role.period_start)}
    if role.period_end is not None:
        period["end"] = _instant_text(role.period_end)
    resource: dict[str, Any] = {
        "resourceType": _ROLE,
        "id": role.id,
        "active": role.active,
        "practitioner": {"reference": f"{_PRACTITIONER}/{role.practitioner_id}"},
        "code": [codeable_to_fhir(role.code)],
        "period": period,
    }
    if role.service_id is not None:
        resource["healthcareService"] = [{"reference": f"{_SERVICE}/{role.service_id}"}]
    extensions: list[dict[str, Any]] = []
    if role.channel is not None:
        extensions.append(_extension("channel", role.channel.value))
    if role.covered_by_practitioner_id is not None and role.covered_until is not None:
        extensions.append(_extension("coveredBy", role.covered_by_practitioner_id))
        extensions.append(_extension("coveredUntil", _instant_text(role.covered_until)))
    if extensions:
        resource["extension"] = extensions
    return resource


def role_from_fhir(resource: dict[str, Any]) -> PractitionerRole:
    """The role for a FHIR PractitionerRole. Refuses a code, channel or period it does not
    recognise, and more than one service."""
    practitioner_id = _reference_id(
        _required(resource, "practitioner"), _PRACTITIONER, "practitioner"
    )
    services = resource.get("healthcareService", [])
    if not isinstance(services, list) or len(services) > 1:
        raise ValidationFailed("healthcareService", "at most one service")
    service_id = _reference_id(services[0], _SERVICE, "healthcareService") if services else None
    codes = _required(resource, "code")
    if not isinstance(codes, list) or len(codes) != 1:
        raise ValidationFailed("code", "needs exactly one code")
    code = codeable_from_fhir(codes[0], PractitionerRoleCode, "code")
    period = _required(resource, "period")
    if not isinstance(period, dict):
        raise ValidationFailed("period", "must be a period")
    values = _extension_values(resource)
    channel = parse_code(Channel, values["channel"]) if "channel" in values else None
    covered_by = values.get("coveredBy")
    covered_until = (
        _instant("coveredUntil", values["coveredUntil"]) if "coveredUntil" in values else None
    )
    active = _required(resource, "active")
    if not isinstance(active, bool):
        raise ValidationFailed("active", "must be a boolean")
    return PractitionerRole(
        id=str(_required(resource, "id")),
        practitioner_id=practitioner_id,
        service_id=service_id,
        code=code,
        active=active,
        channel=channel,
        period_start=_instant("period.start", period.get("start")),
        period_end=_instant("period.end", period["end"]) if "end" in period else None,
        covered_by_practitioner_id=None if covered_by is None else str(covered_by),
        covered_until=covered_until,
    )


def _practitioner_from_stored(resource: dict[str, Any]) -> Practitioner:
    phone_hash = resource.pop(_PHONE_HASH, None)
    email_domain = resource.pop(_EMAIL_DOMAIN, None)
    return practitioner_from_fhir(
        resource,
        None if phone_hash is None else str(phone_hash),
        None if email_domain is None else str(email_domain),
    )


def _reporter_in_effect(role: PractitionerRole, now: datetime) -> bool:
    return role.active and role.code in REPORTER_ROLE_CODES and is_in_effect(role, now)


class Neo4jPersonRepository:
    """Practitioners and roles as FHIR resources. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def get_practitioner(self, practitioner_id: str) -> Practitioner | None:
        resource = await self._store.get(_PRACTITIONER, practitioner_id)
        return None if resource is None else _practitioner_from_stored(resource)

    async def find_by_phone_hash(self, phone_hash: str) -> Practitioner | None:
        check_phone_hash(phone_hash)
        rows = await run_query(self._tx, "Q-PERSON-PHONE-FIND", hash=phone_hash)
        if not rows:
            return None
        # Two active people on one phone is ambiguous: refuse, and return nothing (DEC-065).
        if len(rows) > 1:
            raise Conflict("more than one active practitioner holds this phone")
        return await self.get_practitioner(str(rows[0]["id"]))

    async def roles_for_practitioner(self, practitioner_id: str) -> list[PractitionerRole]:
        rows = await run_query(
            self._tx, "Q-PERSON-ROLES-OF", key=f"{_PRACTITIONER}/{practitioner_id}"
        )
        return await self._roles(str(row["id"]) for row in rows)

    async def services_for_phone_hash(
        self, phone_hash: str, now: datetime
    ) -> list[tuple[PractitionerRole, str]]:
        check_phone_hash(phone_hash)
        check_aware("now", now)
        found: dict[str, tuple[PractitionerRole, str]] = {}
        for query_id in ("Q-PHONE-SERVICES-HELD", "Q-PHONE-SERVICES-AT"):
            rows = await run_query(self._tx, query_id, hash=phone_hash, now=now)
            for row in rows:
                role = await self._role(str(row["roleId"]))
                if role is None or not _reporter_in_effect(role, now):
                    continue
                found[role.id] = (role, str(row["name"]))
        # Spec query #3 orders by service name; service id then role id break ties (DEC-065).
        return sorted(
            found.values(),
            key=lambda pair: (pair[1], pair[0].service_id or "", pair[0].id),
        )

    async def reporter_roles_for_service(
        self, service_id: str, now: datetime
    ) -> list[PractitionerRole]:
        check_aware("now", now)
        rows = await run_query(self._tx, "Q-SERVICE-REPORTER-ROLES", key=f"{_SERVICE}/{service_id}")
        roles = await self._roles(str(row["id"]) for row in rows)
        return [role for role in roles if _reporter_in_effect(role, now)]

    async def save_practitioner(self, practitioner: Practitioner) -> None:
        # Insert or replace. The store checks the version after its lock (DEC-053 item 4).
        current = await self._store.get(_PRACTITIONER, practitioner.id)
        expected = None if current is None else str(current["meta"]["versionId"])
        await self._store.put(practitioner_to_fhir(practitioner), expected)
        await run_query(
            self._tx,
            "Q-PERSON-SET-PROPS",
            key=f"{_PRACTITIONER}/{practitioner.id}",
            phoneHash=practitioner.phone_hash,
            emailDomain=practitioner.email_domain,
        )

    async def save_role(self, role: PractitionerRole) -> None:
        # The practitioner, service and cover-practitioner checks come before the write, so a caller
        # that catches their NotFound commits nothing. The cover-link check after the write is a
        # backstop: it cannot fire unless the graph changed after the pre-check.
        await self._require(_PRACTITIONER, role.practitioner_id)
        if role.service_id is not None:
            await self._require(_SERVICE, role.service_id)
        if role.covered_by_practitioner_id is not None:
            await self._require(_PRACTITIONER, role.covered_by_practitioner_id)
        current = await self._store.get(_ROLE, role.id)
        expected = None if current is None else str(current["meta"]["versionId"])
        await self._store.put(role_to_fhir(role), expected)

        key = f"{_ROLE}/{role.id}"
        if role.channel is not None:
            coding = coding_for(role.channel)
            await run_query(
                self._tx,
                "Q-ROLE-CHANNEL",
                roleKey=key,
                system=coding.system,
                code=coding.code,
                display=coding.display,
                conceptKey=f"{_CONCEPT_PREFIX}{coding.system}{_KEY_SEPARATOR}{coding.code}",
            )
        if role.covered_by_practitioner_id is not None and role.covered_until is not None:
            rows = await run_query(
                self._tx,
                "Q-ROLE-COVER",
                roleKey=key,
                coverKey=f"{_PRACTITIONER}/{role.covered_by_practitioner_id}",
                until=role.covered_until,
            )
            if int(rows[0]["linked"]) != 1:
                raise NotFound(f"{_PRACTITIONER}/{role.covered_by_practitioner_id}")

    async def _require(self, resource_type: str, resource_id: str) -> None:
        if not await self._store.exists(resource_type, resource_id):
            raise NotFound(f"{resource_type}/{resource_id}")

    async def _role(self, role_id: str) -> PractitionerRole | None:
        resource = await self._store.get(_ROLE, role_id)
        return None if resource is None else role_from_fhir(resource)

    async def _roles(self, role_ids: Iterable[str]) -> list[PractitionerRole]:
        roles: list[PractitionerRole] = []
        for role_id in role_ids:
            role = await self._role(role_id)
            if role is not None and role.active:
                roles.append(role)
        return roles
