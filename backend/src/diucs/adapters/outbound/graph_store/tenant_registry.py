"""The tenant registry's writes on Neo4j (TEN-028, TEN-073; DEC-503).

The seven platform statements of `PLATFORM_QUERY_IDS`, written out in full (no Cypher is built from
pieces, DEC-142 item 1), each pinned by digest in `PLATFORM_STATEMENTS` and run only through
`run_platform_query`. This is the only module that runs one (an architecture test). The registry
nodes carry no tenant (DEC-132), so none of these statements takes `$tenant`; each takes the id,
number, host or directory it works on, and the operator use cases that call them are the only code
that holds this adapter.

A unique constraint is what stops a second tenant claiming a host, a directory or a number
(`tenant_host`, `tenant_entra_directory`, `tenant_number_e164`, TEN-007): the server refuses and the
adapter answers `Conflict`, with a fixed message that names no value.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ConstraintError
from neo4j.time import DateTime

from diucs.adapters.outbound.graph_store.connection import Neo4jConnection
from diucs.adapters.outbound.graph_store.driver import run_platform_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.adapters.outbound.graph_store.tenant_directory import tenant_properties
from diucs.application.ports.outbound.tenant_registry import TenantNumberRecord
from diucs.application.ports.outbound.tenants import (
    TenantRecordInvalid,
    check_secret_ref,
    normalise_directory_id,
    normalise_e164,
    normalise_host,
)
from diucs.domain.errors import Conflict, NotFound, ValidationFailed
from diucs.domain.model.tenant import NumberStatus, Tenant, TenantStatus, check_tenant_id

EXISTS_MESSAGE: Final = "a tenant with this id already exists"
IN_USE_MESSAGE: Final = "this value is held by another tenant"
NO_TENANT_MESSAGE: Final = "no tenant with this id"
NO_NUMBER_MESSAGE: Final = "the tenant holds no such number"
NUMBER_RECORD_MESSAGE: Final = "a number record in the registry is not valid"

_CREATE = NamedQuery(
    id="Q-TENANT-REG-CREATE",
    cypher="CREATE (t:Tenant {id: $id}) SET t += $props RETURN t.id AS id",
    mode="write",
    scope="platform",
)
_SAVE = NamedQuery(
    id="Q-TENANT-REG-SAVE",
    cypher=(
        "MATCH (t:Tenant {id: $id, epoch: $expectedEpoch, status: $expectedStatus}) "
        "SET t += $props RETURN t.id AS id"
    ),
    mode="write",
    scope="platform",
)
_SET_HOST = NamedQuery(
    id="Q-TENANT-REG-SET-HOST",
    cypher="MATCH (t:Tenant {id: $id}) SET t.host = $host RETURN t.id AS id",
    mode="write",
    scope="platform",
)
_SET_DIRECTORY = NamedQuery(
    id="Q-TENANT-REG-SET-DIRECTORY",
    cypher=("MATCH (t:Tenant {id: $id}) SET t.entraDirectoryId = $directoryId RETURN t.id AS id"),
    mode="write",
    scope="platform",
)
_PUT_NUMBER = NamedQuery(
    id="Q-TENANT-REG-PUT-NUMBER",
    cypher=(
        "MATCH (t:Tenant {id: $id}) "
        "MERGE (t)-[:HAS_NUMBER]->(n:TenantNumber {e164: $e164}) "
        "SET n += $props RETURN n.e164 AS e164"
    ),
    mode="write",
    scope="platform",
)
_MARK_TESTED = NamedQuery(
    id="Q-TENANT-REG-MARK-TESTED",
    cypher=(
        "MATCH (:Tenant {id: $id})-[:HAS_NUMBER]->(n:TenantNumber {e164: $e164}) "
        "SET n.testedAt = $at RETURN n.e164 AS e164"
    ),
    mode="write",
    scope="platform",
)
_NUMBERS = NamedQuery(
    id="Q-TENANT-REG-NUMBERS",
    cypher=(
        "MATCH (:Tenant {id: $id})-[:HAS_NUMBER]->(n:TenantNumber) "
        "RETURN n.e164 AS e164, n.accountSid AS accountSid, n.secretRef AS secretRef, "
        "n.status AS status, n.testedAt AS testedAt, n.quarantineUntil AS quarantineUntil "
        "ORDER BY n.e164"
    ),
    mode="read",
    scope="platform",
)
for _query in (
    _CREATE,
    _SAVE,
    _SET_HOST,
    _SET_DIRECTORY,
    _PUT_NUMBER,
    _MARK_TESTED,
    _NUMBERS,
):
    REGISTRY.register(_query)


def tenant_write_properties(tenant: Tenant) -> dict[str, Any]:
    """The properties a save writes: every lifecycle property of the record, with `None` for one
    that is not set, so that `SET t += $props` removes it (a resumed tenant has no suspend fields).
    The id is the statement's key and is not here, and neither are the host and the directory, which
    the record does not hold."""
    present = tenant_properties(tenant)
    every = {
        key: present.get(key)
        for key in (
            "displayName",
            "legalName",
            "organisationType",
            "countryCode",
            "timeZone",
            "status",
            "createdAt",
            "activatedAt",
            "suspendedAt",
            "offboardingStartedAt",
            "offboardedAt",
            "purgedAt",
            "suspendMode",
            "suspendReason",
            "retentionHoldUntil",
            "odsCode",
            "epoch",
            "hashKeyVersion",
            "currentConfigVersion",
            "dsaRef",
            "dpiaRef",
            "dcb0160Ref",
        )
    }
    return every


def number_properties(number: TenantNumberRecord) -> dict[str, Any]:
    """The properties of a number's node, besides its key: unset times are `None` (removed)."""
    return {
        "accountSid": number.account_sid,
        "secretRef": number.secret_ref,
        "status": number.status.value,
        "testedAt": number.tested_at,
        "quarantineUntil": number.quarantine_until,
    }


def _instant(value: object) -> datetime | None:
    if value is None:
        return None
    native = value.to_native() if isinstance(value, DateTime) else value
    if not isinstance(native, datetime):
        raise TenantRecordInvalid(NUMBER_RECORD_MESSAGE)
    return native


def number_from_row(row: Mapping[str, Any], tenant_id: str) -> TenantNumberRecord:
    """A number record from a row, through the domain's own checks; a row that does not pass, or a
    reference that is not the tenant's own, is `TenantRecordInvalid` (fixed message)."""
    try:
        return TenantNumberRecord(
            e164=str(row["e164"]),
            account_sid=str(row["accountSid"]),
            secret_ref=check_secret_ref(row.get("secretRef"), tenant_id),
            status=NumberStatus(str(row["status"])),
            tested_at=_instant(row.get("testedAt")),
            quarantine_until=_instant(row.get("quarantineUntil")),
        )
    except ValidationFailed, ValueError, KeyError, TypeError:
        raise TenantRecordInvalid(NUMBER_RECORD_MESSAGE) from None


class Neo4jTenantRegistry:
    """The `TenantRegistry` port over the platform statements (built by the composition root)."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    async def _write(self, query: NamedQuery, **params: Any) -> list[dict[str, Any]]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_platform_query(tx, query, **params)

        return await self._connection.run_write(work)

    async def _read(self, query: NamedQuery, **params: Any) -> list[dict[str, Any]]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_platform_query(tx, query, **params)

        return await self._connection.run_read(work)

    async def create(self, tenant: Tenant) -> None:
        if tenant.status is not TenantStatus.PROVISIONING:
            raise ValidationFailed("status", "a new tenant is in provisioning")
        props = tenant_write_properties(tenant)
        try:
            await self._write(_CREATE, id=tenant.id, props=props)
        except ConstraintError:
            raise Conflict(EXISTS_MESSAGE) from None

    async def save(
        self, tenant: Tenant, *, expected_epoch: int, expected_status: TenantStatus
    ) -> bool:
        rows = await self._write(
            _SAVE,
            id=tenant.id,
            expectedEpoch=expected_epoch,
            expectedStatus=expected_status.value,
            props=tenant_write_properties(tenant),
        )
        return bool(rows)

    async def set_host(self, tenant_id: str, host: str) -> None:
        name = normalise_host(host)
        if name is None:
            raise ValidationFailed("host", "must be a host name")
        await self._set_one(_SET_HOST, tenant_id, host=name)

    async def set_entra_directory(self, tenant_id: str, directory_id: str) -> None:
        guid = normalise_directory_id(directory_id)
        if guid is None:
            raise ValidationFailed("directory_id", "must be a directory id")
        await self._set_one(_SET_DIRECTORY, tenant_id, directoryId=guid)

    async def _set_one(self, query: NamedQuery, tenant_id: str, **params: Any) -> None:
        check_tenant_id(tenant_id)
        try:
            rows = await self._write(query, id=tenant_id, **params)
        except ConstraintError:
            raise Conflict(IN_USE_MESSAGE) from None
        if not rows:
            raise NotFound(NO_TENANT_MESSAGE)

    async def put_number(self, tenant_id: str, number: TenantNumberRecord) -> None:
        check_tenant_id(tenant_id)
        number.for_tenant(tenant_id)
        try:
            rows = await self._write(
                _PUT_NUMBER, id=tenant_id, e164=number.e164, props=number_properties(number)
            )
        except ConstraintError:
            raise Conflict(IN_USE_MESSAGE) from None
        if not rows:
            raise NotFound(NO_TENANT_MESSAGE)

    async def mark_number_tested(self, tenant_id: str, e164: str, at: datetime) -> None:
        check_tenant_id(tenant_id)
        number = normalise_e164(e164)
        if number is None:
            raise ValidationFailed("e164", "must be a number in E.164 form")
        if at.utcoffset() is None:
            raise ValidationFailed("at", "must be a timezone-aware datetime")
        rows = await self._write(_MARK_TESTED, id=tenant_id, e164=number, at=at)
        if not rows:
            raise NotFound(NO_NUMBER_MESSAGE)

    async def numbers(self, tenant_id: str) -> tuple[TenantNumberRecord, ...]:
        check_tenant_id(tenant_id)
        rows = await self._read(_NUMBERS, id=tenant_id)
        return tuple(number_from_row(row, tenant_id) for row in rows)
