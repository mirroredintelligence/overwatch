"""Neo4j communication records (P07, DEC-056): one node per message sent or received.

Layout. (:Resource:Communication {id, status, deliveryStatus, payloadText, sent, received,
providerMessageId, inResponseTo}) with -[:TOPIC]-> a catalogue Concept (message-id system),
-[:MEDIUM]-> a channel Concept, -[:RECIPIENT]-> a PractitionerRole, -[:ABOUT]-> a HealthcareService
and -[:IN_RESPONSE_TO]-> the prompt it answers. Outbound records have `sent`; inbound records
(deliveryStatus 'received') have `received`, so `sent` is absent. Nothing is stored as JSON
(DEC-001). The repository writes its own nodes with named queries: a communication is not a FHIR
resource, its delivery status changes in place, and ResourceStore would version every change.

Shared Concept nodes use the mapper's key (`Concept|<system>|<code>`), so the G05 store and this
repository never create two nodes for one code. Recipient and subject placeholders follow the
G05 convention (a Resource node with placeholder=true, created only when it does not exist).
"""

from collections.abc import Collection
from datetime import UTC
from typing import Any, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ClientError

from diucs.adapters.outbound.graph_store.driver import run_query
from diucs.adapters.outbound.graph_store.queries import REGISTRY, NamedQuery
from diucs.application.ports.outbound.messaging import DELIVERY_STATUSES, Communication
from diucs.domain.codes import BASE_URL, Channel
from diucs.domain.errors import Conflict, NotFound, ValidationFailed

MESSAGE_SYSTEM = f"{BASE_URL}CodeSystem/message-id"
CHANNEL_SYSTEM = f"{BASE_URL}CodeSystem/channel"
_KEY_SEPARATOR = "|"

# FHIR Communication.status for each delivery status. An inbound message is complete when stored.
_FHIR_STATUS = {
    "queued": "in-progress",
    "sent": "completed",
    "delivered": "completed",
    "failed": "not-done",
    "received": "completed",
    # The text of a grouped prompt went out in another service's message (U04, DEC-156 item 8).
    "grouped": "completed",
}

_READ = (
    "OPTIONAL MATCH (c)-[:TOPIC]->(topic:Concept) "
    "OPTIONAL MATCH (c)-[:MEDIUM]->(medium:Concept) "
    "OPTIONAL MATCH (c)-[:RECIPIENT]->(role:PractitionerRole) "
    "OPTIONAL MATCH (c)-[:ABOUT]->(subject:HealthcareService) "
    "RETURN properties(c) AS props, topic.code AS messageId, medium.code AS channel, "
    "role.id AS recipientRoleId, subject.id AS aboutId"
)

_QUERIES: dict[str, tuple[str, Literal["read", "write"]]] = {
    "Q-COMM-ADD": (
        "MERGE (topic:Concept {key: $topicKey}) "
        "ON CREATE SET topic.system = $messageSystem, topic.code = $messageId "
        "MERGE (medium:Concept {key: $mediumKey}) "
        "ON CREATE SET medium.system = $channelSystem, medium.code = $channel "
        "CREATE (c:Resource:Communication {id: $id, status: $status, "
        "deliveryStatus: $deliveryStatus, payloadText: $payloadText, sent: $sent, "
        "received: $received, providerMessageId: $providerMessageId, "
        "inResponseTo: $inResponseTo}) "
        "CREATE (c)-[:TOPIC]->(topic) CREATE (c)-[:MEDIUM]->(medium) "
        "RETURN count(c) AS written",
        "write",
    ),
    "Q-COMM-LINK-RECIPIENT": (
        "MATCH (c:Communication {id: $id}) "
        "MERGE (r:Resource:PractitionerRole {key: $key}) "
        "ON CREATE SET r.id = $targetId, r.placeholder = true "
        "CREATE (c)-[:RECIPIENT]->(r) RETURN count(r) AS linked",
        "write",
    ),
    "Q-COMM-LINK-ABOUT": (
        "MATCH (c:Communication {id: $id}) "
        "MERGE (s:Resource:HealthcareService {key: $key}) "
        "ON CREATE SET s.id = $targetId, s.placeholder = true "
        "CREATE (c)-[:ABOUT]->(s) RETURN count(s) AS linked",
        "write",
    ),
    "Q-COMM-LINK-REPLY": (
        "MATCH (c:Communication {id: $id}) MATCH (p:Communication {id: $inResponseTo}) "
        "CREATE (c)-[:IN_RESPONSE_TO]->(p) RETURN count(p) AS linked",
        "write",
    ),
    "Q-COMM-EXISTS": (
        "MATCH (c:Communication {id: $id}) RETURN count(c) AS found",
        "read",
    ),
    "Q-COMM-GET": ("MATCH (c:Communication {id: $id}) " + _READ, "read"),
    "Q-COMM-BY-PROVIDER": (
        "MATCH (c:Communication {providerMessageId: $providerMessageId}) WITH c LIMIT 1 " + _READ,
        "read",
    ),
    "Q-COMM-SET-STATUS": (
        "MATCH (c:Communication {providerMessageId: $providerMessageId}) "
        "SET c.deliveryStatus = $status RETURN count(c) AS updated",
        "write",
    ),
    "Q-COMM-LATEST-PROMPT": (
        "MATCH (c:Communication)-[:TOPIC]->(t:Concept) "
        "WHERE t.system = $messageSystem AND t.code IN $messageIds "
        "AND c.deliveryStatus <> 'received' "
        "MATCH (c)-[:RECIPIENT]->(role:PractitionerRole) WHERE role.id IN $roleIds "
        "WITH c ORDER BY c.sent DESC, c.id DESC LIMIT 1 " + _READ,
        "read",
    ),
}

for _query_id, (_cypher, _mode) in _QUERIES.items():
    REGISTRY.register(NamedQuery(id=_query_id, cypher=_cypher, mode=_mode))


def _key(system: str, code: str) -> str:
    return f"Concept{_KEY_SEPARATOR}{system}{_KEY_SEPARATOR}{code}"


def _check(communication: Communication) -> None:
    if communication.delivery_status not in DELIVERY_STATUSES:
        raise ValidationFailed("deliveryStatus", "not a delivery status")
    if communication.sent_at.utcoffset() is None:
        raise ValidationFailed("sentAt", "must be timezone-aware")


def _from_row(row: dict[str, Any]) -> Communication:
    props: dict[str, Any] = row["props"]
    stored = props["sent"] if props.get("sent") is not None else props["received"]
    return Communication(
        id=str(props["id"]),
        message_id=str(row["messageId"]),
        channel=Channel(row["channel"]),
        recipient_role_id=row["recipientRoleId"],
        about_id=row["aboutId"],
        payload_text=str(props["payloadText"]),
        sent_at=stored.to_native().astimezone(UTC),
        delivery_status=str(props["deliveryStatus"]),
        provider_message_id=props.get("providerMessageId"),
        in_response_to=props.get("inResponseTo"),
    )


class Neo4jCommunicationRepository:
    def __init__(self, tx: AsyncManagedTransaction) -> None:
        self._tx = tx

    async def add(self, communication: Communication) -> None:
        """Store one communication. Idempotent (DEC-012): a second add of the same record is a
        no-op, and a different record under the same id is refused with Conflict. Every refusal is
        decided before the first write, so a caller that catches the error leaves nothing stored
        (DEC-053 item 16)."""
        _check(communication)
        stored = await self.get(communication.id)
        if stored is not None:
            if stored == communication:
                return
            raise Conflict(f"communication {communication.id} already exists with other content")
        if communication.in_response_to is not None:
            found = await self._run("Q-COMM-EXISTS", id=communication.in_response_to)
            if int(found[0]["found"]) == 0:
                raise NotFound(f"the communication {communication.in_response_to} to reply to")
        inbound = communication.delivery_status == "received"
        sent_at = communication.sent_at.astimezone(UTC)
        try:
            await self._run(
                "Q-COMM-ADD",
                id=communication.id,
                status=_FHIR_STATUS[communication.delivery_status],
                deliveryStatus=communication.delivery_status,
                payloadText=communication.payload_text,
                sent=None if inbound else sent_at,
                received=sent_at if inbound else None,
                providerMessageId=communication.provider_message_id,
                inResponseTo=communication.in_response_to,
                topicKey=_key(MESSAGE_SYSTEM, communication.message_id),
                messageSystem=MESSAGE_SYSTEM,
                messageId=communication.message_id,
                mediumKey=_key(CHANNEL_SYSTEM, communication.channel.value),
                channelSystem=CHANNEL_SYSTEM,
                channel=communication.channel.value,
            )
        except ClientError as error:
            if str(getattr(error, "code", "")).endswith("ConstraintValidationFailed"):
                raise Conflict(f"communication {communication.id} already exists") from error
            raise
        if communication.recipient_role_id is not None:
            role = communication.recipient_role_id
            await self._run(
                "Q-COMM-LINK-RECIPIENT",
                id=communication.id,
                key=f"PractitionerRole/{role}",
                targetId=role,
            )
        if communication.about_id is not None:
            subject = communication.about_id
            await self._run(
                "Q-COMM-LINK-ABOUT",
                id=communication.id,
                key=f"HealthcareService/{subject}",
                targetId=subject,
            )
        if communication.in_response_to is not None:
            await self._run(
                "Q-COMM-LINK-REPLY", id=communication.id, inResponseTo=communication.in_response_to
            )

    async def get(self, communication_id: str) -> Communication | None:
        rows = await self._run("Q-COMM-GET", id=communication_id)
        return _from_row(rows[0]) if rows else None

    async def by_provider_id(self, provider_message_id: str) -> Communication | None:
        rows = await self._run("Q-COMM-BY-PROVIDER", providerMessageId=provider_message_id)
        return _from_row(rows[0]) if rows else None

    async def set_delivery_status(self, provider_message_id: str, status: str) -> bool:
        if status not in DELIVERY_STATUSES:
            raise ValidationFailed("deliveryStatus", "not a delivery status")
        rows = await self._run(
            "Q-COMM-SET-STATUS", providerMessageId=provider_message_id, status=status
        )
        return int(rows[0]["updated"]) > 0

    async def latest_prompt_for_phone(
        self, role_ids: Collection[str], message_ids: Collection[str]
    ) -> Communication | None:
        rows = await self._run(
            "Q-COMM-LATEST-PROMPT",
            roleIds=sorted(role_ids),
            messageIds=sorted(message_ids),
            messageSystem=MESSAGE_SYSTEM,
        )
        return _from_row(rows[0]) if rows else None

    async def _run(self, query_id: str, **params: Any) -> list[dict[str, Any]]:
        return await run_query(self._tx, REGISTRY.get(query_id), **params)
