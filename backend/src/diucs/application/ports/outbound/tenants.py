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

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import Tenant, check_tenant_id

SECRET_REF_MESSAGE: Final = "is not a valid secret reference"

# `<kind>/<tenant id>/<name>`, lower case, three parts. The tenant id is part of the reference, so
# a record can name only its own tenant's secret (check_secret_ref).
_KIND: Final = re.compile(r"[a-z][a-z0-9-]{0,31}")
_NAME: Final = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")

# A number in E.164: a plus, a country code that does not start with 0, up to 15 digits in all.
_E164: Final = re.compile(r"\+[1-9][0-9]{6,14}")
# A Twilio account SID: AC and 32 hexadecimal digits (lower case, as Twilio sends it).
_ACCOUNT_SID: Final = re.compile(r"AC[0-9a-f]{32}")
_HOST_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_HOST_MAX_LENGTH: Final = 253
_GUID: Final = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class TenantRecordInvalid(RuntimeError):
    """A tenant record in the registry is not one the domain accepts, or a number points at
    another tenant's secret. A configuration fault: callers fail closed. The text is fixed."""


def secret_ref(kind: str, tenant_id: str, name: str) -> str:
    """The reference of a tenant's secret: `<kind>/<tenant id>/<name>`. It names a secret and is
    never the secret. A tenant id, kind or name outside the patterns is refused, and the refusal
    holds no value."""
    check_tenant_id(tenant_id)
    if (
        type(kind) is not str
        or _KIND.fullmatch(kind) is None
        or type(name) is not str
        or _NAME.fullmatch(name) is None
    ):
        raise ValidationFailed("secret_ref", SECRET_REF_MESSAGE)
    return f"{kind}/{tenant_id}/{name}"


def twilio_token_ref(tenant_id: str) -> str:
    """The conventional reference of a tenant's Twilio subaccount auth token (DEC-131 item 4)."""
    return secret_ref("twilio", tenant_id, "auth-token")


def check_secret_ref(value: object, tenant_id: str) -> str:
    """The value when it is a reference of this tenant's own (`<kind>/<tenant id>/<name>`), so a
    record cannot point a number at another tenant's token. The refusal holds no value."""
    if type(value) is str:
        parts = value.split("/")
        if (
            len(parts) == 3
            and _KIND.fullmatch(parts[0]) is not None
            and parts[1] == tenant_id
            and _NAME.fullmatch(parts[2]) is not None
        ):
            return value
    raise ValidationFailed("secret_ref", SECRET_REF_MESSAGE)


def normalise_e164(value: object) -> str | None:
    """The number when it is exactly E.164, otherwise None (it is not looked up)."""
    if type(value) is str and _E164.fullmatch(value) is not None:
        return value
    return None


def normalise_account_sid(value: object) -> str | None:
    """The SID when it is exactly a Twilio account SID, otherwise None."""
    if type(value) is str and _ACCOUNT_SID.fullmatch(value) is not None:
        return value
    return None


def normalise_host(value: object) -> str | None:
    """A host name in lower case without the final dot, or None. A port, a scheme, a path, an
    underscore, a label over 63 characters or a name over 253 is not a host here (the edge removes
    the port before it asks). ASCII only, so no other character folds into a letter."""
    if type(value) is not str or not value.isascii():
        return None
    host = value.lower().removesuffix(".")
    if not 1 <= len(host) <= _HOST_MAX_LENGTH:
        return None
    if all(_HOST_LABEL.fullmatch(label) is not None for label in host.split(".")):
        return host
    return None


def normalise_directory_id(value: object) -> str | None:
    """An Entra directory id (a GUID) in lower case, or None."""
    if type(value) is not str or not value.isascii():
        return None
    guid = value.lower()
    return guid if _GUID.fullmatch(guid) is not None else None


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

    async def active_line(self, tenant_id: str) -> TenantLine | None:
        """The active number of this tenant, or None (unknown, suspended, or no active number). More
        than one active number is TenantRecordInvalid. Used by the outbound sender (I10)."""
        ...

    async def by_account_sid(self, account_sid: str) -> TenantLine | None: ...

    async def by_host(self, host: str) -> Tenant | None: ...

    async def host_of(self, tenant_id: str) -> str | None:
        """The host of this tenant's registry record in its lookup form, or None (unknown tenant,
        no host set, or a host that is not a host name). The tenant's capacity links are on it."""
        ...

    async def by_entra_directory(self, directory_id: str) -> Tenant | None: ...

    async def list_active(self) -> Sequence[Tenant]: ...

    async def active_tenant_ids(self) -> Sequence[str]: ...
