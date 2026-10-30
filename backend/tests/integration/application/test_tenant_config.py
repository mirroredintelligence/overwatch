"""The tenant configuration use cases on a real Neo4j (TEN-026): a draft built from the version in
force, one approver for an operational change, two approvers who are not the author for a clinical
one, the version replaced in the same unit of work, the audit entry of every change, the read port,
and two tenants that never see each other's configuration. Synthetic values only. Written in the
build wave and run in the verification stage.

The configuration roles are passed in: the tenant administrator role does not exist yet (TEN-018),
so the default set is empty and every actor is refused (the unit tests hold that)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from neo4j import AsyncDriver

from diucs.adapters.testing.fixed_clock import FixedClock
from diucs.adapters.testing.fixed_ids import SequentialIds
from diucs.application.actor import Actor
from diucs.application.ports.outbound.unit_of_work import UnitOfWorkFactory
from diucs.application.use_cases.tenant_config import (
    ApproveConfigCommand,
    ApproveTenantConfig,
    BindDirectoryCommand,
    BindEntraDirectory,
    DraftConfigCommand,
    DraftTenantConfig,
    MapEntraGroup,
    MapGroupCommand,
    ReadTenantConfig,
    RecordChannelCommand,
    RecordContactCommand,
    RecordTenantChannel,
    RecordTenantContact,
    SetRetentionCommand,
    SetTenantRetention,
)
from diucs.domain.codes import Role
from diucs.domain.errors import (
    Conflict,
    InvalidTransition,
    NotAllowed,
    NotFound,
    ValidationFailed,
)
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    RetentionClass,
)
from diucs.domain.model.tenant_policy import DEFAULT_POLICY
from diucs.domain.model.tenant_records import (
    BindingStatus,
    ChannelKind,
    MappingStatus,
    default_retention,
)
from tests.support.neo4j import count_nodes
from tests.support.uow import ensure_audit_heads

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
ROLES = frozenset({Role.OWNER})
GUID = "11111111-2222-3333-4444-555555555555"
OTHER_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SID = "AC" + "0" * 32
WINDOW: dict[str, Any] = {
    "replyWindowMinutes": 45,
    "reminderAfterMinutes": 45,
    "phoneTaskAfterMinutes": 75,
    "escalateAfterMinutes": 105,
}
WORDING: dict[str, Any] = {
    "systemName": "Example capacity",
    "referralSystemName": "Example referrals",
    "coordinationTeamName": "Example team",
}


def person(ref: str) -> Actor:
    return Actor(
        role=Role.OWNER,
        practitioner_id=ref,
        device_id=None,
        channel="web",
        service_ids=frozenset(),
    )


LEAD = person("prac-lead-1")
OWNER_1 = person("prac-owner-1")
OWNER_2 = person("prac-owner-2")


@pytest.fixture
async def heads(
    neo4j_driver: AsyncDriver, clean_graph: None, tenant_id: str, other_tenant_id: str
) -> None:
    await ensure_audit_heads(neo4j_driver, tenant_id, other_tenant_id)


def draft_use_case(factory: UnitOfWorkFactory) -> DraftTenantConfig:
    return DraftTenantConfig(factory, FixedClock(NOW), ROLES)


def approve_use_case(factory: UnitOfWorkFactory) -> ApproveTenantConfig:
    return ApproveTenantConfig(factory, FixedClock(NOW), ROLES)


async def _draft(
    factory: UnitOfWorkFactory, based_on: int, changes: dict[str, Any], **extra: Any
) -> int:
    result = await draft_use_case(factory).execute(
        DraftConfigCommand(LEAD, based_on, changes, **extra)
    )
    return result.version


async def _in_force(factory: UnitOfWorkFactory, changes: dict[str, Any], based_on: int = 0) -> int:
    """A version approved by two people, as the first configuration of a tenant must be."""
    version = await _draft(factory, based_on, changes)
    await approve_use_case(factory).execute(ApproveConfigCommand(OWNER_1, version))
    await approve_use_case(factory).execute(ApproveConfigCommand(OWNER_2, version))
    return version


# ---------------------------------------------------------------- drafting


async def test_the_first_draft_needs_two_approvers_and_is_not_in_force(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    result = await draft_use_case(uow_factory_a).execute(
        DraftConfigCommand(LEAD, 0, {**WINDOW, **WORDING}, reason_code="first")
    )

    assert result.version == 1
    assert result.diff.approvals_required == 2
    assert result.diff.clinical_keys == tuple(sorted(WINDOW))
    async with uow_factory_a() as uow:
        assert await uow.tenant_config.current_version() is None
        stored = await uow.tenant_config.get_version(1)
    assert stored is not None
    assert stored.status is ConfigStatus.DRAFT
    assert stored.created_by_ref == "prac-lead-1"
    assert stored.reason_code == "first"


async def test_a_draft_that_breaks_a_setting_rule_writes_nothing(
    heads: None, uow_factory_a: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    for changes in ({"staleWarningHours": 9}, {"notASetting": 1}, {"replyWindowMinutes": 61}):
        with pytest.raises(ValidationFailed):
            await _draft(uow_factory_a, 0, changes)

    assert await count_nodes(neo4j_driver, "TenantConfigVersion") == 0
    assert await count_nodes(neo4j_driver, "AuditEvent") == 0


async def test_a_draft_written_against_a_version_that_is_no_longer_in_force_is_a_conflict(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    await _in_force(uow_factory_a, WINDOW)

    with pytest.raises(Conflict):
        await _draft(uow_factory_a, 0, {"staleWarningHours": 3})


async def test_a_draft_is_one_audit_entry_with_the_diff_and_no_value(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    await _draft(uow_factory_a, 0, {**WINDOW, **WORDING})

    async with uow_factory_a() as uow:
        records = await uow.audit.records()
    entry = records[-1].entry
    assert entry.use_case == "DraftTenantConfig"
    assert entry.action == "C"
    assert entry.entity_ids == ("config-1",)
    assert entry.snapshot is not None
    assert entry.snapshot["version"] == 1
    assert "systemName" in entry.snapshot["changedKeys"]
    assert "Example capacity" not in str(entry.snapshot)


# ---------------------------------------------------------------- approving


async def test_a_clinical_change_is_in_force_only_after_two_people_who_are_not_its_author(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    version = await _draft(uow_factory_a, 0, WINDOW)

    first = await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(OWNER_1, version))

    assert (first.status, first.approvals, first.approvals_required) == (
        ConfigStatus.PENDING_APPROVAL,
        1,
        2,
    )
    async with uow_factory_a() as uow:
        assert await uow.tenant_config.current_version() is None

    second = await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(OWNER_2, version))

    assert second.status is ConfigStatus.CURRENT
    async with uow_factory_a() as uow:
        current = await uow.tenant_config.current_version()
    assert current is not None
    assert current.version == 1
    assert current.approved_by_refs == ("prac-owner-1", "prac-owner-2")
    assert current.effective_from == NOW


async def test_the_author_cannot_approve_a_clinical_change_and_nothing_changes(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    version = await _draft(uow_factory_a, 0, WINDOW)

    with pytest.raises(NotAllowed):
        await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(LEAD, version))

    async with uow_factory_a() as uow:
        stored = await uow.tenant_config.get_version(version)
    assert stored is not None
    assert stored.status is ConfigStatus.DRAFT
    assert stored.approved_by_refs == ()


async def test_one_person_cannot_approve_twice(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    version = await _draft(uow_factory_a, 0, WINDOW)
    await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(OWNER_1, version))

    with pytest.raises(NotAllowed):
        await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(OWNER_1, version))


async def test_an_operational_change_needs_one_approver_and_replaces_the_version_in_force(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    await _in_force(uow_factory_a, WINDOW)
    version = await _draft(uow_factory_a, 1, {"alertDefaultNotUpdatedHours": 4})

    result = await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(LEAD, version))

    assert (result.status, result.approvals, result.approvals_required) == (
        ConfigStatus.CURRENT,
        1,
        1,
    )
    async with uow_factory_a() as uow:
        current = await uow.tenant_config.current_version()
        old = await uow.tenant_config.get_version(1)
    assert current is not None and current.version == 2
    assert current.values["alertDefaultNotUpdatedHours"] == 4
    assert current.values["replyWindowMinutes"] == 45
    assert old is not None and old.status is ConfigStatus.SUPERSEDED
    assert old.values == {**WINDOW}


async def test_only_one_version_is_in_force_after_a_series_of_changes(
    heads: None, uow_factory_a: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    await _in_force(uow_factory_a, WINDOW)
    for number, hours in ((2, 4), (3, 2)):
        version = await _draft(uow_factory_a, number - 1, {"alertDefaultNotUpdatedHours": hours})
        await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(LEAD, version))

    async with uow_factory_a() as uow:
        statuses = [(await uow.tenant_config.get_version(n)).status for n in (1, 2, 3)]  # type: ignore[union-attr]
    assert statuses == [ConfigStatus.SUPERSEDED, ConfigStatus.SUPERSEDED, ConfigStatus.CURRENT]
    assert await count_nodes(neo4j_driver, "TenantConfigVersion") == 3


async def test_only_the_latest_version_can_be_approved(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    """A draft written against an older version must never revert a newer one."""
    await _in_force(uow_factory_a, WINDOW)
    stale = await _draft(uow_factory_a, 1, {"alertDefaultNotUpdatedHours": 4})
    newer = await _draft(uow_factory_a, 1, {"staleWarningHours": 3})

    with pytest.raises(Conflict):
        await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(LEAD, stale))

    assert newer == stale + 1
    async with uow_factory_a() as uow:
        stored = await uow.tenant_config.get_version(stale)
    assert stored is not None and stored.status is ConfigStatus.DRAFT


async def test_an_unknown_or_an_approved_version_cannot_be_approved(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    version = await _in_force(uow_factory_a, WINDOW)

    with pytest.raises(NotFound):
        await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(LEAD, 9))
    with pytest.raises(InvalidTransition):
        await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(OWNER_1, version))


async def test_an_approval_is_one_audit_entry(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    version = await _draft(uow_factory_a, 0, WINDOW)
    await approve_use_case(uow_factory_a).execute(ApproveConfigCommand(OWNER_1, version))

    async with uow_factory_a() as uow:
        records = await uow.audit.records()
    entry = records[-1].entry
    assert (entry.use_case, entry.action) == ("ApproveTenantConfig", "U")
    assert entry.snapshot is not None
    assert entry.snapshot["status"] == "pending-approval"
    assert entry.snapshot["approvals"] == 1


# ---------------------------------------------------------------- the read port


async def test_a_tenant_with_nothing_in_force_has_the_default_policy_and_no_wording(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    reader = ReadTenantConfig(uow_factory_a)

    assert await reader.policy() == DEFAULT_POLICY
    assert await reader.wording() is None


async def test_the_read_port_gives_the_policy_and_wording_in_force(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    await _in_force(uow_factory_a, {**WINDOW, **WORDING})
    reader = ReadTenantConfig(uow_factory_a)

    policy = await reader.policy()
    wording = await reader.wording()

    assert policy.reply_window.total_seconds() == 45 * 60
    assert wording is not None
    assert wording.system_name == "Example capacity"


async def test_a_draft_is_not_read_as_the_policy(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    await _draft(uow_factory_a, 0, WINDOW)

    assert await ReadTenantConfig(uow_factory_a).policy() == DEFAULT_POLICY


async def test_two_tenants_have_their_own_configuration(
    heads: None, uow_factory_a: UnitOfWorkFactory, uow_factory_b: UnitOfWorkFactory
) -> None:
    await _in_force(uow_factory_a, {**WINDOW, **WORDING})

    assert (await ReadTenantConfig(uow_factory_b).policy()) == DEFAULT_POLICY
    assert await ReadTenantConfig(uow_factory_b).wording() is None
    version_b = await _draft(uow_factory_b, 0, {"staleWarningHours": 3})
    assert version_b == 1
    with pytest.raises(NotFound):
        await approve_use_case(uow_factory_b).execute(ApproveConfigCommand(OWNER_1, 2))


# ----------------------------------------------- contacts, channels, retention, the directory


async def test_a_contact_is_set_audited_and_read_back(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    await RecordTenantContact(uow_factory_a, FixedClock(NOW), ROLES).execute(
        RecordContactCommand(LEAD, ContactKind.COORDINATION_PHONE, "Desk", "0300 123 4567")
    )

    contacts = await ReadTenantConfig(uow_factory_a).contacts()

    assert [(c.kind, c.value) for c in contacts] == [
        (ContactKind.COORDINATION_PHONE, "0300 123 4567")
    ]
    async with uow_factory_a() as uow:
        assert (await uow.audit.records())[-1].entry.use_case == "RecordTenantContact"


async def test_a_text_channel_names_its_own_tenants_secret_and_no_other(
    heads: None, uow_factory_a: UnitOfWorkFactory, tenant_id: str, other_tenant_id: str
) -> None:
    use_case = RecordTenantChannel(uow_factory_a, FixedClock(NOW), SequentialIds("ch"), ROLES)

    with pytest.raises(ValidationFailed):
        await use_case.execute(
            RecordChannelCommand(
                LEAD,
                ChannelKind.SMS,
                "Example capacity",
                account_sid=SID,
                secret_ref=f"twilio/{other_tenant_id}/auth-token",
            )
        )
    channel_id = await use_case.execute(
        RecordChannelCommand(
            LEAD,
            ChannelKind.SMS,
            "Example capacity",
            account_sid=SID,
            secret_ref=f"twilio/{tenant_id}/auth-token",
        )
    )

    async with uow_factory_a() as uow:
        channels = await uow.tenant_config.channels()
    assert [c.id for c in channels] == [channel_id]
    assert channels[0].status is NumberStatus.ACTIVE


async def test_a_channel_is_retired_by_recording_it_again_with_its_id(
    heads: None, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    use_case = RecordTenantChannel(uow_factory_a, FixedClock(NOW), SequentialIds("ch"), ROLES)
    base: dict[str, Any] = {
        "kind": ChannelKind.EMAIL,
        "sender_label": "Example capacity",
        "from_address": "capacity@example.test",
    }
    channel_id = await use_case.execute(RecordChannelCommand(LEAD, **base))

    await use_case.execute(
        RecordChannelCommand(LEAD, channel_id=channel_id, status=NumberStatus.RETIRED, **base)
    )

    async with uow_factory_a() as uow:
        channels = await uow.tenant_config.channels()
    assert [(c.id, c.status) for c in channels] == [(channel_id, NumberStatus.RETIRED)]


async def test_the_default_retention_is_stored_one_rule_per_class(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    stored = await SetTenantRetention(uow_factory_a, FixedClock(NOW), ROLES).execute(
        SetRetentionCommand(LEAD, use_defaults=True)
    )

    facts = await ReadTenantConfig(uow_factory_a).facts()

    assert stored == len(RetentionClass)
    assert facts.retention_classes_set == frozenset(RetentionClass)
    async with uow_factory_a() as uow:
        assert set(await uow.tenant_config.retention()) == set(default_retention())


async def test_binding_a_directory_then_another_revokes_the_first(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    use_case = BindEntraDirectory(uow_factory_a, FixedClock(NOW), ROLES)

    await use_case.execute(BindDirectoryCommand(LEAD, GUID))
    await use_case.execute(BindDirectoryCommand(LEAD, GUID))  # the same directory: nothing changes
    await use_case.execute(BindDirectoryCommand(LEAD, OTHER_GUID))

    async with uow_factory_a() as uow:
        bindings = {b.directory_id: b.status for b in await uow.tenant_config.bindings()}
    assert bindings == {GUID: BindingStatus.REVOKED, OTHER_GUID: BindingStatus.PENDING}
    assert (await ReadTenantConfig(uow_factory_a).facts()).entra_binding_verified is False


async def test_a_group_is_mapped_to_a_staff_role_and_counted(
    heads: None, uow_factory_a: UnitOfWorkFactory
) -> None:
    use_case = MapEntraGroup(uow_factory_a, FixedClock(NOW), ROLES)
    await use_case.execute(MapGroupCommand(LEAD, GUID, Role.LEAD))
    await use_case.execute(MapGroupCommand(LEAD, OTHER_GUID, Role.ADVISOR))
    await use_case.execute(MapGroupCommand(LEAD, OTHER_GUID, Role.ADVISOR, MappingStatus.RETIRED))

    facts = await ReadTenantConfig(uow_factory_a).facts()

    assert facts.role_mappings == 1
    with pytest.raises(ValidationFailed):
        await use_case.execute(MapGroupCommand(LEAD, GUID, Role.SUPPORT))


async def test_the_facts_of_a_ready_tenant_are_all_true(
    heads: None, uow_factory_a: UnitOfWorkFactory, tenant_id: str
) -> None:
    await _in_force(uow_factory_a, {**WINDOW, **WORDING})
    clock = FixedClock(NOW)
    for kind, label, value in (
        (ContactKind.COORDINATION_PHONE, "Desk", "0300 123 4567"),
        (ContactKind.CLINICAL_SAFETY_OFFICER, "Safety desk", "0300 123 4568"),
    ):
        await RecordTenantContact(uow_factory_a, clock, ROLES).execute(
            RecordContactCommand(LEAD, kind, label, value)
        )
    await RecordTenantChannel(uow_factory_a, clock, SequentialIds("ch"), ROLES).execute(
        RecordChannelCommand(
            LEAD,
            ChannelKind.SMS,
            "Example capacity",
            account_sid=SID,
            secret_ref=f"twilio/{tenant_id}/auth-token",
        )
    )
    await SetTenantRetention(uow_factory_a, clock, ROLES).execute(
        SetRetentionCommand(LEAD, use_defaults=True)
    )
    await MapEntraGroup(uow_factory_a, clock, ROLES).execute(MapGroupCommand(LEAD, GUID, Role.LEAD))

    facts = await ReadTenantConfig(uow_factory_a).facts()

    assert facts.config_approved and facts.wording_complete
    assert facts.contact_kinds == {
        ContactKind.COORDINATION_PHONE,
        ContactKind.CLINICAL_SAFETY_OFFICER,
    }
    assert facts.retention_classes_set == frozenset(RetentionClass)
    assert (facts.role_mappings, facts.active_sms_channels, facts.active_email_channels) == (
        1,
        1,
        0,
    )


async def test_every_change_by_a_role_off_the_list_leaves_the_graph_untouched(
    heads: None, uow_factory_a: UnitOfWorkFactory, neo4j_driver: AsyncDriver
) -> None:
    advisor = Actor(Role.ADVISOR, "prac-advisor-1", None, "web", frozenset())

    with pytest.raises(NotAllowed):
        await DraftTenantConfig(uow_factory_a, FixedClock(NOW), ROLES).execute(
            DraftConfigCommand(advisor, 0, dict(WINDOW))
        )
    with pytest.raises(NotAllowed):
        await DraftTenantConfig(uow_factory_a, FixedClock(NOW)).execute(
            DraftConfigCommand(LEAD, 0, dict(WINDOW))
        )

    assert await count_nodes(neo4j_driver, "TenantConfigVersion") == 0
