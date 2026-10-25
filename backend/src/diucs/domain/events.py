"""Domain events the core raises, and how each maps to a Service Bus topic (D25).

Events are frozen data: identifiers, counts and codes, never patient values. The outbox carries
`to_payload()` output; `from_payload()` rebuilds the event on the consuming side. Nothing here
reads the clock: `at` is always passed in.

Topic names come from docs/spec/architecture.md. Session id is the service id for
`capacity.events` (per-service ordering), and None for every other topic.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar, Self

from diucs.domain.codes import (
    AlertKind,
    BookingStatus,
    ReportSource,
    Status,
    parse_code,
)
from diucs.domain.errors import ValidationFailed

CAPACITY_EVENTS = "capacity.events"
BOOKING_EVENTS = "booking.events"
REGISTRATION_EVENTS = "registration.events"
CRITERIA_EVENTS = "criteria.events"
ALERTS_EVENTS = "alerts.events"

_UTC_OFFSET = timedelta(0)


def _require_utc(at: datetime) -> None:
    if at.tzinfo is None or at.utcoffset() != _UTC_OFFSET:
        raise ValidationFailed("at", "must be a timezone-aware UTC datetime")


def _at_text(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _field(payload: Mapping[str, Any], key: str) -> Any:
    if key not in payload:
        raise ValidationFailed(key, "is required")
    return payload[key]


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = _field(payload, key)
    if not isinstance(value, str):
        raise ValidationFailed(key, "must be text")
    return value


def _count(payload: Mapping[str, Any], key: str) -> int:
    value = _field(payload, key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationFailed(key, "must be a whole number")
    return value


def _code[E: StrEnum](payload: Mapping[str, Any], key: str, enum_cls: type[E]) -> E:
    return parse_code(enum_cls, _text(payload, key))


def _optional_code[E: StrEnum](payload: Mapping[str, Any], key: str, enum_cls: type[E]) -> E | None:
    if _field(payload, key) is None:
        return None
    return _code(payload, key, enum_cls)


def _when(payload: Mapping[str, Any]) -> datetime:
    text = _text(payload, "at")
    if not text.endswith("Z"):
        raise ValidationFailed("at", "must be a UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise ValidationFailed("at", "is not an ISO 8601 timestamp") from None


@dataclass(frozen=True, slots=True)
class CapacityReported:
    event_type: ClassVar[str] = "CapacityReported"
    service_id: str
    report_id: str
    value: int
    source: ReportSource
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "report_id": self.report_id,
            "value": self.value,
            "source": self.source.value,
            "at": _at_text(self.at),
        }

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            service_id=_text(payload, "service_id"),
            report_id=_text(payload, "report_id"),
            value=_count(payload, "value"),
            source=_code(payload, "source", ReportSource),
            at=_when(payload),
        )


@dataclass(frozen=True, slots=True)
class StatusChanged:
    event_type: ClassVar[str] = "StatusChanged"
    service_id: str
    before: Status | None
    after: Status
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "before": None if self.before is None else self.before.value,
            "after": self.after.value,
            "at": _at_text(self.at),
        }

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            service_id=_text(payload, "service_id"),
            before=_optional_code(payload, "before", Status),
            after=_code(payload, "after", Status),
            at=_when(payload),
        )


@dataclass(frozen=True, slots=True)
class BookingRequested:
    event_type: ClassVar[str] = "BookingRequested"
    booking_id: str
    service_id: str
    reference: str
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "booking_id": self.booking_id,
            "service_id": self.service_id,
            "reference": self.reference,
            "at": _at_text(self.at),
        }

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            booking_id=_text(payload, "booking_id"),
            service_id=_text(payload, "service_id"),
            reference=_text(payload, "reference"),
            at=_when(payload),
        )


@dataclass(frozen=True, slots=True)
class BookingResponded:
    event_type: ClassVar[str] = "BookingResponded"
    booking_id: str
    service_id: str
    status: BookingStatus
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "booking_id": self.booking_id,
            "service_id": self.service_id,
            "status": self.status.value,
            "at": _at_text(self.at),
        }

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            booking_id=_text(payload, "booking_id"),
            service_id=_text(payload, "service_id"),
            status=_code(payload, "status", BookingStatus),
            at=_when(payload),
        )


@dataclass(frozen=True, slots=True)
class BookingExpired:
    event_type: ClassVar[str] = "BookingExpired"
    booking_id: str
    service_id: str
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "booking_id": self.booking_id,
            "service_id": self.service_id,
            "at": _at_text(self.at),
        }

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            booking_id=_text(payload, "booking_id"),
            service_id=_text(payload, "service_id"),
            at=_when(payload),
        )


@dataclass(frozen=True, slots=True)
class RegistrationSubmitted:
    event_type: ClassVar[str] = "RegistrationSubmitted"
    registration_id: str
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {"registration_id": self.registration_id, "at": _at_text(self.at)}

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(registration_id=_text(payload, "registration_id"), at=_when(payload))


@dataclass(frozen=True, slots=True)
class RegistrationApproved:
    event_type: ClassVar[str] = "RegistrationApproved"
    registration_id: str
    service_id: str
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "registration_id": self.registration_id,
            "service_id": self.service_id,
            "at": _at_text(self.at),
        }

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            registration_id=_text(payload, "registration_id"),
            service_id=_text(payload, "service_id"),
            at=_when(payload),
        )


@dataclass(frozen=True, slots=True)
class CriteriaApproved:
    event_type: ClassVar[str] = "CriteriaApproved"
    criteria_id: str
    service_id: str
    version: int
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "criteria_id": self.criteria_id,
            "service_id": self.service_id,
            "version": self.version,
            "at": _at_text(self.at),
        }

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            criteria_id=_text(payload, "criteria_id"),
            service_id=_text(payload, "service_id"),
            version=_count(payload, "version"),
            at=_when(payload),
        )


@dataclass(frozen=True, slots=True)
class AlertRaised:
    event_type: ClassVar[str] = "AlertRaised"
    alert_id: str
    kind: AlertKind
    service_id: str
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "kind": self.kind.value,
            "service_id": self.service_id,
            "at": _at_text(self.at),
        }

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            alert_id=_text(payload, "alert_id"),
            kind=_code(payload, "kind", AlertKind),
            service_id=_text(payload, "service_id"),
            at=_when(payload),
        )


@dataclass(frozen=True, slots=True)
class AlertAcknowledged:
    event_type: ClassVar[str] = "AlertAcknowledged"
    alert_id: str
    by: str
    at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.at)

    def to_payload(self) -> dict[str, Any]:
        return {"alert_id": self.alert_id, "by": self.by, "at": _at_text(self.at)}

    @classmethod
    def decode(cls, payload: Mapping[str, Any]) -> Self:
        return cls(
            alert_id=_text(payload, "alert_id"),
            by=_text(payload, "by"),
            at=_when(payload),
        )


DomainEvent = (
    CapacityReported
    | StatusChanged
    | BookingRequested
    | BookingResponded
    | BookingExpired
    | RegistrationSubmitted
    | RegistrationApproved
    | CriteriaApproved
    | AlertRaised
    | AlertAcknowledged
)

_TOPIC_BY_CLASS: Mapping[type, str] = MappingProxyType(
    {
        CapacityReported: CAPACITY_EVENTS,
        StatusChanged: CAPACITY_EVENTS,
        BookingRequested: BOOKING_EVENTS,
        BookingResponded: BOOKING_EVENTS,
        BookingExpired: BOOKING_EVENTS,
        RegistrationSubmitted: REGISTRATION_EVENTS,
        RegistrationApproved: REGISTRATION_EVENTS,
        CriteriaApproved: CRITERIA_EVENTS,
        AlertRaised: ALERTS_EVENTS,
        AlertAcknowledged: ALERTS_EVENTS,
    }
)

_DECODER_BY_NAME: Mapping[str, Callable[[Mapping[str, Any]], DomainEvent]] = MappingProxyType(
    {
        "CapacityReported": CapacityReported.decode,
        "StatusChanged": StatusChanged.decode,
        "BookingRequested": BookingRequested.decode,
        "BookingResponded": BookingResponded.decode,
        "BookingExpired": BookingExpired.decode,
        "RegistrationSubmitted": RegistrationSubmitted.decode,
        "RegistrationApproved": RegistrationApproved.decode,
        "CriteriaApproved": CriteriaApproved.decode,
        "AlertRaised": AlertRaised.decode,
        "AlertAcknowledged": AlertAcknowledged.decode,
    }
)


def topic_for(event: DomainEvent) -> str:
    """The Service Bus topic an event is published to."""
    return _TOPIC_BY_CLASS[type(event)]


def session_id_for(event: DomainEvent) -> str | None:
    """The Service Bus session id: the service id on capacity.events, None elsewhere."""
    if isinstance(event, CapacityReported | StatusChanged):
        return event.service_id
    return None


def from_payload(event_type: str, payload: Mapping[str, Any]) -> DomainEvent:
    """Rebuild an event from its type name and payload. Refuses unknown types and bad values."""
    decoder = _DECODER_BY_NAME.get(event_type)
    if decoder is None:
        raise ValidationFailed("event_type", "is not a known domain event")
    return decoder(payload)
