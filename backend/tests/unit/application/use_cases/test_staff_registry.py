"""The staff registry (DEC-1327): the platform's sync and the sign-in's tenant choice.

The sync reads each active tenant's verified directory and role mappings inside that tenant's scope,
lists each mapped group's members through Graph, and replaces that tenant's records. A tenant whose
read fails keeps its records, so a fault can end nobody's access in the picker. The choice reads a
person's records by their account reference and answers the active tenants they hold a role in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from overwatch.adapters.testing.fake_entra_groups import FakeEntraGroups
from overwatch.application.ports.outbound.entra_groups import GraphUnavailable
from overwatch.application.tenancy import current_tenant
from overwatch.application.use_cases.exchange_token import ExchangeRefused
from overwatch.application.use_cases.staff_registry import StaffTenantChoices, SyncStaffRegistry
from overwatch.domain.codes import Role
from overwatch.domain.errors import ValidationFailed
from overwatch.domain.model.staff_registry import StaffRoleRecord
from overwatch.domain.model.tenant import TenantStatus
from overwatch.domain.model.tenant_records import (
    BindingStatus,
    EntraBinding,
    MappingStatus,
    RoleMapping,
)
from overwatch.domain.rules.token_exchange import account_ref
from tests.support.tenant_samples import make_tenant

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
KEY = b"k" * 32
DIR_A = "11111111-1111-4111-8111-111111111111"
DIR_B = "22222222-2222-4222-8222-222222222222"
GROUP_LEAD_A = "aaaaaaaa-0000-4000-8000-000000000001"
GROUP_ADVISOR_B = "bbbbbbbb-0000-4000-8000-000000000002"
TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
PERSON_A_OBJECT = "33333333-3333-4333-8333-333333333333"
OTHER_OBJECT = "66666666-6666-4666-8666-666666666666"
UNBOUND_DIRECTORY = "55555555-5555-4555-8555-555555555555"


class FakeSecrets:
    def get(self, name: str) -> bytes:
        return KEY


class FakeClock:
    def now(self) -> datetime:
        return NOW


@dataclass
class FakeTenants:
    tenants: dict[str, Any] = field(default_factory=dict)

    async def get(self, tenant_id: str) -> Any:
        return self.tenants.get(tenant_id)

    async def active_tenant_ids(self) -> Sequence[str]:
        return [tid for tid, tenant in self.tenants.items() if tenant.status is TenantStatus.ACTIVE]


@dataclass
class TenantConfig:
    bindings_: tuple[EntraBinding, ...]
    mappings_: tuple[RoleMapping, ...]

    async def bindings(self) -> tuple[EntraBinding, ...]:
        return self.bindings_

    async def role_mappings(self) -> tuple[RoleMapping, ...]:
        return self.mappings_


class FakeUow:
    def __init__(self, config: TenantConfig) -> None:
        self.tenant_config = config

    async def __aenter__(self) -> FakeUow:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@dataclass
class FakeUowFactory:
    configs: dict[str, TenantConfig]
    unreadable: set[str] = field(default_factory=set)

    def __call__(self) -> FakeUow:
        tenant = current_tenant()
        if tenant in self.unreadable:
            raise GraphUnavailable
        return FakeUow(self.configs[tenant])


@dataclass
class FakeRegistry:
    rows: list[StaffRoleRecord] = field(default_factory=list)
    replaced: dict[str, tuple[StaffRoleRecord, ...]] = field(default_factory=dict)

    async def active_roles(self, practitioner_key: str) -> tuple[StaffRoleRecord, ...]:
        return tuple(
            r for r in self.rows if r.practitioner_key == practitioner_key and r.status == "active"
        )

    async def replace_tenant(
        self, tenant_id: str, records: Sequence[StaffRoleRecord], now: datetime
    ) -> None:
        self.replaced[tenant_id] = tuple(records)


def verified(directory: str) -> EntraBinding:
    return EntraBinding(
        directory_id=directory,
        status=BindingStatus.VERIFIED,
        verified_at=NOW,
        verified_by_ref="operator-ref-0001",
    )


def pending(directory: str) -> EntraBinding:
    return EntraBinding(directory_id=directory, status=BindingStatus.PENDING)


def mapping(group: str, role: Role) -> RoleMapping:
    return RoleMapping(group_object_id=group, role=role, status=MappingStatus.ACTIVE)


def tenants() -> FakeTenants:
    return FakeTenants(
        tenants={
            TENANT_A: make_tenant(id=TENANT_A, display_name="Fortrus Limited"),
            TENANT_B: make_tenant(id=TENANT_B, display_name="Trust B"),
        }
    )


def directory_with_members() -> FakeEntraGroups:
    fake = FakeEntraGroups()
    fake.groups = {
        DIR_A: {GROUP_LEAD_A: "Overwatch lead"},
        DIR_B: {GROUP_ADVISOR_B: "Overwatch advisor"},
    }
    fake.members_of = {
        (DIR_A, GROUP_LEAD_A): [PERSON_A_OBJECT],
        (DIR_B, GROUP_ADVISOR_B): [OTHER_OBJECT],
    }
    fake.users = {
        DIR_A: {"person@example.test": PERSON_A_OBJECT},
        DIR_B: {"other@example.test": OTHER_OBJECT},
    }
    return fake


def configs(*, b_binding: EntraBinding | None = None) -> FakeUowFactory:
    return FakeUowFactory(
        configs={
            TENANT_A: TenantConfig((verified(DIR_A),), (mapping(GROUP_LEAD_A, Role.LEAD),)),
            TENANT_B: TenantConfig(
                (b_binding or verified(DIR_B),), (mapping(GROUP_ADVISOR_B, Role.ADVISOR),)
            ),
        }
    )


def sync(uow: FakeUowFactory, groups: FakeEntraGroups, registry: FakeRegistry) -> SyncStaffRegistry:
    return SyncStaffRegistry(uow, tenants(), groups, registry, FakeSecrets(), FakeClock())  # type: ignore[arg-type]


# ---- the domain record


def test_a_record_has_one_id_per_tenant_person_and_role() -> None:
    key = account_ref(KEY, DIR_A, PERSON_A_OBJECT)
    record = StaffRoleRecord(
        tenant_id=TENANT_A, practitioner_key=key, role=Role.LEAD, status="active"
    )
    assert record.id == f"{TENANT_A}:{key}:lead"


@pytest.mark.parametrize(
    "override",
    [
        {"practitioner_key": "too-short"},
        {"role": "not-a-staff-role"},
        {"status": "retired"},
        {"tenant_id": "Trust A"},
    ],
)
def test_a_record_the_rules_refuse_is_refused(override: dict[str, Any]) -> None:
    base: dict[str, Any] = {
        "tenant_id": TENANT_A,
        "practitioner_key": account_ref(KEY, DIR_A, PERSON_A_OBJECT),
        "role": Role.LEAD,
        "status": "active",
    }
    with pytest.raises((ValidationFailed, ValueError)):
        StaffRoleRecord(**{**base, **override})


# ---- the sync


async def test_the_sync_writes_each_tenants_members_as_account_references_with_their_role() -> None:
    registry = FakeRegistry()
    report = await sync(configs(), directory_with_members(), registry).execute()
    assert (report.tenants, report.replaced, report.skipped) == (2, 2, 0)
    (lead,) = registry.replaced[TENANT_A]
    assert lead == StaffRoleRecord(
        tenant_id=TENANT_A,
        practitioner_key=account_ref(KEY, DIR_A, PERSON_A_OBJECT),
        role=Role.LEAD,
        status="active",
    )
    (advisor,) = registry.replaced[TENANT_B]
    assert advisor.role is Role.ADVISOR and advisor.tenant_id == TENANT_B


async def test_a_group_the_directory_no_longer_has_gives_no_members() -> None:
    groups = directory_with_members()
    groups.groups[
        DIR_A
    ] = {}  # the lead group was deleted in the directory (it is no longer listed)
    registry = FakeRegistry()
    await sync(configs(), groups, registry).execute()
    assert registry.replaced[TENANT_A] == ()
    assert len(registry.replaced[TENANT_B]) == 1


async def test_a_tenant_whose_read_fails_keeps_its_records_and_nothing_is_replaced_for_it() -> None:
    uow = configs()
    uow.unreadable = {TENANT_A}
    registry = FakeRegistry()
    report = await sync(uow, directory_with_members(), registry).execute()
    assert TENANT_A not in registry.replaced
    assert TENANT_B in registry.replaced
    assert (report.replaced, report.skipped) == (1, 1)


async def test_a_tenant_without_a_verified_directory_is_skipped_and_nothing_is_written_for_it() -> (
    None
):
    registry = FakeRegistry()
    report = await sync(
        configs(b_binding=pending(DIR_B)), directory_with_members(), registry
    ).execute()
    assert TENANT_B not in registry.replaced
    assert (report.replaced, report.skipped) == (1, 1)


# ---- the sign-in's choice


@dataclass
class FakeVerifier:
    identities: dict[str, Any] = field(default_factory=dict)

    async def verify(self, credential: str, audience: Any) -> Any:
        if credential not in self.identities:
            from overwatch.application.ports.outbound.identity_verifier import IdentityRejected

            raise IdentityRejected
        return self.identities[credential]


@dataclass
class Identity:
    directory_id: str
    object_id: str


def choices(
    rows: list[StaffRoleRecord], *, tenant_status: TenantStatus = TenantStatus.ACTIVE
) -> StaffTenantChoices:
    directory = FakeTenants(
        tenants={
            TENANT_A: make_tenant(id=TENANT_A, display_name="Fortrus Limited"),
            TENANT_B: make_tenant(id=TENANT_B, display_name="Trust B", status=tenant_status)
            if tenant_status is not TenantStatus.ACTIVE
            else make_tenant(id=TENANT_B, display_name="Trust B"),
        }
    )
    verifier = FakeVerifier(identities={"good-token": Identity(DIR_A, PERSON_A_OBJECT)})
    return StaffTenantChoices(verifier, FakeSecrets(), FakeRegistry(rows), directory)  # type: ignore[arg-type]


def record(tenant: str, role: Role) -> StaffRoleRecord:
    return StaffRoleRecord(
        tenant_id=tenant,
        practitioner_key=account_ref(KEY, DIR_A, PERSON_A_OBJECT),
        role=role,
        status="active",
    )


async def test_the_choice_lists_each_active_tenant_by_name_with_its_roles_in_priority_order() -> (
    None
):
    rows = [
        record(TENANT_B, Role.ADVISOR),
        record(TENANT_A, Role.ADVISOR),
        record(TENANT_A, Role.LEAD),
    ]
    listed = await choices(rows).execute("good-token")
    assert [(c.name, c.roles) for c in listed] == [
        ("Fortrus Limited", (Role.LEAD, Role.ADVISOR)),
        ("Trust B", (Role.ADVISOR,)),
    ]


async def test_a_tenant_that_is_not_active_is_not_offered() -> None:
    rows = [record(TENANT_A, Role.LEAD), record(TENANT_B, Role.ADVISOR)]
    listed = await choices(rows, tenant_status=TenantStatus.SUSPENDED).execute("good-token")
    assert [c.tenant_id for c in listed] == [TENANT_A]


async def test_no_tenant_and_a_forged_credential_are_the_same_refusal() -> None:
    with pytest.raises(ExchangeRefused):
        await choices([]).execute("good-token")
    with pytest.raises(ExchangeRefused):
        await choices([record(TENANT_A, Role.LEAD)]).execute("forged-token")
