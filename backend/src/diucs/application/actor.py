"""The actor of a command: who asked, in what role, through which channel, in which tenant
(contracts.md, DEC-130 item 6).

`tenant_id` is required: an actor is built for one tenant or not at all. It is the tenant the edge
bound from a verified source (the signed token, the number called, the link, the pairing), copied
here so the use cases and the audit trail can name it. It is never an access decision: the data
layer's scope is the bound context (`application/tenancy.py`), and `require_actor_in_bound_tenant`
only checks that the two agree.
"""

from dataclasses import dataclass, field

from diucs.application.tenancy import (
    ScopeId,
    ScopeKind,
    TenantMismatch,
    TenantNotBound,
    current_tenant,
)
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.network import check_network_id
from diucs.domain.model.tenant import check_tenant_id

SYSTEM_CHANNEL = "system"


@dataclass(frozen=True, slots=True)
class Actor:
    role: Role
    practitioner_id: str | None
    device_id: str | None
    channel: str
    service_ids: frozenset[str]
    tenant_id: str
    # The networks the token named (TEN-059): a hint that routes the request and tells the page a
    # network view exists. It is never an access decision: every network request is checked against
    # the registry (`NetworkAccess.require_member`). Keyword-only, so the tenant stays the last
    # positional field.
    network_ids: frozenset[str] = field(default=frozenset(), kw_only=True)

    def __post_init__(self) -> None:
        # The domain's rule: a network id, the reserved platform id and anything that is not a plain
        # tenant id is refused, and the refusal holds no value.
        check_tenant_id(self.tenant_id)
        if type(self.network_ids) is not frozenset:
            raise ValidationFailed("network_ids", "must be a set of network ids")
        for network_id in self.network_ids:
            check_network_id(network_id, "network_ids")


def wall_actor(tenant_id: str, device_id: str | None = None) -> Actor:
    """A wall screen of one tenant (the board's own reads, a paired screen)."""
    return Actor(
        role=Role.WALL,
        practitioner_id=None,
        device_id=device_id,
        channel=SYSTEM_CHANNEL,
        service_ids=frozenset(),
        tenant_id=tenant_id,
    )


def system_actor(tenant_id: str, channel: str) -> Actor:
    """The actor of work no person started (the scheduled-work queue, the relay): the role enum has
    no system role, so it holds `owner` as the scheduler always has (DEC-193). It carries the tenant
    of the message it is processing, never a platform-wide identity."""
    return Actor(
        role=Role.OWNER,
        practitioner_id=None,
        device_id=None,
        channel=channel,
        service_ids=frozenset(),
        tenant_id=tenant_id,
    )


def anonymous_actor(tenant_id: str, channel: str) -> Actor:
    """Someone who has proved nothing yet (a text code is being asked for): no person, no device."""
    return Actor(
        role=Role.ANONYMOUS_LINK,
        practitioner_id=None,
        device_id=None,
        channel=channel,
        service_ids=frozenset(),
        tenant_id=tenant_id,
    )


def require_actor_in_bound_tenant(actor: Actor) -> None:
    """Refuse an actor of one tenant in work bound to another, or work with no tenant bound.
    Defence against a wiring fault: the check is on two values the edge set, not on any input."""
    if actor.tenant_id != current_tenant():
        raise TenantMismatch


def unit_tenant_scope(scope: ScopeId | None) -> ScopeId:
    """The tenant scope a unit of work opened under. Nothing bound, or a network scope, is a missing
    binding: a tenant use case runs for one tenant. Checked before the first read or lock, so a unit
    of another scope takes none."""
    if scope is None or scope.kind is not ScopeKind.TENANT:
        raise TenantNotBound
    return scope


def tenant_scope_of_unit(scope: ScopeId | None, actor: Actor) -> ScopeId:
    """`unit_tenant_scope`, and the actor's own: another tenant's actor is `TenantMismatch` (a
    wiring fault, never an access decision)."""
    tenant_scope = unit_tenant_scope(scope)
    if tenant_scope.value != actor.tenant_id:
        raise TenantMismatch
    return tenant_scope


def timer_actor(tenant_id: str) -> Actor:
    """The actor of a timer that the system runs on its own (U19): no person, no device, no
    service, of the one tenant the timer is running for. The role is `audit`, as the booking timers
    have always recorded it; there is no platform-wide timer actor (TEN-018)."""
    return Actor(
        role=Role.AUDIT,
        practitioner_id=None,
        device_id=None,
        channel=SYSTEM_CHANNEL,
        service_ids=frozenset(),
        tenant_id=tenant_id,
    )
