"""Unit tests for the text-code fake (P16, DEC-070). Redis is the production store (I13); this fake
keeps the same contract: a code's state is gone once it has been valid for ten minutes."""

from datetime import UTC, datetime, timedelta

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_code_store import InMemoryCodeStore, RecordingCodeSender
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.identity_policy import CodeState

ISSUED = datetime(2026, 10, 25, 11, 0, tzinfo=UTC)
PHONE_HASH = "e" * 64
CODE_HASH = "f" * 64
STATE = CodeState(issued_at=ISSUED)


async def test_the_code_state_is_returned_until_the_clock_passes_ten_minutes() -> None:
    clock = FixedClock(ISSUED)
    store = InMemoryCodeStore(clock)
    await store.save(PHONE_HASH, CODE_HASH, STATE)

    clock.set(ISSUED + timedelta(minutes=9, seconds=59))
    assert await store.get(PHONE_HASH) == (CODE_HASH, STATE)

    clock.set(ISSUED + timedelta(minutes=10))
    assert await store.get(PHONE_HASH) is None


async def test_an_unknown_phone_hash_has_no_code() -> None:
    store = InMemoryCodeStore(FixedClock(ISSUED))
    assert await store.get(PHONE_HASH) is None


async def test_clear_removes_the_code_for_that_phone_only() -> None:
    store = InMemoryCodeStore(FixedClock(ISSUED))
    await store.save(PHONE_HASH, CODE_HASH, STATE)
    await store.save("d" * 64, "c" * 64, STATE)

    await store.clear(PHONE_HASH)

    assert await store.get(PHONE_HASH) is None
    assert await store.get("d" * 64) == ("c" * 64, STATE)


async def test_recording_code_sender_records_the_phone_and_the_code() -> None:
    sender = RecordingCodeSender()

    await sender.send_code("07700 900123", "482913")
    await sender.send_code("07700 900456", "101112")

    assert [(sent.phone, sent.code) for sent in sender.sent] == [
        ("07700 900123", "482913"),
        ("07700 900456", "101112"),
    ]


async def test_a_code_saved_with_a_naive_issue_time_is_refused() -> None:
    store = InMemoryCodeStore(FixedClock(ISSUED))

    with pytest.raises(ValidationFailed):
        await store.save(PHONE_HASH, CODE_HASH, CodeState(issued_at=datetime(2026, 10, 25, 11, 0)))

    assert await store.get(PHONE_HASH) is None
