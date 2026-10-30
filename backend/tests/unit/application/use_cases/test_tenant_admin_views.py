"""What a tenant's administrator reads of their own tenant (TEN-075).

The role first, then the tenant: each read is of the tenant the unit of work is bound to, so two
tenants with different records show only their own. The diff of a configuration version is judged
against the version in force below it, the operator access log keeps only the platform's own
people, and nothing here carries a secret. No Neo4j: a recording unit of work per tenant.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Self

import pytest

from diucs.application.actor import Actor
from diucs.application.ports.outbound.audit import AuditEntry, AuditRecord
from diucs.application.tenancy import TenantNotBound, current_scope_or_none
from diucs.application.use_cases.tenant_admin_views import (
    ACCESS_LOG_LIMIT,
    ReadTenantAdmin,
)
from diucs.domain.codes import Role
from diucs.domain.errors import NotAllowed, NotFound, ValidationFailed
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    TenantConfig,
    TenantContact,
)
from diucs.domain.model.tenant_records import (
    BindingStatus,
    ChannelKind,
    ChannelProvider,
    EntraBinding,
    MappingStatus,
    RoleMapping,
    TenantChannel,
    default_retention,
)
from tests.support.provisioning_fakes import NOW, FakePlatform, FixedNow, provisioning_tenant
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

A, B = "alpha-org", "bravo-org"
GROUP = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
DIRECTORY = "0f5a7c1e-3b2d-4c6a-9e8f-1a2b3c4d5e6f"


def _admin(tenant: str = A, role: Role = Role.TENANT_ADMIN, ref: str | None = "admin-1") -> Actor:
    return Actor(
        role=role,
        practitioner_id=ref,
        device_id=None,
        channel="api",
        service_ids=frozenset(),
        tenant_id=tenant,
    )


def _version(number: int, status: ConfigStatus, values: dict[str, Any], **fields: Any) -> Any:
    base: dict[str, Any] = {
        "version": number,
        "status": status,
        "values": values,
        "created_at": NOW,
        "created_by_ref": "person-a",
    }
    if status is ConfigStatus.CURRENT:
        base["effective_from"] = NOW
    return TenantConfig(**{**base, **fields})


@dataclass
class Data:
    versions: list[TenantConfig] = field(default_factory=list)
    contacts: tuple[Any, ...] = ()
    channels: tuple[Any, ...] = ()
    retention: tuple[Any, ...] = ()
    bindings: tuple[Any, ...] = ()
    mappings: tuple[Any, ...] = ()
    audit: list[AuditRecord] = field(default_factory=list)


class _Config:
    def __init__(self, data: Data) -> None:
        self._data = data

    async def current_version(self) -> TenantConfig | None:
        return next((v for v in self._data.versions if v.status is ConfigStatus.CURRENT), None)

    async def latest_version_number(self) -> int:
        return max((v.version for v in self._data.versions), default=0)

    async def get_version(self, number: int) -> TenantConfig | None:
        return next((v for v in self._data.versions if v.version == number), None)

    async def contacts(self) -> tuple[Any, ...]:
        return self._data.contacts

    async def channels(self) -> tuple[Any, ...]:
        return self._data.channels

    async def retention(self) -> tuple[Any, ...]:
        return self._data.retention

    async def bindings(self) -> tuple[Any, ...]:
        return self._data.bindings

    async def role_mappings(self) -> tuple[Any, ...]:
        return self._data.mappings


class _Audit:
    def __init__(self, data: Data) -> None:
        self._data = data
        self.asked: list[tuple[datetime, datetime, frozenset[str]]] = []

    async def records_between(
        self, start: datetime, end: datetime, use_cases: frozenset[str]
    ) -> list[AuditRecord]:
        self.asked.append((start, end, use_cases))
        return [
            r
            for r in self._data.audit
            if start <= r.entry.at <= end and r.entry.use_case in use_cases
        ]


class _Unit:
    def __init__(self, world: World) -> None:
        self._scope = current_scope_or_none()
        data = world.data.get(self._scope.value if self._scope else "", Data())
        self.tenant_config = _Config(data)
        self.audit = _Audit(data)
        world.audits.append(self.audit)

    @property
    def unit_scope(self) -> Any:
        return self._scope

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@dataclass
class World:
    data: dict[str, Data] = field(default_factory=dict)
    audits: list[_Audit] = field(default_factory=list)

    def factory(self) -> _Unit:
        return _Unit(self)


def _record(use_case: str, role: Role, minutes: int, tenant: str = A, action: str = "x") -> Any:
    actor = _admin(tenant, role, "ref-" + role.value)
    entry = AuditEntry(
        action=action,
        use_case=use_case,
        actor=actor,
        entity_ids=(f"entity-{minutes}",),
        snapshot={"n": minutes},
        at=NOW - timedelta(minutes=minutes),
    )
    return AuditRecord(id=f"r-{minutes}", entry=entry, chain_hash="h" * 64, previous_hash="p" * 64)


def _read(world: World, *tenants: str) -> ReadTenantAdmin:
    platform = FakePlatform(*(provisioning_tenant(t) for t in (tenants or (A,))))
    platform.hosts.update({t: f"{t}.example.org" for t in (tenants or (A,))})
    return ReadTenantAdmin(world.factory, platform, FixedNow())  # type: ignore[arg-type]


# ---------------------------------------------------------------- the role


@pytest.mark.parametrize("role", [r for r in Role if r is not Role.TENANT_ADMIN])
async def test_only_the_tenants_administrator_reads(role: Role) -> None:
    world = World({A: Data()})
    read = _read(world)

    with as_tenant(A):
        for call in (read.overview, read.versions, read.access_log):
            with pytest.raises(NotAllowed):
                await call(_admin(role=role))
        with pytest.raises(NotAllowed):
            await read.version(_admin(role=role), 1)

    assert world.audits == []


async def test_an_administrator_with_no_name_is_refused() -> None:
    read = _read(World({A: Data()}))

    with as_tenant(A), pytest.raises(NotAllowed):
        await read.overview(_admin(ref=None))


async def test_a_read_with_no_tenant_bound_is_refused() -> None:
    read = _read(World({A: Data()}))

    with pytest.raises(TenantNotBound):
        await read.overview(_admin())


# ---------------------------------------------------------------- the overview


async def test_the_overview_is_the_record_the_host_and_everything_configured() -> None:
    data = Data(
        versions=[_version(1, ConfigStatus.CURRENT, {"systemName": "Alpha view"})],
        contacts=(TenantContact(ContactKind.COORDINATION_PHONE, "Coordination", "01234 567890"),),
        channels=(
            TenantChannel(
                id="sms-1",
                kind=ChannelKind.SMS,
                provider=ChannelProvider.TWILIO,
                status=NumberStatus.ACTIVE,
                sender_label="Alpha",
                account_sid="AC" + "b" * 32,
                secret_ref=f"twilio/{A}/auth-token",
            ),
        ),
        retention=default_retention(),
        bindings=(EntraBinding(DIRECTORY, BindingStatus.PENDING),),
        mappings=(RoleMapping(GROUP, Role.LEAD, MappingStatus.ACTIVE),),
    )
    read = _read(World({A: data}))

    with as_tenant(A):
        overview = await read.overview(_admin())

    assert overview.tenant.id == A and overview.host == f"{A}.example.org"
    assert overview.config is not None and overview.config.version == 1
    assert [c.kind for c in overview.contacts] == [ContactKind.COORDINATION_PHONE]
    assert [c.id for c in overview.channels] == ["sms-1"]
    assert len(overview.retention) == 8
    assert [b.status for b in overview.bindings] == [BindingStatus.PENDING]
    assert [m.role for m in overview.mappings] == [Role.LEAD]


async def test_a_tenant_with_nothing_configured_has_no_version_and_empty_lists() -> None:
    read = _read(World({A: Data()}))

    with as_tenant(A):
        overview = await read.overview(_admin())

    assert overview.config is None
    assert overview.contacts == overview.channels == overview.retention == ()


async def test_two_tenants_each_read_their_own_and_nothing_of_the_other() -> None:
    world = World(
        {
            A: Data(
                versions=[_version(1, ConfigStatus.CURRENT, {"systemName": "Alpha view"})],
                contacts=(TenantContact(ContactKind.COORDINATION_PHONE, "Alpha", "01234 567890"),),
            ),
            B: Data(
                versions=[_version(1, ConfigStatus.CURRENT, {"systemName": "Bravo view"})],
                contacts=(TenantContact(ContactKind.COORDINATION_PHONE, "Bravo", "01632 960001"),),
            ),
        }
    )
    read = _read(world, A, B)

    with as_tenant(A):
        mine = await read.overview(_admin(A))
    with as_tenant(B):
        theirs = await read.overview(_admin(B))

    assert mine.config.values["systemName"] == "Alpha view"  # type: ignore[union-attr]
    assert theirs.config.values["systemName"] == "Bravo view"  # type: ignore[union-attr]
    assert [c.label for c in mine.contacts] == ["Alpha"]
    assert [c.label for c in theirs.contacts] == ["Bravo"]
    assert (mine.host, theirs.host) == (f"{A}.example.org", f"{B}.example.org")


async def test_a_tenant_the_directory_does_not_know_is_not_found() -> None:
    world = World({A: Data()})
    platform = FakePlatform()
    read = ReadTenantAdmin(world.factory, platform, FixedNow())  # type: ignore[arg-type]

    with as_tenant(A), pytest.raises(NotFound):
        await read.overview(_admin())


# ---------------------------------------------------------------- the versions


def _history() -> Data:
    return Data(
        versions=[
            _version(1, ConfigStatus.SUPERSEDED, {"systemName": "Alpha view"}),
            _version(
                2,
                ConfigStatus.CURRENT,
                {"systemName": "Alpha view", "referralSystemName": "Alpha referrals"},
            ),
            _version(
                3,
                ConfigStatus.PENDING_APPROVAL,
                {
                    "systemName": "Alpha view",
                    "referralSystemName": "Alpha referrals",
                    "coordinationTeamName": "The Alpha team",
                },
                approved_by_refs=("person-b",),
            ),
        ]
    )


async def test_versions_are_newest_first_and_each_is_judged_against_the_one_in_force_below() -> (
    None
):
    read = _read(World({A: _history()}))

    with as_tenant(A):
        views = await read.versions(_admin())

    assert [v.config.version for v in views] == [3, 2, 1]
    assert [v.replaces for v in views] == [2, 1, None]
    assert views[0].changed_keys == ("coordinationTeamName",)
    assert views[1].changed_keys == ("referralSystemName",)
    assert views[2].changed_keys == ("systemName",)
    assert all(v.clinical_keys == () and v.approvals_required == 1 for v in views)


async def test_a_clinical_change_says_so_and_needs_two_people() -> None:
    data = Data(
        versions=[
            _version(1, ConfigStatus.CURRENT, {"systemName": "Alpha view"}),
            _version(
                2,
                ConfigStatus.DRAFT,
                {"systemName": "Alpha view", "reverifyEveryDays": 14},
            ),
        ]
    )
    read = _read(World({A: data}))

    with as_tenant(A):
        views = await read.versions(_admin())

    draft = views[0]
    assert draft.changed_keys == ("reverifyEveryDays",)
    assert draft.clinical_keys == ("reverifyEveryDays",)
    assert draft.approvals_required == 2
    assert draft.replaces == 1


async def test_one_version_is_found_by_its_number_and_another_is_not_found() -> None:
    read = _read(World({A: _history()}))

    with as_tenant(A):
        assert (await read.version(_admin(), 2)).config.version == 2
        with pytest.raises(NotFound):
            await read.version(_admin(), 9)


async def test_another_tenants_versions_are_not_visible() -> None:
    world = World({A: _history(), B: Data()})
    read = _read(world, A, B)

    with as_tenant(B):
        assert await read.versions(_admin(B)) == []
        with pytest.raises(NotFound):
            await read.version(_admin(B), 1)


# ---------------------------------------------------------------- the operator access log


def _log() -> Data:
    return Data(
        audit=[
            _record("SupportAccessTicket", Role.SUPPORT, 50, action="support-ticket-requested"),
            _record("ActivateTenant", Role.PLATFORM_OPERATOR, 40, action="U"),
            _record("ApproveTenantConfig", Role.TENANT_ADMIN, 30, action="U"),
            _record("OpenCrossTenantAccess", Role.SUPPORT, 20, action="support-access-opened"),
            _record("SupportAccessTicket", Role.TENANT_ADMIN, 10, action="support-ticket-approved"),
            _record("ExchangeStaffToken", Role.LEAD, 5, action="token-issued"),
        ]
    )


async def test_the_log_is_what_the_platforms_people_did_newest_first() -> None:
    read = _read(World({A: _log()}))

    with as_tenant(A):
        entries = await read.access_log(_admin())

    assert [(e.use_case, e.role) for e in entries] == [
        ("OpenCrossTenantAccess", Role.SUPPORT),
        ("ActivateTenant", Role.PLATFORM_OPERATOR),
        ("SupportAccessTicket", Role.SUPPORT),
    ]
    assert entries[0].actor_ref == "ref-support"
    assert entries[0].entity_ids == ("entity-20",) and entries[0].snapshot == {"n": 20}


async def test_the_log_asks_only_for_the_platforms_use_cases_in_the_window() -> None:
    world = World({A: _log()})
    read = _read(world)

    with as_tenant(A):
        await read.access_log(_admin(), days=30)

    start, end, use_cases = world.audits[0].asked[0]
    assert end == NOW and start == NOW - timedelta(days=30)
    assert "ExchangeStaffToken" not in use_cases and "ApproveTenantConfig" not in use_cases
    assert {"ActivateTenant", "OpenCrossTenantAccess", "SupportAccessTicket"} <= use_cases


@pytest.mark.parametrize("days", [0, -1, 401, "90", None, 1.5])
async def test_a_window_that_is_not_a_window_is_refused_before_anything_is_read(days: Any) -> None:
    world = World({A: _log()})
    read = _read(world)

    with as_tenant(A), pytest.raises(ValidationFailed):
        await read.access_log(_admin(), days=days)

    assert world.audits == []


async def test_the_log_is_bounded() -> None:
    many = Data(
        audit=[_record("ActivateTenant", Role.PLATFORM_OPERATOR, m) for m in range(300, 0, -1)]
    )
    read = _read(World({A: many}))

    with as_tenant(A):
        entries = await read.access_log(_admin())

    assert len(entries) == ACCESS_LOG_LIMIT
    assert entries[0].entity_ids == ("entity-1",)


async def test_one_tenant_never_reads_the_others_log() -> None:
    world = World(
        {
            A: Data(audit=[_record("ActivateTenant", Role.PLATFORM_OPERATOR, 5, A)]),
            B: Data(audit=[_record("SuspendTenant", Role.PLATFORM_OPERATOR, 6, B)]),
        }
    )
    read = _read(world, A, B)

    with as_tenant(A):
        mine = await read.access_log(_admin(A))
    with as_tenant(B):
        theirs = await read.access_log(_admin(B))

    assert [e.use_case for e in mine] == ["ActivateTenant"]
    assert [e.use_case for e in theirs] == ["SuspendTenant"]
