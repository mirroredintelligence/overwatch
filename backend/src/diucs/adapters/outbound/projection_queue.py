"""The production `ProjectionPublisher`: a request goes onto the projection work queue (TEN-055,
DEC-545, DEC-132 item 4).

The producer is bound to the source tenant when it publishes, and the message is that tenant's: its
`tenant_id` is the source tenant, so the bus refuses it from any other binding (a network binding
included), and the apply consumer reads the same tenant back from the `tenantId` property. The
network the request is for is in the payload, never in a property, and the apply step checks it
against the registry before it binds it.

The message id is derived from what the request says (network, member, grant and its version, kind,
service, source version, allowlist version) and not from the time it was asked: a producer that
runs twice for the same state sends the same id, and the apply step's processed marker drops the
second. The id is a digest, so it holds none of the ids it was made from and always fits the wire.
"""

import hashlib
from typing import Final

from diucs.application.ports.outbound.event_bus import BusMessage, EventBus
from diucs.domain.events import PROJECTION_WORK, ProjectionRequested

ID_PREFIX: Final = "proj-"
DIGEST_LENGTH: Final = 40
_SEPARATOR: Final = "\x1f"


def projection_message_id(request: ProjectionRequested) -> str:
    parts = (
        request.network_id,
        request.source_tenant_id,
        request.grant_id,
        str(request.grant_version),
        request.kind.value,
        request.source_service_id,
        str(request.source_version),
        str(request.allowlist_version),
    )
    digest = hashlib.sha256(_SEPARATOR.join(parts).encode("utf-8")).hexdigest()
    return f"{ID_PREFIX}{digest[:DIGEST_LENGTH]}"


def projection_message(request: ProjectionRequested) -> BusMessage:
    return BusMessage(
        id=projection_message_id(request),
        topic=PROJECTION_WORK,
        event_type=ProjectionRequested.message_type,
        payload=request.to_payload(),
        tenant_id=request.source_tenant_id,
    )


class BusProjectionPublisher:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def publish(self, request: ProjectionRequested) -> None:
        await self._bus.enqueue(PROJECTION_WORK, projection_message(request))
