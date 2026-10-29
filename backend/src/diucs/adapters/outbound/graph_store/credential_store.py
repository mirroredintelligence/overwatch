"""Neo4j stores for PIN credentials and devices (P16, DEC-044, DEC-070).

Layout:
- (:Practitioner)-[:HAS_CREDENTIAL]->(:Credential {deviceId, pinHash, failed, locked, lastOutcome,
  updatedAt}). One credential per practitioner and device. Only the keyed PIN hash is stored; the
  PIN itself never reaches this module. `locked` is the lock from DEC-044 item 2, which has no end
  time: it lasts until a verified text code resets it.
- (:Practitioner)-[:HAS_DEVICE]->(:Device {id, status, registeredAt, revokedAt}). Device ids are
  unique in the graph (migration 0023). A device belongs to one practitioner.

Reads of a PIN state take the credential's write lock first (lesson L73), so an attempt that reads
the failure count and the save that follows it cannot interleave with another attempt on the same
device, provided the caller runs both in one unit of work.

Times are written by the database in UTC, or passed in as aware instants and written in UTC.
Neo4j stores no null property (lesson L74): a cleared value is absent, and readers treat it as None.
"""

from datetime import UTC, datetime
from typing import Any, Final, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
    Unique,
)
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.rules.identity_policy import PinOutcome, PinState

_PRACTITIONER_KEY: Final = "Practitioner/{}"
_STATUS_ACTIVE: Final = "active"
_STATUS_REVOKED: Final = "revoked"

# Scenarios of the converted statements (DEC-142 item 5, DEC-150). Both tenants have a practitioner
# with the same key; the practitioner's id and the credential's device id are unique in the whole
# graph until TEN-005 (migrations 0001 and 0026), so they are `Unique`: the generated test also
# runs each statement with the other tenant's device id. A practitioner is written by the resource
# store, which does not stamp the tenant yet (TEN-009); the scenarios seed it stamped.
_PRACTITIONER: Final = SeedNode(
    "practitioner",
    ("Resource", "Practitioner"),
    {
        "id": Unique("prac-1", "resource_id"),
        "key": "Practitioner/prac-1",
        "active": True,
        "name": Marked("Duty Manager"),
    },
)
_PRACTITIONER_SEED: Final = TenantSeed(nodes=(_PRACTITIONER,))
_CREDENTIAL_SEED: Final = TenantSeed(
    nodes=(
        _PRACTITIONER,
        SeedNode(
            "credential",
            ("Credential",),
            {
                "deviceId": Unique("dev-1", "credential_device_id"),
                "pinHash": Marked("hash"),
                "failed": 1,
                "locked": False,
            },
        ),
    ),
    rels=(SeedRel("practitioner", "HAS_CREDENTIAL", "credential"),),
)
_KEY: Final = "Practitioner/prac-1"
_DEVICE: Final = Unique("dev-1", "credential_device_id")
_EXISTS_SCENARIO: Final = Scenario(
    "count the tenant's practitioner by key",
    seed=_PRACTITIONER_SEED,
    params={"key": _KEY},
    lookup=("key",),
    expect=Expect(rows=({"n": 1},)),
)
_SET_SCENARIO: Final = Scenario(
    "set a PIN for a new device of the practitioner",
    seed=_CREDENTIAL_SEED,
    params={
        "key": _KEY,
        "deviceId": Unique("dev-new", "credential_device_id"),
        "pinHash": "hash-new",
    },
    lookup=("key",),
    expect=Expect(
        rows=({"n": 1},),
        nodes={"Credential": 1},
        rels={"HAS_CREDENTIAL": 1},
        after=(
            NodeSpec(
                ("Credential",),
                {
                    "deviceId": Unique("dev-new", "credential_device_id"),
                    "pinHash": "hash-new",
                    "failed": 0,
                },
            ),
        ),
    ),
)
_GET_SCENARIO: Final = Scenario(
    "read and lock the credential of a practitioner's device",
    seed=_CREDENTIAL_SEED,
    params={"key": _KEY, "deviceId": _DEVICE},
    lookup=("key", "deviceId"),
    expect=Expect(rows=({"pinHash": Marked("hash"), "failed": 1, "locked": False},)),
)
_SAVE_STATE_SCENARIO: Final = Scenario(
    "save the failure state of the credential of a device",
    seed=_CREDENTIAL_SEED,
    params={
        "key": _KEY,
        "deviceId": _DEVICE,
        "failed": 2,
        "locked": False,
        "lastOutcome": "wrong-pin",
    },
    lookup=("key", "deviceId"),
    expect=Expect(
        rows=({"n": 1},),
        after=(NodeSpec(("Credential",), {"deviceId": _DEVICE, "failed": 2}),),
    ),
)
_CLEAR_SCENARIO: Final = Scenario(
    "clear the credentials of a practitioner",
    seed=_CREDENTIAL_SEED,
    params={"key": _KEY},
    lookup=("key",),
    expect=Expect(
        rows=({"n": 1},),
        nodes={"Credential": -1},
        rels={"HAS_CREDENTIAL": -1},
        gone=(NodeSpec(("Credential",), {"deviceId": _DEVICE}),),
    ),
)
_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-CRED-PRACTITIONER-EXISTS": _EXISTS_SCENARIO,
    "Q-CRED-SET": _SET_SCENARIO,
    "Q-CRED-GET": _GET_SCENARIO,
    "Q-CRED-SAVE-STATE": _SAVE_STATE_SCENARIO,
    "Q-CRED-CLEAR": _CLEAR_SCENARIO,
}

_QUERIES: dict[str, tuple[str, Literal["read", "write"]]] = {
    "Q-CRED-PRACTITIONER-EXISTS": (
        "MATCH (p:Practitioner {key: $key, tenantId: $tenant}) RETURN count(p) AS n",
        "read",
    ),
    "Q-CRED-SET": (
        "MATCH (p:Practitioner {key: $key, tenantId: $tenant}) "
        "MERGE (p)-[:HAS_CREDENTIAL]->(c:Credential {deviceId: $deviceId, tenantId: $tenant}) "
        "SET c.pinHash = $pinHash, c.failed = 0, c.locked = false, c.lastOutcome = null, "
        "c.updatedAt = datetime({timezone: 'UTC'}) "
        "RETURN count(c) AS n",
        "write",
    ),
    # Lock first, then read: the SET takes the credential's write lock before the properties are
    # read, so a concurrent attempt waits for this one to commit (lesson L73).
    "Q-CRED-GET": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_CREDENTIAL]->"
        "(c:Credential {deviceId: $deviceId, tenantId: $tenant}) "
        "SET c.deviceId = c.deviceId "
        "RETURN c.pinHash AS pinHash, c.failed AS failed, c.locked AS locked, "
        "c.lastOutcome AS lastOutcome",
        "write",
    ),
    "Q-CRED-SAVE-STATE": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_CREDENTIAL]->"
        "(c:Credential {deviceId: $deviceId, tenantId: $tenant}) "
        "SET c.failed = $failed, c.locked = $locked, c.lastOutcome = $lastOutcome, "
        "c.updatedAt = datetime({timezone: 'UTC'}) "
        "RETURN count(c) AS n",
        "write",
    ),
    "Q-CRED-CLEAR": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_CREDENTIAL]->"
        "(c:Credential {tenantId: $tenant}) "
        "DETACH DELETE c RETURN count(*) AS n",
        "write",
    ),
    # Locks the practitioner first, so racing registrations by one practitioner run one after the
    # other, and the second sees the first device (DEC-073 item 2). Also the existence check.
    "Q-DEVICE-LOCK": (
        "MATCH (p:Practitioner {key: $key}) SET p.key = p.key RETURN count(p) AS n",
        "write",
    ),
    "Q-DEVICE-OWNER": (
        "MATCH (p:Practitioner)-[:HAS_DEVICE]->(d:Device {id: $deviceId}) RETURN p.id AS owner",
        "read",
    ),
    "Q-DEVICE-REGISTER": (
        "MATCH (p:Practitioner {key: $key}) "
        "CREATE (p)-[:HAS_DEVICE]->(:Device {id: $deviceId, status: $status, registeredAt: $at}) "
        "RETURN count(*) AS n",
        "write",
    ),
    "Q-DEVICE-KNOWN": (
        "MATCH (:Practitioner {key: $key})-[:HAS_DEVICE]->(d:Device {id: $deviceId}) "
        "WHERE d.revokedAt IS NULL RETURN count(d) AS n",
        "read",
    ),
    "Q-DEVICE-REVOKE": (
        "MATCH (:Practitioner {key: $key})-[:HAS_DEVICE]->(d:Device) WHERE d.revokedAt IS NULL "
        "SET d.status = $revoked, d.revokedAt = datetime({timezone: 'UTC'}) "
        "RETURN count(d) AS n",
        "write",
    ),
}

for _query_id, (_cypher, _mode) in _QUERIES.items():
    REGISTRY.register(
        NamedQuery(id=_query_id, cypher=_cypher, mode=_mode, scenario=_SCENARIOS.get(_query_id))
    )


def _key(practitioner_id: str) -> str:
    return _PRACTITIONER_KEY.format(practitioner_id)


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationFailed(field, "must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _pin_state(row: dict[str, Any]) -> PinState:
    last = row["lastOutcome"]
    return PinState(
        failed_tries=int(row["failed"] or 0),
        locked=bool(row["locked"]),
        last_outcome=PinOutcome(last) if last is not None else None,
    )


class Neo4jPinStore:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def set_pin(self, practitioner_id: str, device_id: str, pin_hash: str) -> None:
        """Store the keyed hash of a PIN and start its state fresh: no failures, not locked. A
        practitioner who does not exist is NotFound, and nothing is written."""
        await self._require_practitioner(practitioner_id)
        try:
            await self._run(
                "Q-CRED-SET", key=_key(practitioner_id), deviceId=device_id, pinHash=pin_hash
            )
        except ConstraintError as error:
            # The device already has a credential, held by another practitioner or raced in
            # parallel. The write is refused and nothing is stored (DEC-074).
            raise Conflict("device already has a PIN credential") from error

    async def get(self, practitioner_id: str, device_id: str) -> tuple[str, PinState] | None:
        """The credential for the device, or None. More than one row is refused, never read as
        one of them: a duplicate would let a PIN be checked against the wrong hash (DEC-074)."""
        rows = await self._run("Q-CRED-GET", key=_key(practitioner_id), deviceId=device_id)
        if len(rows) > 1:
            raise Conflict("more than one credential for this device")
        if not rows or rows[0]["pinHash"] is None:
            return None
        return str(rows[0]["pinHash"]), _pin_state(rows[0])

    async def save_state(self, practitioner_id: str, device_id: str, state: PinState) -> None:
        rows = await self._run(
            "Q-CRED-SAVE-STATE",
            key=_key(practitioner_id),
            deviceId=device_id,
            failed=state.failed_tries,
            locked=state.locked,
            lastOutcome=None if state.last_outcome is None else str(state.last_outcome),
        )
        if not rows or int(rows[0]["n"]) != 1:
            raise NotFound("credential")

    async def clear_all(self, practitioner_id: str) -> None:
        await self._run("Q-CRED-CLEAR", key=_key(practitioner_id))

    async def _require_practitioner(self, practitioner_id: str) -> None:
        rows = await self._run("Q-CRED-PRACTITIONER-EXISTS", key=_key(practitioner_id))
        if not rows or int(rows[0]["n"]) != 1:
            raise NotFound("practitioner")

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, REGISTRY.get(query_id), **params)


class Neo4jDeviceRegistry:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def register(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        """Record a device for the practitioner. Registering a device again for the same
        practitioner changes nothing, so a revoked device stays revoked. A device id that belongs
        to another practitioner is Conflict. A practitioner who does not exist is NotFound. Every
        check runs before the write."""
        registered_at = _utc(at, "at")
        locked = await self._run("Q-DEVICE-LOCK", key=_key(practitioner_id))
        if not locked or int(locked[0]["n"]) != 1:
            raise NotFound("practitioner")
        owners = await self._run("Q-DEVICE-OWNER", deviceId=device_id)
        if owners:
            if owners[0]["owner"] != practitioner_id:
                raise Conflict("device is registered to another practitioner")
            return
        try:
            await self._run(
                "Q-DEVICE-REGISTER",
                key=_key(practitioner_id),
                deviceId=device_id,
                status=_STATUS_ACTIVE,
                at=registered_at,
            )
        except ConstraintError as error:
            raise Conflict("device is already registered") from error

    async def known(self, practitioner_id: str, device_id: str) -> bool:
        rows = await self._run("Q-DEVICE-KNOWN", key=_key(practitioner_id), deviceId=device_id)
        return bool(rows) and int(rows[0]["n"]) > 0

    async def revoke_all(self, practitioner_id: str) -> None:
        await self._run("Q-DEVICE-REVOKE", key=_key(practitioner_id), revoked=_STATUS_REVOKED)

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, REGISTRY.get(query_id), **params)
