"""Outbound port: the tenant directory, secret references and the lookups that run before a tenant
is bound (TEN-007, DEC-131, DEC-134 items 9 and 14).

The directory is the platform's own record of its tenants. It is global and read-only: the only
code that runs before a scope is bound, and it returns tenant configuration and nothing else (no
person, no capacity, no message). A lookup that finds nothing, or whose key is not the shape of
the key it names, answers None and sends nothing to the database.

Secrets are references only. A `TenantLine` carries the reference of a subaccount's auth token
(`twilio/<tenant>/auth-token`), never the token; the token is read through the SecretStore when a
signature is checked (DEC-131 item 4).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from diucs.domain.model.tenant import Tenant


class TenantRecordInvalid(RuntimeError):
    """A tenant record in the registry is not one the domain accepts, or a number points at
    another tenant's secret. A configuration fault: callers fail closed. The text is fixed."""


def secret_ref(kind: str, tenant_id: str, name: str) -> str:
    raise NotImplementedError


def twilio_token_ref(tenant_id: str) -> str:
    raise NotImplementedError


def check_secret_ref(value: object, tenant_id: str) -> str:
    raise NotImplementedError


def normalise_e164(value: object) -> str | None:
    raise NotImplementedError


def normalise_account_sid(value: object) -> str | None:
    raise NotImplementedError


def normalise_host(value: object) -> str | None:
    raise NotImplementedError


def normalise_directory_id(value: object) -> str | None:
    raise NotImplementedError


@dataclass(frozen=True, slots=True)
class TenantLine:
    """An active inbound number of a tenant, the Twilio account that carries it and the reference
    of that account's auth token."""

    tenant: Tenant
    number: str
    account_sid: str
    secret_ref: str


class TenantDirectory(Protocol):
    async def get(self, tenant_id: str) -> Tenant | None: ...

    async def by_inbound_number(self, to_number: str, account_sid: str) -> TenantLine | None: ...

    async def by_account_sid(self, account_sid: str) -> TenantLine | None: ...

    async def by_host(self, host: str) -> Tenant | None: ...

    async def by_entra_directory(self, directory_id: str) -> Tenant | None: ...

    async def list_active(self) -> Sequence[Tenant]: ...

    async def active_tenant_ids(self) -> Sequence[str]: ...
