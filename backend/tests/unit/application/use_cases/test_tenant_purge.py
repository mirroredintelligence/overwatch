"""Purging a tenant (TEN-074, DEC-136 item 10, audit F 2.4, hazards H-T18 and H-T29).

Two different named operators, the tenant's id typed exactly, an offboarded tenant whose retention
hold has passed. A dry run changes nothing. The order is the safety: the tombstone is recorded
first (and if it cannot be, nothing is deleted), the record becomes purged, the data goes in
batches, the cache names go, the audit chain goes last, and nothing may be left. A purge that
stopped is finished by running it again.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.recording_platform_audit import RecordingPlatformAudit
from diucs.application.ports.outbound.tenant_export import AuditHeadState, LabelCount
from diucs.application.tenancy import ScopeId, TenantMismatch, bind_tenant
from diucs.application.use_cases.tenant_purge import PurgeTenant, PurgeTenantCommand
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, NotAllowed, NotFound
from diucs.domain.model.tenant import TenantStatus
from tests.support.network_admin_fakes import person
from tests.support.provisioning_fakes import FakePlatform, provisioning_tenant

NOW = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
TENANT = "org-leaving"


class _Graph:
    """The tenant's scope as the reader and the purger see it: nodes by label set, a log of what
    was asked, and a count that goes down as batches are deleted (data first, audit last)."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.data = {("HealthcareService", "Resource"): 5, ("Observation", "Resource"): 3}
        self.audit = {("AuditEvent", "ChainLink"): 4, ("AuditHead",): 1}
        self.leave_behind = 0  # a node the purge cannot delete
        self.fail_data_after: int | None = None
        self.batches: list[tuple[str, int]] = []

    async def node_counts(self) -> list[LabelCount]:
        items = {**self.data, **self.audit}
        return [LabelCount(k, v) for k, v in sorted(items.items()) if v]

    async def audit_head(self) -> AuditHeadState | None:
        return AuditHeadState("ee" * 32, 4)

    async def delete_data_batch(self, limit: int) -> int:
        self.log.append("purger:data")
        if self.fail_data_after is not None and len(self.batches) >= self.fail_data_after:
            raise ConnectionError("neo4j went away")
        return self._take(self.data, limit, "data")

    async def delete_audit_batch(self, limit: int) -> int:
        self.log.append("purger:audit")
        if any(self.data.values()):
            return 0  # the chain goes last: the statement deletes nothing while data is left
        return self._take(self.audit, limit, "audit")

    def _take(self, bucket: dict[tuple[str, ...], int], limit: int, kind: str) -> int:
        taken = 0
        for labels in list(bucket):
            n = min(bucket[labels], limit - taken)
            bucket[labels] -= n
            taken += n
            if taken >= limit:
                break
        if taken:
            self.batches.append((kind, taken))
        return taken


class _Cache:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.scopes: list[ScopeId] = []

    async def purge_scope(self, scope: ScopeId) -> int:
        self.log.append("cache:purge")
        self.scopes.append(scope)
        return 7


class _Rig:
    def __init__(self, status: TenantStatus = TenantStatus.OFFBOARDED, **fields: Any) -> None:
        self.log: list[str] = []
        self.clock = FixedClock(NOW)
        base: dict[str, Any] = {
            "created_at": NOW - timedelta(days=300),
            "activated_at": NOW - timedelta(days=200),
        }
        if status in (TenantStatus.OFFBOARDING, TenantStatus.OFFBOARDED, TenantStatus.PURGED):
            base["offboarding_started_at"] = NOW - timedelta(days=60)
        if status in (TenantStatus.OFFBOARDED, TenantStatus.PURGED):
            base["offboarded_at"] = NOW - timedelta(days=20)
        if status is TenantStatus.PURGED:
            base["purged_at"] = NOW - timedelta(days=1)
        if status is TenantStatus.SUSPENDED:
            from diucs.domain.model.tenant import SuspendMode, SuspendReason

            base.update(
                suspended_at=NOW - timedelta(days=1),
                suspend_mode=SuspendMode.BLOCKED,
                suspend_reason=SuspendReason.CONTRACT,
            )
        base.update(fields)
        self.platform = FakePlatform(provisioning_tenant(TENANT, status=status, **base))
        self.graph = _Graph(self.log)
        self.cache = _Cache(self.log)
        self.audit = RecordingPlatformAudit()
        platform: Any = self.platform
        original_append = self.audit.append
        original_save = platform.save

        async def logged_append(entry: Any) -> None:
            self.log.append(f"platform-audit:{entry.action}")
            await original_append(entry)

        async def logged_save(*args: Any, **kw: Any) -> Any:
            self.log.append("registry:save")
            return await original_save(*args, **kw)

        self.audit.append = logged_append  # type: ignore[method-assign]
        platform.save = logged_save
        self.changed: list[str] = []
        self.purge = PurgeTenant(
            platform,
            platform,
            self.graph,  # type: ignore[arg-type]
            self.graph,  # type: ignore[arg-type]
            self.cache,
            self.audit,
            self.clock,
            (self.changed.append,),
        )

    @property
    def tenant(self) -> Any:
        return self.platform.tenants[TENANT]


def _op(name: str, role: Role = Role.PLATFORM_OPERATOR) -> Any:
    return person(TENANT, role, name)


def _cmd(rig: _Rig | None = None, **over: Any) -> PurgeTenantCommand:
    fields: dict[str, Any] = dict(actor=_op("one"), second_actor=_op("two"), typed_slug=TENANT)
    fields.update(over)
    return PurgeTenantCommand(**fields)


@pytest.fixture(autouse=True)
def _bound() -> Any:
    with bind_tenant(TENANT):
        yield


# ---------------------------------------------------------------- the guards


async def test_two_operators_the_typed_id_and_an_offboarded_tenant_purge_it() -> None:
    rig = _Rig()
    result = await rig.purge.execute(_cmd())
    assert (result.dry_run, result.resumed, result.nodes_deleted) == (False, False, 13)
    assert rig.tenant.status is TenantStatus.PURGED and rig.tenant.purged_at == NOW
    assert result.counts == {
        "AuditEvent+ChainLink": 4,
        "AuditHead": 1,
        "HealthcareService+Resource": 5,
        "Observation+Resource": 3,
    }
    assert result.cache_names_removed == 7 and rig.cache.scopes == [ScopeId.tenant(TENANT)]
    assert await rig.graph.node_counts() == []
    assert rig.changed == [TENANT]


async def test_one_person_twice_is_not_two_operators() -> None:
    rig = _Rig()
    same = _op("one")
    with pytest.raises(NotAllowed) as caught:
        await rig.purge.execute(_cmd(actor=same, second_actor=same))
    assert "Two different operators" in str(caught.value)
    assert rig.audit.entries == [] and await rig.graph.node_counts() != []


@pytest.mark.parametrize("slug", ["", "org-leaving ", "ORG-LEAVING", "org-other", None])
async def test_the_id_must_be_typed_exactly(slug: Any) -> None:
    rig = _Rig()
    with pytest.raises(NotAllowed):
        await rig.purge.execute(_cmd(typed_slug=slug))
    assert rig.tenant.status is TenantStatus.OFFBOARDED and rig.audit.entries == []


@pytest.mark.parametrize(
    "status", [TenantStatus.ACTIVE, TenantStatus.OFFBOARDING, TenantStatus.SUSPENDED]
)
async def test_only_an_offboarded_tenant_is_purged(status: TenantStatus) -> None:
    rig = _Rig(status)
    with pytest.raises(NotAllowed):
        await rig.purge.execute(_cmd())
    assert rig.audit.entries == [] and rig.graph.batches == []


async def test_a_retention_hold_in_the_future_blocks_it() -> None:
    rig = _Rig(retention_hold_until=NOW + timedelta(days=1))
    with pytest.raises(NotAllowed) as caught:
        await rig.purge.execute(_cmd())
    assert "Retention hold" in str(caught.value)
    assert rig.graph.batches == []


async def test_a_hold_that_has_passed_does_not_block() -> None:
    rig = _Rig(retention_hold_until=NOW - timedelta(seconds=1))
    await rig.purge.execute(_cmd())
    assert rig.tenant.status is TenantStatus.PURGED


@pytest.mark.parametrize("role", [Role.TENANT_ADMIN, Role.NETWORK_ADMIN, Role.LEAD, Role.OWNER])
async def test_both_must_be_platform_operators(role: Role) -> None:
    rig = _Rig()
    with pytest.raises(NotAllowed):
        await rig.purge.execute(_cmd(actor=_op("one", role)))
    with pytest.raises(NotAllowed):
        await rig.purge.execute(_cmd(second_actor=_op("two", role)))
    assert rig.audit.entries == []


async def test_an_operator_without_a_name_is_not_an_operator() -> None:
    from dataclasses import replace

    rig = _Rig()
    with pytest.raises(NotAllowed):
        await rig.purge.execute(_cmd(second_actor=replace(_op("two"), practitioner_id=None)))
    assert rig.audit.entries == []


async def test_an_actor_of_another_tenant_is_a_wiring_fault() -> None:
    rig = _Rig()
    with pytest.raises(TenantMismatch):
        await rig.purge.execute(_cmd(second_actor=person("another", Role.PLATFORM_OPERATOR)))


async def test_an_unknown_tenant_is_not_found() -> None:
    rig = _Rig()
    del rig.platform.tenants[TENANT]
    with pytest.raises(NotFound):
        await rig.purge.execute(_cmd())


# ---------------------------------------------------------------- the dry run


async def test_a_dry_run_counts_and_changes_nothing() -> None:
    rig = _Rig()
    result = await rig.purge.execute(
        PurgeTenantCommand(_op("one"), _op("two"), typed_slug="", dry_run=True)
    )
    assert result.dry_run and result.nodes_deleted == 0
    assert result.counts["HealthcareService+Resource"] == 5
    assert rig.tenant.status is TenantStatus.OFFBOARDED
    assert rig.audit.entries == [] and rig.cache.scopes == [] and rig.graph.batches == []


async def test_a_dry_run_of_a_tenant_that_is_not_offboarded_is_refused() -> None:
    rig = _Rig(TenantStatus.OFFBOARDING)
    with pytest.raises(NotAllowed):
        await rig.purge.execute(PurgeTenantCommand(_op("one"), _op("two"), "", dry_run=True))


# ---------------------------------------------------------------- the order


async def test_the_tombstone_first_then_the_record_the_data_the_cache_and_the_chain() -> None:
    rig = _Rig()
    await rig.purge.execute(_cmd())
    steps = rig.log
    tombstone = steps.index("platform-audit:PurgeTenant")
    record = steps.index("registry:save")
    first_data = steps.index("purger:data")
    last_data = max(i for i, e in enumerate(steps) if e == "purger:data")
    cache = steps.index("cache:purge")
    first_audit = steps.index("purger:audit")
    assert tombstone < record < first_data
    assert last_data < cache < first_audit  # the audit chain goes after the data and the cache
    assert steps[-1] == "platform-audit:PurgeTenantCompleted"


async def test_the_tombstone_names_both_operators_the_final_chain_head_and_the_counts() -> None:
    rig = _Rig()
    await rig.purge.execute(_cmd(export_manifest_hash="ab" * 32))
    start, done = rig.audit.entries
    assert (start.action, start.tenant_id) == ("PurgeTenant", TENANT)
    assert start.principal_ref == _op("one").practitioner_id
    snapshot = start.snapshot or {}
    assert snapshot["second_principal_ref"] == _op("two").practitioner_id
    assert snapshot["final_audit_hash"] == "ee" * 32 and snapshot["final_audit_seq"] == 4
    assert snapshot["export_manifest_hash"] == "ab" * 32
    assert snapshot["counts"]["HealthcareService+Resource"] == 5
    assert done.action == "PurgeTenantCompleted" and (done.snapshot or {})["nodes_deleted"] == 13


async def test_if_the_platform_cannot_record_the_tombstone_nothing_is_deleted() -> None:
    rig = _Rig()
    rig.audit.fail_next = True
    with pytest.raises(ConnectionError):
        await rig.purge.execute(_cmd())
    assert rig.tenant.status is TenantStatus.OFFBOARDED
    assert rig.graph.batches == [] and rig.cache.scopes == []


async def test_the_audit_chain_is_not_deleted_while_any_data_is_left() -> None:
    rig = _Rig()
    assert await rig.graph.delete_audit_batch(100) == 0
    assert rig.graph.audit[("AuditEvent", "ChainLink")] == 4


async def test_the_data_goes_in_batches_of_the_batch_size() -> None:
    rig = _Rig()
    rig.graph.data = {("Observation", "Resource"): 2500}
    await rig.purge.execute(_cmd())
    assert [n for kind, n in rig.graph.batches if kind == "data"] == [1000, 1000, 500]


async def test_a_purge_that_cannot_remove_everything_says_so_and_is_not_completed() -> None:
    rig = _Rig()

    async def stuck(limit: int) -> int:
        return 0

    rig.graph.delete_data_batch = stuck  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        await rig.purge.execute(_cmd())
    assert [e.action for e in rig.audit.entries] == ["PurgeTenant"]


async def test_a_lost_race_on_the_record_deletes_nothing() -> None:
    rig = _Rig()
    rig.platform.reject_save = True
    with pytest.raises(Conflict):
        await rig.purge.execute(_cmd())
    assert rig.graph.batches == [] and rig.cache.scopes == []


# ---------------------------------------------------------------- a purge that stopped


async def test_a_purge_that_stopped_part_way_is_finished_by_the_same_command() -> None:
    rig = _Rig()
    rig.graph.fail_data_after = 0
    with pytest.raises(ConnectionError):
        await rig.purge.execute(_cmd())
    assert rig.tenant.status is TenantStatus.PURGED  # the record moved: nothing reopens it
    assert await rig.graph.node_counts() != []
    rig.graph.fail_data_after = None
    again = await rig.purge.execute(_cmd())
    assert again.resumed and await rig.graph.node_counts() == []
    assert [e.action for e in rig.audit.entries] == [
        "PurgeTenant",
        "PurgeTenant",
        "PurgeTenantCompleted",
    ]


async def test_a_purged_tenant_is_only_finished_with_two_operators_and_the_id() -> None:
    rig = _Rig(TenantStatus.PURGED)
    same = _op("one")
    with pytest.raises(NotAllowed):
        await rig.purge.execute(_cmd(actor=same, second_actor=same))
    with pytest.raises(NotAllowed):
        await rig.purge.execute(_cmd(typed_slug="wrong"))
    assert rig.audit.entries == []
