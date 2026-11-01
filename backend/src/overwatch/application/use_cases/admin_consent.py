"""The admin-consent invitation: invite, read, confirm (DEC-1316).

The operator names the organisation's Entra administrator; we email them the consent link and keep
the invite pending. It becomes consented only when `ConfirmAdminConsent` has seen, through Microsoft
Graph in the administrator's own directory, that our staff app is installed there and holds the
group permission. A redirect (or its `admin_consent=True`) is never proof, and the flag is not read
as one.

Tenancy: all three run in one bound tenant scope. `InviteAdminConsent` and `ReadAdminConsent` are
the platform operator's, on the tenant the operator's path names. `ConfirmAdminConsent` is public:
the route binds the tenant that the state names, and the invite is found by the hash of the whole
state inside that tenant only, so a state that names the wrong tenant finds nothing. No statement
here reads across tenants.

Stored: the state's hash, the address's keyed hash and a masked form. The address in the clear is
used for the one send, and is not stored, audited or logged.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from overwatch.application.actor import Actor, require_actor_in_bound_tenant, system_actor
from overwatch.application.admin_consent_email import render_invitation
from overwatch.application.ports.outbound.admin_consent import (
    AppInstallationCheck,
    GraphUnavailable,
)
from overwatch.application.ports.outbound.audit import AuditEntry
from overwatch.application.ports.outbound.clock import Clock
from overwatch.application.ports.outbound.ids import IdGenerator
from overwatch.application.ports.outbound.sender_resolver import ChannelUnavailable, SenderResolver
from overwatch.application.ports.outbound.tenants import TenantDirectory
from overwatch.application.ports.outbound.tokens import LINK_TOKEN_SECRET, SecretStore
from overwatch.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from overwatch.application.tenancy import ScopeKind, TenantNotBound, current_scope
from overwatch.application.use_cases.tenant_admin import check_operator
from overwatch.domain.errors import NotAllowed, NotFound
from overwatch.domain.model.tenant import NumberStatus, TenantStatus
from overwatch.domain.model.tenant_records import (
    BindingStatus,
    ChannelKind,
    EntraBinding,
)
from overwatch.domain.rules.admin_consent import (
    INVITE_VALID_FOR,
    REQUIRED_APP_ROLE,
    AdminConsentInvite,
    EffectiveStatus,
    InviteStatus,
    check_email,
    consent_url,
    effective_status,
    hash_email,
    hash_state,
    mask_email,
    new_state,
)

log = logging.getLogger(__name__)

USE_CASE_INVITE: Final = "InviteAdminConsent"
USE_CASE_CONFIRM: Final = "ConfirmAdminConsent"
AUDIT_CREATE: Final = "C"
AUDIT_UPDATE: Final = "U"

NO_TENANT: Final = "no tenant with this id"
NOT_OPEN: Final = "the tenant is not open for this change"
NO_DIRECTORY: Final = "bind the organisation's Entra directory before inviting its administrator"
NO_SENDER: Final = "no email sender is available to send the invitation"
NOT_ACCEPTED: Final = "the email provider did not accept the invitation"
NO_INVITE: Final = "no such invitation"

# What the person who opened the link is told, in words (item 5 of DEC-1316).
REASON_NOT_INSTALLED: Final = (
    "Overwatch is not installed in your directory yet. If you have just approved, please wait a "
    "minute and open the link again; if you did not approve, no access has been given."
)
REASON_DECLINED: Final = "Microsoft reported that approval was not given, so no access was given."
REASON_ROLE_MISSING: Final = (
    "Overwatch is installed in your directory but the permission to manage its groups has not "
    "been granted, so we have not marked it approved."
)
REASON_UNREACHABLE: Final = (
    "We could not reach Microsoft to check just now. Nothing has been changed; please try again "
    "in a few minutes."
)
REASON_EXPIRED: Final = (
    "This invitation has expired. Ask the person who set up Overwatch to send a new one."
)
REASON_REVOKED: Final = "This invitation was replaced by a newer one. Please use the newest email."


@dataclass(frozen=True, slots=True)
class AdminConsentLinks:
    """What the consent link is made of: our staff app and where Microsoft returns the person."""

    client_id: str
    redirect_uri: str


def _bound_tenant_id() -> str:
    scope = current_scope()
    if scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope.value


def _pick_binding(bindings: tuple[EntraBinding, ...]) -> EntraBinding | None:
    live = [b for b in bindings if b.status is not BindingStatus.REVOKED]
    verified = [b for b in live if b.status is BindingStatus.VERIFIED]
    chosen = verified or live
    return chosen[0] if chosen else None


# ---------------------------------------------------------------- views


@dataclass(frozen=True, slots=True)
class AdminConsentView:
    invite_id: str
    email_masked: str
    status: EffectiveStatus
    created_at: datetime
    expires_at: datetime
    consented_at: datetime | None
    reason: str | None


def view_of(invite: AdminConsentInvite, now: datetime) -> AdminConsentView:
    return AdminConsentView(
        invite_id=invite.invite_id,
        email_masked=invite.email_masked,
        status=effective_status(invite, now),
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        consented_at=invite.consented_at,
        reason=invite.last_reason,
    )


# ---------------------------------------------------------------- invite (operator)


@dataclass(frozen=True, slots=True)
class InviteAdminConsentCommand:
    actor: Actor
    email: str
    """The administrator's work email address. Used for the send only; never stored in the clear."""


class InviteAdminConsent:
    """Send the administrator the consent link and record the invite as pending. A second call is a
    resend: the pending invites are revoked in the same unit of work, so only the newest link can
    ever count."""

    def __init__(
        self,
        tenants: TenantDirectory,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        ids: IdGenerator,
        secrets: SecretStore,
        senders: SenderResolver,
        links: AdminConsentLinks,
    ) -> None:
        self._tenants = tenants
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._secrets = secrets
        self._senders = senders
        self._links = links

    async def execute(self, command: InviteAdminConsentCommand) -> AdminConsentView:
        operator = check_operator(command.actor)
        require_actor_in_bound_tenant(command.actor)
        tenant_id = _bound_tenant_id()
        email = check_email(command.email)
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise NotFound(NO_TENANT)
        if tenant.status not in (TenantStatus.PROVISIONING, TenantStatus.ACTIVE):
            raise NotAllowed(NOT_OPEN)
        now = self._clock.now()
        secret = self._secrets.get(LINK_TOKEN_SECRET)

        async with self._uow_factory() as uow:
            binding = _pick_binding(await uow.tenant_config.bindings())
            if binding is None:
                raise NotAllowed(NO_DIRECTORY)
            channels = [
                c
                for c in await uow.tenant_config.channels()
                if c.kind is ChannelKind.EMAIL and c.status is NumberStatus.ACTIVE
            ]
            try:
                sender = await self._senders.admin_email_for(
                    channels[0] if len(channels) == 1 else None
                )
            except ChannelUnavailable:
                raise NotAllowed(NO_SENDER) from None

            state = new_state(tenant_id)
            invite = AdminConsentInvite(
                invite_id=self._ids.new_id(),
                directory_id=binding.directory_id,
                email_hash=hash_email(email, secret),
                email_masked=mask_email(email),
                state_hash=hash_state(state),
                status=InviteStatus.PENDING,
                created_at=now,
                expires_at=now + INVITE_VALID_FOR,
            )
            revoked = await uow.admin_consents.revoke_open(now)
            await uow.admin_consents.add(invite)

            link = consent_url(
                binding.directory_id, self._links.client_id, self._links.redirect_uri, state
            )
            message = render_invitation(
                organisation=tenant.display_name, ods=tenant.ods_code or tenant.id, link=link
            )
            receipt = await sender.send(email, message.subject, message.text, None)
            if not receipt.accepted:
                raise NotAllowed(NOT_ACCEPTED)

            await uow.audit.append(
                AuditEntry(
                    action=AUDIT_CREATE,
                    use_case=USE_CASE_INVITE,
                    actor=command.actor,
                    entity_ids=(invite.invite_id,),
                    snapshot={
                        "operator": operator,
                        "expiresAt": invite.expires_at.isoformat(),
                        "replaced": revoked,
                    },
                    at=now,
                )
            )
            await uow.commit()
        return view_of(invite, now)


# ---------------------------------------------------------------- read (operator)


class ReadAdminConsent:
    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, actor: Actor) -> AdminConsentView | None:
        check_operator(actor)
        require_actor_in_bound_tenant(actor)
        _bound_tenant_id()
        async with self._uow_factory() as uow:
            invite = await uow.admin_consents.latest()
        return None if invite is None else view_of(invite, self._clock.now())


# ---------------------------------------------------------------- confirm (public)


@dataclass(frozen=True, slots=True)
class ConfirmResult:
    status: EffectiveStatus
    reason: str | None
    organisation: str | None = None


class ConfirmAdminConsent:
    """Decide what the return of the administrator means. Runs in the tenant the route bound from
    the state. The Graph check is made outside any unit of work (no transaction is held open over
    a network call)."""

    def __init__(
        self,
        tenants: TenantDirectory,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        installation: AppInstallationCheck,
    ) -> None:
        self._tenants = tenants
        self._uow_factory = uow_factory
        self._clock = clock
        self._installation = installation

    async def execute(self, state: str, *, admin_consent: bool | None) -> ConfirmResult:
        tenant_id = _bound_tenant_id()
        tenant = await self._tenants.get(tenant_id)
        if tenant is None or tenant.status not in (TenantStatus.PROVISIONING, TenantStatus.ACTIVE):
            raise NotFound(NO_INVITE)
        async with self._uow_factory() as uow:
            invite = await uow.admin_consents.by_state_hash(hash_state(state))
        if invite is None:
            raise NotFound(NO_INVITE)
        now = self._clock.now()
        status = effective_status(invite, now)
        name = tenant.display_name
        if status is EffectiveStatus.CONSENTED:
            return ConfirmResult(status, None, name)
        if status is EffectiveStatus.REVOKED:
            return ConfirmResult(status, REASON_REVOKED)
        if status is EffectiveStatus.EXPIRED:
            return ConfirmResult(status, REASON_EXPIRED)

        try:
            found = await self._installation.check(invite.directory_id)
        except GraphUnavailable:
            log.warning("admin consent could not be checked: graph unavailable")
            return ConfirmResult(EffectiveStatus.PENDING, REASON_UNREACHABLE, name)

        reason: str | None = None
        if not found.installed:
            reason = REASON_DECLINED if admin_consent is False else REASON_NOT_INSTALLED
        elif REQUIRED_APP_ROLE not in found.granted_roles:
            reason = REASON_ROLE_MISSING
        if reason is not None:
            async with self._uow_factory() as uow:
                await uow.admin_consents.set_reason(invite.invite_id, reason)
                await uow.commit()
            return ConfirmResult(EffectiveStatus.PENDING, reason, name)

        async with self._uow_factory() as uow:
            moved = await uow.admin_consents.mark_consented(invite.invite_id, now)
            if moved:
                await uow.audit.append(
                    AuditEntry(
                        action=AUDIT_UPDATE,
                        use_case=USE_CASE_CONFIRM,
                        actor=system_actor(tenant_id, "admin-consent"),
                        entity_ids=(invite.invite_id,),
                        snapshot={"consentedAt": now.isoformat()},
                        at=now,
                    )
                )
            await uow.commit()
        return ConfirmResult(EffectiveStatus.CONSENTED, None, name)
