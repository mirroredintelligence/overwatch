"""The cross-tenant support guard (TEN-084, DEC-528 to DEC-533, DEC-134 item 5, DEC-136 item 6,
audit F 4.2 and A03, audit C TEN-C23).

No role holds standing access to a tenant's data. Support access to one tenant is the sum of four
things, and the absence of any is a denial:

1. a PRINCIPAL that came from the operator directory: a `PlatformPrincipal` is made only from the
   claims of an operator token (TEN-043, audience `diucs-ops`) whose role is `support`; a tenant
   token's actor, the platform operator (who has no data access) and every tenant role are none;
2. a CODE the tenant's own ADMINISTRATOR issued (`issue_code`, role `tenant-admin` in the bound
   tenant), typed to the support person: eight characters, valid four hours, held as a keyed hash in
   the tenant's cache names, opens one access and only one;
3. ONE tenant: the code is found only under the tenant the support person names (the cache names
   are tenant-scoped), and that tenant must be active;
4. an HOUR: the access (`Elevation`) lasts one hour from its opening, never longer than the code,
   and is gone with the cache (losing a key denies; nothing is allowed by a missing record).

Every opening, use and ending is written to BOTH chains: the tenant's own (so the tenant's
administrator reads what the operator did) and the platform's (`PlatformAudit`), and an access does
not stand, and a call under it is not allowed, if either cannot be written. A refusal is written to
the platform chain only (the tenant learns of an attempt only if it succeeded), with a reason word.
Every refusal the support person sees is one `CrossTenantDenied` with one fixed message, so an
answer never says whether the tenant, the code or the access was wrong.

This module is a binder: it binds the tenant the support person names, only after the principal is
checked and the tenant is known to the directory, to write the tenant's chain and read its cache
(`diucs.application.cross_tenant_guard` joins `BINDING_MODULES`). It reads no tenant data.

Not built here: the routes that call it and the use of an access by the support routes (R18 reads
the access through `authorise`), and the platform chain's graph adapter (needs a platform scope).
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from diucs.application.actor import Actor, require_actor_in_bound_tenant
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.ports.outbound.cache import Cache
from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.ids import IdGenerator
from diucs.application.ports.outbound.platform_audit import PlatformAudit, PlatformAuditEntry
from diucs.application.ports.outbound.tenants import TenantDirectory
from diucs.application.ports.outbound.tokens import SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.tenancy import (
    ScopeKind,
    TenantMismatch,
    TenantNotBound,
    bind_tenant,
    is_valid_tenant_id,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, ValidationFailed
from diucs.domain.model.network import ACCOUNT_REF_PATTERN
from diucs.domain.model.tenant import Tenant, TenantStatus
from diucs.domain.rules.bff_token import OperatorClaims
from diucs.domain.rules.support import (
    SUPPORT_ACCESS_VALID_FOR,
    SUPPORT_CODE_SECRET,
    SUPPORT_CODE_VALID_FOR,
    hash_support_code,
    normalise_support_code,
)
from diucs.domain.rules.tokens import new_support_code

log = logging.getLogger(__name__)

ACCESS_VALID_FOR: Final = SUPPORT_ACCESS_VALID_FOR
"""One hour, per access, per tenant (audit F 4.2 item 4, [ASSUMED] in O06)."""
CODE_VALID_FOR: Final = SUPPORT_CODE_VALID_FOR
"""How long an issued code can be redeemed (four hours, [ASSUMED] in O06)."""

GRANT_PREFIX: Final = "support-grant:"
ACCESS_PREFIX: Final = "support-access:"
CLAIM_PREFIX: Final = "support-claim:"
DENIED_MESSAGE: Final = "This access cannot be opened."
CODE_ATTEMPTS: Final = 5

USE_CASE_ISSUE: Final = "IssueSupportAccessCode"
USE_CASE_OPEN: Final = "OpenCrossTenantAccess"
USE_CASE_USE: Final = "UseCrossTenantAccess"
USE_CASE_END: Final = "EndCrossTenantAccess"
USE_CASE_REVOKE: Final = "RevokeCrossTenantAccess"
ACTION_CODE_ISSUED: Final = "support-access-code-issued"
ACTION_OPENED: Final = "support-access-opened"
ACTION_USED: Final = "support-access-used"
ACTION_ENDED: Final = "support-access-ended"
ACTION_REVOKED: Final = "support-access-revoked"
ACTION_REFUSED: Final = "support-access-refused"
ACTION_ABORTED: Final = "support-access-aborted"
CHANNEL: Final = "api"

_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"
_ACTION: Final = re.compile(r"[a-z][a-z0-9-]{0,39}")
_ACCESS_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_HASH: Final = re.compile(r"[0-9a-f]{64}")
_ISSUER_REF: Final = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
_VERSION: Final = 1


class CrossTenantDenied(NotAllowed):
    """Every refusal of the guard. A `NotAllowed`, so a route answers it as a record that is not
    there. The message is fixed and names no tenant, code or access."""

    def __init__(self) -> None:
        super().__init__(DENIED_MESSAGE)


class _Refusal(Exception):
    """Internal: a reason word for the platform note. Never leaves this module."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------- values


@dataclass(frozen=True, slots=True)
class PlatformPrincipal:
    """A support person of the operator's own directory. Built only for the `support` role, and
    from an operator token's claims (`from_claims`)."""

    account_ref: str
    role: Role

    def __post_init__(self) -> None:
        if (
            type(self.role) is not Role
            or self.role is not Role.SUPPORT
            or type(self.account_ref) is not str
            or ACCOUNT_REF_PATTERN.fullmatch(self.account_ref) is None
        ):
            raise CrossTenantDenied

    @classmethod
    def from_claims(cls, claims: OperatorClaims) -> PlatformPrincipal:
        if type(claims) is not OperatorClaims:
            raise CrossTenantDenied
        return cls(account_ref=claims.sub, role=claims.role)

    def __repr__(self) -> str:
        return "PlatformPrincipal()"

    __str__ = __repr__


def _aware(field: str, value: object) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise ValidationFailed(field, "must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class Grant:
    """What the cache holds for an issued code: its keyed hash, who issued it and when it lapses."""

    code_hash: str
    issued_by_ref: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if type(self.code_hash) is not str or _HASH.fullmatch(self.code_hash) is None:
            raise ValidationFailed("code_hash", "is not a hash")
        if type(self.issued_by_ref) is not str or _ISSUER_REF.fullmatch(self.issued_by_ref) is None:
            raise ValidationFailed("issued_by_ref", "is not a reference")
        issued, expires = _aware("issued_at", self.issued_at), _aware("expires_at", self.expires_at)
        if not issued < expires <= issued + CODE_VALID_FOR:
            raise ValidationFailed("expires_at", "is not within the life of a code")


@dataclass(frozen=True, slots=True)
class Elevation:
    """One access: one support person, one tenant, at most an hour."""

    access_id: str
    tenant_id: str
    principal_ref: str
    opened_at: datetime
    expires_at: datetime
    grant_hash: str

    def __post_init__(self) -> None:
        if type(self.access_id) is not str or _ACCESS_ID.fullmatch(self.access_id) is None:
            raise ValidationFailed("access_id", "is not an access id")
        if type(self.tenant_id) is not str or not is_valid_tenant_id(self.tenant_id):
            raise ValidationFailed("tenant_id", "is not a tenant id")
        if (
            type(self.principal_ref) is not str
            or ACCOUNT_REF_PATTERN.fullmatch(self.principal_ref) is None
        ):
            raise ValidationFailed("principal_ref", "is not a reference")
        if type(self.grant_hash) is not str or _HASH.fullmatch(self.grant_hash) is None:
            raise ValidationFailed("grant_hash", "is not a hash")
        opened, expires = _aware("opened_at", self.opened_at), _aware("expires_at", self.expires_at)
        if not opened < expires <= opened + ACCESS_VALID_FOR:
            raise ValidationFailed("expires_at", "is not within an hour of the opening")

    def __repr__(self) -> str:
        return (
            f"Elevation(tenant_id={self.tenant_id!r}, expires_at={self.expires_at.isoformat()!r})"
        )

    __str__ = __repr__


# ---------------------------------------------------------------------- rules


def check_issuer(actor: object) -> None:
    """Only the tenant's administrator, a person, may issue a code."""
    if (
        type(actor) is not Actor
        or actor.role is not Role.TENANT_ADMIN
        or actor.practitioner_id is None
    ):
        raise CrossTenantDenied


def check_action(action: object) -> str:
    """The short lower-case word an audit entry names a call by."""
    if type(action) is not str or _ACTION.fullmatch(action) is None:
        raise ValidationFailed("action", "must be a short lower-case word")
    return action


def access_expiry(now: datetime, grant_expires_at: datetime) -> datetime:
    """When an access that opens at `now` ends: an hour on, and never after the code lapses."""
    opened = _aware("now", now).replace(microsecond=0)
    lapses = _aware("grant_expires_at", grant_expires_at)
    return min(opened + ACCESS_VALID_FOR, lapses)


def denial(principal: object, elevation: object, tenant_id: object, now: object) -> str | None:
    """None when the access stands for this person on this tenant at `now`, else the reason word.
    Deny by default: anything that is not exactly what it should be is a denial."""
    if type(principal) is not PlatformPrincipal:
        return "no-principal"
    if type(elevation) is not Elevation:
        return "no-access"
    if elevation.tenant_id != tenant_id:
        return "other-tenant"
    if elevation.principal_ref != principal.account_ref:
        return "other-principal"
    if type(now) is not datetime or now.utcoffset() is None or now >= elevation.expires_at:
        return "expired"
    return None


# ---------------------------------------------------------------------- what the cache holds


def _text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_FORMAT)


def _moment(value: object) -> datetime:
    if type(value) is not str:
        raise ValidationFailed("time", "is not text")
    return datetime.strptime(value, _FORMAT).replace(tzinfo=UTC)


def _dump(body: dict[str, Any]) -> str:
    return json.dumps(body, separators=(",", ":"))


def _load(text: object, keys: frozenset[str]) -> dict[str, Any] | None:
    if type(text) is not str:
        return None
    try:
        body = json.loads(text)
    except ValueError, RecursionError:
        return None
    if type(body) is not dict or set(body) != keys:
        return None
    if type(body["v"]) is not int or body["v"] != _VERSION:
        return None
    return body


def encode_grant(grant: Grant) -> str:
    return _dump(
        {
            "v": _VERSION,
            "hash": grant.code_hash,
            "by": grant.issued_by_ref,
            "at": _text(grant.issued_at),
            "exp": _text(grant.expires_at),
        }
    )


def decode_grant(text: object) -> Grant | None:
    body = _load(text, frozenset({"v", "hash", "by", "at", "exp"}))
    if body is None:
        return None
    try:
        return Grant(
            code_hash=body["hash"],
            issued_by_ref=body["by"],
            issued_at=_moment(body["at"]),
            expires_at=_moment(body["exp"]),
        )
    except ValidationFailed, ValueError:
        return None


def encode_elevation(elevation: Elevation) -> str:
    return _dump(
        {
            "v": _VERSION,
            "id": elevation.access_id,
            "tenant": elevation.tenant_id,
            "principal": elevation.principal_ref,
            "opened": _text(elevation.opened_at),
            "expires": _text(elevation.expires_at),
            "grant": elevation.grant_hash,
        }
    )


def decode_elevation(text: object) -> Elevation | None:
    body = _load(text, frozenset({"v", "id", "tenant", "principal", "opened", "expires", "grant"}))
    if body is None:
        return None
    try:
        return Elevation(
            access_id=body["id"],
            tenant_id=body["tenant"],
            principal_ref=body["principal"],
            opened_at=_moment(body["opened"]),
            expires_at=_moment(body["expires"]),
            grant_hash=body["grant"],
        )
    except ValidationFailed, ValueError:
        return None


# ---------------------------------------------------------------------- the guard


@dataclass(frozen=True, slots=True)
class IssueCodeCommand:
    actor: Actor


@dataclass(frozen=True, slots=True)
class IssuedCode:
    code: str
    expires_at: datetime

    def __repr__(self) -> str:
        return f"IssuedCode(expires_at={self.expires_at.isoformat()!r})"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class OpenAccessCommand:
    principal: PlatformPrincipal
    tenant_id: str
    code: str


@dataclass(frozen=True, slots=True)
class AuthoriseCommand:
    principal: PlatformPrincipal
    tenant_id: str
    access_id: str
    action: str


@dataclass(frozen=True, slots=True)
class EndAccessCommand:
    principal: PlatformPrincipal
    tenant_id: str
    access_id: str


@dataclass(frozen=True, slots=True)
class RevokeAccessCommand:
    actor: Actor
    access_id: str


class CrossTenantGuard:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        cache: Cache,
        clock: Clock,
        ids: IdGenerator,
        secrets: SecretStore,
        tenants: TenantDirectory,
        platform_audit: PlatformAudit,
    ) -> None:
        """`secrets` is the tenant-keyed store (the support-code key is derived per tenant), and
        `cache` qualifies every name by the bound tenant: both read the tenant this guard binds."""
        self._uow_factory = uow_factory
        self._cache = cache
        self._clock = clock
        self._ids = ids
        self._secrets = secrets
        self._tenants = tenants
        self._platform = platform_audit

    # ------------------------------------------------------------ issuing, by the tenant

    async def issue_code(self, command: IssueCodeCommand) -> IssuedCode:
        """The tenant's administrator makes a code for a support person. Runs in the tenant the
        edge bound from the administrator's token; returned once, held as a hash."""
        actor = command.actor
        check_issuer(actor)
        require_actor_in_bound_tenant(actor)
        now = self._clock.now()
        secret = self._secrets.get(SUPPORT_CODE_SECRET)
        for _ in range(CODE_ATTEMPTS):
            code = new_support_code()
            code_hash = hash_support_code(code, secret)
            grant = Grant(
                code_hash=code_hash,
                issued_by_ref=str(actor.practitioner_id),
                issued_at=now,
                expires_at=now + CODE_VALID_FOR,
            )
            if await self._cache.set_if_absent(
                GRANT_PREFIX + code_hash, encode_grant(grant), CODE_VALID_FOR
            ):
                break
        else:
            raise RuntimeError("no free support code could be made")
        try:
            await self._tenant_audit(
                AuditEntry(
                    action=ACTION_CODE_ISSUED,
                    use_case=USE_CASE_ISSUE,
                    actor=actor,
                    entity_ids=(str(actor.practitioner_id),),
                    snapshot={"expires_at": grant.expires_at},
                    at=now,
                ),
                actor.tenant_id,
            )
        except BaseException:
            await self._cache.delete(GRANT_PREFIX + code_hash)
            raise
        return IssuedCode(code=code, expires_at=grant.expires_at)

    # ------------------------------------------------------------ opening, by the platform

    async def open(self, command: OpenAccessCommand) -> Elevation:
        principal = _principal(command.principal)
        tenant_id = command.tenant_id
        if type(tenant_id) is not str or not is_valid_tenant_id(tenant_id):
            raise CrossTenantDenied
        now = self._clock.now()
        try:
            return await self._open(principal, tenant_id, command.code, now)
        except _Refusal as refusal:
            await self._note_refusal(principal, tenant_id, refusal.reason, now)
            raise CrossTenantDenied from None

    async def _open(
        self, principal: PlatformPrincipal, tenant_id: str, code: object, now: datetime
    ) -> Elevation:
        tenant = await self._tenants.get(tenant_id)
        if type(tenant) is not Tenant or tenant.status is not TenantStatus.ACTIVE:
            raise _Refusal("tenant")
        canonical = normalise_support_code(code)
        if canonical is None:
            raise _Refusal("code")
        with bind_tenant(tenant_id):
            code_hash = hash_support_code(canonical, self._secrets.get(SUPPORT_CODE_SECRET))
            grant = decode_grant(await self._cache.get(GRANT_PREFIX + code_hash))
            if grant is None or now >= grant.expires_at:
                raise _Refusal("no-grant")
            elevation = Elevation(
                access_id=self._ids.new_id(),
                tenant_id=tenant_id,
                principal_ref=principal.account_ref,
                opened_at=now.astimezone(UTC).replace(microsecond=0),
                expires_at=access_expiry(now, grant.expires_at),
                grant_hash=code_hash,
            )
            # The claim is the single use: one open takes it, a second finds it taken.
            if not await self._cache.set_if_absent(
                CLAIM_PREFIX + code_hash, elevation.access_id, grant.expires_at - now
            ):
                raise _Refusal("no-grant")
            noted = False
            try:
                await self._cache.set(
                    ACCESS_PREFIX + elevation.access_id,
                    encode_elevation(elevation),
                    elevation.expires_at - now,
                )
                await self._platform.append(
                    PlatformAuditEntry(
                        action=ACTION_OPENED,
                        principal_ref=principal.account_ref,
                        tenant_id=tenant_id,
                        access_id=elevation.access_id,
                        snapshot={"expires_at": elevation.expires_at},
                        at=now,
                    )
                )
                noted = True
                await self._tenant_audit(
                    self._support_entry(
                        ACTION_OPENED,
                        USE_CASE_OPEN,
                        principal,
                        elevation,
                        now,
                        {"expires_at": elevation.expires_at},
                    ),
                    tenant_id,
                )
            except BaseException:
                await self._cache.delete(ACCESS_PREFIX + elevation.access_id)
                await self._cache.delete(CLAIM_PREFIX + code_hash)
                if noted:
                    await self._best_effort(
                        PlatformAuditEntry(
                            action=ACTION_ABORTED,
                            principal_ref=principal.account_ref,
                            tenant_id=tenant_id,
                            access_id=elevation.access_id,
                            snapshot=None,
                            at=now,
                        )
                    )
                raise
            return elevation

    # ------------------------------------------------------------ using and ending

    async def authorise(self, command: AuthoriseCommand) -> Elevation:
        """Check a call under an access and write it to both chains. Denied unless the access stands
        for this person on this tenant now; not allowed if either record cannot be written."""
        principal = _principal(command.principal)
        action = check_action(command.action)
        tenant_id = _tenant(command.tenant_id)
        now = self._clock.now()
        elevation = await self._standing(principal, tenant_id, command.access_id, now)
        await self._record(ACTION_USED, USE_CASE_USE, principal, elevation, now, {"action": action})
        return elevation

    async def end(self, command: EndAccessCommand) -> None:
        """The support person ends the access at once. The key goes first (an ending is safe to do
        before it is recorded), then both chains are written."""
        principal = _principal(command.principal)
        tenant_id = _tenant(command.tenant_id)
        now = self._clock.now()
        elevation = await self._standing(principal, tenant_id, command.access_id, now)
        with bind_tenant(tenant_id):
            await self._cache.delete(ACCESS_PREFIX + elevation.access_id)
        await self._record(ACTION_ENDED, USE_CASE_END, principal, elevation, now, None)

    async def revoke(self, command: RevokeAccessCommand) -> None:
        """The tenant's administrator ends an access to their own tenant. Runs in the tenant the
        edge bound from the administrator's token."""
        actor = command.actor
        check_issuer(actor)
        require_actor_in_bound_tenant(actor)
        access_id = _access_id(command.access_id)
        now = self._clock.now()
        elevation = decode_elevation(await self._cache.get(ACCESS_PREFIX + access_id))
        if (
            elevation is None
            or elevation.tenant_id != actor.tenant_id
            or elevation.access_id != access_id
        ):
            raise CrossTenantDenied
        await self._cache.delete(ACCESS_PREFIX + access_id)
        await self._platform.append(
            PlatformAuditEntry(
                action=ACTION_REVOKED,
                principal_ref=elevation.principal_ref,
                tenant_id=elevation.tenant_id,
                access_id=access_id,
                snapshot=None,
                at=now,
            )
        )
        await self._tenant_audit(
            AuditEntry(
                action=ACTION_REVOKED,
                use_case=USE_CASE_REVOKE,
                actor=actor,
                entity_ids=(access_id,),
                snapshot=None,
                at=now,
            ),
            actor.tenant_id,
        )

    # ------------------------------------------------------------ helpers

    async def _standing(
        self, principal: PlatformPrincipal, tenant_id: str, access_id: object, now: datetime
    ) -> Elevation:
        """The access, when it stands for this person on this tenant at `now`. Anything else is
        noted on the platform side and is the one denial."""
        try:
            identifier = _access_id(access_id)
        except CrossTenantDenied:
            await self._note_refusal(principal, tenant_id, "no-access", now)
            raise
        with bind_tenant(tenant_id):
            elevation = decode_elevation(await self._cache.get(ACCESS_PREFIX + identifier))
        reason = denial(principal, elevation, tenant_id, now)
        if reason is None and (elevation is None or elevation.access_id != identifier):
            reason = "no-access"
        if reason is not None or elevation is None:
            await self._note_refusal(principal, tenant_id, reason or "no-access", now)
            raise CrossTenantDenied
        return elevation

    def _support_entry(
        self,
        action: str,
        use_case: str,
        principal: PlatformPrincipal,
        elevation: Elevation,
        now: datetime,
        snapshot: dict[str, Any] | None,
    ) -> AuditEntry:
        return AuditEntry(
            action=action,
            use_case=use_case,
            actor=Actor(
                role=Role.SUPPORT,
                practitioner_id=principal.account_ref,
                device_id=None,
                channel=CHANNEL,
                service_ids=frozenset(),
                tenant_id=elevation.tenant_id,
            ),
            entity_ids=(elevation.access_id,),
            snapshot=snapshot,
            at=now,
        )

    async def _record(
        self,
        action: str,
        use_case: str,
        principal: PlatformPrincipal,
        elevation: Elevation,
        now: datetime,
        snapshot: dict[str, Any] | None,
    ) -> None:
        """Both chains: the platform's first, then the tenant's. Either failing is raised."""
        await self._platform.append(
            PlatformAuditEntry(
                action=action,
                principal_ref=principal.account_ref,
                tenant_id=elevation.tenant_id,
                access_id=elevation.access_id,
                snapshot=snapshot,
                at=now,
            )
        )
        with bind_tenant(elevation.tenant_id):
            await self._tenant_audit(
                self._support_entry(action, use_case, principal, elevation, now, snapshot),
                elevation.tenant_id,
            )

    async def _tenant_audit(self, entry: AuditEntry, tenant_id: str) -> None:
        """One entry in the chain of the tenant that is bound now, in a unit of work of its own."""
        async with self._uow_factory() as uow:
            scope = uow.unit_scope
            if scope is None or scope.kind is not ScopeKind.TENANT:
                raise TenantNotBound
            if scope.value != tenant_id:
                raise TenantMismatch
            await uow.audit.append(entry)
            await uow.commit()

    async def _note_refusal(
        self, principal: PlatformPrincipal, tenant_id: str, reason: str, now: datetime
    ) -> None:
        await self._best_effort(
            PlatformAuditEntry(
                action=ACTION_REFUSED,
                principal_ref=principal.account_ref,
                tenant_id=tenant_id,
                access_id=None,
                snapshot={"reason": reason},
                at=now,
            )
        )

    async def _best_effort(self, entry: PlatformAuditEntry) -> None:
        """A note whose failure must not change the answer it records."""
        try:
            await self._platform.append(entry)
        except Exception as error:
            log.error("platform audit note failed: %s", type(error).__name__)


def _principal(value: object) -> PlatformPrincipal:
    if type(value) is not PlatformPrincipal:
        raise CrossTenantDenied
    return value


def _tenant(value: object) -> str:
    if type(value) is not str or not is_valid_tenant_id(value):
        raise CrossTenantDenied
    return value


def _access_id(value: object) -> str:
    if type(value) is not str or _ACCESS_ID.fullmatch(value) is None:
        raise CrossTenantDenied
    return value
