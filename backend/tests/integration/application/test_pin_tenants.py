"""Two-tenant tests for PIN sign-in (U32, DEC-130 to DEC-132, DEC-142).

Tenant A and tenant B each hold a practitioner `prac-1` with a device `dev-1`, and each has its own
PIN. A's sign-in reads and changes A's credential only; B's failed count does not move; A's PIN is
wrong in B; a practitioner of B given to A's sign-in answers as an unknown person does (needs a text
code). Runs on the shared harness database (the contracted schema, DEC-159).

NOT RUN in the build wave: the batch verification run proves it.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

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
from diucs.domain.model.people import Practitioner
from tests.support.registration_rig import StubLimiter
from tests.support.uow import ensure_audit_heads, tenant_uow_factory

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
SECRETS = FixedSecretStore({PIN_HMAC_SECRET: b"pin-hmac-test-secret-0123456789abcdef"})
PIN_A = "482913"
PIN_B = "135790"


async def _set_up(factory: UnitOfWorkFactory, pin: str) -> None:
    clock = FixedClock(NOW)
    async with factory() as uow:
        await uow.people.save_practitioner(
            Practitioner(id="prac-1", active=True, display_name="Sample", phone_hash=None)
        )
        await uow.commit()
    stamp = NOW - timedelta(minutes=1)
    await RecordTextCodeVerified(factory, clock).execute(
        RecordTextCodeVerifiedCommand("prac-1", "dev-1", stamp, "setup")
    )
    await SetPin(factory, SECRETS, clock, StubLimiter()).execute(
        SetPinCommand("prac-1", "dev-1", pin, stamp)
    )


@pytest_asyncio.fixture(loop_scope="session")
async def two_tenants(
    tenant_id: str, other_tenant_id: str, neo4j_driver: AsyncDriver, clean_graph: None
) -> AsyncIterator[tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory]]:
    driver = neo4j_driver
    await ensure_audit_heads(driver, tenant_id, other_tenant_id)
    factory_a = tenant_uow_factory(driver, tenant_id)
    factory_b = tenant_uow_factory(driver, other_tenant_id)
    await _set_up(factory_a, PIN_A)
    await _set_up(factory_b, PIN_B)
    yield driver, factory_a, factory_b


def _sign_in(factory: UnitOfWorkFactory) -> PinSignIn:
    return PinSignIn(factory, SECRETS, FixedClock(NOW), StubLimiter())


async def test_each_tenant_signs_in_with_its_own_pin_and_the_other_tenants_pin_is_wrong(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    _, factory_a, factory_b = two_tenants

    own_a = await _sign_in(factory_a).execute(PinSignInCommand("prac-1", "dev-1", PIN_A))
    own_b = await _sign_in(factory_b).execute(PinSignInCommand("prac-1", "dev-1", PIN_B))
    a_in_b = await _sign_in(factory_b).execute(PinSignInCommand("prac-1", "dev-1", PIN_A))

    assert own_a.ok is True
    assert own_b.ok is True
    assert a_in_b.ok is False
    assert a_in_b.tries_left == 4


async def test_a_wrong_pin_in_b_changes_b_only(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    _, factory_a, factory_b = two_tenants

    await _sign_in(factory_b).execute(PinSignInCommand("prac-1", "dev-1", PIN_A))

    async with factory_a() as uow:
        held_a = await uow.pins.get("prac-1", "dev-1")
    async with factory_b() as uow:
        held_b = await uow.pins.get("prac-1", "dev-1")
    assert held_a is not None and held_a[1].failed_tries == 0
    assert held_b is not None and held_b[1].failed_tries == 1


async def test_a_practitioner_of_another_tenant_answers_as_an_unknown_person(
    two_tenants: tuple[AsyncDriver, UnitOfWorkFactory, UnitOfWorkFactory],
) -> None:
    _, factory_a, _ = two_tenants

    result = await _sign_in(factory_a).execute(PinSignInCommand("prac-only-in-b", "dev-1", PIN_B))

    assert result.ok is False
    assert result.needs_text_code is True
    assert result.practitioner_id is None
