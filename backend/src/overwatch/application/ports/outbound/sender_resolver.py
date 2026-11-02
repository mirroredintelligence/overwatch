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

from overwatch.application.ports.outbound.messaging import EmailSender, SmsSender
from overwatch.application.ports.outbound.tenant_registry import TenantNumberRecord
from overwatch.domain.model.tenant_records import TenantChannel


class ChannelUnavailable(Exception):
    """The bound tenant has no usable sender for this channel. The message names the tenant id and
    the channel only: never a number, a secret reference or a secret."""


class SenderResolver(Protocol):
    async def sms_for(self) -> SmsSender:
        """The text sender of the bound tenant. Raises ChannelUnavailable when there is none."""
        ...

    async def provisioning_sms_for(self, number: TenantNumberRecord | None) -> SmsSender:
        """The text sender of ONE line of the bound tenant, for a test text while it is being set up
        (DEC-1319): the tenant's own number (its Twilio account and token by the number's own
        reference), or, for `None`, the platform's shared line. Unlike `sms_for` it does not need
        the tenant to be active, since a test is how a tenant gets ready to be. Raises
        ChannelUnavailable when the line cannot send (no token, no platform line)."""
        ...

    async def email_for(self, channel: TenantChannel | None) -> EmailSender:
        """The email sender of the bound tenant, from the tenant's active email channel record (the
        caller reads it in its own unit of work). Raises ChannelUnavailable when there is none."""
        ...

    async def admin_email_for(self, channel: TenantChannel | None) -> EmailSender:
        """The email sender for a message from the platform to a tenant's administrator (DEC-1316):
        the tenant's own email sender when it has a usable one, otherwise the platform's. One rule
        for every platform-admin email. A tenant message (a prompt, a booking) never uses this: it
        stays fail closed on `email_for`. Raises ChannelUnavailable when neither exists."""
        ...
