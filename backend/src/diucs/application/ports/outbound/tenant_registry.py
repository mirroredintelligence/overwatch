"""Outbound port: the writes of the tenant registry (TEN-028, TEN-073; DEC-503).

The tenant directory (`tenants.py`) reads the platform's own record of its tenants. This port writes
it. It is the platform operator's door and nobody else's: a tenant's own code never holds it. Only
the operator use cases (`use_cases/tenant_admin.py`, `tenant_suspend.py`) take it, and the
composition root builds it.

A write that must not be lost to a concurrent one is a compare and set: `save` writes only when the
record still has the epoch and status the operator read, and answers False when it does not, so two
operators who read the same record cannot both move it. A number, a host and a directory are unique
across tenants by constraint: a second claim is a `Conflict`, never a move from one tenant to
another (a retired number stays quarantined, DEC-136 item 10).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from diucs.application.ports.outbound.tenants import (
    check_secret_ref,
    normalise_account_sid,
    normalise_e164,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import NumberStatus, Tenant, TenantStatus


@dataclass(frozen=True, slots=True)
class TenantNumberRecord:
    """A number of a tenant, as the registry holds it. The auth token is never here: only the
    reference of its entry in the secret store (DEC-131 item 4)."""

    e164: str
    account_sid: str
    secret_ref: str
    status: NumberStatus = NumberStatus.ACTIVE
    tested_at: datetime | None = None
    """When a test text was delivered from this number (the activation fact), or None."""
    quarantine_until: datetime | None = None

    def __post_init__(self) -> None:
        if normalise_e164(self.e164) is None:
            raise ValidationFailed("e164", "must be a number in E.164 form")
        if normalise_account_sid(self.account_sid) is None:
            raise ValidationFailed("account_sid", "must be a Twilio account SID")
        if type(self.secret_ref) is not str:
            raise ValidationFailed("secret_ref", "must be a secret reference")
        if type(self.status) is not NumberStatus:
            raise ValidationFailed("status", "has the wrong type")
        for name in ("tested_at", "quarantine_until"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, datetime) or value.utcoffset() is None):
                raise ValidationFailed(name, "must be a timezone-aware datetime")

    def for_tenant(self, tenant_id: str) -> TenantNumberRecord:
        """This record when its secret reference is the tenant's own, else `ValidationFailed`: a
        number cannot point at another tenant's token."""
        check_secret_ref(self.secret_ref, tenant_id)
        return self


class TenantRegistry(Protocol):
    async def create(self, tenant: Tenant) -> None:
        """Write a new tenant in `provisioning`. An id that exists is `Conflict`."""
        ...

    async def save(
        self, tenant: Tenant, *, expected_epoch: int, expected_status: TenantStatus
    ) -> bool:
        """Write the lifecycle fields of the tenant when the stored record still has this epoch
        and status. False when it has not (or there is no such tenant): nothing is written."""
        ...

    async def set_host(self, tenant_id: str, host: str) -> None:
        """The tenant's one host. An unknown tenant is `NotFound`, a host another tenant holds is
        `Conflict`."""
        ...

    async def set_entra_directory(self, tenant_id: str, directory_id: str) -> None:
        """The tenant's one Entra directory, as `set_host`."""
        ...

    async def put_number(self, tenant_id: str, number: TenantNumberRecord) -> None:
        """Record the number on the tenant. An unknown tenant is `NotFound`; a number another
        tenant holds, in any status, is `Conflict`."""
        ...

    async def mark_number_tested(self, tenant_id: str, e164: str, at: datetime) -> None:
        """Record that a test text was delivered from the tenant's number. A number the tenant does
        not hold is `NotFound`."""
        ...

    async def numbers(self, tenant_id: str) -> tuple[TenantNumberRecord, ...]:
        """The numbers of the tenant, by number."""
        ...
