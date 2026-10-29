"""The actor of a command: who asked, in what role, through which channel, in which tenant
(contracts.md, DEC-130 item 6).

`tenant_id` is required: an actor is built for one tenant or not at all. It is the tenant the edge
bound from a verified source (the signed token, the number called, the link, the pairing), copied
here so the use cases and the audit trail can name it. It is never an access decision: the data
layer's scope is the bound context (`application/tenancy.py`), and `require_actor_in_bound_tenant`
only checks that the two agree.
"""

from dataclasses import dataclass

from diucs.application.tenancy import TenantMismatch, current_tenant
from diucs.domain.codes import Role
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

    def __post_init__(self) -> None:
        # The domain's rule: a network id, the reserved platform id and anything that is not a plain
        # tenant id is refused, and the refusal holds no value.
        check_tenant_id(self.tenant_id)


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
