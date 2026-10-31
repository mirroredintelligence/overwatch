"""Neo4j stores for PIN credentials and devices (P16, DEC-044, DEC-070).

Layout:
- (:Practitioner)-[:HAS_CREDENTIAL]->(:Credential {deviceId, pinHash, failed, locked, lastOutcome,
  updatedAt}). One credential per practitioner and device. Only the keyed PIN hash is stored; the
  PIN itself never reaches this module. `locked` is the lock from DEC-044 item 2, which has no end
  time: it lasts until a verified text code resets it.
- (:Practitioner)-[:HAS_DEVICE]->(:Device {id, status, registeredAt, revokedAt}). Device ids are
  unique in the graph (migration 0023). A device belongs to one practitioner.
- (:Device {id, tenantId, deviceType: 'wall-display', status, deviceName, locationName, boardScope,
  tokenHash, pairedAt, lastSeenAt, revokedAt, updatedAt}): a paired wall screen (U10, DEC-160,
  W9I). It hangs from no practitioner and
  carries `deviceType`, which a practitioner's device never has, so the two kinds never match each
  other's statements. It is not a Resource node: it holds a token hash and a pairing status that
  are not FHIR elements, and nothing reads it through the resource store. `tokenHash` is the keyed
  hash of the device token, never the token. An absent property is an absent value.

Reads of a PIN state take the credential's write lock first (lesson L73), so an attempt that reads
the failure count and the save that follows it cannot interleave with another attempt on the same
device, provided the caller runs both in one unit of work.

Times are written by the database in UTC, or passed in as aware instants and written in UTC.
Neo4j stores no null property (lesson L74): a cleared value is absent, and readers treat it as None.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

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
from diucs.application.ports.outbound.identity import DeviceFacts
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from diucs.domain.rules.identity_policy import PinOutcome, PinState

_PRACTITIONER_KEY: Final = "Practitioner/{}"
_STATUS_ACTIVE: Final = "active"
_STATUS_REVOKED: Final = "revoked"
_STATUS_PENDING: Final = "pending-callback"
_WALL_DISPLAY: Final = DeviceType.WALL_DISPLAY.value

# Scenarios of the converted statements (DEC-142 item 5, DEC-150). Both tenants have a practitioner
# with the same id and key, and a credential with the same device id: the keys are composite
# (tenantId plus the key, migration 0031), so the two tenants share them and every statement is
# proved with colliding keys (TEN-005). A practitioner is written by the resource store, which
# stamps the tenant since TEN-009; the scenarios seed it stamped the same way.
_PRACTITIONER: Final = SeedNode(
    "practitioner",
    ("Resource", "Practitioner"),
    {
        "id": "prac-1",
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
                "deviceId": "dev-1",
                "pinHash": Marked("hash"),
                "failed": 1,
                "locked": False,
            },
        ),
    ),
    rels=(SeedRel("practitioner", "HAS_CREDENTIAL", "credential"),),
)
_KEY: Final = "Practitioner/prac-1"
_DEVICE: Final = "dev-1"
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
        "deviceId": "dev-new",
        "pinHash": "hash-new",
    },
    lookup=("key",),
    new=("deviceId", "pinHash"),
    expect=Expect(
        rows=({"n": 1},),
        nodes={"Credential": 1},
        rels={"HAS_CREDENTIAL": 1},
        after=(
            NodeSpec(
                ("Credential",),
                {
                    "deviceId": "dev-new",
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
    new=("failed", "lastOutcome"),
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

# The practitioner's devices (P16, TEN-014). The device hangs from the practitioner, so the seed
# holds both, with the same ids and keys in both tenants. Nothing in the seed differs between the
# tenants, so a row or a node that came from the other tenant shows as a count, not as text.
_AT: Final = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
_DEVICE_NODE: Final = SeedNode(
    "device",
    ("Device",),
    {"id": _DEVICE, "status": _STATUS_ACTIVE, "registeredAt": _AT},
)
_DEVICE_SEED: Final = TenantSeed(
    nodes=(_PRACTITIONER, _DEVICE_NODE),
    rels=(SeedRel("practitioner", "HAS_DEVICE", "device"),),
)
_LOCK_SCENARIO: Final = Scenario(
    "lock a practitioner before a device is registered for it",
    seed=_DEVICE_SEED,
    params={"key": _KEY},
    lookup=("key",),
    expect=Expect(rows=({"n": 1},)),
)
_OWNER_SCENARIO: Final = Scenario(
    "read the practitioner who holds a device",
    seed=_DEVICE_SEED,
    params={"deviceId": _DEVICE},
    lookup=("deviceId",),
    expect=Expect(rows=({"owner": "prac-1"},)),
)
_REGISTER_SCENARIO: Final = Scenario(
    "register a new device for a practitioner",
    seed=_DEVICE_SEED,
    params={"key": _KEY, "deviceId": "dev-new", "status": _STATUS_ACTIVE, "at": _AT},
    lookup=("key",),
    new=("deviceId", "at"),
    expect=Expect(
        rows=({"n": 1},),
        nodes={"Device": 1},
        rels={"HAS_DEVICE": 1},
        after=(NodeSpec(("Device",), {"id": "dev-new", "status": _STATUS_ACTIVE}),),
    ),
)
_KNOWN_SCENARIO: Final = Scenario(
    "count the active devices of a practitioner that are not revoked and have an id",
    seed=_DEVICE_SEED,
    params={"key": _KEY, "deviceId": _DEVICE, "active": _STATUS_ACTIVE},
    lookup=("key", "deviceId"),
    expect=Expect(rows=({"n": 1},)),
)
_ACTIVE_COUNT_SCENARIO: Final = Scenario(
    "count the active devices of a practitioner that are not revoked",
    seed=_DEVICE_SEED,
    params={"key": _KEY, "active": _STATUS_ACTIVE},
    lookup=("key",),
    expect=Expect(rows=({"n": 1},)),
)
_REVOKE_SCENARIO: Final = Scenario(
    "revoke the devices of a practitioner",
    seed=_DEVICE_SEED,
    params={"key": _KEY, "revoked": _STATUS_REVOKED},
    lookup=("key",),
    new=("revoked",),
    expect=Expect(
        rows=({"n": 1},),
        after=(NodeSpec(("Device",), {"id": _DEVICE, "status": _STATUS_REVOKED}),),
    ),
)

_PENDING_DEVICE_NODE: Final = SeedNode(
    "device",
    ("Device",),
    {"id": _DEVICE, "status": _STATUS_PENDING, "registeredAt": _AT},
)
_PENDING_SEED: Final = TenantSeed(
    nodes=(_PRACTITIONER, _PENDING_DEVICE_NODE),
    rels=(SeedRel("practitioner", "HAS_DEVICE", "device"),),
)
_CONFIRM_SCENARIO: Final = Scenario(
    "make the pending-callback devices of a practitioner active",
    seed=_PENDING_SEED,
    params={
        "key": _KEY,
        "pending": _STATUS_PENDING,
        "active": _STATUS_ACTIVE,
        "at": _AT + timedelta(minutes=5),
    },
    lookup=("key",),
    new=("at", "active"),
    expect=Expect(
        rows=({"n": 1},),
        after=(NodeSpec(("Device",), {"id": _DEVICE, "status": _STATUS_ACTIVE}),),
    ),
)
_AWAITING_SCENARIO: Final = Scenario(
    "list the pending-callback devices of a practitioner that are not revoked",
    seed=_PENDING_SEED,
    params={"key": _KEY, "pending": _STATUS_PENDING},
    lookup=("key",),
    expect=Expect(rows=({"id": _DEVICE},)),
)

# The list of a practitioner's devices (W7B C). The device's status text differs between the tenants
# (`Marked`), so a row that came from the other tenant looks different.
_LISTED_DEVICE_NODE: Final = SeedNode(
    "device",
    ("Device",),
    {
        "id": _DEVICE,
        "status": Marked("active"),
        "registeredAt": _AT,
        "lastVerifiedAt": _AT + timedelta(minutes=5),
    },
)
_LIST_SCENARIO: Final = Scenario(
    "list the devices of a practitioner that are not revoked",
    seed=TenantSeed(
        nodes=(_PRACTITIONER, _LISTED_DEVICE_NODE),
        rels=(SeedRel("practitioner", "HAS_DEVICE", "device"),),
    ),
    params={"key": _KEY},
    lookup=("key",),
    expect=Expect(rows=({"id": _DEVICE, "status": Marked("active")},)),
)
_MARK_VERIFIED_SCENARIO: Final = Scenario(
    "stamp the last text-code verification on a practitioner's device that is not revoked",
    seed=_DEVICE_SEED,
    params={"key": _KEY, "deviceId": _DEVICE, "at": _AT + timedelta(minutes=5)},
    lookup=("key", "deviceId"),
    new=("at",),
    expect=Expect(
        rows=({"n": 1},),
        after=(NodeSpec(("Device",), {"id": _DEVICE, "status": _STATUS_ACTIVE}),),
    ),
)
_VERIFIED_SCENARIO: Final = Scenario(
    "read the last text-code verification of a practitioner's device that is not revoked",
    seed=_DEVICE_SEED,
    params={"key": _KEY, "deviceId": _DEVICE},
    lookup=("key", "deviceId"),
    expect=Expect(rows=({"id": _DEVICE},)),
)

# The wall screen statements (U10, DEC-160). Both tenants hold a screen with the same id, type and
# token hash (the keys are composite since TEN-005), so a statement that forgot the tenant finds the
# other tenant's screen.
_SCREEN_HASH: Final = "e" * 64
_SCREEN_TIME: Final = datetime(2026, 10, 30, 10, 0, tzinfo=UTC)
_SCREEN: Final = SeedNode(
    "screen",
    ("Device",),
    {
        "id": "screen-1",
        "deviceType": _WALL_DISPLAY,
        "status": "active",
        "deviceName": Marked("Ward 4 corridor"),
        "boardScope": "tenant",
        "boardScopeVersion": 1,
        "tokenHash": _SCREEN_HASH,
    },
)
_SCREEN_SEED: Final = TenantSeed(nodes=(_SCREEN,))
_SCREEN_GET_SCENARIO: Final = Scenario(
    "read and lock the wall screen of the tenant by id",
    seed=_SCREEN_SEED,
    params={"id": "screen-1", "type": _WALL_DISPLAY},
    lookup=("id", "type"),
    expect=Expect(
        rows=(
            {
                "id": "screen-1",
                "status": "active",
                "name": Marked("Ward 4 corridor"),
                "boardScope": "tenant",
                "scopeVersion": 1,
                "tokenHash": _SCREEN_HASH,
            },
        )
    ),
)
_SCREEN_PEEK_SCENARIO: Final = Scenario(
    "read the wall screen of the tenant by id, without taking its lock",
    seed=_SCREEN_SEED,
    params={"id": "screen-1", "type": _WALL_DISPLAY},
    lookup=("id", "type"),
    expect=Expect(
        rows=(
            {
                "id": "screen-1",
                "status": "active",
                "name": Marked("Ward 4 corridor"),
                "boardScope": "tenant",
                "scopeVersion": 1,
            },
        )
    ),
)
_SCREEN_LIST_SCENARIO: Final = Scenario(
    "list the wall screens of the tenant",
    seed=_SCREEN_SEED,
    params={"type": _WALL_DISPLAY},
    lookup=("type",),
    expect=Expect(
        rows=(
            {
                "id": "screen-1",
                "status": "active",
                "name": Marked("Ward 4 corridor"),
                "boardScope": "tenant",
                "scopeVersion": 1,
            },
        )
    ),
)
_SCREEN_SAVE_SCENARIO: Final = Scenario(
    "replace the wall screen of the tenant with this id",
    seed=_SCREEN_SEED,
    params={
        "id": "screen-1",
        "type": _WALL_DISPLAY,
        "status": "revoked",
        "name": "Renamed corridor",
        "location": "Level 3",
        "boardScope": "network",
        "networkId": "net-dorset",
        "scopeVersion": 2,
        "tokenHash": "f" * 64,
        "pairedAt": _SCREEN_TIME,
        "lastSeenAt": _SCREEN_TIME,
        "revokedAt": _SCREEN_TIME,
    },
    lookup=("id", "type"),
    new=(
        "status",
        "name",
        "location",
        "boardScope",
        "networkId",
        "scopeVersion",
        "tokenHash",
        "pairedAt",
        "lastSeenAt",
        "revokedAt",
    ),
    expect=Expect(
        rows=({"n": 1},),
        after=(
            NodeSpec(
                ("Device",),
                {
                    "id": "screen-1",
                    "status": "revoked",
                    "deviceName": "Renamed corridor",
                    "locationName": "Level 3",
                    "boardScope": "network",
                    "networkId": "net-dorset",
                    "boardScopeVersion": 2,
                    "tokenHash": "f" * 64,
                    "pairedAt": _SCREEN_TIME,
                    "lastSeenAt": _SCREEN_TIME,
                    "revokedAt": _SCREEN_TIME,
                },
            ),
        ),
    ),
)
_SCREEN_BY_TOKEN_SCENARIO: Final = Scenario(
    "find the active wall screen of the tenant by the hash of its token",
    seed=_SCREEN_SEED,
    params={"tokenHash": _SCREEN_HASH, "type": _WALL_DISPLAY, "status": "active"},
    lookup=("tokenHash", "type", "status"),
    expect=Expect(
        rows=({"id": "screen-1", "status": "active", "name": Marked("Ward 4 corridor")},)
    ),
)
_SCREEN_SEEN_SCENARIO: Final = Scenario(
    "confirm the wall screen of the tenant is active and mark it seen when it is stale",
    seed=_SCREEN_SEED,
    params={
        "id": "screen-1",
        "type": _WALL_DISPLAY,
        "seenAt": _SCREEN_TIME,
        "staleBefore": _SCREEN_TIME,
    },
    lookup=("id", "type"),
    new=("seenAt", "staleBefore"),
    expect=Expect(
        rows=({"status": "active"},),
        after=(NodeSpec(("Device",), {"id": "screen-1", "lastSeenAt": _SCREEN_TIME}),),
    ),
)
_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-CRED-PRACTITIONER-EXISTS": _EXISTS_SCENARIO,
    "Q-CRED-SET": _SET_SCENARIO,
    "Q-CRED-GET": _GET_SCENARIO,
    "Q-CRED-SAVE-STATE": _SAVE_STATE_SCENARIO,
    "Q-CRED-CLEAR": _CLEAR_SCENARIO,
    "Q-DEVICE-LOCK": _LOCK_SCENARIO,
    "Q-DEVICE-OWNER": _OWNER_SCENARIO,
    "Q-DEVICE-REGISTER": _REGISTER_SCENARIO,
    "Q-DEVICE-KNOWN": _KNOWN_SCENARIO,
    "Q-DEVICE-ACTIVE-COUNT": _ACTIVE_COUNT_SCENARIO,
    "Q-DEVICE-REVOKE": _REVOKE_SCENARIO,
    "Q-DEVICE-CONFIRM-PENDING": _CONFIRM_SCENARIO,
    "Q-DEVICE-AWAITING": _AWAITING_SCENARIO,
    "Q-DEVICE-LIST": _LIST_SCENARIO,
    "Q-DEVICE-MARK-VERIFIED": _MARK_VERIFIED_SCENARIO,
    "Q-DEVICE-VERIFIED": _VERIFIED_SCENARIO,
    "Q-SCREEN-GET": _SCREEN_GET_SCENARIO,
    "Q-SCREEN-PEEK": _SCREEN_PEEK_SCENARIO,
    "Q-SCREEN-LIST": _SCREEN_LIST_SCENARIO,
    "Q-SCREEN-SAVE": _SCREEN_SAVE_SCENARIO,
    "Q-SCREEN-BY-TOKEN": _SCREEN_BY_TOKEN_SCENARIO,
    "Q-SCREEN-SEEN": _SCREEN_SEEN_SCENARIO,
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
        "MATCH (p:Practitioner {key: $key, tenantId: $tenant}) "
        "SET p.key = p.key RETURN count(p) AS n",
        "write",
    ),
    "Q-DEVICE-OWNER": (
        "MATCH (p:Practitioner {tenantId: $tenant})-[:HAS_DEVICE]->"
        "(d:Device {id: $deviceId, tenantId: $tenant}) RETURN p.id AS owner",
        "read",
    ),
    "Q-DEVICE-REGISTER": (
        "MATCH (p:Practitioner {key: $key, tenantId: $tenant}) "
        "CREATE (p)-[:HAS_DEVICE]->(:Device {id: $deviceId, tenantId: $tenant, "
        "status: $status, registeredAt: $at}) "
        "RETURN count(*) AS n",
        "write",
    ),
    # Known means active: a revoked device, and one that waits for the lead's call-back (U37), is
    # not known, so it cannot sign in.
    "Q-DEVICE-KNOWN": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_DEVICE]->"
        "(d:Device {id: $deviceId, tenantId: $tenant}) "
        "WHERE d.revokedAt IS NULL AND d.status = $active RETURN count(d) AS n",
        "read",
    ),
    # The devices a practitioner can sign in on now: the same test as Q-DEVICE-KNOWN, over every
    # device of the practitioner (W7C: how many other phones are signed in).
    "Q-DEVICE-ACTIVE-COUNT": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_DEVICE]->"
        "(d:Device {tenantId: $tenant}) "
        "WHERE d.revokedAt IS NULL AND d.status = $active RETURN count(d) AS n",
        "read",
    ),
    "Q-DEVICE-CONFIRM-PENDING": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_DEVICE]->"
        "(d:Device {tenantId: $tenant, status: $pending}) WHERE d.revokedAt IS NULL "
        "SET d.status = $active, d.confirmedAt = $at RETURN count(d) AS n",
        "write",
    ),
    "Q-DEVICE-AWAITING": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_DEVICE]->"
        "(d:Device {tenantId: $tenant, status: $pending}) WHERE d.revokedAt IS NULL "
        "RETURN d.id AS id ORDER BY d.id",
        "read",
    ),
    "Q-DEVICE-LIST": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_DEVICE]->"
        "(d:Device {tenantId: $tenant}) WHERE d.revokedAt IS NULL "
        "RETURN d.id AS id, d.status AS status, d.registeredAt AS registeredAt, "
        "d.lastVerifiedAt AS verifiedAt ORDER BY d.registeredAt, d.id",
        "read",
    ),
    # The last text-code verification of a device (U32): the 30-day check and the 10 minutes in
    # which a PIN may be set both read it. A revoked device is never stamped or read.
    "Q-DEVICE-MARK-VERIFIED": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_DEVICE]->"
        "(d:Device {id: $deviceId, tenantId: $tenant}) WHERE d.revokedAt IS NULL "
        "SET d.lastVerifiedAt = $at RETURN count(d) AS n",
        "write",
    ),
    "Q-DEVICE-VERIFIED": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_DEVICE]->"
        "(d:Device {id: $deviceId, tenantId: $tenant}) WHERE d.revokedAt IS NULL "
        "RETURN d.id AS id, d.lastVerifiedAt AS at",
        "read",
    ),
    "Q-DEVICE-REVOKE": (
        "MATCH (:Practitioner {key: $key, tenantId: $tenant})-[:HAS_DEVICE]->"
        "(d:Device {tenantId: $tenant}) WHERE d.revokedAt IS NULL "
        "SET d.status = $revoked, d.revokedAt = datetime({timezone: 'UTC'}) "
        "RETURN count(d) AS n",
        "write",
    ),
    # A wall screen (U10). The self-SET takes the screen's write lock before the properties are read
    # (lesson L73, L85), so a read that judges a single-use change cannot interleave with another.
    "Q-SCREEN-GET": (
        "MATCH (d:Device {id: $id, tenantId: $tenant, deviceType: $type}) "
        "SET d.id = d.id "
        "RETURN d.id AS id, d.status AS status, d.deviceName AS name, "
        "d.locationName AS location, d.deviceType AS deviceType, d.boardScope AS boardScope, "
        "d.networkId AS networkId, coalesce(d.boardScopeVersion, 1) AS scopeVersion, "
        "d.tokenHash AS tokenHash, d.pairedAt AS pairedAt, d.lastSeenAt AS lastSeenAt, "
        "d.revokedAt AS revokedAt",
        "write",
    ),
    # The same read without the lock, for the board reads of a wall screen (TEN-067): a screen asks
    # for its setting on every refresh, and a read that judges nothing single-use needs no lock.
    "Q-SCREEN-PEEK": (
        "MATCH (d:Device {id: $id, tenantId: $tenant, deviceType: $type}) "
        "RETURN d.id AS id, d.status AS status, d.deviceName AS name, "
        "d.locationName AS location, d.deviceType AS deviceType, d.boardScope AS boardScope, "
        "d.networkId AS networkId, coalesce(d.boardScopeVersion, 1) AS scopeVersion, "
        "d.tokenHash AS tokenHash, d.pairedAt AS pairedAt, d.lastSeenAt AS lastSeenAt, "
        "d.revokedAt AS revokedAt",
        "read",
    ),
    "Q-SCREEN-LIST": (
        "MATCH (d:Device {tenantId: $tenant, deviceType: $type}) "
        "RETURN d.id AS id, d.status AS status, d.deviceName AS name, "
        "d.locationName AS location, d.deviceType AS deviceType, d.boardScope AS boardScope, "
        "d.networkId AS networkId, coalesce(d.boardScopeVersion, 1) AS scopeVersion, "
        "d.tokenHash AS tokenHash, d.pairedAt AS pairedAt, d.lastSeenAt AS lastSeenAt, "
        "d.revokedAt AS revokedAt "
        "ORDER BY d.deviceName, d.id",
        "read",
    ),
    # The type is in the MERGE key, so a practitioner's device with this id (it has no type) is
    # never matched: the MERGE tries to create, the unique id refuses it, and nothing changes. A
    # null parameter removes the property, so no null is ever stored.
    "Q-SCREEN-SAVE": (
        "MERGE (d:Device {id: $id, tenantId: $tenant, deviceType: $type}) "
        "SET d.status = $status, d.deviceName = $name, d.locationName = $location, "
        "d.boardScope = $boardScope, d.networkId = $networkId, "
        "d.boardScopeVersion = $scopeVersion, d.tokenHash = $tokenHash, "
        "d.pairedAt = $pairedAt, d.lastSeenAt = $lastSeenAt, d.revokedAt = $revokedAt, "
        "d.updatedAt = datetime({timezone: 'UTC'}) "
        "RETURN count(d) AS n",
        "write",
    ),
    # The edge's question about a wall token (W9I): is this screen still active? It answers with the
    # status as it is, and sets the last seen time only for an active screen whose time is absent or
    # older than $staleBefore, so a screen that reads every minute is written about every half
    # minute at most. A status that is not active is never written (a revoked screen stays as the
    # lead left it). A value of NULL in the CASE's other arm leaves the property as it was.
    "Q-SCREEN-SEEN": (
        "MATCH (d:Device {id: $id, tenantId: $tenant, deviceType: $type}) "
        "WITH d, d.status AS status "
        "SET d.lastSeenAt = CASE WHEN status = 'active' AND "
        "(d.lastSeenAt IS NULL OR d.lastSeenAt < $staleBefore) THEN $seenAt "
        "ELSE d.lastSeenAt END "
        "RETURN status",
        "write",
    ),
    "Q-SCREEN-BY-TOKEN": (
        "MATCH (d:Device {tokenHash: $tokenHash, tenantId: $tenant, deviceType: $type, "
        "status: $status}) "
        "RETURN d.id AS id, d.status AS status, d.deviceName AS name, "
        "d.locationName AS location, d.deviceType AS deviceType, d.boardScope AS boardScope, "
        "d.networkId AS networkId, coalesce(d.boardScopeVersion, 1) AS scopeVersion, "
        "d.tokenHash AS tokenHash, d.pairedAt AS pairedAt, d.lastSeenAt AS lastSeenAt, "
        "d.revokedAt AS revokedAt",
        "read",
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


def _native(stamp: Any) -> datetime:
    """A stored Neo4j datetime as an aware UTC datetime."""
    native: datetime = stamp.to_native() if hasattr(stamp, "to_native") else stamp
    return native.astimezone(UTC)


def _pin_state(row: dict[str, Any]) -> PinState:
    last = row["lastOutcome"]
    return PinState(
        failed_tries=int(row["failed"] or 0),
        locked=bool(row["locked"]),
        last_outcome=PinOutcome(last) if last is not None else None,
    )


class Neo4jPinStore:
    def __init__(self, tx: ScopedTx) -> None:
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


def _instant(value: Any) -> datetime | None:
    if value is None:
        return None
    native: datetime = value.to_native() if hasattr(value, "to_native") else value
    return native.astimezone(UTC)


def _screen(row: dict[str, Any]) -> Device:
    return Device(
        id=str(row["id"]),
        status=DeviceStatus(row["status"]),
        name=str(row["name"]),
        location=None if row["location"] is None else str(row["location"]),
        device_type=DeviceType(row["deviceType"]),
        token_hash=None if row["tokenHash"] is None else str(row["tokenHash"]),
        board_scope=BoardScope(row["boardScope"]),
        network_id=None if row["networkId"] is None else str(row["networkId"]),
        scope_version=int(row["scopeVersion"]),
        paired_at=_instant(row["pairedAt"]),
        last_seen_at=_instant(row["lastSeenAt"]),
        revoked_at=_instant(row["revokedAt"]),
    )


class Neo4jDeviceRegistry:
    def __init__(self, tx: ScopedTx) -> None:
        self._tx = tx

    async def register(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        """Record a device for the practitioner. Registering a device again for the same
        practitioner changes nothing, so a revoked device stays revoked. A device id that belongs
        to another practitioner is Conflict. A practitioner who does not exist is NotFound. Every
        check runs before the write."""
        await self._register(practitioner_id, device_id, at, _STATUS_ACTIVE)

    async def register_pending(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        """As `register`, for a device that waits for the lead's call-back (U37): it is stored
        `pending-callback`, which is not known until `confirm_pending`."""
        await self._register(practitioner_id, device_id, at, _STATUS_PENDING)

    async def _register(
        self, practitioner_id: str, device_id: str, at: datetime, status: str
    ) -> None:
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
                status=status,
                at=registered_at,
            )
        except ConstraintError as error:
            raise Conflict("device is already registered") from error

    async def known(self, practitioner_id: str, device_id: str) -> bool:
        rows = await self._run(
            "Q-DEVICE-KNOWN", key=_key(practitioner_id), deviceId=device_id, active=_STATUS_ACTIVE
        )
        return bool(rows) and int(rows[0]["n"]) > 0

    async def count_active(self, practitioner_id: str) -> int:
        rows = await self._run(
            "Q-DEVICE-ACTIVE-COUNT", key=_key(practitioner_id), active=_STATUS_ACTIVE
        )
        return int(rows[0]["n"]) if rows else 0

    async def revoke_all(self, practitioner_id: str) -> int:
        rows = await self._run(
            "Q-DEVICE-REVOKE", key=_key(practitioner_id), revoked=_STATUS_REVOKED
        )
        return int(rows[0]["n"]) if rows else 0

    async def confirm_pending(self, practitioner_id: str, at: datetime) -> int:
        rows = await self._run(
            "Q-DEVICE-CONFIRM-PENDING",
            key=_key(practitioner_id),
            pending=_STATUS_PENDING,
            active=_STATUS_ACTIVE,
            at=_utc(at, "at"),
        )
        return int(rows[0]["n"]) if rows else 0

    async def awaiting_callback(self, practitioner_id: str) -> list[str]:
        rows = await self._run(
            "Q-DEVICE-AWAITING", key=_key(practitioner_id), pending=_STATUS_PENDING
        )
        return [str(row["id"]) for row in rows]

    async def devices_of(self, practitioner_id: str) -> list[DeviceFacts]:
        rows = await self._run("Q-DEVICE-LIST", key=_key(practitioner_id))
        return [
            DeviceFacts(
                device_id=str(row["id"]),
                status=str(row["status"]),
                registered_at=_native(row["registeredAt"]),
                last_verified_at=None if row["verifiedAt"] is None else _native(row["verifiedAt"]),
            )
            for row in rows
        ]

    async def owner_of(self, device_id: str) -> str | None:
        rows = await self._run("Q-DEVICE-OWNER", deviceId=device_id)
        if len(rows) > 1:
            # One device id with two holders cannot be told apart: refuse, never pick one.
            raise Conflict("more than one practitioner holds this device")
        return str(rows[0]["owner"]) if rows else None

    async def mark_verified(self, practitioner_id: str, device_id: str, at: datetime) -> None:
        """Stamp the device's last text-code verification. A device that is not the
        practitioner's, not registered or revoked is left alone."""
        await self._run(
            "Q-DEVICE-MARK-VERIFIED",
            key=_key(practitioner_id),
            deviceId=device_id,
            at=_utc(at, "at"),
        )

    async def verified_at(self, practitioner_id: str, device_id: str) -> datetime | None:
        rows = await self._run("Q-DEVICE-VERIFIED", key=_key(practitioner_id), deviceId=device_id)
        if not rows or rows[0]["at"] is None:
            return None
        stamp = rows[0]["at"]
        native: datetime = stamp.to_native() if hasattr(stamp, "to_native") else stamp
        return native.astimezone(UTC)

    async def get(self, device_id: str) -> Device | None:
        rows = await self._run("Q-SCREEN-GET", id=device_id, type=_WALL_DISPLAY)
        return _screen(rows[0]) if rows else None

    async def save(self, device: Device) -> None:
        try:
            await self._run(
                "Q-SCREEN-SAVE",
                id=device.id,
                type=device.device_type.value,
                status=device.status.value,
                name=device.name,
                location=device.location,
                boardScope=device.board_scope.value,
                networkId=device.network_id,
                scopeVersion=device.scope_version,
                tokenHash=device.token_hash,
                pairedAt=device.paired_at,
                lastSeenAt=device.last_seen_at,
                revokedAt=device.revoked_at,
            )
        except ConstraintError as error:
            # The id belongs to a device that is not a wall screen of this tenant. The write is
            # refused and nothing is stored.
            raise Conflict("device already exists") from error

    async def peek(self, device_id: str) -> Device | None:
        rows = await self._run("Q-SCREEN-PEEK", id=device_id, type=_WALL_DISPLAY)
        return _screen(rows[0]) if rows else None

    async def list_screens(self) -> list[Device]:
        rows = await self._run("Q-SCREEN-LIST", type=_WALL_DISPLAY)
        return [_screen(row) for row in rows]

    async def confirm_active(
        self, device_id: str, seen_at: datetime, refresh_after: timedelta
    ) -> bool:
        rows = await self._run(
            "Q-SCREEN-SEEN",
            id=device_id,
            type=_WALL_DISPLAY,
            seenAt=_utc(seen_at, "seen_at"),
            staleBefore=_utc(seen_at, "seen_at") - refresh_after,
        )
        return bool(rows) and rows[0]["status"] == DeviceStatus.ACTIVE.value

    async def find_by_token_hash(self, token_hash: str) -> Device | None:
        rows = await self._run(
            "Q-SCREEN-BY-TOKEN",
            tokenHash=token_hash,
            type=_WALL_DISPLAY,
            status=DeviceStatus.ACTIVE.value,
        )
        if len(rows) > 1:
            # A duplicate hash would let a token be read as one of two screens: refuse, never pick.
            raise Conflict("more than one screen has this token")
        return _screen(rows[0]) if rows else None

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, REGISTRY.get(query_id), **params)
