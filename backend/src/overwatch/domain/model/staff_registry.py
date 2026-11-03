"""The staff registry: which tenants a person holds a staff role in (DEC-1327).

A `StaffRoleRecord` is one tenant's staff role for one person, written by the platform's sync from
the tenant's own role groups. It names the tenant and the role and carries the person's keyed
account reference (`account_ref`, DEC-136 item 7), never a name, address or number. Records are
registry data (no tenant property), so a sign-in can read them before a tenant is bound. A record
that is not active is one the sync found the person has lost, and it is kept as history.
"""

from dataclasses import dataclass
from typing import Final, Literal

from overwatch.domain.codes import Role
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.tenant import check_tenant_id
from overwatch.domain.rules.token_exchange import STAFF_ROLE_PRIORITY

RecordStatus = Literal["active", "ended"]
_STATUSES: Final = ("active", "ended")
# An account reference is 43 characters of base64url (token_exchange.account_ref).
_ACCOUNT_REF_LENGTH: Final = 43


def record_id(tenant_id: str, practitioner_key: str, role: Role) -> str:
    """The one id of a tenant's role for a person: a re-sync finds and updates it, never adds."""
    return f"{check_tenant_id(tenant_id)}:{practitioner_key}:{role.value}"


@dataclass(frozen=True, slots=True)
class StaffRoleRecord:
    tenant_id: str
    practitioner_key: str
    role: Role
    status: RecordStatus

    def __post_init__(self) -> None:
        check_tenant_id(self.tenant_id)
        if (
            type(self.practitioner_key) is not str
            or len(self.practitioner_key) != _ACCOUNT_REF_LENGTH
        ):
            raise ValidationFailed("practitioner_key", "must be an account reference")
        if type(self.role) is not Role or self.role not in STAFF_ROLE_PRIORITY:
            raise ValidationFailed("role", "must be a staff role")
        if self.status not in _STATUSES:
            raise ValidationFailed("status", "must be active or ended")

    @property
    def id(self) -> str:
        return record_id(self.tenant_id, self.practitioner_key, self.role)
