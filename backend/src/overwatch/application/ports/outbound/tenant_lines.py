"""Outbound port: which tenant owns an inbound number or a Twilio subaccount (I07, DEC-131).

The number a text was sent to (`To`) and the account that carried it (`AccountSid`) identify the
tenant. The tenant is never taken from the sender, the message body, a query string or a header.
A line holds the tenant id and the secret-store reference of that subaccount's auth token (DEC-131
item 4); the token itself is read through the SecretStore when the signature is checked.

The tenant directory is built by TEN-007, and TEN-041 plugs its inbound-number resolver in here.
Until then the only implementation is the fake in `adapters/testing/fixed_inbound_lines.py`.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class InboundLine:
    tenant_id: str
    token_secret: str


class InboundLineDirectory(Protocol):
    async def for_number(self, to_number: str, account_sid: str) -> InboundLine | None:
        """The line for a number called and the account that carried the call, or None. Both
        must match: a number under another account is not found."""
        ...

    async def for_account(self, account_sid: str) -> InboundLine | None:
        """The line for a Twilio subaccount, or None. Used for delivery receipts (DEC-131 item 2),
        which are matched by AccountSid and message id."""
        ...
