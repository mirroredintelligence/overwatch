"""Outbound port: the sender for the bound tenant, resolved at send time (I10, DEC-131 item 1).

Text and email go from the tenant's own Twilio subaccount and sender identity, so a sender is
chosen per tenant and never shared. The resolver returns the sender for one tenant, or None when
that tenant has no such channel: the caller then records the message as failed and sends nothing
(fail closed, H-T03). Credentials are secret-store references held by the resolver's adapter; the
sender port itself never sees a tenant id.
"""

from typing import Protocol

from diucs.application.ports.outbound.messaging import EmailSender, SmsSender


class SenderResolver(Protocol):
    async def sms_for(self, tenant_id: str) -> SmsSender | None: ...

    async def email_for(self, tenant_id: str) -> EmailSender | None: ...
