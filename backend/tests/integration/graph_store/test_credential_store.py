"""Integration tests for PIN credentials and the device registry (P16, DEC-004, DEC-044, DEC-070).

Run against the throwaway Neo4j of the F10 harness. Each write commits in its own transaction and
each read runs in a fresh session. The PIN hashes are synthetic: the raw PIN never reaches the
store, so the tests assert that no stored property holds it.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from neo4j import AsyncDriver, AsyncManagedTransaction
from neo4j.exceptions import ClientError, ConstraintError
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.credential_store import (
    Neo4jDeviceRegistry,
    Neo4jPinStore,
)
from diucs.adapters.outbound.graph_store.migrations import apply_migrations
from diucs.adapters.outbound.graph_store.person_repository import Neo4jPersonRepository
from diucs.adapters.outbound.graph_store.resource_store import ResourceStore
from diucs.application.tenancy import current_tenant
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.people import Practitioner
from diucs.domain.rules.identity_policy import PinOutcome, PinState, pin_attempt
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

AT = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
PIN_HASH = "c" * 64
OTHER_PIN_HASH = "9" * 64
RAW_PIN = "482913"


async def _seed_practitioners(driver: AsyncDriver) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        repo = Neo4jPersonRepository(tx, ResourceStore(tx))
        await repo.save_practitioner(
            Practitioner(id="p1", active=True, display_name="Duty Manager One", phone_hash=None)
        )
        await repo.save_practitioner(
            Practitioner(id="p2", active=True, display_name="Duty Manager Two", phone_hash=None)
        )
        # The resource store does not stamp the tenant yet (TEN-009), and the credential
        # statements match the practitioner by tenant (DEC-151 item 3): stamp what it wrote.
        await tx.run(
            "MATCH (n:Practitioner) WHERE n.tenantId IS NULL SET n.tenantId = $tenant",
            tenant=current_tenant(),
        )

    await write_tx(driver, work)


async def _run(driver: AsyncDriver, step: Any) -> None:
    """Run one step in its own committed write. A step takes the (pin store, device registry)."""

    async def work(tx: AsyncManagedTransaction) -> None:
        await step(Neo4jPinStore(tx), Neo4jDeviceRegistry(tx))

    await write_tx(driver, work)


async def _read(driver: AsyncDriver, step: Any) -> Any:
    """Read in a fresh session. Reads run as writes: a PIN read takes the credential's lock first
    (lesson L73), so it needs a write transaction, as the attempt that follows it does."""

    async def work(tx: AsyncManagedTransaction) -> Any:
        return await step(Neo4jPinStore(tx), Neo4jDeviceRegistry(tx))

    return await write_tx(driver, work)


async def _nodes_holding(driver: AsyncDriver, text: str) -> int:
    """How many nodes hold `text` in one of their properties (a string, or a list of strings)."""
    query = "MATCH (n) RETURN properties(n) AS props"

    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        return await (await tx.run(query)).data()

    holding = 0
    for row in await read_tx(driver, work):
        for value in row["props"].values():
            values = value if isinstance(value, list) else [value]
            if any(isinstance(item, str) and text in item for item in values):
                holding += 1
                break
    return holding


@pytest_asyncio.fixture(loop_scope="session")
async def practitioners(neo4j_driver: AsyncDriver, clean_graph: None) -> None:
    await _seed_practitioners(neo4j_driver)


async def test_set_pin_stores_a_hash_and_get_returns_it_with_a_fresh_state(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda pins, _: pins.set_pin("p1", "dev-1", PIN_HASH))

    got = await _read(neo4j_driver, lambda pins, _: pins.get("p1", "dev-1"))

    assert got == (PIN_HASH, PinState())
    assert (await node_props(neo4j_driver, "Credential", deviceId="dev-1"))["pinHash"] == PIN_HASH


async def test_the_raw_pin_is_in_no_stored_property(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda pins, _: pins.set_pin("p1", "dev-1", PIN_HASH))

    assert await _nodes_holding(neo4j_driver, RAW_PIN) == 0


async def test_save_state_with_five_failures_and_a_lock_persists_the_lock(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    locked = PinState(failed_tries=5, locked=True, last_outcome=PinOutcome.LOCKED)
    await _run(neo4j_driver, lambda pins, _: pins.set_pin("p1", "dev-1", PIN_HASH))
    await _run(neo4j_driver, lambda pins, _: pins.save_state("p1", "dev-1", locked))

    assert await _read(neo4j_driver, lambda pins, _: pins.get("p1", "dev-1")) == (
        PIN_HASH,
        locked,
    )
    props = await node_props(neo4j_driver, "Credential", deviceId="dev-1")
    assert props["failed"] == 5
    assert props["locked"] is True
    assert isinstance(props["updatedAt"], DateTime)


async def test_get_for_an_unknown_device_is_none(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda pins, _: pins.set_pin("p1", "dev-1", PIN_HASH))

    assert await _read(neo4j_driver, lambda pins, _: pins.get("p1", "dev-9")) is None


async def test_save_state_for_a_missing_credential_is_not_found_and_writes_nothing(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jPinStore(tx).save_state("p1", "dev-1", PinState(failed_tries=1))

    with pytest.raises(NotFound):
        await write_tx(neo4j_driver, work)

    assert await count_nodes(neo4j_driver, "Credential") == 0


async def test_clear_all_removes_every_credential_for_the_practitioner(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda pins, _: pins.set_pin("p1", "dev-1", PIN_HASH))
    await _run(neo4j_driver, lambda pins, _: pins.set_pin("p1", "dev-2", PIN_HASH))
    await _run(neo4j_driver, lambda pins, _: pins.set_pin("p2", "dev-3", OTHER_PIN_HASH))

    await _run(neo4j_driver, lambda pins, _: pins.clear_all("p1"))

    assert await _read(neo4j_driver, lambda pins, _: pins.get("p1", "dev-1")) is None
    assert await _read(neo4j_driver, lambda pins, _: pins.get("p1", "dev-2")) is None
    assert await _read(neo4j_driver, lambda pins, _: pins.get("p2", "dev-3")) == (
        OTHER_PIN_HASH,
        PinState(),
    )
    assert await count_nodes(neo4j_driver, "Credential") == 1


async def test_set_pin_for_an_unknown_practitioner_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jPinStore(tx).set_pin("p-unknown", "dev-1", PIN_HASH)

    with pytest.raises(NotFound):
        await write_tx(neo4j_driver, work)

    assert await count_nodes(neo4j_driver, "Credential") == 0


async def test_register_then_known_is_true(neo4j_driver: AsyncDriver, practitioners: None) -> None:
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", AT))

    assert await _read(neo4j_driver, lambda _, devices: devices.known("p1", "dev-1")) is True


async def test_an_unregistered_device_is_not_known(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    assert await _read(neo4j_driver, lambda _, devices: devices.known("p1", "dev-1")) is False


async def test_revoke_all_makes_every_device_of_the_practitioner_unknown(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", AT))
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-2", AT))

    await _run(neo4j_driver, lambda _, devices: devices.revoke_all("p1"))

    assert await _read(neo4j_driver, lambda _, devices: devices.known("p1", "dev-1")) is False
    assert await _read(neo4j_driver, lambda _, devices: devices.known("p1", "dev-2")) is False
    props = await node_props(neo4j_driver, "Device", id="dev-1")
    assert props["status"] == "revoked"
    assert isinstance(props["revokedAt"], DateTime)


async def test_revoke_all_leaves_another_practitioners_device_alone(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", AT))
    await _run(neo4j_driver, lambda _, devices: devices.register("p2", "dev-2", AT))

    await _run(neo4j_driver, lambda _, devices: devices.revoke_all("p1"))

    assert await _read(neo4j_driver, lambda _, devices: devices.known("p2", "dev-2")) is True


async def test_registered_times_are_stored_as_datetimes(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", AT))

    props = await node_props(neo4j_driver, "Device", id="dev-1")

    assert isinstance(props["registeredAt"], DateTime)
    assert props["registeredAt"].to_native() == AT


async def test_a_device_id_belongs_to_one_practitioner(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", AT))

    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jDeviceRegistry(tx).register("p2", "dev-1", LATER)

    with pytest.raises(Conflict):
        await write_tx(neo4j_driver, work)

    assert await count_nodes(neo4j_driver, "Device") == 1
    assert await _read(neo4j_driver, lambda _, devices: devices.known("p1", "dev-1")) is True
    assert await _read(neo4j_driver, lambda _, devices: devices.known("p2", "dev-1")) is False


async def test_registering_the_same_device_again_keeps_the_first_registration(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", AT))
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", LATER))

    assert await count_nodes(neo4j_driver, "Device") == 1
    props = await node_props(neo4j_driver, "Device", id="dev-1")
    assert props["registeredAt"].to_native() == AT


async def test_a_revoked_device_stays_unknown_when_registered_again(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", AT))
    await _run(neo4j_driver, lambda _, devices: devices.revoke_all("p1"))
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", LATER))

    assert await _read(neo4j_driver, lambda _, devices: devices.known("p1", "dev-1")) is False


async def test_register_for_an_unknown_practitioner_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jDeviceRegistry(tx).register("p-unknown", "dev-1", AT)

    with pytest.raises(NotFound):
        await write_tx(neo4j_driver, work)

    assert await count_nodes(neo4j_driver, "Device") == 0


async def test_device_id_is_unique_in_the_graph(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    await _run(neo4j_driver, lambda _, devices: devices.register("p1", "dev-1", AT))

    async def duplicate(tx: AsyncManagedTransaction) -> None:
        await tx.run("CREATE (:Device {id: 'dev-1', status: 'active'})")

    with pytest.raises(ClientError):
        await write_tx(neo4j_driver, duplicate)


async def test_sixteen_concurrent_wrong_pins_lock_the_device_at_five_failures(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    """Each attempt reads the state, judges it and saves it in its own unit of work. Without the
    lock taken by the read, two attempts can read the same count and both be allowed, so more than
    four wrong PINs would get an answer of WRONG."""
    await _run(neo4j_driver, lambda pins, _: pins.set_pin("p1", "dev-1", PIN_HASH))

    async def attempt(_: int) -> PinOutcome | None:
        async def work(tx: AsyncManagedTransaction) -> PinOutcome | None:
            pins = Neo4jPinStore(tx)
            current = await pins.get("p1", "dev-1")
            assert current is not None
            judged = pin_attempt(current[1], ok=False, now=AT)
            await pins.save_state("p1", "dev-1", judged)
            return judged.last_outcome

        return await write_tx(neo4j_driver, work)

    outcomes = await asyncio.gather(*(attempt(n) for n in range(16)))

    assert outcomes.count(PinOutcome.WRONG) == 4
    assert outcomes.count(PinOutcome.LOCKED) == 12
    final = await _read(neo4j_driver, lambda pins, _: pins.get("p1", "dev-1"))
    assert final == (
        PIN_HASH,
        PinState(failed_tries=5, locked=True, last_outcome=PinOutcome.LOCKED),
    )


async def test_a_naive_registration_time_is_refused_and_writes_nothing(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jDeviceRegistry(tx).register("p1", "dev-1", datetime(2026, 10, 25, 11, 0))

    with pytest.raises(ValidationFailed):
        await write_tx(neo4j_driver, work)

    assert await count_nodes(neo4j_driver, "Device") == 0


async def test_racing_registrations_of_one_device_leave_one_device_node(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    """Two practitioners race for one device id. The device-owner check passes for both before
    either writes, so the unique constraint decides: one wins and the other is Conflict."""

    async def register(practitioner_id: str) -> str:
        async def work(tx: AsyncManagedTransaction) -> None:
            await Neo4jDeviceRegistry(tx).register(practitioner_id, "dev-race", AT)

        try:
            await write_tx(neo4j_driver, work)
        except Conflict:
            return "conflict"
        return "registered"

    outcomes = await asyncio.gather(*(register(pid) for pid in ["p1", "p2"] * 8))

    assert await count_nodes(neo4j_driver, "Device") == 1
    assert set(outcomes) <= {"registered", "conflict"}
    assert outcomes.count("registered") >= 1


async def test_racing_register_by_the_same_practitioner_succeeds_and_leaves_one_device(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    """Sixteen racing registrations of one device by one practitioner are one registration, so
    none is refused (DEC-073 item 2)."""

    async def register(_: int) -> None:
        async def work(tx: AsyncManagedTransaction) -> None:
            await Neo4jDeviceRegistry(tx).register("p1", "dev-same", AT)

        await write_tx(neo4j_driver, work)

    await asyncio.gather(*(register(n) for n in range(16)))

    assert await count_nodes(neo4j_driver, "Device") == 1
    assert await _read(neo4j_driver, lambda _, devices: devices.known("p1", "dev-same")) is True


async def test_a_second_credential_for_one_device_is_refused_by_the_schema(
    neo4j_driver: AsyncDriver,
) -> None:
    """Deterministic: a second raw CREATE of a Credential with the same deviceId raises. The schema
    is applied first, so the result does not depend on which test ran before (lesson L92). A
    duplicate Credential would defeat the PIN lockout (DEC-074)."""
    await apply_migrations(neo4j_driver)

    async def create(tx: AsyncManagedTransaction) -> None:
        await tx.run("CREATE (:Credential {deviceId: 'dev-1', pinHash: 'x'})")

    await write_tx(neo4j_driver, create)
    with pytest.raises(ConstraintError):
        await write_tx(neo4j_driver, create)
    assert await count_nodes(neo4j_driver, "Credential") == 1


async def test_a_pin_for_a_device_of_another_practitioner_is_a_conflict(
    neo4j_driver: AsyncDriver, practitioners: None
) -> None:
    """One credential per device in the graph: a second practitioner cannot set a PIN for a device
    that already has one (DEC-074)."""
    await _run(neo4j_driver, lambda pins, _: pins.set_pin("p1", "dev-1", PIN_HASH))

    async def work(tx: AsyncManagedTransaction) -> None:
        await Neo4jPinStore(tx).set_pin("p2", "dev-1", OTHER_PIN_HASH)

    with pytest.raises(Conflict):
        await write_tx(neo4j_driver, work)

    assert await count_nodes(neo4j_driver, "Credential") == 1
    assert await _read(neo4j_driver, lambda pins, _: pins.get("p1", "dev-1")) == (
        PIN_HASH,
        PinState(),
    )
