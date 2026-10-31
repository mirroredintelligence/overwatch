"""What a member organisation shares with each network (TEN-081, DEC-132 items 3 and 6, DEC-1263).

The tenant administrator reads, for every network its organisation is in, its own membership, the
state of what the network holds of the organisation for each kind (open or ended, with the date and
the reason), and the exact keys that may leave a tenant for each kind, from the one allowlist
(`body_keys`). Only the administrator may. The source read is the actor's own tenant and no other:
the organisation's id is the token's, never an input. A member that left is shown its dates and no
live state; an invitation not yet accepted is shown with nothing open.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from diucs.application.ports.outbound.projection import (
    ProjectionEndReason,
    SourceState,
    SourceStatus,
)
from diucs.application.projection import body_keys
from diucs.application.tenancy import bind_tenant
from diucs.application.use_cases.member_sharing import QueryMemberSharing
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed
from diucs.domain.model.network import GrantScope, MembershipEndReason, MembershipStatus
from diucs.domain.rules.projection import PROJECTION_ALLOWLIST_VERSION
from tests.support.network_admin_fakes import MemoryRegistry, UnitFactories, UnitWorld, person
from tests.support.network_samples import (
    MEMBER_B,
    MEMBER_C,
    NETWORK_ID,
    NOW,
    OTHER_NETWORK_ID,
    OWNER,
    make_member,
    make_network,
    make_owner_membership,
    rid,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

ENDED = NOW + timedelta(days=2)


def source(
    member: str,
    kind: GrantScope,
    *,
    ended: bool = False,
    reason: ProjectionEndReason | None = None,
) -> SourceState:
    return SourceState(
        source_tenant_id=member,
        kind=kind,
        status=SourceStatus.ENDED if ended else SourceStatus.ACTIVE,
        grant_id="grant-1",
        ended_at=ENDED if ended else None,
        end_reason=reason if ended else None,
    )


class _Rig:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(
            make_network(),
            members=[make_owner_membership(), make_member(MEMBER_B), make_member(MEMBER_C)],
        )
        factories = UnitFactories(self.world)
        self.query = QueryMemberSharing(self.registry, factories.network_read_only)  # type: ignore[arg-type]


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


def admin(tenant: str = MEMBER_B, role: Role = Role.TENANT_ADMIN) -> Any:
    return person(tenant, role, "admin")


async def read(rig: _Rig, actor: Any) -> Any:
    with bind_tenant(actor.tenant_id):
        return await rig.query.execute(actor)


async def test_the_allowlist_is_the_one_the_projection_enforces(rig: _Rig) -> None:
    view = await read(rig, admin())

    assert view.allowlist_version == PROJECTION_ALLOWLIST_VERSION
    assert {scope: set(fields) for scope, fields in view.allowlist.items()} == {
        kind: set(body_keys(kind)) for kind in GrantScope
    }
    # Sorted, so the screen and a test see one order.
    assert all(list(fields) == sorted(fields) for fields in view.allowlist.values())


async def test_the_allowlist_holds_nothing_about_a_person_a_message_or_a_booking(rig: _Rig) -> None:
    view = await read(rig, admin())

    named = {field for fields in view.allowlist.values() for field in fields}
    for word in ("reporter", "pin", "token", "booking", "case", "audit", "comment", "reason"):
        assert not any(word in field for field in named), word


async def test_a_member_reads_its_own_networks_and_what_each_holds_of_it(rig: _Rig) -> None:
    rig.world.sources.extend(
        [
            source(MEMBER_B, GrantScope.CAPACITY),
            source(
                MEMBER_B, GrantScope.DIRECTORY, ended=True, reason=ProjectionEndReason.GRANT_ENDED
            ),
        ]
    )

    view = await read(rig, admin(MEMBER_B))

    (network,) = view.networks
    assert (network.network_id, network.membership_status) == (NETWORK_ID, MembershipStatus.ACTIVE)
    assert network.membership_id == rid(f"mem-{MEMBER_B}")
    by_kind = {k.kind: k for k in network.kinds}
    assert set(by_kind) == {GrantScope.CAPACITY, GrantScope.DIRECTORY}
    assert by_kind[GrantScope.CAPACITY].status is SourceStatus.ACTIVE
    assert by_kind[GrantScope.DIRECTORY].status is SourceStatus.ENDED
    assert by_kind[GrantScope.DIRECTORY].ended_at == ENDED
    assert by_kind[GrantScope.DIRECTORY].end_reason is ProjectionEndReason.GRANT_ENDED


async def test_another_members_sources_are_never_read_into_the_answer(rig: _Rig) -> None:
    rig.world.sources.extend(
        [source(MEMBER_B, GrantScope.CAPACITY), source(MEMBER_C, GrantScope.CRITERIA)]
    )

    b = await read(rig, admin(MEMBER_B))
    c = await read(rig, admin(MEMBER_C))

    assert [k.kind for k in b.networks[0].kinds] == [GrantScope.CAPACITY]
    assert [k.kind for k in c.networks[0].kinds] == [GrantScope.CRITERIA]
    assert "tenant" not in repr(b).lower().replace("tenant_admin", "")


async def test_a_member_that_left_is_shown_its_dates_and_nothing_live(rig: _Rig) -> None:
    left = replace(
        make_member(MEMBER_B),
        status=MembershipStatus.LEFT,
        left_at=ENDED,
        end_reason=MembershipEndReason.LEFT,
    )
    rig.registry.members[left.id] = left
    rig.world.sources.append(source(MEMBER_B, GrantScope.CAPACITY))

    view = await read(rig, admin(MEMBER_B))

    (network,) = view.networks
    assert network.membership_status is MembershipStatus.LEFT
    assert network.left_at == ENDED
    assert network.kinds == ()  # a member that left reads nothing of the network scope


async def test_an_invitation_not_yet_accepted_shows_nothing_open(rig: _Rig) -> None:
    invited = make_member(MEMBER_B, status=MembershipStatus.INVITED)
    rig.registry.members[invited.id] = invited
    rig.world.sources.append(source(MEMBER_B, GrantScope.CAPACITY))

    view = await read(rig, admin(MEMBER_B))

    (network,) = view.networks
    assert network.membership_status is MembershipStatus.INVITED
    assert network.kinds == ()


async def test_an_organisation_in_no_network_gets_the_allowlist_and_no_networks(rig: _Rig) -> None:
    view = await read(rig, admin("tenant-nobody"))

    assert view.networks == ()
    assert set(view.allowlist) == set(GrantScope)


async def test_the_agreement_state_is_the_members_own(rig: _Rig) -> None:
    view = await read(rig, admin(MEMBER_B))

    (network,) = view.networks
    assert network.agreement_version == 1
    assert network.accepted_agreement_version == 1
    assert network.agreement_behind is False
    assert network.name == "Sample network"


async def test_each_network_is_read_in_a_read_only_unit_of_its_own_scope(rig: _Rig) -> None:
    other = make_network(id=OTHER_NETWORK_ID, owner=MEMBER_C)
    rig.registry.seed(
        other,
        members=[
            make_owner_membership(other),
            make_member(MEMBER_B, network=other, id=rid("mem-b-other")),
        ],
    )

    view = await read(rig, admin(MEMBER_B))

    assert sorted(n.network_id for n in view.networks) == sorted([NETWORK_ID, OTHER_NETWORK_ID])
    assert rig.world.opened == 2 and rig.world.max_open == 1
    assert all(entry.startswith(("network:open", "network:close")) for entry in rig.log)


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.TENANT_ADMIN])
async def test_only_the_tenant_administrator_may_read_it(rig: _Rig, role: Role) -> None:
    with pytest.raises(NotAllowed):
        await read(rig, admin(MEMBER_B, role))

    assert rig.log == []  # nothing was read, in either scope


async def test_the_owners_network_administrator_is_refused_too(rig: _Rig) -> None:
    with pytest.raises(NotAllowed):
        await read(rig, admin(OWNER, Role.NETWORK_ADMIN))
