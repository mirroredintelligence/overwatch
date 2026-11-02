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

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import httpx
from pydantic import SecretStr

from overwatch.adapters.inbound.sms_webhook.routes import STATUS_PATH
from overwatch.adapters.outbound.email_smtp.smtp_email import SmtpEmail, SmtpIdentity, SmtpRelay
from overwatch.adapters.outbound.email_twilio.twilio_email import TwilioEmail
from overwatch.adapters.outbound.sms_twilio.twilio_sms import TwilioSms
from overwatch.application.ports.outbound.messaging import EmailSender, SmsSender
from overwatch.application.ports.outbound.sender_resolver import ChannelUnavailable
from overwatch.application.ports.outbound.tenant_registry import TenantNumberRecord
from overwatch.application.ports.outbound.tenants import (
    TenantDirectory,
    TenantLine,
    TenantRecordInvalid,
    check_secret_ref,
    normalise_account_sid,
    normalise_e164,
)
from overwatch.application.ports.outbound.tokens import SecretStore
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.tenancy import current_tenant
from overwatch.bootstrap.settings import Settings
from overwatch.domain.errors import NotFound, ValidationFailed
from overwatch.domain.model.tenant import NumberStatus, TenantStatus, check_tenant_id
from overwatch.domain.model.tenant_records import ChannelKind, ChannelProvider, TenantChannel

PLATFORM_EMAIL_TOKEN_SECRET: Final = "twilio-auth-token"
"""The platform's own Twilio auth token, a platform secret (not a tenant's reference)."""

TEXT_CHANNEL: Final = "text"
EMAIL_CHANNEL: Final = "email"


@dataclass(frozen=True, slots=True)
class PlatformEmailIdentity:
    """The platform's own Twilio account and sender for email from the platform to a tenant's
    administrator (DEC-1316). The auth token is the secret `PLATFORM_EMAIL_TOKEN_SECRET`."""

    account_sid: str
    from_address: str
    display_name: str | None = "Overwatch"


PLATFORM_SMS_TOKEN_SECRET: Final = PLATFORM_EMAIL_TOKEN_SECRET
"""The platform's Twilio auth token: one secret for the platform email and the shared text line."""


@dataclass(frozen=True, slots=True)
class PlatformSmsIdentity:
    """The platform's own Twilio account and shared number for a tenant's outgoing texts (DEC-1319).
    The auth token is the secret `PLATFORM_SMS_TOKEN_SECRET`. This number is never a tenant's."""

    account_sid: str
    from_number: str


SharedLineCheck = Callable[[], Awaitable[bool]]
"""Does the bound tenant have an active shared text channel? Reads the tenant's own scope."""


def platform_sms_identity(settings: Settings) -> PlatformSmsIdentity | None:
    """The shared line's identity from the two settings, or None when either is missing or not the
    right shape (no shared line is offered then)."""
    account = normalise_account_sid(settings.platform_twilio_account_sid)
    number = normalise_e164(settings.platform_sms_from)
    if account is None or number is None:
        return None
    return PlatformSmsIdentity(account, number)


def demo_inbound_problem(settings: Settings) -> str | None:
    """TEMPORARY DEMO (DEC-1320): what is wrong with `OVERWATCH_DEMO_INBOUND_TENANT`, in plain
    words, or None when it is unset or good. The value is never repeated."""
    tenant = settings.demo_inbound_tenant
    if tenant is None:
        return None
    try:
        check_tenant_id(tenant)
    except ValidationFailed:
        return "OVERWATCH_DEMO_INBOUND_TENANT must be a tenant id (or be left unset)"
    if platform_sms_identity(settings) is None:
        return (
            "OVERWATCH_DEMO_INBOUND_TENANT is set but the shared line is not: set "
            "OVERWATCH_PLATFORM_TWILIO_ACCOUNT_SID and OVERWATCH_PLATFORM_SMS_FROM, or unset it"
        )
    return None


def shared_line_check(uow_factory: UnitOfWorkFactory) -> SharedLineCheck:
    """The check over the tenant's own channels, in the bound tenant's scope."""

    async def has_shared_line() -> bool:
        async with uow_factory() as uow:
            return any(
                channel.shared
                and channel.kind is ChannelKind.SMS
                and channel.status is NumberStatus.ACTIVE
                for channel in await uow.tenant_config.channels()
            )

    return has_shared_line


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
        platform_email: PlatformEmailIdentity | None = None,
        platform_sms: PlatformSmsIdentity | None = None,
        shared_line: SharedLineCheck | None = None,
        demo_tenant: str | None = None,
    ) -> None:
        self._directory = directory
        self._secrets = secrets
        self._http = http
        self._status_url = status_url
        self._smtp_relay = smtp_relay
        self._platform_email = platform_email
        self._platform_sms = platform_sms
        self._shared_line = shared_line
        self._demo_tenant = demo_tenant

    async def admin_email_for(self, channel: TenantChannel | None) -> EmailSender:
        """One rule for every platform-admin email (DEC-1316): the tenant's own email sender when
        it has a usable one, otherwise the platform's Twilio. Only this method falls back; a
        tenant's own messages use `email_for` and fail closed."""
        try:
            return await self.email_for(channel)
        except ChannelUnavailable:
            return self._platform_sender()

    def _platform_sender(self) -> EmailSender:
        unavailable = ChannelUnavailable("no platform email sender")
        identity = self._platform_email
        if identity is None:
            raise unavailable
        token = self._secret_text(PLATFORM_EMAIL_TOKEN_SECRET, unavailable)
        try:
            return TwilioEmail(
                self._http,
                identity.account_sid,
                token,
                identity.from_address,
                identity.display_name,
            )
        except ValueError:
            raise unavailable from None

    async def sms_for(self) -> SmsSender:
        """The tenant's own active number; only when it has none, and is an active tenant that chose
        the platform's shared line (outgoing only, DEC-1319), that line. A registry fault is not a
        gap to fall back from."""
        tenant = current_tenant()
        unavailable = ChannelUnavailable(f"no {TEXT_CHANNEL} channel for tenant {tenant}")
        if self._demo_tenant is not None and tenant == self._demo_tenant:
            return await self._demo_sender(tenant, unavailable)
        try:
            line = await self._directory.active_line(tenant)
        except TenantRecordInvalid:
            raise unavailable from None
        if line is None:
            return await self._shared_sender(tenant, unavailable)
        if line.tenant.id != tenant:
            raise unavailable
        token = self._token(tenant, line)
        return TwilioSms(self._http, line.account_sid, token, line.number, self._status_url)

    async def provisioning_sms_for(self, number: TenantNumberRecord | None) -> SmsSender:
        """The sender of one named line for a test text: no lookup of an active line, as the tenant
        is usually still being set up. The tenant's own number uses its own account and a token
        reference that must be the tenant's own; `None` is the platform's shared line."""
        tenant = current_tenant()
        unavailable = ChannelUnavailable(f"no {TEXT_CHANNEL} channel for tenant {tenant}")
        if number is None:
            return self._platform_sms_sender(unavailable)
        try:
            check_secret_ref(number.secret_ref, tenant)
        except ValidationFailed:
            raise unavailable from None
        token = self._secret_text(number.secret_ref, unavailable)
        return TwilioSms(self._http, number.account_sid, token, number.e164, self._status_url)

    async def _demo_sender(self, tenant: str, unavailable: ChannelUnavailable) -> SmsSender:
        """TEMPORARY DEMO (DEC-1320). A text came in on the shared line for the demo tenant, so its
        texts go out from the shared line: the person texted that number and expects the answer
        from it. It needs no shared channel and no number of its own, only a tenant that exists and
        is provisioning or active, and the platform's identity; anything else is unavailable."""
        found = await self._directory.get(tenant)
        usable = (
            found is not None
            and found.id == tenant
            and found.status in (TenantStatus.PROVISIONING, TenantStatus.ACTIVE)
        )
        if not usable:
            raise unavailable
        return self._platform_sms_sender(unavailable)

    async def _shared_sender(self, tenant: str, unavailable: ChannelUnavailable) -> SmsSender:
        if self._shared_line is None or self._platform_sms is None:
            raise unavailable
        found = await self._directory.get(tenant)
        if found is None or found.id != tenant or found.status is not TenantStatus.ACTIVE:
            raise unavailable
        if not await self._shared_line():
            raise unavailable
        return self._platform_sms_sender(unavailable)

    def _platform_sms_sender(self, unavailable: ChannelUnavailable) -> SmsSender:
        identity = self._platform_sms
        if identity is None:
            raise unavailable
        token = self._secret_text(PLATFORM_SMS_TOKEN_SECRET, unavailable)
        return TwilioSms(
            self._http, identity.account_sid, token, identity.from_number, self._status_url
        )

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
