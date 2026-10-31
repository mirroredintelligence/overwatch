"""The code request leaves the sender what it needs to text a known number (KI-270, N1).

The outbox message of a code carries, besides the sealed code, the recipient key the seal is bound
to, the number sealed under the same message, tenant and key, and the time the code was issued.
The number is never in the clear. A known and an unknown number get the same payload shape, so the
only difference is the event type (H-96). Sample numbers only.
"""

import json
import random
from typing import Any

import pytest

from diucs.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.adapters.testing.fixed_secrets import FixedSecretStore
from diucs.adapters.testing.memory_code_store import InMemoryCodeStore
from diucs.application.use_cases.text_code import (
    DISCARD_CODE,
    SEND_CODE,
    RequestTextCode,
    RequestTextCodeCommand,
    code_key,
)
from diucs.domain.errors import ValidationFailed
from tests.unit.application.use_cases.test_text_code_timing import (
    CLOCK_AT,
    HASHER,
    KNOWN_HASH,
    KNOWN_MOBILE,
    UNKNOWN_HASH,
    UNKNOWN_MOBILE,
    Calls,
    _practitioner,
    _Store,
    _Unit,
)

SEALER = AesGcmContentSealer(
    FixedSecretStore({"link-token": b"link-token-test-secret-0123456789abcdef"})
)
TENANT = "default"


async def _request(mobile: str, held: dict[str, Any], purpose: str = "register") -> Any:
    calls = Calls()
    clock = FixedClock(CLOCK_AT)
    use_case = RequestTextCode(
        _Store(calls, InMemoryCodeStore(clock)),
        HASHER,
        lambda: _Unit(calls, held, {}),  # type: ignore[arg-type, return-value]
        FixedSecretStore({"code-hmac": b"code-hmac-test-secret-0123456789abcdef"}),
        SEALER,
        SequentialIds("m"),
        clock,
        random.Random(11),
    )
    await use_case.execute(
        RequestTextCodeCommand(idempotency_key="req-1", phone=mobile, purpose=purpose)
    )
    (message,) = calls.outbox
    return message


async def test_the_payload_names_the_recipient_key_and_the_issue_time() -> None:
    message = await _request(KNOWN_MOBILE, {KNOWN_HASH: _practitioner(KNOWN_HASH)})

    assert message.payload["recipient_key"] == code_key(KNOWN_HASH, "register")
    assert message.payload["purpose"] == "register"
    assert message.payload["issued_at"] == CLOCK_AT.isoformat()


async def test_the_number_is_sealed_to_this_message_tenant_and_recipient_key() -> None:
    message = await _request(KNOWN_MOBILE, {KNOWN_HASH: _practitioner(KNOWN_HASH)})
    key = message.payload["recipient_key"]

    opened = SEALER.unseal(
        message.payload["sealed_phone"],
        message_id=message.id,
        tenant_id=TENANT,
        recipient_role_id=key,
    )

    assert opened == "+447700900456"
    code = SEALER.unseal(
        message.payload["sealed_code"],
        message_id=message.id,
        tenant_id=TENANT,
        recipient_role_id=key,
    )
    assert code.isdigit() and len(code) == 6


async def test_the_sealed_number_cannot_be_moved_to_another_message_or_tenant() -> None:
    message = await _request(KNOWN_MOBILE, {KNOWN_HASH: _practitioner(KNOWN_HASH)})
    key = message.payload["recipient_key"]

    with pytest.raises(ValidationFailed):
        SEALER.unseal(
            message.payload["sealed_phone"],
            message_id="m-other",
            tenant_id=TENANT,
            recipient_role_id=key,
        )
    with pytest.raises(ValidationFailed):
        SEALER.unseal(
            message.payload["sealed_phone"],
            message_id=message.id,
            tenant_id="other",
            recipient_role_id=key,
        )


async def test_no_digit_of_the_number_or_the_code_is_in_the_clear() -> None:
    message = await _request(KNOWN_MOBILE, {KNOWN_HASH: _practitioner(KNOWN_HASH)})
    clear = json.dumps({k: v for k, v in message.payload.items() if not k.startswith("sealed_")})
    code = SEALER.unseal(
        message.payload["sealed_code"],
        message_id=message.id,
        tenant_id=TENANT,
        recipient_role_id=message.payload["recipient_key"],
    )

    for secret in ("7700", "900456", "07700", code):
        assert secret not in clear
    for field in ("sealed_phone", "sealed_code"):
        assert "900456" not in message.payload[field]


async def test_a_known_and_an_unknown_number_leave_the_same_payload_shape() -> None:
    known = await _request(KNOWN_MOBILE, {KNOWN_HASH: _practitioner(KNOWN_HASH)})
    unknown = await _request(UNKNOWN_MOBILE, {})

    assert (known.event_type, unknown.event_type) == (SEND_CODE, DISCARD_CODE)
    assert set(known.payload) == set(unknown.payload)
    assert unknown.payload["recipient_key"] == code_key(UNKNOWN_HASH, "register")
    assert unknown.payload["issued_at"] == known.payload["issued_at"]
