"""AES-256-GCM sealing of prompt content (U03, DEC-116).

The key is derived from the link-token secret with HMAC-SHA256 and a fixed label, so the secret
itself never keys the cipher directly. A seal is `v2.` followed by unpadded base64url of the 96-bit
nonce and the ciphertext with its 128-bit tag. The associated data is canonical JSON of the message
id, the tenant id and the recipient role id. Decoding is strict: no padding, only the base64url
alphabet, the canonical encoding, and a minimum length. Every refusal is ValidationFailed with the
field name only, never the text.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, SecretStore
from diucs.domain.errors import ValidationFailed

SEAL_VERSION: Final = "v2."
NONCE_BYTES: Final = 12
TAG_BYTES: Final = 16
KEY_BYTES: Final = 32
MIN_SECRET_BYTES: Final = 32
_KEY_LABEL: Final = b"diucs:prompt-content:v2"
_NOT_SEALED: Final = "is not a sealed prompt"


def derive_key(secret: bytes) -> bytes:
    """The 256-bit content key, derived from the link secret with a fixed label. A secret shorter
    than 32 bytes is refused (DEC-116 item 2)."""
    if len(secret) < MIN_SECRET_BYTES:
        raise ValidationFailed("secret", "must be at least 32 bytes")
    return hmac.new(secret, _KEY_LABEL, hashlib.sha256).digest()


def _check_key(key: bytes) -> None:
    if len(key) != KEY_BYTES:
        raise ValidationFailed("key", "must be 32 bytes")


def _associated(message_id: str, tenant_id: str, recipient_role_id: str) -> bytes:
    """The associated data as canonical JSON (sorted keys, no spaces), so that sealed content cannot
    be moved to another message, tenant or recipient (DEC-116 item 3)."""
    return json.dumps(
        {"message_id": message_id, "recipient_role_id": recipient_role_id, "tenant_id": tenant_id},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def seal_content(
    content: str, key: bytes, *, message_id: str, tenant_id: str, recipient_role_id: str
) -> str:
    """Seal text with AES-256-GCM. The nonce is 96 random bits from the operating system, one per
    seal, and is kept in the sealed text (DEC-116 item 4)."""
    _check_key(key)
    nonce = os.urandom(NONCE_BYTES)
    aad = _associated(message_id, tenant_id, recipient_role_id)
    sealed = AESGCM(key).encrypt(nonce, content.encode("utf-8"), aad)
    return SEAL_VERSION + base64.urlsafe_b64encode(nonce + sealed).rstrip(b"=").decode("ascii")


def unseal_content(
    sealed: str, key: bytes, *, message_id: str, tenant_id: str, recipient_role_id: str
) -> str:
    """The text a seal holds, when the seal is in strict form and verifies under this key and these
    associated data (DEC-116 item 5)."""
    _check_key(key)
    if not sealed.startswith(SEAL_VERSION) or "=" in sealed:
        raise ValidationFailed("sealed_content", _NOT_SEALED)
    body = sealed[len(SEAL_VERSION) :]
    try:
        raw = base64.b64decode(body + "=" * (-len(body) % 4), altchars=b"-_", validate=True)
    except ValueError, binascii.Error:
        raise ValidationFailed("sealed_content", _NOT_SEALED) from None
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != body:
        raise ValidationFailed("sealed_content", _NOT_SEALED)
    if len(raw) < NONCE_BYTES + TAG_BYTES:
        raise ValidationFailed("sealed_content", _NOT_SEALED)
    aad = _associated(message_id, tenant_id, recipient_role_id)
    try:
        plain = AESGCM(key).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], aad)
    except InvalidTag:
        raise ValidationFailed("sealed_content", "does not verify") from None
    return plain.decode("utf-8")


class AesGcmContentSealer:
    """The ContentSealer port, keyed from the link-token secret in the secret store."""

    def __init__(self, secrets: SecretStore) -> None:
        self._secrets = secrets

    def _key(self) -> bytes:
        return derive_key(self._secrets.get(LINK_TOKEN_SECRET))

    def seal(self, content: str, *, message_id: str, tenant_id: str, recipient_role_id: str) -> str:
        return seal_content(
            content,
            self._key(),
            message_id=message_id,
            tenant_id=tenant_id,
            recipient_role_id=recipient_role_id,
        )

    def unseal(
        self, sealed: str, *, message_id: str, tenant_id: str, recipient_role_id: str
    ) -> str:
        return unseal_content(
            sealed,
            self._key(),
            message_id=message_id,
            tenant_id=tenant_id,
            recipient_role_id=recipient_role_id,
        )
