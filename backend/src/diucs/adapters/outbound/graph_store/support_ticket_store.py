"""The support-access tickets on Neo4j (TEN-075, TEN-084; `ports/outbound/cross_tenant_tickets.py`).

A `SupportAccessTicket` is a platform record (DEC-132: the registry and the platform's own records
carry no `tenantId`). It names the tenant the access is for as data, `forTenant`, and the support
person as `requestedBy` (an opaque account reference). Each statement names the side it serves:
the tenant's administrator reads and moves tickets by `forTenant`, the support person reads them by
`requestedBy`, and a move is a compare and set on the tenant and the state the caller read, so two
decisions on one ticket cannot both stand and a ticket of another tenant is never matched.

Six platform statements (`PLATFORM_QUERY_IDS`), fixed text pinned by digest, run only through
`run_platform_query`. The properties are typed (DEC-001): times as datetimes, the state as text, and
no property for a field that is not set (an unset field is `None`, which `SET t += $props` removes).
The record holds no code, only the keyed hash of the one the approval issued, and no name.
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
from diucs.application.ports.outbound.tenants import TenantRecordInvalid
from diucs.domain.errors import Conflict, ValidationFailed
from diucs.domain.model.tenant import check_tenant_id
from diucs.domain.rules.support_ticket import (
    EndedBy,
    ReasonCode,
    SupportTicket,
    TicketState,
    check_reference,
)

EXISTS_MESSAGE: Final = "a ticket with this id already exists"
RECORD_MESSAGE: Final = "a support ticket in the registry is not valid"
MAX_LIST: Final = 200

_ADD = NamedQuery(
    id="Q-SUPPORT-TICKET-ADD",
    cypher="CREATE (t:SupportAccessTicket {id: $id}) SET t += $props RETURN t.id AS id",
    mode="write",
    scope="platform",
)
_OF_TENANT = NamedQuery(
    id="Q-SUPPORT-TICKET-OF-TENANT",
    cypher=(
        "MATCH (t:SupportAccessTicket {id: $id, forTenant: $forTenant}) "
        "RETURN properties(t) AS ticket"
    ),
    mode="read",
    scope="platform",
)
_OF_PRINCIPAL = NamedQuery(
    id="Q-SUPPORT-TICKET-OF-PRINCIPAL",
    cypher=(
        "MATCH (t:SupportAccessTicket {id: $id, requestedBy: $requestedBy}) "
        "RETURN properties(t) AS ticket"
    ),
    mode="read",
    scope="platform",
)
_LIST_OF_TENANT = NamedQuery(
    id="Q-SUPPORT-TICKETS-OF-TENANT",
    cypher=(
        "MATCH (t:SupportAccessTicket {forTenant: $forTenant}) "
        "RETURN properties(t) AS ticket ORDER BY t.requestedAt DESC LIMIT $limit"
    ),
    mode="read",
    scope="platform",
)
_LIST_OF_PRINCIPAL = NamedQuery(
    id="Q-SUPPORT-TICKETS-OF-PRINCIPAL",
    cypher=(
        "MATCH (t:SupportAccessTicket {requestedBy: $requestedBy}) "
        "RETURN properties(t) AS ticket ORDER BY t.requestedAt DESC LIMIT $limit"
    ),
    mode="read",
    scope="platform",
)
_MOVE = NamedQuery(
    id="Q-SUPPORT-TICKET-MOVE",
    cypher=(
        "MATCH (t:SupportAccessTicket {id: $id, forTenant: $forTenant, state: $expectedState}) "
        "SET t += $props RETURN t.id AS id"
    ),
    mode="write",
    scope="platform",
)
for _query in (_ADD, _OF_TENANT, _OF_PRINCIPAL, _LIST_OF_TENANT, _LIST_OF_PRINCIPAL, _MOVE):
    REGISTRY.register(_query)


def ticket_properties(ticket: SupportTicket) -> dict[str, Any]:
    """The properties of a ticket's node besides its id: every field, `None` for one that is not set
    so that a move removes what it no longer holds."""
    return {
        "forTenant": ticket.tenant_id,
        "requestedBy": ticket.requested_by_ref,
        "reasonCode": ticket.reason_code.value,
        "reason": ticket.reason,
        "reference": ticket.reference,
        "state": ticket.state.value,
        "requestedAt": ticket.requested_at,
        "validUntil": ticket.valid_until,
        "decidedBy": ticket.decided_by_ref,
        "decidedAt": ticket.decided_at,
        "grantHash": ticket.grant_hash,
        "accessId": ticket.access_id,
        "openedAt": ticket.opened_at,
        "endedAt": ticket.ended_at,
        "endedBy": None if ticket.ended_by is None else ticket.ended_by.value,
    }


def _instant(value: object) -> datetime | None:
    if value is None:
        return None
    native = value.to_native() if isinstance(value, DateTime) else value
    if not isinstance(native, datetime):
        raise TenantRecordInvalid(RECORD_MESSAGE)
    return native


def _required_instant(value: object) -> datetime:
    moment = _instant(value)
    if moment is None:
        raise TenantRecordInvalid(RECORD_MESSAGE)
    return moment


def ticket_from_properties(props: Mapping[str, Any]) -> SupportTicket:
    """A ticket from a node, through the domain's own checks: a node that does not pass is
    `TenantRecordInvalid` (a fixed message that names no value)."""
    try:
        ended_by = props.get("endedBy")
        return SupportTicket(
            id=str(props["id"]),
            tenant_id=check_tenant_id(props["forTenant"]),
            requested_by_ref=str(props["requestedBy"]),
            reason_code=ReasonCode(str(props["reasonCode"])),
            reason=str(props["reason"]),
            reference=check_reference(props.get("reference")),
            state=TicketState(str(props["state"])),
            requested_at=_required_instant(props["requestedAt"]),
            valid_until=_required_instant(props["validUntil"]),
            decided_by_ref=props.get("decidedBy"),
            decided_at=_instant(props.get("decidedAt")),
            grant_hash=props.get("grantHash"),
            access_id=props.get("accessId"),
            opened_at=_instant(props.get("openedAt")),
            ended_at=_instant(props.get("endedAt")),
            ended_by=None if ended_by is None else EndedBy(str(ended_by)),
        )
    except ValidationFailed, ValueError, KeyError, TypeError:
        raise TenantRecordInvalid(RECORD_MESSAGE) from None


def _limit(limit: int) -> int:
    if type(limit) is not int or not 1 <= limit <= MAX_LIST:
        raise ValidationFailed("limit", f"must be from 1 to {MAX_LIST}")
    return limit


class Neo4jSupportTickets:
    """The `CrossTenantTicketStore` port over the platform statements."""

    def __init__(self, connection: Neo4jConnection) -> None:
        self._connection = connection

    async def _read(self, query: NamedQuery, **params: Any) -> list[dict[str, Any]]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_platform_query(tx, query, **params)

        return await self._connection.run_read(work)

    async def _write(self, query: NamedQuery, **params: Any) -> list[dict[str, Any]]:
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            return await run_platform_query(tx, query, **params)

        return await self._connection.run_write(work)

    @staticmethod
    def _one(rows: list[dict[str, Any]]) -> SupportTicket | None:
        if not rows:
            return None
        if len(rows) > 1:  # the id is unique, so this is a registry fault
            raise TenantRecordInvalid(RECORD_MESSAGE)
        return ticket_from_properties(rows[0]["ticket"])

    async def add(self, ticket: SupportTicket) -> None:
        try:
            await self._write(_ADD, id=ticket.id, props=ticket_properties(ticket))
        except ConstraintError:
            raise Conflict(EXISTS_MESSAGE) from None

    async def for_tenant(self, tenant_id: str, ticket_id: str) -> SupportTicket | None:
        check_tenant_id(tenant_id)
        return self._one(await self._read(_OF_TENANT, id=ticket_id, forTenant=tenant_id))

    async def for_principal(self, principal_ref: str, ticket_id: str) -> SupportTicket | None:
        return self._one(await self._read(_OF_PRINCIPAL, id=ticket_id, requestedBy=principal_ref))

    async def of_tenant(self, tenant_id: str, limit: int) -> list[SupportTicket]:
        check_tenant_id(tenant_id)
        rows = await self._read(_LIST_OF_TENANT, forTenant=tenant_id, limit=_limit(limit))
        return [ticket_from_properties(row["ticket"]) for row in rows]

    async def of_principal(self, principal_ref: str, limit: int) -> list[SupportTicket]:
        rows = await self._read(_LIST_OF_PRINCIPAL, requestedBy=principal_ref, limit=_limit(limit))
        return [ticket_from_properties(row["ticket"]) for row in rows]

    async def move(self, ticket: SupportTicket, expected: TicketState) -> bool:
        rows = await self._write(
            _MOVE,
            id=ticket.id,
            forTenant=ticket.tenant_id,
            expectedState=expected.value,
            props=ticket_properties(ticket),
        )
        return bool(rows)
