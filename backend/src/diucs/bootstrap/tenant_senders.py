"""The production SenderResolver (I10, DEC-131): the bound tenant's own number and subaccount.

The resolver reads the tenant from the bound unit of work only (`current_tenant`), asks the tenant
directory for that tenant's one active number (`active_line`), and reads the subaccount's auth token
through the secret store, by the reference the directory holds (never the value in the graph). The
sender is a TwilioSms on that subaccount, sending from that number, with the status callback of the
inbound webhook (I07).

Fail closed. A tenant with no active number (none, suspended or quarantined), a number that is not
this tenant's, a missing secret, a registry fault or a tenant with no email identity raises
ChannelUnavailable, whose text names the tenant id and the channel only. No number, reference or
secret is ever in an error or a log. A missing bound tenant is a TenancyError, never a default.
"""

from typing import Final

import httpx

from diucs.adapters.inbound.sms_webhook.routes import STATUS_PATH
from diucs.adapters.outbound.sms_twilio.twilio_sms import TwilioSms
from diucs.application.ports.outbound.messaging import EmailSender, SmsSender
from diucs.application.ports.outbound.sender_resolver import ChannelUnavailable
from diucs.application.ports.outbound.tenants import (
    TenantDirectory,
    TenantLine,
    TenantRecordInvalid,
)
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.tenancy import current_tenant
from diucs.bootstrap.settings import Settings
from diucs.domain.errors import NotFound

TEXT_CHANNEL: Final = "text"
EMAIL_CHANNEL: Final = "email"


def status_callback_url(settings: Settings) -> str:
    """The URL Twilio posts delivery receipts to: the inbound status webhook of this deployment."""
    return settings.base_url.rstrip("/") + STATUS_PATH


class TenantSenderResolver:
    """The SenderResolver of the production profile. The directory, the secret store and the HTTP
    client are injected; the tenant is never a parameter."""

    def __init__(
        self,
        directory: TenantDirectory,
        secrets: SecretStore,
        http: httpx.AsyncClient,
        status_url: str,
    ) -> None:
        self._directory = directory
        self._secrets = secrets
        self._http = http
        self._status_url = status_url

    async def sms_for(self) -> SmsSender:
        tenant = current_tenant()
        line = await self._line(tenant)
        token = self._token(tenant, line)
        return TwilioSms(self._http, line.account_sid, token, line.number, self._status_url)

    async def email_for(self) -> EmailSender:
        # No email identity is held in tenant configuration yet (TEN-007 holds the text number
        # only), so no tenant has an email channel: every email is refused, not sent by default.
        raise ChannelUnavailable(f"no {EMAIL_CHANNEL} channel for tenant {current_tenant()}")

    async def _line(self, tenant: str) -> TenantLine:
        unavailable = ChannelUnavailable(f"no {TEXT_CHANNEL} channel for tenant {tenant}")
        try:
            line = await self._directory.active_line(tenant)
        except TenantRecordInvalid:
            raise unavailable from None
        if line is None or line.tenant.id != tenant:
            raise unavailable
        return line

    def _token(self, tenant: str, line: TenantLine) -> str:
        unavailable = ChannelUnavailable(f"no {TEXT_CHANNEL} channel for tenant {tenant}")
        try:
            raw = self._secrets.get(line.secret_ref)
        except NotFound:
            raise unavailable from None
        try:
            token = raw.decode("ascii").strip()
        except UnicodeDecodeError:
            raise unavailable from None
        if not token:
            raise unavailable
        return token
