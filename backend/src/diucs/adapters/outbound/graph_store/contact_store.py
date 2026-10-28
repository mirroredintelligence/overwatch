"""Neo4j store for protected contacts (P16, DEC-070, DEC-073): phone numbers and role emails.

Layout: (:ProtectedContact {key, roleId, kind, value, updatedAt}), one node per role and kind
("phone" or "email"). key is roleId and kind joined by "|", and it is unique in the graph (migration
0025), so two racing first writes for one role cannot create two nodes (DEC-073 item 1). The node is
not linked to any FHIR resource or PractitionerRole, so a read of the readable graph never reaches a
number. Only this store reads it. roleId is indexed (migration 0024). updatedAt is a UTC datetime
written by the database.
"""

from typing import Any, Final, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ConstraintError

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.domain.errors import Conflict, ValidationFailed

_PHONE: Final = "phone"
_EMAIL: Final = "email"

_QUERIES: dict[str, tuple[str, Literal["read", "write"]]] = {
    "Q-CONTACT-PUT": (
        "MERGE (c:ProtectedContact {key: $key}) "
        "ON CREATE SET c.roleId = $roleId, c.kind = $kind "
        "SET c.value = $value, c.updatedAt = datetime({timezone: 'UTC'}) "
        "RETURN count(c) AS n",
        "write",
    ),
    "Q-CONTACT-GET": (
        "MATCH (c:ProtectedContact {key: $key}) RETURN c.value AS value LIMIT 1",
        "read",
    ),
}

for _query_id, (_cypher, _mode) in _QUERIES.items():
    REGISTRY.register(NamedQuery(id=_query_id, cypher=_cypher, mode=_mode))


def _key(role_id: str, kind: str) -> str:
    return f"{role_id}|{kind}"


def _checked_phone(number: str) -> str:
    """The number as stored: trimmed, and not blank. The value is never put in the message."""
    if not isinstance(number, str) or not number.strip():
        raise ValidationFailed("phone", "must be a phone number")
    return number.strip()


def _checked_email(email: str) -> str:
    """The address as stored: one @, a local part, and a domain with a dot. Never echoed."""
    text = email.strip() if isinstance(email, str) else ""
    local, _, domain = text.partition("@")
    if not local or not domain or "@" in domain or "." not in domain:
        raise ValidationFailed("email", "must be an email address")
    return text


class Neo4jContactStore:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def put_phone(self, role_id: str, number: str) -> None:
        await self._put(role_id, _PHONE, _checked_phone(number))

    async def get_phone(self, role_id: str) -> str | None:
        return await self._get(role_id, _PHONE)

    async def put_email(self, role_id: str, email: str) -> None:
        await self._put(role_id, _EMAIL, _checked_email(email))

    async def get_email(self, role_id: str) -> str | None:
        return await self._get(role_id, _EMAIL)

    async def _put(self, role_id: str, kind: str, value: str) -> None:
        try:
            await self._run(
                "Q-CONTACT-PUT", key=_key(role_id, kind), roleId=role_id, kind=kind, value=value
            )
        except ConstraintError as error:
            # A racing first write for the same role and kind. Nothing is stored by this write.
            raise Conflict("protected contact is being written by another request") from error

    async def _get(self, role_id: str, kind: str) -> str | None:
        rows = await self._run("Q-CONTACT-GET", key=_key(role_id, kind))
        if not rows or rows[0]["value"] is None:
            return None
        return str(rows[0]["value"])

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, REGISTRY.get(query_id), **params)
