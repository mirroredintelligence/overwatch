"""Integration tests for the text codes (U25), against the real Neo4j the harness starts.

A six-digit code is sent to a known number (an open invitation or a registered practitioner) and
verified. An unknown number gets exactly the same answers and no text. Every assertion reads back
through a fresh unit of work or the harness helpers. The number and the code are sample values.
"""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.outbound.audit_neo4j.audit_log import ensure_audit_head
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_code_store import InMemoryCodeStore, RecordingCodeSender
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, LinkTokenService
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.text_code import (
    RequestTextCode,
    RequestTextCodeCommand,
    RequestTextCodeResult,
    VerifyTextCode,
    VerifyTextCodeCommand,
    VerifyTextCodeResult,
    code_key,
)
from diucs.domain.rules.identity_policy import CODE_VALID_FOR
from tests.support.neo4j import node_props

pytestmark = pytest.mark.asyncio(loop_scope="session")

INVITED_MOBILE = "07700 900456"
UNKNOWN_MOBILE = "07700 900999"
PHONE_SECRET = b"phone-hash-test-secret-0123456789ab"
CODE_SECRET = b"code-hmac-test-secret-0123456789abcd"
LINK_SECRET = b"link-token-test-secret-0123456789abcdef"
HASHER = HmacPhoneHasher(FixedSecretStore({PHONE_HASH_SECRET: PHONE_SECRET}))
INVITED_HASH = HASHER.hash(INVITED_MOBILE)
START = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
PURPOSE = "register"


class Rig:
    """One clock, one code store and one sender, shared by the request and the verify."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self.clock = FixedClock(START)
        self.codes = InMemoryCodeStore(self.clock)
        self.sender = RecordingCodeSender()
        secrets = FixedSecretStore({"code-hmac": CODE_SECRET, LINK_TOKEN_SECRET: LINK_SECRET})
        self.request = RequestTextCode(
            self.codes,
            self.sender,
            HASHER,
            uow_factory,
            secrets,
            self.clock,
            random.Random(2026),
        )
        self.verify = VerifyTextCode(self.codes, HASHER, uow_factory, secrets, self.clock)

    async def ask(self, mobile: str, key: str) -> RequestTextCodeResult:
        return await self.request.execute(
            RequestTextCodeCommand(idempotency_key=key, phone=mobile, purpose=PURPOSE)
        )

    async def enter(self, mobile: str, code: str) -> VerifyTextCodeResult:
        return await self.verify.execute(
            VerifyTextCodeCommand(phone=mobile, purpose=PURPOSE, code=code)
        )


@pytest.fixture
async def invited(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, clean_graph: None
) -> Rig:
    """An open invitation for the invited mobile: a link token with purpose invite, about the
    invitation, holding the phone's hash and expiring in 48 hours (U24's shape)."""
    await ensure_audit_head(neo4j_driver)
    rig = Rig(uow_factory)
    secrets = FixedSecretStore({LINK_TOKEN_SECRET: LINK_SECRET})
    async with uow_factory() as uow:
        tokens = LinkTokenService(uow.link_tokens, secrets, rig.clock)
        await tokens.issue("invite", "invitation-1", INVITED_HASH, START + timedelta(hours=48))
        await uow.commit()
    return rig


async def test_a_known_invited_phone_gets_one_code_and_the_store_holds_a_hash_not_the_digits(
    uow_factory: UnitOfWorkFactory, invited: Rig
) -> None:
    result = await invited.ask(INVITED_MOBILE, "req-1")
    assert result == RequestTextCodeResult(sent=True, retry_after_seconds=60)
    assert len(invited.sender.sent) == 1
    code = invited.sender.sent[0].code
    stored = await invited.codes.get(code_key(INVITED_HASH, PURPOSE))
    assert stored is not None
    stored_hash, _ = stored
    assert code not in stored_hash
    assert stored_hash != code


async def test_an_unknown_phone_gets_the_same_result_and_no_text(
    uow_factory: UnitOfWorkFactory, invited: Rig
) -> None:
    known = await invited.ask(INVITED_MOBILE, "req-known")
    unknown = await invited.ask(UNKNOWN_MOBILE, "req-unknown")
    assert unknown == known
    assert [message.phone for message in invited.sender.sent] == [INVITED_MOBILE]


async def test_a_second_request_after_thirty_seconds_sends_nothing_and_after_sixty_one_sends(
    uow_factory: UnitOfWorkFactory, invited: Rig
) -> None:
    await invited.ask(INVITED_MOBILE, "req-a")
    invited.clock.set(START + timedelta(seconds=30))
    again = await invited.ask(INVITED_MOBILE, "req-b")
    assert again == RequestTextCodeResult(sent=False, retry_after_seconds=30)
    assert len(invited.sender.sent) == 1
    invited.clock.set(START + timedelta(seconds=61))
    later = await invited.ask(INVITED_MOBILE, "req-c")
    assert later.sent is True
    assert len(invited.sender.sent) == 2


async def test_the_right_code_within_ten_minutes_verifies_once(
    uow_factory: UnitOfWorkFactory, invited: Rig
) -> None:
    await invited.ask(INVITED_MOBILE, "req-d")
    code = invited.sender.sent[-1].code
    invited.clock.set(START + timedelta(minutes=9))
    ok = await invited.enter(INVITED_MOBILE, code)
    assert ok.ok is True
    assert ok.invitation_id == "invitation-1"
    assert ok.verified_at == START + timedelta(minutes=9)
    again = await invited.enter(INVITED_MOBILE, code)
    assert again.ok is False
    assert again.needs_new_code is True


async def test_the_right_code_after_ten_minutes_and_one_second_is_refused(
    uow_factory: UnitOfWorkFactory, invited: Rig
) -> None:
    await invited.ask(INVITED_MOBILE, "req-e")
    code = invited.sender.sent[-1].code
    invited.clock.set(START + CODE_VALID_FOR + timedelta(seconds=1))
    late = await invited.enter(INVITED_MOBILE, code)
    assert late.ok is False
    assert late.needs_new_code is True


async def test_five_wrong_codes_use_the_code_up_and_even_the_right_one_then_fails(
    uow_factory: UnitOfWorkFactory, invited: Rig
) -> None:
    await invited.ask(INVITED_MOBILE, "req-f")
    right = invited.sender.sent[-1].code
    wrong = "000000" if right != "000000" else "111111"
    last: VerifyTextCodeResult | None = None
    for _ in range(5):
        last = await invited.enter(INVITED_MOBILE, wrong)
    assert last is not None
    assert last.tries_left == 0
    assert last.needs_new_code is True
    assert (await invited.enter(INVITED_MOBILE, right)).ok is False


async def test_the_audit_entries_hold_the_purpose_and_outcome_and_neither_code_nor_number(
    uow_factory: UnitOfWorkFactory, neo4j_driver: AsyncDriver, invited: Rig
) -> None:
    await invited.ask(INVITED_MOBILE, "req-g")
    code = invited.sender.sent[-1].code
    await invited.enter(INVITED_MOBILE, code)
    events: list[dict[str, Any]] = []
    for use_case in ("RequestTextCode", "VerifyTextCode"):
        events.append(await node_props(neo4j_driver, "AuditEvent", useCase=use_case))
    text = repr(events)
    assert code not in text
    assert "900456" not in text
    assert "register" in text
