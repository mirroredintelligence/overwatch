"""One sealer for tests that build the capacity, reply and invitation use cases.

Every outbound text is sealed (DEC-1336), so these use cases refuse to run without a sealer. The
secret is a test value."""

import json

from overwatch.adapters.outbound.content_seal.aes_gcm import AesGcmContentSealer
from overwatch.adapters.testing.fixed_secrets import FixedSecretStore

TEST_SEAL_SECRET = b"link-token-test-secret-0123456789abcdef"
TEST_SEALER = AesGcmContentSealer(FixedSecretStore({"link-token": TEST_SEAL_SECRET}))


def text_of(message: object, tenant_id: str) -> str:
    """The text an outbox message carries, opened the way the sender opens it."""
    payload = message.payload  # type: ignore[attr-defined]
    body = json.loads(
        TEST_SEALER.unseal(
            payload["sealed_content"],
            message_id=message.id,  # type: ignore[attr-defined]
            tenant_id=tenant_id,
            recipient_role_id=payload["recipient_role_id"],
        )
    )
    return str(body["text"])
