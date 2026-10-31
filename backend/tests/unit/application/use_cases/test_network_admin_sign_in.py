"""How the owner's network administrators are named (TEN-080, DEC-1260).

The network owner is a tenant. Its network administrators sign in through its own directory, like
its other staff: a group of that directory is mapped to `network-admin`. Two ways to make the
mapping: the owner's tenant administrator through the ordinary role-mapping route (the record now
allows the role), and the platform operator's `MapNetworkAdminGroup`, which is how the first one is
made (the tenant administrator cannot sign in yet, KI-532). Both give the role to nobody until the
tenant owns an ACTIVE network (`owns_active_network`): the registry is asked, never the token.
"""

from dataclasses import replace
from datetime import timedelta
from types import TracebackType
from typing import Any, Self

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.ports.outbound.audit import AuditEntry
from diucs.application.tenancy import ScopeId, bind_tenant, current_scope_or_none
from diucs.application.use_cases.network_admin import (
    MapNetworkAdminGroup,
    MapNetworkAdminGroupCommand,
    RegistryNetworkOwnership,
    owns_active_network,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.network import MembershipStatus, NetworkStatus
from diucs.domain.model.tenant_records import MappingStatus, RoleMapping
from tests.support.network_admin_fakes import MemoryRegistry, person
from tests.support.network_samples import (
    MEMBER_B,
    NETWORK_ID,
    NOW,
    OWNER,
    SETTINGS,
    make_member,
    make_network,
    make_owner_membership,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

GROUP = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
OTHER_GROUP = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


# ----------------------------------------------------------------------- who owns a network


def registry_with_owner() -> MemoryRegistry:
    registry = MemoryRegistry()
    network = make_network()
    registry.networks[network.id] = (network, SETTINGS)
    owner = make_owner_membership()
    registry.members[owner.id] = owner
    return registry


async def test_the_tenant_that_owns_an_active_network_owns_one() -> None:
    assert await owns_active_network(registry_with_owner(), OWNER) is True


async def test_a_member_is_not_an_owner() -> None:
    registry = registry_with_owner()
    member = make_member(MEMBER_B)
    registry.members[member.id] = member

    assert await owns_active_network(registry, MEMBER_B) is False


async def test_a_tenant_in_no_network_owns_none() -> None:
    assert await owns_active_network(MemoryRegistry(), OWNER) is False
    assert await owns_active_network(registry_with_owner(), "tenant-nobody") is False


@pytest.mark.parametrize("status", [NetworkStatus.SUSPENDED, NetworkStatus.CLOSED])
async def test_an_owner_of_a_suspended_or_closed_network_owns_no_active_one(
    status: NetworkStatus,
) -> None:
    registry = registry_with_owner()
    network, settings = registry.networks[NETWORK_ID]
    registry.networks[NETWORK_ID] = (replace(network, status=status), settings)

    assert await owns_active_network(registry, OWNER) is False


async def test_an_owner_whose_own_membership_has_ended_owns_none() -> None:
    registry = registry_with_owner()
    (owner,) = registry.members.values()
    registry.members[owner.id] = replace(owner, status=MembershipStatus.REMOVED)

    assert await owns_active_network(registry, OWNER) is False


async def test_owning_is_by_the_registry_owner_field_not_by_a_membership_row_alone() -> None:
    # A row that says `owner` in a network another tenant owns (a damaged registry) is not ownership.
    registry = registry_with_owner()
    network, settings = registry.networks[NETWORK_ID]
    registry.networks[NETWORK_ID] = (replace(network, owner_tenant_id=MEMBER_B), settings)

    assert await owns_active_network(registry, OWNER) is False


async def test_the_exchange_port_answers_from_the_registry() -> None:
    ownership = RegistryNetworkOwnership(registry_with_owner())  # type: ignore[arg-type]

    assert await ownership.owns_active_network(OWNER) is True
    assert await ownership.owns_active_network(MEMBER_B) is False


# ----------------------------------------------------------------------- the operator's mapping


class _Config:
    def __init__(self, mappings: list[RoleMapping]) -> None:
        self.mappings = mappings

    async def put_role_mapping(self, mapping: RoleMapping) -> None:
        self.mappings = [m for m in self.mappings if m.group_object_id != mapping.group_object_id]
        self.mappings.append(mapping)

    async def role_mappings(self) -> tuple[RoleMapping, ...]:
        return tuple(self.mappings)


class _Audit:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def append(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


class _Unit:
    def __init__(self, world: "_World") -> None:
        self._world = world
        self.tenant_config = world.configs[
            (current_scope_or_none() or ScopeId.tenant("none-x")).value
        ]
        self.audit = world.audit

    @property
    def unit_scope(self) -> ScopeId | None:
        return current_scope_or_none()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self._world.commits += 1


class _World:
    def __init__(self) -> None:
        self.configs: dict[str, _Config] = {OWNER: _Config([]), MEMBER_B: _Config([])}
        self.audit = _Audit()
        self.commits = 0

    def factory(self) -> _Unit:
        return _Unit(self)


def make(world: _World, registry: MemoryRegistry | None = None) -> MapNetworkAdminGroup:
    return MapNetworkAdminGroup(
        registry or registry_with_owner(),  # type: ignore[arg-type]
        world.factory,  # type: ignore[arg-type]
        FixedClock(NOW + timedelta(days=1)),
    )


def operator(tenant: str = OWNER) -> Any:
    return person(tenant, Role.PLATFORM_OPERATOR, "operator")


async def run(use_case: MapNetworkAdminGroup, **over: Any) -> Any:
    fields: dict[str, Any] = {"actor": operator(), "group_object_id": GROUP}
    fields.update(over)
    with bind_tenant(over.get("tenant", OWNER)):
        return await use_case.execute(MapNetworkAdminGroupCommand(**{
            k: v for k, v in fields.items() if k != "tenant"
        }))


async def test_the_operator_maps_a_group_of_the_owners_directory_to_the_role() -> None:
    world = _World()

    result = await run(make(world))

    assert result.created is True
    (mapping,) = world.configs[OWNER].mappings
    assert (mapping.group_object_id, mapping.role, mapping.status) == (
        GROUP,
        Role.NETWORK_ADMIN,
        MappingStatus.ACTIVE,
    )
    assert world.commits == 1


async def test_it_is_repeatable_and_a_repeat_changes_nothing() -> None:
    world = _World()
    use_case = make(world)
    await run(use_case)

    again = await run(use_case)

    assert again.created is False
    assert len(world.configs[OWNER].mappings) == 1


async def test_it_writes_one_audit_entry_with_the_role_and_never_the_group() -> None:
    world = _World()

    await run(make(world))

    (entry,) = world.audit.entries
    assert (entry.use_case, entry.actor.role, entry.actor.tenant_id) == (
        "MapNetworkAdminGroup",
        Role.PLATFORM_OPERATOR,
        OWNER,
    )
    assert entry.snapshot == {"role": "network-admin", "status": "active"}
    assert GROUP not in repr(entry)


async def test_a_tenant_that_owns_no_network_is_not_found() -> None:
    world = _World()

    with pytest.raises(NotFound):
        await run(make(world, MemoryRegistry()))

    assert world.configs[OWNER].mappings == []
    assert world.commits == 0


async def test_a_member_of_a_network_is_not_found_either() -> None:
    world = _World()
    registry = registry_with_owner()
    member = make_member(MEMBER_B)
    registry.members[member.id] = member

    with pytest.raises(NotFound):
        await run(make(world, registry), actor=operator(MEMBER_B), tenant=MEMBER_B)

    assert world.configs[MEMBER_B].mappings == []


@pytest.mark.parametrize(
    "role",
    [Role.TENANT_ADMIN, Role.NETWORK_ADMIN, Role.LEAD, Role.SUPPORT, Role.ADVISOR, Role.WALL],
)
async def test_only_the_platform_operator_may(role: Role) -> None:
    world = _World()

    with pytest.raises(NotAllowed):
        await run(make(world), actor=person(OWNER, role, "someone"))

    assert world.configs[OWNER].mappings == []


async def test_the_actor_must_be_of_the_bound_tenant() -> None:
    world = _World()

    with pytest.raises(Exception) as caught:
        await run(make(world), actor=operator(MEMBER_B))

    assert type(caught.value).__name__ == "TenantMismatch"
    assert world.configs[OWNER].mappings == []


@pytest.mark.parametrize("group", ["", "not-a-guid", None, 7, GROUP + "0"])
async def test_a_group_that_is_not_a_directory_id_is_refused(group: Any) -> None:
    world = _World()

    with pytest.raises(ValidationFailed):
        await run(make(world), group_object_id=group)

    assert world.configs[OWNER].mappings == []


async def test_a_group_that_already_gives_another_role_is_a_conflict_not_an_overwrite() -> None:
    world = _World()
    world.configs[OWNER].mappings.append(RoleMapping(GROUP, Role.LEAD, MappingStatus.ACTIVE))

    with pytest.raises(Conflict):
        await run(make(world))

    assert world.configs[OWNER].mappings == [RoleMapping(GROUP, Role.LEAD, MappingStatus.ACTIVE)]


async def test_another_group_is_left_alone() -> None:
    world = _World()
    world.configs[OWNER].mappings.append(
        RoleMapping(OTHER_GROUP, Role.LEAD, MappingStatus.ACTIVE)
    )

    await run(make(world))

    assert {m.group_object_id for m in world.configs[OWNER].mappings} == {GROUP, OTHER_GROUP}


async def test_a_retired_mapping_of_the_group_is_made_active_again() -> None:
    world = _World()
    world.configs[OWNER].mappings.append(
        RoleMapping(GROUP, Role.NETWORK_ADMIN, MappingStatus.RETIRED)
    )

    result = await run(make(world))

    assert result.created is True
    (mapping,) = world.configs[OWNER].mappings
    assert mapping.status is MappingStatus.ACTIVE
