"""Outbound port: sealing message content so that no token text is stored at rest (U03, DEC-116).

The sealed text is opened by the sender at send time. The associated data (the outbox message id,
the tenant and the recipient role) bind a sealed text to one message, tenant and recipient, so it
cannot be moved. The adapter is diucs.adapters.outbound.content_seal (AES-256-GCM).
"""

from typing import Protocol


class ContentSealer(Protocol):
    def seal(self, content: str, *, message_id: str, tenant_id: str, recipient_role_id: str) -> str:
        """Seal the text. Each call gives a different sealed text for the same content."""
        ...

    def unseal(
        self, sealed: str, *, message_id: str, tenant_id: str, recipient_role_id: str
    ) -> str:
        """The text a sealed text holds. Refused (ValidationFailed, field name only) for any text
        that is not in strict form, that does not verify, or that is bound to other data."""
        ...
