"""A tenant's configuration records on Neo4j (TEN-026, DEC-130 to DEC-132, DEC-134 item 14).

The records live in the tenant's own scope: every node carries `tenantId`, and every statement is a
registered `NamedQuery` that matches and creates it with `tenantId: $tenant`. A tenant's record is
never read by another tenant, and the tenant registry (`Tenant`, `TenantNumber`, which carry no
tenantId) is not touched here.

- `(:TenantConfigVersion {tenantId, version, status, createdAt, createdByRef, effectiveFrom,
  approvedByRefs, reasonCode})-[:HAS_SETTING]->(:TenantSetting {tenantId, configVersion, key, unit,
  intValue | textValue | boolValue | timeValue | codeValues})`. A version is immutable once it is
  current: the only statement that changes a version's node sets its status, approvers and
  effective time, and a setting is written once with its version. The settings are typed rows,
  one column each, never JSON (DEC-001).
- `TenantContact {kind}`, `TenantChannel {id}`, `TenantRetention {dataClass}`,
  `TenantEntraBinding {directoryId}` and `TenantRoleMapping {groupObjectId}`: one node per key and
  tenant (composite constraints, migration 0055).

A secret is never stored, only the reference of its entry in the secret store (DEC-131 item 4). A
node the domain refuses when it is read is `TenantRecordInvalid` with a fixed message, never a
default and never a guess (fail closed).
"""

from datetime import UTC, datetime
from typing import Any, Final, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.scenario import (
    Expect,
    Marked,
    NodeSpec,
    Scenario,
    SeedNode,
    SeedRel,
    TenantSeed,
)
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.domain.codes import Role
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.model.tenant import (
    ConfigStatus,
    ContactKind,
    NumberStatus,
    RetentionClass,
    TenantConfig,
    TenantContact,
)
from diucs.domain.model.tenant_policy import SettingValue
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
from diucs.domain.rules.tenant_lifecycle import transition_config
from diucs.domain.rules.tenant_settings import SettingKind, spec_for, validate_value

RECORD_MESSAGE: Final = "a tenant configuration record is not valid"
VALUE_COLUMNS: Final = ("intValue", "textValue", "boolValue", "timeValue", "codeValues")

# ------------------------------------------------------------ scenarios (DEC-142 item 5, DEC-150)
#
# Both tenants hold the same keys and the same plain values, so a statement that forgets its
# tenant predicate finds the other tenant's node by key; the text that differs between them is
# `Marked`. A put is proved as an update of the tenant's own record: a lookup must be a value the
# seed holds, so a create cannot be proved with a key of its own (DEC-229 item 3).

_T: Final = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
_T2: Final = datetime(2026, 10, 25, 12, 30, tzinfo=UTC)
_GROUP: Final = "22222222-2222-2222-2222-222222222222"
_DIRECTORY: Final = "11111111-1111-1111-1111-111111111111"
_SID: Final = "AC" + "0" * 32


def _version(ref: str, number: int, status: str, approvers: list[str]) -> SeedNode:
    return SeedNode(
        ref,
        ("TenantConfigVersion",),
        {
            "version": number,
            "status": status,
            "createdAt": _T,
            "createdByRef": Marked("author"),
            "approvedByRefs": approvers,
            "reasonCode": "initial",
        },
    )


_CURRENT_SEED: Final = TenantSeed(nodes=(_version("v", 1, "current", ["ref-1", "ref-2"]),))
_PENDING_SEED: Final = TenantSeed(nodes=(_version("v", 1, "pending-approval", ["ref-1"]),))
_TWO_VERSIONS_SEED: Final = TenantSeed(
    nodes=(
        _version("v1", 1, "superseded", ["ref-1"]),
        _version("v2", 2, "current", ["ref-1", "ref-2"]),
    )
)
_SETTING: Final = SeedNode(
    "s",
    ("TenantSetting",),
    {"configVersion": 1, "key": "systemName", "unit": "text", "textValue": Marked("name")},
)
_SETTINGS_SEED: Final = TenantSeed(
    nodes=(_version("v", 1, "current", ["ref-1", "ref-2"]), _SETTING),
    rels=(SeedRel("v", "HAS_SETTING", "s"),),
)
_CONTACT_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "c",
            ("TenantContact",),
            {"kind": "coordination-phone", "label": Marked("desk"), "value": "0300 123 4567"},
        ),
    )
)
_CHANNEL_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "ch",
            ("TenantChannel",),
            {
                "id": "ch-1",
                "kind": "sms",
                "provider": "twilio",
                "status": "active",
                "senderLabel": Marked("sender"),
                "accountSid": _SID,
                "secretRef": "twilio/seed/auth-token",
            },
        ),
    )
)
# A retention row holds no free text, so the seed tells the tenants apart by a marked action
# (scenario data only: nothing reads it back through the domain).
_RETENTION_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "r",
            ("TenantRetention",),
            {"dataClass": "bookings", "keepDays": 730, "action": Marked("delete")},
        ),
    )
)
_BINDING_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "b",
            ("TenantEntraBinding",),
            {
                "directoryId": _DIRECTORY,
                "status": "verified",
                "verifiedAt": _T,
                "verifiedByRef": Marked("operator"),
            },
        ),
    )
)
_MAPPING_SEED: Final = TenantSeed(
    nodes=(
        SeedNode(
            "m",
            ("TenantRoleMapping",),
            {"groupObjectId": _GROUP, "role": "advisor", "status": Marked("active")},
        ),
    )
)

_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-TCFG-ADD-VERSION": Scenario(
        "create the next configuration version beside the tenant's own",
        seed=_CURRENT_SEED,
        params={
            "version": 2,
            "status": "draft",
            "createdAt": _T2,
            "createdByRef": "ref-new",
            "effectiveFrom": None,
            "approvedByRefs": [],
            "reasonCode": "winter",
        },
        new=("version", "status", "createdAt", "createdByRef", "reasonCode"),
        expect=Expect(
            rows=({"written": 1},),
            nodes={"TenantConfigVersion": 1},
            after=(NodeSpec(("TenantConfigVersion",), {"version": 2, "status": "draft"}),),
        ),
    ),
    "Q-TCFG-ADD-SETTINGS": Scenario(
        "write the settings of the tenant's version",
        seed=_CURRENT_SEED,
        params={
            "version": 1,
            "settings": [
                {
                    "key": "staleWarningHours",
                    "unit": "hours",
                    "intValue": 3,
                    "textValue": None,
                    "boolValue": None,
                    "timeValue": None,
                    "codeValues": None,
                }
            ],
        },
        lookup=("version",),
        new=("settings",),
        expect=Expect(
            rows=({"written": 1},),
            nodes={"TenantSetting": 1},
            rels={"HAS_SETTING": 1},
        ),
    ),
    "Q-TCFG-GET": Scenario(
        "read the tenant's configuration version by number",
        seed=_CURRENT_SEED,
        params={"version": 1},
        lookup=("version",),
        expect=Expect(rows=({"props": {"createdByRef": Marked("author"), "status": "current"}},)),
    ),
    "Q-TCFG-CURRENT": Scenario(
        "read the tenant's configuration version in force",
        seed=_CURRENT_SEED,
        expect=Expect(rows=({"props": {"createdByRef": Marked("author")}},)),
    ),
    "Q-TCFG-SETTINGS": Scenario(
        "read the settings of the tenant's version",
        seed=_SETTINGS_SEED,
        params={"version": 1},
        lookup=("version",),
        expect=Expect(rows=({"props": {"key": "systemName", "textValue": Marked("name")}},)),
    ),
    "Q-TCFG-LATEST": Scenario(
        "read the highest version number of the tenant and how many versions it holds",
        seed=_TWO_VERSIONS_SEED,
        expect=Expect(rows=({"latest": 2, "versions": 2},)),
    ),
    "Q-TCFG-MOVE": Scenario(
        "move the tenant's version to its next status once",
        seed=_PENDING_SEED,
        params={
            "version": 1,
            "expected": "pending-approval",
            "status": "current",
            "effectiveFrom": _T2,
            "approvedByRefs": ["ref-1", "ref-2"],
        },
        lookup=("version",),
        new=("status", "approvedByRefs"),
        expect=Expect(
            rows=({"moved": 1},),
            after=(NodeSpec(("TenantConfigVersion",), {"version": 1, "status": "current"}),),
        ),
    ),
    "Q-TCONTACT-PUT": Scenario(
        "set the tenant's contact of one kind",
        seed=_CONTACT_SEED,
        params={"kind": "coordination-phone", "label": "New desk", "value": "0300 123 4568"},
        lookup=("kind",),
        new=("label", "value"),
        expect=Expect(
            rows=({"saved": 1},),
            after=(
                NodeSpec(("TenantContact",), {"kind": "coordination-phone", "label": "New desk"}),
            ),
        ),
    ),
    "Q-TCONTACT-LIST": Scenario(
        "list the tenant's contacts",
        seed=_CONTACT_SEED,
        expect=Expect(rows=({"props": {"kind": "coordination-phone", "label": Marked("desk")}},)),
    ),
    "Q-TCHANNEL-PUT": Scenario(
        "set the tenant's channel record",
        seed=_CHANNEL_SEED,
        params={
            "id": "ch-1",
            "kind": "sms",
            "provider": "twilio",
            "status": "retired",
            "senderLabel": "New sender",
            "accountSid": _SID,
            "secretRef": "twilio/seed/auth-token",
            "fromAddress": None,
            "fromDisplayName": None,
        },
        lookup=("id",),
        new=("status", "senderLabel"),
        expect=Expect(
            rows=({"saved": 1},),
            after=(NodeSpec(("TenantChannel",), {"id": "ch-1", "status": "retired"}),),
        ),
    ),
    "Q-TCHANNEL-LIST": Scenario(
        "list the tenant's channels",
        seed=_CHANNEL_SEED,
        expect=Expect(rows=({"props": {"id": "ch-1", "senderLabel": Marked("sender")}},)),
    ),
    "Q-TRETENTION-PUT": Scenario(
        "set the tenant's retention rule of one data class",
        seed=_RETENTION_SEED,
        params={"dataClass": "bookings", "keepDays": 365, "action": "summarise"},
        lookup=("dataClass",),
        new=("keepDays", "action"),
        expect=Expect(
            rows=({"saved": 1},),
            after=(NodeSpec(("TenantRetention",), {"dataClass": "bookings", "keepDays": 365}),),
        ),
    ),
    "Q-TRETENTION-LIST": Scenario(
        "list the tenant's retention rules",
        seed=_RETENTION_SEED,
        expect=Expect(rows=({"props": {"dataClass": "bookings", "action": Marked("delete")}},)),
    ),
    "Q-TBINDING-PUT": Scenario(
        "set the tenant's directory binding",
        seed=_BINDING_SEED,
        params={
            "directoryId": _DIRECTORY,
            "status": "revoked",
            "verifiedAt": None,
            "verifiedByRef": None,
        },
        lookup=("directoryId",),
        new=("status",),
        expect=Expect(
            rows=({"saved": 1},),
            after=(
                NodeSpec(("TenantEntraBinding",), {"directoryId": _DIRECTORY, "status": "revoked"}),
            ),
        ),
    ),
    "Q-TBINDING-LIST": Scenario(
        "list the tenant's directory bindings",
        seed=_BINDING_SEED,
        expect=Expect(
            rows=({"props": {"directoryId": _DIRECTORY, "verifiedByRef": Marked("operator")}},)
        ),
    ),
    "Q-TMAPPING-PUT": Scenario(
        "set the tenant's role mapping of one directory group",
        seed=_MAPPING_SEED,
        params={"groupObjectId": _GROUP, "role": "lead", "status": "retired"},
        lookup=("groupObjectId",),
        new=("role", "status"),
        expect=Expect(
            rows=({"saved": 1},),
            after=(NodeSpec(("TenantRoleMapping",), {"groupObjectId": _GROUP, "role": "lead"}),),
        ),
    ),
    "Q-TMAPPING-LIST": Scenario(
        "list the tenant's role mappings",
        seed=_MAPPING_SEED,
        expect=Expect(rows=({"props": {"groupObjectId": _GROUP, "status": Marked("active")}},)),
    ),
}

# ---------------------------------------------------------------- the statements
#
# Written out in full: no Cypher is built from pieces (DEC-142 item 1). A put is a MERGE on the
# record's key and the tenant, then SET of every other property; a property given as null is
# removed, so an absent value is never stored.

_QUERIES: Final[dict[str, tuple[str, Literal["read", "write"]]]] = {
    "Q-TCFG-ADD-VERSION": (
        "CREATE (v:TenantConfigVersion {tenantId: $tenant, version: $version, status: $status, "
        "createdAt: $createdAt, createdByRef: $createdByRef, effectiveFrom: $effectiveFrom, "
        "approvedByRefs: $approvedByRefs, reasonCode: $reasonCode}) "
        "RETURN count(v) AS written",
        "write",
    ),
    "Q-TCFG-ADD-SETTINGS": (
        "UNWIND $settings AS s "
        "MATCH (v:TenantConfigVersion {version: $version, tenantId: $tenant}) "
        "CREATE (v)-[:HAS_SETTING]->(:TenantSetting {tenantId: $tenant, configVersion: $version, "
        "key: s.key, unit: s.unit, intValue: s.intValue, textValue: s.textValue, "
        "boolValue: s.boolValue, timeValue: s.timeValue, codeValues: s.codeValues}) "
        "RETURN count(*) AS written",
        "write",
    ),
    "Q-TCFG-GET": (
        "MATCH (v:TenantConfigVersion {version: $version, tenantId: $tenant}) "
        "RETURN properties(v) AS props",
        "read",
    ),
    "Q-TCFG-CURRENT": (
        "MATCH (v:TenantConfigVersion {status: 'current', tenantId: $tenant}) "
        "RETURN properties(v) AS props ORDER BY v.version DESC LIMIT 1",
        "read",
    ),
    "Q-TCFG-SETTINGS": (
        "MATCH (v:TenantConfigVersion {version: $version, tenantId: $tenant})"
        "-[:HAS_SETTING]->(s:TenantSetting {tenantId: $tenant}) "
        "RETURN properties(s) AS props ORDER BY s.key",
        "read",
    ),
    # The count beside the maximum is what shows a missing tenant predicate to the generated test:
    # two tenants holding the same numbers give the same maximum, but not the same count.
    "Q-TCFG-LATEST": (
        "MATCH (v:TenantConfigVersion {tenantId: $tenant}) "
        "RETURN coalesce(max(v.version), 0) AS latest, count(v) AS versions",
        "read",
    ),
    # Lock first, then read the status (lessons L73 and L99): the match is by key only and the
    # self-set takes the node's write lock, so two approvers at once are told apart by the status
    # the second reads after the first has committed. A version is never edited otherwise.
    "Q-TCFG-MOVE": (
        "MATCH (v:TenantConfigVersion {version: $version, tenantId: $tenant}) "
        "SET v.version = v.version "
        "WITH v WHERE v.status = $expected "
        "SET v.status = $status, v.effectiveFrom = $effectiveFrom, "
        "v.approvedByRefs = $approvedByRefs "
        "RETURN count(v) AS moved",
        "write",
    ),
    "Q-TCONTACT-PUT": (
        "MERGE (c:TenantContact {kind: $kind, tenantId: $tenant}) "
        "SET c.label = $label, c.value = $value "
        "RETURN count(c) AS saved",
        "write",
    ),
    "Q-TCONTACT-LIST": (
        "MATCH (c:TenantContact {tenantId: $tenant}) RETURN properties(c) AS props ORDER BY c.kind",
        "read",
    ),
    "Q-TCHANNEL-PUT": (
        "MERGE (c:TenantChannel {id: $id, tenantId: $tenant}) "
        "SET c.kind = $kind, c.provider = $provider, c.status = $status, "
        "c.senderLabel = $senderLabel, c.accountSid = $accountSid, c.secretRef = $secretRef, "
        "c.fromAddress = $fromAddress, c.fromDisplayName = $fromDisplayName "
        "RETURN count(c) AS saved",
        "write",
    ),
    "Q-TCHANNEL-LIST": (
        "MATCH (c:TenantChannel {tenantId: $tenant}) RETURN properties(c) AS props ORDER BY c.id",
        "read",
    ),
    "Q-TRETENTION-PUT": (
        "MERGE (r:TenantRetention {dataClass: $dataClass, tenantId: $tenant}) "
        "SET r.keepDays = $keepDays, r.action = $action "
        "RETURN count(r) AS saved",
        "write",
    ),
    "Q-TRETENTION-LIST": (
        "MATCH (r:TenantRetention {tenantId: $tenant}) "
        "RETURN properties(r) AS props ORDER BY r.dataClass",
        "read",
    ),
    "Q-TBINDING-PUT": (
        "MERGE (b:TenantEntraBinding {directoryId: $directoryId, tenantId: $tenant}) "
        "SET b.status = $status, b.verifiedAt = $verifiedAt, b.verifiedByRef = $verifiedByRef "
        "RETURN count(b) AS saved",
        "write",
    ),
    "Q-TBINDING-LIST": (
        "MATCH (b:TenantEntraBinding {tenantId: $tenant}) "
        "RETURN properties(b) AS props ORDER BY b.directoryId",
        "read",
    ),
    "Q-TMAPPING-PUT": (
        "MERGE (m:TenantRoleMapping {groupObjectId: $groupObjectId, tenantId: $tenant}) "
        "SET m.role = $role, m.status = $status "
        "RETURN count(m) AS saved",
        "write",
    ),
    "Q-TMAPPING-LIST": (
        "MATCH (m:TenantRoleMapping {tenantId: $tenant}) "
        "RETURN properties(m) AS props ORDER BY m.groupObjectId",
        "read",
    ),
}

CONFIG_QUERY_IDS: Final[tuple[str, ...]] = tuple(_QUERIES)

for _query_id, (_cypher, _mode) in _QUERIES.items():
    REGISTRY.register(
        NamedQuery(id=_query_id, cypher=_cypher, mode=_mode, scenario=_SCENARIOS[_query_id])
    )


# ---------------------------------------------------------------- the mapping (pure)


def _invalid() -> TenantRecordInvalid:
    return TenantRecordInvalid(RECORD_MESSAGE)


def _native(value: Any) -> Any:
    """A driver temporal as the Python value it holds."""
    return value.to_native() if hasattr(value, "to_native") else value


def _instant(value: Any) -> datetime:
    native = _native(value)
    if type(native) is not datetime or native.utcoffset() is None:
        raise _invalid()
    return native.astimezone(UTC)


def _optional_instant(value: Any) -> datetime | None:
    return None if value is None else _instant(value)


def _text(props: dict[str, Any], key: str) -> str:
    value = props.get(key)
    if type(value) is not str:
        raise _invalid()
    return value


def _optional_text(props: dict[str, Any], key: str) -> str | None:
    value = props.get(key)
    if value is None:
        return None
    return _text(props, key)


def setting_row(key: str, value: SettingValue) -> dict[str, Any]:
    """The row of one setting: its key and unit and exactly one typed column. An unknown key or a
    value the registry refuses (the wrong type, out of bounds, not an allowed code) is refused
    here, so nothing the registry would refuse is ever written."""
    spec = spec_for(key)
    checked = validate_value(spec, value)
    row: dict[str, Any] = {"key": key, "unit": spec.unit, **dict.fromkeys(VALUE_COLUMNS)}
    if spec.kind is SettingKind.INT:
        row["intValue"] = checked
    elif spec.kind is SettingKind.TEXT:
        row["textValue"] = checked
    elif spec.kind is SettingKind.BOOL:
        row["boolValue"] = checked
    elif spec.kind is SettingKind.TIME:
        row["timeValue"] = checked
    else:
        row["codeValues"] = sorted(checked)  # type: ignore[arg-type]
    return row


def _setting_value(kind: SettingKind, row: dict[str, Any]) -> SettingValue:
    column = {
        SettingKind.INT: "intValue",
        SettingKind.TEXT: "textValue",
        SettingKind.BOOL: "boolValue",
        SettingKind.TIME: "timeValue",
        SettingKind.CODES: "codeValues",
    }[kind]
    if any(row.get(name) is not None for name in VALUE_COLUMNS if name != column):
        raise _invalid()  # one column only
    raw = _native(row.get(column))
    if kind is SettingKind.CODES:
        if not isinstance(raw, list) or not all(type(code) is str for code in raw):
            raise _invalid()
        return frozenset(raw)
    return raw  # type: ignore[no-any-return]  # validate_value checks the exact type


def values_from_rows(rows: list[dict[str, Any]]) -> dict[str, SettingValue]:
    """The values of a version from its setting rows. A row the registry refuses, a value in the
    wrong column, two rows for one key: `TenantRecordInvalid`."""
    values: dict[str, SettingValue] = {}
    try:
        for row in rows:
            key = _text(row, "key")
            if key in values:
                raise _invalid()
            spec = spec_for(key)
            values[key] = validate_value(spec, _setting_value(spec.kind, row))
    except (ValidationFailed, KeyError, TypeError) as error:
        raise _invalid() from error
    return values


def version_props(config: TenantConfig) -> dict[str, Any]:
    """The properties of a version's node (no tenant, no settings)."""
    return {
        "version": config.version,
        "status": config.status.value,
        "createdAt": config.created_at,
        "createdByRef": config.created_by_ref,
        "effectiveFrom": config.effective_from,
        "approvedByRefs": list(config.approved_by_refs),
        "reasonCode": config.reason_code,
    }


def version_from_props(props: dict[str, Any], values: dict[str, SettingValue]) -> TenantConfig:
    """The version a node holds, through the domain's own checks."""
    try:
        refs = props.get("approvedByRefs", [])
        if not isinstance(refs, list):
            raise _invalid()
        return TenantConfig(
            version=props["version"],
            status=ConfigStatus(_text(props, "status")),
            values=values,
            created_at=_instant(props["createdAt"]),
            created_by_ref=props["createdByRef"],
            effective_from=_optional_instant(props.get("effectiveFrom")),
            approved_by_refs=tuple(refs),
            reason_code=props.get("reasonCode", ""),
        )
    except (ValidationFailed, KeyError, TypeError, ValueError) as error:
        raise _invalid() from error


def contact_params(contact: TenantContact) -> dict[str, Any]:
    return {"kind": contact.kind.value, "label": contact.label, "value": contact.value}


def contact_from_props(props: dict[str, Any]) -> TenantContact:
    try:
        return TenantContact(
            ContactKind(_text(props, "kind")), _text(props, "label"), _text(props, "value")
        )
    except (ValidationFailed, ValueError) as error:
        raise _invalid() from error


def channel_params(channel: TenantChannel) -> dict[str, Any]:
    return {
        "id": channel.id,
        "kind": channel.kind.value,
        "provider": channel.provider.value,
        "status": channel.status.value,
        "senderLabel": channel.sender_label,
        "accountSid": channel.account_sid,
        "secretRef": channel.secret_ref,
        "fromAddress": channel.from_address,
        "fromDisplayName": channel.from_display_name,
    }


def channel_from_props(props: dict[str, Any]) -> TenantChannel:
    try:
        return TenantChannel(
            id=_text(props, "id"),
            kind=ChannelKind(_text(props, "kind")),
            provider=ChannelProvider(_text(props, "provider")),
            status=NumberStatus(_text(props, "status")),
            sender_label=_text(props, "senderLabel"),
            account_sid=_optional_text(props, "accountSid"),
            secret_ref=_optional_text(props, "secretRef"),
            from_address=_optional_text(props, "fromAddress"),
            from_display_name=_optional_text(props, "fromDisplayName"),
        )
    except (ValidationFailed, ValueError) as error:
        raise _invalid() from error


def retention_params(rule: TenantRetention) -> dict[str, Any]:
    return {
        "dataClass": rule.data_class.value,
        "keepDays": rule.keep_days,
        "action": rule.action.value,
    }


def retention_from_props(props: dict[str, Any]) -> TenantRetention:
    try:
        return TenantRetention(
            RetentionClass(_text(props, "dataClass")),
            props.get("keepDays"),
            RetentionAction(_text(props, "action")),
        )
    except (ValidationFailed, ValueError) as error:
        raise _invalid() from error


def binding_params(binding: EntraBinding) -> dict[str, Any]:
    return {
        "directoryId": binding.directory_id,
        "status": binding.status.value,
        "verifiedAt": binding.verified_at,
        "verifiedByRef": binding.verified_by_ref,
    }


def binding_from_props(props: dict[str, Any]) -> EntraBinding:
    try:
        return EntraBinding(
            _text(props, "directoryId"),
            BindingStatus(_text(props, "status")),
            _optional_instant(props.get("verifiedAt")),
            _optional_text(props, "verifiedByRef"),
        )
    except (ValidationFailed, ValueError) as error:
        raise _invalid() from error


def mapping_params(mapping: RoleMapping) -> dict[str, Any]:
    return {
        "groupObjectId": mapping.group_object_id,
        "role": mapping.role.value,
        "status": mapping.status.value,
    }


def mapping_from_props(props: dict[str, Any]) -> RoleMapping:
    try:
        return RoleMapping(
            _text(props, "groupObjectId"),
            Role(_text(props, "role")),
            MappingStatus(_text(props, "status")),
        )
    except (ValidationFailed, ValueError) as error:
        raise _invalid() from error


# ---------------------------------------------------------------- the repository


class Neo4jTenantConfigRepository:
    """The tenant's configuration on the unit of work's transaction (DEC-012). The tenant is the
    scope the unit opened with; nothing here takes one."""

    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, REGISTRY.get(query_id), **params)

    # --- versions

    async def latest_version_number(self) -> int:
        rows = await self._run("Q-TCFG-LATEST")
        latest = rows[0]["latest"]
        if type(latest) is not int:
            raise _invalid()
        return latest

    async def add_version(self, config: TenantConfig) -> None:
        """Store a draft as the next version, with its settings. Only a draft is added, and only as
        the next number: another number, or a number that two writers raced for, is `Conflict`
        (the composite key refuses the second), and the unit of work is refused with it."""
        if config.status is not ConfigStatus.DRAFT:
            raise ValidationFailed("status", "a version is added as a draft")
        if config.version != await self.latest_version_number() + 1:
            raise Conflict("the configuration has a newer version")
        settings = [setting_row(key, value) for key, value in config.values.items()]
        try:
            await self._run("Q-TCFG-ADD-VERSION", **version_props(config))
            if settings:
                written = await self._run(
                    "Q-TCFG-ADD-SETTINGS", version=config.version, settings=settings
                )
                if int(written[0]["written"]) != len(settings):
                    raise Conflict("the configuration version was not written whole")
        except ConstraintError as error:
            raise Conflict("the configuration has a newer version") from error

    async def _with_settings(self, props: dict[str, Any]) -> TenantConfig:
        rows = await self._run("Q-TCFG-SETTINGS", version=props.get("version"))
        return version_from_props(props, values_from_rows([row["props"] for row in rows]))

    async def get_version(self, version: int) -> TenantConfig | None:
        rows = await self._run("Q-TCFG-GET", version=version)
        return await self._with_settings(rows[0]["props"]) if rows else None

    async def current_version(self) -> TenantConfig | None:
        rows = await self._run("Q-TCFG-CURRENT")
        return await self._with_settings(rows[0]["props"]) if rows else None

    async def move_version(self, config: TenantConfig, expected: ConfigStatus) -> bool:
        """Move a version to the status `config` holds, with its approvers and effective time, only
        if it is still in `expected`. True for the caller whose write moved it; False when it had
        already moved (another approver got there first). An illegal move is refused first."""
        transition_config(expected, config.status)
        rows = await self._run(
            "Q-TCFG-MOVE",
            version=config.version,
            expected=expected.value,
            status=config.status.value,
            effectiveFrom=config.effective_from,
            approvedByRefs=list(config.approved_by_refs),
        )
        return int(rows[0]["moved"]) == 1

    # --- contacts, channels, retention, the directory

    async def put_contact(self, contact: TenantContact) -> None:
        await self._run("Q-TCONTACT-PUT", **contact_params(contact))

    async def contacts(self) -> tuple[TenantContact, ...]:
        rows = await self._run("Q-TCONTACT-LIST")
        return tuple(contact_from_props(row["props"]) for row in rows)

    async def put_channel(self, channel: TenantChannel) -> None:
        await self._run("Q-TCHANNEL-PUT", **channel_params(channel))

    async def channels(self) -> tuple[TenantChannel, ...]:
        rows = await self._run("Q-TCHANNEL-LIST")
        return tuple(channel_from_props(row["props"]) for row in rows)

    async def put_retention(self, rule: TenantRetention) -> None:
        await self._run("Q-TRETENTION-PUT", **retention_params(rule))

    async def retention(self) -> tuple[TenantRetention, ...]:
        rows = await self._run("Q-TRETENTION-LIST")
        return tuple(retention_from_props(row["props"]) for row in rows)

    async def put_binding(self, binding: EntraBinding) -> None:
        await self._run("Q-TBINDING-PUT", **binding_params(binding))

    async def bindings(self) -> tuple[EntraBinding, ...]:
        rows = await self._run("Q-TBINDING-LIST")
        return tuple(binding_from_props(row["props"]) for row in rows)

    async def put_role_mapping(self, mapping: RoleMapping) -> None:
        await self._run("Q-TMAPPING-PUT", **mapping_params(mapping))

    async def role_mappings(self) -> tuple[RoleMapping, ...]:
        rows = await self._run("Q-TMAPPING-LIST")
        return tuple(mapping_from_props(row["props"]) for row in rows)


__all__ = [
    "CONFIG_QUERY_IDS",
    "Neo4jTenantConfigRepository",
    "RECORD_MESSAGE",
    "binding_from_props",
    "binding_params",
    "channel_from_props",
    "channel_params",
    "contact_from_props",
    "contact_params",
    "mapping_from_props",
    "mapping_params",
    "retention_from_props",
    "retention_params",
    "setting_row",
    "values_from_rows",
    "version_from_props",
    "version_props",
]
