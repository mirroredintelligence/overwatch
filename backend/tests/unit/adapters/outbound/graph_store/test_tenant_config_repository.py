"""The statements and the row mapping of a tenant's configuration on Neo4j (TEN-026).

Every statement is a registered `NamedQuery` that writes `tenantId: $tenant` on each node it
matches, merges or creates, and carries a scenario for the generated two-tenant test (DEC-142,
DEC-150). This file reads the statement text and the pure mapping; the behaviour against a real
graph is in tests/integration/graph_store/test_tenant_config_repository.py and the generated test.
Values are invented.
"""

import re
from datetime import UTC, datetime, time
from typing import Any

import pytest

from diucs.adapters.outbound.graph_store.queries import _NODE_PATTERN, REGISTRY
from diucs.adapters.outbound.graph_store.scenario import validate_scenario
from diucs.adapters.outbound.graph_store.tenant_config_repository import (
    CONFIG_QUERY_IDS,
    binding_from_props,
    binding_params,
    channel_from_props,
    channel_params,
    contact_from_props,
    contact_params,
    mapping_from_props,
    mapping_params,
    retention_from_props,
    retention_params,
    setting_row,
    values_from_rows,
    version_from_props,
    version_props,
)
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.domain.codes import Role
from diucs.domain.errors import ValidationFailed
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

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 29, 9, 30, tzinfo=UTC)
GUID = "11111111-2222-3333-4444-555555555555"

EXPECTED_IDS = {
    "Q-TCFG-ADD-VERSION": "write",
    "Q-TCFG-ADD-SETTINGS": "write",
    "Q-TCFG-GET": "read",
    "Q-TCFG-CURRENT": "read",
    "Q-TCFG-SETTINGS": "read",
    "Q-TCFG-LATEST": "read",
    "Q-TCFG-MOVE": "write",
    "Q-TCONTACT-PUT": "write",
    "Q-TCONTACT-LIST": "read",
    "Q-TCHANNEL-PUT": "write",
    "Q-TCHANNEL-LIST": "read",
    "Q-TRETENTION-PUT": "write",
    "Q-TRETENTION-LIST": "read",
    "Q-TBINDING-PUT": "write",
    "Q-TBINDING-LIST": "read",
    "Q-TMAPPING-PUT": "write",
    "Q-TMAPPING-LIST": "read",
}

# ---------------------------------------------------------------- the statements


def test_the_module_registers_exactly_the_documented_statements() -> None:
    assert set(CONFIG_QUERY_IDS) == set(EXPECTED_IDS)
    assert len(CONFIG_QUERY_IDS) == len(set(CONFIG_QUERY_IDS))
    for query_id in CONFIG_QUERY_IDS:
        assert query_id in REGISTRY.ids()


@pytest.mark.parametrize("query_id", sorted(EXPECTED_IDS))
def test_each_statement_is_a_tenant_statement_with_a_scenario(query_id: str) -> None:
    query = REGISTRY.get(query_id)

    assert query.scope == "tenant"
    assert query.mode == EXPECTED_IDS[query_id]
    assert query.scenario is not None
    assert validate_scenario(query_id, query.scenario) == []
    assert query_id not in REGISTRY.ratchet_ids()


@pytest.mark.parametrize("query_id", sorted(EXPECTED_IDS))
def test_every_node_of_every_statement_carries_the_tenant(query_id: str) -> None:
    cypher = REGISTRY.get(query_id).cypher
    # `properties(v)` and `count(c)` read as a node pattern; a name right before the bracket is a
    # function call, not a node. A bare `(v)` is a reference to a node matched earlier in the
    # statement, whose own pattern is checked.
    nodes = [
        node
        for node in _NODE_PATTERN.finditer(cypher)
        if (
            node.start() == 0
            or not (cypher[node.start() - 1].isalnum() or cypher[node.start() - 1] == "_")
        )
        and re.fullmatch(r"\(\s*\w+\s*\)", node.group(0)) is None
    ]

    assert nodes, query_id
    for node in nodes:
        assert "tenantId: $tenant" in node.group(0), (query_id, node.group(0))


@pytest.mark.parametrize("query_id", sorted(EXPECTED_IDS))
def test_a_read_writes_nothing_and_a_write_is_not_a_read(query_id: str) -> None:
    cypher = REGISTRY.get(query_id).cypher
    writes = re.search(r"\b(CREATE|MERGE|SET|DELETE|REMOVE)\b", cypher) is not None

    assert writes is (EXPECTED_IDS[query_id] == "write")


@pytest.mark.parametrize("query_id", sorted(EXPECTED_IDS))
def test_no_statement_names_a_registry_label_or_builds_its_text(query_id: str) -> None:
    cypher = REGISTRY.get(query_id).cypher

    for label in ("Tenant)", ":Tenant ", "TenantNumber", "Network", "Grant"):
        assert label not in cypher
    assert "{" in cypher or "UNWIND" in cypher
    assert "%s" not in cypher and "{0}" not in cypher


def test_every_graph_key_is_the_tenant_and_the_key_of_the_record() -> None:
    puts = {
        "Q-TCONTACT-PUT": "MERGE (c:TenantContact {kind: $kind, tenantId: $tenant})",
        "Q-TCHANNEL-PUT": "MERGE (c:TenantChannel {id: $id, tenantId: $tenant})",
        "Q-TRETENTION-PUT": "MERGE (r:TenantRetention {dataClass: $dataClass, tenantId: $tenant})",
        "Q-TBINDING-PUT": (
            "MERGE (b:TenantEntraBinding {directoryId: $directoryId, tenantId: $tenant})"
        ),
        "Q-TMAPPING-PUT": (
            "MERGE (m:TenantRoleMapping {groupObjectId: $groupObjectId, tenantId: $tenant})"
        ),
    }
    for query_id, merge in puts.items():
        assert merge in REGISTRY.get(query_id).cypher, query_id


def test_a_version_is_created_not_merged_and_its_settings_hang_from_it() -> None:
    add = REGISTRY.get("Q-TCFG-ADD-VERSION").cypher
    settings = REGISTRY.get("Q-TCFG-ADD-SETTINGS").cypher

    assert add.startswith("CREATE (v:TenantConfigVersion {")
    assert "MERGE" not in add
    assert "UNWIND $settings AS s" in settings
    assert "MATCH (v:TenantConfigVersion {version: $version, tenantId: $tenant})" in settings
    assert "-[:HAS_SETTING]->" in settings
    assert "TenantSetting {tenantId: $tenant, configVersion: $version, key: s.key" in settings


def test_a_status_move_locks_the_version_before_it_reads_the_status() -> None:
    """Two approvers at once: the second must see the first's committed status (lessons L73,
    L99). The match is by key only, the lock is a self-set, and the status is read after it."""
    cypher = REGISTRY.get("Q-TCFG-MOVE").cypher
    match = cypher.split("SET", 1)[0]

    assert "status" not in match
    assert cypher.index("SET v.version = v.version") < cypher.index("WHERE v.status = $expected")
    assert "SET v.status = $status" in cypher
    assert "RETURN count(v) AS moved" in cypher


def test_an_old_version_is_never_edited_by_any_statement() -> None:
    """Only the move statement sets anything on a version, and it sets its status and approvals."""
    for query_id, cypher in ((i, REGISTRY.get(i).cypher) for i in CONFIG_QUERY_IDS):
        if "TenantConfigVersion" not in cypher or re.search(r"\bSET\b", cypher) is None:
            continue
        assert query_id == "Q-TCFG-MOVE"
        assigned = set(re.findall(r"SET (?:v\.\w+ = [^,]+(?:, )?)+", cypher))
        assert all("createdAt" not in text and "createdByRef" not in text for text in assigned)


def test_the_latest_statement_also_counts_so_a_missing_predicate_shows() -> None:
    cypher = REGISTRY.get("Q-TCFG-LATEST").cypher

    assert "coalesce(max(v.version), 0) AS latest" in cypher
    assert "count(v) AS versions" in cypher


def test_no_read_of_a_unique_key_is_limited() -> None:
    for query_id in ("Q-TCFG-GET", "Q-TCFG-SETTINGS", "Q-TCONTACT-LIST", "Q-TCHANNEL-LIST"):
        assert "LIMIT" not in REGISTRY.get(query_id).cypher
    assert "LIMIT 1" in REGISTRY.get("Q-TCFG-CURRENT").cypher
    assert "ORDER BY v.version DESC" in REGISTRY.get("Q-TCFG-CURRENT").cypher


# ---------------------------------------------------------------- settings


def test_an_integer_setting_is_stored_in_its_unit_in_one_typed_column() -> None:
    row = setting_row("replyWindowMinutes", 45)

    assert row == {
        "key": "replyWindowMinutes",
        "unit": "minutes",
        "intValue": 45,
        "textValue": None,
        "boolValue": None,
        "timeValue": None,
        "codeValues": None,
    }


def test_a_text_setting_a_time_setting_and_a_codes_setting_each_use_their_column() -> None:
    text = setting_row("systemName", "Example capacity")
    clock = setting_row("twiceADaySecondTime", time(14, 0))
    codes = setting_row("criticalAlertKinds", frozenset({"system-pressure", "service-closed"}))

    assert (text["textValue"], text["unit"]) == ("Example capacity", "text")
    assert clock["timeValue"] == time(14, 0)
    assert codes["codeValues"] == ["service-closed", "system-pressure"]
    for row in (text, clock, codes):
        assert (
            sum(
                row[name] is not None
                for name in ("intValue", "textValue", "boolValue", "timeValue", "codeValues")
            )
            == 1
        )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("notASetting", 1),
        ("replyWindowMinutes", "45"),
        ("replyWindowMinutes", True),
        ("replyWindowMinutes", 5),
        ("replyWindowMinutes", 61),
        ("systemName", ""),
        ("systemName", "<b>"),
        ("criticalAlertKinds", frozenset({"nonsense"})),
    ],
)
def test_a_setting_the_registry_refuses_is_never_written(key: str, value: object) -> None:
    with pytest.raises(ValidationFailed):
        setting_row(key, value)  # type: ignore[arg-type]


def test_rows_read_back_to_the_values_that_were_written() -> None:
    values: dict[str, Any] = {
        "replyWindowMinutes": 45,
        "reminderAfterMinutes": 45,
        "phoneTaskAfterMinutes": 75,
        "escalateAfterMinutes": 105,
        "systemName": "Example capacity",
        "twiceADaySecondTime": time(14, 30),
        "criticalAlertKinds": frozenset({"service-closed"}),
    }

    rows = [setting_row(key, value) for key, value in values.items()]
    read = values_from_rows(rows)

    assert read == values
    assert type(read["criticalAlertKinds"]) is frozenset


def test_a_damaged_setting_row_is_a_record_fault_not_a_default() -> None:
    good = setting_row("replyWindowMinutes", 45)
    for damaged in (
        {**good, "intValue": None},
        {**good, "intValue": "45"},
        {**good, "key": "notASetting"},
        {**good, "intValue": 999},
        {**good, "textValue": "x"},
        {k: v for k, v in good.items() if k != "key"},
    ):
        with pytest.raises(TenantRecordInvalid):
            values_from_rows([damaged])


def test_two_rows_for_one_key_are_a_record_fault() -> None:
    row = setting_row("replyWindowMinutes", 45)

    with pytest.raises(TenantRecordInvalid):
        values_from_rows([row, row])


# ---------------------------------------------------------------- versions


def sample_config(**changes: Any) -> TenantConfig:
    fields: dict[str, Any] = {
        "version": 2,
        "status": ConfigStatus.CURRENT,
        "values": {
            "replyWindowMinutes": 45,
            "reminderAfterMinutes": 45,
            "phoneTaskAfterMinutes": 75,
            "escalateAfterMinutes": 105,
        },
        "created_at": T0,
        "created_by_ref": "prac-lead-1",
        "effective_from": T1,
        "approved_by_refs": ("prac-owner-1", "prac-owner-2"),
        "reason_code": "winter-change",
    }
    fields.update(changes)
    return TenantConfig(**fields)


def test_a_version_has_the_documented_properties_and_no_tenant_or_values() -> None:
    props = version_props(sample_config())

    assert props == {
        "version": 2,
        "status": "current",
        "createdAt": T0,
        "createdByRef": "prac-lead-1",
        "effectiveFrom": T1,
        "approvedByRefs": ["prac-owner-1", "prac-owner-2"],
        "reasonCode": "winter-change",
    }
    assert "tenantId" not in props


def test_a_draft_has_no_effective_time() -> None:
    props = version_props(
        sample_config(status=ConfigStatus.DRAFT, effective_from=None, approved_by_refs=())
    )

    assert props["effectiveFrom"] is None
    assert props["approvedByRefs"] == []


def test_a_version_reads_back_equal() -> None:
    config = sample_config()

    read = version_from_props(version_props(config), dict(config.values))

    assert read == config


def test_a_version_read_from_the_graph_is_in_utc() -> None:
    class _Native:
        def __init__(self, value: datetime) -> None:
            self._value = value

        def to_native(self) -> datetime:
            return self._value

    props = version_props(sample_config())
    props["createdAt"] = _Native(T0)
    props["effectiveFrom"] = _Native(T1)

    read = version_from_props(props, dict(sample_config().values))

    assert read.created_at == T0
    assert read.effective_from == T1
    assert read.created_at.utcoffset() is not None


def test_a_missing_empty_list_reads_as_no_approvers() -> None:
    config = sample_config(status=ConfigStatus.DRAFT, effective_from=None, approved_by_refs=())
    props = version_props(config)
    del props["approvedByRefs"]  # Neo4j keeps an empty list, but a node written by hand may not

    assert version_from_props(props, dict(config.values)) == config


@pytest.mark.parametrize(
    "damage",
    [
        {"status": "live"},
        {"status": None},
        {"version": "2"},
        {"version": 0},
        {"createdAt": "2026-10-29"},
        {"createdByRef": None},
        {"createdByRef": "bad ref!"},
        {"approvedByRefs": "prac-owner-1"},
        {"approvedByRefs": "abc"},  # a string is not a list of refs, whatever its letters
        {"approvedByRefs": ["a", "a"]},
        {"reasonCode": 5},
    ],
)
def test_a_damaged_version_is_a_record_fault_with_a_fixed_message(damage: dict[str, Any]) -> None:
    props = {**version_props(sample_config()), **damage}

    with pytest.raises(TenantRecordInvalid) as refused:
        version_from_props(props, dict(sample_config().values))

    assert "prac" not in str(refused.value)


def test_a_current_version_with_no_effective_time_is_a_record_fault() -> None:
    props = {**version_props(sample_config()), "effectiveFrom": None}

    with pytest.raises(TenantRecordInvalid):
        version_from_props(props, dict(sample_config().values))


# ---------------------------------------------------------------- the other records


def test_a_contact_round_trips() -> None:
    contact = TenantContact(ContactKind.COORDINATION_PHONE, "Coordination desk", "0300 123 4567")

    assert contact_params(contact) == {
        "kind": "coordination-phone",
        "label": "Coordination desk",
        "value": "0300 123 4567",
    }
    assert contact_from_props(contact_params(contact)) == contact


def test_a_damaged_contact_is_a_record_fault() -> None:
    good = contact_params(
        TenantContact(ContactKind.SUPPORT_EMAIL, "Support", "support@example.test")
    )
    for damage in ({"kind": "unknown"}, {"value": "not an address"}, {"label": ""}, {"kind": None}):
        with pytest.raises(TenantRecordInvalid):
            contact_from_props({**good, **damage})


def test_a_text_channel_round_trips() -> None:
    channel = TenantChannel(
        id="ch-1",
        kind=ChannelKind.SMS,
        provider=ChannelProvider.TWILIO,
        status=NumberStatus.QUARANTINED,
        sender_label="Example capacity",
        account_sid="AC" + "1" * 32,
        secret_ref="twilio/example-icb/auth-token",
    )

    params = channel_params(channel)

    assert params == {
        "id": "ch-1",
        "kind": "sms",
        "provider": "twilio",
        "status": "quarantined",
        "senderLabel": "Example capacity",
        "accountSid": "AC" + "1" * 32,
        "secretRef": "twilio/example-icb/auth-token",
        "fromAddress": None,
        "fromDisplayName": None,
    }
    assert channel_from_props({k: v for k, v in params.items() if v is not None}) == channel


def test_an_email_channel_round_trips_and_a_damaged_one_is_a_record_fault() -> None:
    channel = TenantChannel(
        id="ch-2",
        kind=ChannelKind.EMAIL,
        provider=ChannelProvider.SMTP,
        status=NumberStatus.ACTIVE,
        sender_label="Example capacity",
        from_address="capacity@example.test",
        from_display_name="Example capacity",
    )
    params = {k: v for k, v in channel_params(channel).items() if v is not None}

    assert channel_from_props(params) == channel
    for damage in ({"provider": "twilio"}, {"status": "on"}, {"fromAddress": "x"}, {"kind": 1}):
        with pytest.raises(TenantRecordInvalid):
            channel_from_props({**params, **damage})


def test_a_retention_rule_round_trips() -> None:
    rules = (
        TenantRetention(RetentionClass.BOOKINGS, 730, RetentionAction.DELETE),
        TenantRetention(RetentionClass.AUDIT_CHAIN, None, RetentionAction.KEEP),
    )

    for rule in rules:
        params = retention_params(rule)
        assert retention_from_props({k: v for k, v in params.items() if v is not None}) == rule
    assert retention_params(rules[1]) == {
        "dataClass": "audit-chain",
        "keepDays": None,
        "action": "keep",
    }


def test_a_damaged_retention_rule_is_a_record_fault() -> None:
    good = {"dataClass": "bookings", "keepDays": 730, "action": "delete"}
    for damage in (
        {"dataClass": "mystery"},
        {"keepDays": 0},
        {"keepDays": "730"},
        {"action": "keep"},
        {"action": "shred"},
    ):
        with pytest.raises(TenantRecordInvalid):
            retention_from_props({**good, **damage})


def test_a_binding_round_trips() -> None:
    pending = EntraBinding(GUID, BindingStatus.PENDING)
    verified = EntraBinding(GUID, BindingStatus.VERIFIED, T0, "operator-1")

    assert binding_params(pending) == {
        "directoryId": GUID,
        "status": "pending",
        "verifiedAt": None,
        "verifiedByRef": None,
    }
    assert binding_from_props({"directoryId": GUID, "status": "pending"}) == pending
    assert binding_from_props(binding_params(verified)) == verified


def test_a_damaged_binding_is_a_record_fault() -> None:
    for props in (
        {"directoryId": "x", "status": "pending"},
        {"directoryId": GUID, "status": "verified"},
        {"directoryId": GUID, "status": "pending", "verifiedByRef": "operator-1"},
        {"directoryId": GUID, "status": "gone"},
    ):
        with pytest.raises(TenantRecordInvalid):
            binding_from_props(props)


def test_a_role_mapping_round_trips_and_a_damaged_one_is_a_record_fault() -> None:
    mapping = RoleMapping(GUID, Role.LEAD, MappingStatus.ACTIVE)

    assert mapping_params(mapping) == {"groupObjectId": GUID, "role": "lead", "status": "active"}
    assert mapping_from_props(mapping_params(mapping)) == mapping
    for damage in ({"role": "support"}, {"role": "nope"}, {"status": "on"}, {"groupObjectId": "x"}):
        with pytest.raises(TenantRecordInvalid):
            mapping_from_props({**mapping_params(mapping), **damage})
