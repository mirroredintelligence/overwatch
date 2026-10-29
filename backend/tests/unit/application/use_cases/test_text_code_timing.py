"""The request for a code answers a known and an unknown number with the same calls, in the same
order, and the same result (U25, H-96). The ports are recording doubles, so the sequence of calls
before the result returns can be compared. Only the outbox event differs: SendCode for a known
number, DiscardCode for an unknown one. The sender acts on SendCode alone.
"""

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_code_store import InMemoryCodeStore
from diucs.application.ports.outbound.identity import PHONE_HASH_SECRET, HmacPhoneHasher
from diucs.application.tenancy import ScopeId
from diucs.application.use_cases.text_code import (
    DISCARD_CODE,
    SEND_CODE,
    RequestTextCode,
    RequestTextCodeCommand,
)
from diucs.domain.model.people import Practitioner
from diucs.domain.rules.tokens import LinkTokenRecord

CLOCK_AT = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)
KNOWN_MOBILE = "07700 900456"
UNKNOWN_MOBILE = "07700 900999"
HASHER = HmacPhoneHasher(
    FixedSecretStore({PHONE_HASH_SECRET: b"phone-hash-test-secret-0123456789ab"})
)
KNOWN_HASH = HASHER.hash(KNOWN_MOBILE)
UNKNOWN_HASH = HASHER.hash(UNKNOWN_MOBILE)


@dataclass
class Calls:
    """Every call the request makes, by port and method, in order, and the outbox messages."""

    names: list[str] = field(default_factory=list)
    outbox: list[Any] = field(default_factory=list)


class _Named:
    def __init__(self, calls: Calls, name: str) -> None:
        self._calls = calls
        self._name = name

    def log(self, method: str) -> None:
        self._calls.names.append(f"{self._name}.{method}")


class _People(_Named):
    def __init__(self, calls: Calls, held: dict[str, Practitioner]) -> None:
        super().__init__(calls, "people")
        self._held = held

    async def find_by_phone_hash(self, phone_hash: str) -> Practitioner | None:
        self.log("find_by_phone_hash")
        return self._held.get(phone_hash)


class _Links(_Named):
    def __init__(self, calls: Calls, open_links: dict[str, LinkTokenRecord]) -> None:
        super().__init__(calls, "link_tokens")
        self._open = open_links

    async def open_for_phone(
        self, purpose: str, phone_hash: str, now: datetime
    ) -> LinkTokenRecord | None:
        self.log("open_for_phone")
        return self._open.get(phone_hash)


class _Idempotency(_Named):
    def __init__(self, calls: Calls) -> None:
        super().__init__(calls, "idempotency")
        self._stored: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        self.log("get")
        return self._stored.get(key)

    async def put(self, key: str, result: Any) -> None:
        self.log("put")
        self._stored[key] = result


class _Audit(_Named):
    def __init__(self, calls: Calls) -> None:
        super().__init__(calls, "audit")

    async def append(self, entry: Any) -> None:
        self.log("append")


class _Outbox(_Named):
    def __init__(self, calls: Calls) -> None:
        super().__init__(calls, "outbox")

    async def add(self, message: Any) -> None:
        self.log("add")
        self._calls.outbox.append(message)


class _Unit:
    def __init__(
        self, calls: Calls, held: dict[str, Practitioner], open_links: dict[str, LinkTokenRecord]
    ) -> None:
        self.people = _People(calls, held)
        self.link_tokens = _Links(calls, open_links)
        self.idempotency = _Idempotency(calls)
        self.audit = _Audit(calls)
        self.outbox = _Outbox(calls)
        self._calls = calls

    @property
    def unit_scope(self) -> ScopeId:
        return ScopeId.tenant("default")

    async def __aenter__(self) -> _Unit:
        self._calls.names.append("uow.enter")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._calls.names.append("uow.exit")

    async def commit(self) -> None:
        self._calls.names.append("uow.commit")


class _Store:
    """The code store, counted: a real in-memory store is a fake of a non-record store."""

    def __init__(self, calls: Calls, inner: InMemoryCodeStore) -> None:
        self._calls = calls
        self._inner = inner

    async def get(self, purpose: str, phone_hash: str) -> Any:
        self._calls.names.append("codes.get")
        return await self._inner.get(purpose, phone_hash)

    async def save(self, purpose: str, phone_hash: str, code_hash: str, state: Any) -> None:
        self._calls.names.append("codes.save")
        await self._inner.save(purpose, phone_hash, code_hash, state)

    async def clear(self, purpose: str, phone_hash: str) -> None:
        self._calls.names.append("codes.clear")
        await self._inner.clear(purpose, phone_hash)


class _Sealer:
    def __init__(self, calls: Calls) -> None:
        self._calls = calls

    def seal(self, content: str, *, message_id: str, tenant_id: str, recipient_role_id: str) -> str:
        self._calls.names.append("sealer.seal")
        return f"sealed:{len(content)}:{message_id}"


def _practitioner(hash_: str) -> Practitioner:
    return Practitioner(id="prac-1", active=True, display_name="Reporter", phone_hash=hash_)


def _invitation(hash_: str) -> LinkTokenRecord:
    return LinkTokenRecord(
        token_hash="cd" * 32,
        purpose="invite",
        about_id="invitation-1",
        phone_hash=hash_,
        expires_at=CLOCK_AT + timedelta(hours=48),
        used_at=None,
    )


async def _request(
    mobile: str, held: dict[str, Practitioner], open_links: dict[str, LinkTokenRecord]
) -> tuple[Any, Calls]:
    calls = Calls()
    clock = FixedClock(CLOCK_AT)
    store = _Store(calls, InMemoryCodeStore(clock))
    use_case = RequestTextCode(
        store,
        HASHER,
        lambda: _Unit(calls, held, open_links),
        FixedSecretStore({"code-hmac": b"code-hmac-test-secret-0123456789abcdef"}),
        _Sealer(calls),
        SequentialIds("m"),
        clock,
        random.Random(11),
    )
    result = await use_case.execute(
        RequestTextCodeCommand(idempotency_key="req-1", phone=mobile, purpose="register")
    )
    return result, calls


@pytest.mark.parametrize(
    "held_practitioner", [True, False], ids=["registered-practitioner", "open-invitation"]
)
async def test_a_known_number_and_an_unknown_one_make_the_same_calls_before_the_answer(
    held_practitioner: bool,
) -> None:
    if held_practitioner:
        known_held, known_links = {KNOWN_HASH: _practitioner(KNOWN_HASH)}, {}
    else:
        known_held, known_links = {}, {KNOWN_HASH: _invitation(KNOWN_HASH)}
    known_result, known_calls = await _request(KNOWN_MOBILE, known_held, known_links)
    unknown_result, unknown_calls = await _request(UNKNOWN_MOBILE, {}, {})
    assert known_calls.names == unknown_calls.names
    assert known_result == unknown_result


async def test_the_answer_is_the_same_for_a_known_and_an_unknown_number() -> None:
    known, _ = await _request(KNOWN_MOBILE, {KNOWN_HASH: _practitioner(KNOWN_HASH)}, {})
    unknown, _ = await _request(UNKNOWN_MOBILE, {}, {})
    assert known == unknown
    assert known.sent is True
    assert known.retry_after_seconds == 60


async def test_only_a_known_number_is_enqueued_to_be_sent() -> None:
    _, known_calls = await _request(KNOWN_MOBILE, {KNOWN_HASH: _practitioner(KNOWN_HASH)}, {})
    _, unknown_calls = await _request(UNKNOWN_MOBILE, {}, {})
    assert [m.event_type for m in known_calls.outbox] == [SEND_CODE]
    assert [m.event_type for m in unknown_calls.outbox] == [DISCARD_CODE]
    assert SEND_CODE not in [m.event_type for m in unknown_calls.outbox]


async def test_the_send_carries_a_sealed_code_never_the_digits_and_no_tenant_in_the_body() -> None:
    # TEN-020: the tenant is a message property the relay sets from the row's own tenant, never a
    # field of the body (a body copy would be a second, forgeable source), and a bus message whose
    # payload names a tenant is refused. The consumer opens the sealed code with the bound tenant.
    _, known_calls = await _request(KNOWN_MOBILE, {KNOWN_HASH: _practitioner(KNOWN_HASH)}, {})
    (message,) = known_calls.outbox
    assert not {"tenantId", "tenant_id", "tenant"} & set(message.payload)
    assert message.payload["sealed_code"].startswith("sealed:6:")
    assert KNOWN_MOBILE not in repr(message.payload)
