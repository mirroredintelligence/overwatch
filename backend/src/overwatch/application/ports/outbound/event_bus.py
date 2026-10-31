"""Outbound port: the message bus and its scheduler, and the ScheduledWork records (P08).

Topic and queue names are the ones in docs/spec/architecture.md. The Azure Service Bus adapter
(I02) and the in-memory fake with a manual clock (adapters/testing/memory_event_bus.py) both
implement EventBus. A use case never calls schedule or cancel: it writes a ScheduledWork row, and
the outbox relay (I03) makes the bus call.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

from diucs.application.tenancy import ScopeKind, current_scope_or_none, is_valid_tenant_id
from diucs.application.work import ScheduledWork, WorkKind
from diucs.domain.errors import DomainError, ValidationFailed

# `projection.work` carries `ProjectionRequested` from a tenant's producer to the network's apply
# step (TEN-055). The name is `domain.events.PROJECTION_WORK`; a test pins that they are equal.
QUEUES: frozenset[str] = frozenset(
    {"inbound.replies", "inbound.receipts", "scheduled.work", "projection.work"}
)
TOPICS: frozenset[str] = frozenset(
    {
        "capacity.events",
        "booking.events",
        "registration.events",
        "criteria.events",
        "alerts.events",
        "network.events",
        "messages.outbound",
        "codes.dispatch",
    }
)


# ---------------------------------------------------------------- the tenant on the wire (TEN-020)
#
# Every message carries the tenant it belongs to as the application property `tenantId`, and its
# message id and session id are qualified with it (`<tenant>:<local id>`). The local values are what
# `BusMessage` holds; only the wire form is qualified. One pure function, `from_wire`, turns a
# received message back into a `BusMessage`, and it is the only reader of the tenant: a consumer
# binds what it returns before it opens a unit of work. Nothing from the body ever reaches a
# property, and no refusal repeats what it was given.

TENANT_PROPERTY: Final = "tenantId"
# A tenant id holds no colon, so the first colon splits a wire id exactly; a local id may hold more.
TENANT_SEPARATOR: Final = ":"
# Service Bus limits a message id and a session id to 128 characters.
MAX_WIRE_ID_LENGTH: Final = 128

REASON_TENANT_MISSING: Final = "tenant-missing"
REASON_TENANT_MALFORMED: Final = "tenant-malformed"
REASON_TENANT_MISMATCH: Final = "tenant-mismatch"
TENANT_REJECTION_REASONS: Final = (
    REASON_TENANT_MISSING,
    REASON_TENANT_MALFORMED,
    REASON_TENANT_MISMATCH,
)

# Keys a body may not carry at its top level: the tenant (a second, forgeable source), and a live
# link or token (it must be sealed before it reaches the bus: a dead letter holds the body).
_TENANT_BODY_KEYS: Final = frozenset({"tenantId", "tenant_id", "tenant"})
_LINK_BODY_KEYS: Final = frozenset({"link", "link_token", "token", "url"})

_TENANT_PAYLOAD_MESSAGE: Final = "must not carry the tenant"
_LINK_PAYLOAD_MESSAGE: Final = "must not carry a link or a token: seal it"
_BOUND_TENANT_MESSAGE: Final = "does not match the bound tenant"
_WIRE_LENGTH_MESSAGE: Final = "is too long for the bus once qualified with the tenant"


class MessageTenantError(DomainError):
    """A received message has no usable tenant. The message is the reason, a fixed word that holds
    no tenant, id or payload text; a consumer dead-letters with it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class BusMessage:
    id: str
    topic: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    # The tenant the message belongs to (DEC-130 item 7), required. The adapter sends it as the
    # Service Bus application property `tenantId`; a consumer binds it before it opens a unit of
    # work. It is never part of the payload.
    tenant_id: str = field(kw_only=True)
    # The W3C trace context of the span that sent the message (O01). The publisher stamps it; the
    # adapter sends it as the `traceparent` application property; a consumer opens its span under
    # it. None when there is no trace.
    traceparent: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, str) or not is_valid_tenant_id(self.tenant_id):
            raise ValidationFailed("tenant_id", "is not a valid tenant id")
        if not isinstance(self.id, str) or not self.id:
            raise ValidationFailed("id", "must not be empty")
        if self.session_id is not None and (
            not isinstance(self.session_id, str) or not self.session_id
        ):
            raise ValidationFailed("session_id", "must be absent or not empty")
        if _TENANT_BODY_KEYS & self.payload.keys():
            raise ValidationFailed("payload", _TENANT_PAYLOAD_MESSAGE)


@dataclass(frozen=True, slots=True)
class WireView:
    """What goes on the wire for a message, with no SDK type: the qualified ids, the subject and
    the application properties. Both bus implementations build it with `to_wire`."""

    message_id: str
    session_id: str | None
    subject: str
    application_properties: Mapping[str, str]


def _qualified(tenant_id: str, local: str, field_name: str) -> str:
    wire = f"{tenant_id}{TENANT_SEPARATOR}{local}"
    if len(wire) > MAX_WIRE_ID_LENGTH:
        raise ValidationFailed(field_name, _WIRE_LENGTH_MESSAGE)
    return wire


def to_wire(message: BusMessage) -> WireView:
    """The wire form of a message. The properties are exactly the event type, the tenant, a text
    channel and a trace context; no other value of the payload ever becomes a property."""
    properties: dict[str, str] = {
        "event_type": message.event_type,
        TENANT_PROPERTY: message.tenant_id,
    }
    channel = message.payload.get("channel")
    if isinstance(channel, str):
        properties["channel"] = channel
    if message.traceparent is not None:
        properties["traceparent"] = message.traceparent
    return WireView(
        message_id=_qualified(message.tenant_id, message.id, "id"),
        session_id=(
            None
            if message.session_id is None
            else _qualified(message.tenant_id, message.session_id, "session_id")
        ),
        subject=message.event_type,
        application_properties=properties,
    )


def _text(value: object) -> str | None:
    """Text, or bytes read as strict UTF-8; anything else (or bytes that are not text) is None."""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return None


def _tenant_of(properties: Mapping[str | bytes, object] | None) -> str:
    """The tenant property, read as the one source of the tenant. Raises MessageTenantError."""
    found: list[object] = []
    for key, value in (properties or {}).items():
        if _text(key) == TENANT_PROPERTY:
            found.append(value)
    if not found:
        raise MessageTenantError(REASON_TENANT_MISSING)
    if len(found) > 1:
        raise MessageTenantError(REASON_TENANT_MALFORMED)
    (value,) = found
    if value is None or value == "" or value == b"":
        raise MessageTenantError(REASON_TENANT_MISSING)
    text = _text(value)
    if text is None or not is_valid_tenant_id(text):
        raise MessageTenantError(REASON_TENANT_MALFORMED)
    return text


def _local_part(wire: object, tenant: str) -> str:
    """The part after the first colon, when the part before it is the tenant and the part after it
    is not empty; otherwise a mismatch."""
    text = _text(wire)
    if text is None:
        raise MessageTenantError(REASON_TENANT_MISMATCH)
    head, separator, tail = text.partition(TENANT_SEPARATOR)
    if not separator or head != tenant or not tail:
        raise MessageTenantError(REASON_TENANT_MISMATCH)
    return tail


def from_wire(
    topic: str,
    *,
    message_id: str | None,
    session_id: str | None,
    subject: str | None,
    properties: Mapping[str | bytes, object] | None,
    payload: object,
) -> BusMessage:
    """The message a received wire view holds. The tenant comes from the `tenantId` property only,
    and the message id (and the session id, when there is one) must be qualified with that same
    tenant: a message whose ids name another tenant is a mismatch. Raises `MessageTenantError`
    (`tenant-missing`, `tenant-malformed`, `tenant-mismatch`) or `ValidationFailed` for what is
    wrong with the rest; never repeats what it was given."""
    tenant = _tenant_of(properties)
    local_id = _local_part(message_id, tenant)
    local_session: str | None = None
    if session_id is not None and _text(session_id) != "":
        local_session = _local_part(session_id, tenant)
    event_type = _text(subject) or _event_type_property(properties)
    if not event_type:
        raise ValidationFailed("event_type", "is missing")
    if not isinstance(payload, dict):
        raise ValidationFailed("payload", "must be an object")
    return BusMessage(
        id=local_id,
        topic=topic,
        event_type=event_type,
        payload=payload,
        session_id=local_session,
        tenant_id=tenant,
    )


def _event_type_property(properties: Mapping[str | bytes, object] | None) -> str | None:
    for key, value in (properties or {}).items():
        if _text(key) == "event_type":
            return _text(value)
    return None


def check_publishable(message: BusMessage) -> None:
    """Refuse what no bus may send: a message for another tenant than the one bound (a network
    scope is refused too: a tenant message is never sent from a network binding), and a body that
    carries a live link or token. With nothing bound, the message's own tenant is the declaration:
    the loops that carry the tenant on each message (the outbox relay) call with nothing bound."""
    scope = current_scope_or_none()
    if scope is not None and (
        scope.kind is not ScopeKind.TENANT or scope.value != message.tenant_id
    ):
        raise ValidationFailed("tenant_id", _BOUND_TENANT_MESSAGE)
    if _LINK_BODY_KEYS & message.payload.keys():
        raise ValidationFailed("payload", _LINK_PAYLOAD_MESSAGE)


class EventBus(Protocol):
    async def publish(self, message: BusMessage) -> None:
        """Send to a topic. Refuses an unknown topic (ValidationFailed)."""
        ...

    async def enqueue(self, queue: str, message: BusMessage) -> None:
        """Send to a queue now, so it can be received at once (I07). Refuses a name that is not
        a queue (ValidationFailed): a topic takes publish, a later time takes schedule."""
        ...

    async def schedule(self, queue: str, message: BusMessage, enqueue_at: datetime) -> int:
        """Enqueue at a UTC instant and return the sequence number. Refuses an unknown queue."""
        ...

    async def cancel(self, queue: str, sequence_number: int) -> None:
        """Cancel a scheduled message. An unknown or already delivered number does nothing."""
        ...


class ScheduledWorkRepository(Protocol):
    async def add(self, work: ScheduledWork) -> None: ...

    async def get(self, id: str) -> ScheduledWork: ...

    async def for_about(
        self, about_id: str, kind: WorkKind | None = None
    ) -> list[ScheduledWork]: ...

    async def save(self, work: ScheduledWork) -> None: ...
