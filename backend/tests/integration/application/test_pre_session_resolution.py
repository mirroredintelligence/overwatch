"""The entries that precede a session, on the real registry and store (TEN-041, DEC-520).

Two tenants on the shared harness graph.

- Inbound number: `DirectoryInboundLines` over the real tenant directory resolves an ACTIVE number
  and the account that carries it to its tenant and that tenant's token reference, and nothing
  else: a retired or quarantined number, a number under another account, a suspended tenant's number
  and a number nobody holds all resolve to nobody, with no difference to the caller.
- Device token: a wall screen saved in tenant A is found by its keyed hash in A, and in B it is
  refused with the one refusal every entry gives.

Pairing codes and link pages keep their own cross-tenant tests (U10, R15, L01); the link and
invitation resolvers are in `test_tenancy_link_tokens.py`.

Written in build wave 5 and not run there: the orchestrator runs the full integration suite once on
the merged tip. Synthetic values only.
"""

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET, TenantKeyedSecrets
from diucs.application.ports.outbound.tenant_lines import InboundLine
from diucs.application.ports.outbound.tenants import TenantDirectory, twilio_token_ref
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenant_resolution import (
    ENTRY_REFUSED_MESSAGE,
    DirectoryInboundLines,
    EntryRefused,
    PreSessionResolver,
)
from diucs.bootstrap.container import TEST_NOW, Container
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from diucs.domain.model.tenant import TenantStatus
from diucs.domain.rules.tokens import hash_token
from tests.support.neo4j import write_tx
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

SID_A = "AC" + "a" * 32
SID_B = "AC" + "b" * 32
NUMBER_ACTIVE = "+447700900301"
NUMBER_RETIRED = "+447700900302"
NUMBER_QUARANTINED = "+447700900303"
NUMBER_OTHER = "+447700900304"
PLATFORM_KEY = b"synthetic-platform-key-for-the-pre-session-tests-12345"
TOKEN_A = "AbCdEfGhIjKlMnOpQrStUvW"
UNKNOWN = "QqQqQqQqQqQqQqQqQqQqQqQ"


async def _number(
    driver: AsyncDriver, tenant: str, e164: str, sid: str, status: str = "active"
) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "MATCH (t:Tenant {id: $id}) "
            "MERGE (t)-[:HAS_NUMBER]->(n:TenantNumber {e164: $e164}) "
            "SET n.accountSid = $sid, n.secretRef = $ref, n.status = $status",
            id=tenant,
            e164=e164,
            sid=sid,
            ref=twilio_token_ref(tenant),
            status=status,
        )

    await write_tx(driver, work)


async def _status(driver: AsyncDriver, tenant: str, status: TenantStatus) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "MATCH (t:Tenant {id: $id}) SET t.status = $status, t.suspendMode = $mode, "
            "t.suspendedAt = $at, t.suspendReason = $reason",
            id=tenant,
            status=status.value,
            mode="read-only" if status is TenantStatus.SUSPENDED else None,
            at=TEST_NOW if status is TenantStatus.SUSPENDED else None,
            reason="contract" if status is TenantStatus.SUSPENDED else None,
        )

    await write_tx(driver, work)


@pytest.fixture
def lines(test_container: Container) -> DirectoryInboundLines:
    directory: TenantDirectory = test_container.tenants
    return DirectoryInboundLines(directory)


async def test_an_active_number_resolves_to_its_tenant_and_token_reference(
    lines: DirectoryInboundLines,
    neo4j_driver: AsyncDriver,
    edge_tenants: None,
    tenant_id: str,
) -> None:
    await _number(neo4j_driver, tenant_id, NUMBER_ACTIVE, SID_A)

    assert await lines.for_number(NUMBER_ACTIVE, SID_A) == InboundLine(
        tenant_id=tenant_id, token_secret=twilio_token_ref(tenant_id)
    )
    assert await lines.for_account(SID_A) == InboundLine(
        tenant_id=tenant_id, token_secret=twilio_token_ref(tenant_id)
    )


async def test_each_tenants_number_resolves_to_that_tenant_only(
    lines: DirectoryInboundLines,
    neo4j_driver: AsyncDriver,
    edge_tenants: None,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    await _number(neo4j_driver, tenant_id, NUMBER_ACTIVE, SID_A)
    await _number(neo4j_driver, other_tenant_id, NUMBER_OTHER, SID_B)

    first = await lines.for_number(NUMBER_ACTIVE, SID_A)
    second = await lines.for_number(NUMBER_OTHER, SID_B)

    assert first is not None and first.tenant_id == tenant_id
    assert second is not None and second.tenant_id == other_tenant_id
    # A number under the other tenant's account is nobody's: both must match, together.
    assert await lines.for_number(NUMBER_ACTIVE, SID_B) is None
    assert await lines.for_number(NUMBER_OTHER, SID_A) is None


async def test_a_retired_or_quarantined_number_resolves_to_nobody(
    lines: DirectoryInboundLines, neo4j_driver: AsyncDriver, edge_tenants: None, tenant_id: str
) -> None:
    await _number(neo4j_driver, tenant_id, NUMBER_RETIRED, SID_A, "retired")
    await _number(neo4j_driver, tenant_id, NUMBER_QUARANTINED, SID_A, "quarantined")

    assert await lines.for_number(NUMBER_RETIRED, SID_A) is None
    assert await lines.for_number(NUMBER_QUARANTINED, SID_A) is None


async def test_a_suspended_tenants_number_answers_as_an_unknown_one(
    lines: DirectoryInboundLines, neo4j_driver: AsyncDriver, edge_tenants: None, tenant_id: str
) -> None:
    await _number(neo4j_driver, tenant_id, NUMBER_ACTIVE, SID_A)
    unknown = await lines.for_number("+447700900399", SID_A)
    try:
        await _status(neo4j_driver, tenant_id, TenantStatus.SUSPENDED)
        suspended = await lines.for_number(NUMBER_ACTIVE, SID_A)
        receipt = await lines.for_account(SID_A)
    finally:
        await _status(neo4j_driver, tenant_id, TenantStatus.ACTIVE)

    assert suspended is None and receipt is None
    assert suspended == unknown


async def test_a_wall_screen_token_is_found_in_its_tenant_and_refused_in_the_other(
    clean_graph: None,
    uow_factory: UnitOfWorkFactory,
    tenant_id: str,
    other_tenant_id: str,
) -> None:
    secrets = TenantKeyedSecrets(
        FixedSecretStore({DEVICE_TOKEN_SECRET: PLATFORM_KEY, LINK_TOKEN_SECRET: PLATFORM_KEY})
    )
    clock = FixedClock(TEST_NOW)
    with as_tenant(tenant_id):
        token_hash = hash_token(TOKEN_A, secrets.get(DEVICE_TOKEN_SECRET))
        async with uow_factory() as uow:
            await uow.devices.save(
                Device(
                    id="screen-ten041-a",
                    status=DeviceStatus.ACTIVE,
                    name="Ward screen",
                    location=None,
                    device_type=DeviceType.WALL_DISPLAY,
                    token_hash=token_hash,
                    board_scope=BoardScope.TENANT,
                )
            )
            await uow.commit()
        found = await PreSessionResolver(uow_factory, clock, secrets).device(TOKEN_A)
    assert found.id == "screen-ten041-a"

    messages: set[str] = set()
    with as_tenant(other_tenant_id):
        resolver = PreSessionResolver(uow_factory, clock, secrets)
        for text in (TOKEN_A, UNKNOWN, "not a token"):
            with pytest.raises(EntryRefused) as caught:
                await resolver.device(text)
            messages.add(str(caught.value))
    assert messages == {ENTRY_REFUSED_MESSAGE}


async def test_a_revoked_screen_is_refused_in_its_own_tenant(
    clean_graph: None, uow_factory: UnitOfWorkFactory, tenant_id: str
) -> None:
    secrets = TenantKeyedSecrets(
        FixedSecretStore({DEVICE_TOKEN_SECRET: PLATFORM_KEY, LINK_TOKEN_SECRET: PLATFORM_KEY})
    )
    with as_tenant(tenant_id):
        token_hash = hash_token(TOKEN_A, secrets.get(DEVICE_TOKEN_SECRET))
        async with uow_factory() as uow:
            await uow.devices.save(
                Device(
                    id="screen-ten041-r",
                    status=DeviceStatus.REVOKED,
                    name="Ward screen",
                    location=None,
                    device_type=DeviceType.WALL_DISPLAY,
                    token_hash=token_hash,
                    board_scope=BoardScope.TENANT,
                )
            )
            await uow.commit()
        with pytest.raises(EntryRefused):
            await PreSessionResolver(uow_factory, FixedClock(TEST_NOW), secrets).device(TOKEN_A)
