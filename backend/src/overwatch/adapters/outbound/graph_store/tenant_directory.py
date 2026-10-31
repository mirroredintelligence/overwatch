"""The tenant directory on Neo4j (TEN-007, DEC-130 to DEC-134).

The directory is the platform's own record of its tenants: the `Tenant` and `TenantNumber`
registry nodes, which carry no `tenantId` (DEC-132). It is global and read-only. Its statements
run before any tenant is bound, so they are the global allowlist (`GLOBAL_QUERY_IDS`), they run
only through `run_global_query`, and they send no tenant: the result is the same whatever tenant is
bound, or none. A statement reads registry nodes and nothing else (the registry refuses a global
statement that writes or names another label), and the answer is configuration: no person, no
capacity, no message.

A tenant is a node with typed properties (DEC-001): codes as text, times as datetimes, counts as
integers, nothing as JSON. `host` and `entraDirectoryId` are properties of the node (one of each per
tenant, unique across tenants); a number is a `TenantNumber` node on a `HAS_NUMBER` relationship,
unique by its E.164 number. A secret is never on a node, only the reference of its entry in the
secret store (DEC-131 item 4).

Fail closed. A key that is not the shape it names is not looked up. A record the domain refuses,
a number that points at another tenant's secret, an account that two tenants hold: each is
`TenantRecordInvalid` (a configuration fault with a fixed message that names no value), never a
guess and never an unknown number. Nothing is cached: a suspension takes effect on the next call.
Nothing is logged here.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from neo4j import AsyncManagedTransaction
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_global_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.application.ports.outbound.tenants import (
    TenantLine,
    TenantRecordInvalid,
    check_secret_ref,
    normalise_account_sid,
    normalise_directory_id,
    normalise_e164,
    normalise_host,
)
from diucs.domain.errors import ValidationFailed
from diucs.domain.model.tenant import (
    OrganisationType,
    SuspendMode,
    SuspendReason,
    Tenant,
    TenantStatus,
    check_tenant_id,
)

RECORD_MESSAGE: Final = "a tenant record in the registry is not valid"

# The statements, written out in full (no Cypher is built from pieces, DEC-142 item 1). Each is on
# GLOBAL_QUERY_IDS with its reason; test_global_allowlist.py pins the text of every one.
_GET = NamedQuery(
    id="Q-TENANT-GET",
    cypher="MATCH (t:Tenant {id: $id}) RETURN properties(t) AS tenant",
    mode="read",
    scope="global",
)
_LIST_ACTIVE = NamedQuery(
    id="Q-TENANT-LIST-ACTIVE",
    cypher="MATCH (t:Tenant {status: 'active'}) RETURN properties(t) AS tenant ORDER BY t.id",
    mode="read",
    scope="global",
)
_ACTIVE_IDS = NamedQuery(
    id="Q-TENANT-ACTIVE-IDS",
    cypher="MATCH (t:Tenant {status: 'active'}) RETURN t.id AS id ORDER BY t.id",
    mode="read",
    scope="global",
)
_BY_NUMBER = NamedQuery(
    id="Q-TENANT-BY-NUMBER",
    cypher=(
        "MATCH (t:Tenant)-[:HAS_NUMBER]->(n:TenantNumber "
        "{e164: $number, accountSid: $accountSid, status: 'active'}) "
        "RETURN properties(t) AS tenant, n.e164 AS number, n.accountSid AS accountSid, "
        "n.secretRef AS secretRef"
    ),
    mode="read",
    scope="global",
)
_BY_ACCOUNT = NamedQuery(
    id="Q-TENANT-BY-ACCOUNT",
    cypher=(
        "MATCH (t:Tenant)-[:HAS_NUMBER]->(n:TenantNumber "
        "{accountSid: $accountSid, status: 'active'}) "
        "RETURN properties(t) AS tenant, n.e164 AS number, n.accountSid AS accountSid, "
        "n.secretRef AS secretRef ORDER BY n.e164"
    ),
    mode="read",
    scope="global",
)
_ACTIVE_LINE = NamedQuery(
    id="Q-TENANT-ACTIVE-LINE",
    cypher=(
        "MATCH (t:Tenant {id: $id, status: 'active'})-[:HAS_NUMBER]->(n:TenantNumber "
        "{status: 'active'}) "
        "RETURN properties(t) AS tenant, n.e164 AS number, n.accountSid AS accountSid, "
        "n.secretRef AS secretRef ORDER BY n.e164"
    ),
    mode="read",
    scope="global",
)
_BY_HOST = NamedQuery(
    id="Q-TENANT-BY-HOST",
    cypher="MATCH (t:Tenant {host: $host}) RETURN properties(t) AS tenant",
    mode="read",
    scope="global",
)
_BY_ENTRA = NamedQuery(
    id="Q-TENANT-BY-ENTRA",
    cypher="MATCH (t:Tenant {entraDirectoryId: $directoryId}) RETURN properties(t) AS tenant",
    mode="read",
    scope="global",
)
for _query in (
    _GET,
    _LIST_ACTIVE,
    _ACTIVE_IDS,
    _BY_NUMBER,
    _BY_ACCOUNT,
    _ACTIVE_LINE,
    _BY_HOST,
    _BY_ENTRA,
):
    REGISTRY.register(_query)


# ---------------------------------------------------------------- the record and its node


def tenant_properties(tenant: Tenant) -> dict[str, Any]:
    """The properties of a tenant's node: codes as text, times as datetimes, counts as integers,
    and no property for a field that is not set (Neo4j holds no null). `host` and
    `entraDirectoryId` are not part of the tenant record and are not here."""
    properties: dict[str, Any] = {
        "id": tenant.id,
        "displayName": tenant.display_name,
        "legalName": tenant.legal_name,
        "organisationType": tenant.organisation_type.value,
        "countryCode": tenant.country_code,
        "timeZone": tenant.time_zone,
        "status": tenant.status.value,
        "createdAt": tenant.created_at,
        "activatedAt": tenant.activated_at,
        "suspendedAt": tenant.suspended_at,
        "offboardingStartedAt": tenant.offboarding_started_at,
        "offboardedAt": tenant.offboarded_at,
        "purgedAt": tenant.purged_at,
        "suspendMode": None if tenant.suspend_mode is None else tenant.suspend_mode.value,
        "suspendReason": None if tenant.suspend_reason is None else tenant.suspend_reason.value,
        "retentionHoldUntil": tenant.retention_hold_until,
        "odsCode": tenant.ods_code,
        "epoch": tenant.epoch,
        "hashKeyVersion": tenant.hash_key_version,
        "currentConfigVersion": tenant.current_config_version,
        "dsaRef": tenant.dsa_ref,
        "dpiaRef": tenant.dpia_ref,
        "dcb0160Ref": tenant.dcb0160_ref,
    }
    return {key: value for key, value in properties.items() if value is not None}


class _Invalid(Exception):
    """Internal: a property is missing or of the wrong type. Never leaves this module."""


def _optional_text(props: Mapping[str, Any], key: str) -> str | None:
    value = props.get(key)
    if value is None:
        return None
    if type(value) is not str:
        raise _Invalid
    return value


def _text(props: Mapping[str, Any], key: str) -> str:
    value = _optional_text(props, key)
    if value is None:
        raise _Invalid
    return value


def _code[E: StrEnum](props: Mapping[str, Any], key: str, kind: type[E]) -> E:
    return kind(_text(props, key))


def _optional_code[E: StrEnum](props: Mapping[str, Any], key: str, kind: type[E]) -> E | None:
    value = _optional_text(props, key)
    return None if value is None else kind(value)


def _optional_instant(props: Mapping[str, Any], key: str) -> datetime | None:
    value = props.get(key)
    if value is None:
        return None
    native = value.to_native() if isinstance(value, DateTime) else value
    if not isinstance(native, datetime):
        raise _Invalid  # a time held as text, or as anything but a datetime
    return native


def _instant(props: Mapping[str, Any], key: str) -> datetime:
    value = _optional_instant(props, key)
    if value is None:
        raise _Invalid
    return value


def _optional_count(props: Mapping[str, Any], key: str) -> int | None:
    value = props.get(key)
    if value is None:
        return None
    if type(value) is not int:
        raise _Invalid
    return value


def _count(props: Mapping[str, Any], key: str) -> int:
    value = _optional_count(props, key)
    if value is None:
        raise _Invalid
    return value


def tenant_from_properties(props: Mapping[str, Any]) -> Tenant:
    """The tenant a node holds, through the domain's own checks. A missing or mistyped property, a
    status that does not agree with its times, an id that is not a tenant id: `TenantRecordInvalid`,
    with a fixed message that holds no value."""
    try:
        return Tenant(
            id=_text(props, "id"),
            display_name=_text(props, "displayName"),
            legal_name=_text(props, "legalName"),
            organisation_type=_code(props, "organisationType", OrganisationType),
            country_code=_text(props, "countryCode"),
            time_zone=_text(props, "timeZone"),
            status=_code(props, "status", TenantStatus),
            created_at=_instant(props, "createdAt"),
            activated_at=_optional_instant(props, "activatedAt"),
            suspended_at=_optional_instant(props, "suspendedAt"),
            offboarding_started_at=_optional_instant(props, "offboardingStartedAt"),
            offboarded_at=_optional_instant(props, "offboardedAt"),
            purged_at=_optional_instant(props, "purgedAt"),
            suspend_mode=_optional_code(props, "suspendMode", SuspendMode),
            suspend_reason=_optional_code(props, "suspendReason", SuspendReason),
            retention_hold_until=_optional_instant(props, "retentionHoldUntil"),
            ods_code=_optional_text(props, "odsCode"),
            epoch=_count(props, "epoch"),
            hash_key_version=_count(props, "hashKeyVersion"),
            current_config_version=_optional_count(props, "currentConfigVersion"),
            dsa_ref=_optional_text(props, "dsaRef"),
            dpia_ref=_optional_text(props, "dpiaRef"),
            dcb0160_ref=_optional_text(props, "dcb0160Ref"),
        )
    except _Invalid, ValidationFailed, ValueError, TypeError:
        raise TenantRecordInvalid(RECORD_MESSAGE) from None


def _line_of(row: Mapping[str, Any]) -> TenantLine:
    """A line from a `TenantNumber` row: the tenant, the number and account in the shape they are
    looked up by, and a secret reference that is the tenant's own."""
    tenant = tenant_from_properties(row["tenant"])
    number = normalise_e164(row.get("number"))
    account_sid = normalise_account_sid(row.get("accountSid"))
    if number is None or account_sid is None:
        raise TenantRecordInvalid(RECORD_MESSAGE)
    try:
        reference = check_secret_ref(row.get("secretRef"), tenant.id)
    except ValidationFailed:
        raise TenantRecordInvalid(RECORD_MESSAGE) from None
    return TenantLine(tenant=tenant, number=number, account_sid=account_sid, secret_ref=reference)


class Neo4jTenantDirectory:
    """The `TenantDirectory` port (and the outbox relay's `ActiveTenants`) over the registry."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    async def _read(self, query: NamedQuery, **params: Any) -> list[dict[str, Any]]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_global_query(tx, query, **params)

        return await self._connection.run_read(work)

    async def get(self, tenant_id: str) -> Tenant | None:
        try:
            check_tenant_id(tenant_id)
        except ValidationFailed:
            return None
        rows = await self._read(_GET, id=tenant_id)
        return self._one_tenant(rows)

    async def by_inbound_number(self, to_number: str, account_sid: str) -> TenantLine | None:
        number = normalise_e164(to_number)
        account = normalise_account_sid(account_sid)
        if number is None or account is None:
            return None
        rows = await self._read(_BY_NUMBER, number=number, accountSid=account)
        if not rows:
            return None
        if len(rows) > 1:  # the number is unique, so this is a registry fault
            raise TenantRecordInvalid(RECORD_MESSAGE)
        return _line_of(rows[0])

    async def active_line(self, tenant_id: str) -> TenantLine | None:
        """The active number of this tenant, if the tenant is active and holds exactly one active
        number (I10). None for an unknown, suspended or number-less tenant; more than one active
        number is a registry fault. The id is the bound tenant's (DEC-131)."""
        try:
            check_tenant_id(tenant_id)
        except ValidationFailed:
            return None
        rows = await self._read(_ACTIVE_LINE, id=tenant_id)
        if not rows:
            return None
        if len(rows) > 1:
            raise TenantRecordInvalid(RECORD_MESSAGE)
        return _line_of(rows[0])

    async def by_account_sid(self, account_sid: str) -> TenantLine | None:
        account = normalise_account_sid(account_sid)
        if account is None:
            return None
        rows = await self._read(_BY_ACCOUNT, accountSid=account)
        if not rows:
            return None
        lines = [_line_of(row) for row in rows]
        if (
            len({line.tenant.id for line in lines}) > 1
            or len({line.secret_ref for line in lines}) > 1
        ):
            raise TenantRecordInvalid(RECORD_MESSAGE)  # an account is one tenant's, with one token
        return lines[0]

    async def by_host(self, host: str) -> Tenant | None:
        name = normalise_host(host)
        if name is None:
            return None
        return self._one_tenant(await self._read(_BY_HOST, host=name))

    async def host_of(self, tenant_id: str) -> str | None:
        """The host property of the tenant's node, read with the same statement as `get`. The
        property is not part of the domain record, so it is read from the row."""
        try:
            check_tenant_id(tenant_id)
        except ValidationFailed:
            return None
        rows = await self._read(_GET, id=tenant_id)
        if not rows:
            return None
        if len(rows) > 1:
            raise TenantRecordInvalid(RECORD_MESSAGE)
        return normalise_host(rows[0]["tenant"].get("host"))

    async def by_entra_directory(self, directory_id: str) -> Tenant | None:
        guid = normalise_directory_id(directory_id)
        if guid is None:
            return None
        return self._one_tenant(await self._read(_BY_ENTRA, directoryId=guid))

    async def list_active(self) -> Sequence[Tenant]:
        rows = await self._read(_LIST_ACTIVE)
        return [tenant_from_properties(row["tenant"]) for row in rows]

    async def active_tenant_ids(self) -> Sequence[str]:
        """The ids of the active tenants, in order. Ids only: the relay binds each one in turn, so
        one tenant's damaged record cannot stop the others. The caller checks each id."""
        rows = await self._read(_ACTIVE_IDS)
        return [row["id"] for row in rows if type(row["id"]) is str]

    @staticmethod
    def _one_tenant(rows: list[dict[str, Any]]) -> Tenant | None:
        if not rows:
            return None
        if len(rows) > 1:  # each key is unique, so this is a registry fault
            raise TenantRecordInvalid(RECORD_MESSAGE)
        return tenant_from_properties(rows[0]["tenant"])
