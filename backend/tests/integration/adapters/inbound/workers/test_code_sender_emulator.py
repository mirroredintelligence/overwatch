"""A text code reaches the person: request, relay, bus and code sender, on the Service Bus emulator
and real Neo4j (KI-270, N1).

Before this, `codes.dispatch` was in no topology and had no consumer, so no code was ever sent. The
chain here is the real one: `RequestTextCode` writes the outbox message in the graph, the relay
publishes it to the `codes.dispatch` topic of the emulator, and the `code-sender` runner receives it
and texts it through a RECORDING sender (no real message is sent). The code the person would receive
is read from the recorded text and verified with `VerifyTextCode`.

Needs the emulator started from the `integration/build` `infra/servicebus-config.json`. Ids are
unique per run; the emulator keeps messages an hour (lessons L6, L101); the emulator lock is held
(L177).
"""

import asyncio
import random
import re
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from neo4j import AsyncDriver

from diucs.adapters.inbound.workers.code_sender import code_runner
from diucs.adapters.inbound.workers.outbox_relay import OutboxRelay, StaticTenants
from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.outbound.bus_servicebus.service_bus import ServiceBusEventBus
from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.adapters.testing.memory_code_store import InMemoryCodeStore
from diucs.adapters.testing.recording_senders import FixedSenderResolver, RecordingSmsSender
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.text_code import (
    RequestTextCode,
    RequestTextCodeCommand,
    VerifyTextCode,
    VerifyTextCodeCommand,
)
from tests.integration.application.test_text_code import (
    CODE_SECRET,
    INVITED_MOBILE,
    LINK_SECRET,
    PHONE_SECRET,
    START,
    UNKNOWN_MOBILE,
)
from tests.support.neo4j import read_tx, run_nodes
from tests.support.servicebus import client, take_emulator_lock

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
    pytest.mark.servicebus,
    pytest.mark.exclusive,
]

HASHER = HmacPhoneHasher(FixedSecretStore({PHONE_HASH_SECRET: PHONE_SECRET}))
INVITED_HASH = HASHER.hash(INVITED_MOBILE)
PURPOSE = "setup"


@pytest_asyncio.fixture
async def real_bus() -> AsyncIterator[ServiceBusEventBus]:
    sb = client()
    bus = ServiceBusEventBus(sb)
    try:
        yield bus
    finally:
        await bus.close()
        await sb.close()


async def test_a_code_for_a_known_number_is_texted_once_and_one_for_an_unknown_number_is_not(
    uow_factory: UnitOfWorkFactory,
    real_bus: ServiceBusEventBus,
    neo4j_driver: AsyncDriver,
    clean_graph: None,
    tenant_id: str,
) -> None:
    await ensure_audit_head(neo4j_driver)
    clock = FixedClock(START)
    secrets = FixedSecretStore(
        {"code-hmac": CODE_SECRET, LINK_TOKEN_SECRET: LINK_SECRET, PHONE_HASH_SECRET: PHONE_SECRET}
    )
    sealer = AesGcmContentSealer(secrets)
    codes = InMemoryCodeStore(clock)
    async with uow_factory() as uow:
        tokens = LinkTokenService(uow.link_tokens, secrets, clock)
        await tokens.issue("invite", "invitation-1", INVITED_HASH, START + timedelta(hours=48))
        await uow.commit()
    request = RequestTextCode(
        codes, HASHER, uow_factory, secrets, sealer, SequentialIds("code"), clock, random.Random(7)
    )
    await request.execute(
        RequestTextCodeCommand(idempotency_key="known", phone=INVITED_MOBILE, purpose=PURPOSE)
    )
    await request.execute(
        RequestTextCodeCommand(idempotency_key="unknown", phone=UNKNOWN_MOBILE, purpose=PURPOSE)
    )

    recorder = RecordingSmsSender("+441234567890")
    release = await take_emulator_lock()
    try:
        relay = OutboxRelay(
            uow_factory, real_bus, InMemoryCache(clock), clock, StaticTenants([tenant_id])
        )
        result = await relay.run_once()
        assert result.published == 2 and result.failed == 0

        async with client() as sb:
            runner = code_runner(
                sb,
                uow_factory,
                StaticTenants([tenant_id]),
                FixedSenderResolver(sms={tenant_id: recorder}),
                sealer,
                clock,
            )
            stop = asyncio.Event()
            task = asyncio.create_task(runner.run(stop))
            try:
                async with asyncio.timeout(60):
                    while not recorder.sent:
                        await asyncio.sleep(0.2)
                await asyncio.sleep(4)  # the unknown number's message is settled, not sent
            finally:
                stop.set()
                await asyncio.wait_for(task, timeout=30)
    finally:
        release()

    assert [sms.to for sms in recorder.sent] == ["+447700900456"]
    (text,) = [sms.text for sms in recorder.sent]
    match = re.fullmatch(r"DIUCS code: (\d{6})\. It works for 10 minutes\. Do not share it\.", text)
    assert match is not None
    code = match.group(1)
    assert recorder.sent[0].tenant == tenant_id
    verified = await VerifyTextCode(codes, HASHER, uow_factory, secrets, clock).execute(
        VerifyTextCodeCommand(phone=INVITED_MOBILE, purpose=PURPOSE, code=code)
    )
    assert verified.ok is True

    # The code and the number are in no node of the run: not in a message, an audit entry or a
    # record (the sealed forms differ from the digits).
    async def every_value(tx):  # type: ignore[no-untyped-def]
        rows = await (await run_nodes(tx, "n")).data()
        return [repr(row["n"]) for row in rows]

    nodes = await read_tx(neo4j_driver, every_value)
    assert nodes
    for needle in (code, "7700900456", "07700900456", "447700900456"):
        assert not [node for node in nodes if needle in node]
