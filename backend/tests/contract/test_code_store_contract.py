"""Contract for the text-code store (I13, D27). Runs against every factory in factories.py: the
in-memory fake in every run, and Redis under the integration marker.

A code is keyed by (tenant, purpose, phone hash). The text code itself is never stored: the caller
passes its keyed hash, and these tests use sample hashes. Durations are seconds or minutes of the
clock the harness gives, never wall time.
"""

from datetime import datetime, timedelta

import pytest

from diucs.application.ports.outbound.identity import CodeResendRefused, CodeStore
from diucs.domain.errors import ValidationFailed
from diucs.domain.rules.identity_policy import (
    CODE_MAX_TRIES,
    CODE_RESEND_AFTER,
    CODE_VALID_FOR,
    CodeOutcome,
    CodeState,
    code_attempt,
)
from tests.contract.harness import Harness

REGISTRATION = "registration"
SIGN_IN = "sign-in"
HASH_A = "keyed-hash-of-the-first-code"
HASH_B = "keyed-hash-of-the-second-code"
HASH_C = "keyed-hash-of-the-third-code"
TEN_SECONDS = timedelta(seconds=10)


async def test_a_right_code_verifies(code_store_harness: Harness[CodeStore]) -> None:
    store = code_store_harness.subject
    now = code_store_harness.now()
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=now))

    stored = await store.get(REGISTRATION, "h1")
    assert stored is not None
    code_hash, state = stored
    assert code_hash == HASH_A
    await store.save(REGISTRATION, "h1", code_hash, code_attempt(state, entered_ok=True, now=now))

    stored = await store.get(REGISTRATION, "h1")
    assert stored is not None
    assert stored[1].verified is True
    assert stored[1].last_outcome is CodeOutcome.VERIFIED


async def test_five_wrong_tries_lock_the_code(code_store_harness: Harness[CodeStore]) -> None:
    store = code_store_harness.subject
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=code_store_harness.now()))

    for _ in range(CODE_MAX_TRIES):
        stored = await store.get(REGISTRATION, "h1")
        assert stored is not None
        code_hash, state = stored
        judged = code_attempt(state, entered_ok=False, now=code_store_harness.now())
        await store.save(REGISTRATION, "h1", code_hash, judged)

    stored = await store.get(REGISTRATION, "h1")
    assert stored is not None
    assert stored[1].failed_tries == CODE_MAX_TRIES
    assert stored[1].last_outcome is CodeOutcome.TOO_MANY_TRIES
    # Once locked, the right code is refused too.
    refused = code_attempt(stored[1], entered_ok=True, now=code_store_harness.now())
    assert refused.verified is False
    assert refused.last_outcome is CodeOutcome.TOO_MANY_TRIES


async def test_a_code_expires_ten_minutes_after_it_is_issued(
    code_store_harness: Harness[CodeStore],
) -> None:
    store = code_store_harness.subject
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=code_store_harness.now()))

    await code_store_harness.advance(CODE_VALID_FOR - TEN_SECONDS)
    assert await store.get(REGISTRATION, "h1") is not None

    await code_store_harness.advance(TEN_SECONDS * 2)
    assert await store.get(REGISTRATION, "h1") is None


async def test_a_resend_inside_sixty_seconds_is_refused(
    code_store_harness: Harness[CodeStore],
) -> None:
    store = code_store_harness.subject
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=code_store_harness.now()))
    await code_store_harness.advance(CODE_RESEND_AFTER - TEN_SECONDS)

    with pytest.raises(CodeResendRefused):
        await store.save(
            REGISTRATION, "h1", HASH_B, CodeState(issued_at=code_store_harness.now())
        )

    stored = await store.get(REGISTRATION, "h1")
    assert stored is not None
    assert stored[0] == HASH_A, "a refused resend leaves the first code in place"


async def test_a_resend_after_sixty_seconds_replaces_the_code(
    code_store_harness: Harness[CodeStore],
) -> None:
    store = code_store_harness.subject
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=code_store_harness.now()))
    await code_store_harness.advance(CODE_RESEND_AFTER + TEN_SECONDS)

    await store.save(REGISTRATION, "h1", HASH_B, CodeState(issued_at=code_store_harness.now()))

    stored = await store.get(REGISTRATION, "h1")
    assert stored is not None
    assert stored[0] == HASH_B


async def test_saving_the_same_code_again_updates_its_tries_at_any_time(
    code_store_harness: Harness[CodeStore],
) -> None:
    store = code_store_harness.subject
    issued = code_store_harness.now()
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=issued))

    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=issued, failed_tries=1))

    stored = await store.get(REGISTRATION, "h1")
    assert stored is not None
    assert stored[1].failed_tries == 1


async def test_clear_removes_the_code_and_a_missing_clear_is_not_an_error(
    code_store_harness: Harness[CodeStore],
) -> None:
    store = code_store_harness.subject
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=code_store_harness.now()))

    await store.clear(REGISTRATION, "h1")
    await store.clear(REGISTRATION, "h1")

    assert await store.get(REGISTRATION, "h1") is None


async def test_codes_are_kept_per_phone_hash(code_store_harness: Harness[CodeStore]) -> None:
    store = code_store_harness.subject
    now = code_store_harness.now()
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=now))
    await store.save(REGISTRATION, "h2", HASH_B, CodeState(issued_at=now))

    await store.clear(REGISTRATION, "h1")

    assert await store.get(REGISTRATION, "h1") is None
    stored = await store.get(REGISTRATION, "h2")
    assert stored is not None
    assert stored[0] == HASH_B


async def test_the_same_phone_holds_two_independent_codes_for_two_purposes(
    code_store_harness: Harness[CodeStore],
) -> None:
    store = code_store_harness.subject
    now = code_store_harness.now()
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=now))
    await store.save(SIGN_IN, "h1", HASH_B, CodeState(issued_at=now))

    registration = await store.get(REGISTRATION, "h1")
    sign_in = await store.get(SIGN_IN, "h1")
    assert registration is not None and registration[0] == HASH_A
    assert sign_in is not None and sign_in[0] == HASH_B

    await store.clear(REGISTRATION, "h1")

    assert await store.get(REGISTRATION, "h1") is None
    sign_in = await store.get(SIGN_IN, "h1")
    assert sign_in is not None and sign_in[0] == HASH_B


async def test_a_code_issued_for_one_purpose_is_not_found_for_another(
    code_store_harness: Harness[CodeStore],
) -> None:
    store = code_store_harness.subject
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=code_store_harness.now()))

    assert await store.get(SIGN_IN, "h1") is None
    stored = await store.get(REGISTRATION, "h1")
    assert stored is not None
    assert stored[0] == HASH_A


async def test_a_resend_cooldown_is_kept_per_purpose(
    code_store_harness: Harness[CodeStore],
) -> None:
    """A code for another purpose does not start or end the cooldown of this one."""
    store = code_store_harness.subject
    await store.save(REGISTRATION, "h1", HASH_A, CodeState(issued_at=code_store_harness.now()))
    await code_store_harness.advance(TEN_SECONDS)

    # A new code for a different purpose is allowed at once.
    await store.save(SIGN_IN, "h1", HASH_B, CodeState(issued_at=code_store_harness.now()))

    # A new code for the first purpose is still inside its own cooldown.
    with pytest.raises(CodeResendRefused):
        await store.save(
            REGISTRATION, "h1", HASH_C, CodeState(issued_at=code_store_harness.now())
        )


async def test_an_unknown_purpose_is_refused(code_store_harness: Harness[CodeStore]) -> None:
    store = code_store_harness.subject
    now = code_store_harness.now()
    for bad in ("", "Sign In", "a:b", "x" * 40):
        with pytest.raises(ValidationFailed):
            await store.save(bad, "h1", HASH_A, CodeState(issued_at=now))


async def test_get_of_an_unknown_phone_hash_is_none(code_store_harness: Harness[CodeStore]) -> None:
    assert await code_store_harness.subject.get(REGISTRATION, "never-saved") is None


async def test_an_issue_time_without_a_timezone_is_refused(
    code_store_harness: Harness[CodeStore],
) -> None:
    naive: datetime = datetime(2026, 10, 25, 12, 0)
    with pytest.raises(ValidationFailed):
        await code_store_harness.subject.save(
            REGISTRATION, "h1", HASH_A, CodeState(issued_at=naive)
        )
