"""Pure tests of the Redis text-code store (I13): the record body and the refusals that come before
any Redis call. No Docker."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.outbound.cache_redis.code_store import RedisCodeStore, decode_code, encode_code
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import TenantNotBound, bind_tenant
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.identity_policy import CodeOutcome, CodeState

NO_CLIENT: Any = object()
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
CODE_HASH = "keyed-hash-sample"


def test_a_code_record_round_trips_with_its_state() -> None:
    state = CodeState(
        issued_at=NOW + timedelta(seconds=3),
        failed_tries=2,
        verified=False,
        last_outcome=CodeOutcome.WRONG,
    )
    assert decode_code(encode_code(CODE_HASH, state)) == (CODE_HASH, state)


def test_a_code_record_holds_the_hash_it_is_given() -> None:
    text = encode_code(CODE_HASH, CodeState(issued_at=NOW))
    assert CODE_HASH in text


@pytest.mark.parametrize("text", ["", "not json", "{}", '{"hash": 3}'])
def test_text_that_is_not_a_code_record_decodes_to_none(text: str) -> None:
    assert decode_code(text) is None


async def test_save_get_and_clear_without_a_tenant_are_refused_before_redis() -> None:
    store = RedisCodeStore(NO_CLIENT, FixedClock(NOW))
    with pytest.raises(TenantNotBound):
        await store.save("registration", "h1", CODE_HASH, CodeState(issued_at=NOW))
    with pytest.raises(TenantNotBound):
        await store.get("registration", "h1")
    with pytest.raises(TenantNotBound):
        await store.clear("registration", "h1")


async def test_an_issue_time_without_a_timezone_is_refused_before_redis() -> None:
    store = RedisCodeStore(NO_CLIENT, FixedClock(NOW))
    with bind_tenant("tenant-alpha"), pytest.raises(ValidationFailed):
        await store.save("registration", "h1", CODE_HASH, CodeState(issued_at=datetime(2026, 10, 25, 9, 0)))


async def test_a_purpose_that_is_not_a_plain_name_is_refused_before_redis() -> None:
    store = RedisCodeStore(NO_CLIENT, FixedClock(NOW))
    with bind_tenant("tenant-alpha"), pytest.raises(ValidationFailed):
        await store.save("sign:in", "h1", CODE_HASH, CodeState(issued_at=NOW))
