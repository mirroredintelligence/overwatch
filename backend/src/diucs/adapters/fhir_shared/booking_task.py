"""The FHIR form of a booking Task (P02, R09): the pure mapping used by the Neo4j booking
repository and the booking routes. No I/O. The status mapping is D13's (`to_fhir`)."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from diucs.domain.codes import BASE_URL, BookingStatus, Coding, code_system_url, coding_for
from diucs.domain.model.booking import Booking
from diucs.domain.rules.booking_state import from_fhir, to_fhir

BOOKING_REFERENCE_SYSTEM: Final = f"{BASE_URL}booking-reference"

_OUTPUT_TYPE_SYSTEM: Final = code_system_url("booking-output-type")

_TASK: Final = "Task"

_INTENT: Final = "order"

_DECISION: Final = "decision"

_REASON: Final = "reason"

_CONFIRMED_AT: Final = "confirmed-at"

_PHONE_PROMPT_AT: Final = "phone-prompt-at"

_REQUEST_MESSAGE: Final = "request-message"

_ACKNOWLEDGED_AT: Final = "acknowledged-at"

_ACKNOWLEDGED_BY: Final = "acknowledged-by"

_REQUEST_DELIVERY: Final = "request-delivery"
"""Read-time only: the delivery state of the request message is the message's, not stored on the
booking, so it is added when a booking is read and never written (H-494)."""


def codeable_to_fhir(member: StrEnum) -> dict[str, Any]:
    """A CodeableConcept with one coding for a local code (the coding's system comes from its enum
    class)."""
    coding: Coding = coding_for(member)
    return {"coding": [{"system": coding.system, "code": coding.code, "display": coding.display}]}


def _iso(value: datetime) -> str:
    """UTC, with Z. Microseconds are kept only when present."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _output_type(code: str) -> dict[str, Any]:
    return {"coding": [{"system": _OUTPUT_TYPE_SYSTEM, "code": code}]}


def _output_entries(booking: Booking, delivery_status: str | None = None) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if booking.status is not BookingStatus.REQUESTED:
        entries.append(
            {
                "type": _output_type(_DECISION),
                "valueCodeableConcept": codeable_to_fhir(booking.status),
            }
        )
    if booking.reason is not None:
        entries.append({"type": _output_type(_REASON), "valueString": booking.reason})
    if booking.confirmed_at is not None:
        entries.append(
            {"type": _output_type(_CONFIRMED_AT), "valueDateTime": _iso(booking.confirmed_at)}
        )
    if booking.phone_prompt_at is not None:
        entries.append(
            {"type": _output_type(_PHONE_PROMPT_AT), "valueDateTime": _iso(booking.phone_prompt_at)}
        )
    if booking.request_message_id is not None:
        entries.append(
            {"type": _output_type(_REQUEST_MESSAGE), "valueString": booking.request_message_id}
        )
    if booking.acknowledged_at is not None and booking.acknowledged_by is not None:
        entries.append(
            {
                "type": _output_type(_ACKNOWLEDGED_AT),
                "valueDateTime": _iso(booking.acknowledged_at),
            }
        )
        entries.append(
            {"type": _output_type(_ACKNOWLEDGED_BY), "valueString": booking.acknowledged_by}
        )
    if delivery_status is not None:
        entries.append({"type": _output_type(_REQUEST_DELIVERY), "valueString": delivery_status})
    return entries


def booking_to_fhir(booking: Booking, *, delivery_status: str | None = None) -> dict[str, Any]:
    """The Task for a booking. No meta: the store sets it. `delivery_status` is the state of the
    request message at the time of a read; it is an output of the answer and is never stored."""
    task = to_fhir(booking.status)
    status = from_fhir(task.business_status)
    resource: dict[str, Any] = {
        "resourceType": _TASK,
        "id": booking.id,
        "status": task.status,
        "businessStatus": codeable_to_fhir(status),
        "intent": _INTENT,
        "authoredOn": _iso(booking.requested_at),
        "lastModified": _iso(booking.responded_at or booking.requested_at),
        "identifier": [{"system": BOOKING_REFERENCE_SYSTEM, "value": booking.reference}],
        "restriction": {"period": {"end": _iso(booking.reply_by)}},
        "focus": {"reference": f"ServiceRequest/{booking.case_id}"},
        "owner": {"reference": f"HealthcareService/{booking.service_id}"},
        "requester": {"reference": f"Practitioner/{booking.requester_id}"},
    }
    period: dict[str, Any] = {"start": _iso(booking.requested_at)}
    if booking.responded_at is not None:
        period["end"] = _iso(booking.responded_at)
    resource["executionPeriod"] = period
    if task.status_reason is not None:
        resource["statusReason"] = codeable_to_fhir(from_fhir(task.status_reason))
    entries = _output_entries(booking, delivery_status)
    if entries:
        resource["output"] = entries
    return resource
