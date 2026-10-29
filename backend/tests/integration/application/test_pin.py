"""Integration tests for PIN set, sign-in, lock, reset and the 30-day check (U32), against the real
Neo4j the harness starts. Credentials are `Credential` nodes. Each assertion reads back through the
harness helpers or a fresh unit of work. The PINs are samples: no real PIN, no real number.

NOT RUN in the build wave (no Neo4j in the builder's environment, build-wave rules): the batch
verification run proves them.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.pin import (
    PIN_HMAC_SECRET,
    PinSignIn,
    PinSignInCommand,
    RecordTextCodeVerified,
    RecordTextCodeVerifiedCommand,
    SetPin,
    SetPinCommand,
)
from diucs.domain.codes import PractitionerRoleCode, Role, ServiceCategory
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.people import Practitioner, PractitionerRole
from tests.support.neo4j import count_nodes, node_props, read_tx
from tests.support.registration_rig import StubLimiter

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
SECRETS = FixedSecretStore({PIN_HMAC_SECRET: b"pin-hmac-test-secret-0123456789abcdef"})
PIN = "482913"
PERSON = "prac-1"
DEVICE = "dev-1"


class Rig:
    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.uow_factory = uow_factory
        self.clock = FixedClock(NOW)
        limiter = StubLimiter()
        self.set_pin = SetPin(uow_factory, SECRETS, self.clock, limiter)
        self.sign_in = PinSignIn(uow_factory, SECRETS, self.clock, limiter)
        self.record = RecordTextCodeVerified(uow_factory, self.clock)

    async def verified(
        self, ago: timedelta, purpose: str = "setup", device: str = DEVICE
    ) -> datetime:
        stamp = self.clock.now() - ago
        await self.record.execute(RecordTextCodeVerifiedCommand(PERSON, device, stamp, purpose))
        return stamp

    async def set(self, pin: str, stamp: datetime, device: str = DEVICE) -> Any:
        return await self.set_pin.execute(SetPinCommand(PERSON, device, pin, stamp))

    async def sign(self, pin: str, device: str = DEVICE) -> Any:
        return await self.sign_in.execute(PinSignInCommand(PERSON, device, pin))


@pytest.fixture
async def rig(uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None) -> Rig:
    await ensure_audit_head(neo4j_driver)
    async with uow_factory() as uow:
        await uow.scope.save_entry(_entry("svc-west", "UCR West"))
        await uow.scope.save_entry(_entry("svc-east", "UCR East"))
        await uow.people.save_practitioner(
            Practitioner(id=PERSON, active=True, display_name="Sample Reporter", phone_hash=None)
        )
        for number, service in enumerate(("svc-west", "svc-east"), start=1):
            await uow.people.save_role(
                PractitionerRole(
                    id=f"role-{number}",
                    practitioner_id=PERSON,
                    service_id=service,
                    code=PractitionerRoleCode.DUTY_MANAGER,
                    active=True,
                    channel=None,
                    period_start=NOW - timedelta(days=30),
                )
            )
        await uow.commit()
    return Rig(uow_factory)


def _entry(service_id: str, name: str) -> Any:
    from datetime import date

    from diucs.domain.codes import ScopeFlag
    from diucs.domain.model.registration import ScopeEntry

    return ScopeEntry(
        service_id=service_id,
        name=name,
        category=ServiceCategory.URGENT_COMMUNITY_RESPONSE,
        flag=ScopeFlag.IN_PILOT,
        date=date(2026, 10, 29),
    )


async def test_a_pin_is_stored_only_as_a_hash_and_a_pin_after_eleven_minutes_makes_no_credential(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    stamp = await rig.verified(timedelta(minutes=11))
    refused = await rig.set(PIN, stamp)
    assert refused.ok is False
    assert await count_nodes(neo4j_driver, "Credential") == 0

    stamp = await rig.verified(timedelta(minutes=2))
    accepted = await rig.set(PIN, stamp)

    assert accepted.ok is True
    props = await node_props(neo4j_driver, "Credential", deviceId=DEVICE)
    assert props["pinHash"]
    assert PIN not in props["pinHash"]
    assert props["failed"] == 0


@pytest.mark.parametrize("bad", ["48291", "48291a"])
async def test_a_pin_of_the_wrong_format_is_refused_and_no_credential_is_made(
    rig: Rig, neo4j_driver: AsyncDriver, bad: str
) -> None:
    stamp = await rig.verified(timedelta(minutes=1))

    with pytest.raises(ValidationFailed):
        await rig.set(bad, stamp)

    assert await count_nodes(neo4j_driver, "Credential") == 0


async def test_the_right_pin_signs_in_with_both_services_and_another_device_needs_a_code(
    rig: Rig,
) -> None:
    await rig.set(PIN, await rig.verified(timedelta(minutes=1)))

    same = await rig.sign(PIN)
    other = await rig.sign(PIN, "dev-2")

    assert same.ok is True
    assert same.role is Role.REPORTER
    assert same.service_ids == ("svc-east", "svc-west")
    assert other.ok is False
    assert other.needs_text_code is True


async def test_five_wrong_pins_lock_the_credential_and_the_right_pin_then_still_fails(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    await rig.set(PIN, await rig.verified(timedelta(minutes=1)))

    for _ in range(5):
        last = await rig.sign("135790")

    assert (last.locked, last.tries_left) == (True, 0)
    props = await node_props(neo4j_driver, "Credential", deviceId=DEVICE)
    assert props["failed"] == 5
    assert props["locked"] is True
    assert (await rig.sign(PIN)).ok is False


async def test_a_reset_by_text_code_unlocks_and_zeroes_the_count(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    await rig.set(PIN, await rig.verified(timedelta(minutes=1)))
    for _ in range(5):
        await rig.sign("135790")

    stamp = await rig.verified(timedelta(minutes=1), purpose="pin-reset")
    await rig.set("246801", stamp)

    assert (await rig.sign("246801")).ok is True
    props = await node_props(neo4j_driver, "Credential", deviceId=DEVICE)
    assert props["failed"] == 0
    assert props["locked"] is False


async def test_thirty_days_and_a_minute_after_the_last_code_a_new_code_is_needed(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    await rig.set(PIN, await rig.verified(timedelta(minutes=1)))
    rig.clock.advance(timedelta(days=30, minutes=1))

    result = await rig.sign(PIN)

    assert result.needs_text_code is True
    assert result.ok is False


async def test_no_audit_node_holds_a_pin_or_a_hash(rig: Rig, neo4j_driver: AsyncDriver) -> None:
    await rig.set(PIN, await rig.verified(timedelta(minutes=1)))
    await rig.sign("135790")
    await rig.sign(PIN)
    credential = await node_props(neo4j_driver, "Credential", deviceId=DEVICE)

    async def work(tx: Any) -> list[dict[str, Any]]:
        result = await tx.run(
            "MATCH (n) WHERE NOT n:Credential RETURN labels(n) AS labels, properties(n) AS p"
        )
        return await result.data()

    for row in await read_tx(neo4j_driver, work):
        for value in row["p"].values():
            text = str(value)
            assert PIN not in text or row["labels"] == ["ProtectedContact"]
            assert credential["pinHash"] not in text
