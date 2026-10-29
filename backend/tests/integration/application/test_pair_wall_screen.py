"""Integration tests for PairWallScreen (U10, DEC-160), against the real Neo4j the harness starts.

A wall display starts a pairing and shows the six-digit code; a shift lead types it with a screen
name; the display then collects a device token that reads only the board. Every assertion reads back
through a fresh unit of work or the harness helpers. Values are synthetic: no patient data.
"""

import asyncio
import random
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_cache import InMemoryCache
from diucs.application.actor import Actor
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeId, TenantNotBound, bind_scope
from diucs.application.use_cases.pair_wall_screen import (
    CODE_ATTEMPTS,
    CONFIRM_FAILURE_LIMIT,
    PAIRING_PURPOSE,
    PAIRING_SECRET_PURPOSE,
    REFUSED_MESSAGE,
    START_LIMIT,
    ClaimPairing,
    ClaimPairingCommand,
    ConfirmPairing,
    ConfirmPairingCommand,
    ConfirmPairingResult,
    PairingRateLimited,
    StartPairing,
    StartPairingResult,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, ValidationFailed
from diucs.domain.model.device import BoardScope, Device, DeviceStatus, DeviceType
from diucs.domain.rules.tokens import hash_token
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx

pytestmark = pytest.mark.asyncio(loop_scope="session")

LINK_SECRET = b"link-secret-for-the-pairing-tests"
DEVICE_SECRET = b"device-secret-for-the-pairing-tests"
SECRETS = {LINK_TOKEN_SECRET: LINK_SECRET, DEVICE_TOKEN_SECRET: DEVICE_SECRET}
SCREEN_NAME = "Ward 4 corridor"
LOCATION = "Level 2"
AUDIT_ACTION_PAIRED = "wall-screen-paired"
AUDIT_ACTION_CLAIMED = "wall-screen-claimed"

LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
OTHER_LEAD = Actor(
    role=Role.LEAD,
    practitioner_id="prac-lead-2",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)
ADVISOR = Actor(
    role=Role.ADVISOR,
    practitioner_id="prac-advisor-1",
    device_id=None,
    channel="web",
    service_ids=frozenset(),
)


class ScriptedRandom(random.Random):
    """Gives the digits it is told (a list per call of the six), then counts. For the tests that
    need a code to repeat."""

    def __init__(self, digits: list[int]) -> None:
        super().__init__(0)
        self._digits = list(digits)
        self._bytes = 0

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        if self._digits:
            return self._digits.pop(0)
        return 0

    def randbytes(self, n: int) -> bytes:
        self._bytes += 1
        return self._bytes.to_bytes(n, "big")


@dataclass
class Rig:
    clock: FixedClock
    cache: Cache
    ids: SequentialIds
    start: StartPairing
    confirm: ConfirmPairing
    claim: ClaimPairing
    uow_factory: UnitOfWorkFactory

    async def pair(self, actor: Actor = LEAD, key: str = "key-1") -> tuple[StartPairingResult, str]:
        """Start and confirm one screen. Returns the start result and the device id."""
        started = await self.start.execute()
        confirmed = await self.confirm.execute(
            ConfirmPairingCommand(
                idempotency_key=key,
                actor=actor,
                code=started.code_display,
                screen_name=SCREEN_NAME,
                location=LOCATION,
            )
        )
        return started, confirmed.device_id


def make_rig(
    uow_factory: UnitOfWorkFactory,
    clock: Clock,
    *,
    cache: Cache | None = None,
    ids: SequentialIds | None = None,
    rng: random.Random | None = None,
) -> Rig:
    fixed = cast(FixedClock, clock)
    shared_cache = InMemoryCache(fixed) if cache is None else cache
    shared_ids = SequentialIds("pairing") if ids is None else ids
    shared_rng = random.Random(7) if rng is None else rng
    secrets = FixedSecretStore(SECRETS)
    return Rig(
        clock=fixed,
        cache=shared_cache,
        ids=shared_ids,
        start=StartPairing(uow_factory, fixed, shared_ids, shared_rng, secrets, shared_cache),
        confirm=ConfirmPairing(uow_factory, fixed, secrets, shared_cache),
        claim=ClaimPairing(uow_factory, fixed, shared_rng, secrets),
        uow_factory=uow_factory,
    )


@pytest.fixture
async def rig(uow_factory: UnitOfWorkFactory, uow_clock: Clock, neo4j_driver: AsyncDriver) -> Rig:
    await ensure_audit_head(neo4j_driver)
    return make_rig(uow_factory, uow_clock)


def _command(
    started: StartPairingResult,
    *,
    key: str = "key-1",
    actor: Actor = LEAD,
    code: str | None = None,
    name: str = SCREEN_NAME,
    location: str | None = LOCATION,
    board_scope: BoardScope = BoardScope.TENANT,
) -> ConfirmPairingCommand:
    return ConfirmPairingCommand(
        idempotency_key=key,
        actor=actor,
        code=started.code_display if code is None else code,
        screen_name=name,
        location=location,
        board_scope=board_scope,
    )


async def _all_values(driver: AsyncDriver) -> list[Any]:
    """Every property value of every node, and every list element of a list property."""

    async def work(tx: AsyncManagedTransaction) -> list[Any]:
        result = await tx.run("MATCH (n) UNWIND keys(n) AS k RETURN n[k] AS v")
        values: list[Any] = []
        for row in await result.data():
            value = row["v"]
            values.extend(value if isinstance(value, list) else [value])
        return values

    return await read_tx(driver, work)


async def _link_tokens(driver: AsyncDriver) -> list[dict[str, Any]]:
    async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
        result = await tx.run("MATCH (t:LinkToken) RETURN properties(t) AS props ORDER BY t.purpose")
        return [row["props"] for row in await result.data()]

    return await read_tx(driver, work)


async def _device(rig: Rig, device_id: str) -> Device | None:
    async with rig.uow_factory() as uow:
        return await uow.devices.get(device_id)


async def _audit_actions(rig: Rig) -> list[str]:
    async with rig.uow_factory() as uow:
        records = await uow.audit.records()
    return [r.entry.action for r in records if r.entry.use_case == "PairWallScreen"]


async def _state(driver: AsyncDriver) -> tuple[Any, ...]:
    """What a refusal must leave untouched: the device nodes, the link tokens and the audit."""
    return (
        await count_nodes(driver, "Device"),
        await _link_tokens(driver),
        await count_nodes(driver, "AuditEvent"),
        await count_nodes(driver, "IdempotencyRecord"),
    )


async def _set_device_status(driver: AsyncDriver, device_id: str, status: str) -> None:
    async def work(tx: AsyncManagedTransaction) -> None:
        await tx.run("MATCH (d:Device {id: $id}) SET d.status = $status", id=device_id, status=status)

    await write_tx(driver, work)


# -- 1 Start ------------------------------------------------------------------------------------


async def test_start_returns_a_spaced_code_a_secret_and_the_ten_minute_expiry(rig: Rig) -> None:
    started = await rig.start.execute()
    assert re.fullmatch(r"[0-9]{3} [0-9]{3}", started.code_display)
    assert re.fullmatch(r"[A-Za-z]{23}", started.screen_secret)
    assert started.pairing_id == "pairing-1"
    assert started.expires_at == rig.clock.now() + timedelta(minutes=10)


async def test_start_stores_two_link_tokens_and_no_property_holds_the_code_or_the_secret(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    stored = await _link_tokens(neo4j_driver)
    assert [t["purpose"] for t in stored] == [PAIRING_PURPOSE, PAIRING_SECRET_PURPOSE]
    for token in stored:
        assert token["aboutId"] == started.pairing_id
        assert token["expiresAt"].to_native() == started.expires_at
        assert token.get("usedAt") is None
        assert token.get("phoneHash") is None
    digits = started.code_display.replace(" ", "")
    for value in await _all_values(neo4j_driver):
        assert value not in (digits, started.code_display, started.screen_secret)
        if isinstance(value, str):
            assert started.screen_secret not in value
    assert await count_nodes(neo4j_driver, "Device") == 0


async def test_start_leaves_no_audit_entry_and_no_device(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    await rig.start.execute()
    assert await _audit_actions(rig) == []
    assert await count_nodes(neo4j_driver, "Device") == 0


async def test_two_starts_give_two_different_pairings(rig: Rig) -> None:
    first = await rig.start.execute()
    second = await rig.start.execute()
    assert first.pairing_id != second.pairing_id
    assert first.screen_secret != second.screen_secret
    assert first.code_display != second.code_display


async def test_a_code_that_is_already_in_use_is_drawn_again(
    uow_factory: UnitOfWorkFactory, uow_clock: Clock, neo4j_driver: AsyncDriver
) -> None:
    ones, twos = [1] * 6, [2] * 6
    rig = make_rig(uow_factory, uow_clock, rng=ScriptedRandom(ones + ones + twos))
    first = await rig.start.execute()
    second = await rig.start.execute()
    assert first.code_display == "111 111"
    assert second.code_display == "222 222"
    assert len(await _link_tokens(neo4j_driver)) == 4


async def test_a_code_that_keeps_colliding_is_refused_and_writes_nothing(
    uow_factory: UnitOfWorkFactory, uow_clock: Clock, neo4j_driver: AsyncDriver
) -> None:
    rig = make_rig(uow_factory, uow_clock, rng=ScriptedRandom([1] * 6 * (CODE_ATTEMPTS + 1)))
    await rig.start.execute()
    before = await _link_tokens(neo4j_driver)
    with pytest.raises(Conflict):
        await rig.start.execute()
    assert await _link_tokens(neo4j_driver) == before


# -- 2 Claim before confirmation ---------------------------------------------------------------


async def test_a_claim_before_the_lead_confirms_is_waiting_and_writes_nothing(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    before = await _state(neo4j_driver)
    for _ in range(3):
        result = await rig.claim.execute(ClaimPairingCommand(started.pairing_id, started.screen_secret))
        assert (result.status, result.device_token) == ("waiting", None)
    assert await _state(neo4j_driver) == before


# -- 3 Confirm ---------------------------------------------------------------------------------


async def test_a_lead_confirms_and_a_paired_unclaimed_device_is_stored_with_one_audit_entry(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    result = await rig.confirm.execute(_command(started))
    assert result == ConfirmPairingResult(started.pairing_id, SCREEN_NAME)
    assert await _device(rig, started.pairing_id) == Device(
        id=started.pairing_id,
        status=DeviceStatus.PAIRED_UNCLAIMED,
        name=SCREEN_NAME,
        location=LOCATION,
        device_type=DeviceType.WALL_DISPLAY,
        token_hash=None,
        board_scope=BoardScope.TENANT,
    )
    assert await _audit_actions(rig) == [AUDIT_ACTION_PAIRED]
    code_record = (await _link_tokens(neo4j_driver))[0]
    assert code_record["purpose"] == PAIRING_PURPOSE
    assert code_record["usedAt"].to_native() == rig.clock.now()


async def test_the_confirmed_device_node_holds_only_what_a_wall_display_needs(
    rig: Rig, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    started = await rig.start.execute()
    await rig.confirm.execute(_command(started, location=None, board_scope=BoardScope.NETWORK))
    props = await node_props(neo4j_driver, "Device", id=started.pairing_id)
    assert set(props) == {
        "id",
        "tenantId",
        "deviceType",
        "status",
        "deviceName",
        "boardScope",
        "updatedAt",
    }
    assert props["tenantId"] == tenant_id
    assert props["deviceType"] == "wall-display"
    assert props["status"] == "paired-unclaimed"
    assert props["deviceName"] == SCREEN_NAME
    assert props["boardScope"] == "network"


@pytest.mark.parametrize("typed", ["{spaced}", "{plain}", "{hyphen}", " {spaced} "])
async def test_a_code_typed_with_a_space_a_hyphen_or_none_is_the_same_code(
    rig: Rig, typed: str
) -> None:
    started = await rig.start.execute()
    plain = started.code_display.replace(" ", "")
    code = typed.format(spaced=started.code_display, plain=plain, hyphen=f"{plain[:3]}-{plain[3:]}")
    result = await rig.confirm.execute(_command(started, code=code))
    assert result.device_id == started.pairing_id


async def test_the_audit_entry_names_the_lead_and_the_screen_and_holds_no_code_or_secret(
    rig: Rig,
) -> None:
    started = await rig.start.execute()
    await rig.confirm.execute(_command(started))
    async with rig.uow_factory() as uow:
        records = [r for r in await uow.audit.records() if r.entry.use_case == "PairWallScreen"]
    assert len(records) == 1
    entry = records[0].entry
    assert entry.action == AUDIT_ACTION_PAIRED
    assert entry.actor == LEAD
    assert entry.entity_ids == (started.pairing_id,)
    assert entry.snapshot == {
        "screen_name": SCREEN_NAME,
        "location": LOCATION,
        "board_scope": "tenant",
    }
    assert entry.at == rig.clock.now()


async def test_the_code_works_up_to_but_not_including_ten_minutes(rig: Rig) -> None:
    started = await rig.start.execute()
    rig.clock.advance(timedelta(minutes=10) - timedelta(seconds=1))
    assert (await rig.confirm.execute(_command(started))).device_id == started.pairing_id


# -- 4 Claim -----------------------------------------------------------------------------------


async def test_a_claim_with_the_right_secret_returns_the_token_and_activates_the_device(
    rig: Rig, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    started, device_id = await rig.pair()
    result = await rig.claim.execute(ClaimPairingCommand(device_id, started.screen_secret))
    assert result.status == "paired"
    token = result.device_token
    assert token is not None
    assert re.fullmatch(r"[A-Za-z]{23}", token)
    token_hash = hash_token(token, DEVICE_SECRET)
    props = await node_props(neo4j_driver, "Device", id=device_id)
    assert props["status"] == "active"
    assert props["tokenHash"] == token_hash
    assert props["tenantId"] == tenant_id
    async with rig.uow_factory() as uow:
        found = await uow.devices.find_by_token_hash(token_hash)
    assert found == Device(
        id=device_id,
        status=DeviceStatus.ACTIVE,
        name=SCREEN_NAME,
        location=LOCATION,
        device_type=DeviceType.WALL_DISPLAY,
        token_hash=token_hash,
        board_scope=BoardScope.TENANT,
    )
    secret_record = (await _link_tokens(neo4j_driver))[1]
    assert secret_record["purpose"] == PAIRING_SECRET_PURPOSE
    assert secret_record["usedAt"].to_native() == rig.clock.now()


async def test_the_device_token_is_stored_nowhere_and_hashed_with_its_own_secret(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started, device_id = await rig.pair()
    result = await rig.claim.execute(ClaimPairingCommand(device_id, started.screen_secret))
    token = result.device_token
    assert token is not None
    for value in await _all_values(neo4j_driver):
        if isinstance(value, str):
            assert token not in value
    stored = (await node_props(neo4j_driver, "Device", id=device_id))["tokenHash"]
    assert stored == hash_token(token, DEVICE_SECRET)
    assert stored != hash_token(token, LINK_SECRET)
    async with rig.uow_factory() as uow:
        assert await uow.devices.find_by_token_hash(hash_token(token, LINK_SECRET)) is None


async def test_the_claim_writes_one_audit_entry_and_a_wait_or_a_second_claim_writes_none(
    rig: Rig,
) -> None:
    started = await rig.start.execute()
    command = ClaimPairingCommand(started.pairing_id, started.screen_secret)
    await rig.claim.execute(command)
    assert await _audit_actions(rig) == []
    await rig.confirm.execute(_command(started))
    await rig.claim.execute(command)
    await rig.claim.execute(command)
    assert await _audit_actions(rig) == [AUDIT_ACTION_PAIRED, AUDIT_ACTION_CLAIMED]
    async with rig.uow_factory() as uow:
        claimed = [r for r in await uow.audit.records() if r.entry.action == AUDIT_ACTION_CLAIMED]
    entry = claimed[0].entry
    assert entry.actor.role is Role.WALL
    assert entry.actor.device_id == started.pairing_id
    assert entry.actor.practitioner_id is None
    assert entry.entity_ids == (started.pairing_id,)
    assert entry.snapshot == {"board_scope": "tenant"}


# -- 5 Second claim ----------------------------------------------------------------------------


async def test_a_second_claim_says_paired_and_gives_no_token(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started, device_id = await rig.pair()
    command = ClaimPairingCommand(device_id, started.screen_secret)
    first = await rig.claim.execute(command)
    assert first.device_token is not None
    before = await node_props(neo4j_driver, "Device", id=device_id)
    for _ in range(2):
        again = await rig.claim.execute(command)
        assert (again.status, again.device_token) == ("paired", None)
    assert await node_props(neo4j_driver, "Device", id=device_id) == before


async def test_a_claim_after_the_ten_minutes_still_says_paired_once_the_token_was_collected(
    rig: Rig,
) -> None:
    started, device_id = await rig.pair()
    command = ClaimPairingCommand(device_id, started.screen_secret)
    await rig.claim.execute(command)
    rig.clock.advance(timedelta(minutes=11))
    again = await rig.claim.execute(command)
    assert (again.status, again.device_token) == ("paired", None)


async def test_sixteen_racing_claims_give_exactly_one_token(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started, device_id = await rig.pair()
    command = ClaimPairingCommand(device_id, started.screen_secret)
    results = await asyncio.gather(*(rig.claim.execute(command) for _ in range(16)))
    tokens = [r.device_token for r in results if r.device_token is not None]
    assert len(tokens) == 1
    assert [r.status for r in results] == ["paired"] * 16
    props = await node_props(neo4j_driver, "Device", id=device_id)
    assert props["tokenHash"] == hash_token(tokens[0], DEVICE_SECRET)
    assert await _audit_actions(rig) == [AUDIT_ACTION_PAIRED, AUDIT_ACTION_CLAIMED]


# -- 6 Refusals --------------------------------------------------------------------------------


async def test_every_refusal_of_a_code_is_the_same_error_with_the_same_message(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    expired = await rig.start.execute()
    used = await rig.start.execute()
    await rig.confirm.execute(_command(used, key="used-1"))
    rig.clock.advance(timedelta(minutes=10))  # the two codes above are now 10 minutes old
    fresh = await rig.start.execute()
    never_issued = "000 000" if fresh.code_display != "000 000" else "111 111"
    attempts = {
        "wrong": never_issued,
        "expired": expired.code_display,
        "used": used.code_display,
        "short": "48291",
        "letters": "abc def",
        "empty": "",
    }
    before = await _state(neo4j_driver)
    messages: set[str] = set()
    for n, (label, code) in enumerate(attempts.items()):
        # One lead each, so the failure allowance of one lead does not answer for the others.
        actor = Actor(
            role=Role.LEAD,
            practitioner_id=f"prac-lead-{n}",
            device_id=None,
            channel="web",
            service_ids=frozenset(),
        )
        with pytest.raises(NotAllowed) as refused:
            await rig.confirm.execute(_command(fresh, actor=actor, code=code, key=f"refused-{label}"))
        assert type(refused.value) is NotAllowed
        messages.add(str(refused.value))
    assert messages == {REFUSED_MESSAGE}
    assert await _state(neo4j_driver) == before


async def test_a_code_one_second_past_ten_minutes_is_refused_and_writes_nothing(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    before = await _state(neo4j_driver)
    rig.clock.advance(timedelta(minutes=10))
    with pytest.raises(NotAllowed, match=re.escape(REFUSED_MESSAGE)):
        await rig.confirm.execute(_command(started))
    assert await _state(neo4j_driver) == before


@pytest.mark.parametrize("role", [Role.ADVISOR, Role.REPORTER, Role.CLINICAL, Role.WALL, Role.EXEC])
async def test_only_a_lead_may_confirm_and_nothing_is_written_otherwise(
    rig: Rig, neo4j_driver: AsyncDriver, role: Role
) -> None:
    started = await rig.start.execute()
    before = await _state(neo4j_driver)
    actor = Actor(
        role=role, practitioner_id="prac-x", device_id=None, channel="web", service_ids=frozenset()
    )
    with pytest.raises(NotAllowed):
        await rig.confirm.execute(_command(started, actor=actor))
    assert await _state(neo4j_driver) == before
    # The code was not touched: the lead can still use it.
    assert (await rig.confirm.execute(_command(started))).device_id == started.pairing_id


async def test_a_lead_with_no_practitioner_is_refused(rig: Rig, neo4j_driver: AsyncDriver) -> None:
    started = await rig.start.execute()
    actor = Actor(
        role=Role.LEAD, practitioner_id=None, device_id=None, channel="web", service_ids=frozenset()
    )
    with pytest.raises(NotAllowed):
        await rig.confirm.execute(_command(started, actor=actor))
    assert await count_nodes(neo4j_driver, "Device") == 0


async def test_an_advisor_who_types_a_wrong_code_gets_the_role_refusal_not_a_code_verdict(
    rig: Rig,
) -> None:
    started = await rig.start.execute()
    with pytest.raises(NotAllowed) as refused:
        await rig.confirm.execute(_command(started, actor=ADVISOR, code="000 000"))
    assert str(refused.value) != REFUSED_MESSAGE


async def test_wrong_secrets_and_wrong_pairings_are_all_the_same_refusal(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    first, device_id = await rig.pair()
    second = await rig.start.execute()
    before = await _state(neo4j_driver)
    attempts = [
        ClaimPairingCommand(device_id, "A" * 23),
        ClaimPairingCommand(device_id, second.screen_secret),
        ClaimPairingCommand(second.pairing_id, first.screen_secret),
        ClaimPairingCommand("unknown-pairing", first.screen_secret),
        ClaimPairingCommand(device_id, "not a token!"),
        ClaimPairingCommand(device_id, ""),
        ClaimPairingCommand(device_id, first.screen_secret.lower()),
    ]
    messages: set[str] = set()
    for attempt in attempts:
        with pytest.raises(NotAllowed) as refused:
            await rig.claim.execute(attempt)
        assert type(refused.value) is NotAllowed
        messages.add(str(refused.value))
    assert messages == {REFUSED_MESSAGE}
    assert await _state(neo4j_driver) == before


async def test_the_pairing_code_cannot_be_used_as_a_secret_nor_the_secret_as_a_code(
    rig: Rig,
) -> None:
    started = await rig.start.execute()
    with pytest.raises(NotAllowed):
        await rig.claim.execute(ClaimPairingCommand(started.pairing_id, started.code_display))
    with pytest.raises(NotAllowed):
        await rig.confirm.execute(_command(started, code=started.screen_secret))


async def test_a_claim_on_an_expired_pairing_says_expired_and_gives_no_token(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    rig.clock.advance(timedelta(minutes=10))
    before = await _state(neo4j_driver)
    result = await rig.claim.execute(ClaimPairingCommand(started.pairing_id, started.screen_secret))
    assert (result.status, result.device_token) == ("expired", None)
    assert await _state(neo4j_driver) == before


async def test_a_pairing_confirmed_but_not_collected_in_time_is_expired_and_never_active(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started, device_id = await rig.pair()
    rig.clock.advance(timedelta(minutes=11))
    result = await rig.claim.execute(ClaimPairingCommand(device_id, started.screen_secret))
    assert (result.status, result.device_token) == ("expired", None)
    props = await node_props(neo4j_driver, "Device", id=device_id)
    assert props["status"] == "paired-unclaimed"
    assert "tokenHash" not in props


async def test_a_device_that_is_no_longer_paired_unclaimed_is_never_activated(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started, device_id = await rig.pair()
    await _set_device_status(neo4j_driver, device_id, "revoked")
    with pytest.raises(NotAllowed, match=re.escape(REFUSED_MESSAGE)):
        await rig.claim.execute(ClaimPairingCommand(device_id, started.screen_secret))
    props = await node_props(neo4j_driver, "Device", id=device_id)
    assert props["status"] == "revoked"
    assert "tokenHash" not in props
    secret_record = (await _link_tokens(neo4j_driver))[1]
    assert secret_record.get("usedAt") is None


async def test_two_confirmations_of_one_code_make_one_device(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    await rig.confirm.execute(_command(started, key="first"))
    with pytest.raises(NotAllowed, match=re.escape(REFUSED_MESSAGE)):
        await rig.confirm.execute(_command(started, key="second", actor=OTHER_LEAD))
    assert await count_nodes(neo4j_driver, "Device") == 1
    assert await _audit_actions(rig) == [AUDIT_ACTION_PAIRED]


async def test_eight_leads_racing_for_one_code_make_exactly_one_device(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    actors = [
        Actor(
            role=Role.LEAD,
            practitioner_id=f"prac-lead-{n}",
            device_id=None,
            channel="web",
            service_ids=frozenset(),
        )
        for n in range(8)
    ]
    outcomes = await asyncio.gather(
        *(
            rig.confirm.execute(_command(started, key=f"race-{n}", actor=actor))
            for n, actor in enumerate(actors)
        ),
        return_exceptions=True,
    )
    wins = [o for o in outcomes if isinstance(o, ConfirmPairingResult)]
    refusals = [o for o in outcomes if isinstance(o, NotAllowed)]
    assert len(wins) == 1
    assert len(refusals) == 7
    assert await count_nodes(neo4j_driver, "Device") == 1
    assert await _audit_actions(rig) == [AUDIT_ACTION_PAIRED]


# -- Input checks ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "location", "field"),
    [
        ("", LOCATION, "screen_name"),
        ("x" * 61, LOCATION, "screen_name"),
        ("Bay DT4 8XX", LOCATION, "screen_name"),
        (SCREEN_NAME, "x" * 61, "location"),
        (SCREEN_NAME, "943 476 5919", "location"),
    ],
)
async def test_a_bad_name_or_place_is_refused_before_the_code_is_burned(
    rig: Rig, neo4j_driver: AsyncDriver, name: str, location: str, field: str
) -> None:
    started = await rig.start.execute()
    before = await _state(neo4j_driver)
    with pytest.raises(ValidationFailed) as refused:
        await rig.confirm.execute(_command(started, name=name, location=location))
    assert refused.value.field == field
    assert await _state(neo4j_driver) == before
    assert (await rig.confirm.execute(_command(started))).device_id == started.pairing_id


async def test_the_name_is_trimmed_and_an_absent_place_stays_absent(rig: Rig) -> None:
    started = await rig.start.execute()
    await rig.confirm.execute(_command(started, name="  Ward 4 corridor  ", location=None))
    device = await _device(rig, started.pairing_id)
    assert device is not None
    assert (device.name, device.location) == (SCREEN_NAME, None)


# -- Replay ------------------------------------------------------------------------------------


async def test_a_replayed_confirmation_returns_the_same_result_and_writes_nothing_more(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    first = await rig.confirm.execute(_command(started))
    before = await _state(neo4j_driver)
    again = await rig.confirm.execute(_command(started))
    assert again == ConfirmPairingResult(first.device_id, first.screen_name, replayed=True)
    assert await _state(neo4j_driver) == before
    assert await _audit_actions(rig) == [AUDIT_ACTION_PAIRED]


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Ward 5 corridor"},
        {"location": "Level 3"},
        {"board_scope": BoardScope.NETWORK},
        {"actor": OTHER_LEAD},
        {"code": "000 000"},
    ],
)
async def test_a_key_used_for_a_different_confirmation_is_a_conflict(
    rig: Rig, changes: dict[str, Any]
) -> None:
    started = await rig.start.execute()
    await rig.confirm.execute(_command(started))
    with pytest.raises(Conflict):
        await rig.confirm.execute(_command(started, **changes))


async def test_the_stored_replay_holds_no_code_secret_or_token(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started, device_id = await rig.pair()
    await rig.claim.execute(ClaimPairingCommand(device_id, started.screen_secret))
    digits = started.code_display.replace(" ", "")
    for value in await _all_values(neo4j_driver):
        assert value != digits
        if isinstance(value, str):
            assert started.screen_secret not in value


# -- Rate limits -------------------------------------------------------------------------------


async def test_five_wrong_codes_stop_the_lead_even_with_the_right_code(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    for n in range(CONFIRM_FAILURE_LIMIT):
        with pytest.raises(NotAllowed):
            await rig.confirm.execute(_command(started, code="000 000", key=f"wrong-{n}"))
    before = await _state(neo4j_driver)
    with pytest.raises(PairingRateLimited):
        await rig.confirm.execute(_command(started, key="right"))
    assert await _state(neo4j_driver) == before
    # Another lead of the same tenant is not held up.
    assert (await rig.confirm.execute(_command(started, key="other", actor=OTHER_LEAD))).device_id


async def test_the_limit_ends_when_the_window_has_passed(rig: Rig) -> None:
    started = await rig.start.execute()
    for n in range(CONFIRM_FAILURE_LIMIT):
        with pytest.raises(NotAllowed):
            await rig.confirm.execute(_command(started, code="000 000", key=f"wrong-{n}"))
    with pytest.raises(PairingRateLimited):
        await rig.confirm.execute(_command(started, key="right"))
    rig.clock.advance(timedelta(minutes=10))
    fresh = await rig.start.execute()
    assert (await rig.confirm.execute(_command(fresh, key="again"))).device_id == fresh.pairing_id


async def test_a_good_confirmation_does_not_use_up_the_failure_allowance(rig: Rig) -> None:
    for n in range(CONFIRM_FAILURE_LIMIT + 2):
        started = await rig.start.execute()
        confirmed = await rig.confirm.execute(_command(started, key=f"good-{n}"))
        assert confirmed.device_id == started.pairing_id
        rig.clock.advance(timedelta(minutes=1))


async def test_a_replay_is_answered_even_when_the_lead_is_over_the_failure_limit(rig: Rig) -> None:
    started = await rig.start.execute()
    first = await rig.confirm.execute(_command(started, key="good"))
    for n in range(CONFIRM_FAILURE_LIMIT):
        with pytest.raises(NotAllowed):
            await rig.confirm.execute(_command(started, code="000 000", key=f"wrong-{n}"))
    again = await rig.confirm.execute(_command(started, key="good"))
    assert again.replayed
    assert again.device_id == first.device_id


async def test_the_twenty_first_start_in_ten_minutes_is_refused_and_writes_nothing(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    for _ in range(START_LIMIT):
        await rig.start.execute()
    before = await _link_tokens(neo4j_driver)
    assert len(before) == START_LIMIT * 2
    with pytest.raises(PairingRateLimited):
        await rig.start.execute()
    assert await _link_tokens(neo4j_driver) == before
    rig.clock.advance(timedelta(minutes=10))
    assert (await rig.start.execute()).pairing_id


# -- Tenancy -----------------------------------------------------------------------------------


@dataclass
class Pair:
    a: Rig
    b: Rig


@pytest.fixture
async def pair(
    neo4j_driver: AsyncDriver,
    uow_factory_a: UnitOfWorkFactory,
    uow_factory_b: UnitOfWorkFactory,
    uow_clock: Clock,
    tenant_id: str,
    other_tenant_id: str,
) -> Pair:
    await ensure_audit_head(neo4j_driver)
    cache = InMemoryCache(cast(FixedClock, uow_clock))
    both_same_digits = lambda: ScriptedRandom([4, 8, 2, 9, 1, 3] * 3)  # noqa: E731
    return Pair(
        a=make_rig(
            uow_factory_a,
            uow_clock,
            cache=cache,
            ids=SequentialIds.scoped(tenant_id, "pairing"),
            rng=both_same_digits(),
        ),
        b=make_rig(
            uow_factory_b,
            uow_clock,
            cache=cache,
            ids=SequentialIds.scoped(other_tenant_id, "pairing"),
            rng=both_same_digits(),
        ),
    )


async def test_two_tenants_can_hold_the_same_six_digits_at_once_and_each_pairs_its_own_screen(
    pair: Pair, neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    a = await pair.a.start.execute()
    b = await pair.b.start.execute()
    assert a.code_display == b.code_display == "482 913"
    await pair.a.confirm.execute(_command(a, key="a"))
    await pair.b.confirm.execute(_command(b, key="b"))
    owners = {
        (await node_props(neo4j_driver, "Device", id=i))["tenantId"]: i
        for i in (a.pairing_id, b.pairing_id)
    }
    assert owners == {tenant_id: a.pairing_id, other_tenant_id: b.pairing_id}


async def test_another_tenants_lead_cannot_confirm_a_code_and_it_reads_as_a_wrong_code(
    pair: Pair, neo4j_driver: AsyncDriver
) -> None:
    a = await pair.a.start.execute()
    before = await _state(neo4j_driver)
    # B types the digits A's screen shows. B has issued no code, so for B they are just wrong.
    with pytest.raises(NotAllowed) as refused:
        await pair.b.confirm.execute(_command(a, key="b"))
    assert str(refused.value) == REFUSED_MESSAGE
    assert await _state(neo4j_driver) == before
    # A's code is untouched and A's lead can still use it.
    assert (await pair.a.confirm.execute(_command(a, key="a"))).device_id == a.pairing_id


async def test_another_tenants_screen_and_secret_read_as_a_wrong_secret(
    pair: Pair, neo4j_driver: AsyncDriver
) -> None:
    a = await pair.a.start.execute()
    await pair.a.confirm.execute(_command(a, key="a"))
    before = await _state(neo4j_driver)
    with pytest.raises(NotAllowed) as refused:
        await pair.b.claim.execute(ClaimPairingCommand(a.pairing_id, a.screen_secret))
    assert str(refused.value) == REFUSED_MESSAGE
    assert await _state(neo4j_driver) == before
    granted = await pair.a.claim.execute(ClaimPairingCommand(a.pairing_id, a.screen_secret))
    assert granted.device_token is not None


async def test_a_device_token_is_found_in_its_own_tenant_only(pair: Pair) -> None:
    a = await pair.a.start.execute()
    await pair.a.confirm.execute(_command(a, key="a"))
    granted = await pair.a.claim.execute(ClaimPairingCommand(a.pairing_id, a.screen_secret))
    assert granted.device_token is not None
    token_hash = hash_token(granted.device_token, DEVICE_SECRET)
    async with pair.a.uow_factory() as uow:
        assert (await uow.devices.find_by_token_hash(token_hash)) is not None
    async with pair.b.uow_factory() as uow:
        assert await uow.devices.find_by_token_hash(token_hash) is None
        assert await uow.devices.get(a.pairing_id) is None


async def test_the_failure_and_start_limits_are_kept_per_tenant(pair: Pair) -> None:
    for _ in range(START_LIMIT):
        await pair.a.start.execute()
    with pytest.raises(PairingRateLimited):
        await pair.a.start.execute()
    b = await pair.b.start.execute()  # B is not held up by A
    for n in range(CONFIRM_FAILURE_LIMIT):
        with pytest.raises(NotAllowed):
            await pair.a.confirm.execute(_command(b, code="000 000", key=f"a-{n}"))
    with pytest.raises(PairingRateLimited):
        await pair.a.confirm.execute(_command(b, key="a-last"))
    # The same practitioner id in tenant B has its own allowance.
    assert (await pair.b.confirm.execute(_command(b, key="b"))).device_id == b.pairing_id


async def test_a_unit_of_work_bound_to_a_network_scope_pairs_nothing(
    rig: Rig, neo4j_driver: AsyncDriver
) -> None:
    started = await rig.start.execute()
    with bind_scope(ScopeId.network("net-test-1")):
        with pytest.raises(TenantNotBound):
            await rig.start.execute()
        with pytest.raises(TenantNotBound):
            await rig.confirm.execute(_command(started))
        with pytest.raises(TenantNotBound):
            await rig.claim.execute(ClaimPairingCommand(started.pairing_id, started.screen_secret))
    assert await count_nodes(neo4j_driver, "Device") == 0


@pytest.mark.no_tenant
async def test_with_no_tenant_bound_nothing_starts_confirms_or_claims(
    uow_factory: UnitOfWorkFactory, uow_clock: Clock, neo4j_driver: AsyncDriver
) -> None:
    rig = make_rig(uow_factory, uow_clock)
    with pytest.raises(TenantNotBound):
        await rig.start.execute()
    started = StartPairingResult("p", "482 913", "A" * 23, uow_clock.now())
    with pytest.raises(TenantNotBound):
        await rig.confirm.execute(_command(started))
    with pytest.raises(TenantNotBound):
        await rig.claim.execute(ClaimPairingCommand("p", "A" * 23))
    assert await count_nodes(neo4j_driver, "LinkToken") == 0


def test_no_command_carries_a_tenant() -> None:
    for command in (ConfirmPairingCommand, ClaimPairingCommand):
        assert not [name for name in command.__dataclass_fields__ if "tenant" in name]
