"""
Outbound port: the sender for the bound tenant, resolved at send time (I10, DEC-131 item 1). Text
and email go from the tenant's own Twilio subaccount and sender identity, so a sender is chosen
per tenant and never shared. The resolver takes no tenant argument: it reads the tenant of the
unit of work that is bound for the message (TenantBoundConsumer), and nothing else. When that
tenant has no usable sender for the channel (no active number, a suspended or quarantined number,
a missing secret, no email identity), the resolver raises ChannelUnavailable, and the sender
records the message as failed and sends nothing (fail closed, H-T03). Credentials are secret-store
references held by the adapter; the sender port never sees a tenant id or a secret.
"""

from typing import Protocol

from diucs.application.ports.outbound.messaging import EmailSender, SmsSender
from diucs.domain.model.tenant_records import TenantChannel


class ChannelUnavailable(Exception):
    """The bound tenant has no usable sender for this channel. The message names the tenant id and
    the channel only: never a number, a secret reference or a secret."""


class SenderResolver(Protocol):
    async def sms_for(self) -> SmsSender:
        """The text sender of the bound tenant. Raises ChannelUnavailable when there is none."""
        ...

    async def email_for(self, channel: TenantChannel | None) -> EmailSender:
        """The email sender of the bound tenant, from the tenant's active email channel record (the
        caller reads it in its own unit of work). Raises ChannelUnavailable when there is none."""
        ...
