"""What the REST edge decides about a verified token and the tenant record it names (TEN-018).

The tenant is the signed claim. The record is the platform's own, read at the edge (cached for at
most a minute), so a suspend or a role-mapping change takes effect before the token's `exp`
(H-T23, DEC-094 item 4 is not enough once tenants can be suspended): the token carries the tenant's
`epoch` and is refused when the record has moved past it.

Pure: no I/O and no clock. Fail closed: a record that is not exactly a `Tenant`, a role that is not
exactly a `Role`, a method or an epoch of the wrong type, and a record for another tenant than the
claim are all refused. There is one refusal, so the edge answers every cause the same way (an
unknown tenant must not read differently from a suspended one).

[ASSUMED] (DEC-155 item 8, audit F section 2.4): a suspended tenant in `read-only` mode lets the
tenant administrator read (GET and HEAD) and nothing else; every other suspension, role and method
is refused. TEN-073 owns the suspend use case and may widen what a read-only suspension allows.
"""

from enum import StrEnum
from typing import Final

from diucs.domain.codes import Role
from diucs.domain.model.tenant import SuspendMode, Tenant, TenantStatus
from diucs.domain.rules.bff_token import EPOCH_MAX


class EdgeVerdict(StrEnum):
    ALLOWED = "allowed"
    REFUSED = "refused"
    # The token's epoch is ahead of the record: the record may be a cached copy that has not seen
    # a resume yet. The edge reads it again once and asks again; a record still behind is refused.
    RECORD_BEHIND = "record-behind"


_READ_METHODS: Final = frozenset({"GET", "HEAD"})


def edge_verdict(
    tenant: object, *, claimed_tenant: str, token_epoch: object, role: object, method: object
) -> EdgeVerdict:
    """Whether a verified token may act at the edge, given the tenant record its claim names."""
    if type(tenant) is not Tenant or type(role) is not Role or type(method) is not str:
        return EdgeVerdict.REFUSED
    if type(token_epoch) is not int or not 1 <= token_epoch <= EPOCH_MAX:
        return EdgeVerdict.REFUSED
    if tenant.id != claimed_tenant or role is Role.PLATFORM_OPERATOR:
        return EdgeVerdict.REFUSED
    if token_epoch < tenant.epoch:
        return EdgeVerdict.REFUSED
    if not _status_allows(tenant, role, method):
        return EdgeVerdict.REFUSED
    if token_epoch > tenant.epoch:
        return EdgeVerdict.RECORD_BEHIND
    return EdgeVerdict.ALLOWED


def _status_allows(tenant: Tenant, role: Role, method: str) -> bool:
    if tenant.status is TenantStatus.ACTIVE:
        return True
    if tenant.status is TenantStatus.SUSPENDED and tenant.suspend_mode is SuspendMode.READ_ONLY:
        return role is Role.TENANT_ADMIN and method in _READ_METHODS
    return False
