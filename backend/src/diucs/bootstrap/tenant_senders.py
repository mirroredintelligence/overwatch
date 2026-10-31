"""The production SenderResolver (I10, DEC-131): the bound tenant's own number and subaccount.

The resolver reads the tenant from the bound unit of work only (`current_tenant`), asks the tenant
directory for that tenant's one active number (`active_line`), and reads the subaccount's auth token
through the secret store, by the reference the directory holds (never the value in the graph). The
sender is a TwilioSms on that subaccount, sending from that number, with the status callback of the
inbound webhook (I07).

Email (TEN-042, DEC-1130): the caller reads the tenant's active email channel in its own unit of
work and hands the record over. A Twilio email channel (the provider of every new one) is sent with
a TwilioEmail on the same subaccount, Account SID and token as the tenant's text line. A channel
recorded before DEC-1130 still names the SMTP relay; for it the resolver builds an SmtpEmail from
the channel's sender address and display name, the login (the channel's address) and the password,
which is the secret the channel's own reference names. Every credential is a network secret read
from the secret store by a reference of the shape `<kind>/<own tenant>/<name>` (TEN-026), checked
again here for the bound tenant; none is an environment variable or a value in git. The relay
endpoint is the platform's (`SmtpRelay`).

Fail closed. A tenant with no active number (none, suspended or quarantined), a number that is not
this tenant's, a missing secret, a registry fault or a tenant with no email identity raises
ChannelUnavailable, whose text names the tenant id and the channel only. No number, reference or
secret is ever in an error or a log. A missing bound tenant is a TenancyError, never a default.
"""

from typing import Final

import httpx
from pydantic import SecretStr

from diucs.adapters.inbound.sms_webhook.routes import STATUS_PATH
from diucs.adapters.outbound.email_smtp.smtp_email import SmtpEmail, SmtpIdentity, SmtpRelay
from diucs.adapters.outbound.email_twilio.twilio_email import TwilioEmail
from diucs.adapters.outbound.sms_twilio.twilio_sms import TwilioSms
from diucs.application.ports.outbound.messaging import EmailSender, SmsSender
from diucs.application.ports.outbound.sender_resolver import ChannelUnavailable
from diucs.application.ports.outbound.tenants import (
    TenantDirectory,
    TenantLine,
    TenantRecordInvalid,
    check_secret_ref,
)
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.tenancy import current_tenant
from diucs.bootstrap.settings import Settings
from diucs.domain.errors import NotFound, ValidationFailed
from diucs.domain.model.tenant import NumberStatus
from diucs.domain.model.tenant_records import ChannelKind, ChannelProvider, TenantChannel

TEXT_CHANNEL: Final = "text"
EMAIL_CHANNEL: Final = "email"


def smtp_relay_from(settings: Settings) -> SmtpRelay:
    """The platform's SMTP relay: host, port and STARTTLS from the settings, and nothing of a
    tenant's (its address and login are its channel's, its password its secret's)."""
    return SmtpRelay(
        host=settings.smtp_host, port=settings.smtp_port, starttls=settings.smtp_starttls
    )


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
        smtp_relay: SmtpRelay | None = None,
    ) -> None:
        self._directory = directory
        self._secrets = secrets
        self._http = http
        self._status_url = status_url
        self._smtp_relay = smtp_relay

    async def sms_for(self) -> SmsSender:
        tenant = current_tenant()
        line = await self._line(tenant)
        token = self._token(tenant, line)
        return TwilioSms(self._http, line.account_sid, token, line.number, self._status_url)

    async def email_for(self, channel: TenantChannel | None) -> EmailSender:
        """The email sender of the bound tenant, from the active email channel record the caller
        read in its own unit of work. The sender's address and display name are the channel's; the
        login is the channel's address and the password is the secret its own reference names
        (`smtp/<tenant>/<name>`, own tenant only). The relay is the platform's. Anything missing,
        retired, quarantined, of another kind or another tenant's is ChannelUnavailable."""
        tenant = current_tenant()
        unavailable = ChannelUnavailable(f"no {EMAIL_CHANNEL} channel for tenant {tenant}")
        if (
            type(channel) is not TenantChannel
            or channel.kind is not ChannelKind.EMAIL
            or channel.status is not NumberStatus.ACTIVE
            or channel.from_address is None
        ):
            raise unavailable
        if channel.provider is ChannelProvider.TWILIO:
            return await self._twilio_email(tenant, channel, channel.from_address, unavailable)
        relay = self._smtp_relay
        if relay is None or relay.host is None:
            raise unavailable
        username: str | None = None
        password: SecretStr | None = None
        if channel.secret_ref is not None:
            try:
                check_secret_ref(channel.secret_ref, tenant)
            except ValidationFailed:
                raise unavailable from None
            password = SecretStr(self._secret_text(channel.secret_ref, unavailable))
            username = channel.from_address
        try:
            identity = SmtpIdentity(
                from_address=channel.from_address,
                display_name=channel.from_display_name,
                username=username,
                password=password,
            )
        except ValueError:
            raise unavailable from None
        return SmtpEmail(relay, identity)

    async def _twilio_email(
        self,
        tenant: str,
        channel: TenantChannel,
        from_address: str,
        unavailable: ChannelUnavailable,
    ) -> EmailSender:
        """Twilio email (DEC-1130): sent from the tenant's own subaccount with the same Account SID
        and Auth Token as its text line, so one set of secrets covers both and a tenant with no
        active text line has no email either. The sender address is the channel's; that the
        tenant verified it in Twilio is an onboarding step."""
        line = await self._line(tenant, EMAIL_CHANNEL)
        token = self._token(tenant, line, EMAIL_CHANNEL)
        try:
            return TwilioEmail(
                self._http, line.account_sid, token, from_address, channel.from_display_name
            )
        except ValueError:
            raise unavailable from None

    async def _line(self, tenant: str, channel: str = TEXT_CHANNEL) -> TenantLine:
        unavailable = ChannelUnavailable(f"no {channel} channel for tenant {tenant}")
        try:
            line = await self._directory.active_line(tenant)
        except TenantRecordInvalid:
            raise unavailable from None
        if line is None or line.tenant.id != tenant:
            raise unavailable
        return line

    def _token(self, tenant: str, line: TenantLine, channel: str = TEXT_CHANNEL) -> str:
        unavailable = ChannelUnavailable(f"no {channel} channel for tenant {tenant}")
        try:
            check_secret_ref(line.secret_ref, tenant)
        except ValidationFailed:
            # The directory refuses a number that names another tenant's secret; this is the same
            # rule once more at the point the secret is read.
            raise unavailable from None
        return self._secret_text(line.secret_ref, unavailable)

    def _secret_text(self, reference: str, unavailable: ChannelUnavailable) -> str:
        """The secret as text, or `unavailable` when it is not there, not text or empty. The
        reference and the value are never in the error."""
        try:
            raw = self._secrets.get(reference)
        except NotFound:
            raise unavailable from None
        try:
            value = raw.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise unavailable from None
        if not value:
            raise unavailable
        return value
