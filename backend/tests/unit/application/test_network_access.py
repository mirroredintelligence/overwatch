"""Who may read a network, and what of the registry a read sees (TEN-057, DEC-546, DEC-132 item 4).

The membership claim of a token only routes (TEN-059): every network read starts here, with the
registry's own record of the viewer's tenant. A role that never sees a network is refused before
any read, so the refusal says nothing about any network; everyone else who is not an active member
of an active network gets the same NotFound, from the same single read, whether the network is
unknown, the tenant never joined, or the tenant left a minute ago.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

import pytest
from diucs.application.network_access import (
    NETWORK_NOT_FOUND,
    NETWORK_VIEW_ROLES,
    NetworkAccess,
)

from diucs.application.actor import Actor
from diucs.application.ports.outbound.network import RegisteredNetwork
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound
from diucs.domain.model.network import (
    Grant,
    GrantScope,
    Listing,
    MembershipStatus,
    NetworkMembership,
    NetworkStatus,
)
from tests.support.network_samples import (
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    OUTSIDER,
    SETTINGS,
    make_grant,
    make_listing,
    make_member,
    make_network,
)
from tests.support.projection_samples import NOW


class Registry:
    """The registry port over fixed rows, counting every read."""

    def __init__(
        self,
        memberships: Sequence[NetworkMembership] = (),
        status: NetworkStatus | None = NetworkStatus.ACTIVE,
        grants: Sequence[Grant] = (),
        listings: Sequence[Listing] = (),
    ) -> None:
        self._memberships = list(memberships)
        self._status = status
        self._grants = list(grants)
        self._listings = list(listings)
        self.calls: list[str] = []

    async def get_network(self, network_id: str) -> RegisteredNetwork | None:
        self.calls.append("get_network")
        if self._status is None or network_id != NETWORK_ID:
            return None
        return RegisteredNetwork(make_network(self._status), SETTINGS)

    async def active_membership(self, network_id: str, tenant_id: str) -> NetworkMembership | None:
        self.calls.append("active_membership")
        for row in self._memberships:
            if (
                row.network_id == network_id
                and row.member_tenant_id == tenant_id
                and row.status is MembershipStatus.ACTIVE
            ):
                return row
        return None

    async def memberships(self, network_id: str) -> Sequence[NetworkMembership]:
        self.calls.append("memberships")
        return [m for m in self._memberships if m.network_id == network_id]

    async def grants(self, network_id: str) -> Sequence[Grant]:
        self.calls.append("grants")
        return [g for g in self._grants if g.network_id == network_id]

    async def listings(self, network_id: str) -> Sequence[Listing]:
        self.calls.append("listings")
        return [x for x in self._listings if x.network_id == network_id]


class Names:
    def __init__(self, names: dict[str, str]) -> None:
        self._names = names
        self.asked: list[str] = []

    async def get(self, tenant_id: str) -> object | None:
        self.asked.append(tenant_id)
        name = self._names.get(tenant_id)
        return None if name is None else _Tenant(name)


class _Tenant:
    def __init__(self, display_name: str) -> None:
        self.display_name = display_name


def actor(tenant: str = MEMBER_B, role: Role = Role.ADVISOR) -> Actor:
    return Actor(
        role=role,
        practitioner_id="prac-1",
        device_id=None,
        channel="web",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def access(registry: Registry, names: Names | None = None) -> NetworkAccess:
    return NetworkAccess(registry, names or Names({MEMBER_B: "B Trust"}))  # type: ignore[arg-type]


def test_the_roles_that_see_a_network_are_the_staff_who_see_the_board() -> None:
    assert {Role.ADVISOR, Role.CLINICAL, Role.LEAD, Role.OWNER, Role.EXEC} == NETWORK_VIEW_ROLES


@pytest.mark.parametrize(
    "role",
    [
        Role.REPORTER,
        Role.WALL,
        Role.ANONYMOUS_LINK,
        Role.SUPPORT,
        Role.AUDIT,
        Role.TENANT_ADMIN,
        Role.NETWORK_ADMIN,
        Role.PLATFORM_OPERATOR,
    ],
)
async def test_a_role_that_never_sees_a_network_is_refused_before_any_read(role: Role) -> None:
    registry = Registry([make_member(MEMBER_B)])
    with pytest.raises(NotAllowed):
        await access(registry).require_member(actor(role=role), NETWORK_ID)
    assert registry.calls == []


@pytest.mark.parametrize("role", sorted(NETWORK_VIEW_ROLES))
async def test_an_active_member_of_an_active_network_is_let_in(role: Role) -> None:
    registry = Registry([make_member(MEMBER_B)])
    found = await access(registry).require_member(actor(role=role), NETWORK_ID)
    assert found.network.id == NETWORK_ID
    assert found.settings == SETTINGS
    assert found.membership.member_tenant_id == MEMBER_B


async def test_a_tenant_that_never_joined_and_an_unknown_network_get_the_same_answer() -> None:
    outsider_registry = Registry([make_member(MEMBER_B)])
    unknown_registry = Registry([make_member(MEMBER_B)], status=None)
    with pytest.raises(NotFound) as outsider:
        await access(outsider_registry).require_member(actor(OUTSIDER), NETWORK_ID)
    with pytest.raises(NotFound) as unknown:
        await access(unknown_registry).require_member(actor(MEMBER_B), "net-nowhere")
    assert type(outsider.value) is type(unknown.value)
    assert str(outsider.value) == str(unknown.value) == NETWORK_NOT_FOUND
    assert outsider_registry.calls == unknown_registry.calls == ["active_membership"]


@pytest.mark.parametrize("status", [MembershipStatus.LEFT, MembershipStatus.REMOVED])
async def test_a_member_who_left_is_refused_at_once(status: MembershipStatus) -> None:
    registry = Registry([make_member(MEMBER_B, status=status)])
    with pytest.raises(NotFound, match=NETWORK_NOT_FOUND):
        await access(registry).require_member(actor(), NETWORK_ID)
    assert registry.calls == ["active_membership"]


@pytest.mark.parametrize("status", [NetworkStatus.SUSPENDED, NetworkStatus.CLOSED])
async def test_a_network_that_is_not_active_reads_as_not_found(status: NetworkStatus) -> None:
    registry = Registry([make_member(MEMBER_B)], status=status)
    with pytest.raises(NotFound, match=NETWORK_NOT_FOUND):
        await access(registry).require_member(actor(), NETWORK_ID)


# what the registry shows a read


async def test_the_view_holds_the_admitted_listings_with_the_scopes_of_effective_grants() -> None:
    registry = Registry(
        [make_member(MEMBER_B), make_member(MEMBER_C)],
        grants=[
            make_grant(id="g-cap"),
            make_grant(id="g-dir", scope=GrantScope.DIRECTORY),
            make_grant(id="g-c", tenant=MEMBER_C, scope=GrantScope.CAPACITY),
            make_grant(id="g-pending", scope=GrantScope.CRITERIA, approved=False),
        ],
        listings=[make_listing(), make_listing(id="lst-c", tenant=MEMBER_C, service="svc-9")],
    )
    names = Names({MEMBER_B: "B Trust", MEMBER_C: "C Trust"})
    gate = access(registry, names)
    view = await gate.view(await gate.require_member(actor(), NETWORK_ID), NOW)

    b = view.listing_for(MEMBER_B, "svc-1")
    assert b is not None
    assert (b.row_ref, b.organisation_name) == ("lst-b-1", "B Trust")
    assert b.scopes == {GrantScope.CAPACITY, GrantScope.DIRECTORY}  # a pending grant is no scope
    c = view.listing_for(MEMBER_C, "svc-9")
    assert c is not None and c.scopes == {GrantScope.CAPACITY}
    assert view.listing_for(MEMBER_B, "svc-unlisted") is None


async def test_a_listing_that_is_not_admitted_has_no_scope_and_a_member_who_left_has_none() -> None:
    left = make_member(MEMBER_C, status=MembershipStatus.LEFT)
    registry = Registry(
        [make_member(MEMBER_B), left],
        grants=[make_grant(), make_grant(id="g-c", tenant=MEMBER_C)],
        listings=[
            make_listing(admitted=False),
            make_listing(id="lst-c", tenant=MEMBER_C, service="svc-9"),
        ],
    )
    names = Names({MEMBER_B: "B Trust", MEMBER_C: "C Trust"})
    gate = access(registry, names)
    view = await gate.view(await gate.require_member(actor(), NETWORK_ID), NOW)
    pending = view.listing_for(MEMBER_B, "svc-1")
    assert pending is not None and pending.scopes == frozenset()
    departed = view.listing_for(MEMBER_C, "svc-9")
    assert departed is not None and departed.scopes == frozenset()


async def test_a_listing_of_a_tenant_the_directory_does_not_know_is_not_in_the_view() -> None:
    registry = Registry([make_member(MEMBER_B)], grants=[make_grant()], listings=[make_listing()])
    gate = access(registry, Names({}))
    view = await gate.view(await gate.require_member(actor(), NETWORK_ID), NOW)
    assert view.listing_for(MEMBER_B, "svc-1") is None


async def test_a_grant_that_ends_before_the_read_gives_no_scope() -> None:
    ended = replace(make_grant(), effective_to=_before(NOW))
    registry = Registry([make_member(MEMBER_B)], grants=[ended], listings=[make_listing()])
    gate = access(registry)
    view = await gate.view(await gate.require_member(actor(), NETWORK_ID), NOW)
    listed = view.listing_for(MEMBER_B, "svc-1")
    assert listed is not None and listed.scopes == frozenset()


def _before(moment: datetime) -> datetime:
    from datetime import timedelta

    return moment - timedelta(hours=1)
