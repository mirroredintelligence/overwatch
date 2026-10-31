"""Offboarding a tenant: start, export and complete (TEN-074, DEC-136 item 10, audit F 2.4).

The platform operator moves a tenant to offboarding (it first leaves every network), exports its
data to a package with a manifest of hashes, and completes the offboarding (the export delivered or
waived, the notice over or waived; its numbers are quarantined for 90 days). Each use case is for
the one tenant its call is bound to, writes that tenant's chain, refuses a tenant in the wrong
state before it writes anything, and can be run again after a failure.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.memory_export_storage import MemoryExportStorage
from diucs.application.ports.outbound.tenant_export import (
    AuditHeadState,
    ExportedNode,
    ExportedRelationship,
    LabelCount,
)
from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord
from diucs.application.tenancy import TenantMismatch, bind_tenant
from diucs.application.use_cases.membership import LeaveAllNetworks
from diucs.application.use_cases.network_admin import GovernanceRecorder
from diucs.application.use_cases.network_leave import EndResult
from diucs.application.use_cases.tenant_offboard import (
    CompleteOffboarding,
    CompleteOffboardingCommand,
    ExportTenant,
    ExportTenantCommand,
    OffboardTenant,
)
from diucs.application.use_cases.tenant_offboarding import (
    StartOffboardingCommand,
    StartTenantOffboarding,
)
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, InvalidTransition, NotAllowed, ValidationFailed
from diucs.domain.model.network import MembershipStatus
from diucs.domain.model.tenant import NumberStatus, TenantStatus
from diucs.domain.rules.tenant_export import UnclassifiedData, sha256_hex
from tests.support.network_admin_fakes import (
    Ids,
    MemoryRegistry,
    UnitFactories,
    UnitWorld,
    person,
)
from tests.support.network_samples import (
    MEMBER_B,
    NETWORK_ID,
    make_grant,
    make_member,
    make_network,
    make_owner_membership,
    rid,
)
from tests.support.provisioning_fakes import FakePlatform, provisioning_tenant

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
TENANT = MEMBER_B
ACCOUNT_SID = "AC" + "0" * 32


class _Ends:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.calls: list[tuple[str, str]] = []

    async def end_member(self, network_id: str, member: str, *, at: Any) -> EndResult:
        self.log.append("ends:end_member")
        self.calls.append((network_id, member))
        return EndResult(3, 3)


class _Reader:
    def __init__(self) -> None:
        self.counts: list[LabelCount] = []
        self.rows: dict[tuple[str, ...], list[ExportedNode]] = {}
        self.rels: list[ExportedRelationship] = []
        self.head: AuditHeadState | None = AuditHeadState("cd" * 32, 12)
        self.pages = 0

    async def node_counts(self) -> list[LabelCount]:
        return list(self.counts)

    async def nodes(
        self, labels: tuple[str, ...], *, after: str | None, limit: int
    ) -> list[ExportedNode]:
        self.pages += 1
        rows = self.rows.get(tuple(sorted(labels)), [])
        later = [r for r in rows if after is None or r.ref > after]
        return later[:limit]

    async def relationships(self, *, after: str | None, limit: int) -> list[ExportedRelationship]:
        later = [r for r in self.rels if after is None or r.ref > after]
        return later[:limit]

    async def audit_head(self) -> AuditHeadState | None:
        return self.head


class _Rig:
    def __init__(self, status: TenantStatus = TenantStatus.ACTIVE, **tenant_fields: Any) -> None:
        self.log: list[str] = []
        self.clock = FixedClock(NOW)
        fields: dict[str, Any] = {
            "created_at": NOW - timedelta(days=200),
            "activated_at": NOW - timedelta(days=100),
        }
        if status is TenantStatus.OFFBOARDING:
            fields["offboarding_started_at"] = NOW - timedelta(days=31)
        if status is TenantStatus.OFFBOARDED:
            fields["offboarding_started_at"] = NOW - timedelta(days=40)
            fields["offboarded_at"] = NOW - timedelta(days=5)
        fields.update(tenant_fields)
        self.platform = FakePlatform(provisioning_tenant(TENANT, status=status, **fields))
        self.world = UnitWorld(self.log)
        self.registry = MemoryRegistry(self.log)
        self.registry.seed(
            make_network(),
            members=[make_owner_membership(), make_member(TENANT, id=rid("mem-t"))],
            grants=[make_grant(id=rid("grant-t"), tenant=TENANT)],
        )
        factories = UnitFactories(self.world)
        recorder = GovernanceRecorder(
            factories.tenant,  # type: ignore[arg-type]
            factories.network,  # type: ignore[arg-type]
            Ids("ob"),
            self.clock,
        )
        self.ends = _Ends(self.log)
        self.leave = LeaveAllNetworks(
            self.registry,  # type: ignore[arg-type]
            self.ends,  # type: ignore[arg-type]
            recorder,
            self.clock,
        )
        self.storage = MemoryExportStorage()
        self.reader = _Reader()
        self.changed: list[str] = []
        platform: Any = self.platform
        self.start = OffboardTenant(
            platform,
            self.leave,
            StartTenantOffboarding(
                platform,
                platform,
                factories.tenant,  # type: ignore[arg-type]
                self.clock,
                (self.changed.append,),
            ),
            factories.tenant,  # type: ignore[arg-type]
            self.clock,
        )
        self.export = ExportTenant(
            platform,
            self.reader,
            self.storage,
            factories.tenant,  # type: ignore[arg-type]
            Ids("pkg"),
            self.clock,
        )
        self.complete = CompleteOffboarding(
            platform,
            platform,
            self.storage,
            factories.tenant,  # type: ignore[arg-type]
            self.clock,
            (self.changed.append,),
        )

    @property
    def tenant(self) -> Any:
        return self.platform.tenants[TENANT]

    def add_number(self, e164: str = "+441234567890") -> None:
        self.platform.numbers_by_tenant.setdefault(TENANT, {})[e164] = TenantNumberRecord(
            e164, ACCOUNT_SID, f"twilio/{TENANT}/token", NumberStatus.ACTIVE, NOW
        )


def _operator(role: Role = Role.PLATFORM_OPERATOR, name: str = "op-1") -> Any:
    return person(TENANT, role, name)


@pytest.fixture(autouse=True)
def _bound() -> Any:
    with bind_tenant(TENANT):
        yield


# ---------------------------------------------------------------- start


async def test_a_tenant_leaves_its_networks_and_then_its_record_moves_to_offboarding() -> None:
    rig = _Rig()
    result = await rig.start.execute(StartOffboardingCommand(_operator(), TENANT))
    assert (result.memberships_ended, result.resumed) == (1, False)
    assert rig.tenant.status is TenantStatus.OFFBOARDING
    assert rig.tenant.offboarding_started_at == NOW
    assert rig.registry.members[rid("mem-t")].status is MembershipStatus.LEFT
    assert rig.ends.calls == [(NETWORK_ID, TENANT)]
    assert rig.changed == [TENANT]
    # the memberships end while the tenant is still active, so their events are relayed
    assert rig.log.index("ends:end_member") < rig.log.index("tenant:audit:StartTenantOffboarding")
    assert [e.use_case for _, e in rig.world.audits][-2:] == [
        "EndNetworkMemberships",
        "StartTenantOffboarding",
    ]
    assert result.notice_ends_at == NOW + timedelta(days=30)


async def test_the_owner_of_a_network_cannot_be_offboarded_until_it_hands_it_over() -> None:
    rig = _Rig()
    rig.registry.members[rid("mem-owner")] = replace(
        make_owner_membership(), member_tenant_id=TENANT
    )
    network, settings = rig.registry.networks[NETWORK_ID]
    rig.registry.networks[NETWORK_ID] = (replace(network, owner_tenant_id=TENANT), settings)
    with pytest.raises(NotAllowed):
        await rig.start.execute(StartOffboardingCommand(_operator(), TENANT))
    assert rig.tenant.status is TenantStatus.ACTIVE and rig.ends.calls == []


@pytest.mark.parametrize("status", [TenantStatus.PROVISIONING, TenantStatus.PURGED])
async def test_a_tenant_in_another_state_is_refused_before_anything_changes(
    status: TenantStatus,
) -> None:
    rig = _Rig(
        status,
        activated_at=NOW if status is TenantStatus.PURGED else None,
        offboarding_started_at=NOW if status is TenantStatus.PURGED else None,
        offboarded_at=NOW if status is TenantStatus.PURGED else None,
        purged_at=NOW if status is TenantStatus.PURGED else None,
    )
    with pytest.raises((InvalidTransition, NotAllowed)):
        await rig.start.execute(StartOffboardingCommand(_operator(), TENANT))
    assert rig.ends.calls == [] and rig.changed == []


@pytest.mark.parametrize("role", [Role.TENANT_ADMIN, Role.NETWORK_ADMIN, Role.LEAD, Role.OWNER])
async def test_only_the_platform_operator_starts_it(role: Role) -> None:
    rig = _Rig()
    with pytest.raises(NotAllowed):
        await rig.start.execute(StartOffboardingCommand(_operator(role), TENANT))
    assert rig.tenant.status is TenantStatus.ACTIVE


async def test_an_actor_of_another_tenant_is_a_wiring_fault() -> None:
    rig = _Rig()
    with pytest.raises(TenantMismatch):
        await rig.start.execute(
            StartOffboardingCommand(person("other-org", Role.PLATFORM_OPERATOR), "other-org")
        )


async def test_a_start_that_stopped_after_the_memberships_is_finished_by_running_it_again() -> None:
    rig = _Rig()
    rig.platform.reject_save = True
    with pytest.raises(Conflict):
        await rig.start.execute(StartOffboardingCommand(_operator(), TENANT))
    assert rig.registry.members[rid("mem-t")].status is MembershipStatus.LEFT  # already done
    assert rig.tenant.status is TenantStatus.ACTIVE
    rig.platform.reject_save = False
    again = await rig.start.execute(StartOffboardingCommand(_operator(), TENANT))
    assert again.memberships_ended == 0 and rig.tenant.status is TenantStatus.OFFBOARDING


async def test_a_second_start_on_an_offboarding_tenant_only_finishes_what_is_left() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    result = await rig.start.execute(StartOffboardingCommand(_operator(), TENANT))
    assert result.resumed and rig.tenant.status is TenantStatus.OFFBOARDING
    assert rig.changed == []  # the record was not written again
    assert result.notice_ends_at == NOW - timedelta(days=1)  # started 31 days ago


async def test_the_operator_must_type_the_tenants_id_before_anything_ends() -> None:
    rig = _Rig()
    for typed in ("org-other", "", "ORG-LEAVING"):
        with pytest.raises(ValidationFailed):
            await rig.start.execute(StartOffboardingCommand(_operator(), typed))
    assert rig.ends.calls == [] and rig.tenant.status is TenantStatus.ACTIVE


# ---------------------------------------------------------------- export


def _stock(rig: _Rig) -> None:
    rig.reader.counts = [
        LabelCount(("HealthcareService", "Resource"), 2),
        LabelCount(("Observation", "Resource"), 1),
        LabelCount(("ProtectedContact",), 3),
        LabelCount(("Credential",), 4),
    ]
    rig.reader.rows = {
        ("HealthcareService", "Resource"): [
            ExportedNode("n1", {"name": "Ward A"}),
            ExportedNode("n2", {"name": "Ward B"}),
        ],
        ("Observation", "Resource"): [ExportedNode("n3", {"value": 4, "at": NOW})],
        ("ProtectedContact",): [ExportedNode("p1", {"phone": "07700 900123"})],
    }
    rig.reader.rels = [ExportedRelationship("r1", "FOCUS", "n3", "n1", {})]


async def test_the_package_has_a_file_for_each_label_set_and_a_manifest_of_hashes() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    _stock(rig)
    result = await rig.export.execute(ExportTenantCommand(_operator()))
    names = rig.storage.names(TENANT, result.package_id)
    assert names == [
        "capacity-reports/Observation+Resource.jsonl",
        "directory-and-criteria/HealthcareService+Resource.jsonl",
        "manifest.json",
        "relationships.jsonl",
    ]
    manifest = json.loads(rig.storage.files[(TENANT, result.package_id, "manifest.json")])
    assert manifest["tenant"] == TENANT and manifest["audit_chain"] == {
        "last_hash": "cd" * 32,
        "last_seq": 12,
    }
    for entry in manifest["files"]:
        stored = rig.storage.files[(TENANT, result.package_id, entry["name"])]
        assert entry["sha256"] == sha256_hex(stored)
        assert entry["rows"] == len([line for line in stored.splitlines() if line])
    assert result.manifest_hash == sha256_hex(
        rig.storage.files[(TENANT, result.package_id, "manifest.json")]
    )
    assert await rig.storage.has_package(TENANT, result.manifest_hash)


async def test_the_protected_stores_are_held_back_unless_asked_and_secrets_never_go() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    _stock(rig)
    plain = await rig.export.execute(ExportTenantCommand(_operator()))
    assert plain.held_back == {"ProtectedContact": 3} and plain.excluded == {"Credential": 4}
    assert not any("protected" in n for n in rig.storage.names(TENANT, plain.package_id))
    asked = await rig.export.execute(ExportTenantCommand(_operator(), include_protected=True))
    assert any("protected/" in n for n in rig.storage.names(TENANT, asked.package_id))
    assert asked.held_back == {} and asked.excluded == {"Credential": 4}
    for package in (plain.package_id, asked.package_id):
        assert not any("Credential" in n for n in rig.storage.names(TENANT, package))


async def test_a_kind_of_data_with_no_class_refuses_the_export_and_writes_nothing() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    rig.reader.counts = [LabelCount(("SomethingNew",), 1)]
    with pytest.raises(UnclassifiedData):
        await rig.export.execute(ExportTenantCommand(_operator()))
    assert rig.storage.files == {} and rig.world.audits == []


async def test_the_export_pages_through_a_long_label_set(monkeypatch: pytest.MonkeyPatch) -> None:
    import diucs.application.use_cases.tenant_offboard as module

    monkeypatch.setattr(module, "PAGE_SIZE", 2)
    rig = _Rig(TenantStatus.OFFBOARDING)
    rig.reader.counts = [LabelCount(("HealthcareService", "Resource"), 5)]
    rig.reader.rows = {
        ("HealthcareService", "Resource"): [ExportedNode(f"n{i}", {"i": i}) for i in range(5)]
    }
    result = await rig.export.execute(ExportTenantCommand(_operator()))
    [entry] = [f for f in result.files if f.name.startswith("directory")]
    assert entry.rows == 5 and rig.reader.pages == 3


@pytest.mark.parametrize(
    "status", [TenantStatus.ACTIVE, TenantStatus.SUSPENDED, TenantStatus.PROVISIONING]
)
async def test_only_a_tenant_that_is_being_offboarded_is_exported(status: TenantStatus) -> None:
    fields: dict[str, Any] = {"activated_at": NOW}
    if status is TenantStatus.SUSPENDED:
        from diucs.domain.model.tenant import SuspendMode, SuspendReason

        fields.update(
            suspended_at=NOW,
            suspend_mode=SuspendMode.BLOCKED,
            suspend_reason=SuspendReason.CONTRACT,
        )
    if status is TenantStatus.PROVISIONING:
        fields["activated_at"] = None
    rig = _Rig(status, **fields)
    with pytest.raises(NotAllowed):
        await rig.export.execute(ExportTenantCommand(_operator()))
    assert rig.storage.files == {}


async def test_an_export_that_did_not_arrive_whole_is_not_acknowledged() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    _stock(rig)
    rig.storage.fail_next = True
    with pytest.raises(ConnectionError):
        await rig.export.execute(ExportTenantCommand(_operator()))
    assert rig.world.audits == []  # no record of an export that did not happen


async def test_the_audit_names_the_package_the_hash_and_counts_and_no_value() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    _stock(rig)
    result = await rig.export.execute(ExportTenantCommand(_operator()))
    [(scope, entry)] = rig.world.audits
    assert (scope, entry.use_case) == (TENANT, "ExportTenant")
    assert entry.snapshot == {
        "package": result.package_id,
        "manifest_hash": result.manifest_hash,
        "files": 3,  # two label sets and the relationships; the manifest is not counted
        "protected_included": False,
    }
    assert "Ward" not in repr(entry)


# ---------------------------------------------------------------- complete


async def test_the_export_delivered_and_the_notice_over_complete_it_and_quarantine_numbers() -> (
    None
):
    rig = _Rig(TenantStatus.OFFBOARDING)
    _stock(rig)
    rig.add_number()
    delivered = await rig.export.execute(ExportTenantCommand(_operator()))
    result = await rig.complete.execute(
        CompleteOffboardingCommand(_operator(), manifest_hash=delivered.manifest_hash)
    )
    assert (result.numbers_quarantined, result.resumed) == (1, False)
    assert rig.tenant.status is TenantStatus.OFFBOARDED and rig.tenant.offboarded_at == NOW
    [number] = rig.platform.numbers_by_tenant[TENANT].values()
    assert (number.status, number.quarantine_until) == (
        NumberStatus.QUARANTINED,
        NOW + timedelta(days=90),
    )
    assert rig.changed == [TENANT]


async def test_without_the_export_or_a_waiver_it_is_refused_and_nothing_changes() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    rig.add_number()
    for manifest in (None, "0" * 64, sha256_hex(b"another package")):
        with pytest.raises(NotAllowed):
            await rig.complete.execute(
                CompleteOffboardingCommand(_operator(), manifest_hash=manifest)
            )
    assert rig.tenant.status is TenantStatus.OFFBOARDING
    assert next(iter(rig.platform.numbers_by_tenant[TENANT].values())).status is NumberStatus.ACTIVE


async def test_another_tenants_package_does_not_count_as_this_tenants_export() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    await rig.storage.put("other-org", "pkg", "manifest.json", b"{}")
    with pytest.raises(NotAllowed):
        await rig.complete.execute(
            CompleteOffboardingCommand(_operator(), manifest_hash=sha256_hex(b"{}"))
        )


async def test_the_export_may_be_waived_in_writing() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    result = await rig.complete.execute(CompleteOffboardingCommand(_operator(), export_waived=True))
    assert result.numbers_quarantined == 0 and rig.tenant.status is TenantStatus.OFFBOARDED


async def test_before_the_notice_has_ended_it_is_refused_unless_the_notice_is_waived() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING, offboarding_started_at=NOW - timedelta(days=10))
    with pytest.raises(NotAllowed):
        await rig.complete.execute(CompleteOffboardingCommand(_operator(), export_waived=True))
    assert rig.tenant.status is TenantStatus.OFFBOARDING
    await rig.complete.execute(
        CompleteOffboardingCommand(_operator(), export_waived=True, notice_waived=True)
    )
    assert rig.tenant.status is TenantStatus.OFFBOARDED


@pytest.mark.parametrize("status", [TenantStatus.ACTIVE, TenantStatus.PROVISIONING])
async def test_only_an_offboarding_tenant_is_completed(status: TenantStatus) -> None:
    rig = _Rig(status, activated_at=NOW if status is TenantStatus.ACTIVE else None)
    with pytest.raises(NotAllowed):
        await rig.complete.execute(CompleteOffboardingCommand(_operator(), export_waived=True))


async def test_a_completion_that_stopped_after_the_record_finishes_the_numbers_next_time() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    rig.add_number("+441234567890")
    rig.add_number("+441234567891")
    first = await rig.complete.execute(CompleteOffboardingCommand(_operator(), export_waived=True))
    assert first.numbers_quarantined == 2
    # a number that came back to active (a failed step) is quarantined by the repeat, once
    held = rig.platform.numbers_by_tenant[TENANT]
    held["+441234567891"] = replace(
        held["+441234567891"], status=NumberStatus.ACTIVE, quarantine_until=None
    )
    rig.clock.advance(timedelta(days=1))
    again = await rig.complete.execute(CompleteOffboardingCommand(_operator(), export_waived=True))
    assert (again.resumed, again.numbers_quarantined) == (True, 1)
    assert held["+441234567891"].quarantine_until == rig.tenant.offboarded_at + timedelta(days=90)  # type: ignore[operator]
