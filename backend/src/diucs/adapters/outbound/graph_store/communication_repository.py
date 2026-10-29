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
from datetime import UTC, datetime
from typing import Any, Final, Literal

from neo4j import AsyncManagedTransaction
from neo4j.exceptions import ClientError

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
from diucs.application.ports.outbound.messaging import (
    DELIVERY_STATUSES,
    Communication,
    statuses_before,
)
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


def _key(system: str, code: str) -> str:
    return f"Concept{_KEY_SEPARATOR}{system}{_KEY_SEPARATOR}{code}"


_READ = (
    "OPTIONAL MATCH (c)-[:TOPIC]->(topic:Concept {tenantId: $tenant}) "
    "OPTIONAL MATCH (c)-[:MEDIUM]->(medium:Concept {tenantId: $tenant}) "
    "OPTIONAL MATCH (c)-[:RECIPIENT]->(role:PractitionerRole {tenantId: $tenant}) "
    "OPTIONAL MATCH (c)-[:ABOUT]->(subject:HealthcareService {tenantId: $tenant}) "
    "RETURN properties(c) AS props, topic.code AS messageId, medium.code AS channel, "
    "role.id AS recipientRoleId, subject.id AS aboutId"
)

# The scenarios of the statements (TEN-015, DEC-142 item 5, DEC-150). Both tenants get the same
# nodes with the same ids and keys, and each tenant's message text is `Marked`, so a row from the
# other tenant reads differently. The composite keys (tenantId plus the key) let the two share them.
_SENT: Final = datetime(2026, 10, 25, 9, 0, 0, tzinfo=UTC)
_MESSAGE_TEXT: Final = "how many referrals can you take?"
_PROMPT_NODE: Final = SeedNode(
    "prompt",
    ("Resource", "Communication"),
    {
        "id": "comm-1",
        "status": "completed",
        "deliveryStatus": "sent",
        "payloadText": Marked(_MESSAGE_TEXT),
        "sent": _SENT,
        "providerMessageId": "SM-1",
    },
)
_UNLINKED_NODE: Final = SeedNode(
    "unlinked",
    ("Resource", "Communication"),
    {
        "id": "comm-2",
        "status": "completed",
        "deliveryStatus": "sent",
        "payloadText": Marked("a second prompt"),
        "sent": _SENT,
        "providerMessageId": "SM-2",
    },
)
_REPLY_NODE: Final = SeedNode(
    "reply",
    ("Resource", "Communication"),
    {
        "id": "comm-3",
        "status": "completed",
        "deliveryStatus": "received",
        "payloadText": Marked("Y"),
        "received": _SENT,
    },
)
_ROLE_NODE: Final = SeedNode(
    "role",
    ("Resource", "PractitionerRole"),
    {"id": "role-1", "key": "PractitionerRole/role-1", "name": Marked("Duty Manager")},
)
_SERVICE_NODE: Final = SeedNode(
    "service",
    ("Resource", "HealthcareService"),
    {"id": "svc-1", "key": "HealthcareService/svc-1", "name": Marked("UCR West")},
)
_TOPIC_NODE: Final = SeedNode(
    "topic",
    ("Concept",),
    {"key": _key(MESSAGE_SYSTEM, "C1"), "system": MESSAGE_SYSTEM, "code": "C1"},
)
_MEDIUM_NODE: Final = SeedNode(
    "medium",
    ("Concept",),
    {"key": _key(CHANNEL_SYSTEM, "text"), "system": CHANNEL_SYSTEM, "code": "text"},
)
_TOPIC_EDGE: Final = SeedRel("prompt", "TOPIC", "topic")
_MEDIUM_EDGE: Final = SeedRel("prompt", "MEDIUM", "medium")
_RECIPIENT_EDGE: Final = SeedRel("prompt", "RECIPIENT", "role")
_ABOUT_EDGE: Final = SeedRel("prompt", "ABOUT", "service")
_PROMPT_SEED: Final = TenantSeed(
    nodes=(_ROLE_NODE, _SERVICE_NODE, _TOPIC_NODE, _MEDIUM_NODE, _PROMPT_NODE),
    rels=(_TOPIC_EDGE, _MEDIUM_EDGE, _RECIPIENT_EDGE, _ABOUT_EDGE),
)
# The latest prompt scenario: both tenants send at the same time, so the order is decided by the id.
# The id is `Marked`, so it is `-B` for tenant B, and `ORDER BY c.id DESC` puts tenant B's prompt
# first when the statement is not scoped: the leak then shows in the rows (TEN-015).
_LATEST_PROMPT_NODE: Final = SeedNode(
    "prompt",
    ("Resource", "Communication"),
    {
        "id": Marked("comm-latest"),
        "status": "completed",
        "deliveryStatus": "sent",
        "payloadText": Marked(_MESSAGE_TEXT),
        "sent": _SENT,
        "providerMessageId": "SM-1",
    },
)
_LATEST_SEED: Final = TenantSeed(
    nodes=(_ROLE_NODE, _SERVICE_NODE, _TOPIC_NODE, _MEDIUM_NODE, _LATEST_PROMPT_NODE),
    rels=(_TOPIC_EDGE, _MEDIUM_EDGE, _RECIPIENT_EDGE, _ABOUT_EDGE),
)
_QUEUED_NODE: Final = SeedNode(
    "prompt",
    ("Resource", "Communication"),
    {
        "id": "comm-queued",
        "status": "in-progress",
        "deliveryStatus": "queued",
        "payloadText": Marked("a queued prompt"),
        "sent": _SENT,
    },
)
_QUEUED_SEED: Final = TenantSeed(
    nodes=(_ROLE_NODE, _SERVICE_NODE, _TOPIC_NODE, _MEDIUM_NODE, _QUEUED_NODE),
    rels=(_TOPIC_EDGE, _MEDIUM_EDGE, _RECIPIENT_EDGE, _ABOUT_EDGE),
)
_ROW_OF_LATEST: Final[dict[str, Any]] = {
    "messageId": "C1",
    "channel": "text",
    "recipientRoleId": "role-1",
    "aboutId": "svc-1",
    "props": {
        "id": Marked("comm-latest"),
        "payloadText": Marked(_MESSAGE_TEXT),
        "deliveryStatus": "sent",
    },
}
_ROW_OF_PROMPT: Final[dict[str, Any]] = {
    "messageId": "C1",
    "channel": "text",
    "recipientRoleId": "role-1",
    "aboutId": "svc-1",
    "props": {"id": "comm-1", "payloadText": Marked(_MESSAGE_TEXT), "deliveryStatus": "sent"},
}
_PROVIDER_ID: Final = "SM-1"


def _scenario(
    description: str,
    seed: TenantSeed,
    params: dict[str, Any],
    *,
    lookup: tuple[str, ...] = (),
    new: tuple[str, ...] = (),
    expect: Expect | None = None,
) -> Scenario:
    return Scenario(
        description, seed=seed, params=params, lookup=lookup, new=new, expect=expect or Expect()
    )


_ADD_SEED: Final = TenantSeed(
    nodes=(_ROLE_NODE, _SERVICE_NODE, _TOPIC_NODE),
)
_LINK_SEED: Final = TenantSeed(
    nodes=(_ROLE_NODE, _SERVICE_NODE, _TOPIC_NODE, _MEDIUM_NODE, _UNLINKED_NODE),
    rels=(
        SeedRel("unlinked", "TOPIC", "topic"),
        SeedRel("unlinked", "MEDIUM", "medium"),
    ),
)
_REPLY_SEED: Final = TenantSeed(
    nodes=(_ROLE_NODE, _SERVICE_NODE, _TOPIC_NODE, _MEDIUM_NODE, _PROMPT_NODE, _REPLY_NODE),
    rels=(_TOPIC_EDGE, _MEDIUM_EDGE, _RECIPIENT_EDGE, _ABOUT_EDGE),
)

_SCENARIOS: Final[dict[str, Scenario]] = {
    "Q-COMM-ADD": _scenario(
        "store a new prompt whose topic is held and whose channel is not",
        _ADD_SEED,
        {
            "id": "comm-new",
            "status": "in-progress",
            "deliveryStatus": "queued",
            "payloadText": "a new prompt",
            "sent": _SENT,
            "received": None,
            "providerMessageId": None,
            "inResponseTo": None,
            "topicKey": _key(MESSAGE_SYSTEM, "C1"),
            "messageSystem": MESSAGE_SYSTEM,
            "messageId": "C1",
            "mediumKey": _key(CHANNEL_SYSTEM, "text"),
            "channelSystem": CHANNEL_SYSTEM,
            "channel": "text",
        },
        new=(
            "id",
            "status",
            "deliveryStatus",
            "payloadText",
            "mediumKey",
            "channelSystem",
            "channel",
        ),
        expect=Expect(
            rows=({"written": 1},),
            nodes={"Resource": 1, "Communication": 1, "Concept": 1},
            rels={"TOPIC": 1, "MEDIUM": 1},
            after=(NodeSpec(("Communication",), {"id": "comm-new", "deliveryStatus": "queued"}),),
        ),
    ),
    "Q-COMM-LINK-RECIPIENT": _scenario(
        "link an unlinked communication to the role that holds the phone",
        _LINK_SEED,
        {"id": "comm-2", "key": "PractitionerRole/role-1", "targetId": "role-1"},
        lookup=("id",),
        expect=Expect(rows=({"linked": 1},), rels={"RECIPIENT": 1}),
    ),
    "Q-COMM-LINK-ABOUT": _scenario(
        "link an unlinked communication to the service it is about",
        _LINK_SEED,
        {"id": "comm-2", "key": "HealthcareService/svc-1", "targetId": "svc-1"},
        lookup=("id",),
        expect=Expect(rows=({"linked": 1},), rels={"ABOUT": 1}),
    ),
    "Q-COMM-LINK-REPLY": _scenario(
        "link a reply to the prompt it answers",
        _REPLY_SEED,
        {"id": "comm-3", "inResponseTo": "comm-1"},
        lookup=("id", "inResponseTo"),
        expect=Expect(rows=({"linked": 1},), rels={"IN_RESPONSE_TO": 1}),
    ),
    "Q-COMM-EXISTS": _scenario(
        "count the communication by its id",
        _PROMPT_SEED,
        {"id": "comm-1"},
        lookup=("id",),
        expect=Expect(rows=({"found": 1},)),
    ),
    "Q-COMM-GET": _scenario(
        "read a communication with its topic, channel, role and service",
        _PROMPT_SEED,
        {"id": "comm-1"},
        lookup=("id",),
        expect=Expect(rows=(_ROW_OF_PROMPT,)),
    ),
    "Q-COMM-BY-PROVIDER": _scenario(
        "read a communication by its provider message id",
        _PROMPT_SEED,
        {"providerMessageId": _PROVIDER_ID},
        lookup=("providerMessageId",),
        expect=Expect(rows=(_ROW_OF_PROMPT,)),
    ),
    "Q-COMM-SET-STATUS": _scenario(
        "move a sent communication to delivered by its provider message id",
        _PROMPT_SEED,
        {
            "providerMessageId": _PROVIDER_ID,
            "status": "delivered",
            "fhirStatus": "completed",
            "movesFrom": ["queued", "sent"],
        },
        lookup=("providerMessageId",),
        new=("status", "movesFrom"),
        expect=Expect(
            rows=({"updated": 1},),
            after=(
                NodeSpec(
                    ("Communication",),
                    {"providerMessageId": _PROVIDER_ID, "deliveryStatus": "delivered"},
                ),
            ),
        ),
    ),
    "Q-COMM-RECORD-OUTCOME": _scenario(
        "record that a queued communication was sent, with its provider id",
        _QUEUED_SEED,
        {
            "id": "comm-queued",
            "status": "sent",
            "fhirStatus": "completed",
            "providerMessageId": "SM-9",
            "errorCode": None,
        },
        lookup=("id",),
        new=("status", "fhirStatus", "providerMessageId", "errorCode"),
        expect=Expect(
            rows=({"recorded": 1},),
            after=(
                NodeSpec(
                    ("Communication",),
                    {
                        "id": "comm-queued",
                        "deliveryStatus": "sent",
                        "providerMessageId": "SM-9",
                    },
                ),
            ),
        ),
    ),
    "Q-COMM-LATEST-PROMPT": _scenario(
        "find the latest prompt sent to a role for a message id",
        _LATEST_SEED,
        {
            "roleIds": ["role-1"],
            "messageIds": ["C1"],
            "messageSystem": MESSAGE_SYSTEM,
        },
        expect=Expect(rows=(_ROW_OF_LATEST,)),
    ),
}

_QUERIES: dict[str, tuple[str, Literal["read", "write"]]] = {
    "Q-COMM-ADD": (
        "MERGE (topic:Concept {key: $topicKey, tenantId: $tenant}) "
        "ON CREATE SET topic.system = $messageSystem, topic.code = $messageId "
        "MERGE (medium:Concept {key: $mediumKey, tenantId: $tenant}) "
        "ON CREATE SET medium.system = $channelSystem, medium.code = $channel "
        "CREATE (c:Resource:Communication {id: $id, tenantId: $tenant, status: $status, "
        "deliveryStatus: $deliveryStatus, payloadText: $payloadText, sent: $sent, "
        "received: $received, providerMessageId: $providerMessageId, "
        "inResponseTo: $inResponseTo}) "
        "CREATE (c)-[:TOPIC]->(topic) CREATE (c)-[:MEDIUM]->(medium) "
        "RETURN count(c) AS written",
        "write",
    ),
    "Q-COMM-LINK-RECIPIENT": (
        "MATCH (c:Communication {id: $id, tenantId: $tenant}) "
        "MERGE (r:Resource:PractitionerRole {key: $key, tenantId: $tenant}) "
        "ON CREATE SET r.id = $targetId, r.placeholder = true "
        "CREATE (c)-[:RECIPIENT]->(r) RETURN count(r) AS linked",
        "write",
    ),
    "Q-COMM-LINK-ABOUT": (
        "MATCH (c:Communication {id: $id, tenantId: $tenant}) "
        "MERGE (s:Resource:HealthcareService {key: $key, tenantId: $tenant}) "
        "ON CREATE SET s.id = $targetId, s.placeholder = true "
        "CREATE (c)-[:ABOUT]->(s) RETURN count(s) AS linked",
        "write",
    ),
    "Q-COMM-LINK-REPLY": (
        "MATCH (c:Communication {id: $id, tenantId: $tenant}) "
        "MATCH (p:Communication {id: $inResponseTo, tenantId: $tenant}) "
        "CREATE (c)-[:IN_RESPONSE_TO]->(p) RETURN count(p) AS linked",
        "write",
    ),
    "Q-COMM-EXISTS": (
        "MATCH (c:Communication {id: $id, tenantId: $tenant}) RETURN count(c) AS found",
        "read",
    ),
    "Q-COMM-GET": ("MATCH (c:Communication {id: $id, tenantId: $tenant}) " + _READ, "read"),
    # No LIMIT: a provider id is unique within a tenant, so one row comes back. A LIMIT with no
    # order would hide another tenant's row from the generated test (TEN-015), so it is not used.
    "Q-COMM-BY-PROVIDER": (
        "MATCH (c:Communication {providerMessageId: $providerMessageId, tenantId: $tenant}) "
        + _READ,
        "read",
    ),
    # The id is set to itself first: that takes the record's write lock, and the status is read
    # after it (lesson L73), so a receipt that waited for another sees the status the other left
    # and not the one it read before the lock. The id never changes, so the self-SET is safe (L142).
    "Q-COMM-SET-STATUS": (
        "MATCH (c:Communication {providerMessageId: $providerMessageId, tenantId: $tenant}) "
        "SET c.id = c.id "
        "WITH c WHERE c.deliveryStatus IN $movesFrom "
        "SET c.deliveryStatus = $status, c.status = $fhirStatus "
        "RETURN count(c) AS updated",
        "write",
    ),
    # The id is set to itself first, which takes the record's write lock (lesson L73). The state is
    # read after the lock: only a queued communication with no provider id moves (I10).
    "Q-COMM-RECORD-OUTCOME": (
        "MATCH (c:Communication {id: $id, tenantId: $tenant}) "
        "SET c.id = c.id "
        "WITH c WHERE c.deliveryStatus = 'queued' AND c.providerMessageId IS NULL "
        "SET c.deliveryStatus = $status, c.status = $fhirStatus, "
        "c.providerMessageId = $providerMessageId, c.errorCode = $errorCode "
        "RETURN count(c) AS recorded",
        "write",
    ),
    "Q-COMM-LATEST-PROMPT": (
        "MATCH (c:Communication {tenantId: $tenant})-[:TOPIC]->(t:Concept {tenantId: $tenant}) "
        "WHERE t.system = $messageSystem AND t.code IN $messageIds "
        "AND c.deliveryStatus <> 'received' "
        "MATCH (c)-[:RECIPIENT]->(role:PractitionerRole {tenantId: $tenant}) "
        "WHERE role.id IN $roleIds "
        "WITH c ORDER BY c.sent DESC, c.id DESC LIMIT 1 " + _READ,
        "read",
    ),
}

for _query_id, (_cypher, _mode) in _QUERIES.items():
    REGISTRY.register(
        NamedQuery(
            id=_query_id,
            cypher=_cypher,
            mode=_mode,
            scenario=_SCENARIOS[_query_id],
        )
    )


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
            "Q-COMM-SET-STATUS",
            providerMessageId=provider_message_id,
            status=status,
            fhirStatus=_FHIR_STATUS[status],
            movesFrom=list(statuses_before(status)),
        )
        return int(rows[0]["updated"]) > 0

    async def record_send_outcome(
        self,
        communication_id: str,
        *,
        status: str,
        provider_message_id: str | None,
        error_code: str | None,
    ) -> bool:
        if status not in ("sent", "failed"):
            raise ValidationFailed("deliveryStatus", "a send records sent or failed")
        rows = await self._run(
            "Q-COMM-RECORD-OUTCOME",
            id=communication_id,
            status=status,
            fhirStatus=_FHIR_STATUS[status],
            providerMessageId=provider_message_id,
            errorCode=error_code,
        )
        return int(rows[0]["recorded"]) > 0

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
