"""Alert subscriptions and alerts on Neo4j (P17).

A subscription is a platform node, one per practitioner, that CONTACTs the practitioner:
(:AlertSubscription {practitionerId, kinds, notUpdatedHours, quietStart, quietEnd,
quietCriticalOnly, ackMinutes, deputyId, dailySummary, weeklySummary, updatedAt, tenantId}).
Its preferences are not a FHIR Subscription: R12 maps the node to FHIR later (the R4B Subscription
elements are not verified).

An alert is a Task with code `acknowledge-alert`, written through the resource store (G05). Its
business status is a property of the Task, as the registration Task's is (P13): the store keeps the
CodeableConcept only in the mapping. The escalation chain is the `partOf` link; `owner` is the
practitioner alerted; `focus` is the service (absent for system pressure).

Decisions: DEC-046 (alert rules), and the choices of P17 in the fragment. Every statement names its
tenant on every node it matches or creates, and carries a scenario (DEC-142).
"""

from datetime import UTC, datetime, time
from typing import Any, Final

from neo4j import AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.extensions import by_short_name
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from diucs.domain.codes import AlertKind, code_system_url, parse_code
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.alerts import ALERT_STATUSES, AlertRecord, AlertSubscription
from diucs.domain.rules.alerts import AlertPreferences

TASK: Final = "Task"
SERVICE: Final = "HealthcareService"
PRACTITIONER: Final = "Practitioner"
ALERT_CODE: Final = "acknowledge-alert"
TASK_CODE_SYSTEM: Final = code_system_url("task-code")
ALERT_STATUS_SYSTEM: Final = code_system_url("alert-status")
_OPEN_STATUSES: Final = frozenset({"new", "escalated"})
_TIME_FORMAT: Final = "%H:%M"

# Scenarios (DEC-150). Both tenants hold the practitioner `p1`, the service `svc-1`, the alert
# `alert-1` and its code: every key is shared, so only the tenant stamp keeps the two apart.
_NOW: Final = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)
_NODE_PRACTITIONER: Final = SeedNode(
    "p1",
    ("Resource", "Practitioner"),
    {"id": "p1", "key": "Practitioner/p1", "active": True, "name": Marked("Pat")},
)
_NODE_SERVICE: Final = SeedNode(
    "svc",
    ("Resource", "HealthcareService"),
    {"id": "svc-1", "key": "HealthcareService/svc-1", "active": True, "name": Marked("Pilot")},
)
_NODE_CONCEPT: Final = SeedNode(
    "concept",
    ("Concept",),
    {
        "system": TASK_CODE_SYSTEM,
        "code": ALERT_CODE,
        "key": f"Concept|{TASK_CODE_SYSTEM}|{ALERT_CODE}",
        "display": Marked("Acknowledge an alert"),
    },
)
_NODE_TASK: Final = SeedNode(
    "task",
    ("Resource", "Task"),
    {"id": "alert-1", "key": "Task/alert-1", "businessStatus": "new"},
)
_NODE_SUBSCRIPTION: Final = SeedNode(
    "sub",
    ("AlertSubscription",),
    {
        "practitionerId": "p1",
        "kinds": ["over-capacity"],
        "notUpdatedHours": 2,
        "quietStart": None,
        "quietEnd": None,
        "quietCriticalOnly": True,
        "ackMinutes": 15,
        "deputyId": "p-deputy",
        "dailySummary": False,
        "weeklySummary": False,
        "updatedAt": _NOW,
    },
)
_PRACTITIONER_SEED: Final = TenantSeed(nodes=(_NODE_PRACTITIONER,))
_SUBSCRIPTION_SEED: Final = TenantSeed(nodes=(_NODE_PRACTITIONER, _NODE_SUBSCRIPTION))
_ALERT_SEED: Final = TenantSeed(
    nodes=(_NODE_PRACTITIONER, _NODE_SERVICE, _NODE_CONCEPT, _NODE_TASK),
    rels=(
        SeedRel("task", "CODE", "concept"),
        SeedRel("task", "OWNER", "p1"),
        SeedRel("task", "FOCUS", "svc"),
    ),
)
_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-ALERT-SUB-LOCK": Scenario(
        "lock the practitioner before a subscription is saved for it",
        seed=_PRACTITIONER_SEED,
        params={"practitionerId": "p1"},
        lookup=("practitionerId",),
        expect=Expect(rows=({"locked": 1},)),
    ),
    "Q-ALERT-SUB-SAVE": Scenario(
        "save the alert subscription of a practitioner",
        seed=_PRACTITIONER_SEED,
        params={
            "practitionerId": "p1",
            "kinds": ["over-capacity"],
            "notUpdatedHours": 2,
            "quietStart": None,
            "quietEnd": None,
            "quietCriticalOnly": True,
            "ackMinutes": 15,
            "deputyId": "p-deputy",
            "dailySummary": False,
            "weeklySummary": False,
            "updatedAt": _NOW,
        },
        lookup=("practitionerId",),
        new=(
            "kinds",
            "notUpdatedHours",
            "quietStart",
            "quietEnd",
            "quietCriticalOnly",
            "ackMinutes",
            "deputyId",
            "dailySummary",
            "weeklySummary",
            "updatedAt",
        ),
        expect=Expect(
            rows=({"saved": 1},),
            nodes={"AlertSubscription": 1},
            rels={"CONTACT": 1},
        ),
    ),
    "Q-ALERT-SUB-FOR": Scenario(
        "read the alert subscription of a practitioner",
        seed=_SUBSCRIPTION_SEED,
        params={"practitionerId": "p1"},
        lookup=("practitionerId",),
        expect=Expect(rows=({"practitionerId": "p1", "deputyId": "p-deputy"},)),
    ),
    "Q-ALERT-SUB-KIND": Scenario(
        "list the practitioners whose subscription has an alert kind switched on",
        seed=_SUBSCRIPTION_SEED,
        params={"kind": "over-capacity"},
        lookup=("kind",),
        expect=Expect(rows=({"practitionerId": "p1"},)),
    ),
    "Q-ALERT-SET-STATUS": Scenario(
        "set the business status of an alert",
        seed=_ALERT_SEED,
        params={"key": "Task/alert-1", "businessStatus": "acknowledged"},
        lookup=("key",),
        new=("businessStatus",),
        expect=Expect(
            rows=({"set": 1},),
            after=(NodeSpec(("Task",), {"id": "alert-1", "businessStatus": "acknowledged"}),),
        ),
    ),
    "Q-ALERT-OPEN-FOR-OWNER": Scenario(
        "list the new alerts owned by a practitioner, for the alert code",
        seed=_ALERT_SEED,
        params={"practitionerId": "p1", "system": TASK_CODE_SYSTEM, "code": ALERT_CODE},
        lookup=("practitionerId", "system", "code"),
        expect=Expect(rows=({"id": "alert-1"},)),
    ),
}

_QUERIES: Final[tuple[NamedQuery, ...]] = (
    NamedQuery(
        id="Q-ALERT-SUB-LOCK",
        cypher=(
            "MATCH (p:Practitioner {id: $practitionerId, tenantId: $tenant}) "
            "SET p.id = p.id RETURN count(p) AS locked"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-ALERT-SUB-LOCK"],
    ),
    NamedQuery(
        id="Q-ALERT-SUB-SAVE",
        cypher=(
            "MATCH (p:Practitioner {id: $practitionerId, tenantId: $tenant}) "
            "MERGE (s:AlertSubscription {practitionerId: $practitionerId, tenantId: $tenant}) "
            "SET s.kinds = $kinds, s.notUpdatedHours = $notUpdatedHours, "
            "s.quietStart = $quietStart, s.quietEnd = $quietEnd, "
            "s.quietCriticalOnly = $quietCriticalOnly, s.ackMinutes = $ackMinutes, "
            "s.deputyId = $deputyId, s.dailySummary = $dailySummary, "
            "s.weeklySummary = $weeklySummary, s.updatedAt = $updatedAt "
            "MERGE (s)-[:CONTACT]->(p) "
            "RETURN count(s) AS saved"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-ALERT-SUB-SAVE"],
    ),
    NamedQuery(
        id="Q-ALERT-SUB-FOR",
        cypher=(
            "MATCH (s:AlertSubscription {practitionerId: $practitionerId, tenantId: $tenant}) "
            "RETURN s.practitionerId AS practitionerId, s.kinds AS kinds, "
            "s.notUpdatedHours AS notUpdatedHours, s.quietStart AS quietStart, "
            "s.quietEnd AS quietEnd, s.quietCriticalOnly AS quietCriticalOnly, "
            "s.ackMinutes AS ackMinutes, s.deputyId AS deputyId, "
            "s.dailySummary AS dailySummary, s.weeklySummary AS weeklySummary, "
            "s.updatedAt AS updatedAt"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-ALERT-SUB-FOR"],
    ),
    NamedQuery(
        id="Q-ALERT-SUB-KIND",
        cypher=(
            "MATCH (s:AlertSubscription {tenantId: $tenant}) "
            "WHERE $kind IN s.kinds "
            "RETURN s.practitionerId AS practitionerId ORDER BY s.practitionerId"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-ALERT-SUB-KIND"],
    ),
    NamedQuery(
        id="Q-ALERT-SET-STATUS",
        cypher=(
            "MATCH (t:Task {key: $key, tenantId: $tenant}) "
            "SET t.businessStatus = $businessStatus RETURN count(t) AS set"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-ALERT-SET-STATUS"],
    ),
    NamedQuery(
        id="Q-ALERT-OPEN-FOR-OWNER",
        cypher=(
            "MATCH (t:Task {businessStatus: 'new', tenantId: $tenant})"
            "-[:OWNER]->(:Practitioner {id: $practitionerId, tenantId: $tenant}), "
            "(t)-[:CODE]->(:Concept {system: $system, code: $code, tenantId: $tenant}) "
            "RETURN t.id AS id ORDER BY t.authoredOn, t.id"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-ALERT-OPEN-FOR-OWNER"],
    ),
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in _QUERIES:
    _register(_query)


def _iso(value: datetime) -> str:
    """UTC, with Z (the FHIR form the store keeps)."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _instant(field: str, text: Any) -> datetime:
    if not isinstance(text, str):
        raise ValidationFailed(field, "must be a FHIR datetime")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValidationFailed(field, "not a FHIR datetime") from None
    if parsed.tzinfo is None:
        raise ValidationFailed(field, "must carry a UTC offset")
    return parsed.astimezone(UTC)


def _utc(value: Any) -> datetime:
    """A stored instant as UTC. The driver returns its own datetime type, so it is converted."""
    native: datetime = value.to_native() if hasattr(value, "to_native") else value
    return native.astimezone(UTC)


def _extension(short_name: str, value: Any) -> dict[str, Any]:
    defn = by_short_name(short_name)
    if defn is None:  # a programming error: the names are registered in extensions.py
        raise LookupError(short_name)
    return {"url": defn.url, defn.value_key: value}


def _extension_value(resource: dict[str, Any], short_name: str) -> Any:
    defn = by_short_name(short_name)
    if defn is None:
        raise LookupError(short_name)
    for entry in resource.get("extension", []):
        if entry.get("url") == defn.url:
            return entry.get(defn.value_key)
    return None


def _is_alert(resource: dict[str, Any]) -> bool:
    codings = resource.get("code", {}).get("coding")
    return (
        isinstance(codings, list)
        and len(codings) == 1
        and codings[0].get("system") == TASK_CODE_SYSTEM
        and codings[0].get("code") == ALERT_CODE
    )


def _target(resource: dict[str, Any], element: str, resource_type: str) -> str:
    reference = resource.get(element, {}).get("reference")
    prefix = f"{resource_type}/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValidationFailed(element, f"must reference a {resource_type}")
    return reference[len(prefix) :]


def _task_status(status: str) -> str:
    return "requested" if status in _OPEN_STATUSES else "completed"


def alert_to_fhir(alert: AlertRecord) -> dict[str, Any]:
    """The Task for an alert. The store sets meta; the repository moves businessStatus to a
    property before the put, as the registration repository does."""
    resource: dict[str, Any] = {
        "resourceType": TASK,
        "id": alert.id,
        "status": _task_status(alert.status),
        "businessStatus": {"coding": [{"system": ALERT_STATUS_SYSTEM, "code": alert.status}]},
        "intent": "order",
        "code": {"coding": [{"system": TASK_CODE_SYSTEM, "code": ALERT_CODE}]},
        "authoredOn": _iso(alert.raised_at),
        "owner": {"reference": f"{PRACTITIONER}/{alert.owner_practitioner_id}"},
        "extension": [_extension("alertKind", alert.kind.value)],
    }
    if alert.service_id is not None:
        resource["focus"] = {"reference": f"{SERVICE}/{alert.service_id}"}
    if alert.escalation_due_at is not None:
        resource["extension"].append(_extension("escalationDueAt", _iso(alert.escalation_due_at)))
    if alert.acknowledged_at is not None:
        resource["extension"].append(_extension("acknowledgedAt", _iso(alert.acknowledged_at)))
    if alert.part_of_id is not None:
        resource["partOf"] = [{"reference": f"{TASK}/{alert.part_of_id}"}]
    return resource


def alert_from_fhir(resource: dict[str, Any]) -> AlertRecord:
    """The alert for a Task with code acknowledge-alert. Any other Task is refused."""
    if not _is_alert(resource):
        raise ValidationFailed("code", "not an alert task")
    status = resource.get("businessStatus", {}).get("coding", [{}])[0].get("code")
    if not isinstance(status, str) or status not in ALERT_STATUSES:
        raise ValidationFailed("businessStatus", "not an alert status")
    kind_text = _extension_value(resource, "alertKind")
    if not isinstance(kind_text, str):
        raise ValidationFailed("alertKind", "is required")
    due = _extension_value(resource, "escalationDueAt")
    acknowledged = _extension_value(resource, "acknowledgedAt")
    part_of = resource.get("partOf")
    return AlertRecord(
        id=str(resource["id"]),
        kind=parse_code(AlertKind, kind_text),
        service_id=_target(resource, "focus", SERVICE) if "focus" in resource else None,
        owner_practitioner_id=_target(resource, "owner", PRACTITIONER),
        status=status,
        raised_at=_instant("authoredOn", resource.get("authoredOn")),
        escalation_due_at=None if due is None else _instant("escalationDueAt", due),
        part_of_id=None if not part_of else _part_of_id(part_of),
        acknowledged_at=None if acknowledged is None else _instant("acknowledgedAt", acknowledged),
    )


def _part_of_id(part_of: list[dict[str, Any]]) -> str:
    reference = part_of[0].get("reference")
    prefix = f"{TASK}/"
    if not isinstance(reference, str) or not reference.startswith(prefix):
        raise ValidationFailed("partOf", "must reference a Task")
    return reference[len(prefix) :]


def subscription_to_props(subscription: AlertSubscription) -> dict[str, Any]:
    """The node properties of a subscription. Quiet hours are stored as clock text; no quiet hours
    are None, which the store does not keep (a missing key reads as None)."""
    prefs = subscription.preferences
    start, end = prefs.quiet_hours if prefs.quiet_hours is not None else (None, None)
    return {
        "practitionerId": subscription.practitioner_id,
        "kinds": sorted(kind.value for kind in prefs.kinds),
        "notUpdatedHours": prefs.not_updated_hours,
        "quietStart": None if start is None else start.strftime(_TIME_FORMAT),
        "quietEnd": None if end is None else end.strftime(_TIME_FORMAT),
        "quietCriticalOnly": prefs.quiet_critical_only,
        "ackMinutes": prefs.ack_minutes,
        "deputyId": subscription.deputy_id,
        "dailySummary": subscription.daily_summary,
        "weeklySummary": subscription.weekly_summary,
        "updatedAt": subscription.updated_at.astimezone(UTC),
    }


def subscription_from_props(props: dict[str, Any]) -> AlertSubscription:
    start = props.get("quietStart")
    quiet: tuple[time, time] | None = None
    if start is not None:
        quiet = (
            time.fromisoformat(str(start)),
            time.fromisoformat(str(props.get("quietEnd"))),
        )
    preferences = AlertPreferences(
        kinds=frozenset(parse_code(AlertKind, kind) for kind in props["kinds"]),
        not_updated_hours=int(props["notUpdatedHours"]),
        quiet_hours=quiet,
        quiet_critical_only=bool(props["quietCriticalOnly"]),
        ack_minutes=int(props["ackMinutes"]),
    )
    return AlertSubscription(
        practitioner_id=str(props["practitionerId"]),
        preferences=preferences,
        deputy_id=props.get("deputyId"),
        daily_summary=bool(props["dailySummary"]),
        weekly_summary=bool(props["weeklySummary"]),
        updated_at=_utc(props["updatedAt"]),
    )


class Neo4jAlertSubscriptionRepository:
    """Alert subscriptions, one per practitioner. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def get_for_practitioner(self, practitioner_id: str) -> AlertSubscription | None:
        rows = await run_query(
            self._tx, REGISTRY.get("Q-ALERT-SUB-FOR"), practitionerId=practitioner_id
        )
        if not rows:
            return None
        return subscription_from_props(rows[0])

    async def save(self, subscription: AlertSubscription) -> None:
        props = subscription_to_props(subscription)
        # The practitioner's write lock first, so two saves for one practitioner serialise and
        # leave one subscription node (lesson L73).
        await run_query(
            self._tx, REGISTRY.get("Q-ALERT-SUB-LOCK"), practitionerId=props["practitionerId"]
        )
        rows = await run_query(self._tx, REGISTRY.get("Q-ALERT-SUB-SAVE"), **props)
        if not rows or rows[0]["saved"] == 0:
            raise NotFound("practitioner")

    async def subscribers_for_kind(self, kind: AlertKind) -> list[AlertSubscription]:
        if type(kind) is not AlertKind:
            raise ValidationFailed("kind", "must be an alert kind")
        rows = await run_query(self._tx, REGISTRY.get("Q-ALERT-SUB-KIND"), kind=kind.value)
        found: list[AlertSubscription] = []
        for row in rows:
            subscription = await self.get_for_practitioner(str(row["practitionerId"]))
            if subscription is not None:
                found.append(subscription)
        return found


class Neo4jAlertRepository:
    """Alerts as Task resources. Built per transaction (DEC-012)."""

    def __init__(self, tx: AsyncManagedTransaction, store: ResourceStore) -> None:
        self._tx = tx
        self._store = store

    async def add(self, alert: AlertRecord) -> None:
        # The store refuses an existing Task with Conflict (expected version None).
        await self._put(alert, None)

    async def get(self, alert_id: str) -> AlertRecord | None:
        resource = await self._store.get(TASK, alert_id)
        if resource is None or not _is_alert(resource):
            return None
        stored = resource.pop("businessStatus", None)
        if not isinstance(stored, str):
            raise ValidationFailed("businessStatus", "missing on a stored alert")
        resource["businessStatus"] = {"coding": [{"system": ALERT_STATUS_SYSTEM, "code": stored}]}
        return alert_from_fhir(resource)

    async def save(self, alert: AlertRecord) -> None:
        current = await self._store.get(TASK, alert.id)
        if current is None or not _is_alert(current):
            raise NotFound("alert")
        await self._put(alert, str(current["meta"]["versionId"]))

    async def open_for_owner(self, practitioner_id: str) -> list[AlertRecord]:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-ALERT-OPEN-FOR-OWNER"),
            practitionerId=practitioner_id,
            system=TASK_CODE_SYSTEM,
            code=ALERT_CODE,
        )
        found: list[AlertRecord] = []
        for row in rows:
            alert = await self.get(str(row["id"]))
            if alert is not None:
                found.append(alert)
        return found

    async def chain(self, alert_id: str) -> list[AlertRecord]:
        """The alert and the alerts it escalates from, oldest first. A loop of partOf links is
        refused, and an alert that is not there raises NotFound."""
        found: list[AlertRecord] = []
        seen: set[str] = set()
        current: str | None = alert_id
        while current is not None:
            if current in seen:
                raise ValidationFailed("partOf", "the escalation chain loops")
            seen.add(current)
            alert = await self.get(current)
            if alert is None:
                raise NotFound("alert")
            found.append(alert)
            current = alert.part_of_id
        return list(reversed(found))

    async def _put(self, alert: AlertRecord, expected_version: str | None) -> None:
        resource = alert_to_fhir(alert)
        status = resource.pop("businessStatus")["coding"][0]["code"]
        await self._store.put(resource, expected_version)
        await run_query(
            self._tx,
            REGISTRY.get("Q-ALERT-SET-STATUS"),
            key=f"{TASK}/{alert.id}",
            businessStatus=status,
        )
