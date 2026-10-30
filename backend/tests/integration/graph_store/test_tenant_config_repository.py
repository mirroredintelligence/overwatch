"""Neo4j round trips of a tenant's configuration records, and two tenants holding the same keys
(TEN-026, DEC-130 to DEC-132). Synthetic values only. Written in the build wave and run in the
verification stage (one Neo4j at a time); the statements themselves are also run, as tenant A and
as tenant B, by the generated test (test_tenant_isolation.py).

The labels are new, so no superseded single-property constraint applies and the shared harness
schema (with migration 0055) is enough: two tenants may hold the same version number, contact kind,
channel id, retention class, directory and group."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time
from typing import Any

import pytest
from neo4j import AsyncDriver, AsyncManagedTransaction

from diucs.adapters.outbound.graph_store.tenant_config_repository import (
    Neo4jTenantConfigRepository,
)
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, InvalidTransition, ValidationFailed
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    RetentionClass,
    TenantConfig,
    TenantContact,
)
from diucs.domain.model.tenant_records import (
    BindingStatus,
    ChannelKind,
    ChannelProvider,
    EntraBinding,
    MappingStatus,
    RetentionAction,
    RoleMapping,
    TenantChannel,
    TenantRetention,
)
from tests.support.neo4j import count_nodes, node_props, read_tx, write_tx
from tests.support.tenancy import as_tenant

pytestmark = pytest.mark.asyncio(loop_scope="session")

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
GUID = "11111111-2222-3333-4444-555555555555"
OTHER_GUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SID = "AC" + "0" * 32
VALUES: dict[str, Any] = {
    "replyWindowMinutes": 45,
    "reminderAfterMinutes": 45,
    "phoneTaskAfterMinutes": 75,
    "escalateAfterMinutes": 105,
    "systemName": "Example capacity",
    "twiceADaySecondTime": time(14, 30),
    "criticalAlertKinds": frozenset({"service-closed", "system-pressure"}),
}

Work = Callable[[Neo4jTenantConfigRepository], Awaitable[Any]]


async def _write(driver: AsyncDriver, tenant: str, work: Work) -> Any:
    async def run(tx: AsyncManagedTransaction) -> Any:
        return await work(Neo4jTenantConfigRepository(tx))

    with as_tenant(tenant):
        return await write_tx(driver, run)


async def _read(driver: AsyncDriver, tenant: str, work: Work) -> Any:
    async def run(tx: AsyncManagedTransaction) -> Any:
        return await work(Neo4jTenantConfigRepository(tx))

    with as_tenant(tenant):
        return await read_tx(driver, run)


def draft(version: int = 1, **changes: Any) -> TenantConfig:
    fields: dict[str, Any] = {
        "version": version,
        "status": ConfigStatus.DRAFT,
        "values": dict(VALUES),
        "created_at": T0,
        "created_by_ref": "prac-lead-1",
    }
    fields.update(changes)
    return TenantConfig(**fields)


# ---------------------------------------------------------------- versions


async def test_a_version_round_trips_with_every_kind_of_setting(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    config = draft()

    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(config))
    read = await _read(neo4j_driver, tenant_id, lambda repo: repo.get_version(1))

    assert read == config
    assert type(read.values["criticalAlertKinds"]) is frozenset
    assert read.values["twiceADaySecondTime"] == time(14, 30)
    props = await node_props(neo4j_driver, "TenantConfigVersion", version=1)
    assert props["tenantId"] == tenant_id
    assert props["status"] == "draft"
    assert await count_nodes(neo4j_driver, "TenantSetting") == len(VALUES)


async def test_settings_are_typed_rows_and_never_json(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(draft()))

    window = await node_props(neo4j_driver, "TenantSetting", key="replyWindowMinutes")
    codes = await node_props(neo4j_driver, "TenantSetting", key="criticalAlertKinds")
    clock = await node_props(neo4j_driver, "TenantSetting", key="twiceADaySecondTime")

    assert window["intValue"] == 45
    assert window["unit"] == "minutes"
    assert window["configVersion"] == 1
    assert codes["codeValues"] == ["service-closed", "system-pressure"]
    assert clock["timeValue"].hour == 14
    for props in (window, codes, clock):
        assert not any(isinstance(value, dict) for value in props.values())
        assert not any(
            isinstance(value, str) and value.startswith(("{", "[")) for value in props.values()
        )


async def test_the_next_version_number_is_the_only_one_that_can_be_added(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(draft(1)))

    for number in (1, 3):
        with pytest.raises(Conflict):
            await _write(neo4j_driver, tenant_id, lambda repo, n=number: repo.add_version(draft(n)))
    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.latest_version_number()) == 1
    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(draft(2)))
    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.latest_version_number()) == 2


async def test_only_a_draft_is_added(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    current = draft(status=ConfigStatus.CURRENT, effective_from=T1, approved_by_refs=("a-1",))

    with pytest.raises(ValidationFailed):
        await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(current))

    assert await count_nodes(neo4j_driver, "TenantConfigVersion") == 0


async def test_a_version_with_no_overrides_has_no_settings(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    empty = draft(values={})

    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(empty))

    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.get_version(1)) == empty
    assert await count_nodes(neo4j_driver, "TenantSetting") == 0


async def test_a_version_moves_through_its_statuses_and_the_current_one_is_found(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    first = draft()
    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(first))
    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.current_version()) is None
    pending = TenantConfig(
        version=1,
        status=ConfigStatus.PENDING_APPROVAL,
        values=dict(VALUES),
        created_at=T0,
        created_by_ref="prac-lead-1",
        approved_by_refs=("prac-owner-1",),
    )
    current = TenantConfig(
        version=1,
        status=ConfigStatus.CURRENT,
        values=dict(VALUES),
        created_at=T0,
        created_by_ref="prac-lead-1",
        effective_from=T1,
        approved_by_refs=("prac-owner-1", "prac-owner-2"),
    )

    moved_to_pending = await _write(
        neo4j_driver, tenant_id, lambda repo: repo.move_version(pending, ConfigStatus.DRAFT)
    )
    moved_to_current = await _write(
        neo4j_driver,
        tenant_id,
        lambda repo: repo.move_version(current, ConfigStatus.PENDING_APPROVAL),
    )

    assert (moved_to_pending, moved_to_current) == (True, True)
    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.current_version()) == current
    assert await count_nodes(neo4j_driver, "TenantSetting") == len(VALUES)


async def test_a_move_from_a_status_the_version_has_left_changes_nothing(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(draft()))
    pending = draft(status=ConfigStatus.PENDING_APPROVAL, approved_by_refs=("prac-owner-1",))
    await _write(
        neo4j_driver, tenant_id, lambda repo: repo.move_version(pending, ConfigStatus.DRAFT)
    )
    other = draft(status=ConfigStatus.PENDING_APPROVAL, approved_by_refs=("prac-owner-2",))

    stale = await _write(
        neo4j_driver, tenant_id, lambda repo: repo.move_version(other, ConfigStatus.DRAFT)
    )

    assert stale is False
    read = await _read(neo4j_driver, tenant_id, lambda repo: repo.get_version(1))
    assert read is not None
    assert read.approved_by_refs == ("prac-owner-1",)


async def test_an_illegal_move_is_refused_before_it_is_written(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(draft()))
    current = draft(status=ConfigStatus.CURRENT, effective_from=T1, approved_by_refs=("a-1",))

    with pytest.raises(InvalidTransition):
        await _write(
            neo4j_driver, tenant_id, lambda repo: repo.move_version(current, ConfigStatus.DRAFT)
        )

    read = await _read(neo4j_driver, tenant_id, lambda repo: repo.get_version(1))
    assert read is not None and read.status is ConfigStatus.DRAFT


async def test_two_approvers_at_once_move_the_version_once(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    """The move locks the version before it reads the status (lessons L73, L99): of two writers that
    both read `draft`, exactly one moves it and the other is told it had already moved."""
    import asyncio

    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(draft()))

    def pending(ref: str) -> TenantConfig:
        return draft(status=ConfigStatus.PENDING_APPROVAL, approved_by_refs=(ref,))

    results = await asyncio.gather(
        *(
            _write(
                neo4j_driver,
                tenant_id,
                lambda repo, ref=ref: repo.move_version(pending(ref), ConfigStatus.DRAFT),
            )
            for ref in ("prac-owner-1", "prac-owner-2", "prac-owner-3", "prac-owner-4")
        )
    )

    assert sorted(results) == [False, False, False, True]


# ---------------------------------------------------------------- the other records


async def test_a_contact_is_set_once_per_kind_and_a_second_put_changes_it(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    desk = TenantContact(ContactKind.COORDINATION_PHONE, "Coordination desk", "0300 123 4567")
    new_desk = TenantContact(ContactKind.COORDINATION_PHONE, "New desk", "0300 123 4568")
    support = TenantContact(ContactKind.SUPPORT_EMAIL, "Support", "support@example.test")

    for contact in (desk, support, new_desk):
        await _write(neo4j_driver, tenant_id, lambda repo, c=contact: repo.put_contact(c))

    contacts = await _read(neo4j_driver, tenant_id, lambda repo: repo.contacts())
    assert contacts == (new_desk, support)
    assert await count_nodes(neo4j_driver, "TenantContact") == 2


async def test_channels_round_trip_and_a_retired_channel_stays_as_history(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    sms = TenantChannel(
        id="ch-sms-1",
        kind=ChannelKind.SMS,
        provider=ChannelProvider.TWILIO,
        status=NumberStatus.ACTIVE,
        sender_label="Example capacity",
        account_sid=SID,
        secret_ref=f"twilio/{tenant_id}/auth-token",
    )
    mail = TenantChannel(
        id="ch-mail-1",
        kind=ChannelKind.EMAIL,
        provider=ChannelProvider.SMTP,
        status=NumberStatus.ACTIVE,
        sender_label="Example capacity",
        from_address="capacity@example.test",
        from_display_name="Example capacity",
    )
    retired = TenantChannel(
        id="ch-sms-1",
        kind=ChannelKind.SMS,
        provider=ChannelProvider.TWILIO,
        status=NumberStatus.RETIRED,
        sender_label="Example capacity",
        account_sid=SID,
        secret_ref=f"twilio/{tenant_id}/auth-token",
    )
    for channel in (sms, mail, retired):
        await _write(neo4j_driver, tenant_id, lambda repo, c=channel: repo.put_channel(c))

    channels = await _read(neo4j_driver, tenant_id, lambda repo: repo.channels())

    assert channels == (retired, mail)
    props = await node_props(neo4j_driver, "TenantChannel", id="ch-sms-1")
    assert "token" not in {key.lower() for key in props}
    assert props["secretRef"] == f"twilio/{tenant_id}/auth-token"


async def test_retention_rules_round_trip_one_per_class(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    bookings = TenantRetention(RetentionClass.BOOKINGS, 730, RetentionAction.DELETE)
    shorter = TenantRetention(RetentionClass.BOOKINGS, 365, RetentionAction.DELETE)
    audit = TenantRetention(RetentionClass.AUDIT_CHAIN, None, RetentionAction.KEEP)
    for rule in (bookings, audit, shorter):
        await _write(neo4j_driver, tenant_id, lambda repo, r=rule: repo.put_retention(r))

    rules = await _read(neo4j_driver, tenant_id, lambda repo: repo.retention())

    assert rules == (audit, shorter)
    assert await count_nodes(neo4j_driver, "TenantRetention") == 2


async def test_bindings_and_role_mappings_round_trip(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    pending = EntraBinding(GUID, BindingStatus.PENDING)
    verified = EntraBinding(GUID, BindingStatus.VERIFIED, T0, "operator-1")
    other = EntraBinding(OTHER_GUID, BindingStatus.REVOKED)
    lead = RoleMapping(GUID, Role.LEAD, MappingStatus.ACTIVE)
    retired = RoleMapping(GUID, Role.LEAD, MappingStatus.RETIRED)
    advisor = RoleMapping(OTHER_GUID, Role.ADVISOR, MappingStatus.ACTIVE)
    for binding in (pending, other, verified):
        await _write(neo4j_driver, tenant_id, lambda repo, b=binding: repo.put_binding(b))
    for mapping in (lead, advisor, retired):
        await _write(neo4j_driver, tenant_id, lambda repo, m=mapping: repo.put_role_mapping(m))

    bindings = await _read(neo4j_driver, tenant_id, lambda repo: repo.bindings())
    mappings = await _read(neo4j_driver, tenant_id, lambda repo: repo.role_mappings())

    assert bindings == (verified, other)
    assert mappings == (retired, advisor)


async def test_a_binding_that_is_no_longer_verified_loses_its_verifier(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    verified = EntraBinding(GUID, BindingStatus.VERIFIED, T0, "operator-1")
    revoked = EntraBinding(GUID, BindingStatus.REVOKED)
    for binding in (verified, revoked):
        await _write(neo4j_driver, tenant_id, lambda repo, b=binding: repo.put_binding(b))

    props = await node_props(neo4j_driver, "TenantEntraBinding", directoryId=GUID)

    assert props["status"] == "revoked"
    assert "verifiedAt" not in props and "verifiedByRef" not in props


async def test_a_node_the_domain_refuses_is_a_record_fault_and_not_a_default(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str
) -> None:
    async def plant(tx: AsyncManagedTransaction) -> None:
        await tx.run(
            "CREATE (:TenantContact {tenantId: $t, kind: 'nonsense', label: 'x', value: 'y'})",
            t=tenant_id,
        )

    await write_tx(neo4j_driver, plant)

    with pytest.raises(TenantRecordInvalid):
        await _read(neo4j_driver, tenant_id, lambda repo: repo.contacts())


# ---------------------------------------------------------------- two tenants


async def test_two_tenants_hold_the_same_keys_and_read_only_their_own(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    mine = draft(values={"systemName": "Tenant A capacity"})
    theirs = draft(values={"systemName": "Tenant B capacity"}, created_by_ref="prac-lead-9")
    desk_a = TenantContact(ContactKind.COORDINATION_PHONE, "A desk", "0300 123 4567")
    desk_b = TenantContact(ContactKind.COORDINATION_PHONE, "B desk", "0300 999 8888")
    rule_a = TenantRetention(RetentionClass.BOOKINGS, 100, RetentionAction.DELETE)
    rule_b = TenantRetention(RetentionClass.BOOKINGS, 200, RetentionAction.DELETE)
    group_a = RoleMapping(GUID, Role.LEAD, MappingStatus.ACTIVE)
    group_b = RoleMapping(GUID, Role.ADVISOR, MappingStatus.ACTIVE)

    for tenant, config, desk, rule, group in (
        (tenant_id, mine, desk_a, rule_a, group_a),
        (other_tenant_id, theirs, desk_b, rule_b, group_b),
    ):
        await _write(neo4j_driver, tenant, lambda repo, c=config: repo.add_version(c))
        await _write(neo4j_driver, tenant, lambda repo, c=desk: repo.put_contact(c))
        await _write(neo4j_driver, tenant, lambda repo, r=rule: repo.put_retention(r))
        await _write(neo4j_driver, tenant, lambda repo, g=group: repo.put_role_mapping(g))

    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.get_version(1)) == mine
    assert await _read(neo4j_driver, other_tenant_id, lambda repo: repo.get_version(1)) == theirs
    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.contacts()) == (desk_a,)
    assert await _read(neo4j_driver, other_tenant_id, lambda repo: repo.contacts()) == (desk_b,)
    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.retention()) == (rule_a,)
    assert await _read(neo4j_driver, other_tenant_id, lambda repo: repo.role_mappings()) == (
        group_b,
    )
    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.latest_version_number()) == 1


async def test_a_move_in_one_tenant_leaves_the_other_tenants_version_alone(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    for tenant in (tenant_id, other_tenant_id):
        await _write(neo4j_driver, tenant, lambda repo: repo.add_version(draft()))
    pending = draft(status=ConfigStatus.PENDING_APPROVAL, approved_by_refs=("prac-owner-1",))

    moved = await _write(
        neo4j_driver, tenant_id, lambda repo: repo.move_version(pending, ConfigStatus.DRAFT)
    )

    assert moved is True
    other = await _read(neo4j_driver, other_tenant_id, lambda repo: repo.get_version(1))
    assert other is not None and other.status is ConfigStatus.DRAFT
    assert other.approved_by_refs == ()


async def test_the_other_tenants_record_is_not_a_conflict_for_the_same_key(
    clean_graph: None, neo4j_driver: AsyncDriver, tenant_id: str, other_tenant_id: str
) -> None:
    """The first version of tenant B is number 1 whatever tenant A holds: the latest number is read
    inside the tenant, and the composite key is (tenant, version)."""
    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(draft(1)))
    await _write(neo4j_driver, tenant_id, lambda repo: repo.add_version(draft(2)))

    await _write(neo4j_driver, other_tenant_id, lambda repo: repo.add_version(draft(1)))

    assert (
        await _read(neo4j_driver, other_tenant_id, lambda repo: repo.latest_version_number()) == 1
    )
    assert await _read(neo4j_driver, tenant_id, lambda repo: repo.latest_version_number()) == 2
