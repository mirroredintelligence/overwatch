"""Network administration, part one: creating a network and recording its agreement (TEN-077,
DEC-132 items 2 and 3, DEC-136 items 3 and 10, DEC-541, the known gap of DEC-543 item 7).

The platform operator creates a network for an active owner organisation: the network's own audit
chain head first (the gap that a network scope had none), then the registry record, then the owner's
own membership, then the records in both scopes (the owner's chain and the network's) and the
`NetworkCreated` event. Every step is repeatable, so a creation that stopped is finished by running
it again; a different network under a taken id is a conflict. The owner's network administrator
records a new agreement version (a reference and a number, never the content), never a lower one.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.application.tenancy import ScopeId, bind_tenant
from diucs.application.use_cases.network_admin import (
    CreateNetwork,
    CreateNetworkCommand,
    GovernanceRecorder,
    RecordAgreement,
    RecordAgreementCommand,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.network import (
    Agreement,
    MembershipRole,
    MembershipStatus,
    NetworkStatus,
)
from tests.support.network_admin_fakes import (
    Heads,
    Ids,
    MemoryDirectory,
    MemoryRegistry,
    UnitFactories,
    UnitWorld,
    active_tenant,
    person,
)
from tests.support.network_samples import (
    NETWORK_ID,
    NOW,
    OWNER,
    make_network,
    make_owner_membership,
)

AT = NOW + timedelta(days=1)


class _Rig:
    def __init__(self, *, owner_active: bool = True) -> None:
        self.log: list[str] = []
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        owner = active_tenant(OWNER)
        if not owner_active:
            from diucs.domain.model.tenant import SuspendMode, SuspendReason, TenantStatus

            owner = replace(
                owner,
                status=TenantStatus.SUSPENDED,
                suspended_at=NOW,
                suspend_mode=SuspendMode.BLOCKED,
                suspend_reason=SuspendReason.OPERATOR_REQUEST,
            )
        self.directory = MemoryDirectory(owner)
        self.heads = Heads(self.log)
        factories = UnitFactories(self.world)
        self.recorder = GovernanceRecorder(
            factories.tenant,  # type: ignore[arg-type]
            factories.network,  # type: ignore[arg-type]
            Ids("ob"),
            FixedClock(AT),
        )
        self.create = CreateNetwork(
            self.registry,  # type: ignore[arg-type]
            self.directory,  # type: ignore[arg-type]
            self.heads,
            self.recorder,
            Ids("mem"),
            FixedClock(AT),
        )
        self.agreement = RecordAgreement(
            self.registry,  # type: ignore[arg-type]
            self.recorder,
            FixedClock(AT),
        )


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


@pytest.fixture(autouse=True)
def _tenant() -> Any:
    with bind_tenant(OWNER):
        yield


def _operator(tenant: str = OWNER) -> Any:
    return person(tenant, Role.PLATFORM_OPERATOR, "operator")


def _create(**over: Any) -> CreateNetworkCommand:
    fields: dict[str, Any] = dict(
        actor=_operator(),
        network_id=NETWORK_ID,
        name="Sample network",
        agreement_reference="DSA-2026-1",
        agreement_version=1,
        system_name="Sample capacity board",
        pathway_name="Sample urgent pathway",
    )
    return CreateNetworkCommand(**{**fields, **over})


# creating a network


async def test_a_network_is_made_active_with_its_agreement_and_the_owner_as_its_first_member(
    rig: _Rig,
) -> None:
    result = await rig.create.execute(_create())
    assert (result.network_id, result.created) == (NETWORK_ID, True)
    network, settings = rig.registry.networks[NETWORK_ID]
    assert network.status is NetworkStatus.ACTIVE and network.owner_tenant_id == OWNER
    assert network.agreement == Agreement("DSA-2026-1", 1)
    assert (settings.system_name, settings.time_zone) == ("Sample capacity board", "Europe/London")
    [owner] = [m for m in rig.registry.members.values()]
    assert (owner.member_tenant_id, owner.role, owner.status) == (
        OWNER,
        MembershipRole.OWNER,
        MembershipStatus.ACTIVE,
    )


async def test_the_networks_audit_chain_head_is_made_first_in_the_networks_own_scope(
    rig: _Rig,
) -> None:
    await rig.create.execute(_create())
    assert rig.heads.scopes == [ScopeId.network(NETWORK_ID)]
    assert rig.log.index(f"audit-head:{NETWORK_ID}") < rig.log.index("registry:create_network")


async def test_the_order_is_head_registry_owner_membership_then_the_records(rig: _Rig) -> None:
    await rig.create.execute(_create())
    steps = [
        e
        for e in rig.log
        if e.startswith(("registry", "audit-head", "tenant:audit", "network:audit"))
    ]
    assert steps == [
        f"audit-head:{NETWORK_ID}",
        "registry:create_network",
        "registry:create_membership",
        "tenant:audit:CreateNetwork",
        "network:audit:CreateNetwork",
    ]


async def test_both_chains_and_the_event_record_it_and_no_value_but_ids_and_codes(
    rig: _Rig,
) -> None:
    await rig.create.execute(_create())
    scopes = [scope for scope, _ in rig.world.audits]
    assert scopes == [OWNER, NETWORK_ID]
    [(_, entry), _] = rig.world.audits
    assert entry.use_case == "CreateNetwork" and entry.action == "C"
    assert entry.entity_ids == (NETWORK_ID,)
    assert entry.snapshot == {"agreement_version": 1, "owner": OWNER}
    [(scope, message)] = rig.world.outbox
    assert scope == OWNER and message.event_type == "NetworkCreated"
    assert message.payload["network_id"] == NETWORK_ID


async def test_the_agreement_reference_is_not_in_any_audit_snapshot(rig: _Rig) -> None:
    await rig.create.execute(_create())
    assert all("DSA-2026-1" not in repr(entry.snapshot) for _, entry in rig.world.audits)


async def test_running_it_again_finishes_nothing_twice(rig: _Rig) -> None:
    await rig.create.execute(_create())
    again = await rig.create.execute(_create())
    assert again.created is False
    assert len(rig.registry.members) == 1
    assert len(rig.world.audits) == 2 and len(rig.world.outbox) == 1


async def test_a_creation_that_stopped_after_the_registry_is_finished_by_running_it_again(
    rig: _Rig,
) -> None:
    rig.world.fail_commit = "tenant"
    with pytest.raises(ConnectionError):
        await rig.create.execute(_create())
    assert NETWORK_ID in rig.registry.networks and rig.world.audits == []
    rig.world.fail_commit = None
    result = await rig.create.execute(_create())
    assert result.created is False
    assert [scope for scope, _ in rig.world.audits] == [OWNER, NETWORK_ID]


async def test_a_different_network_under_a_taken_id_is_a_conflict(rig: _Rig) -> None:
    await rig.create.execute(_create())
    with pytest.raises(Conflict):
        await rig.create.execute(_create(name="Another network"))


async def test_only_the_platform_operator_creates_a_network(rig: _Rig) -> None:
    for role in (Role.NETWORK_ADMIN, Role.TENANT_ADMIN, Role.LEAD, Role.OWNER):
        with pytest.raises(NotAllowed):
            await rig.create.execute(_create(actor=person(OWNER, role)))
    assert rig.registry.networks == {} and rig.heads.scopes == []


async def test_an_operator_must_be_named(rig: _Rig) -> None:
    from dataclasses import replace as rep

    unnamed = rep(_operator(), practitioner_id=None)
    with pytest.raises(NotAllowed):
        await rig.create.execute(_create(actor=unnamed))


async def test_the_owner_must_be_an_active_organisation() -> None:
    rig = _Rig(owner_active=False)
    with pytest.raises(NotFound):
        await rig.create.execute(_create())
    assert rig.registry.networks == {} and rig.heads.scopes == []


async def test_an_actor_of_another_tenant_than_the_bound_one_is_refused(rig: _Rig) -> None:
    from diucs.application.tenancy import TenantMismatch

    with pytest.raises(TenantMismatch):
        await rig.create.execute(_create(actor=_operator("someone-else")))


@pytest.mark.parametrize(
    "over",
    [
        {"network_id": "tenant-a"},
        {"name": ""},
        {"agreement_reference": "has space"},
        {"agreement_version": 0},
        {"system_name": "Call 0300 123 4567 now"},
        {"time_zone": "America/New_York"},
    ],
)
async def test_a_bad_value_is_refused_before_anything_is_written(
    rig: _Rig, over: dict[str, Any]
) -> None:
    with pytest.raises(ValidationFailed):
        await rig.create.execute(_create(**over))
    assert rig.registry.networks == {} and rig.heads.scopes == []


# recording an agreement


def _seeded(rig: _Rig) -> None:
    rig.registry.seed(make_network(), members=[make_owner_membership()])


def _admin(tenant: str = OWNER, role: Role = Role.NETWORK_ADMIN) -> Any:
    return person(tenant, role, "admin")


async def test_a_new_agreement_version_replaces_the_current_one(rig: _Rig) -> None:
    _seeded(rig)
    await rig.agreement.execute(RecordAgreementCommand(_admin(), NETWORK_ID, "DSA-2026-2", 2))
    assert rig.registry.networks[NETWORK_ID][0].agreement == Agreement("DSA-2026-2", 2)
    [(_, message)] = rig.world.outbox
    assert message.event_type == "AgreementRecorded" and message.payload["version"] == 2
    assert [scope for scope, _ in rig.world.audits] == [OWNER, NETWORK_ID]


async def test_the_same_version_again_is_a_repeat_and_records_nothing_new(rig: _Rig) -> None:
    _seeded(rig)
    command = RecordAgreementCommand(_admin(), NETWORK_ID, "DSA-2026-2", 2)
    await rig.agreement.execute(command)
    await rig.agreement.execute(command)
    assert len(rig.world.outbox) == 1 and len(rig.world.audits) == 2


@pytest.mark.parametrize("version", [1, 0])
async def test_a_version_that_is_not_higher_is_refused(rig: _Rig, version: int) -> None:
    _seeded(rig)
    with pytest.raises((Conflict, ValidationFailed)):
        await rig.agreement.execute(RecordAgreementCommand(_admin(), NETWORK_ID, "DSA-X", version))
    assert rig.registry.networks[NETWORK_ID][0].agreement == Agreement("DSA-2026-1", 1)


async def test_only_the_owners_network_administrator_records_an_agreement(rig: _Rig) -> None:
    _seeded(rig)
    other = "other-org-x"
    for actor in (
        _admin(role=Role.TENANT_ADMIN),
        _admin(role=Role.LEAD),
        _admin(role=Role.PLATFORM_OPERATOR),
    ):
        with pytest.raises(NotAllowed):
            await rig.agreement.execute(RecordAgreementCommand(actor, NETWORK_ID, "DSA-2", 2))
    with bind_tenant(other), pytest.raises(NotFound):
        await rig.agreement.execute(RecordAgreementCommand(_admin(other), NETWORK_ID, "DSA-2", 2))
    assert rig.world.outbox == []


async def test_a_network_that_does_not_exist_is_not_found(rig: _Rig) -> None:
    with pytest.raises(NotFound):
        await rig.agreement.execute(RecordAgreementCommand(_admin(), NETWORK_ID, "DSA-2", 2))


async def test_a_lost_race_is_a_conflict_and_records_nothing(rig: _Rig) -> None:
    _seeded(rig)
    rig.registry.fail_on = set()
    network, settings = rig.registry.networks[NETWORK_ID]

    async def changed(*args: Any, **kw: Any) -> None:
        rig.registry.networks[NETWORK_ID] = (
            replace(network, status=NetworkStatus.SUSPENDED),
            settings,
        )
        raise Conflict("the registry row is not as expected, so nothing was written")

    rig.registry.save_network = changed  # type: ignore[method-assign]
    with pytest.raises(Conflict):
        await rig.agreement.execute(RecordAgreementCommand(_admin(), NETWORK_ID, "DSA-2", 2))
    assert rig.world.outbox == [] and rig.world.audits == []


# the administrator's reads


def _reads(rig: _Rig) -> Any:
    from diucs.application.use_cases.network_admin import QueryNetworkAdmin
    from tests.support.network_samples import MEMBER_B, MEMBER_C, make_member, rid

    rig.registry.seed(
        make_network(),
        members=[make_owner_membership(), make_member(MEMBER_B, id=rid("mem-opaque-b"))],
    )
    rig.directory.tenants[MEMBER_B] = active_tenant(MEMBER_B, "Member Bee")
    return (
        QueryNetworkAdmin(
            rig.registry,  # type: ignore[arg-type]
            rig.directory,  # type: ignore[arg-type]
            UnitFactories(rig.world).network_read_only,  # type: ignore[arg-type]
        ),
        MEMBER_B,
        MEMBER_C,
    )


async def test_the_owner_reads_every_membership_by_its_id_and_the_organisation_by_name(
    rig: _Rig,
) -> None:
    query, member, _ = _reads(rig)
    rows = await query.members(person(OWNER, Role.NETWORK_ADMIN), NETWORK_ID)
    assert [r.organisation_name for r in rows] == [active_tenant(OWNER).display_name, "Member Bee"]
    assert member not in repr(rows) and OWNER not in repr(rows)
    assert [r.role for r in rows] == [MembershipRole.OWNER, MembershipRole.MEMBER]


async def test_a_member_behind_on_the_agreement_is_flagged(rig: _Rig) -> None:
    query, _, _ = _reads(rig)
    network, settings = rig.registry.networks[NETWORK_ID]
    rig.registry.networks[NETWORK_ID] = (
        replace(network, agreement=Agreement("DSA-2026-2", 2)),
        settings,
    )
    rows = await query.members(person(OWNER, Role.NETWORK_ADMIN), NETWORK_ID)
    assert [r.agreement_behind for r in rows] == [True, True]


async def test_only_the_owners_network_administrator_reads_the_members(rig: _Rig) -> None:
    query, member, _ = _reads(rig)
    for role in (Role.TENANT_ADMIN, Role.LEAD, Role.OWNER):
        with pytest.raises(NotAllowed):
            await query.members(person(OWNER, role), NETWORK_ID)
        with pytest.raises(NotAllowed):
            await query.projection_status(person(OWNER, role), NETWORK_ID)
    with pytest.raises(NotFound):
        await query.members(person(member, Role.NETWORK_ADMIN), NETWORK_ID)


async def test_an_organisation_reads_the_networks_it_belongs_to_with_its_own_membership(
    rig: _Rig,
) -> None:
    query, member, other = _reads(rig)
    [view] = await query.networks(person(member, Role.TENANT_ADMIN))
    assert (view.network_id, view.is_owner, view.membership_status) == (
        NETWORK_ID,
        False,
        MembershipStatus.ACTIVE,
    )
    assert view.agreement_version == 1 and not view.agreement_behind
    assert await query.networks(person(other, Role.TENANT_ADMIN)) == []
    with pytest.raises(NotAllowed):
        await query.networks(person(member, Role.ADVISOR))


async def test_the_projection_status_shows_states_and_dates_and_never_a_row(rig: _Rig) -> None:
    from diucs.application.ports.outbound.projection import (
        ProjectionEndReason,
        SourceState,
        SourceStatus,
    )
    from diucs.domain.model.network import GrantScope

    query, member, _ = _reads(rig)
    rig.world.sources += [
        SourceState(member, GrantScope.CAPACITY, SourceStatus.ACTIVE, "g-1", None, None),
        SourceState(
            member,
            GrantScope.DIRECTORY,
            SourceStatus.ENDED,
            "g-2",
            NOW,
            ProjectionEndReason.GRANT_ENDED,
        ),
        SourceState(
            "tt-unknown-member", GrantScope.CAPACITY, SourceStatus.ACTIVE, "g-3", None, None
        ),
    ]
    [row] = await query.projection_status(person(OWNER, Role.NETWORK_ADMIN), NETWORK_ID)
    assert row.organisation_name == "Member Bee"
    assert [(k.kind.value, k.status.value) for k in row.kinds] == [
        ("capacity", "active"),
        ("directory", "ended"),
    ]
    assert member not in repr(row)
    assert rig.world.max_open == 1 and rig.world.commits == 0
