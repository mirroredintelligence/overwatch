"""Pre-session resolution: the entries that precede a session and the one answer for refusing them
(TEN-041, DEC-520, DEC-131, DEC-134 items 3 and 9, hazard H-T24).

Five things name a tenant before any person has signed in: a link, an invitation, a wall screen's
device token, a pairing code and a text sent to a tenant's number. The tenant is never taken from
what the caller sends. A request on the web is answered for the tenant its HOST names (TEN-040, the
one binder), and the token is then looked up INSIDE that tenant, so a token of another tenant is
simply not found: host and token cannot disagree, and the answer to a token that is not the host's
own is the answer to a token nobody holds. No statement looks a token up across tenants (DEC-228
item 2), so no statement can tell a caller which tenant holds a token. A text is resolved by the
number called and the Twilio account that carried it (DEC-131 item 2).

One refusal. An unknown token, one of another purpose, one of another tenant, one that cannot be a
token, a device that is revoked or has not collected its token, a suspended tenant (the host binder
answers it as a host nobody owns) and a number that is retired, quarantined, under another account
or a suspended tenant's all give the same fixed answer, so a caller learns nothing about which
tenants, tokens or numbers exist (known issue TEN-007: the edges answer a suspended tenant as an
unknown value). A link that exists in the host's tenant but has expired or been used is a STATE for
the page that shows it (`link`), and a refusal where no state is wanted (`open_link`).

Fail closed. A missing secret is a configuration fault (a RuntimeError, a 500), never a refusal that
reads a broken deployment as "no such token". A unit of work that is not a tenant scope resolves
nothing. A directory that cannot be reached raises, so a route with no tenant never opens because
the registry was down. A token, a hash, a number or an account never reaches a log line or an
error: a refusal logs the kind of entry or a reason word and nothing else.
"""

import logging
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from diucs.application.ports.outbound.clock import Clock
from diucs.application.ports.outbound.identity import DEVICE_TOKEN_SECRET
from diucs.application.ports.outbound.tenant_lines import InboundLine
from diucs.application.ports.outbound.tenants import (
    TenantDirectory,
    TenantLine,
    TenantRecordInvalid,
    check_secret_ref,
    normalise_account_sid,
    normalise_e164,
)
from diucs.application.ports.outbound.tokens import LINK_TOKEN_SECRET, SecretStore
from diucs.application.ports.outbound.unit_of_work import UnitOfWork, UnitOfWorkFactory
from diucs.application.tenancy import ScopeKind, TenantNotBound
from diucs.application.use_cases.text_code import INVITATION_PURPOSE
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.device import Device, DeviceStatus
from diucs.domain.model.tenant import Tenant, TenantStatus
from diucs.domain.rules.tokens import LinkCheck, LinkTokenRecord, check_link, hash_token

log = logging.getLogger(__name__)

ENTRY_REFUSED_MESSAGE: Final = "this entry cannot be resolved"
MAX_TOKEN_LENGTH: Final = 64
"""A link token is 23 letters (DEC-154), or 22 characters of base64url for a link sent before
that; a device token is the same shape. Nothing longer can be one, so it is refused before it is
hashed."""


class EntryKind(StrEnum):
    LINK = "link"
    INVITATION = "invitation"
    DEVICE = "device"
    PAIRING = "pairing"
    INBOUND_NUMBER = "inbound-number"


class EntryRefused(NotFound):
    """The one refusal of every entry that precedes a session. A `NotFound`, so a route answers it
    as a resource that is not there. The message is fixed and names no kind and no value."""

    def __init__(self) -> None:
        super().__init__(ENTRY_REFUSED_MESSAGE)


def _refuse(kind: EntryKind) -> EntryRefused:
    log.info("pre-session entry refused: kind=%s", kind.value)
    return EntryRefused()


# ---------------------------------------------------------------------- the inbound number


class DirectoryInboundLines:
    """The `InboundLineDirectory` over the tenant directory (DEC-163 item 12, DEC-131 item 2).

    A line is the tenant that owns an ACTIVE number, that number's account, and the reference of
    that account's auth token. The number and the account must be the shape they are looked up by
    and must match together; anything else, and anything the directory holds for a tenant that is
    not active, is None. A record the directory refuses is None too, logged as a reason word."""

    def __init__(self, directory: TenantDirectory) -> None:
        self._directory = directory

    async def for_number(self, to_number: str, account_sid: str) -> InboundLine | None:
        number = normalise_e164(to_number)
        account = normalise_account_sid(account_sid)
        if number is None or account is None:
            return None
        try:
            line = await self._directory.by_inbound_number(number, account)
        except TenantRecordInvalid:
            log.warning("inbound line refused: reason=tenant-record")
            return None
        return _line_of(line)

    async def for_account(self, account_sid: str) -> InboundLine | None:
        account = normalise_account_sid(account_sid)
        if account is None:
            return None
        try:
            line = await self._directory.by_account_sid(account)
        except TenantRecordInvalid:
            log.warning("inbound line refused: reason=tenant-record")
            return None
        return _line_of(line)


def _line_of(line: object) -> InboundLine | None:
    """The line a directory answer makes, or None. Nothing the directory returns is trusted
    further than its shape: the tenant must be exactly an active `Tenant`, and the secret reference
    must be that tenant's own."""
    if type(line) is not TenantLine:
        return None
    tenant = line.tenant
    if type(tenant) is not Tenant or tenant.status is not TenantStatus.ACTIVE:
        return None
    try:
        reference = check_secret_ref(line.secret_ref, tenant.id)
    except ValidationFailed:
        log.warning("inbound line refused: reason=secret-reference")
        return None
    return InboundLine(tenant_id=tenant.id, token_secret=reference)


# ---------------------------------------------------------------------- tokens in the host's tenant


@dataclass(frozen=True, slots=True)
class ResolvedLink:
    """A link found in the bound tenant, and what `check_link` says of it at the clock's now."""

    record: LinkTokenRecord
    state: LinkCheck


def _tenant_scope(uow: UnitOfWork) -> None:
    """The unit must be one tenant's. A network scope, or none, resolves nothing."""
    scope = uow.unit_scope
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound


class PreSessionResolver:
    """Resolves a token inside the tenant the edge has bound (the host's, TEN-040). Each call opens
    one read-only unit of work and never commits. `secrets` is the process's tenant-keyed store, so
    a hash is made with the bound tenant's own key (TEN-023)."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, secrets: SecretStore) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._secrets = secrets

    def _hash(self, token: object, secret_name: str) -> str | None:
        """The keyed hash of a token, or None for text that cannot be one."""
        if type(token) is not str or not 0 < len(token) <= MAX_TOKEN_LENGTH:
            return None
        try:
            secret = self._secrets.get(secret_name)
        except NotFound:
            raise RuntimeError(
                "a secret the pre-session resolver needs is not configured"
            ) from None
        try:
            return hash_token(token, secret)
        except ValidationFailed as error:
            if error.field == "token":
                return None
            raise

    async def link(self, token: str, purposes: Collection[str]) -> ResolvedLink:
        """The link in the bound tenant, whatever its state. An unknown token, a token that cannot
        be one, another tenant's and one of a purpose not asked for are `EntryRefused`."""
        token_hash = self._hash(token, LINK_TOKEN_SECRET)
        if token_hash is None:
            raise _refuse(EntryKind.LINK)
        async with self._uow_factory() as uow:
            _tenant_scope(uow)
            record = await uow.link_tokens.get_by_hash(token_hash)
        if record is None or record.purpose not in purposes:
            raise _refuse(EntryKind.LINK)
        return ResolvedLink(record=record, state=check_link(record, self._clock.now()))

    async def open_link(self, token: str, purposes: Collection[str]) -> ResolvedLink:
        """The link, when it is open. An expired or used one is `EntryRefused` as well."""
        found = await self.link(token, purposes)
        if found.state is not LinkCheck.OK:
            raise _refuse(EntryKind.LINK)
        return found

    async def invitation(self, token: str) -> ResolvedLink:
        """An invitation is a link of the invitation purpose; its state is the page's to show."""
        token_hash = self._hash(token, LINK_TOKEN_SECRET)
        if token_hash is None:
            raise _refuse(EntryKind.INVITATION)
        try:
            return await self.link(token, {INVITATION_PURPOSE})
        except EntryRefused:
            raise _refuse(EntryKind.INVITATION) from None

    async def device(self, token: str) -> Device:
        """The ACTIVE wall screen of the bound tenant whose token this is. A screen that is not
        active is refused even if the store returned it (the port promises active ones only)."""
        token_hash = self._hash(token, DEVICE_TOKEN_SECRET)
        if token_hash is None:
            raise _refuse(EntryKind.DEVICE)
        async with self._uow_factory() as uow:
            _tenant_scope(uow)
            try:
                found = await uow.devices.find_by_token_hash(token_hash)
            except Conflict:
                log.error("device token refused: reason=ambiguous")
                found = None
        if found is None or found.status is not DeviceStatus.ACTIVE:
            raise _refuse(EntryKind.DEVICE)
        return found
