"""Token exchange: the back end issues the tenant-bound token (TEN-043, DEC-522 to DEC-527,
DEC-134 item 2, DEC-136 item 6, audit F A01 to A03).

The BFF holds no signing secret. It hands the back end what the person signed in with, and the back
end answers with a token it signed itself. Three exchanges, one rule each:

- `ExchangeStaffToken`: the tenant is the HOST's (the edge bound it). The credential is verified for
  the staff audience; the directory it was issued in must be the tenant's own VERIFIED binding (a
  member of another tenant's directory gets nothing on this host); the role is the highest one the
  tenant's role mapping gives for the groups held, never a role the token claims; the tenant must
  be one the edge would accept (active, or read-only suspended for its administrator). The token
  names the tenant and the tenant's current epoch, expires in eight hours, and the exchange writes
  one audit entry in the tenant's chain holding the role and epoch and nothing about the person.
- `ExchangeOperatorToken`: no tenant. The credential is verified for the operator audience and must
  come from the operator's own directory; the role is an app role of that directory
  (`platform-operator` or `support`); a customer's directory can never give one. The token is for
  the operator door and names no tenant.
- `ExchangeDeviceToken`: a paired wall screen presents its device token; the resolver finds the
  active screen inside the host's tenant (TEN-041); the token is a wall token for that tenant.

One refusal. Every way of not getting a staff or operator token is `ExchangeRefused` with the same
fixed message, so an answer says nothing about which directories, groups or tenants exist. A screen
that does not resolve is the resolver's `EntryRefused`, the one 404 of every pre-session entry. A
missing secret is a configuration fault (a RuntimeError), never a refusal, and an audit store that
fails gives no token.

No credential, token, directory id, object id or group reaches a log line, an error or the audit.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity_verifier import (
    Audience,
    IdentityRejected,
    IdentityVerifier,
    VerifiedIdentity,
)
from diucs.application.ports.outbound.tenants import normalise_directory_id
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantMismatch, TenantNotBound
from diucs.application.tenant_resolution import EntryKind, EntryRefused
from diucs.domain.codes import Role
from diucs.domain.errors import DomainError, NotFound
from diucs.domain.model.device import Device
from diucs.domain.model.tenant import Tenant
from diucs.domain.rules.bff_token import (
    BffClaims,
    OperatorClaims,
    encode_bff_token,
    encode_operator_token,
)
from diucs.domain.rules.token_exchange import (
    OPERATOR_TOKEN_LIFETIME,
    STAFF_TOKEN_LIFETIME,
    WALL_TOKEN_LIFETIME,
    account_ref,
    directory_is_bound,
    expiry,
    may_issue,
    operator_role,
    staff_role,
    staff_subject,
)

log = logging.getLogger(__name__)

SIGNING_SECRET: Final = "bff-jwt"
"""The platform secret that signs every back-end token. The REST edge reads the same name."""
ACCOUNT_REF_SECRET: Final = "account-ref"
"""The platform key of the derived subject and account reference of a person."""
EXCHANGE_REFUSED_MESSAGE: Final = "Your account does not have access."
MAX_CREDENTIAL_LENGTH: Final = 8192
"""An ID token is a few kilobytes; nothing longer is a credential and it is not sent on."""

USE_CASE_STAFF: Final = "ExchangeStaffToken"
ACTION_TOKEN_ISSUED: Final = "token-issued"
EXCHANGE_CHANNEL: Final = "api"


class ExchangeRefused(DomainError):
    """The one refusal of a staff or operator exchange. The message is fixed and names nothing."""

    def __init__(self) -> None:
        super().__init__(EXCHANGE_REFUSED_MESSAGE)


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_at: datetime
    role: Role
    account_ref: str | None = None
    """The opaque account reference of an operator the token was issued to (an operator exchange
    only): what the platform chain records of a sign-in. Never a name, never printed."""

    def __repr__(self) -> str:
        return f"IssuedToken(role={self.role.value!r})"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class ExchangeStaffCommand:
    tenant: Tenant
    """The tenant the request host names, read by the edge from the directory (TEN-040)."""
    credential: str


@dataclass(frozen=True, slots=True)
class ExchangeOperatorCommand:
    credential: str


@dataclass(frozen=True, slots=True)
class ExchangeDeviceCommand:
    tenant: Tenant
    token: str


class DeviceResolver(Protocol):
    async def device(self, token: str) -> Device:
        """The active wall screen of the bound tenant whose token this is, or `EntryRefused`."""
        ...


def _secret(secrets: SecretStore, name: str) -> bytes:
    """A secret the exchange needs. Missing is a configuration fault, never a refusal."""
    try:
        return secrets.get(name)
    except NotFound:
        raise RuntimeError("a secret the token exchange needs is not configured") from None


async def _verified(
    verifier: IdentityVerifier, credential: object, audience: Audience
) -> VerifiedIdentity:
    if type(credential) is not str or not 0 < len(credential) <= MAX_CREDENTIAL_LENGTH:
        raise ExchangeRefused
    try:
        return await verifier.verify(credential, audience)
    except IdentityRejected:
        log.info("token exchange refused: reason=credential audience=%s", audience.value)
        raise ExchangeRefused from None


def _refused(reason: str) -> ExchangeRefused:
    log.info("token exchange refused: reason=%s", reason)
    return ExchangeRefused()


class ExchangeStaffToken:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        verifier: IdentityVerifier,
        secrets: SecretStore,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._verifier = verifier
        self._secrets = secrets

    async def execute(self, command: ExchangeStaffCommand) -> IssuedToken:
        signing = _secret(self._secrets, SIGNING_SECRET)
        account_key = _secret(self._secrets, ACCOUNT_REF_SECRET)
        identity = await _verified(self._verifier, command.credential, Audience.STAFF)
        tenant = command.tenant
        now = self._clock.now()
        async with self._uow_factory() as uow:
            scope = uow.unit_scope
            if scope is None or scope.kind is not ScopeKind.TENANT:
                raise TenantNotBound
            if scope.value != tenant.id:
                raise TenantMismatch
            if not directory_is_bound(await uow.tenant_config.bindings(), identity.directory_id):
                raise _refused("directory")
            role = staff_role(await uow.tenant_config.role_mappings(), identity.group_ids)
            if role is None:
                raise _refused("role")
            if not may_issue(tenant, role):
                raise _refused("tenant")
            subject = staff_subject(
                account_key, tenant.id, identity.directory_id, identity.object_id
            )
            expires_at = expiry(now, STAFF_TOKEN_LIFETIME)
            token = encode_bff_token(
                BffClaims(
                    sub=subject,
                    role=role,
                    services=frozenset(),
                    expires_at=expires_at,
                    tenant=tenant.id,
                    epoch=tenant.epoch,
                ),
                signing,
            )
            await uow.audit.append(
                AuditEntry(
                    action=ACTION_TOKEN_ISSUED,
                    use_case=USE_CASE_STAFF,
                    actor=Actor(
                        role=role,
                        practitioner_id=subject,
                        device_id=None,
                        channel=EXCHANGE_CHANNEL,
                        service_ids=frozenset(),
                        tenant_id=tenant.id,
                    ),
                    entity_ids=(subject,),
                    snapshot={"role": role.value, "epoch": tenant.epoch},
                    at=now,
                )
            )
            await uow.commit()
        return IssuedToken(token=token, expires_at=expires_at, role=role)


class ExchangeOperatorToken:
    def __init__(
        self,
        clock: Clock,
        verifier: IdentityVerifier,
        secrets: SecretStore,
        operator_directory_id: str,
    ) -> None:
        """`operator_directory_id` is the Entra directory of the platform operator's own staff, from
        settings (a GUID). It is the only directory an operator role may come from."""
        directory = normalise_directory_id(operator_directory_id)
        if directory is None:
            raise ValueError("the operator directory must be a GUID")
        self._directory = directory
        self._clock = clock
        self._verifier = verifier
        self._secrets = secrets

    async def execute(self, command: ExchangeOperatorCommand) -> IssuedToken:
        signing = _secret(self._secrets, SIGNING_SECRET)
        account_key = _secret(self._secrets, ACCOUNT_REF_SECRET)
        identity = await _verified(self._verifier, command.credential, Audience.OPERATOR)
        if identity.directory_id != self._directory:
            raise _refused("operator-directory")
        role = operator_role(identity.app_roles)
        if role is None:
            raise _refused("operator-role")
        expires_at = expiry(self._clock.now(), OPERATOR_TOKEN_LIFETIME)
        reference = account_ref(account_key, identity.directory_id, identity.object_id)
        token = encode_operator_token(
            OperatorClaims(sub=reference, role=role, expires_at=expires_at), signing
        )
        return IssuedToken(token=token, expires_at=expires_at, role=role, account_ref=reference)


class ExchangeDeviceToken:
    def __init__(self, clock: Clock, resolver: DeviceResolver, secrets: SecretStore) -> None:
        self._clock = clock
        self._resolver = resolver
        self._secrets = secrets

    async def execute(self, command: ExchangeDeviceCommand) -> IssuedToken:
        signing = _secret(self._secrets, SIGNING_SECRET)
        tenant = command.tenant
        if not may_issue(tenant, Role.WALL):
            log.info("pre-session entry refused: kind=%s", EntryKind.DEVICE.value)
            raise EntryRefused
        device = await self._resolver.device(command.token)
        expires_at = expiry(self._clock.now(), WALL_TOKEN_LIFETIME)
        token = encode_bff_token(
            BffClaims(
                sub=device.id,
                role=Role.WALL,
                services=frozenset(),
                expires_at=expires_at,
                tenant=tenant.id,
                epoch=tenant.epoch,
            ),
            signing,
        )
        return IssuedToken(token=token, expires_at=expires_at, role=Role.WALL)
