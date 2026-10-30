"""Web Push subscriptions on Neo4j (P19).

A subscription belongs to one installed app on one device:
(:Resource:Device {id, key, status, deviceType: 'mobile-app', pushSubscriptionJson, pushSavedAt,
tenantId})-[:USED_BY]->(:Practitioner) and -[:TYPE]->(:Concept {system: device-type,
code: mobile-app}). The Device carries the Resource label so later FHIR reads find it.

A Device is keyed by (tenant, deviceType, id). Every statement here matches the device type in its
key, so a push subscription never addresses a wall display. The id is also unique per tenant across
device types (the composite constraint tenant_device_id), so a save with an id that a wall display
holds is refused by the constraint, and the refusal names neither record. A wall display's own
statements match on their type in the same way, so the reverse holds.

The subscription JSON (endpoint and the p256dh and auth keys) is a capability secret. It is stored
on the Device and nowhere else: never logged, never in an audit row or in telemetry, and never in an
error message. Deleting removes the JSON and the save time; the Device stays.
"""

import json
from datetime import UTC, datetime
from typing import Any, Final

from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.driver import ScopedTx, run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from diucs.application.ports.outbound.messaging import PushSubscription
from diucs.domain.codes import code_system_url
from diucs.domain.errors import Conflict, NotFound, ValidationFailed

DEVICE: Final = "Device"
PRACTITIONER: Final = "Practitioner"
DEVICE_TYPE_SYSTEM: Final = code_system_url("device-type")
MOBILE_APP: Final = "mobile-app"
PUSH_DEVICE_TYPE: Final = MOBILE_APP
"""The deviceType of every push device: part of the key of a Device (tenant, deviceType, id)."""
_CONCEPT_KEY: Final = f"Concept|{DEVICE_TYPE_SYSTEM}|{MOBILE_APP}"

# Scenarios (DEC-150). Both tenants hold the practitioner `p1` and the device `dev-1`, with the
# subscription of the device; the keys are shared, so only the tenant stamp keeps them apart.
_NOW: Final = datetime(2026, 10, 25, 13, 12, tzinfo=UTC)
_SUBSCRIPTION_JSON: Final = (
    '{"endpoint":"https://push.example/abc","keys":{"auth":"a1","p256dh":"k1"}}'
)
_NODE_PRACTITIONER: Final = SeedNode(
    "p1",
    ("Resource", "Practitioner"),
    {"id": "p1", "key": "Practitioner/p1", "active": True, "name": Marked("Pat")},
)
_NODE_DEVICE: Final = SeedNode(
    "dev",
    ("Resource", "Device"),
    {
        "id": "dev-1",
        "key": "Device/dev-1",
        "status": "active",
        "deviceType": PUSH_DEVICE_TYPE,
        "pushSubscriptionJson": _SUBSCRIPTION_JSON,
        "pushSavedAt": _NOW,
    },
)
_PRACTITIONER_SEED: Final = TenantSeed(nodes=(_NODE_PRACTITIONER,))
_DEVICE_SEED: Final = TenantSeed(
    nodes=(_NODE_PRACTITIONER, _NODE_DEVICE),
    rels=(SeedRel("dev", "USED_BY", "p1"),),
)
_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-PUSH-SAVE": Scenario(
        "save the push subscription of a device of a practitioner",
        seed=_PRACTITIONER_SEED,
        params={
            "practitionerId": "p1",
            "deviceId": "dev-1",
            "deviceType": PUSH_DEVICE_TYPE,
            "key": "Device/dev-1",
            "json": _SUBSCRIPTION_JSON,
            "savedAt": _NOW,
            "system": DEVICE_TYPE_SYSTEM,
            "code": MOBILE_APP,
            "conceptKey": _CONCEPT_KEY,
        },
        lookup=("practitionerId",),
        new=("deviceId", "deviceType", "key", "json", "savedAt", "system", "code", "conceptKey"),
        expect=Expect(
            rows=({"saved": 1},),
            nodes={"Resource": 1, "Device": 1, "Concept": 1},
            rels={"USED_BY": 1, "TYPE": 1},
        ),
    ),
    "Q-PUSH-FOR": Scenario(
        "list the push subscriptions of a practitioner's devices, newest first",
        seed=_DEVICE_SEED,
        params={"practitionerId": "p1", "deviceType": PUSH_DEVICE_TYPE},
        lookup=("practitionerId", "deviceType"),
        expect=Expect(rows=({"deviceId": "dev-1"},)),
    ),
    "Q-PUSH-DELETE": Scenario(
        "remove the push subscription of a device and keep the device",
        seed=_DEVICE_SEED,
        params={"deviceId": "dev-1", "deviceType": PUSH_DEVICE_TYPE},
        lookup=("deviceId", "deviceType"),
        expect=Expect(
            rows=({"deleted": 1},),
            after=(NodeSpec(("Device",), {"id": "dev-1", "status": "active"}),),
        ),
    ),
}

_QUERIES: Final[tuple[NamedQuery, ...]] = (
    NamedQuery(
        id="Q-PUSH-SAVE",
        cypher=(
            "MATCH (p:Practitioner {id: $practitionerId, tenantId: $tenant}) "
            "MERGE (d:Resource:Device {id: $deviceId, tenantId: $tenant, deviceType: $deviceType}) "
            "ON CREATE SET d.key = $key "
            "SET d.status = 'active', d.pushSubscriptionJson = $json, d.pushSavedAt = $savedAt "
            "WITH d, p "
            "OPTIONAL MATCH (d)-[old:USED_BY]->(:Practitioner {tenantId: $tenant}) DELETE old "
            "WITH d, p "
            "MERGE (d)-[:USED_BY]->(p) "
            "MERGE (c:Concept {system: $system, code: $code, tenantId: $tenant}) "
            "ON CREATE SET c.key = $conceptKey "
            "MERGE (d)-[:TYPE]->(c) "
            "RETURN count(d) AS saved"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-PUSH-SAVE"],
    ),
    NamedQuery(
        id="Q-PUSH-FOR",
        cypher=(
            "MATCH (d:Device {tenantId: $tenant, deviceType: $deviceType})-[:USED_BY]->"
            "(:Practitioner {id: $practitionerId, tenantId: $tenant}) "
            "WHERE d.pushSubscriptionJson IS NOT NULL "
            "RETURN d.id AS deviceId, d.pushSubscriptionJson AS json, d.pushSavedAt AS savedAt "
            "ORDER BY d.pushSavedAt DESC, d.id"
        ),
        mode="read",
        scenario=_SCENARIOS["Q-PUSH-FOR"],
    ),
    NamedQuery(
        id="Q-PUSH-DELETE",
        cypher=(
            "MATCH (d:Device {id: $deviceId, tenantId: $tenant, deviceType: $deviceType}) "
            "SET d.pushSubscriptionJson = null, d.pushSavedAt = null "
            "RETURN count(d) AS deleted"
        ),
        mode="write",
        scenario=_SCENARIOS["Q-PUSH-DELETE"],
    ),
)


def _register(query: NamedQuery) -> None:
    if query.id not in REGISTRY.ids():
        REGISTRY.register(query)


for _query in _QUERIES:
    _register(_query)


def _present(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def checked_subscription(subscription: dict[str, Any]) -> None:
    """A subscription must hold an endpoint and the p256dh and auth keys. The refusal names the
    fields and never the values (the endpoint and the keys are a capability secret)."""
    keys = subscription.get("keys") if isinstance(subscription, dict) else None
    ok = (
        isinstance(subscription, dict)
        and _present(subscription.get("endpoint"))
        and isinstance(keys, dict)
        and _present(keys.get("p256dh"))
        and _present(keys.get("auth"))
    )
    if not ok:
        raise ValidationFailed("subscription", "must hold an endpoint and the p256dh and auth keys")


def subscription_json(subscription: dict[str, Any]) -> str:
    """The stored text: sorted keys and no spaces, so the same subscription always has one text."""
    return json.dumps(subscription, sort_keys=True, separators=(",", ":"))


def subscription_from_json(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValidationFailed("subscription", "stored subscription is not an object")
    return value


def _utc(value: Any) -> datetime:
    native: datetime = value.to_native() if hasattr(value, "to_native") else value
    return native.astimezone(UTC)


class Neo4jPushSubscriptionRepository:
    """Push subscriptions. Built per transaction (DEC-012)."""

    def __init__(self, tx: ScopedTx) -> None:
        self._tx = tx

    async def save(self, subscription: PushSubscription) -> None:
        checked_subscription(subscription.subscription)
        try:
            rows = await run_query(
                self._tx,
                REGISTRY.get("Q-PUSH-SAVE"),
                practitionerId=subscription.practitioner_id,
                deviceId=subscription.device_id,
                deviceType=PUSH_DEVICE_TYPE,
                key=f"{DEVICE}/{subscription.device_id}",
                json=subscription_json(subscription.subscription),
                savedAt=subscription.saved_at.astimezone(UTC),
                system=DEVICE_TYPE_SYSTEM,
                code=MOBILE_APP,
                conceptKey=_CONCEPT_KEY,
            )
        except ConstraintError as error:
            # The id is taken in this tenant: by a racing save of this device, or by a device of
            # another type. Nothing is stored by this write, and the message names neither record.
            raise Conflict("the device id is already in use") from error
        if not rows or rows[0]["saved"] == 0:
            raise NotFound("practitioner")

    async def for_practitioner(self, practitioner_id: str) -> list[PushSubscription]:
        rows = await run_query(
            self._tx,
            REGISTRY.get("Q-PUSH-FOR"),
            practitionerId=practitioner_id,
            deviceType=PUSH_DEVICE_TYPE,
        )
        return [
            PushSubscription(
                device_id=str(row["deviceId"]),
                practitioner_id=practitioner_id,
                subscription=subscription_from_json(str(row["json"])),
                saved_at=_utc(row["savedAt"]),
            )
            for row in rows
        ]

    async def delete(self, device_id: str) -> None:
        await run_query(
            self._tx,
            REGISTRY.get("Q-PUSH-DELETE"),
            deviceId=device_id,
            deviceType=PUSH_DEVICE_TYPE,
        )
